"""Tests for the functions that produce the counts in logs and README.

Covers financials.summary_log, prices.scored_companies,
sample.company_profiles and the tag coverage report in tag_coverage.py.
Every expected number below can be worked out by hand from the inputs.
"""

import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline import financials, prices, sample, tag_coverage, tag_map

SUBMISSIONS_FIXTURE = Path(__file__).parent / "fixtures" / "sec" / "financials"

# ---- financials.summary_log ----------------------------------------------


def make_financials(rows):
    """Build financials rows (fy, revenue, assets, passes, derived) with
    every other line item missing."""
    financials_df = pd.DataFrame(
        rows,
        columns=[
            "fiscal_year",
            "revenue",
            "total_assets",
            "passes_size_floor",
            "derived_items",
        ],
    )
    for item in tag_map.LINE_ITEMS:
        if item not in financials_df:
            financials_df[item] = np.nan
    return financials_df


def test_summary_log_counts():
    """FY2011 is prior-year only; FY2012-14 give one pass, one fail and
    one untestable year; missing and derived counts use passing years."""
    financials_df = make_financials(
        [
            (2011, 5e8, 9e8, True, None),
            (2012, 2e8, 9e8, True, "income_continuing_ops"),
            (2013, 1e6, 2e6, False, None),
            (2014, np.nan, np.nan, False, None),
        ]
    )
    log = {"dropped:duplicate_fiscal_year_label": 3}
    summary = financials.summary_log(financials_df, log)
    counts = dict(zip(summary["measure"], summary["count"]))
    assert counts["dropped:duplicate_fiscal_year_label"] == 3
    assert counts["kept:company_years_fy2011_prior_year_only"] == 1
    assert counts["kept:company_years_fy2012_on"] == 3
    assert counts["size_floor:pass"] == 1
    assert counts["size_floor:fail"] == 1
    assert counts["size_floor:untestable_no_revenue_or_assets"] == 1
    # Only the FY2012 row passes: revenue present, sga missing.
    assert counts["missing_in_size_floor_years:revenue"] == 0
    assert counts["missing_in_size_floor_years:sga"] == 1
    assert counts["derived_in_size_floor_years:income_continuing_ops"] == 1


# ---- prices.scored_companies and sample.company_profiles -----------------

COMPANIES = pd.DataFrame(
    {
        "cik": [1, 2, 3],
        "name": ["One", "Two", "Three"],
        "sic": pd.array([3571, 2834, 7372], dtype="Int64"),
        "ticker": ["AAA", None, "CCC"],
    }
)
FINANCIALS = pd.DataFrame(
    {
        "cik": [1, 1, 1, 1, 2, 2, 2, 3],
        "fiscal_year": [2011, 2013, 2015, 2016, 2013, 2014, 2015, 2014],
        # Company 3 never passes, so it is not a scored company.
        "passes_size_floor": [
            True,
            True,
            True,
            False,
            True,
            True,
            True,
            False,
        ],
        "filed_date": pd.to_datetime(
            [
                "2012-02-01",
                "2014-02-01",
                "2016-02-01",
                "2017-02-01",
                "2014-03-01",
                "2015-03-01",
                "2016-03-01",
                "2015-03-01",
            ]
        ),
    }
)


def test_scored_companies_windows():
    """Company 1: passing FY2013 and FY2015 (FY2011 ignored), last 10-K
    FY2016. Company 3 never passes and is left out."""
    scored = prices.scored_companies(COMPANIES, FINANCIALS).set_index("cik")
    assert sorted(scored.index) == [1, 2]
    assert scored.loc[1, "first_filed"] == pd.Timestamp("2014-02-01")
    assert scored.loc[1, "last_filed"] == pd.Timestamp("2016-02-01")
    assert scored.loc[1, "last_10k_fiscal_year"] == 2016


def test_company_profiles_order_division_and_prices():
    """Company 2 (3 passing years) sorts before company 1 (2 years);
    divisions come from the SIC's first digit; only AAA has prices."""
    prices_df = pd.DataFrame(
        {
            "ticker": "AAA",
            "date": pd.date_range("2014-01-01", "2026-11-10", freq="D"),
            "adj_close": 1.0,
        }
    )
    profiles = sample.company_profiles(COMPANIES, FINANCIALS, prices_df)
    assert profiles["cik"].tolist() == [2, 1]
    assert profiles["passing_years"].tolist() == [3, 2]
    assert profiles["sic_division"].tolist() == [2, 3]
    assert profiles["has_prices"].tolist() == [False, True]


# ---- tag_coverage report --------------------------------------------------


def test_ten_k_company_years_from_submissions(tmp_path):
    """Company 20's fixture: 10-Ks for FY2024 and FY2023, and two 10-Ks
    labeled FY2021 (earlier kept). Amendments and 10-Qs are ignored."""
    zip_path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for json_path in SUBMISSIONS_FIXTURE.glob("*.json"):
            archive.write(json_path, arcname=json_path.name)
    years = tag_coverage.ten_k_company_years(zip_path, [20])
    assert years["fiscal_year"].tolist() == [2021, 2023, 2024]
    assert years["report_date"].iloc[0] == date(2021, 12, 31)


