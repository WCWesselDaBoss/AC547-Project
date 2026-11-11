"""Build the facts_long table (CLAUDE.md section 4).

One row per company, line item, period and filing: every 10-K or 10-K/A
that reported the value, so later restatements are kept alongside the
original. The earliest filing for each company, line item and period is
marked is_original; scores use only those values.

Run on its own with:
    python -m src.pipeline.facts
"""

import json
import re
import zipfile
from collections import Counter

import pandas as pd

import config
from src.pipeline import periods, tag_map

# Prior year is needed to score the first year, so facts start one year
# before the first scored fiscal year.
FIRST_FACT_YEAR = config.FIRST_FISCAL_YEAR - 1

# Drop reasons, counted so every removed fact is accounted for (section 6).
DROP_FORM = "form_not_10k"
DROP_UNIT = "unit_not_usd_or_shares"
DROP_NOT_ANNUAL = "duration_not_350_to_380_days"
DROP_YEAR = "fiscal_year_out_of_range"
DROP_WRONG_UNIT_OR_PERIOD = "unit_or_period_type_wrong_for_line_item"
DROP_OTHER_TAG = "company_reported_preferred_tag_for_same_period"
DROP_DUPLICATE = "duplicate_within_same_filing"

# Companies per batch. Each company's facts are processed independently,
# so batching keeps memory flat without changing any result.
BATCH_COMPANIES = 500

FACTS_LONG_DROP_LOG = config.LOG_DIR / "facts_long_drops.csv"

# Column order from the section 4 contract.
FACTS_LONG_COLUMNS = [
    "cik",
    "line_item",
    "xbrl_tag",
    "value",
    "unit",
    "period_start",
    "period_end",
    "fiscal_year",
    "form",
    "accession",
    "filed_date",
    "filing_url",
    "is_original",
]

PERIOD_KEY = ["cik", "line_item", "period_start", "period_end"]


def mapped_tag_regex():
    """Return a regex matching exactly the tags used by any item."""
    tags = sorted(tag_map.all_mapped_tags())
    return re.compile("|".join(f"^{re.escape(tag)}$" for tag in tags))


def annual_facts_from_company(cik, company_facts, tag_regex, drops=None):
    """Return a list of annual 10-K fact dicts for one companyfacts JSON.

    Keeps only us-gaap tags matching tag_regex, units USD or shares, forms
    10-K/10-K/A, durations of 350-380 days or instants, and fiscal years
    in range. Fiscal year comes from the period end, never the fy field,
    because fy describes the filing, not the period (CLAUDE.md section 4).

    The CIK is passed in from the file name (the same source the companies
    table uses) because some files in SEC's bulk download are just "{}"
    with no cik field; files without facts simply yield no rows. If drops
    (a Counter) is given, each removed fact is counted by reason.
    """
    drops = Counter() if drops is None else drops
    rows = []
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for tag, tag_info in us_gaap.items():
        if not tag_regex.search(tag):
            continue
        for unit, unit_facts in tag_info["units"].items():
            if unit not in ("USD", "shares"):
                drops[DROP_UNIT] += len(unit_facts)
                continue
            for fact in unit_facts:
                if fact.get("form") not in config.ANNUAL_FORMS:
                    drops[DROP_FORM] += 1
                    continue
                end = periods.to_date(fact["end"])
                start = periods.to_date(fact.get("start"))
                # Quarterly and year-to-date values also appear in 10-Ks;
                # they would be mistaken for annual totals.
                if start is not None and not periods.is_annual_duration(
                    start, end
                ):
                    drops[DROP_NOT_ANNUAL] += 1
                    continue
                fiscal_year = config.fiscal_year_from_period_end(end)
                if not (
                    FIRST_FACT_YEAR <= fiscal_year <= config.LAST_FISCAL_YEAR
                ):
                    drops[DROP_YEAR] += 1
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
                        "form": fact["form"],
                        "accession": fact["accn"],
                        "filed_date": periods.to_date(fact["filed"]),
                    }
                )
    return rows


def edgar_filing_url(cik, accession):
    """Return the EDGAR filing index URL for a CIK and accession number.

    Example: CIK 320193, accession 0000320193-26-000026 ->
    https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/
    0000320193-26-000026-index.htm. The index page lists the 10-K and
    every exhibit, so click-to-trace always lands on the right filing.
    """
    folder = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/"
        f"{accession}-index.htm"
    )


def assign_line_items(raw_df, drops):
    """Return one row per (fact, line item) the fact's tag serves.

    A tag can serve two items (LiabilitiesAndStockholdersEquity is a
    total_assets fallback and the liabilities_and_equity component), so
    each fact is copied once per item. Facts whose unit or period type
    does not fit the item are dropped and counted.
    """
    pieces = []
    for item, spec in tag_map.ALL_ITEMS.items():
        uses_tag = raw_df["tag"].isin(spec["tags"])
        fits = (raw_df["unit"] == spec["unit"]) & (
            raw_df["period_type"] == spec["period"]
        )
        drops[DROP_WRONG_UNIT_OR_PERIOD] += int((uses_tag & ~fits).sum())
        pieces.append(raw_df[uses_tag & fits].assign(line_item=item))
    return pd.concat(pieces, ignore_index=True)


