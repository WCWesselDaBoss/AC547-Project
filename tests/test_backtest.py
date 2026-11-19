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

import numpy as np
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


# ---------------------------------------------------------------------------
# Choosing the legs
# ---------------------------------------------------------------------------
# (cik, ticker, fiscal_year, filed_date, flags_raised, has all 3 scores)
SCORE_ROWS = [
    (1, "A", 2020, "2021-03-01", 0, True),
    (1, "A", 2021, "2022-03-01", 0, True),
    # B's FY2020 10-K is filed ON the 2021 trade date, so 2021 uses FY2019.
    (2, "B", 2019, "2020-06-01", 0, True),
    (2, "B", 2020, "2021-06-30", 3, True),
    (3, "C", 2020, "2021-02-01", 3, True),
    (3, "C", 2021, "2022-02-01", 3, True),
    # D files no 10-K after March 2021: stale (16 months) by June 2022.
    (4, "D", 2020, "2021-03-01", 3, True),
    (5, "E", 2021, "2022-03-01", 3, True),
    (6, "F", 2020, "2021-03-01", 0, True),  # $4 stock
    (7, None, 2020, "2021-03-01", 0, True),  # no ticker
    (8, "ZZZ", 2020, "2021-03-01", 0, True),  # no prices at all
    (9, "G", 2020, "2021-03-01", 0, False),  # 0 flags, only Z''
    (10, "H", 2020, "2021-03-01", 1, True),  # 1 flag: in neither leg
    (11, "I", 2020, "2021-03-01", 0, True),  # trading since 2021-06-21
]
# 0-flag rows with all three scores are "best" (M not flagged, Z'' safe,
# F strong) except B's FY2019 10-K, whose F-Score is only middle.
NOT_BEST = {(2, 2019)}


def make_score_inputs():
    """Return (scores, financials, companies) for SCORE_ROWS."""
    rows = pd.DataFrame(
        SCORE_ROWS,
        columns=["cik", "ticker", "fiscal_year", "filed", "flags", "all3"],
    )
    not_best = [
        (cik, year) in NOT_BEST
        for cik, year in zip(rows["cik"], rows["fiscal_year"])
    ]
    # Verdicts consistent with the flag count: 3 flags = all warnings;
    # 1 flag = only the M-Score; 0 flags = none.
    m_flag = rows["flags"] >= 1
    z_zone = np.where(rows["flags"] == 3, "distress", "safe")
    f_band = np.where(
        rows["flags"] == 3, "weak", np.where(not_best, "middle", "strong")
    )
    scores_df = pd.DataFrame(
        {
            "cik": rows["cik"],
            "fiscal_year": rows["fiscal_year"],
            "flags_raised": pd.array(rows["flags"], dtype="Int64"),
            "m_score": rows["all3"].map({True: -2.5, False: np.nan}),
            "m_flag": pd.array(
                m_flag.where(rows["all3"], None), dtype="boolean"
            ),
            "z_score": 3.0,
            "z_zone": pd.array(z_zone, dtype="string"),
            "f_score": pd.array(
                rows["all3"].map({True: 7, False: None}), dtype="Int64"
            ),
            "f_band": pd.array(
                pd.Series(f_band).where(rows["all3"], None), dtype="string"
            ),
        }
    )
    financials_df = pd.DataFrame(
        {
            "cik": rows["cik"],
            "fiscal_year": rows["fiscal_year"],
            "filed_date": pd.to_datetime(rows["filed"]),
        }
    )
    companies_df = rows.drop_duplicates("cik")[["cik", "ticker"]].astype(
        {"ticker": "string"}
    )
    return scores_df, financials_df, companies_df


def make_full_prices():
    """Return the example prices plus F ($4), G ($30) and I (first
    trade 2021-06-21)."""
    extra = [
        stock("F", [(None, 4.0)]),
        stock("G", [(None, 30.0)]),
        stock("I", [(None, 25.0)]),
    ]
    extra[2] = extra[2][extra[2]["date"] >= "2021-06-21"]
    prices = pd.concat([make_prices()] + extra, ignore_index=True)
    return prices.astype({"ticker": "string"})


