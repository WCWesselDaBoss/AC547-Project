"""Build the financials_annual table (CLAUDE.md section 4).

One row per company and fiscal year, with one column per line item holding
the ORIGINALLY reported value (is_original in facts_long), because that is
what investors saw when the 10-K came out.

Run on its own with:
    python -m src.pipeline.financials
"""

import json
import zipfile

import pandas as pd

import config
from src.pipeline import derived_items, periods, tag_map

# Prior year is needed to score FY2012, so rows start one year earlier.
FIRST_ROW_YEAR = config.FIRST_FISCAL_YEAR - 1

# A fact belongs to a 10-K's fiscal year if its period ends within this
# many days of the 10-K's report date. Absorbs 52/53-week calendars without
# reaching into a neighbouring year (which ends ~365 days away).
REPORT_DATE_TOLERANCE = pd.Timedelta(days=7)

FINANCIALS_LOG = config.LOG_DIR / "financials_annual_log.csv"

ID_COLUMNS = [
    "cik",
    "fiscal_year",
    "period_end",
    "filed_date",
    "accession",
    "passes_size_floor",
    "derived_items",
]
# Section 4 order: line items first, then derivation components.
VALUE_COLUMNS = list(tag_map.LINE_ITEMS) + list(tag_map.COMPONENT_ITEMS)
FINANCIALS_COLUMNS = ID_COLUMNS + VALUE_COLUMNS


def annual_reports_from_submission(cik, submission, archive):
    """Return a list of original 10-K filings for one company.

    Reads the "recent" filings and the overflow files, because older
    10-Ks live in the overflow files for long-lived companies.
    """
    filings = submission["filings"]
    tables = [filings["recent"]] + [
        json.loads(archive.read(extra["name"]))
        for extra in filings.get("files", [])
    ]
    reports = []
    for table in tables:
        for form, report_date, accession, filed in zip(
            table["form"],
            table["reportDate"],
            table["accessionNumber"],
            table["filingDate"],
        ):
            # Amendments do not create a new fiscal year; their values
            # reach the table through facts_long if they were first.
            if form != "10-K" or not report_date:
                continue
            period_end = periods.to_date(report_date)
            reports.append(
                {
                    "cik": cik,
                    "fiscal_year": config.fiscal_year_from_period_end(
                        period_end
                    ),
                    "period_end": period_end,
                    "filed_date": periods.to_date(filed),
                    "accession": accession,
                }
            )
    return reports


def annual_report_index(submissions_zip, ciks, log):
    """Return one row per company-year with an original 10-K.

    These rows define which company-years exist, independently of which
    facts were found, so missing data shows up as missing, not as an
    absent year. log (a dict) receives the duplicate-year count.
    """
    reports = []
    with zipfile.ZipFile(submissions_zip) as archive:
        for cik in ciks:
            submission = json.loads(archive.read(f"CIK{cik:010d}.json"))
            reports.extend(
                annual_reports_from_submission(cik, submission, archive)
            )
    index_df = pd.DataFrame(reports)
    in_range = index_df["fiscal_year"].between(
        FIRST_ROW_YEAR, config.LAST_FISCAL_YEAR
    )
    index_df = index_df[in_range]
    # A change of fiscal year end can give two 10-Ks the same fiscal year
    # label. Keep the earlier one; the other is counted, not hidden.
    index_df = index_df.sort_values(["cik", "period_end"])
    duplicate = index_df.duplicated(subset=["cik", "fiscal_year"])
    log["dropped:duplicate_fiscal_year_label"] = int(duplicate.sum())
    index_df = index_df[~duplicate].copy()
    # pandas 3 converts Python dates to second resolution; the contract
    # (and facts_long) use nanoseconds, and merges need matching types.
    for column in ("period_end", "filed_date"):
        index_df[column] = pd.to_datetime(index_df[column]).astype(
            "datetime64[ns]"
        )
    return index_df.reset_index(drop=True)


