"""Tests for the About page figures (app/about_view.py).

Fixture scores (tests/fixtures/build_app_fixtures.py): 9 company-years,
3 companies, FY2021 to FY2023. M-Score exists for 4 rows (Steady Co and
Stretch Co FY2022, FY2023), F-Score for 2, Z'' for all 9.
"""

import pandas as pd

import config
from app import about_view, labels


def read_fixture(table):
    """Read one app fixture table."""
    return pd.read_parquet(config.APP_FIXTURE_DIR / f"{table}.parquet")


def test_data_summary_counts_the_loaded_tables():
    """Counts and latest filing date come from the data, not the page."""
    summary = about_view.data_summary(
        read_fixture("scores"), read_fixture("financials_annual")
    )
    assert summary == {
        "companies": 3,
        "company_years": 9,
        "first_year": 2021,
        "last_year": 2023,
        "latest_filing": pd.Timestamp("2024-02-20"),
    }


def test_coverage_table_reports_each_score():
    """M 4 of 9, Z'' 9 of 9, F 2 of 9 in the fixture."""
    table = about_view.coverage_table(read_fixture("scores")).set_index(
        "Score"
    )
    assert table.loc[
        labels.CHECK_NAMES["m"], "Company-years with a score"
    ] == ("4 of 9")
    assert table.loc[labels.CHECK_NAMES["z"], "Share"] == "100%"
    assert table.loc[labels.CHECK_NAMES["f"], "Share"] == "22%"


def test_neutral_substitutions_match_whole_codes():
    """A code counts only as a whole item, never as part of another."""
    scores_df = pd.DataFrame(
        {
            "missing_inputs": pd.array(
                ["sgai_set_to_1; sga_t", "xsgai_set_to_1", None],
                dtype="string",
            )
        }
    )
    table = about_view.neutral_substitution_table(scores_df).set_index(
        "Substitution"
    )
    assert table.iloc[0]["Company-years"] == "1 of 3"
    assert table.iloc[1]["Company-years"] == "0 of 3"


def test_percent_handles_empty_tables():
    """No rows gives 0%, not a division error."""
    assert about_view.percent(0, 0) == "0%"
    assert about_view.percent(1, 3) == "33%"