def choose_company_tags(item_facts_df, drops):
    """Keep only the company's preferred tag for each line item and period.

    The preferred tag is the one the company reports in the most fiscal
    years (ties keep the map order), the same rule as
    tag_map.company_tag_order. Every filing of the chosen tag is kept.
    """
    years_reported = item_facts_df.groupby(["cik", "line_item", "tag"])[
        "fiscal_year"
    ].transform("nunique")
    rank_of = {
        (item, tag): position
        for item, spec in tag_map.ALL_ITEMS.items()
        for position, tag in enumerate(spec["tags"])
    }
    map_rank = pd.Series(
        [
            rank_of[(item, tag)]
            for item, tag in zip(
                item_facts_df["line_item"], item_facts_df["tag"]
            )
        ],
        index=item_facts_df.index,
    )
    # One sortable number: more years first, then earlier in the map.
    rank = -years_reported * 1000 + map_rank
    # dropna=False keeps instants, whose period_start is empty.
    best = rank.groupby(
        [item_facts_df[col] for col in PERIOD_KEY], dropna=False
    ).transform("min")
    keep = rank == best
    drops[DROP_OTHER_TAG] += int((~keep).sum())
    return item_facts_df[keep]


def mark_is_original(chosen_df, drops):
    """Add is_original: True for the earliest filing of each period.

    Ties on filing date put the 10-K before a 10-K/A, then the lower
    accession number, so the choice is deterministic. A filing that
    reports the same period twice keeps one row (counted as a duplicate).
    """
    before = len(chosen_df)
    chosen_df = chosen_df.drop_duplicates(
        subset=PERIOD_KEY + ["accession"], keep="first"
    )
    drops[DROP_DUPLICATE] += before - len(chosen_df)
    ordered = chosen_df.assign(
        is_amendment=chosen_df["form"] != "10-K"
    ).sort_values(["filed_date", "is_amendment", "accession"], kind="stable")
    first = ~ordered.duplicated(subset=PERIOD_KEY, keep="first")
    return ordered.assign(is_original=first).drop(columns="is_amendment")


def facts_for_companies(archive, ciks, tag_regex, drops):
    """Return facts_long rows (before typing) for one batch of companies."""
    rows = []
    for cik in ciks:
        company_facts = json.loads(archive.read(f"CIK{cik:010d}.json"))
        rows.extend(
            annual_facts_from_company(cik, company_facts, tag_regex, drops)
        )
    if not rows:
        return pd.DataFrame()
    item_facts_df = assign_line_items(pd.DataFrame(rows), drops)
    chosen_df = choose_company_tags(item_facts_df, drops)
    return mark_is_original(chosen_df, drops)


def to_contract_types(chosen_df):
    """Return the table with section 4 column names, order and types."""
    facts_long_df = chosen_df.rename(columns={"tag": "xbrl_tag"})
    facts_long_df["filing_url"] = [
        edgar_filing_url(cik, accession)
        for cik, accession in zip(
            facts_long_df["cik"], facts_long_df["accession"]
        )
    ]
    facts_long_df = facts_long_df[FACTS_LONG_COLUMNS].astype(
        {
            "cik": "int64",
            "line_item": "string",
            "xbrl_tag": "string",
            "value": "float64",
            "unit": "string",
            "period_start": "datetime64[ns]",
            "period_end": "datetime64[ns]",
            "fiscal_year": "int64",
            "form": "string",
            "accession": "string",
            "filed_date": "datetime64[ns]",
            "filing_url": "string",
            "is_original": "bool",
        }
    )
    return facts_long_df.sort_values(
        ["cik", "line_item", "period_end", "filed_date"]
    ).reset_index(drop=True)


def build_facts_long(companyfacts_zip, ciks):
    """Return (facts_long DataFrame, drop Counter) for the given CIKs."""
    drops = Counter()
    tag_regex = mapped_tag_regex()
    batches = []
    with zipfile.ZipFile(companyfacts_zip) as archive:
        for start in range(0, len(ciks), BATCH_COMPANIES):
            batch_ciks = ciks[start : start + BATCH_COMPANIES]
            batch_df = facts_for_companies(
                archive, batch_ciks, tag_regex, drops
            )
            if not batch_df.empty:
                batches.append(batch_df)
            print(f"  processed {start + len(batch_ciks):,} of {len(ciks):,}")
    return to_contract_types(pd.concat(batches, ignore_index=True)), drops


def drop_log(facts_long_df, drops):
    """Return a DataFrame of drop counts and kept-row counts for the log."""
    rows = [(f"dropped:{reason}", count) for reason, count in drops.items()]
    rows += [
        ("kept:rows", len(facts_long_df)),
        ("kept:original_rows", int(facts_long_df["is_original"].sum())),
        ("kept:companies", facts_long_df["cik"].nunique()),
    ]
    return pd.DataFrame(rows, columns=["measure", "count"])


def main():
    """Build facts_long for included companies and write its drop log."""
    companies_df = pd.read_parquet(config.COMPANIES_PATH)
    ciks = companies_df.loc[~companies_df["is_excluded"], "cik"].tolist()
    print(f"Building facts_long for {len(ciks):,} included companies")
    facts_long_df, drops = build_facts_long(config.COMPANYFACTS_ZIP, ciks)
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    facts_long_df.to_parquet(config.FACTS_LONG_PATH, index=False)
    log_df = drop_log(facts_long_df, drops)
    log_df.to_csv(FACTS_LONG_DROP_LOG, index=False)
    print(log_df.to_string(index=False))


if __name__ == "__main__":
    main()
