"""Tests for src/scores/piotroski.py. Hand values from the fixture grid.

Reminder: ROA uses BEGINNING assets, so year t needs total assets for
t-1, and the prior year's ROA needs t-2. Only FY2023 has all three.
"""

import numpy as np
import pandas as pd
import pytest

from src.scores import piotroski
from tests.conftest import row, set_value


def scores(financials_df, facts_long_df):
    """Run the F-Score on the given fixture tables."""
    return piotroski.compute_piotroski(financials_df, facts_long_df)


def signal_values(result):
    """Return the 9 signals of a result row as a list."""
    return [result[name] for name in piotroski.SIGNAL_COLUMNS]


def test_steady_co_ties_earn_no_points(financials_fixture, facts_long_fixture):
    """Steady Co FY2023:
    1 ROA = 121/1100 = 0.11 > 0                         True
    2 CFO = 145.2 > 0                                   True
    3 ROA 0.11 vs prior 110/1000 = 0.11 (tie)           False
    4 CFO/beg. assets = 145.2/1100 = 0.132 > 0.11       True
    5 LTD/avg TA 363/1155 = 0.3143 vs 330/1050 = 0.3143 False (tie)
    6 current ratio 484/242 = 2 vs 440/220 = 2          False (tie)
    7 shares 100M vs 100M in same 10-K (not higher)     True
    8 gross margin 0.40 vs 0.40                         False (tie)
    9 turnover 1210/1100 = 1.1 vs 1100/1000 = 1.1       False (tie)
    F = 4
    """
    result = row(scores(financials_fixture, facts_long_fixture), 101, 2023)
    assert signal_values(result) == [
        True,
        True,
        False,
        True,
        False,
        False,
        True,
        False,
        False,
    ]
    assert result["f_score"] == 4
    assert result["piotroski_notes"] is pd.NA


def test_stretch_co_loss_year(financials_fixture, facts_long_fixture):
    """Stretch Co FY2023 (negative net income):
    1 ROA = -50/800 = -0.0625                           False
    2 CFO = -10                                         False
    3 ROA -0.0625 vs 100/500 = 0.20                     False
    4 CFO/beg. assets = -10/800 = -0.0125 > -0.0625     True
    5 LTD/avg TA 250/800 = 0.3125 vs 200/650 = 0.3077   False (rose)
    6 current ratio 300/300 = 1.0 vs 350/200 = 1.75     False
    7 shares 120M vs FY2022 as restated in THIS 10-K:
      120M (split-adjusted) -> not higher               True
    8 gross margin 0.20 vs 0.3333                       False
    9 turnover 600/800 = 0.75 vs 750/500 = 1.5          False
    F = 2
    """
    result = row(scores(financials_fixture, facts_long_fixture), 102, 2023)
    assert signal_values(result) == [
        False,
        False,
        False,
        True,
        False,
        False,
        True,
        False,
        False,
    ]
    assert result["f_score"] == 2


def test_stock_split_is_not_share_issuance(
    financials_fixture, facts_long_fixture
):
    """The trap section 4 warns about: comparing 120M (FY2023) with the
    ORIGINAL FY2022 figure of 60M would say shares doubled. The
    same-filing figure (120M) correctly shows no issuance."""
    frame = piotroski.prepare_frame(financials_fixture, facts_long_fixture)
    stretch_2023 = row(frame, 102, 2023)
    assert stretch_2023["shares_outstanding_prior"] == 60e6  # original
    assert stretch_2023[piotroski.PRIOR_SHARES] == 120e6  # same filing
    assert row(scores(financials_fixture, facts_long_fixture), 102, 2023)[
        "f_no_new_shares"
    ]


def test_real_issuance_fails_signal_7(financials_fixture, facts_long_fixture):
    """Stretch Co FY2022: 60M vs 50M in the same 10-K -> issued shares."""
    result = row(scores(financials_fixture, facts_long_fixture), 102, 2022)
    assert result["f_no_new_shares"] == False  # noqa: E712


def test_missing_prior_year_gives_no_f_score(
    financials_fixture, facts_long_fixture
):
    """Edge case: FY2022 has no FY2020 row (t-2), so ROA_t-1, leverage
    t-1 and turnover t-1 cannot be formed. Signals 3, 5, 9 are NA and
    the F-Score is NA rather than a score out of 6."""
    result = row(scores(financials_fixture, facts_long_fixture), 101, 2022)
    assert result["f_roa_improved"] is pd.NA
    assert result["f_asset_turnover_up"] is pd.NA
    assert result["f_score"] is pd.NA
    assert result["piotroski_notes"] == "no_row_t-2"