def make_candidates():
    """Return select_candidates() on the example."""
    prices = make_full_prices()
    calendar = backtest.trading_calendar(prices)
    periods = backtest.holding_periods(calendar, FORMATION)
    return backtest.select_candidates(
        *make_score_inputs(),
        backtest.price_table(prices, calendar),
        calendar,
        periods,
    )


def statuses(candidates, year):
    """Return {ticker or cik: (leg, status)} for one formation year."""
    rows = candidates[candidates["formation_date"].dt.year == year]
    return {
        (r.ticker if pd.notna(r.ticker) else r.cik): (r.leg, r.status)
        for r in rows.itertuples()
    }


def test_2021_candidates_and_reasons():
    """2021: B uses FY2019 (FY2020 was filed on the trade date); F is
    under $5; cik 7 has no ticker; ZZZ has no prices; I has only 8
    trading days; H (1 flag) is not a candidate."""
    assert statuses(make_candidates(), 2021) == {
        "A": ("long", "eligible"),
        "B": ("long", "eligible"),
        "C": ("short", "eligible"),
        "D": ("short", "eligible"),
        "F": ("long", "under_min_price"),
        7: ("long", "no_ticker"),
        "ZZZ": ("long", "no_prices"),
        "G": ("long", "eligible"),
        "I": ("long", "short_history"),
    }


def test_2022_uses_latest_10k_and_drops_stale_scores():
    """2022: B's FY2020 10-K (3 flags) is now known, so B is a short;
    D, F, G, I, ZZZ and cik 7 last filed in March 2021, 16 months
    before, so they are stale."""
    result = statuses(make_candidates(), 2022)
    assert {k: v for k, v in result.items() if v[1] == "eligible"} == {
        "A": ("long", "eligible"),
        "B": ("short", "eligible"),
        "C": ("short", "eligible"),
        "E": ("short", "eligible"),
    }
    stale = {k for k, v in result.items() if v[1] == "stale_score"}
    assert stale == {"D", "F", 7, "ZZZ", "G", "I"}


def test_no_score_filed_on_or_after_the_trade_date_is_used():
    """Every candidate's 10-K was filed strictly before its trade date."""
    candidates = make_candidates()
    assert (candidates["filed_date"] < candidates["trade_date"]).all()


def test_all_three_scores_variant_drops_partial_longs_only():
    """G (0 flags but only a Z'') leaves the long leg in the stricter
    variant; the short leg is unchanged."""
    candidates = make_candidates()
    loose = backtest.picks_for_variant(candidates, "as_specified")
    strict = backtest.picks_for_variant(candidates, "all_three_scores")
    assert "G" in set(loose["ticker"])
    assert "G" not in set(strict["ticker"])

    def shorts(picks):
        return picks.loc[picks["leg"] == "short", "ticker"].tolist()

    assert shorts(loose) == shorts(strict)


# ---------------------------------------------------------------------------
# Benchmark, hit rates and the full run
# ---------------------------------------------------------------------------
def test_hit_rates():
    """Longs vs SPY (0% in P1, +5% in P2): A +20% beats, B 0% ties (not
    a beat), A +10% beats, B -10% does not: 2 of 4 = 50%.
    Shorts lagging SPY: C -20% yes, D +50% no, C -25% yes, E 0% < 5%
    yes: 3 of 4 = 75%."""
    price_wide, periods = setup()
    log = backtest.position_log(price_wide, make_picks(), periods)
    assert log["spy_return"].unique().tolist() == pytest.approx([0, 0.05])
    long_rate, short_rate = backtest.hit_rates(log)
    assert long_rate == pytest.approx(0.5)
    assert short_rate == pytest.approx(0.75)


