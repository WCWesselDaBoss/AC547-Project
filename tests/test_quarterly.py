"""Tests for the quarterly upgrade (src/pipeline/quarterly.py), with fake
data only. The annual tables are guarded by tests/test_annual_baseline.py.
"""

import json
import zipfile
from collections import Counter
from datetime import date

import pandas as pd
import pytest

from src.pipeline import facts, quarterly


def ends(*dates):
    """Return fiscal year ends as a DatetimeIndex."""
    return pd.DatetimeIndex(pd.to_datetime(list(dates)))


# ---------------------------------------------------------------------------
# Durations
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "start, end, months",
    [
        ("2024-01-01", "2024-03-31", 3),  # 91 days, counting both ends
        ("2024-01-01", "2024-06-30", 6),  # 182 days
        ("2024-01-01", "2024-09-30", 9),  # 274 days
        ("2024-01-01", "2024-12-31", 12),  # 366 days
        ("2024-01-01", "2024-04-29", None),  # 120 days: not a quarter length
        ("2023-09-04", "2023-11-26", 3),  # 84 days: a 12-week quarter
        ("2024-01-02", "2024-04-23", 3),  # 113 days: a 16-week quarter
        ("2023-09-04", "2024-02-18", 6),  # 168 days: 24 weeks (Costco)
        ("2024-01-02", "2024-07-16", 6),  # 197 days: 28 weeks (Advance)
        ("2023-09-04", "2024-05-12", 9),  # 252 days: 36 weeks (Costco)
        ("2024-01-01", "2024-07-31", None),  # 213 days: 7 months
        ("2024-01-01", "2024-08-31", None),  # 244 days: 8 months
    ],
)
def test_duration_bins(start, end, months):
    """3, 6, 9 and 12-month flows are recognized; a 4-month one is not."""
    assert (
        quarterly.duration_months(
            date.fromisoformat(start), date.fromisoformat(end)
        )
        == months
    )


# ---------------------------------------------------------------------------
# Fiscal year and quarter
# ---------------------------------------------------------------------------
def test_calendar_year_quarters():
    """December year ends: March, June and September ends are Q1 to Q3 of
    that year; the December 31 year end is Q4."""
    year_ends = ends("2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31")
    for end, expected in [
        ("2024-03-31", (2024, 1)),
        ("2024-06-30", (2024, 2)),
        ("2024-09-30", (2024, 3)),
        ("2024-12-31", (2024, 4)),
    ]:
        assert quarterly.assign_quarter(end, year_ends) == expected


def test_non_calendar_year_quarters():
    """Apple-style September year ends (Sept 30, 2023 and Sept 28, 2024):
    a quarter ending Dec 30, 2023 is Q1 of fiscal 2024, and the Sept 28,
    2024 year end is Q4 of fiscal 2024 (labeled from the year end, as
    annual is)."""
    year_ends = ends("2022-09-24", "2023-09-30", "2024-09-28", "2025-09-27")
    assert quarterly.assign_quarter("2023-12-30", year_ends) == (2024, 1)
    assert quarterly.assign_quarter("2024-06-29", year_ends) == (2024, 3)
    assert quarterly.assign_quarter("2024-09-28", year_ends) == (2024, 4)


def test_52_53_week_year_quarters():
    """A retailer ending on the Saturday nearest January 31: Jan 28, 2023
    to Feb 3, 2024 is a 53-week year (371 days). Its 13-week quarters end
    Apr 29, Jul 29 and Oct 28, and the 14-week fourth quarter ends Feb 3,
    2024: all four are placed, in fiscal 2023 (a year ending in February
    belongs to the prior year, as annual labels it). A 14-week FIRST
    quarter (98 days) is also Q1."""
    year_ends = ends("2022-01-29", "2023-01-28", "2024-02-03", "2025-02-01")
    for end, quarter in [
        ("2023-04-29", 1),
        ("2023-07-29", 2),
        ("2023-10-28", 3),
        ("2024-02-03", 4),
    ]:
        assert quarterly.assign_quarter(end, year_ends) == (2023, quarter)
    assert quarterly.assign_quarter("2023-05-06", year_ends) == (2023, 1)


