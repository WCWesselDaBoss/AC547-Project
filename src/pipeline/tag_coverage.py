"""Coverage report for the tag map (Phase 1, step 4).

For each line item in tag_map.LINE_ITEMS this reports:
  - what share of 10-K company-years find a value with the current tags,
  - which mapped tag supplied it, and how often a company switches tags
    between consecutive years (a switch can distort year-over-year ratios),
  - candidate tags that would fill the gaps, with evidence: how often the
    candidate's value AGREES with the mapped value when both are reported.

Run with:
    python -m src.pipeline.tag_coverage            # use cached extract
    python -m src.pipeline.tag_coverage --rebuild  # rescan companyfacts.zip

The report is evidence for a human decision. Nothing here changes the map.
"""

import argparse
import json
import re
import zipfile

import pandas as pd

import config
from src.pipeline import derived_items, periods, tag_map

# Prior year is needed to score the first year, so facts start one year
# before the first scored fiscal year.
FIRST_FACT_YEAR = config.FIRST_FISCAL_YEAR - 1

# A fact belongs to a 10-K's company-year only if its end date is within
# this many days of the 10-K's report date. This absorbs 52/53-week
# calendars without pulling in a different fiscal year.
REPORT_DATE_TOLERANCE_DAYS = 7

# Two values "agree" if they differ by at most 0.5%. Exact equality is too
# strict because some filers round differently in different filings.
AGREEMENT_TOLERANCE = 0.005

# How many candidate tags to show per line item.
TOP_CANDIDATES = 8

CANDIDATE_FACTS_PATH = config.INTERIM_DIR / "candidate_facts.parquet"
COVERAGE_LOG = config.LOG_DIR / "tag_coverage.csv"
CANDIDATES_LOG = config.LOG_DIR / "tag_candidates.csv"


def combined_candidate_regex():
    """Return one regex matching any mapped tag or candidate pattern."""
    exact = [f"^{re.escape(tag)}$" for tag in tag_map.all_mapped_tags()]
    patterns = list(tag_map.CANDIDATE_PATTERNS.values()) + list(
        tag_map.SUPPORT_PATTERNS.values()
    )
    return re.compile("|".join(exact + patterns))


def annual_facts_from_company(cik, company_facts, tag_regex):
    """Return a list of annual 10-K fact dicts for one companyfacts JSON.

    Keeps only us-gaap tags matching tag_regex, units USD or shares, forms
    10-K/10-K/A, durations of 350-380 days or instants, and fiscal years
    in range. Fiscal year comes from the period end, never the fy field.

    The CIK is passed in from the file name (the same source the companies
    table uses) because some files in SEC's bulk download are just "{}"
    with no cik field; files without facts simply yield no rows.
    """
    rows = []
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for tag, tag_info in us_gaap.items():
        if not tag_regex.search(tag):
            continue
        for unit in ("USD", "shares"):
            for fact in tag_info["units"].get(unit, []):
                if fact.get("form") not in config.ANNUAL_FORMS:
                    continue
                end = periods.to_date(fact["end"])
                start = periods.to_date(fact.get("start"))
                if start is not None and not periods.is_annual_duration(
                    start, end
                ):
                    continue
                fiscal_year = config.fiscal_year_from_period_end(end)
                if (
                    not FIRST_FACT_YEAR
                    <= fiscal_year
                    <= config.LAST_FISCAL_YEAR
                ):
                    continue
                rows.append(
                    {
                        "cik": cik,
                        "tag": tag,
                        "unit": unit,
                        "period_type": (
                            tag_map.INSTANT
                            if start is None
                            else tag_map.DURATION
                        ),
                        "period_start": start,
                        "period_end": end,
                        "fiscal_year": fiscal_year,
                        "value": float(fact["val"]),
                        "accession": fact["accn"],
                        "filed_date": periods.to_date(fact["filed"]),
                    }
                )
    return rows


def keep_earliest_filed(facts_df):
    """Keep the earliest-filed value for each company, tag and period.

    The same period appears in later 10-Ks as a comparative or restated
    figure; the earliest is what investors saw first (CLAUDE.md section 4).
    """
    period_key = ["cik", "tag", "unit", "period_start", "period_end"]
    return (
        facts_df.sort_values("filed_date", kind="stable")
        .drop_duplicates(subset=period_key, keep="first")
        .reset_index(drop=True)
    )


def extract_candidate_facts(companyfacts_zip, ciks):
    """Scan companyfacts.zip and return candidate annual facts for ciks."""
    tag_regex = combined_candidate_regex()
    rows = []
    with zipfile.ZipFile(companyfacts_zip) as archive:
        for count, cik in enumerate(ciks, start=1):
            company_facts = json.loads(archive.read(f"CIK{cik:010d}.json"))
            rows.extend(
                annual_facts_from_company(cik, company_facts, tag_regex)
            )
            if count % 1000 == 0:
                print(f"  scanned {count:,} of {len(ciks):,} companies")
    return keep_earliest_filed(pd.DataFrame(rows))