def coverage_fact(cik, tag, value, end, period="duration", filed="2025-02-01"):
    """Return one candidate-fact row for the coverage tests."""
    return {
        "cik": cik,
        "tag": tag,
        "unit": "USD",
        "period_type": period,
        "period_end": date.fromisoformat(end),
        "fiscal_year": int(end[:4]),
        "value": value,
        "filed_date": date.fromisoformat(filed),
    }


YEARS = pd.DataFrame(
    {
        "cik": [1, 2],
        "fiscal_year": [2024, 2024],
        "report_date": [date(2024, 12, 31), date(2024, 12, 31)],
    }
)


def test_match_facts_to_years_uses_7_day_window():
    """A Dec 31 fact matches; a Sept 30 fact in the same year does not."""
    facts_df = pd.DataFrame(
        [
            coverage_fact(1, "Revenues", 100.0, "2024-12-31"),
            coverage_fact(1, "Assets", 9.0, "2024-09-30", period="instant"),
        ]
    )
    matched = tag_coverage.match_facts_to_years(YEARS, facts_df)
    assert matched["tag"].tolist() == ["Revenues"]


def test_facts_for_line_item_filters_and_keeps_earliest():
    """Revenue keeps duration USD facts only, earliest filing per tag."""
    matched = pd.DataFrame(
        [
            coverage_fact(
                1, "Revenues", 105.0, "2024-12-31", filed="2026-02-01"
            ),
            coverage_fact(
                1, "Revenues", 100.0, "2024-12-31", filed="2025-02-01"
            ),
            coverage_fact(1, "Revenues", 7.0, "2024-12-31", period="instant"),
        ]
    )
    item_facts = tag_coverage.facts_for_line_item(matched, "revenue")
    assert item_facts["value"].tolist() == [100.0]


def test_coverage_row_counts_and_switches():
    """4 company-years, 3 found (75%), tags A, B, A with one switch."""
    years = pd.DataFrame(
        {"cik": [1, 1, 2, 3], "fiscal_year": [2023, 2024, 2024, 2024]}
    )
    winners = pd.DataFrame(
        {
            "cik": [1, 1, 2],
            "fiscal_year": [2023, 2024, 2024],
            "tag": ["A", "B", "A"],
        }
    )
    row = tag_coverage.coverage_row(years, winners, "revenue")
    assert row["found"] == 3
    assert row["pct_found"] == 75.0
    assert row["tag_switch_pairs"] == 1
    assert row["found_by_tag"] == "A=2; B=1"


def test_candidate_rows_fill_and_agreement():
    """SalesRevenueGoodsNet fills 1 of 3 company-years (33.3%) and agrees
    with the mapped value in 1 of the 2 years both exist (50%)."""
    years = pd.DataFrame({"cik": [1, 1, 2], "fiscal_year": [2023, 2024, 2024]})
    winners = pd.DataFrame(
        {"cik": [1, 2], "fiscal_year": [2024, 2024], "value": [100.0, 200.0]}
    )
    candidates = pd.DataFrame(
        {
            "cik": [1, 2, 1],
            "fiscal_year": [2024, 2024, 2023],
            "tag": ["SalesRevenueGoodsNet"] * 3,
            "value": [100.0, 150.0, 90.0],
        }
    )
    rows = tag_coverage.candidate_rows(years, candidates, winners, "revenue")
    assert rows == [
        {
            "line_item": "revenue",
            "candidate_tag": "SalesRevenueGoodsNet",
            "fills_missing": 1,
            "pct_gain": 33.3,
            "both_reported": 2,
            "agree_pct": 50.0,
        }
    ]


def test_build_report_coverage_with_derivations():
    """Company 1 reports revenue and net income; company 2 nothing.
    Revenue is 50% found; continuing-ops income is 0% tagged but 50%
    after the derivation from net income."""
    facts_df = pd.DataFrame(
        [
            coverage_fact(1, "Revenues", 100.0, "2024-12-31"),
            coverage_fact(1, "NetIncomeLoss", 10.0, "2024-12-31"),
        ]
    )
    coverage, _ = tag_coverage.build_report(YEARS, facts_df)
    coverage = coverage.set_index("line_item")
    assert coverage.loc["revenue", "pct_found"] == 50.0
    assert coverage.loc["income_continuing_ops", "pct_found"] == 0.0
    assert (
        coverage.loc["income_continuing_ops", "pct_with_derivations"] == 50.0
    )


def test_wide_values_one_column_per_item():
    """Missing company-years stay as NaN columns, not dropped rows."""
    winners = {
        "revenue": pd.DataFrame(
            {"cik": [1], "fiscal_year": [2024], "value": [100.0]}
        )
    }
    wide = tag_coverage.wide_values(winners, YEARS)
    assert len(wide) == 2
    assert wide["revenue"].tolist()[0] == 100.0
    assert np.isnan(wide["revenue"].tolist()[1])
