"""Tests for src/scores/common.py (prior-year matching, safe division,
tie-aware comparisons and missing_inputs notes)."""

import numpy as np
import pandas as pd
import pytest

from src.scores import common


def test_with_prior_years_matches_exact_prior_year(financials_fixture):
    """Revenue_prior is the t-1 row's revenue (Steady Co: 1,100M)."""
    frame = common.with_prior_years(financials_fixture, ["revenue"], 2)
    steady_2023 = frame[(frame.cik == 101) & (frame.fiscal_year == 2023)]
    assert steady_2023["revenue_prior"].item() == 1100e6
    assert steady_2023["revenue_prior2"].item() == 1000e6


def test_with_prior_years_never_borrows_an_older_year(financials_fixture):
    """With FY2022 deleted, FY2023 has NO prior year (not FY2021).

    A two-year change is not the one-year change the formulas define.
    """
    gap_df = financials_fixture[financials_fixture.fiscal_year != 2022]
    frame = common.with_prior_years(gap_df, ["revenue"], 1)
    fy2023 = frame[frame.fiscal_year == 2023]
    assert fy2023["revenue_prior"].isna().all()
    assert not fy2023["has_row_prior"].any()


def test_with_prior_years_rejects_duplicate_company_years(
    financials_fixture,
):
    """Two rows for one company-year would make 't-1' ambiguous."""
    doubled = pd.concat([financials_fixture, financials_fixture.head(1)])
    with pytest.raises(ValueError):
        common.with_prior_years(doubled, ["revenue"], 1)


def test_safe_divide_zero_gives_nan_not_infinity():
    """10/0 is NaN (not inf); 10/4 = 2.5; NaN/2 stays NaN."""
    result = common.safe_divide(
        pd.Series([10.0, 10.0, np.nan]), pd.Series([0.0, 4.0, 2.0])
    )
    assert np.isnan(result[0]) and not np.isinf(result[0])
    assert result[1] == 2.5
    assert np.isnan(result[2])


def test_is_higher_tie_missing_and_rounding():
    """Strictly higher only; NA if missing; tiny rounding gap is a tie.

    Rows: 2 vs 1 -> True; 1 vs 1 -> False (tie earns no point);
    1 vs NaN -> NA; 0.11 + 1e-15 vs 0.11 -> False (within tolerance).
    """
    result = common.is_higher(
        pd.Series([2.0, 1.0, 1.0, 0.11 + 1e-15]),
        pd.Series([1.0, 1.0, np.nan, 0.11]),
        tolerance=1e-9,
    )
    assert result[0] == True  # noqa: E712
    assert result[1] == False  # noqa: E712
    assert result[2] is pd.NA
    assert result[3] == False  # noqa: E712
    assert str(result.dtype) == "boolean"


def test_is_positive_keeps_missing_as_na():
    """-5 -> False, 0 -> False, 3 -> True, NaN -> NA (not False)."""
    result = common.is_positive(pd.Series([-5.0, 0.0, 3.0, np.nan]))
    assert result.tolist()[:3] == [False, False, True]
    assert result[3] is pd.NA


def test_build_notes_joins_reasons_and_is_null_when_complete():
    """Row 0 gets both reasons in order; row 1 gets none (NA)."""
    index = pd.RangeIndex(2)
    notes = common.build_notes(
        index,
        [
            (pd.Series([True, False]), "sga_t"),
            (pd.Series([True, False]), "no_row_t-1"),
            (pd.Series([True, False]), "sga_t"),  # repeat is dropped
        ],
    )
    assert notes[0] == "sga_t; no_row_t-1"
    assert notes[1] is pd.NA


def test_combine_notes_merges_without_repeats():
    """Notes from two modules merge in order, each reason once."""
    combined = common.combine_notes(
        pd.Series(["no_row_t-1; sga_t", pd.NA], dtype="string"),
        pd.Series(["no_row_t-1", pd.NA], dtype="string"),
    )
    assert combined[0] == "no_row_t-1; sga_t"
    assert combined[1] is pd.NA
