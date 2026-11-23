"""Quarterly upgrade, step 2: build facts_quarterly from 10-Q and 10-K data.

facts_quarterly is the quarterly counterpart of facts_long (CLAUDE.md
section 4): one row per company, line item, period and filing, from the
same SEC bulk file, using the same tag map, so a line item means exactly
the same thing in both modes. It is a NEW table; this module changes no
annual table, function or result (tests/test_annual_baseline.py checks).

What is different from facts_long:
- forms: 10-Q and 10-Q/A as well as 10-K and 10-K/A (the 10-Ks supply
  the full-year flows needed for the fourth quarter and the year-end
  balance sheets);
- durations: 3, 6, 9 and 12-month flows are all kept, each labeled by
  its length (duration_days), because 10-Q cash flow statements are
  usually year-to-date only and step 3 differences them;
- each row gets a fiscal_quarter (1 to 4), counted from the company's
  own fiscal year end, which handles non-calendar and 52/53-week years.

Run: python -m src.pipeline.quarterly
"""

import json
import zipfile
from collections import Counter

import numpy as np
import pandas as pd

import config
from src.pipeline import facts, periods, tag_map

FACTS_QUARTERLY_PATH = config.PROCESSED_DIR / "facts_quarterly.parquet"
DROP_LOG = config.LOG_DIR / "facts_quarterly_drops.csv"

QUARTERLY_FORMS = ("10-Q", "10-Q/A", "10-K", "10-K/A")
# Facts start two fiscal years before the first quarterly score year
# (FY2013): a FY2013 Q1 TTM needs the four prior quarters, and its prior
# year needs four more. There is no upper limit: the most recent 10-Qs
# are kept (FY2026 included).
FIRST_FACT_YEAR = 2011

# Flow lengths, in days counting both ends (periods.period_days, as the
# annual 350-380 rule does). Anything else is dropped and counted.
# The bins cover 12 to 16-week quarters, not just 13-week ones: Costco's
# 24 and 36-week year-to-date periods are 168 and 252 days, and Advance
# Auto's 16-week first quarter is 112 days. They still exclude calendar
# 4, 5, 7 and 8-month periods (about 120, 151, 212 and 243 days).
DURATION_BINS = {3: (80, 115), 6: (165, 200), 9: (250, 290), 12: (350, 380)}

# A quarter end is about 91.3 days (a quarter of 365.25) after the
# previous one. 52/53-week years have 13 or 14-week quarters (91 or 98
# days), so a period end within this many days of a quarter boundary is
# accepted; anything further off (a changed fiscal year, a transition
# period) is dropped and counted rather than forced into a quarter.
DAYS_PER_QUARTER = 365.25 / 4
QUARTER_TOLERANCE_DAYS = 10
# A period ending this close to a fiscal year end belongs to that year
# end (its Q4 or its year-end balance sheet), not to the next year's Q1.
YEAR_END_TOLERANCE_DAYS = 10
# Fiscal year ends are extended this many years before the first and
# after the last 10-K, so early 10-Qs and the latest 10-Qs get quarters.
EXTEND_YEARS = 3
# Some companies use 12 and 16-week quarters (Costco: 12, 12, 12, 16
# weeks; Advance Auto Parts: 16, 12, 12, 12), whose quarter ends sit 15
# to 22 days off the 91-day grid. So a period end is also accepted if it
# is within this many days of one of the company's own 10-Q or 10-K
# report dates (SEC submissions "reportDate", the period each filing
# covers). 7 days allows for a fact dated a day or two from the filing's
# report date, but is far shorter than any real quarter (84 days).
REPORT_DATE_TOLERANCE_DAYS = 7

DROP_FORM = "form_not_10q_or_10k"
DROP_DURATION = "duration_not_3_6_9_or_12_months"
DROP_YEAR = "fiscal_year_before_2011"
DROP_NO_YEAR_END = "no_fiscal_year_end_from_10k"
DROP_OFF_QUARTER = "period_end_not_at_a_quarter_end"

FACTS_QUARTERLY_COLUMNS = [
    "cik",
    "line_item",
    "xbrl_tag",
    "value",
    "unit",
    "period_start",
    "period_end",
    "fiscal_year",
    "fiscal_quarter",
    "duration_days",
    "form",
    "accession",
    "filed_date",
    "filing_url",
    "is_original",
]


