"""Tests for src/scores/beneish.py.

Expected values are worked by hand from tests/fixtures/build_fixtures.py
(amounts in $ millions; ratios are unit-free so millions cancel).
"""

import numpy as np
import pandas as pd
import pytest

from src.scores import beneish
from tests.conftest import row, set_value

APPROX = 1e-6


def test_steady_co_every_index_is_one_except_sgi(financials_fixture):
    """Steady Co FY2023: everything grew 10%, so ratios are unchanged.

    DSRI = (121/1210)/(110/1100) = 0.1/0.1 = 1; same logic for GMI, AQI,
    DEPI, SGAI, LVGI. SGI = 1210/1100 = 1.1.
    TATA = (121 - 145.2) / 1210 = -24.2 / 1210 = -0.02.
    """
    result = row(beneish.compute_beneish(financials_fixture), 101, 2023)
    for index_name in ["dsri", "gmi", "aqi", "depi", "sgai", "lvgi"]:
        assert result[index_name] == pytest.approx(1.0, abs=APPROX)
    assert result["sgi"] == pytest.approx(1.1, abs=APPROX)
    assert result["tata"] == pytest.approx(-0.02, abs=APPROX)


def test_steady_co_m_score_not_flagged(financials_fixture):
    """M = -4.84 + .920 + .528 + .404 + .892(1.1) + .115 - .172
           + 4.679(-0.02) - .327 = -2.48438.

    -2.48438 is below both cutoffs (-1.78 and -2.22): not flagged.
    """
    result = row(beneish.compute_beneish(financials_fixture), 101, 2023)
    assert result["m_score"] == pytest.approx(-2.48438, abs=APPROX)
    assert result["m_flag"] == False  # noqa: E712


def test_flag_depends_on_cutoff():
    """M = -2.0 sits between the cutoffs: not flagged at -1.78, flagged
    at -2.22. M exactly at the cutoff is not flagged (rule is M > cutoff).
    No score -> no flag (NA), never False."""
    m_scores = pd.Series([-2.0, -1.78, np.nan])
    default = beneish.m_flag(m_scores, cutoff=-1.78)
    strict = beneish.m_flag(m_scores, cutoff=-2.22)
    assert default.tolist()[:2] == [False, False]
    assert strict.tolist()[:2] == [True, True]
    assert default[2] is pd.NA


def test_stretch_co_fy2022_indexes(financials_fixture):
    """Stretch Co FY2022 (the aggressive year), by hand:

    DSRI = (150/750)/(50/500) = 0.2/0.1 = 2.0
    GMI  = [(500-300)/500] / [(750-500)/750] = 0.4/0.3333 = 1.2
    AQI  = [1-(350+250)/800] / [1-(200+200)/500] = 0.25/0.20 = 1.25
    SGI  = 750/500 = 1.5
    DEPI = [20/(20+200)] / [25/(25+250)] = 0.0909/0.0909 = 1.0
    SGAI = (100/750)/(100/500) = 0.1333/0.2 = 0.6667
    TATA = (100 - 20)/800 = 0.10
    LVGI = [(200+200)/800] / [(100+100)/500] = 0.5/0.4 = 1.25
    """
    result = row(beneish.compute_beneish(financials_fixture), 102, 2022)
    expected = {
        "dsri": 2.0,
        "gmi": 1.2,
        "aqi": 1.25,
        "sgi": 1.5,
        "depi": 1.0,
        "sgai": 2 / 3,
        "tata": 0.10,
        "lvgi": 1.25,
    }
    for index_name, value in expected.items():
        assert result[index_name] == pytest.approx(value, abs=APPROX)


def test_stretch_co_fy2022_is_flagged(financials_fixture):
    """M = -4.84 + .920(2) + .528(1.2) + .404(1.25) + .892(1.5)
      + .115(1) - .172(.6667) + 4.679(.1) - .327(1.25)
    = -0.463917, above -1.78 so flagged."""
    result = row(beneish.compute_beneish(financials_fixture), 102, 2022)
    assert result["m_score"] == pytest.approx(-0.463917, abs=APPROX)
    assert result["m_flag"] == True  # noqa: E712


def test_stretch_co_fy2023_loss_year(financials_fixture):
    """Negative income still gives an M-Score (no rule blanks it).

    GMI = 0.3333/0.2 = 1.6667; AQI = 0.30/0.25 = 1.2; SGI = 600/750 =
    0.8; DEPI = 0.090909/0.087719 = 1.036364; SGAI = 0.2/0.1333 = 1.5;
    TATA = (-50 - -10)/800 = -0.05; LVGI = 0.6875/0.5 = 1.375; DSRI = 1.
    M = -4.84 + .92 + .88 + .4848 + .7136 + .119182 - .258 - .23395
        - .449625 = -2.663993.
    """
    result = row(beneish.compute_beneish(financials_fixture), 102, 2023)
    assert result["tata"] == pytest.approx(-0.05, abs=APPROX)
    assert result["m_score"] == pytest.approx(-2.663993, abs=APPROX)
    assert result["m_flag"] == False  # noqa: E712


