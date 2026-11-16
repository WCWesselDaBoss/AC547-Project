"""Tests for src/scores/altman.py. Hand values from the fixture grid."""

import numpy as np
import pandas as pd
import pytest

from src.scores import altman
from tests.conftest import row, set_value

APPROX = 1e-6


def test_steady_co_ratios_and_score(financials_fixture):
    """Steady Co FY2023:
    X1 = (484 - 242)/1210 = 0.2;  X2 = 363/1210 = 0.3
    X3 = 181.5/1210 = 0.15;       X4 = 605/605 = 1.0
    Z'' = 6.56(.2) + 3.26(.3) + 6.72(.15) + 1.05(1) = 4.348 -> safe
    """
    result = row(altman.compute_altman(financials_fixture), 101, 2023)
    assert result["z_x1"] == pytest.approx(0.2, abs=APPROX)
    assert result["z_x2"] == pytest.approx(0.3, abs=APPROX)
    assert result["z_x3"] == pytest.approx(0.15, abs=APPROX)
    assert result["z_x4"] == pytest.approx(1.0, abs=APPROX)
    assert result["z_score"] == pytest.approx(4.348, abs=APPROX)
    assert result["z_zone"] == "safe"


def test_stretch_co_loss_year_is_distress(financials_fixture):
    """Stretch Co FY2023 (operating loss):
    X1 = (300 - 300)/800 = 0;     X2 = 150/800 = 0.1875
    X3 = -25/800 = -0.03125;      X4 = 200/600 = 0.33333
    Z'' = 0 + 0.61125 - 0.21 + 0.35 = 0.75125 -> distress
    """
    result = row(altman.compute_altman(financials_fixture), 102, 2023)
    assert result["z_x3"] == pytest.approx(-0.03125, abs=APPROX)
    assert result["z_score"] == pytest.approx(0.75125, abs=APPROX)
    assert result["z_zone"] == "distress"


def test_zone_boundaries_fall_in_grey():
    """2.60 and 1.10 exactly are grey; just above 2.60 is safe; just
    below 1.10 is distress; no score -> no zone."""
    zones = altman.z_zone(pd.Series([2.60, 2.6001, 1.10, 1.0999, np.nan]))
    assert zones.tolist()[:4] == ["grey", "safe", "grey", "distress"]
    assert zones[4] is pd.NA


def test_zero_total_liabilities_blanks_x4(financials_fixture):
    """Edge case: TL = 0 makes X4 = equity/0 undefined -> NaN, no Z."""
    set_value(financials_fixture, 101, 2023, "total_liabilities", 0.0)
    result = row(altman.compute_altman(financials_fixture), 101, 2023)
    assert np.isnan(result["z_x4"])
    assert np.isnan(result["z_score"])
    assert result["z_zone"] is pd.NA
    assert "z_x4_zero_denominator" in result["altman_notes"]


def test_missing_retained_earnings_blanks_score(financials_fixture):
    """A missing input is never treated as 0: X2 and Z'' are blank."""
    set_value(financials_fixture, 101, 2023, "retained_earnings", np.nan)
    result = row(altman.compute_altman(financials_fixture), 101, 2023)
    assert np.isnan(result["z_x2"])
    assert np.isnan(result["z_score"])
    assert result["altman_notes"] == "retained_earnings_t"