def test_12_12_12_16_week_quarters_use_report_dates():
    """A Costco-style calendar: year ends Sept 3, 2023 and Sept 1, 2024,
    quarters of 12, 12, 12 and 16 weeks (84, 168, 252 and 364 days).
    Q2 and Q3 are 15 and 22 days off the 91-day grid, so without the
    company's report dates they are not placed; with them, all four
    quarters are placed in fiscal 2024."""
    year_ends = ends("2022-08-28", "2023-09-03", "2024-09-01", "2025-08-31")
    quarter_ends = ["2023-11-26", "2024-02-18", "2024-05-12", "2024-09-01"]
    reports = ends(*quarter_ends)
    assert quarterly.assign_quarter("2024-02-18", year_ends) is None
    assert quarterly.assign_quarter("2024-05-12", year_ends) is None
    for end, quarter in zip(quarter_ends, [1, 2, 3, 4]):
        assert quarterly.assign_quarter(end, year_ends, reports) == (
            2024,
            quarter,
        )


def test_16_12_12_12_week_quarters_use_report_dates():
    """An Advance Auto-style calendar: a 16-week first quarter (112 days),
    then three of 12 weeks (196, 280, 364 days). Q1 is 21 days off the
    grid; with the report dates all four are placed, in fiscal 2022
    (Jan 1, 2022 to Dec 31, 2022)."""
    year_ends = ends("2021-01-02", "2022-01-01", "2022-12-31", "2023-12-30")
    quarter_ends = ["2022-04-23", "2022-07-16", "2022-10-08", "2022-12-31"]
    reports = ends(*quarter_ends)
    assert quarterly.assign_quarter("2022-04-23", year_ends) is None
    for end, quarter in zip(quarter_ends, [1, 2, 3, 4]):
        assert quarterly.assign_quarter(end, year_ends, reports) == (
            2022,
            quarter,
        )


def test_report_dates_never_remove_a_grid_quarter():
    """A grid quarter end is still placed when the company's report dates
    do not include it (for example, a 10-Q missing from submissions),
    and an off-quarter date far from every report date is still None."""
    year_ends = ends("2023-12-31", "2024-12-31", "2025-12-31")
    reports = ends("2024-03-31", "2024-12-31")
    assert quarterly.assign_quarter("2024-06-30", year_ends, reports) == (
        2024,
        2,
    )
    assert quarterly.assign_quarter("2024-02-14", year_ends, reports) is None


def test_off_quarter_period_end_is_not_placed():
    """A period ending 45 days after a year end is not a quarter end."""
    year_ends = ends("2023-12-31", "2024-12-31", "2025-12-31")
    assert quarterly.assign_quarter("2024-02-14", year_ends) is None


def test_year_ends_are_extended_beyond_the_10ks():
    """With 10-K year ends for FY2015 and FY2016 only, a 10-Q quarter in
    fiscal 2018 (after the last 10-K) still gets a quarter."""
    financials = pd.DataFrame(
        {
            "cik": [7, 7],
            "fiscal_year": [2015, 2016],
            "period_end": pd.to_datetime(["2015-12-31", "2016-12-31"]),
        }
    )
    year_ends = quarterly.fiscal_year_ends(financials)[7]
    assert quarterly.assign_quarter("2018-06-30", year_ends) == (2018, 2)


# ---------------------------------------------------------------------------
# Reading one company's facts
# ---------------------------------------------------------------------------
def fake_company():
    """Return a companyfacts JSON with revenue reported several ways:
    a 3-month 10-Q value, a 6-month year-to-date 10-Q value, the 10-K
    annual total, a 4-month value (dropped), an 8-K value (dropped), and
    a 10-Q whose fy field (2099) is wrong (ignored)."""
    revenue = [
        {
            "start": "2024-01-01",
            "end": "2024-03-31",
            "val": 100.0,
            "accn": "q1",
            "form": "10-Q",
            "filed": "2024-05-01",
            "fy": 2099,
        },
        {
            "start": "2024-01-01",
            "end": "2024-06-30",
            "val": 210.0,
            "accn": "q2",
            "form": "10-Q",
            "filed": "2024-08-01",
            "fy": 2024,
        },
        {
            "start": "2024-01-01",
            "end": "2024-12-31",
            "val": 440.0,
            "accn": "k1",
            "form": "10-K",
            "filed": "2025-02-20",
            "fy": 2024,
        },
        {
            "start": "2024-01-01",
            "end": "2024-04-29",
            "val": 130.0,
            "accn": "x1",
            "form": "10-Q",
            "filed": "2024-05-01",
            "fy": 2024,
        },
        {
            "start": "2024-01-01",
            "end": "2024-03-31",
            "val": 100.0,
            "accn": "e1",
            "form": "8-K",
            "filed": "2024-04-15",
            "fy": 2024,
        },
    ]
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": revenue}}}}}