def ten_k_company_years(submissions_zip, ciks):
    """Return one row per (cik, fiscal_year) that has an original 10-K.

    This is the coverage denominator: years in which the company filed
    an annual report, so a value SHOULD exist. It uses submissions data,
    not the tags being tested, so it cannot flatter the coverage numbers.
    """
    rows = []
    with zipfile.ZipFile(submissions_zip) as archive:
        for cik in ciks:
            submission = json.loads(archive.read(f"CIK{cik:010d}.json"))
            filings = submission["filings"]
            tables = [filings["recent"]] + [
                json.loads(archive.read(extra["name"]))
                for extra in filings.get("files", [])
            ]
            for table in tables:
                for form, report_date in zip(
                    table["form"], table["reportDate"]
                ):
                    # Amendments do not create a new company-year.
                    if form != "10-K" or not report_date:
                        continue
                    report_date = periods.to_date(report_date)
                    rows.append(
                        {
                            "cik": cik,
                            "fiscal_year": config.fiscal_year_from_period_end(
                                report_date
                            ),
                            "report_date": report_date,
                        }
                    )
    years_df = pd.DataFrame(rows)
    in_range = years_df["fiscal_year"].between(
        config.FIRST_FISCAL_YEAR, config.LAST_FISCAL_YEAR
    )
    # A company that changed fiscal year end can file two 10-Ks labeled
    # with the same fiscal year; keep the earlier report date.
    return (
        years_df[in_range]
        .sort_values("report_date")
        .drop_duplicates(subset=["cik", "fiscal_year"], keep="first")
        .reset_index(drop=True)
    )


def match_facts_to_years(company_years_df, facts_df):
    """Attach facts to the 10-K company-year whose report date they match."""
    merged = facts_df.merge(company_years_df, on=["cik", "fiscal_year"])
    gap_days = (
        pd.to_datetime(merged["period_end"])
        - pd.to_datetime(merged["report_date"])
    ).dt.days.abs()
    return merged[gap_days <= REPORT_DATE_TOLERANCE_DAYS].reset_index(
        drop=True
    )


def facts_for_line_item(matched_df, line_item):
    """Return matched facts with the line item's period type and unit."""
    spec = tag_map.ALL_ITEMS[line_item]
    keep = (matched_df["period_type"] == spec["period"]) & (
        matched_df["unit"] == spec["unit"]
    )
    # One value per company-year and tag (earliest filed).
    return (
        matched_df[keep]
        .sort_values("filed_date", kind="stable")
        .drop_duplicates(subset=["cik", "fiscal_year", "tag"], keep="first")
    )


def winning_values(item_facts_df, line_item):
    """Return one value per company-year using each company's tag order.

    Mirrors tag_map.company_tag_order in vectorized form: for each company
    the mapped tag it reports in the most years wins; ties keep the map
    order; other tags fill only years where the preferred tag is missing.
    """
    map_order = tag_map.ALL_ITEMS[line_item]["tags"]
    tag_rank = {tag: rank for rank, tag in enumerate(map_order)}
    mapped = item_facts_df[item_facts_df["tag"].isin(tag_rank)].copy()
    years_by_tag = (
        mapped.groupby(["cik", "tag"])["fiscal_year"]
        .nunique()
        .rename("years_reported")
        .reset_index()
    )
    mapped = mapped.merge(years_by_tag, on=["cik", "tag"])
    mapped["map_rank"] = mapped["tag"].map(tag_rank)
    return (
        mapped.sort_values(
            ["years_reported", "map_rank"], ascending=[False, True]
        )
        .drop_duplicates(subset=["cik", "fiscal_year"], keep="first")
        .drop(columns=["years_reported", "map_rank"])
    )


def count_tag_switches(winners_df):
    """Count consecutive company-year pairs where the winning tag changed."""
    ordered = winners_df.sort_values(["cik", "fiscal_year"])
    previous = ordered.groupby("cik")[["fiscal_year", "tag"]].shift(1)
    consecutive = ordered["fiscal_year"] - previous["fiscal_year"] == 1
    return int((consecutive & (ordered["tag"] != previous["tag"])).sum())


def coverage_row(company_years_df, winners_df, line_item):
    """Return the coverage summary dict for one line item."""
    total = len(company_years_df)
    found = len(winners_df)
    by_tag = winners_df["tag"].value_counts()
    return {
        "line_item": line_item,
        "company_years": total,
        "found": found,
        "pct_found": round(100 * found / total, 1),
        "tag_switch_pairs": count_tag_switches(winners_df),
        "found_by_tag": "; ".join(f"{tag}={n}" for tag, n in by_tag.items()),
    }