def test_spy_benchmark():
    """100,000 in SPY: 400 -> 420 = 105,000 (+5%) over two years; the
    path never falls, so drawdown is 0."""
    price_wide, periods = setup()
    path = backtest.benchmark_path(
        price_wide,
        periods["start"].iloc[0],
        periods["end"].iloc[-1],
        100_000.0,
    )
    summary = backtest.summarize(path, 100_000.0)
    assert summary["end_value"] == pytest.approx(105_000.0)
    assert summary["total_return"] == pytest.approx(0.05)
    assert summary["max_drawdown"] == 0.0


def test_run_backtest_tables(monkeypatch):
    """3 variants x 4 portfolios x 2 cost levels x 2 periods = 48 rows,
    plus 2 SPY rows. Picks: 2021 long A, B, G and short C, D; 2022 long
    A and short B, C, E. The stricter variant drops G (only a Z'')."""
    monkeypatch.setattr(backtest.config, "BACKTEST_FORMATION_DATES", FORMATION)
    tables = backtest.run_backtest(*make_score_inputs(), make_full_prices())
    results = tables["results"]
    # + comparison group (2 cost levels x 2 periods) + 2 SPY rows.
    assert len(results) == 3 * 4 * 2 * 2 + 4 + 2
    assert list(results.columns) == backtest.RESULT_COLUMNS
    strategy = results[
        (results["portfolio"] == "strategy") & (results["cost_bps"] == 0)
    ]
    strategy = strategy.assign(year=strategy["formation_date"].dt.year)
    strategy = strategy.set_index(["variant", "year"])
    assert strategy.loc[("as_specified", 2021), "n_long"] == 3
    assert strategy.loc[("all_three_scores", 2021), "n_long"] == 2
    assert strategy.loc[("as_specified", 2022), "n_short"] == 3
    spy = tables["summary"].set_index("portfolio").loc["spy"]
    assert spy["end_value"] == pytest.approx(105_000.0)
    # D (short, 2021) is the only delisting, once per variant.
    positions = tables["positions"]
    assert positions.loc[positions["delisted"], "ticker"].tolist() == ["D"] * 3


def test_outputs_and_hit_rate_table(monkeypatch, tmp_path):
    """Outputs land at the configured paths; the "all" hit-rate row for
    the stricter variant counts 2021 longs A, B and 2022 long A (G is
    dropped) and shorts C, D (2021) and B, C, E (2022)."""
    monkeypatch.setattr(backtest.config, "BACKTEST_FORMATION_DATES", FORMATION)
    monkeypatch.setattr(backtest.config, "LOG_DIR", tmp_path)
    results_path = tmp_path / "backtest_results.parquet"
    monkeypatch.setattr(backtest.config, "BACKTEST_RESULTS_PATH", results_path)
    tables = backtest.run_backtest(*make_score_inputs(), make_full_prices())
    paths = backtest.write_outputs(tables)
    assert pd.read_parquet(results_path).shape == (54, 17)
    hits = pd.read_csv(paths["hit_rates"], dtype={"year": "string"})
    strict_all = hits[
        (hits["variant"] == "all_three_scores")
        & (hits["rule"] == "hold")
        & (hits["year"] == "all")
    ].iloc[0]
    assert strict_all["n_long"] == 3
    assert strict_all["n_short"] == 5


# ---------------------------------------------------------------------------
# Best scores and selling on a flag
# ---------------------------------------------------------------------------
def test_best_scores_variant_keeps_only_best_longs():
    """2021 longs: A is best; B (FY2019) has a middle F-Score and G has
    only a Z'', so both are left out. 2022 long: A. Shorts unchanged."""
    candidates = make_candidates()
    best = backtest.picks_for_variant(candidates, "best_scores")
    longs = best[best["leg"] == "long"]
    assert longs["ticker"].tolist() == ["A", "A"]
    loose = backtest.picks_for_variant(candidates, "as_specified")
    assert (
        best.loc[best["leg"] == "short", "ticker"].tolist()
        == loose.loc[loose["leg"] == "short", "ticker"].tolist()
    )