def test_company_rows_keep_quarterly_facts():
    """The 3-month, 6-month and 12-month values are kept with fiscal 2024
    quarters 1, 2 and 4 (from the period end, not the wrong fy field);
    the 4-month and 8-K values are dropped and counted."""
    drops = Counter()
    year_ends = ends("2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31")
    rows = quarterly.company_rows(
        1, fake_company(), facts.mapped_tag_regex(), {1: year_ends}, drops
    )
    kept = rows.sort_values("filed_date")
    assert kept["accession"].tolist() == ["q1", "q2", "k1"]
    assert kept["fiscal_year"].tolist() == [2024, 2024, 2024]
    assert kept["fiscal_quarter"].tolist() == [1, 2, 4]
    assert kept["duration_days"].tolist() == [91, 182, 366]
    assert drops[quarterly.DROP_DURATION] == 1
    assert drops[quarterly.DROP_FORM] == 1


def test_company_without_a_10k_year_end_is_counted():
    """A company with no fiscal year ends from 10-Ks cannot be placed."""
    drops = Counter()
    rows = quarterly.company_rows(
        2, fake_company(), facts.mapped_tag_regex(), {}, drops
    )
    assert rows.empty
    assert drops[quarterly.DROP_NO_YEAR_END] == 3


# ---------------------------------------------------------------------------
# The original
# ---------------------------------------------------------------------------
def test_earliest_filing_is_original_and_10q_is_not_an_amendment():
    """For one period: a 10-Q filed May 1 is the original, before a later
    10-K comparative. On a tie, a 10-Q is not treated as an amendment (the
    lower accession wins between two originals), but a 10-Q/A loses to
    its 10-Q."""

    def chosen(rows):
        return pd.DataFrame(
            [
                {
                    "cik": 1,
                    "line_item": "revenue",
                    "period_start": date(2024, 1, 1),
                    "period_end": date(2024, 3, 31),
                    "form": form,
                    "accession": accn,
                    "filed_date": date.fromisoformat(filed),
                }
                for form, accn, filed in rows
            ]
        )

    def original(rows):
        marked = quarterly.mark_is_original_quarterly(chosen(rows))
        return marked.loc[marked["is_original"], "accession"].tolist()

    assert original(
        [("10-K", "k1", "2025-02-20"), ("10-Q", "q1", "2024-05-01")]
    ) == ["q1"]
    assert original(
        [("10-Q/A", "a1", "2024-05-01"), ("10-Q", "z9", "2024-05-01")]
    ) == ["z9"]
    assert original(
        [("10-K", "k2", "2024-05-01"), ("10-Q", "a0", "2024-05-01")]
    ) == ["a0"]


def test_report_period_ends_reads_10q_and_10k_dates(tmp_path):
    """Report dates come from 10-Q and 10-K filings in the "recent" list
    and the overflow files; 8-K dates and blanks are ignored, duplicates
    are kept once, and a company not in the file is left out."""
    recent = {
        "form": ["10-Q", "10-K", "8-K", "10-Q", "10-Q/A"],
        "reportDate": [
            "2024-03-31",
            "2024-12-31",
            "2024-02-14",
            "",
            "2024-03-31",
        ],
    }
    overflow = {"form": ["10-Q"], "reportDate": ["2023-09-30"]}
    submission = {
        "filings": {
            "recent": recent,
            "files": [{"name": "CIK0000000001-submissions-001.json"}],
        }
    }
    zip_path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("CIK0000000001.json", json.dumps(submission))
        archive.writestr(
            "CIK0000000001-submissions-001.json", json.dumps(overflow)
        )
    found = quarterly.report_period_ends(zip_path, [1, 2])
    assert list(found) == [1]
    assert found[1].strftime("%Y-%m-%d").tolist() == [
        "2023-09-30",
        "2024-03-31",
        "2024-12-31",
    ]


def test_excluded_companies_are_left_out():
    """Only companies not excluded in the companies table are built."""
    companies = pd.DataFrame(
        {"cik": [1, 2, 3], "is_excluded": [False, True, False]}
    )
    assert quarterly.included_ciks(companies) == [1, 3]
