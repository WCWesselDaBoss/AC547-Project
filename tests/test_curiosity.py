"""Tests for src/curiosity/vol_matched.py, each checkable by hand."""

import numpy as np
import pandas as pd
import pytest

from src.curiosity import vol_matched as vm


def test_volatility_on_a_five_day_series():
    """Closes 100, 110, 99, 108.9, 98.01: each day +10% or -10%.
    Log returns: ln(1.1) = 0.095310, ln(0.9) = -0.105361, again twice.
    Mean = -0.005025; each return is 0.100335 from the mean, so the
    sample variance = 4 x 0.100335^2 / 3 = 0.013423 and the daily
    standard deviation = 0.115857. Annualized: x sqrt(252) = 15.8745
    -> 1.8392 (184% a year)."""
    closes = pd.Series([100.0, 110.0, 99.0, 108.9, 98.01])
    returns = np.log(closes / closes.shift(1)).iloc[1:]
    volatility = vm.trailing_volatility(returns, min_returns=4)
    assert volatility == pytest.approx(1.8392, abs=1e-4)


def test_too_few_returns_gives_no_volatility():
    """200 returns are required by default; 4 give NaN."""
    assert np.isnan(vm.trailing_volatility([0.01, -0.02, 0.03, 0.0]))


def test_clipping_caps_extreme_returns():
    """With bounds (-0.1, 0.1), returns -0.5 and 0.5 count as -0.1 and
    0.1, so the result equals the volatility of [-0.1, 0.01, 0.02, 0.1]."""
    raw = [-0.5, 0.01, 0.02, 0.5]
    clipped = vm.trailing_volatility(raw, bounds=(-0.1, 0.1), min_returns=4)
    expected = np.std([-0.1, 0.01, 0.02, 0.1], ddof=1) * np.sqrt(252)
    assert clipped == pytest.approx(expected)


def test_window_returns_skip_missing_days():
    """A missing close on one day blanks the two returns that would use
    it, rather than stretching one return over two days. Start is the
    6th day, so the window is days 1-5 (plus day 0 for the first return)."""
    days = pd.bdate_range("2024-01-01", periods=8).astype("datetime64[ns]")
    calendar = pd.DatetimeIndex(days)
    prices = pd.Series([100, 101, np.nan, 103, 104, 105, 106, 107.0], days)
    returns = vm.window_returns(prices, calendar, days[6])
    assert len(returns) == 5  # days 1 to 5
    assert returns.isna().tolist() == [False, True, True, False, False]
    assert returns.iloc[0] == pytest.approx(np.log(101 / 100))


def test_buckets_on_ten_values():
    """Values 1 to 10 in quintiles: two per bucket."""
    buckets, cutoffs = vm.assign_buckets(range(1, 11))
    assert buckets.tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert len(cutoffs) == 6
    assert cutoffs[0] == 1 and cutoffs[-1] == 10


def test_barrier_formula():
    """sigma = 0.5, d = 0.3, 2 years: ln(0.7) = -0.35667;
    0.5 x sqrt(2) = 0.70711; ratio -0.50441; N(-0.50441) = 0.30699;
    P = 2 x 0.30699 = 0.6140."""
    assert float(vm.barrier_probability(0.5, 0.3)) == pytest.approx(
        0.6140, abs=1e-4
    )
    # Very calm stocks almost never touch -30%; very wild ones almost
    # always do.
    assert float(vm.barrier_probability(0.01, 0.3)) < 1e-6
    assert float(vm.barrier_probability(50.0, 0.3)) > 0.99


def make_bucket_frame():
    """Three buckets; drops on day 100, everyone else followed to day
    730, so each 24-month share is simply drops / observations.
    Bucket 1: Clean 6 of 30 (20%), Flagged 12 of 30 (40%).
    Bucket 2: Clean 4 of 40 (10%), Flagged 2 of 10: too few Flagged.
    Bucket 3: Clean 12 of 60 (20%), Flagged 9 of 30 (30%)."""
    rows = []
    for bucket, group, n, drops in [
        (1, "clean", 30, 6),
        (1, "flagged", 30, 12),
        (2, "clean", 40, 4),
        (2, "flagged", 10, 2),
        (3, "clean", 60, 12),
        (3, "flagged", 30, 9),
    ]:
        for i in range(n):
            dropped = i < drops
            rows.append((bucket, group, dropped, 100 if dropped else 730))
    frame = pd.DataFrame(
        rows, columns=["bucket", "group", "event", "duration_days"]
    )
    frame["event"] = frame["event"].astype("boolean")
    return frame


def test_within_bucket_gaps_and_adjusted_gap():
    """Gaps: bucket 1 +20 points (ratio 2.0), bucket 3 +10 points
    (ratio 1.5); bucket 2 is too few to compare and left out. Adjusted
    gap = (20 x 60 + 10 x 90) / (60 + 90) = 2,100 / 150 = 14 points."""
    table = vm.within_bucket(make_bucket_frame(), "bucket").set_index("bucket")
    assert table.loc[1, "gap_pts"] == pytest.approx(20.0)
    assert table.loc[1, "ratio"] == pytest.approx(2.0)
    assert table.loc[3, "gap_pts"] == pytest.approx(10.0)
    assert bool(table.loc[2, "too_few_to_compare"])
    assert not table.loc[[1, 3], "too_few_to_compare"].any()
    assert vm.adjusted_gap(table.reset_index()) == pytest.approx(14.0)


def test_benchmark_compares_actual_with_predicted():
    """Two Clean stocks, both with volatility 0.5, so each is predicted
    to touch -30% with chance 0.614; one did. Actual 50%, predicted
    61.4%, actual / predicted = 0.5 / 0.614 = 0.814."""
    frame = pd.DataFrame(
        {
            "group": ["clean", "clean"],
            "tier": ["0 flags", "0 flags"],
            "volatility": [0.5, 0.5],
            "event": pd.array([True, False], dtype="boolean"),
        }
    )
    row = vm.benchmark_table(frame, 0.3).set_index("group").loc["Clean"]
    assert row["pct_actual"] == pytest.approx(50.0)
    assert row["pct_predicted"] == pytest.approx(61.40, abs=0.01)
    assert row["actual_over_predicted"] == pytest.approx(0.8143, abs=1e-3)


def test_cox_direction_on_made_up_data():
    """A sanity check, not a hand calculation (a Cox fit has no closed
    form): when flagged stocks drop at twice the rate of clean stocks
    with the same volatility, the hazard ratio comes out near 2 with an
    interval that excludes 1."""
    rng = np.random.default_rng(7)
    n = 600
    flagged = rng.integers(0, 2, n)
    volatility = np.exp(rng.normal(-1.0, 0.3, n))
    rate = np.exp(np.log(2) * flagged + np.log(volatility)) / 400
    time = rng.exponential(1 / rate)
    frame = pd.DataFrame(
        {
            "group": np.where(flagged == 1, "flagged", "clean"),
            "volatility": volatility,
            "duration_days": np.minimum(time, 730),
            "event": pd.array(time < 730, dtype="boolean"),
            "cik": rng.integers(0, 150, n),
        }
    )
    result = vm.cox_flagged(frame)
    assert 1.5 < result["hazard_ratio_flagged"] < 2.7
    assert result["ci_low"] > 1
    assert result["companies"] == frame["cik"].nunique()
