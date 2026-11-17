"""Tests for src/scores/verdicts.py (f_band and flags_raised)."""

import pandas as pd

from src.scores import verdicts


def test_f_band_edges():
    """0 and 3 weak; 4 and 6 middle; 7 and 9 strong; no score -> NA.
    The edges come from config (weak <= 3, strong >= 7)."""
    scores = pd.Series([0, 3, 4, 6, 7, 9, pd.NA], dtype="Int64")
    bands = verdicts.f_band(scores)
    assert bands.tolist()[:6] == [
        "weak",
        "weak",
        "middle",
        "middle",
        "strong",
        "strong",
    ]
    assert bands[6] is pd.NA
    assert str(bands.dtype) == "string"


def test_flags_raised_counts_each_warning():
    """Row 0: all three warn -> 3. Row 1: none warn -> 0.
    Row 2: only the Z'' distress zone -> 1."""
    m_flags = pd.array([True, False, False], dtype="boolean")
    z_zones = pd.array(["distress", "safe", "distress"], dtype="string")
    f_bands = pd.array(["weak", "strong", "middle"], dtype="string")
    result = verdicts.flags_raised(
        pd.Series(m_flags), pd.Series(z_zones), pd.Series(f_bands)
    )
    assert result.tolist() == [3, 0, 1]
    assert str(result.dtype) == "Int64"


def test_missing_check_counts_as_no_warning_but_all_missing_is_na():
    """Row 0: no M-Score, Z'' distress, no F-Score -> 1 (the one check
    that exists warns). Row 1: no check has a score -> NA, not 0,
    because 0 would claim an all-clear that was never tested."""
    m_flags = pd.Series(pd.array([pd.NA, pd.NA], dtype="boolean"))
    z_zones = pd.Series(pd.array(["distress", pd.NA], dtype="string"))
    f_bands = pd.Series(pd.array([pd.NA, pd.NA], dtype="string"))
    result = verdicts.flags_raised(m_flags, z_zones, f_bands)
    assert result[0] == 1
    assert result[1] is pd.NA


def test_fixture_verdicts_in_scores_table(
    financials_fixture, facts_long_fixture
):
    """Fixture FY2023, by hand from the module tests:
    Steady Co: F 4 -> middle; M -2.48 not flagged; Z'' 4.35 safe -> 0.
    Stretch Co: F 2 -> weak; M -2.66 not flagged; Z'' 0.75 distress
    -> 2 warnings. Service Co: no M or F; Z'' 3.47 safe -> 0."""
    from src.scores import build_scores
    from tests.test_build_scores import make_companies

    companies = make_companies([(101, 3571), (102, 3571), (103, 3571)])
    scores_df, _ = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies
    )
    fy2023 = scores_df[scores_df.fiscal_year == 2023].set_index("cik")
    assert fy2023.loc[101, "f_band"] == "middle"
    assert fy2023.loc[101, "flags_raised"] == 0
    assert fy2023.loc[102, "f_band"] == "weak"
    assert fy2023.loc[102, "flags_raised"] == 2
    assert fy2023.loc[103, "f_band"] is pd.NA
    assert fy2023.loc[103, "flags_raised"] == 0