# ---------------------------------------------------------------------------
# Reading facts
# ---------------------------------------------------------------------------
def duration_months(start, end):
    """Return 3, 6, 9 or 12 for a flow period of that length, or None.

    Lengths count both ends (periods.period_days), as the annual rule
    does."""
    days = periods.period_days(start, end)
    for months, (low, high) in DURATION_BINS.items():
        if low <= days <= high:
            return months
    return None


def quarterly_facts_from_company(cik, company_facts, tag_regex, drops):
    """Return quarterly fact dicts for one companyfacts JSON.

    Keeps us-gaap tags matching tag_regex, units USD or shares, forms
    10-Q, 10-Q/A, 10-K and 10-K/A, and flows of 3, 6, 9 or 12 months (or
    instants). Fiscal year and quarter are added later, from the
    company's fiscal year ends. Every removed fact is counted in drops.
    """
    rows = []
    us_gaap = company_facts.get("facts", {}).get("us-gaap", {})
    for tag, tag_info in us_gaap.items():
        if not tag_regex.search(tag):
            continue
        for unit, unit_facts in tag_info["units"].items():
            if unit not in ("USD", "shares"):
                drops[facts.DROP_UNIT] += len(unit_facts)
                continue
            for fact in unit_facts:
                if fact.get("form") not in QUARTERLY_FORMS:
                    drops[DROP_FORM] += 1
                    continue
                end = periods.to_date(fact["end"])
                start = periods.to_date(fact.get("start"))
                duration = None
                if start is not None:
                    if duration_months(start, end) is None:
                        drops[DROP_DURATION] += 1
                        continue
                    duration = periods.period_days(start, end)
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
                        "duration_days": duration,
                        "value": float(fact["val"]),
                        "form": fact["form"],
                        "accession": fact["accn"],
                        "filed_date": periods.to_date(fact["filed"]),
                    }
                )
    return rows


# ---------------------------------------------------------------------------
# Fiscal years and quarters, from each company's own fiscal year ends
# ---------------------------------------------------------------------------
def fiscal_year_ends(financials_df):
    """Return {cik: sorted fiscal year end dates}, from the 10-K year ends
    in financials_annual (read only), extended EXTEND_YEARS years before
    the first and after the last by whole years, so 10-Qs filed before a
    company's first 10-K or after its latest one still get quarters."""
    ends = {}
    for cik, group in financials_df.groupby("cik"):
        dates = sorted(pd.to_datetime(group["period_end"]).dropna().unique())
        if not dates:
            continue
        first, last = pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
        before = [
            first - pd.DateOffset(years=k) for k in range(EXTEND_YEARS, 0, -1)
        ]
        after = [
            last + pd.DateOffset(years=k) for k in range(1, EXTEND_YEARS + 1)
        ]
        ends[int(cik)] = pd.DatetimeIndex(
            before + [pd.Timestamp(d) for d in dates] + after
        )
    return ends


def report_period_ends(submissions_zip, ciks):
    """Return {cik: sorted unique report dates} of each company's 10-Q,
    10-Q/A, 10-K and 10-K/A filings, from SEC's submissions file (read
    only). Reads the "recent" filings and the overflow files, as
    financials.annual_reports_from_submission does. Companies with no
    submissions record are left out (assign_quarter then uses the grid
    rule alone)."""
    ends = {}
    with zipfile.ZipFile(submissions_zip) as archive:
        names = set(archive.namelist())
        for cik in ciks:
            name = f"CIK{int(cik):010d}.json"
            if name not in names:
                continue
            filings = json.loads(archive.read(name))["filings"]
            tables = [filings["recent"]] + [
                json.loads(archive.read(extra["name"]))
                for extra in filings.get("files", [])
                if extra["name"] in names
            ]
            dates = {
                report_date
                for table in tables
                for form, report_date in zip(
                    table["form"], table["reportDate"]
                )
                if form in QUARTERLY_FORMS and report_date
            }
            if dates:
                ends[int(cik)] = pd.DatetimeIndex(
                    sorted(pd.to_datetime(list(dates)))
                )
    return ends


def near_a_report_date(period_end, report_ends):
    """Return True if period_end is within REPORT_DATE_TOLERANCE_DAYS of
    one of the company's report dates (report_ends, sorted)."""
    if report_ends is None or len(report_ends) == 0:
        return False
    position = report_ends.searchsorted(period_end)
    nearby = report_ends[max(position - 1, 0) : position + 1]
    gaps = np.abs((nearby - period_end).days.to_numpy())
    return bool(gaps.min() <= REPORT_DATE_TOLERANCE_DAYS)