def test_flag_sell_dates():
    """B was bought on 2021-06-30 (FY2019, 0 flags). Its FY2020 10-K,
    filed that same day, raises 3 flags, so B is sold on the next
    trading day, 2021-07-01. A's FY2021 10-K (2022-03-01) raises none,
    so A is never sold; shorts get no sell date."""
    prices = make_full_prices()
    calendar = backtest.trading_calendar(prices)
    periods = backtest.holding_periods(calendar, FORMATION)
    scores_df, financials_df, _ = make_score_inputs()
    picks = backtest.picks_for_variant(make_candidates(), "as_specified")
    picks = backtest.flag_sell_dates(
        picks, scores_df, financials_df, calendar, periods
    )
    sells = picks.dropna(subset=["sell_date"])
    assert sells[["ticker", "sell_date"]].values.tolist() == [
        ["B", pd.Timestamp("2021-07-01")]
    ]
    assert picks.loc[picks["leg"] == "short", "sell_date"].isna().all()


def test_selling_early_freezes_the_value():
    """Long only, 100,000 in A and B. Selling A on 2021-12-31 at 10
    (before its jump to 12) leaves A at 50,000: 50,000 + B 50,000 =
    100,000, against 110,000 when held. A's return is 0%, it is marked
    sold, not delisted, and its exit date is the sale day."""
    price_wide, periods = setup()
    period = periods.iloc[0]
    sale = pd.Timestamp("2021-12-31")
    path, positions, _ = backtest.simulate_period(
        price_wide,
        ["A", "B"],
        [],
        period.start,
        period.end,
        100_000.0,
        (1.0, 0.0),
        0,
        0.0,
        {"A": sale},
    )
    assert path["value"].iloc[-1] == pytest.approx(100_000.0)
    a_row = positions.set_index("ticker").loc["A"]
    assert bool(a_row["sold_on_flag"]) and not bool(a_row["delisted"])
    assert a_row["exit_date"] == sale
    assert a_row["stock_return"] == pytest.approx(0.0)


def test_sell_date_at_or_after_the_end_changes_nothing():
    """A sell date on the period's last day is just the normal exit."""
    price_wide, periods = setup()
    period = periods.iloc[0]
    _, positions = backtest.position_paths(
        price_wide, ["A"], period.start, period.end, 1.0, {"A": period.end}
    )
    assert not positions["sold_on_flag"].any()


def test_sell_on_flag_portfolio_counts_sales(monkeypatch):
    """In the full run, the as-specified long-only sell-on-flag portfolio
    sells B once (2021) and nothing in 2022."""
    monkeypatch.setattr(backtest.config, "BACKTEST_FORMATION_DATES", FORMATION)
    tables = backtest.run_backtest(*make_score_inputs(), make_full_prices())
    results = tables["results"]
    rows = results[
        (results["variant"] == "as_specified")
        & (results["portfolio"] == "long_only_sell_on_flag")
        & (results["cost_bps"] == 0)
    ]
    assert rows["n_sold_on_flag"].tolist() == [1, 0]


# ---------------------------------------------------------------------------
# Empty legs and wiped-out accounts
# ---------------------------------------------------------------------------
def test_empty_leg_is_cash_with_no_costs():
    """No stocks to buy: the 100,000 stays in cash, so even at 20 bps and
    a 1% borrow fee nothing is charged."""
    price_wide, periods = setup()
    period = periods.iloc[0]
    path, _, costs = backtest.simulate_period(
        price_wide,
        [],
        [],
        period.start,
        period.end,
        100_000.0,
        (0.5, 0.5),
        20,
        0.01,
    )
    assert path["value"].iloc[-1] == pytest.approx(100_000.0)
    assert costs["trading_cost"] == 0.0 and costs["borrow_cost"] == 0.0


