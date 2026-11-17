"""Tests for src/scores/drivers.py and src/scores/explanations.py.

Contributions are worked by hand from the fixture's M-Score indexes
(tests/test_beneish.py): coefficient x (index - 1), or coefficient x
TATA for TATA.
"""

import numpy as np
import pandas as pd
import pytest

from src.scores import build_scores, drivers, explanations
from tests.conftest import row
from tests.test_build_scores import make_companies

APPROX = 1e-6


@pytest.fixture
def fixture_scores(financials_fixture, facts_long_fixture):
    """Return the scores table built from the 3-company fixture."""
    companies = make_companies([(101, 3571), (102, 3571), (103, 3571)])
    scores_df, _ = build_scores.build_scores(
        financials_fixture, facts_long_fixture, companies
    )
    return scores_df


def drivers_for(drivers_df, cik, fiscal_year):
    """Return one company-year's driver rows, in rank order."""
    return drivers_df[
        (drivers_df["cik"] == cik) & (drivers_df["fiscal_year"] == fiscal_year)
    ].reset_index(drop=True)


def test_baseline_is_no_change_m_score():
    """-4.84 + .920 + .528 + .404 + .892 + .115 - .172 - .327 = -2.48:
    the M-Score of a company whose ratios are unchanged and whose
    profit equals its cash."""
    assert drivers.m_score_baseline() == pytest.approx(-2.48, abs=APPROX)


def test_stretch_co_fy2022_top_three(fixture_scores):
    """Stretch Co FY2022 contributions:
    DSRI .920 x (2.0 - 1)    = 0.920   <- 1
    GMI  .528 x (1.2 - 1)    = 0.1056
    AQI  .404 x (1.25 - 1)   = 0.101
    SGI  .892 x (1.5 - 1)    = 0.446   <- 3
    DEPI .115 x (1.0 - 1)    = 0
    SGAI -.172 x (0.6667 - 1) = 0.0573
    TATA 4.679 x 0.10        = 0.4679  <- 2
    LVGI -.327 x (1.25 - 1)  = -0.0818
    Top three: DSRI, TATA, SGI."""
    result = drivers_for(
        drivers.build_score_drivers(fixture_scores), 102, 2022
    )
    assert result["component"].tolist() == ["DSRI", "TATA", "SGI"]
    assert result["driver_rank"].tolist() == [1, 2, 3]
    assert result["contribution"].tolist() == pytest.approx(
        [0.920, 0.4679, 0.446], abs=APPROX
    )
    assert result["component_value"].tolist() == pytest.approx(
        [2.0, 0.10, 1.5], abs=APPROX
    )


def test_stretch_co_fy2023_loss_year(fixture_scores):
    """Stretch Co FY2023 contributions:
    DSRI .920 x 0 = 0; GMI .528 x 0.6667 = 0.352;
    AQI .404 x 0.2 = 0.0808; SGI .892 x -0.2 = -0.178;
    DEPI .115 x 0.03636 = 0.00418; SGAI -.172 x 0.5 = -0.086;
    TATA 4.679 x -0.05 = -0.234; LVGI -.327 x 0.375 = -0.123.
    Positive: GMI, AQI, DEPI (exactly three)."""
    result = drivers_for(
        drivers.build_score_drivers(fixture_scores), 102, 2023
    )
    assert result["component"].tolist() == ["GMI", "AQI", "DEPI"]
    assert result["contribution"].tolist() == pytest.approx(
        [0.528 * 2 / 3, 0.404 * 0.2, 0.115 * (0.090909 / 0.087719 - 1)],
        abs=1e-5,
    )


def test_steady_co_has_one_driver(fixture_scores):
    """Steady Co FY2023: every ratio index is 1 except SGI (1.1), and
    TATA is -0.02. Only SGI is positive: .892 x 0.1 = 0.0892."""
    result = drivers_for(
        drivers.build_score_drivers(fixture_scores), 101, 2023
    )
    assert result["component"].tolist() == ["SGI"]
    assert result["contribution"].item() == pytest.approx(0.0892, APPROX)


def test_rounding_noise_is_not_a_driver():
    """An index of 1 + 1e-15 (rounding noise around 'no change') gives a
    contribution of about 1e-15, below config.DRIVER_MIN_CONTRIBUTION,
    so it is not reported. DSRI 1.1 (.920 x 0.1 = 0.092) still is."""
    scores_df = pd.DataFrame(
        {
            "cik": [1],
            "fiscal_year": [2023],
            "m_score": [-2.4],
            "dsri": [1.1],
            "gmi": [1 + 1e-15],
            "aqi": [1.0],
            "sgi": [1.0],
            "depi": [1.0],
            "sgai": [1.0],
            "tata": [0.0],
            "lvgi": [1.0],
        }
    )
    result = drivers.build_score_drivers(scores_df)
    assert result["component"].tolist() == ["DSRI"]


def test_no_m_score_means_no_drivers(fixture_scores):
    """Service Co has no M-Score (no cost of revenue): no driver rows,
    even though its other indexes exist."""
    result = drivers.build_score_drivers(fixture_scores)
    assert (result["cik"] != 103).all()


def test_no_positive_contribution_gives_no_rows():
    """Edge case: every component at or below 'no change' in the
    warning direction (ratios <= 1, TATA < 0, SGAI and LVGI >= 1):
    the company-year gets no driver rows. A neutral SGAI of exactly 1
    contributes 0 and is never a driver."""
    scores_df = pd.DataFrame(
        {
            "cik": [1],
            "fiscal_year": [2023],
            "m_score": [-3.0],
            "dsri": [0.9],
            "gmi": [0.95],
            "aqi": [1.0],
            "sgi": [0.8],
            "depi": [1.0],
            "sgai": [1.0],
            "tata": [-0.05],
            "lvgi": [1.2],
        }
    )
    assert drivers.build_score_drivers(scores_df).empty


def test_contributions_add_up_to_m_score(fixture_scores):
    """M = baseline + sum of all 8 contributions, for every fixture
    company-year with an M-Score."""
    contribution_df = drivers.contributions(fixture_scores)
    total = contribution_df[list(drivers.COMPONENTS)].sum(axis=1)
    m_scores = fixture_scores.loc[contribution_df.index, "m_score"]
    assert (drivers.m_score_baseline() + total).tolist() == pytest.approx(
        m_scores.tolist(), abs=APPROX
    )


def test_every_component_has_an_approved_sentence(fixture_scores):
    """All 8 components have a sentence, and each driver row carries
    exactly the approved text for its component."""
    assert set(explanations.COMPONENT_SENTENCES) == set(
        drivers.COMPONENTS.values()
    )
    result = drivers.build_score_drivers(fixture_scores)
    for component, sentence in zip(result["component"], result["explanation"]):
        assert sentence == explanations.explain(component)
    with pytest.raises(KeyError):
        explanations.explain("XYZ")


def test_driver_table_contract_types(fixture_scores):
    """Columns and types match CLAUDE.md section 4."""
    result = drivers.build_score_drivers(fixture_scores)
    assert list(result.columns) == drivers.DRIVER_COLUMNS
    for column, dtype in drivers.DRIVER_TYPES.items():
        assert str(result[column].dtype) == dtype
    assert (result["contribution"] > 0).all()
    assert result["driver_rank"].between(1, 3).all()
    assert not np.isinf(result["contribution"]).any()
