"""Tests for src/curiosity/vol_matched.py, each checkable by hand."""

import numpy as np
import pandas as pd
import pytest

from src.curiosity import implied_vol as iv
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


# ---------------------------------------------------------------------------
# Part 2: implied volatility (src/curiosity/implied_vol.py)
# ---------------------------------------------------------------------------
WEEK = pd.DatetimeIndex(
    pd.bdate_range("2024-03-01", "2024-03-15").astype("datetime64[ns]")
)


def test_usable_rows_drop_missing_codes():
    """-99.99 strike, 0 premium and a blank volatility are all missing;
    only the complete row is usable."""
    surface = pd.DataFrame(
        {
            "impl_volatility": [0.4, np.nan, 0.4, 0.4],
            "impl_strike": [50.0, 50.0, -99.99, 50.0],
            "impl_premium": [6.0, 6.0, 6.0, 0.0],
        }
    )
    assert iv.usable_rows(surface).index.tolist() == [0]


def test_fallback_uses_two_days_earlier_never_later():
    """Start Wednesday 2024-03-06 has no row. Monday 03-04 (2 trading
    days earlier) and Thursday 03-07 (1 day later) both do: the earlier
    one is used, never the later one, even though it is closer."""
    rows = pd.DataFrame(
        {"impl_volatility": [0.30, 0.99]},
        index=pd.to_datetime(["2024-03-04", "2024-03-07"]),
    )
    row = iv.option_row(rows, WEEK, pd.Timestamp("2024-03-06"))
    assert row.name == pd.Timestamp("2024-03-04")
    assert row["impl_volatility"] == 0.30


def test_fallback_gives_up_after_five_trading_days():
    """The only row is 6 trading days before the start: no option data.
    A row only after the start is never used either."""
    rows = pd.DataFrame(
        {"impl_volatility": [0.3, 0.4]},
        index=pd.to_datetime(["2024-03-01", "2024-03-14"]),
    )
    assert iv.option_row(rows, WEEK, pd.Timestamp("2024-03-11")) is None


def test_fallback_prefers_the_start_day():
    """A usable row on the start day itself is used first."""
    rows = pd.DataFrame(
        {"impl_volatility": [0.3, 0.5]},
        index=pd.to_datetime(["2024-03-05", "2024-03-06"]),
    )
    row = iv.option_row(rows, WEEK, pd.Timestamp("2024-03-06"))
    assert row["impl_volatility"] == 0.5


def test_name_check():
    """Punctuation, case and corporate words are ignored; a name cut off
    at 28 characters still matches by containment; unrelated names do
    not."""
    assert iv.clean_name("The Apple, Inc.") == "APPLE"
    assert iv.names_match("Apple Inc.", "APPLE INC")
    assert iv.names_match(
        "International Business Machines Corp", "INTERNATIONAL BUSINESS MACHI"
    )
    assert iv.names_match("Spectrum Brands Holdings, Inc.", "SPECTRUM BRANDS")
    assert not iv.names_match("Apple Inc.", "APPLIED MATERIALS INC")
    assert not iv.names_match("Cencora, Inc.", "CORE SCIENTIFIC INC")


def test_name_in_effect_on_a_date():
    """Names effective 2010 and 2020: on 2015 the 2010 name applies; on
    2021 the 2020 name; before 2010 there is none."""
    names = pd.DataFrame(
        {
            "secid": [1, 1],
            "effect_date": pd.to_datetime(["2010-01-01", "2020-01-01"]),
            "issuer": ["OLD NAME CO", "NEW NAME CO"],
        }
    )
    assert iv.name_on(names, 1, pd.Timestamp("2015-06-30")) == "OLD NAME CO"
    assert iv.name_on(names, 1, pd.Timestamp("2021-06-30")) == "NEW NAME CO"
    assert iv.name_on(names, 1, pd.Timestamp("2005-06-30")) is None


