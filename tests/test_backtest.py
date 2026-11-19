"""Tests for src/scores/backtest.py on a hand-checkable example.

Two periods, two longs and two shorts each. Every price change happens
on one day, so each value can be checked by hand:

Period 1 (2021-06-30 to 2022-06-30, 365 days): long A, B; short C, D.
  A 10 -> 12 on 2022-01-03 (+20%)      B 20 flat (0%)
  C 50 -> 40 on 2022-01-03 (-20%)      D 10 -> 15 on 2021-12-31, then
                                       delisted (+50%, covered at 15)
  SPY 400 flat (0%).
Period 2 (2022-06-30 to 2023-06-30, 365 days): long A, B; short C, E.
  A 12 -> 13.2 on 2023-01-03 (+10%)   B 20 -> 18 on 2023-01-03 (-10%)
  C 40 -> 30 on 2023-01-03 (-25%)     E 8 flat (0%)
  SPY 400 -> 420 on 2023-01-03 (+5%).
"""

import pandas as pd
import pytest

from src.scores import backtest

DAYS = pd.bdate_range("2021-06-01", "2023-06-30").astype("datetime64[ns]")
FORMATION = ["2021-06-30", "2022-06-30"]
JAN_2022 = pd.Timestamp("2022-01-03")
JAN_2023 = pd.Timestamp("2023-01-03")


def stock(ticker, steps, last_day=None):
    """Return a price series that starts at steps[0][1] and changes to
    each later (date, price) on that date."""
    days = DAYS if last_day is None else DAYS[DAYS <= last_day]
    prices = pd.Series(steps[0][1], index=days, dtype="float64")
    for date, price in steps[1:]:
        prices[prices.index >= date] = price
    return pd.DataFrame(
        {"ticker": ticker, "date": days, "adj_close": prices.to_numpy()}
    )


def make_prices():
    """Return the example prices table (section 4 columns and types)."""
    frames = [
        stock("SPY", [(None, 400.0), (JAN_2023, 420.0)]),
        stock("A", [(None, 10.0), (JAN_2022, 12.0), (JAN_2023, 13.2)]),
        stock("B", [(None, 20.0), (JAN_2023, 18.0)]),
        stock("C", [(None, 50.0), (JAN_2022, 40.0), (JAN_2023, 30.0)]),
        stock(
            "D",
            [(None, 10.0), (pd.Timestamp("2021-12-31"), 15.0)],
            last_day="2021-12-31",
        ),
        stock("E", [(None, 8.0)]),
    ]
    prices = pd.concat(frames, ignore_index=True)
    return prices.astype({"ticker": "string"})


def make_picks():
    """Return the picks: formation_date, leg, ticker."""
    rows = [
        ("2021-06-30", "long", "A"),
        ("2021-06-30", "long", "B"),
        ("2021-06-30", "short", "C"),
        ("2021-06-30", "short", "D"),
        ("2022-06-30", "long", "A"),
        ("2022-06-30", "long", "B"),
        ("2022-06-30", "short", "C"),
        ("2022-06-30", "short", "E"),
    ]
    picks = pd.DataFrame(rows, columns=["formation_date", "leg", "ticker"])
    picks["formation_date"] = pd.to_datetime(picks["formation_date"])
    return picks


def setup():
    """Return (price table, periods) for the example."""
    prices = make_prices()
    calendar = backtest.trading_calendar(prices)
    periods = backtest.holding_periods(calendar, FORMATION)
    return backtest.price_table(prices, calendar), periods


def run(weights, cost_bps=0, borrow_rate=0.0):
    """Run the example portfolio; return (summary, daily path)."""
    price_wide, periods = setup()
    return backtest.run_portfolio(
        price_wide,
        make_picks(),
        periods,
        weights,
        cost_bps,
        borrow_rate,
        100_000.0,
    )


def test_periods_run_from_formation_to_next_formation():
    """The final period ends on the last price date (2023-06-30)."""
    _, periods = setup()
    assert list(periods["start"]) == list(
        pd.to_datetime(["2021-06-30", "2022-06-30"])
    )
    assert list(periods["end"]) == list(
        pd.to_datetime(["2022-06-30", "2023-06-30"])
    )


def test_formation_on_a_weekend_uses_the_prior_trading_day():
    """2022-07-02 is a Saturday, so the trade is on Friday 2022-07-01."""
    calendar = backtest.trading_calendar(make_prices())
    periods = backtest.holding_periods(calendar, ["2022-07-02"])
    assert periods["start"].iloc[0] == pd.Timestamp("2022-07-01")


