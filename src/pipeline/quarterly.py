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
# Fix C (Nov 22): fiscal year ends also come from the company's own
# 10-Ks: each 10-K's year end is the latest period end of its 12-month
# facts, so a year that financials_annual lacks still has its year end.
# SEC's submissions "reportDate" is not used for this: for some 10-Ks it
# is the filing date (Southwestern Energy's FY2017 10-K shows
# 2018-03-01), which created false 2-month "fiscal years".
# A real fiscal year lasts 350 to 380 days between year ends (52/53-week
# years are 364 or 371). A shorter or longer interval is a change of
# fiscal year end (a transition period, or a gap with no report); its
# quarters belong to no fiscal year and are dropped and counted, never
# rounded into a quarter number.
FISCAL_YEAR_DAYS = (350, 380)
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
# Fix C: the 12-month bin, used to find each 10-K's year end.
TWELVE_MONTH_DAYS = DURATION_BINS[12]

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
DROP_AFTER_FILING = "period_end_after_filed_date"
DROP_TRANSITION = "quarter_in_a_fiscal_year_change"
DROP_LABEL_TWICE = "fiscal_year_label_used_twice"

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
                filed = periods.to_date(fact["filed"])
                # A filing cannot report a period that has not ended yet;
                # such facts are mis-tagged contexts (635 found). Dropped
                # before the original is chosen, so the real, later
                # filing becomes the original.
                if end > filed:
                    drops[DROP_AFTER_FILING] += 1
                    continue
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
                        "filed_date": filed,
                    }
                )
    return rows


# ---------------------------------------------------------------------------
# Fiscal years and quarters, from each company's own fiscal year ends
# ---------------------------------------------------------------------------
def annual_year_end_dates(financials_df):
    """Return {cik: sorted year end dates} from financials_annual (read
    only), before any 10-K dates are added or the list is extended."""
    return {
        int(cik): [
            pd.Timestamp(d)
            for d in sorted(pd.to_datetime(group["period_end"]).dropna())
        ]
        for cik, group in financials_df.groupby("cik")
    }


def ten_k_year_ends(rows_df):
    """Return the year ends of a company's own 10-Ks (fix C): for each
    10-K or 10-K/A, the latest period end among its 12-month facts. A
    10-K's most recent 12-month period is the fiscal year it reports;
    earlier 12-month facts are comparatives of other years."""
    twelve = rows_df[
        rows_df["form"].str.startswith("10-K")
        & rows_df["duration_days"].between(*TWELVE_MONTH_DAYS).fillna(False)
    ]
    ends = twelve.groupby("accession")["period_end"].max()
    return pd.DatetimeIndex(sorted(pd.to_datetime(ends).unique()))


def combine_year_ends(annual_dates, ten_k_dates):
    """Return one company's fiscal year ends: financials_annual's dates
    plus its own 10-K year ends that are not within
    YEAR_END_TOLERANCE_DAYS of one of them (where both give a date,
    financials_annual's is kept, so labels match the annual table),
    extended EXTEND_YEARS years before the first and after the last by
    whole years, so 10-Qs filed before a company's first 10-K or after
    its latest one still get quarters. Empty if there are no dates."""
    tolerance = pd.Timedelta(days=YEAR_END_TOLERANCE_DAYS)
    annual = [pd.Timestamp(d) for d in annual_dates]
    extra = [
        pd.Timestamp(d)
        for d in ten_k_dates
        if not any(abs(pd.Timestamp(d) - a) <= tolerance for a in annual)
    ]
    dates = sorted(set(annual + extra))
    if not dates:
        return pd.DatetimeIndex([])
    first, last = dates[0], dates[-1]
    before = [
        first - pd.DateOffset(years=k) for k in range(EXTEND_YEARS, 0, -1)
    ]
    after = [last + pd.DateOffset(years=k) for k in range(1, EXTEND_YEARS + 1)]
    return pd.DatetimeIndex(before + dates + after)


def fiscal_year_ends(financials_df, ten_k_dates=None):
    """Return {cik: sorted fiscal year end dates}: financials_annual's
    year ends plus, if given, 10-K year ends ({cik: dates}), combined
    and extended by combine_year_ends. A year missing from
    financials_annual (Southwestern Energy FY2017) then still has its
    year end; a transition period (Archer-Daniels-Midland, July to
    December 2012) has none, so it shows as a gap that is not a fiscal
    year (see place_quarter)."""
    ten_k_dates = ten_k_dates or {}
    annual = annual_year_end_dates(financials_df)
    ends = {}
    for cik in sorted(set(annual) | set(ten_k_dates)):
        combined = combine_year_ends(
            annual.get(cik, []), ten_k_dates.get(cik, [])
        )
        if len(combined):
            ends[cik] = combined
    return ends