def comparative_year_index(facts_long_df, index_df, log):
    """Return company-years known only from a later or earlier 10-K.

    A company's first 10-K also reports the prior year's balance sheet and
    income statement. No 10-K was ever filed for that prior year, but the
    values are original 10-K data, and without them the first 10-K year
    can never be scored (the spec needs year t-1). The same applies to a
    gap year whose own 10-K is missing (for example, a 10-KT transition).

    A year is added when an original total_assets balance falls within
    REPORT_DATE_TOLERANCE of one year before or after an existing 10-K's
    year end, and that fiscal year has no 10-K of its own. The row's
    accession and filed_date are the filing that first reported that
    balance, so the year still traces to a real 10-K.
    """
    assets = facts_long_df[
        facts_long_df["is_original"]
        & (facts_long_df["line_item"] == "total_assets")
    ][["cik", "fiscal_year", "period_end", "filed_date", "accession"]]
    one_year = pd.Timedelta(days=365)
    targets = pd.concat(
        [
            index_df[["cik"]].assign(target=index_df["period_end"] - one_year),
            index_df[["cik"]].assign(target=index_df["period_end"] + one_year),
        ]
    )
    matched = pd.merge_asof(
        assets.sort_values("period_end"),
        targets.sort_values("target").assign(near_target=True),
        left_on="period_end",
        right_on="target",
        by="cik",
        direction="nearest",
        tolerance=REPORT_DATE_TOLERANCE,
    )
    matched = matched[matched["near_target"].notna()]
    own_years = index_df[["cik", "fiscal_year"]].assign(has_own_10k=True)
    matched = matched.merge(own_years, on=["cik", "fiscal_year"], how="left")
    added = matched[
        matched["has_own_10k"].isna()
        & matched["fiscal_year"].between(
            FIRST_ROW_YEAR, config.LAST_FISCAL_YEAR
        )
    ]
    added = added.sort_values("period_end").drop_duplicates(
        subset=["cik", "fiscal_year"], keep="last"
    )[["cik", "fiscal_year", "period_end", "filed_date", "accession"]]
    log["added:comparative_only_years"] = len(added)
    return added.reset_index(drop=True)


def match_originals_to_years(facts_long_df, index_df, log):
    """Attach each original fact to the 10-K year whose date is nearest.

    merge_asof finds, per company, the 10-K report date closest to the
    fact's period end, within REPORT_DATE_TOLERANCE.
    """
    originals = facts_long_df[facts_long_df["is_original"]]
    originals = originals[["cik", "line_item", "value", "period_end"]]
    matched = pd.merge_asof(
        originals.sort_values("period_end"),
        index_df[["cik", "fiscal_year", "period_end"]]
        .rename(columns={"period_end": "report_date"})
        .sort_values("report_date"),
        left_on="period_end",
        right_on="report_date",
        by="cik",
        direction="nearest",
        tolerance=REPORT_DATE_TOLERANCE,
    )
    unmatched = matched["fiscal_year"].isna()
    # Typical causes: a 10-K missing from submissions, or a balance on a
    # date other than the fiscal year end.
    log["unused:original_facts_matching_no_10k_year"] = int(unmatched.sum())
    matched = matched[~unmatched].copy()
    matched["fiscal_year"] = matched["fiscal_year"].astype("int64")
    # If two values fall in one year (rare), keep the one nearest the
    # report date.
    matched["gap"] = (matched["period_end"] - matched["report_date"]).abs()
    return matched.sort_values("gap").drop_duplicates(
        subset=["cik", "fiscal_year", "line_item"], keep="first"
    )


def pivot_to_wide(matched_df, index_df, log):
    """Return one row per company-year, one column per item value."""
    wide = matched_df.pivot(
        index=["cik", "fiscal_year"], columns="line_item", values="value"
    )
    wide = wide.reindex(columns=VALUE_COLUMNS)
    wide_df = index_df.merge(
        wide.reset_index(), on=["cik", "fiscal_year"], how="left"
    )
    no_values = wide_df[VALUE_COLUMNS].isna().all(axis=1)
    log["dropped:10k_year_with_no_facts"] = int(no_values.sum())
    return wide_df[~no_values].reset_index(drop=True)