def make_match_inputs():
    """Ticker XYZ has two secids: 10 (named Xyzzy Corp) and 20 (named
    Other Things Inc). Ticker ABC has one secid, 30, whose name does not
    match. Ticker NOP is not in WRDS."""
    obs = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "fiscal_year": [2020, 2020, 2020],
            "ticker": ["XYZ", "ABC", "NOP"],
            "start": pd.to_datetime(["2021-03-01"] * 3),
        }
    )
    sec_names = {1: "Xyzzy Corp", 2: "Abacus Robotics Inc", 3: "Nop Inc"}
    names = pd.DataFrame(
        {
            "secid": [10, 20, 30],
            "effect_date": pd.to_datetime(["2015-01-01"] * 3),
            "issuer": ["XYZZY CORP", "OTHER THINGS INC", "ABC GOLD MINES"],
        }
    )
    by_ticker = {"XYZ": [10, 20], "ABC": [30]}
    return obs, sec_names, by_ticker, names


def test_two_secids_resolved_by_name_and_rejections_counted():
    """XYZ: only secid 10's name passes, so it is used. ABC's name fails
    and goes to the review file. NOP has no WRDS ticker."""
    obs, sec_names, by_ticker, names = make_match_inputs()
    matches, review = iv.match_observations(
        obs, sec_names, by_ticker, names, approved=set()
    )
    matches = matches.set_index("cik")
    assert matches.loc[1, "secid"] == 10
    assert matches.loc[2, "reject_reason"] == iv.REJECT_NAME
    assert matches.loc[3, "reject_reason"] == iv.REJECT_NO_WRDS_TICKER
    assert set(zip(review["cik"], review["secid"])) == {(1, 20), (2, 30)}


def test_hand_approval_turns_a_review_pair_into_a_match():
    """Approving (2, 30) by hand makes ABC a match; approving the second
    XYZ secid (1, 20) makes XYZ ambiguous, so it is rejected."""
    obs, sec_names, by_ticker, names = make_match_inputs()
    matches, _ = iv.match_observations(
        obs, sec_names, by_ticker, names, approved={(2, 30), (1, 20)}
    )
    matches = matches.set_index("cik")
    assert matches.loc[2, "secid"] == 30
    assert matches.loc[1, "reject_reason"] == iv.REJECT_AMBIGUOUS


def test_review_file_keeps_earlier_approvals(tmp_path):
    """Rewriting the review file keeps the approved marks and notes."""
    path = tmp_path / "name_review.csv"
    review = pd.DataFrame(
        {
            "cik": [2],
            "ticker": ["ABC"],
            "secid": [30],
            "sec_name": ["A"],
            "wrds_name": ["B"],
            "similarity": [0.1],
        }
    )
    iv.write_review(review, path)
    marked = pd.read_csv(path)
    marked["approved"] = "yes"
    marked["review_note"] = "checked by hand"
    marked.to_csv(path, index=False)
    iv.write_review(review, path)
    assert iv.approved_pairs(path) == {(2, 30)}
    assert pd.read_csv(path)["review_note"].tolist() == ["checked by hand"]


def test_put_payoff_at_expiry():
    """Strike 50, price 35 at expiry, premium 6: payoff 50 - 35 = 15;
    return (15 - 6) / 6 = +150%. At a price of 55 the put expires
    worthless: payoff 0, return -100%."""
    assert iv.put_return_at_expiry(50.0, 35.0, 6.0) == pytest.approx(
        (15.0, 1.5)
    )
    assert iv.put_return_at_expiry(50.0, 55.0, 6.0) == pytest.approx(
        (0.0, -1.0)
    )


def test_exit_rule_on_a_fake_price_path():
    """Price ratios 0.95, 0.85, 0.72, 0.70, 0.60: the first close at or
    below 70% of the reference is position 3 (exactly 0.70). A path that
    never gets there has no early exit (held to expiry)."""
    assert iv.first_exit_day([0.95, 0.85, 0.72, 0.70, 0.60]) == 3
    assert iv.first_exit_day([0.95, 0.9, 0.8, 0.71]) is None


def test_black_scholes_put():
    """Textbook value: price 100, strike 100, one year, 20% volatility,
    zero rate and dividend: 100 x (2N(0.1) - 1) = 7.9656. Intrinsic
    value (here 0) is never above it, and with no time left the value is
    the intrinsic value."""
    value = iv.black_scholes_put(100.0, 100.0, 1.0, 0.2)
    assert value == pytest.approx(7.9656, abs=1e-4)
    assert iv.black_scholes_put(80.0, 100.0, 0.0, 0.2) == 20.0
    assert iv.black_scholes_put(80.0, 100.0, 1.0, 0.2) >= 20.0


