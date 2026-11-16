"""Tests for src/scores/build_scores.py on the hand-checkable fixture."""

import pandas as pd
import pytest

from src.scores import build_scores
from tests.conftest import row, set_value


def make_companies(ciks_and_sics):
    """Return a companies table (section 4 types) for the given CIKs."""
    return pd.DataFrame(
        {
            "cik": pd.array([cik for cik, _ in ciks_and_sics], "int64"),
            "name": pd.array(
                [f"Company {cik}" for cik, _ in ciks_and_sics], "string"
            ),
            "sic": pd.array([sic for _, sic in ciks_and_sics], "Int64"),
            "sic_description": pd.array(
                ["Test"] * len(ciks_and_sics), "string"
            ),
            "ticker": pd.array([pd.NA] * len(ciks_and_sics), "string"),
            "is_excluded": False,
            "exclusion_reason": pd.array(
                [pd.NA] * len(ciks_and_sics), "string"
            ),
        }
    )


@pytest.fixture
def companies_fixture():
    """All three fixture companies in SIC 3571 (one industry)."""
    return make_companies([(101, 3571), (102, 3571), (103, 3571)])


def test_scores_table_has_contract_columns_and_types(
    financials_fixture, facts_long_fixture, companies_fixture
):
    """Columns in section 4 order with the agreed types."""
    scores_df, _ = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies_fixture
    )
    assert list(scores_df.columns) == build_scores.SCORES_COLUMNS
    for column, dtype in build_scores.SCORES_TYPES.items():
        assert str(scores_df[column].dtype) == dtype, column


def test_scores_match_module_results(
    financials_fixture, facts_long_fixture, companies_fixture
):
    """Merging must not shift values between companies: spot-check the
    hand-calculated numbers from the module tests."""
    scores_df, _ = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies_fixture
    )
    steady = row(scores_df, 101, 2023)
    assert steady["m_score"] == pytest.approx(-2.48438, abs=1e-6)
    assert steady["z_score"] == pytest.approx(4.348, abs=1e-6)
    assert steady["f_score"] == 4
    assert row(scores_df, 102, 2022)["m_flag"] == True  # noqa: E712


def test_missing_inputs_combines_module_notes(
    financials_fixture, facts_long_fixture, companies_fixture
):
    """Service Co FY2023: COGS missing (M and F) appears once; complete
    rows (Steady Co FY2023) have a null missing_inputs."""
    scores_df, _ = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies_fixture
    )
    service = row(scores_df, 103, 2023)["missing_inputs"]
    assert service.split("; ").count("cost_of_revenue_t") == 1
    assert row(scores_df, 101, 2023)["missing_inputs"] is pd.NA


def test_three_companies_fall_back_to_industry_peers(
    financials_fixture, facts_long_fixture, companies_fixture
):
    """3 companies < 5: everyone is ranked in 'SIC 35' (size 3).
    FY2023 z_scores: Stretch 0.75 < Service 3.47 < Steady 4.35, so
    percentiles 0, 50, 100."""
    scores_df, _ = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies_fixture
    )
    fy2023 = scores_df[scores_df.fiscal_year == 2023].set_index("cik")
    assert (fy2023["peer_group"] == "SIC 35").all()
    assert (fy2023["peer_group_size"] == 3).all()
    assert fy2023["z_score_pctile"].to_dict() == {
        101: 100.0,
        102: 0.0,
        103: 50.0,
    }


def test_unscored_rows_are_counted_not_silently_dropped(
    financials_fixture, facts_long_fixture, companies_fixture, monkeypatch
):
    """FY2021 rows act as prior years only (first scored year set to
    2022 here), one row fails the size floor, and one company is
    excluded. Each is counted once and the counts add up."""
    monkeypatch.setattr(build_scores.config, "FIRST_FISCAL_YEAR", 2022)
    set_value(financials_fixture, 101, 2022, "passes_size_floor", False)
    companies_fixture.loc[companies_fixture.cik == 103, "is_excluded"] = True
    scores_df, log_rows = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies_fixture
    )
    log = dict(log_rows)
    assert log["not_scored_prior_year_only_before_first_year"] == 3
    assert log["not_scored_company_excluded_or_no_sic"] == 2  # 103: 22, 23
    assert log["not_scored_fails_size_floor"] == 1  # 101 FY2022
    assert log["scored_company_years"] == 3  # 101 FY23, 102 FY22, FY23
    assert len(scores_df) == 3
    dropped = sum(v for k, v in log.items() if k.startswith("not_scored"))
    assert dropped + log["scored_company_years"] == log["financials_rows"]


def test_below_floor_year_still_serves_as_prior_year(
    financials_fixture, facts_long_fixture, companies_fixture
):
    """Section 4: a row failing the floor is not scored but can still be
    t-1. Steady Co FY2023's M-Score is unchanged when FY2022 fails."""
    set_value(financials_fixture, 101, 2022, "passes_size_floor", False)
    scores_df, _ = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies_fixture
    )
    assert row(scores_df, 101, 2023)["m_score"] == pytest.approx(
        -2.48438, abs=1e-6
    )