def assign_quarter(period_end, year_ends, report_ends=None):
    """Return (fiscal_year, fiscal_quarter) for a period end, or None.

    The fiscal year is the one closing at the first fiscal year end on or
    after the period end (within YEAR_END_TOLERANCE_DAYS), labeled from
    that year end's date the same way as annual (config.
    fiscal_year_from_period_end), never from SEC's fy field. The quarter
    is the number of quarter-lengths (about 91 days) from the previous
    fiscal year end, rounded: about 91 days is Q1, 182 Q2, 273 Q3 and 364
    (the year end itself) Q4. A 14-week quarter in a 53-week year is 98
    days and still rounds correctly, and so do 12/16-week calendars
    (84, 168, 252, 364 days, or 112, 196, 280, 364).

    The period end must be a real quarter end: within 7 days of one of
    the company's own report dates (report_ends, optional), or within
    QUARTER_TOLERANCE_DAYS of the 91-day grid. Either is enough, so
    adding report dates can only place more facts, never fewer.
    Otherwise it returns None.
    """
    period_end = pd.Timestamp(period_end)
    tolerance = pd.Timedelta(days=YEAR_END_TOLERANCE_DAYS)
    position = year_ends.searchsorted(period_end - tolerance, side="left")
    if position == 0 or position >= len(year_ends):
        return None
    year_end, previous = year_ends[position], year_ends[position - 1]
    days = (period_end - previous).days
    quarter = int(round(days / DAYS_PER_QUARTER))
    if not 1 <= quarter <= 4:
        return None
    on_grid = abs(days - quarter * DAYS_PER_QUARTER) <= QUARTER_TOLERANCE_DAYS
    if not (on_grid or near_a_report_date(period_end, report_ends)):
        return None
    return config.fiscal_year_from_period_end(year_end.date()), quarter


def add_quarters(raw_df, year_ends, drops, report_ends=None):
    """Return raw_df with fiscal_year and fiscal_quarter, dropping (and
    counting) rows that cannot be placed. report_ends is {cik: report
    dates} (optional; see assign_quarter)."""
    cik = int(raw_df["cik"].iloc[0])
    company_ends = year_ends.get(cik)
    if company_ends is None:
        drops[DROP_NO_YEAR_END] += len(raw_df)
        return raw_df.iloc[0:0].assign(fiscal_year=[], fiscal_quarter=[])
    company_reports = (report_ends or {}).get(cik)
    placed = [
        assign_quarter(end, company_ends, company_reports)
        for end in raw_df["period_end"]
    ]
    keep = np.array([p is not None for p in placed])
    drops[DROP_OFF_QUARTER] += int((~keep).sum())
    out = raw_df[keep].copy()
    out["fiscal_year"] = [p[0] for p in placed if p is not None]
    out["fiscal_quarter"] = [p[1] for p in placed if p is not None]
    too_early = out["fiscal_year"] < FIRST_FACT_YEAR
    drops[DROP_YEAR] += int(too_early.sum())
    return out[~too_early]


# ---------------------------------------------------------------------------
# One row per period and filing, and the original
# ---------------------------------------------------------------------------
def mark_is_original_quarterly(chosen_df):
    """Add is_original: True for the earliest filing of each period.

    The same rule as facts_long (CLAUDE.md section 4): the earliest
    filing that reported the period under any mapped tag is the
    original. facts.mark_is_original treats every form other than "10-K"
    as an amendment in its tie-break, which would wrongly count a plain
    10-Q as one, so this version (used only for quarterly data) treats
    only forms ending in "/A" as amendments. Ties on filing date put the
    original form before its amendment, then the lower accession number.
    """
    ordered = chosen_df.assign(
        is_amendment=chosen_df["form"].str.endswith("/A")
    ).sort_values(["filed_date", "is_amendment", "accession"], kind="stable")
    first = ~ordered.duplicated(subset=facts.PERIOD_KEY, keep="first")
    return ordered.assign(is_original=first).drop(columns="is_amendment")


def company_rows(
    cik, company_facts, tag_regex, year_ends, drops, report_ends=None
):
    """Return one company's quarterly facts with fiscal year and quarter,
    before line items and tag choice (those run on a whole batch)."""
    rows = quarterly_facts_from_company(cik, company_facts, tag_regex, drops)
    if not rows:
        return pd.DataFrame()
    return add_quarters(pd.DataFrame(rows), year_ends, drops, report_ends)