def test_review_helpers_flag_renames_but_approve_nothing():
    """Company 1 was renamed (its former SEC name is the WRDS name);
    secid 20's own history later carries company 2's SEC name; company
    3 matches neither (a reused ticker). The helpers only add columns:
    the approved column is untouched by them."""
    review = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "secid": [10, 20, 30],
            "sec_name": ["Ecovyst Inc.", "Magnite, Inc.", "Everpure, Inc."],
            "wrds_name": [
                "PQ GROUP HOLDINGS INC",
                "RUBICON PROJ INC",
                "PANDORA MEDIA INC",
            ],
        }
    )
    former = {1: ["PQ Group Holdings Inc."], 2: [], 3: []}
    names = pd.DataFrame(
        {
            "secid": [10, 20, 20, 30],
            "effect_date": pd.to_datetime(
                ["2017-01-01", "2014-01-01", "2020-07-01", "2011-01-01"]
            ),
            "issuer": [
                "PQ GROUP HOLDINGS INC",
                "RUBICON PROJ INC",
                "MAGNITE INC",
                "PANDORA MEDIA INC",
            ],
        }
    )
    helped = iv.add_review_helpers(review, former, names).set_index("cik")
    assert helped["former_sec_name_matches"].tolist() == [True, False, False]
    assert helped["wrds_history_has_sec_name"].tolist() == [False, True, False]
    assert helped.loc[1, "sec_former_names"] == "PQ Group Holdings Inc."
    assert "approved" not in helped.columns


def test_option_data_falls_back_per_delta():
    """Start Wednesday 2024-03-06. Delta -50 has a row that day; delta
    -25 only on Monday 03-04 (2 trading days earlier) and Thursday 03-07
    (later, never used). Secid 7 is an ADR. Each delta falls back on its
    own."""
    surface = pd.DataFrame(
        {
            "secid": [7, 7, 7],
            "date": pd.to_datetime(["2024-03-06", "2024-03-04", "2024-03-07"]),
            "delta": [-50, -25, -25],
            "impl_volatility": [0.40, 0.45, 0.99],
            "impl_strike": [50.0, 40.0, 41.0],
            "impl_premium": [6.0, 2.0, 2.5],
            "issue_type": ["F", "F", "F"],
        }
    )
    matched = pd.DataFrame(
        {
            "cik": [1],
            "fiscal_year": [2023],
            "secid": [7],
            "start": [pd.Timestamp("2024-03-06")],
        }
    )
    row = iv.option_data(matched, surface, WEEK).iloc[0]
    assert row["option_date_50"] == pd.Timestamp("2024-03-06")
    assert row["iv_50"] == 0.40
    assert row["option_date_25"] == pd.Timestamp("2024-03-04")
    assert (row["strike_25"], row["premium_25"]) == (40.0, 2.0)
    assert bool(row["is_adr"])


def test_tradeability_counts():
    """Three observations: a Clean one matched with both deltas, a
    2-flag one matched with delta -50 only, and a 3-flag one not
    matched."""
    obs = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "fiscal_year": 2023,
            "group": ["clean", "flagged", "flagged"],
            "tier": ["0 flags", "2 flags", "3 flags"],
        }
    )
    matches = pd.DataFrame(
        {"cik": [1, 2, 3], "fiscal_year": 2023, "secid": [10, 20, None]}
    )
    options = pd.DataFrame(
        {
            "cik": [1, 2],
            "fiscal_year": 2023,
            "iv_50": [0.3, 0.5],
            "iv_25": [0.35, np.nan],
        }
    )
    table = iv.tradeability(obs, matches, options).set_index("group")
    assert table.loc["Clean"].tolist() == [1, 1, 1, 1]
    assert table.loc["Flagged"].tolist() == [2, 1, 1, 0]
    assert table.loc["2 flags"].tolist() == [1, 1, 1, 0]
    assert table.loc["3 flags"].tolist() == [1, 0, 0, 0]