def passes_size_floor(revenue, total_assets):
    """Return True where revenue OR total assets is at least the floor.

    Tested separately each year in nominal dollars (CLAUDE.md section 2).
    A missing value cannot pass, so a year with both missing is False.
    """
    floor = config.SIZE_FLOOR_USD
    return (revenue >= floor).fillna(False) | (total_assets >= floor).fillna(
        False
    )


def to_contract_types(wide_df):
    """Return the table in section 4 column order and types."""
    financials_df = wide_df[FINANCIALS_COLUMNS].astype(
        {
            "cik": "int64",
            "fiscal_year": "int64",
            "period_end": "datetime64[ns]",
            "filed_date": "datetime64[ns]",
            "accession": "string",
            "passes_size_floor": "bool",
            "derived_items": "string",
            **{column: "float64" for column in VALUE_COLUMNS},
        }
    )
    return financials_df.sort_values(["cik", "fiscal_year"]).reset_index(
        drop=True
    )


def build_financials(facts_long_df, index_df, log):
    """Return financials_annual from facts_long and the 10-K index."""
    log["kept:company_years_with_own_10k"] = len(index_df)
    index_df = pd.concat(
        [index_df, comparative_year_index(facts_long_df, index_df, log)],
        ignore_index=True,
    )
    matched_df = match_originals_to_years(facts_long_df, index_df, log)
    wide_df = pivot_to_wide(matched_df, index_df, log)
    wide_df = derived_items.apply_derivations(wide_df)
    wide_df["passes_size_floor"] = passes_size_floor(
        wide_df["revenue"], wide_df["total_assets"]
    )
    return to_contract_types(wide_df)


def summary_log(financials_df, log):
    """Return the log as a DataFrame: drops, size floor, missing values."""
    scored_years = financials_df["fiscal_year"] >= config.FIRST_FISCAL_YEAR
    in_range = financials_df[scored_years]
    untestable = in_range["revenue"].isna() & in_range["total_assets"].isna()
    rows = list(log.items())
    rows += [
        (
            "kept:company_years_fy2011_prior_year_only",
            int((~scored_years).sum()),
        ),
        ("kept:company_years_fy2012_on", len(in_range)),
        ("size_floor:pass", int(in_range["passes_size_floor"].sum())),
        (
            "size_floor:fail",
            int((~in_range["passes_size_floor"] & ~untestable).sum()),
        ),
        ("size_floor:untestable_no_revenue_or_assets", int(untestable.sum())),
    ]
    passing = in_range[in_range["passes_size_floor"]]
    rows += [
        (
            f"missing_in_size_floor_years:{column}",
            int(passing[column].isna().sum()),
        )
        for column in tag_map.LINE_ITEMS
    ]
    derived = passing["derived_items"].dropna().str.split("; ").explode()
    rows += [
        (f"derived_in_size_floor_years:{item}", int(count))
        for item, count in derived.value_counts().items()
    ]
    return pd.DataFrame(rows, columns=["measure", "count"])


def main():
    """Build financials_annual for included companies and write its log."""
    companies_df = pd.read_parquet(config.COMPANIES_PATH)
    ciks = companies_df.loc[~companies_df["is_excluded"], "cik"].tolist()
    facts_long_df = pd.read_parquet(config.FACTS_LONG_PATH)
    log = {}
    index_df = annual_report_index(config.SUBMISSIONS_ZIP, ciks, log)
    financials_df = build_financials(facts_long_df, index_df, log)
    financials_df.to_parquet(config.FINANCIALS_PATH, index=False)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_df = summary_log(financials_df, log)
    log_df.to_csv(FINANCIALS_LOG, index=False)
    print(log_df.to_string(index=False))


if __name__ == "__main__":
    main()