def test_missing_cost_of_revenue_gives_no_f_score(
    financials_fixture, facts_long_fixture
):
    """Service Co FY2023 has 8 determinable signals (7 True), but signal
    8 needs COGS, so F is NA (section 5: no exception for COGS)."""
    result = row(scores(financials_fixture, facts_long_fixture), 103, 2023)
    assert result["f_gross_margin_up"] is pd.NA
    assert result["f_score"] is pd.NA
    assert "cost_of_revenue_t" in result["piotroski_notes"]


def test_missing_long_term_debt_counts_zero_points(
    financials_fixture, facts_long_fixture
):
    """Section 5 exception: LTD missing -> signal 5 NA, worth 0 points,
    F still computed. Steady Co FY2023 stays at 4 and is flagged."""
    set_value(financials_fixture, 101, 2023, "long_term_debt", np.nan)
    result = row(scores(financials_fixture, facts_long_fixture), 101, 2023)
    assert result["f_leverage_down"] is pd.NA
    assert result["f_score"] == 4
    assert "f_leverage_down_no_point" in result["piotroski_notes"]


def test_ltd_exception_never_adds_points(
    financials_fixture, facts_long_fixture
):
    """Service Co FY2023 signal 5 is True (LTD fell 90 -> 80). If LTD
    were missing, that point must be lost, not kept. Give Service Co a
    COGS so F is computable: base F counts signal 5; with LTD missing
    F is exactly one lower."""
    for year in (2021, 2022, 2023):
        set_value(financials_fixture, 103, year, "cost_of_revenue", 100e6)
    base = row(scores(financials_fixture, facts_long_fixture), 103, 2023)
    assert base["f_leverage_down"] == True  # noqa: E712
    set_value(financials_fixture, 103, 2023, "long_term_debt", np.nan)
    without = row(scores(financials_fixture, facts_long_fixture), 103, 2023)
    assert without["f_score"] == base["f_score"] - 1


def test_missing_same_filing_share_count_is_na(
    financials_fixture, facts_long_fixture
):
    """No FY2022 comparative in Steady Co's FY2023 10-K: signal 7 is NA
    (we do NOT fall back to the original FY2022 count), F is NA."""
    is_comparative = (
        (facts_long_fixture.cik == 101)
        & (facts_long_fixture.fiscal_year == 2022)
        & ~facts_long_fixture.is_original
        & (facts_long_fixture.accession.str.endswith("24-000001"))
    )
    trimmed = facts_long_fixture[~is_comparative]
    result = row(scores(financials_fixture, trimmed), 101, 2023)
    assert result["f_no_new_shares"] is pd.NA
    assert result["f_score"] is pd.NA
    assert "shares_t-1_same_filing" in result["piotroski_notes"]


def test_two_conflicting_share_counts_are_ambiguous(
    financials_fixture, facts_long_fixture
):
    """Same filing, same date, two different values -> NA, never a
    guess, with an 'ambiguous' note."""
    comparative = facts_long_fixture[
        (facts_long_fixture.cik == 101)
        & (facts_long_fixture.fiscal_year == 2022)
        & (facts_long_fixture.accession.str.endswith("24-000001"))
    ].copy()
    comparative["value"] = 999e6
    conflicted = pd.concat([facts_long_fixture, comparative])
    result = row(scores(financials_fixture, conflicted), 101, 2023)
    assert result["f_no_new_shares"] is pd.NA
    assert "shares_t-1_same_filing_ambiguous" in result["piotroski_notes"]


def test_zero_sales_blanks_gross_margin_signal(
    financials_fixture, facts_long_fixture
):
    """Edge case: revenue 0 at t -> gross margin undefined -> signal 8
    NA with a zero-denominator note, so F is NA. Turnover 0/1100 = 0 is
    a real value (False: 0 < 1.1), not a blank."""
    set_value(financials_fixture, 101, 2023, "revenue", 0.0)
    result = row(scores(financials_fixture, facts_long_fixture), 101, 2023)
    assert result["f_gross_margin_up"] is pd.NA
    assert "f_gross_margin_up_zero_denominator" in result["piotroski_notes"]
    assert result["f_asset_turnover_up"] == False  # noqa: E712
    assert result["f_score"] is pd.NA


@pytest.mark.parametrize("column", piotroski.SIGNAL_COLUMNS)
def test_signals_are_nullable_boolean(
    financials_fixture, facts_long_fixture, column
):
    """Contract type (section 4): every signal is nullable boolean."""
    result_df = scores(financials_fixture, facts_long_fixture)
    assert str(result_df[column].dtype) == "boolean"