def candidate_rows(company_years_df, item_facts_df, winners_df, line_item):
    """Return evidence rows for unmapped tags that could fill gaps.

    fills_missing: company-years with no mapped value that this tag covers.
    both_reported / agree_pct: where the tag AND a mapped tag both have a
    value, how often they are within 0.5%. High agreement is evidence of
    the same meaning; low agreement means a different concept.
    """
    pattern = re.compile(tag_map.CANDIDATE_PATTERNS[line_item])
    mapped_tags = set(tag_map.ALL_ITEMS[line_item]["tags"])
    candidates = item_facts_df[
        ~item_facts_df["tag"].isin(mapped_tags)
        & item_facts_df["tag"].str.contains(pattern)
    ]
    found_keys = winners_df[["cik", "fiscal_year"]].assign(found=True)
    candidates = candidates.merge(
        found_keys, on=["cik", "fiscal_year"], how="left"
    )
    missing = candidates[candidates["found"].isna()]

    fills = missing.groupby("tag").size().rename("fills_missing")
    both = candidates.merge(
        winners_df[["cik", "fiscal_year", "value"]],
        on=["cik", "fiscal_year"],
        suffixes=("", "_mapped"),
    )
    both["agrees"] = (both["value"] - both["value_mapped"]).abs() <= (
        AGREEMENT_TOLERANCE * both["value_mapped"].abs()
    )
    agreement = both.groupby("tag")["agrees"].agg(["size", "mean"])
    agreement.columns = ["both_reported", "agree_share"]

    evidence = pd.concat([fills, agreement], axis=1).fillna(0)
    evidence = evidence.sort_values("fills_missing", ascending=False).head(
        TOP_CANDIDATES
    )
    total = len(company_years_df)
    return [
        {
            "line_item": line_item,
            "candidate_tag": tag,
            "fills_missing": int(row["fills_missing"]),
            "pct_gain": round(100 * row["fills_missing"] / total, 1),
            "both_reported": int(row["both_reported"]),
            "agree_pct": round(100 * row["agree_share"], 1),
        }
        for tag, row in evidence.iterrows()
    ]


def wide_values(winners_by_item, company_years_df):
    """Return one row per company-year and one column per item's value."""
    wide_df = company_years_df[["cik", "fiscal_year"]].copy()
    for item, winners_df in winners_by_item.items():
        wide_df = wide_df.merge(
            winners_df[["cik", "fiscal_year", "value"]].rename(
                columns={"value": item}
            ),
            on=["cik", "fiscal_year"],
            how="left",
        )
    return wide_df


def build_report(company_years_df, facts_df):
    """Return (coverage DataFrame, candidates DataFrame) for every item.

    Coverage shows both the tag-only share and the share after the
    derivations in derived_items.py, so the effect of each is visible.
    """
    matched_df = match_facts_to_years(company_years_df, facts_df)
    coverage, candidates, winners_by_item = [], [], {}
    for item in tag_map.ALL_ITEMS:
        item_facts_df = facts_for_line_item(matched_df, item)
        winners_df = winning_values(item_facts_df, item)
        winners_by_item[item] = winners_df
        if item not in tag_map.LINE_ITEMS:
            continue  # components are inputs, not reported line items
        coverage.append(coverage_row(company_years_df, winners_df, item))
        candidates.extend(
            candidate_rows(company_years_df, item_facts_df, winners_df, item)
        )
    coverage_df = pd.DataFrame(coverage)

    derived_df = derived_items.apply_derivations(
        wide_values(winners_by_item, company_years_df)
    )
    coverage_df["pct_with_derivations"] = [
        round(100 * derived_df[item].notna().mean(), 1)
        for item in coverage_df["line_item"]
    ]
    return coverage_df, pd.DataFrame(candidates)


def main():
    """Build (or load) the candidate extract and write the two reports."""
    parser = argparse.ArgumentParser(description="Tag map coverage report")
    parser.add_argument("--rebuild", action="store_true", help="rescan ZIP")
    args = parser.parse_args()

    companies_df = pd.read_parquet(config.COMPANIES_PATH)
    ciks = companies_df.loc[~companies_df["is_excluded"], "cik"].tolist()

    if args.rebuild or not CANDIDATE_FACTS_PATH.exists():
        print(f"Scanning companyfacts for {len(ciks):,} included companies")
        facts_df = extract_candidate_facts(config.COMPANYFACTS_ZIP, ciks)
        config.INTERIM_DIR.mkdir(parents=True, exist_ok=True)
        facts_df.to_parquet(CANDIDATE_FACTS_PATH, index=False)
    facts_df = pd.read_parquet(CANDIDATE_FACTS_PATH)

    company_years_df = ten_k_company_years(config.SUBMISSIONS_ZIP, ciks)
    coverage_df, candidates_df = build_report(company_years_df, facts_df)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    coverage_df.to_csv(COVERAGE_LOG, index=False)
    candidates_df.to_csv(CANDIDATES_LOG, index=False)
    print(coverage_df.drop(columns="found_by_tag").to_string(index=False))


if __name__ == "__main__":
    main()