def test_missing_cost_of_revenue_blanks_gmi_and_m(financials_fixture):
    """Service Co has no COGS: GMI and M are blank, and the notes say
    why. Other indexes are still shown (e.g. SGI = 250/220 = 1.13636)."""
    result = row(beneish.compute_beneish(financials_fixture), 103, 2023)
    assert np.isnan(result["gmi"])
    assert np.isnan(result["m_score"])
    assert pd.isna(result["m_flag"])
    assert result["sgi"] == pytest.approx(250 / 220, abs=APPROX)
    assert "cost_of_revenue_t" in result["beneish_notes"]


def test_missing_sga_sets_sgai_to_one_and_still_scores(financials_fixture):
    """Section 5: missing SGA -> SGAI = 1, flagged; M still computed.

    Steady Co FY2023 already has SGAI = 1, so M stays -2.48438.
    """
    set_value(financials_fixture, 101, 2022, "sga", np.nan)
    result = row(beneish.compute_beneish(financials_fixture), 101, 2023)
    assert result["sgai"] == 1.0
    assert result["m_score"] == pytest.approx(-2.48438, abs=APPROX)
    assert "sga_t-1" in result["beneish_notes"]
    assert "sgai_set_to_1" in result["beneish_notes"]


def test_missing_long_term_debt_sets_lvgi_to_one(financials_fixture):
    """Section 5: missing LTD -> LVGI = 1, flagged.

    Stretch Co FY2022 had LVGI 1.25. Neutral LVGI changes M by
    -0.327 * (1 - 1.25) = +0.08175: -0.463917 + 0.08175 = -0.382167.
    """
    set_value(financials_fixture, 102, 2022, "long_term_debt", np.nan)
    result = row(beneish.compute_beneish(financials_fixture), 102, 2022)
    assert result["lvgi"] == 1.0
    assert result["m_score"] == pytest.approx(-0.382167, abs=APPROX)
    assert "lvgi_set_to_1" in result["beneish_notes"]


def test_neutral_value_not_used_when_other_inputs_also_missing(
    financials_fixture,
):
    """LTD AND current liabilities missing: LVGI stays NaN, no score.

    The neutral rule covers one known gap, not a broken balance sheet.
    """
    set_value(financials_fixture, 102, 2022, "long_term_debt", np.nan)
    set_value(financials_fixture, 102, 2022, "current_liabilities", np.nan)
    result = row(beneish.compute_beneish(financials_fixture), 102, 2022)
    assert np.isnan(result["lvgi"])
    assert np.isnan(result["m_score"])
    assert "lvgi_set_to_1" not in result["beneish_notes"]


def test_zero_sales_gives_blank_not_infinity(financials_fixture):
    """Edge case: revenue 0 at t. DSRI, GMI, SGAI divide by sales, so
    they are NaN (never inf) and the notes name the zero denominator."""
    set_value(financials_fixture, 101, 2023, "revenue", 0.0)
    result = row(beneish.compute_beneish(financials_fixture), 101, 2023)
    for index_name in ["dsri", "gmi", "sgai"]:
        assert np.isnan(result[index_name])
        assert f"{index_name}_zero_denominator" in result["beneish_notes"]
    # SGI = 0 / 1100 = 0 is a real (if extreme) value, not a blank.
    assert result["sgi"] == 0.0
    assert np.isnan(result["m_score"])


def test_missing_prior_year_row_gives_no_score(financials_fixture):
    """Edge case: delete Steady Co FY2022. FY2023 has no t-1 to compare
    with, so every two-year index and M are blank ("no_row_t-1")."""
    gap_df = financials_fixture[
        ~(
            (financials_fixture.cik == 101)
            & (financials_fixture.fiscal_year == 2022)
        )
    ]
    result = row(beneish.compute_beneish(gap_df), 101, 2023)
    assert np.isnan(result["dsri"])
    assert np.isnan(result["m_score"])
    # SGAI is NOT set to 1 here: the prior row is missing, not just SGA.
    assert np.isnan(result["sgai"])
    assert result["beneish_notes"] == "no_row_t-1"
    # TATA uses year t only, so it is still shown: -0.02.
    assert result["tata"] == pytest.approx(-0.02, abs=APPROX)