def choose_and_mark(raw_df, drops):
    """Return one row per company, line item, period and filing, with
    is_original: the project's own line-item and tag-choice functions
    (facts.assign_line_items, facts.choose_tag_per_filing, including the
    revenue guard), then the quarterly is_original rule."""
    item_facts_df = facts.assign_line_items(raw_df, drops)
    if item_facts_df.empty:
        return item_facts_df
    chosen_df = facts.choose_tag_per_filing(item_facts_df, drops)
    return mark_is_original_quarterly(chosen_df)


def included_ciks(companies_df):
    """Return the companies to build: those not excluded in the companies
    table (the same SIC 6000-6799 and missing-SIC exclusions as annual)."""
    return companies_df.loc[~companies_df["is_excluded"], "cik"].tolist()


def to_contract_types(chosen_df):
    """Return the table with the section 4 column names, order and types."""
    table = chosen_df.rename(columns={"tag": "xbrl_tag"})
    table["filing_url"] = [
        facts.edgar_filing_url(cik, accession)
        for cik, accession in zip(table["cik"], table["accession"])
    ]
    table = table[FACTS_QUARTERLY_COLUMNS].astype(
        {
            "cik": "int64",
            "line_item": "string",
            "xbrl_tag": "string",
            "value": "float64",
            "unit": "string",
            "period_start": "datetime64[ns]",
            "period_end": "datetime64[ns]",
            "fiscal_year": "int64",
            "fiscal_quarter": "int64",
            "duration_days": "Int64",
            "form": "string",
            "accession": "string",
            "filed_date": "datetime64[ns]",
            "filing_url": "string",
            "is_original": "bool",
        }
    )
    return table.sort_values(
        ["cik", "line_item", "period_end", "period_start", "filed_date"]
    ).reset_index(drop=True)


def build_facts_quarterly(companyfacts_zip, ciks, year_ends, report_ends=None):
    """Return (facts_quarterly, drop Counter) for the given companies.

    Companies are processed in batches of facts.BATCH_COMPANIES, as the
    annual pipeline does; each company's facts are independent, so the
    batch size changes no result, only speed and memory."""
    drops = Counter()
    tag_regex = facts.mapped_tag_regex()
    pieces = []
    with zipfile.ZipFile(companyfacts_zip) as archive:
        names = set(archive.namelist())
        for start in range(0, len(ciks), facts.BATCH_COMPANIES):
            batch = []
            for cik in ciks[start : start + facts.BATCH_COMPANIES]:
                name = f"CIK{int(cik):010d}.json"
                if name not in names:
                    continue
                rows = company_rows(
                    int(cik),
                    json.loads(archive.read(name)),
                    tag_regex,
                    year_ends,
                    drops,
                    report_ends,
                )
                if not rows.empty:
                    batch.append(rows)
            if batch:
                chosen = choose_and_mark(
                    pd.concat(batch, ignore_index=True), drops
                )
                if not chosen.empty:
                    pieces.append(chosen)
            done = min(start + facts.BATCH_COMPANIES, len(ciks))
            print(f"  processed {done:,} of {len(ciks):,}")
    return to_contract_types(pd.concat(pieces, ignore_index=True)), drops


def main():
    """Build data/processed/facts_quarterly.parquet and its drop log."""
    companies = pd.read_parquet(
        config.COMPANIES_PATH, columns=["cik", "is_excluded"]
    )
    ciks = included_ciks(companies)
    financials_df = pd.read_parquet(
        config.FINANCIALS_PATH, columns=["cik", "fiscal_year", "period_end"]
    )
    report_ends = report_period_ends(config.SUBMISSIONS_ZIP, ciks)
    print(f"Report dates found for {len(report_ends):,} companies")
    table, drops = build_facts_quarterly(
        config.COMPANYFACTS_ZIP,
        ciks,
        fiscal_year_ends(financials_df),
        report_ends,
    )
    table.to_parquet(FACTS_QUARTERLY_PATH, index=False)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = pd.DataFrame(sorted(drops.items()), columns=["reason", "facts"])
    log.to_csv(DROP_LOG, index=False)
    print(log.to_string(index=False))
    print(f"Wrote {len(table):,} rows to {FACTS_QUARTERLY_PATH}")


if __name__ == "__main__":
    main()
