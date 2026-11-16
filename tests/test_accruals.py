"""Tests for src/scores/accruals.py. Hand values from the fixture grid."""

import numpy as np
import pytest

from src.scores import accruals
from tests.conftest import row, set_value

APPROX = 1e-6


def test_steady_co_accruals_and_cash_conversion(financials_fixture):
    """Steady Co FY2023:
    accruals = (121 - 145.2) / ((1210 + 1100)/2) = -24.2/1155 = -0.020952
    cash conversion = 145.2 / 121 = 1.2
    """
    result = row(accruals.compute_accruals(financials_fixture), 101, 2023)
    assert result["accruals_ratio"] == pytest.approx(-24.2 / 1155, APPROX)
    assert result["cash_conversion"] == pytest.approx(1.2, abs=APPROX)


def test_stretch_co_profit_not_backed_by_cash(financials_fixture):
    """Stretch Co FY2022: accruals = (100 - 20)/((800+500)/2) = 80/650
    = 0.123077 (high); cash conversion = 20/100 = 0.2 (low)."""
    result = row(accruals.compute_accruals(financials_fixture), 102, 2022)
    assert result["accruals_ratio"] == pytest.approx(80 / 650, abs=APPROX)
    assert result["cash_conversion"] == pytest.approx(0.2, abs=APPROX)


def test_negative_net_income_blanks_cash_conversion(financials_fixture):
    """Edge case: Stretch Co FY2023 loses 50. CFO/NI = -10/-50 = +0.2
    would look healthy, so it is blank, with a stated reason. The
    accruals ratio still works: (-50 - -10)/800 = -0.05."""
    result = row(accruals.compute_accruals(financials_fixture), 102, 2023)
    assert np.isnan(result["cash_conversion"])
    assert result["accruals_notes"] == "net_income_not_positive"
    assert result["accruals_ratio"] == pytest.approx(-0.05, abs=APPROX)


def test_zero_net_income_blanks_cash_conversion(financials_fixture):
    """Net income exactly 0 -> blank, not a divide-by-zero error."""
    set_value(financials_fixture, 101, 2023, "net_income", 0.0)
    result = row(accruals.compute_accruals(financials_fixture), 101, 2023)
    assert np.isnan(result["cash_conversion"])


def test_missing_prior_year_blanks_accruals_only(financials_fixture):
    """Edge case: Steady Co FY2021 has no FY2020 row, so average assets
    cannot be formed and the accruals ratio is blank. Cash conversion
    uses year t only, so it is still 120/100 = 1.2."""
    result = row(accruals.compute_accruals(financials_fixture), 101, 2021)
    assert np.isnan(result["accruals_ratio"])
    assert result["cash_conversion"] == pytest.approx(1.2, abs=APPROX)
    assert result["accruals_notes"] == "no_row_t-1"