def test_short_that_quadruples_wipes_the_account_out():
    """Short only, 100,000 in X: X goes 10 -> 40 on 2022-01-03, so the
    shorts owe 400,000 against 200,000 held: -200,000. The account is
    wiped out that day and stays at 0; the next period holds nothing."""
    prices = pd.concat(
        [make_prices(), stock("X", [(None, 10.0), (JAN_2022, 40.0)])],
        ignore_index=True,
    ).astype({"ticker": "string"})
    calendar = backtest.trading_calendar(prices)
    periods = backtest.holding_periods(calendar, FORMATION)
    picks = pd.DataFrame(
        {
            "formation_date": pd.to_datetime(FORMATION),
            "leg": "short",
            "ticker": ["X", "X"],
        }
    )
    summary, daily = backtest.run_portfolio(
        backtest.price_table(prices, calendar),
        picks,
        periods,
        (0.0, 1.0),
        0,
        0.0,
        100_000.0,
    )
    assert daily.loc["2021-12-31"] == pytest.approx(100_000.0)
    assert daily.loc["2022-01-03"] == 0.0
    assert (daily[daily.index >= "2022-01-03"] == 0.0).all()
    assert summary["wiped_out"].tolist() == [True, True]
    assert summary["end_value"].tolist() == [0.0, 0.0]
    assert pd.isna(summary["period_return"].iloc[1])
    assert backtest.max_drawdown(daily) == -1.0


# ---------------------------------------------------------------------------
# Comparison group and comparison table
# ---------------------------------------------------------------------------
def test_universe_takes_every_eligible_company_whatever_its_flags():
    """2021: A, B (FY2019), C, D and G are eligible; H (1 flag) has no
    prices, F is under $5, I is too new, ZZZ has no prices and cik 7 no
    ticker. 2022: A, B, C and E (the rest are stale)."""
    prices = make_full_prices()
    calendar = backtest.trading_calendar(prices)
    periods = backtest.holding_periods(calendar, FORMATION)
    picks, counts = backtest.universe_picks(
        *make_score_inputs(),
        backtest.price_table(prices, calendar),
        calendar,
        periods,
    )
    by_year = picks.groupby(picks["formation_date"].dt.year)["ticker"]
    assert sorted(by_year.get_group(2021)) == ["A", "B", "C", "D", "G"]
    assert sorted(by_year.get_group(2022)) == ["A", "B", "C", "E"]
    eligible = counts[counts["status"] == "eligible"]
    assert eligible["companies"].tolist() == [5, 4]


def test_t_statistic():
    """Differences 1% and 3%: mean 2%, standard deviation 1.414%,
    standard error 1.414% / sqrt(2) = 1% -> t = 2.0. One year: NaN."""
    assert backtest.t_statistic([0.01, 0.03]) == pytest.approx(2.0)
    assert np.isnan(backtest.t_statistic([0.01]))


def test_comparison_table():
    """A portfolio returning 10% and 0% against a comparison group at 5%
    and 5% and SPY at 8% and -2%: vs group +5 and -5 points (mean 0, one
    year ahead); vs SPY +2 and +2 points (two years ahead, no spread so
    t is NaN). A wiped-out year (NaN) is left out."""
    years = pd.to_datetime(["2021-06-30", "2022-06-30", "2023-06-30"])

    def rows(variant, returns, spy):
        return pd.DataFrame(
            {
                "window": "2021_2023",
                "variant": variant,
                "portfolio": "long_only",
                "cost_bps": 20,
                "formation_date": years,
                "period_return": returns,
                "spy_return": spy,
            }
        )

    results = pd.concat(
        [
            rows("best_scores", [0.10, 0.0, np.nan], [0.08, -0.02, 0.0]),
            rows("universe", [0.05, 0.05, 0.05], [0.08, -0.02, 0.0]),
            rows("spy", [0.08, -0.02, 0.0], [0.08, -0.02, 0.0]),
        ],
        ignore_index=True,
    )
    table = backtest.comparison_table(results)
    assert table["variant"].tolist() == ["best_scores"]
    row = table.iloc[0]
    assert row["years"] == 2
    assert row["mean_vs_universe"] == pytest.approx(0.0)
    assert row["years_ahead_of_universe"] == 1
    assert row["mean_vs_spy"] == pytest.approx(0.02)
    assert row["years_ahead_of_spy"] == 2
    assert np.isnan(row["t_vs_spy"])