def test_strategy_values_without_costs():
    """Period 1: long 50,000 -> A 30,000 + B 25,000 = 55,000; shorts
    owe C 20,000 + D 37,500 = 57,500. Value = 100,000 + 55,000 - 57,500
    = 97,500.
    Period 2 (rebalanced, 48,750 a leg): long 0% -> 48,750; shorts owe
    C 18,281.25 + E 24,375 = 42,656.25. Value = 97,500 + 48,750 -
    42,656.25 = 103,593.75."""
    summary, _ = run((0.5, 0.5))
    assert summary["end_value"].tolist() == pytest.approx(
        [97_500.0, 103_593.75]
    )
    assert summary["period_return"].tolist() == pytest.approx([-0.025, 0.0625])
    assert summary["n_long"].tolist() == [2, 2]
    assert summary["n_short"].tolist() == [2, 2]


def test_strategy_values_with_costs_and_borrow_fee():
    """20 bps per trade, 1% a year borrow, 365-day periods.
    Period 1: entry 0.002 x 100,000 = 200; exit 0.002 x (55,000 +
    57,500) = 225; borrow 0.01 x 50,000 = 500.
    End = 97,500 - 925 = 96,575.
    Period 2 on 96,575: gross = 96,575 x 1.0625 = 102,610.9375; entry
    0.002 x 96,575 = 193.15; exit 0.002 x (48,287.5 + 42,251.5625) =
    181.078125; borrow 0.01 x 48,287.5 = 482.875.
    End = 101,753.834375."""
    summary, _ = run((0.5, 0.5), cost_bps=20, borrow_rate=0.01)
    assert summary["end_value"].tolist() == pytest.approx(
        [96_575.0, 101_753.834375]
    )
    assert summary["trading_cost"].tolist() == pytest.approx(
        [425.0, 374.228125]
    )
    assert summary["borrow_cost"].tolist() == pytest.approx([500, 482.875])


def test_each_leg_alone():
    """Long only, 100,000: P1 A 60,000 + B 50,000 = 110,000; P2 0% ->
    110,000. Short only, 100,000 (50,000 a stock): P1 owes C 40,000 +
    D 75,000 = 115,000 -> 100,000 cash + 100,000 proceeds - 115,000 =
    85,000. P2 +12.5% -> 85,000 x 1.125 = 95,625."""
    long_summary, _ = run((1.0, 0.0))
    short_summary, _ = run((0.0, 1.0))
    assert long_summary["end_value"].tolist() == pytest.approx(
        [110_000.0, 110_000.0]
    )
    assert short_summary["end_value"].tolist() == pytest.approx(
        [85_000.0, 95_625.0]
    )
    assert long_summary["n_short"].tolist() == [0, 0]


def test_delisted_short_is_covered_at_its_last_price():
    """D stops trading on 2021-12-31 at 15: covered there, +50%."""
    price_wide, periods = setup()
    period = periods.iloc[0]
    _, positions, _ = backtest.simulate_period(
        price_wide,
        ["A", "B"],
        ["C", "D"],
        period.start,
        period.end,
        100_000.0,
        (0.5, 0.5),
        0,
        0.0,
    )
    d_row = positions.set_index("ticker").loc["D"]
    assert bool(d_row["delisted"])
    assert d_row["exit_date"] == pd.Timestamp("2021-12-31")
    assert d_row["exit_price"] == 15.0
    assert d_row["stock_return"] == pytest.approx(0.5)
    assert positions["delisted"].sum() == 1


def test_missing_entry_price_is_an_error():
    """A stock with no price on the start day cannot be bought."""
    price_wide, periods = setup()
    period = periods.iloc[1]
    with pytest.raises(ValueError):
        backtest.simulate_period(
            price_wide,
            ["D"],
            [],
            period.start,
            period.end,
            100_000.0,
            (1.0, 0.0),
            0,
            0.0,
        )


def test_drawdown_and_annualized_return():
    """Path: 100,000 until D jumps on 2021-12-31 (shorts owe 12,500
    more) -> 87,500, the trough: drawdown -12.5%. Total return 2 years
    (730 days): 103,593.75 / 100,000 - 1 = 3.59375%; annualized =
    1.0359375 ** 0.5 - 1."""
    summary, daily = run((0.5, 0.5))
    assert daily.loc["2021-12-31"] == pytest.approx(87_500.0)
    assert backtest.max_drawdown(daily) == pytest.approx(-0.125)
    start, end = summary["start"].iloc[0], summary["end"].iloc[-1]
    assert backtest.total_return(100_000.0, daily.iloc[-1]) == (
        pytest.approx(0.0359375)
    )
    assert backtest.annualized_return(
        100_000.0, daily.iloc[-1], start, end
    ) == pytest.approx(1.0359375**0.5 - 1)