def report_period_ends(submissions_zip, ciks):
    """Return {cik: sorted unique report dates} of each company's 10-Q,
    10-Q/A, 10-K and 10-K/A filings, from SEC's submissions file (read
    only). Companies with no submissions record are left out
    (assign_quarter then uses the grid rule alone)."""
    return report_dates_for_forms(submissions_zip, ciks, QUARTERLY_FORMS)


def report_dates_for_forms(submissions_zip, ciks, forms):
    """Return {cik: sorted unique report dates} of the filings of the
    given forms. Reads the "recent" filings and the overflow files, as
    financials.annual_reports_from_submission does."""
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
                if form in forms and report_date
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
    """Return (fiscal_year, fiscal_quarter) for a period end, or None
    when it cannot be placed (place_quarter gives the reason)."""
    placed = place_quarter(period_end, year_ends, report_ends)
    return None if isinstance(placed, str) else placed


def place_quarter(period_end, year_ends, report_ends=None):
    """Return (fiscal_year, fiscal_quarter) for a period end, or the drop
    reason (a string) when it cannot be placed.

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
    Otherwise the reason is DROP_OFF_QUARTER.

    Fix C adds two checks on the fiscal year itself. If its year ends
    are not 350 to 380 days apart, it is a change of fiscal year end
    (DROP_TRANSITION): its quarters belong to no fiscal year. If its
    label equals the previous year's (a 52/53-week year ending in the
    first days of June after one ending at the end of May, so both fall
    in the same label under the January-May rule), the annual table kept
    only the earlier year, so this year's quarters cannot carry a label
    that matches it (DROP_LABEL_TWICE).
    """
    period_end = pd.Timestamp(period_end)
    tolerance = pd.Timedelta(days=YEAR_END_TOLERANCE_DAYS)
    position = year_ends.searchsorted(period_end - tolerance, side="left")
    if position == 0 or position >= len(year_ends):
        return DROP_OFF_QUARTER
    year_end, previous = year_ends[position], year_ends[position - 1]
    if (
        not FISCAL_YEAR_DAYS[0]
        <= (year_end - previous).days
        <= (FISCAL_YEAR_DAYS[1])
    ):
        return DROP_TRANSITION
    label = config.fiscal_year_from_period_end(year_end.date())
    if label == config.fiscal_year_from_period_end(previous.date()):
        return DROP_LABEL_TWICE
    days = (period_end - previous).days
    quarter = int(round(days / DAYS_PER_QUARTER))
    if not 1 <= quarter <= 4:
        return DROP_OFF_QUARTER
    on_grid = abs(days - quarter * DAYS_PER_QUARTER) <= QUARTER_TOLERANCE_DAYS
    if not (on_grid or near_a_report_date(period_end, report_ends)):
        return DROP_OFF_QUARTER
    return label, quarter


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
        place_quarter(end, company_ends, company_reports)
        for end in raw_df["period_end"]
    ]
    keep = np.array([not isinstance(p, str) for p in placed])
    for reason in placed:
        if isinstance(reason, str):
            drops[reason] += 1
    out = raw_df[keep].copy()
    out["fiscal_year"] = [p[0] for p in placed if not isinstance(p, str)]
    out["fiscal_quarter"] = [p[1] for p in placed if not isinstance(p, str)]
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
    cik,
    company_facts,
    tag_regex,
    year_ends,
    drops,
    report_ends=None,
    annual_dates=None,
):
    """Return one company's quarterly facts with fiscal year and quarter,
    before line items and tag choice (those run on a whole batch).

    If annual_dates ({cik: financials_annual year ends}) is given, the
    company's year ends are built from them plus its own 10-K year ends
    (fix C); otherwise year_ends ({cik: dates}) is used as given."""
    rows = quarterly_facts_from_company(cik, company_facts, tag_regex, drops)
    if not rows:
        return pd.DataFrame()
    raw_df = pd.DataFrame(rows)
    if annual_dates is not None:
        combined = combine_year_ends(
            annual_dates.get(cik, []), ten_k_year_ends(raw_df)
        )
        year_ends = {cik: combined} if len(combined) else {}
    return add_quarters(raw_df, year_ends, drops, report_ends)


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


def build_facts_quarterly(
    companyfacts_zip, ciks, year_ends, report_ends=None, annual_dates=None
):
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
                    annual_dates,
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
        annual_year_end_dates(financials_df),
    )
    table.to_parquet(FACTS_QUARTERLY_PATH, index=False)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = pd.DataFrame(sorted(drops.items()), columns=["reason", "facts"])
    log.to_csv(DROP_LOG, index=False)
    print(log.to_string(index=False))
    print(f"Wrote {len(table):,} rows to {FACTS_QUARTERLY_PATH}")


if __name__ == "__main__":
    main()
