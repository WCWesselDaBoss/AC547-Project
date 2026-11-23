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

from src.scores import (
    backtest,
    blowups,
    drop_sizes,
    public_float,
    time_to_drop,
)

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
# Book equity for the value tests (100 unless listed): A's FY2021 is
# 300; G's FY2020 is negative.
EQUITY = {(1, 2021): 300.0, (9, 2020): -10.0}
# Public float per 10-K (cik, fiscal year): D's FY2020 has none.
FLOATS = {
    (1, 2020): 100.0,
    (1, 2021): 100.0,
    (2, 2019): 50.0,
    (2, 2020): 100.0,
    (3, 2020): 200.0,
    (3, 2021): 400.0,
    (5, 2021): 200.0,
    (9, 2020): 100.0,
}


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
            "accession": pd.array(
                [f"acc-{c}-{y}" for c, y in zip(rows.cik, rows.fiscal_year)],
                dtype="string",
            ),
            "stockholders_equity": [
                EQUITY.get((c, y), 100.0)
                for c, y in zip(rows.cik, rows.fiscal_year)
            ],
            # Blank, so the float plausibility checks are skipped here;
            # test_plausible_float covers them.
            "shares_outstanding": np.nan,
            "total_assets": np.nan,
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


# ---------------------------------------------------------------------------
# Value tilt (test 7)
# ---------------------------------------------------------------------------


def make_floats():
    """Return float_per_filing-style rows for FLOATS."""
    return pd.DataFrame(
        {
            "cik": [c for c, _ in FLOATS],
            "accession": pd.array(
                [f"acc-{c}-{y}" for c, y in FLOATS], dtype="string"
            ),
            "float_date": pd.Timestamp("2020-06-30"),
            "public_float": list(FLOATS.values()),
        }
    )


def test_float_rows_keep_10k_dollar_facts_only():
    """Only USD facts from 10-K or 10-K/A forms are kept."""
    facts = {
        "facts": {
            "dei": {
                "EntityPublicFloat": {
                    "units": {
                        "USD": [
                            {
                                "accn": "a1",
                                "end": "2021-06-30",
                                "val": 5e8,
                                "form": "10-K",
                            },
                            {
                                "accn": "a2",
                                "end": "2021-06-30",
                                "val": 6e8,
                                "form": "S-1",
                            },
                        ]
                    }
                }
            }
        }
    }
    rows = public_float.float_rows(facts, 42)
    assert rows[["cik", "accession", "public_float"]].values.tolist() == [
        [42, "a1", 5e8]
    ]


def test_float_per_filing_uses_the_filing_own_date_and_adds_classes():
    """Filing a1 repeats last year's float (2020) and reports two share
    classes on its own date (2021): 300 + 200 = 500."""
    floats = pd.DataFrame(
        {
            "cik": [1, 1, 1],
            "accession": ["a1", "a1", "a1"],
            "period_end": pd.to_datetime(
                ["2020-06-30", "2021-06-30", "2021-06-30"]
            ),
            "public_float": [900.0, 300.0, 200.0],
        }
    )
    result = public_float.float_per_filing(floats)
    assert result["public_float"].tolist() == [500.0]
    assert result["float_date"].tolist() == [pd.Timestamp("2021-06-30")]


def make_value_ranks():
    """Return book_to_market() on the example comparison group."""
    prices = make_full_prices()
    calendar = backtest.trading_calendar(prices)
    periods = backtest.holding_periods(calendar, FORMATION)
    scores_df, financials_df, companies_df = make_score_inputs()
    universe, _ = backtest.universe_picks(
        scores_df,
        financials_df,
        companies_df,
        backtest.price_table(prices, calendar),
        calendar,
        periods,
    )
    return backtest.book_to_market(universe, financials_df, make_floats())


def test_book_to_market_and_value_group():
    """2021: B 100/50 = 2.0, A 100/100 = 1.0, C 100/200 = 0.5; D has no
    float; G's equity is negative. Ranked: C 1/3, A 2/3, B 1 -> only B
    is in the top fifth. 2022: A 300/100 = 3.0, B 1.0, E 0.5, C 0.25 ->
    only A (rank 1.0; B's 0.75 is not above 0.8)."""
    ranks = make_value_ranks().set_index(
        [make_value_ranks()["formation_date"].dt.year, "ticker"]
    )
    assert ranks.loc[(2021, "B"), "book_to_market"] == pytest.approx(2.0)
    assert ranks.loc[(2021, "D"), "value_status"] == "no_float"
    assert ranks.loc[(2021, "G"), "value_status"] == "equity_not_positive"
    assert ranks.loc[(2022, "A"), "book_to_market"] == pytest.approx(3.0)
    value = ranks[ranks["is_value"]].index.tolist()
    assert value == [(2021, "B"), (2022, "A")]


def test_value_variants_filter_on_the_scores():
    """B (2021) is in the value group but its F-Score is only middle, so
    the strong-F and best-score versions hold nothing in 2021; A (2022)
    is best on every check, so all three versions hold it."""
    ranks = make_value_ranks()

    def held(variant):
        picks = backtest.value_picks(ranks, variant)
        return list(zip(picks["formation_date"].dt.year, picks["ticker"]))

    assert held("value") == [(2021, "B"), (2022, "A")]
    assert held("value_strong_f") == [(2022, "A")]
    assert held("value_best") == [(2022, "A")]


def test_run_backtest_adds_value_portfolios(monkeypatch):
    """With floats, 3 value portfolios x 2 cost levels x 2 periods = 12
    more rows; the strong-F version is cash in 2021 (no stocks)."""
    monkeypatch.setattr(backtest.config, "BACKTEST_FORMATION_DATES", FORMATION)
    tables = backtest.run_backtest(
        *make_score_inputs(), make_full_prices(), floats_df=make_floats()
    )
    results = tables["results"]
    # + value (3 x 2 x 2) + large companies (2 x 2 x 2) + SPY.
    assert len(results) == 3 * 4 * 2 * 2 + 4 + 12 + 8 + 2
    strong = results[
        (results["variant"] == "value_strong_f") & (results["cost_bps"] == 20)
    ]
    assert strong["n_long"].tolist() == [0, 1]
    assert strong["period_return"].iloc[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Large companies minus red flags (test 9)
# ---------------------------------------------------------------------------
def test_weighted_positions():
    """Long only, 100,000 split 75/25 between A and B. A rises 20% and
    B is flat: 90,000 + 25,000 = 115,000 (equal weights would give
    110,000)."""
    price_wide, periods = setup()
    period = periods.iloc[0]
    path, _, _ = backtest.simulate_period(
        price_wide,
        ["A", "B"],
        [],
        period.start,
        period.end,
        100_000.0,
        (1.0, 0.0),
        0,
        0.0,
        long_weights={"A": 0.75, "B": 0.25},
    )
    assert path["value"].iloc[-1] == pytest.approx(115_000.0)


def test_run_portfolio_normalizes_weights():
    """Weights 300 and 100 become 75% and 25%: same 115,000 in P1."""
    price_wide, periods = setup()
    picks = pd.DataFrame(
        {
            "formation_date": pd.Timestamp("2021-06-30"),
            "leg": "long",
            "ticker": ["A", "B"],
            "weight": [300.0, 100.0],
        }
    )
    summary, _ = backtest.run_portfolio(
        price_wide, picks, periods.iloc[:1], (1.0, 0.0), 0, 0.0, 100_000.0
    )
    assert summary["end_value"].iloc[0] == pytest.approx(115_000.0)


def test_large_cap_pool_and_no_flags(monkeypatch):
    """With a pool of 3: 2021 floats among ranked-or-not companies with a
    positive float are C 200, A 100, G 100, B 50 (D has none) -> pool
    C, A and G. C has 3 flags, so the no-flags
    version holds A and G. 2022: C 400, E 200, A 100, B 100 -> C, E and
    A (A and B tie at 100; the lower CIK, A, wins); C and E (3 flags)
    drop -> A."""
    monkeypatch.setattr(backtest.config, "BACKTEST_LARGE_CAP_COUNT", 3)
    ranks = make_value_ranks()

    def held(variant):
        picks = backtest.large_cap_picks(ranks, variant)
        return {
            year: sorted(group["ticker"])
            for year, group in picks.groupby(picks["formation_date"].dt.year)
        }

    pool = held("large_500")
    assert pool[2021] == ["A", "C", "G"]
    assert pool[2022] == ["A", "C", "E"]
    assert held("large_500_no_flags") == {2021: ["A", "G"], 2022: ["A"]}
    picks = backtest.large_cap_picks(ranks, "large_500")
    c_2022 = picks[
        (picks["ticker"] == "C") & (picks["formation_date"].dt.year == 2022)
    ]
    assert c_2022["weight"].iloc[0] == 400.0


def test_plausible_float():
    """Rough value = price 10 x 1,000 shares = 10,000; assets 5,000.
    - 20,000: within 100x of 10,000 and 1,000x of assets -> kept;
    - 2e9 (200,000x the rough value) -> rejected;
    - 50 (1/200 of the rough value) -> rejected;
    - 2e6 with no shares (price check skipped) but 400x assets ->
      rejected; 2e5 with no shares and 40x assets -> kept."""
    frame = pd.DataFrame(
        {
            "public_float": [2e4, 2e9, 50.0, 2e6, 2e5],
            "entry_price": 10.0,
            "shares_outstanding": [1e3, 1e3, 1e3, np.nan, np.nan],
            "total_assets": 5e3,
        }
    )
    assert backtest.plausible_float(frame).tolist() == [
        True,
        False,
        False,
        False,
        True,
    ]


# ---------------------------------------------------------------------------
# Test 10: blowup rates (src/scores/blowups.py)
# ---------------------------------------------------------------------------
# Two windows: 2021-06-30 -> 2022-06-30 and 2022-06-30 -> 2023-06-30.
#   HALF: 10, exactly 5.00 on 2021-12-01 only, then 8 -> 50%: blowup.
#         Window 2 starts at 8 and stays: no blowup.
#   DROP: 10, then 4 from 2022-01-03, last price 2022-02-01 (delisted
#         after falling) -> blowup.
#   EARLY: 10, then 8 from 2021-09-01, last price 2021-10-01 (delisted
#         before falling) -> unknown.
#   OK: 10, then 6 from 2022-01-03 (60%) -> no blowup. Window 2 starts
#       at 6, then 2.4 from 2023-01-03 (40%) -> blowup.
#   PART: 10 flat, only a Z'' score -> not grouped (whole pool only).
BLOWUP_FORMATION = ["2021-06-30", "2022-06-30"]


def make_blowup_prices():
    """Return the test-10 example prices."""
    frames = [
        stock("SPY", [(None, 100.0)]),
        stock(
            "HALF",
            [
                (None, 10.0),
                (pd.Timestamp("2021-12-01"), 5.0),
                (pd.Timestamp("2021-12-02"), 8.0),
            ],
        ),
        stock("DROP", [(None, 10.0), (JAN_2022, 4.0)], last_day="2022-02-01"),
        stock(
            "EARLY",
            [(None, 10.0), (pd.Timestamp("2021-09-01"), 8.0)],
            last_day="2021-10-01",
        ),
        stock("OK", [(None, 10.0), (JAN_2022, 6.0), (JAN_2023, 2.4)]),
        stock("PART", [(None, 10.0)]),
    ]
    prices = pd.concat(frames, ignore_index=True)
    return prices.astype({"ticker": "string"})


def make_blowup_pool():
    """Return the pool: (formation, ticker, flags_raised, all three)."""
    rows = [
        ("2021-06-30", "HALF", 0, True),
        ("2021-06-30", "DROP", 3, True),
        ("2021-06-30", "EARLY", 1, True),
        ("2021-06-30", "OK", 0, True),
        ("2021-06-30", "PART", 0, False),
        ("2022-06-30", "HALF", 0, True),
        ("2022-06-30", "OK", 2, True),
    ]
    pool = pd.DataFrame(
        rows,
        columns=[
            "formation_date",
            "ticker",
            "flags_raised",
            "all_three_scores",
        ],
    )
    pool["formation_date"] = pd.to_datetime(pool["formation_date"])
    pool["flags_raised"] = pool["flags_raised"].astype("Int64")
    pool["cik"] = pool["ticker"].map(
        {"HALF": 1, "DROP": 2, "EARLY": 3, "OK": 4, "PART": 5}
    )
    return pool.assign(pool="comparison")


def run_blowup_example(monkeypatch):
    """Return (details, rates) for the example."""
    monkeypatch.setattr(
        blowups.config, "BLOWUP_FORMATION_DATES", BLOWUP_FORMATION
    )
    monkeypatch.setattr(blowups.config, "BLOWUP_FINAL_END", "2023-06-30")
    prices = make_blowup_prices()
    calendar = backtest.trading_calendar(prices)
    periods = blowups.blowup_periods(calendar)
    details = blowups.blowup_details(
        make_blowup_pool(), backtest.price_table(prices, calendar), periods
    )
    return details, blowups.blowup_rates(details)


def test_blowup_periods_end_on_the_final_date(monkeypatch):
    """Window 1 ends at window 2's start; window 2 ends 2023-06-30."""
    monkeypatch.setattr(
        blowups.config, "BLOWUP_FORMATION_DATES", BLOWUP_FORMATION
    )
    monkeypatch.setattr(blowups.config, "BLOWUP_FINAL_END", "2023-06-30")
    calendar = backtest.trading_calendar(make_blowup_prices())
    periods = blowups.blowup_periods(calendar)
    assert periods["end"].tolist() == list(
        pd.to_datetime(["2022-06-30", "2023-06-30"])
    )


def test_blowup_outcomes(monkeypatch):
    """HALF hits exactly 50% (blowup); DROP falls then delists
    (blowup); EARLY delists at 80% (unknown); OK bottoms at 60% (no
    blowup), then 40% in window 2 (blowup)."""
    details, _ = run_blowup_example(monkeypatch)
    outcome = details.set_index(["year", "ticker"])["outcome"]
    assert outcome[(2021, "HALF")] == "blowup"
    assert outcome[(2021, "DROP")] == "blowup"
    assert outcome[(2021, "EARLY")] == "unknown"
    assert outcome[(2021, "OK")] == "no_blowup"
    assert outcome[(2021, "PART")] == "no_blowup"
    assert outcome[(2022, "HALF")] == "no_blowup"
    assert outcome[(2022, "OK")] == "blowup"
    ratio = details.set_index(["year", "ticker"])["min_ratio"]
    assert ratio[(2021, "HALF")] == pytest.approx(0.5)
    assert ratio[(2021, "OK")] == pytest.approx(0.6)
    stopped = details.set_index(["year", "ticker"])["stopped"]
    assert bool(stopped[(2021, "DROP")]) and bool(stopped[(2021, "EARLY")])
    assert not bool(stopped[(2021, "HALF")])


def test_blowup_rates_and_groups(monkeypatch):
    """2021: Clean (HALF, OK) 1 of 2 = 0.5; Flagged (DROP, EARLY): EARLY
    is unknown, so 1 of 1 = 1.0; 1 flag (EARLY only) has no known stock,
    so NaN; the whole pool (PART included) 2 of 4 known = 0.5.
    2022: Clean (HALF) 0 of 1 = 0; Flagged (OK, 2 flags) 1 of 1 = 1."""
    _, rates = run_blowup_example(monkeypatch)
    rate = rates.set_index(["year", "group"])
    assert rate.loc[(2021, "clean"), "rate"] == pytest.approx(0.5)
    assert rate.loc[(2021, "flagged"), "rate"] == pytest.approx(1.0)
    assert rate.loc[(2021, "flagged"), "unknowns"] == 1
    assert np.isnan(rate.loc[(2021, "1_flags"), "rate"])
    assert rate.loc[(2021, "3_flags"), "rate"] == pytest.approx(1.0)
    assert rate.loc[(2021, "whole_pool"), "stocks"] == 5
    assert rate.loc[(2021, "whole_pool"), "rate"] == pytest.approx(0.5)
    assert rate.loc[(2022, "clean"), "rate"] == pytest.approx(0.0)
    assert rate.loc[(2022, "flagged"), "rate"] == pytest.approx(1.0)
    assert rate.loc[(2022, "2_flags"), "rate"] == pytest.approx(1.0)


def test_blowup_questions_and_pooled_rates(monkeypatch):
    """Yearly differences (Flagged - Clean): +0.5 and +1.0. Mean 0.75,
    standard deviation 0.3536, standard error 0.25 -> t = 3.0.
    Pooled: Clean 1 blowup of 3; Flagged 2 of 2 known (EARLY unknown)
    = 1.0; ratio 3.0."""
    details, rates = run_blowup_example(monkeypatch)
    question = blowups.registered_questions(rates).iloc[0]
    assert question["mean_difference"] == pytest.approx(0.75)
    assert question["median_difference"] == pytest.approx(0.75)
    assert question["years_flagged_higher"] == 2
    assert question["t"] == pytest.approx(3.0)
    assert bool(question["passes"])
    pooled = blowups.pooled_rates(details).set_index("group")
    assert pooled.loc["clean", "rate"] == pytest.approx(1 / 3)
    assert pooled.loc["flagged", "rate"] == pytest.approx(1.0)
    assert pooled.loc["flagged", "ratio_to_clean"] == pytest.approx(3.0)


def test_blowup_pools(monkeypatch):
    """The comparison pool is the comparison group; with a large pool of
    3, 2021 holds C, A and G (the same as test 9). all_three_scores
    comes from the score behind each pick: G has only a Z''."""
    monkeypatch.setattr(backtest.config, "BACKTEST_LARGE_CAP_COUNT", 3)
    prices = make_full_prices()
    calendar = backtest.trading_calendar(prices)
    periods = backtest.holding_periods(calendar, FORMATION)
    pools = blowups.build_pools(
        *make_score_inputs(),
        backtest.price_table(prices, calendar),
        calendar,
        periods,
        make_floats(),
    )
    in_2021 = pools[pools["formation_date"].dt.year == 2021]
    large = in_2021[in_2021["pool"] == "large_500"].set_index("ticker")
    assert sorted(large.index) == ["A", "C", "G"]
    assert not bool(large.loc["G", "all_three_scores"])
    assert large.loc["C", "flags_raised"] == 3
    comparison = in_2021[in_2021["pool"] == "comparison"]
    assert sorted(comparison["ticker"]) == ["A", "B", "C", "D", "G"]


# ---------------------------------------------------------------------------
# Test 11: time to a 50% drop (src/scores/time_to_drop.py)
# ---------------------------------------------------------------------------
# One 10-K each, filed Wednesday 2021-01-06, so every start is that day.
# Weekday calendar from 2020-12-01 (more than 20 trading days before).
#   FAST: 10, then 6 from 2021-02-01, then exactly 5.00 (50%) from Monday
#         2021-02-15 = day 40 -> event at day 40.
#   STEADY: 10 every day to 2023-06-30 -> no drop; censored at 24 months,
#           2023-01-06 = day 730.
#   STOP: 10, last price Friday 2021-04-16 = day 100 -> censored at 100.
TTD_DAYS = pd.bdate_range("2020-12-01", "2023-06-30").astype("datetime64[ns]")
TTD_START = pd.Timestamp("2021-01-06")


def ttd_series(steps, last_day=None):
    """Return a price series on TTD_DAYS (NaN after last_day)."""
    prices = pd.Series(steps[0][1], index=TTD_DAYS, dtype="float64")
    for date, price in steps[1:]:
        prices[prices.index >= date] = price
    if last_day is not None:
        prices[prices.index > last_day] = np.nan
    return prices


TTD_PRICES = {
    "FAST": ttd_series(
        [
            (None, 10.0),
            (pd.Timestamp("2021-02-01"), 6.0),
            (pd.Timestamp("2021-02-15"), 5.0),
        ]
    ),
    "STEADY": ttd_series([(None, 10.0)]),
    "STOP": ttd_series([(None, 10.0)], last_day="2021-04-16"),
}


def ttd_end():
    """Return the follow-up end for TTD_START."""
    return time_to_drop.follow_up_end(pd.DatetimeIndex(TTD_DAYS), TTD_START)


def test_follow_up_ends_24_months_later():
    """2021-01-06 + 24 months = Friday 2023-01-06, a trading day."""
    assert ttd_end() == pd.Timestamp("2023-01-06")


def test_drop_on_day_40_is_an_event():
    """FAST falls to 6 (60%, no event), then to exactly 5.00 (50%) on
    2021-02-15, 40 calendar days after the start."""
    event, days, drop_date = time_to_drop.drop_outcome(
        TTD_PRICES["FAST"], TTD_START, ttd_end()
    )
    assert event is True
    assert days == 40
    assert drop_date == pd.Timestamp("2021-02-15")


def test_no_drop_is_censored_at_24_months():
    """STEADY never drops: censored at the end of follow-up, day 730."""
    event, days, drop_date = time_to_drop.drop_outcome(
        TTD_PRICES["STEADY"], TTD_START, ttd_end()
    )
    assert (event, days) == (False, 730)
    assert pd.isna(drop_date)


def test_prices_that_stop_are_censored_at_the_last_price():
    """STOP's prices end 2021-04-16 without a drop: censored at day
    100, not counted as surviving to 24 months."""
    event, days, _ = time_to_drop.drop_outcome(
        TTD_PRICES["STOP"], TTD_START, ttd_end()
    )
    assert (event, days) == (False, 100)


def ttd_frame():
    """Return the three outcomes as an eligible-observation table:
    FAST is Flagged (2 flags); STEADY and STOP are Clean (0 flags)."""
    rows = []
    for ticker, flags in [("FAST", 2), ("STEADY", 0), ("STOP", 0)]:
        event, days, _ = time_to_drop.drop_outcome(
            TTD_PRICES[ticker], TTD_START, ttd_end()
        )
        rows.append((ticker, flags, event, days))
    frame = pd.DataFrame(
        rows, columns=["ticker", "flags_raised", "event", "duration_days"]
    )
    frame["event"] = frame["event"].astype("boolean")
    frame["tier"] = frame["flags_raised"].map(time_to_drop.tier_label)
    frame["group"] = np.where(frame["flags_raised"] >= 1, "flagged", "clean")
    return frame


def test_kaplan_meier_with_censoring():
    """All three together: on day 40, 1 of the 3 at risk drops, so the
    share not yet dropped is 2/3. STOP leaves the count at day 100 and
    STEADY at day 730 without dropping, so the curve stays at 2/3:
    33.3% dropped by 3, 6, 12 and 24 months. STOP counts as "not yet
    dropped" only for the 100 days it was watched."""
    curve = time_to_drop.survival_curve(ttd_frame())
    assert float(curve.evaluate(39)) == pytest.approx(1.0)
    assert float(curve.evaluate(40)) == pytest.approx(2 / 3)
    assert float(curve.evaluate(730)) == pytest.approx(2 / 3)


def test_tier_summary_and_median_among_dropped():
    """2 flags: 1 observation, dropped at day 40 -> 100% by 3 months,
    median 40 days (only among stocks that dropped). 0 flags: 2
    observations, both censored -> 0% dropped and no median."""
    summary = time_to_drop.tier_summary(ttd_frame()).set_index("group")
    assert summary.loc["2 flags", "pct_dropped_3m"] == pytest.approx(100.0)
    assert summary.loc["2 flags", "median_days_only_among_dropped"] == 40
    assert summary.loc["0 flags", "censored"] == 2
    assert summary.loc["0 flags", "pct_dropped_24m"] == pytest.approx(0.0)
    assert np.isnan(summary.loc["0 flags", "median_days_only_among_dropped"])


def test_log_rank_by_hand():
    """Flagged {FAST} vs Clean {STEADY, STOP}. The only drop is on day
    40, with 1 Flagged and 2 Clean stocks at risk (3 in all):
    expected Flagged drops E = 1 x 1/3 = 1/3, observed O = 1;
    variance V = (1 x 2 x 1 x (3 - 1)) / (3^2 x (3 - 1)) = 2/9;
    Z = (O - E) / sqrt(V) = (2/3) / 0.4714 = 1.414 (positive: Flagged
    dropped earlier); two-sided p = 0.157, so it does not pass."""
    question = time_to_drop.registered_question(ttd_frame())
    assert question["statistic"] == pytest.approx(2**0.5, rel=1e-6)
    assert question["p_value"] == pytest.approx(0.1573, abs=1e-4)
    assert question["flagged_faster"] is True
    assert question["passes"] is False


def test_observations_keep_only_complete_scores_filed_in_time():
    """Observation filters: all three scores, filed on or before
    2024-06-30. cik 1 FY2023 (filed 2024-03-01) is kept; cik 2 lacks an
    F-Score; cik 3 FY2024 was filed 2025-02-01."""
    scores_df = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "fiscal_year": [2023, 2023, 2024],
            "flags_raised": pd.array([1, 0, 0], dtype="Int64"),
            "m_score": [-2.0, -2.0, -2.0],
            "z_score": [3.0, 3.0, 3.0],
            "f_score": pd.array([7, None, 7], dtype="Int64"),
        }
    )
    financials_df = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "fiscal_year": [2023, 2023, 2024],
            "filed_date": pd.to_datetime(
                ["2024-03-01", "2024-03-01", "2025-02-01"]
            ),
        }
    )
    companies_df = pd.DataFrame(
        {"cik": [1, 2, 3], "ticker": pd.array(["A", "B", "C"], dtype="string")}
    )
    obs = time_to_drop.observations(scores_df, financials_df, companies_df)
    assert obs["cik"].tolist() == [1]


def test_follow_observations_checks_eligibility_on_each_start():
    """Filed Saturday 2021-01-02 -> start Monday 2021-01-04. STEADY is
    eligible (followed to 2023-01-04, day 730); CHEAP ($4) is under the
    $5 minimum; cik 3 has no ticker. Only eligible rows get an outcome."""
    spy = ttd_series([(None, 400.0)])
    prices = pd.DataFrame(
        {
            "SPY": spy,
            "STEADY": TTD_PRICES["STEADY"],
            "CHEAP": ttd_series([(None, 4.0)]),
        }
    )
    obs = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "fiscal_year": 2020,
            "flags_raised": pd.array([0, 1, 0], dtype="Int64"),
            "filed_date": pd.Timestamp("2021-01-02"),
            "ticker": pd.array(["STEADY", "CHEAP", None], dtype="string"),
        }
    )
    followed = time_to_drop.follow_observations(
        obs, prices, pd.DatetimeIndex(TTD_DAYS)
    ).set_index("cik")
    assert followed.loc[1, "start"] == pd.Timestamp("2021-01-04")
    assert followed["status"].tolist() == [
        "eligible",
        "under_min_price",
        "no_ticker",
    ]
    assert followed.loc[1, "duration_days"] == 730
    assert not bool(followed.loc[1, "event"])
    assert pd.isna(followed.loc[2, "event"])
    assert followed.loc[2, "group"] == "flagged"


# ---------------------------------------------------------------------------
# Test 12: drops of 10% to 90% (src/scores/drop_sizes.py)
# ---------------------------------------------------------------------------
def test_drop_sizes_on_the_test_11_example():
    """FAST: 10 -> 6 (60%) on 2021-02-01, day 26 -> 5 (50%) on day 40.
    Drops of 10% to 40% are reached on day 26 (a 40% drop needs a close
    of 60% or less, and 6.00 is exactly 60%); 50% on day 40; 60% to 90%
    never, so censored at day 730. STOP never drops: censored at 100 for
    every size. With no threshold given, drop_outcome stays at 50%."""
    price_wide = pd.DataFrame(TTD_PRICES)
    eligible = pd.DataFrame(
        {
            "ticker": ["FAST", "STOP"],
            "start": TTD_START,
            "end": ttd_end(),
        }
    )
    expected_fast = {
        0.1: (True, 26),
        0.2: (True, 26),
        0.3: (True, 26),
        0.4: (True, 26),
        0.5: (True, 40),
        0.6: (False, 730),
        0.9: (False, 730),
    }
    for size, (event, days) in expected_fast.items():
        frame = drop_sizes.outcomes_at(eligible, price_wide, size)
        fast = frame.set_index("ticker").loc["FAST"]
        stop = frame.set_index("ticker").loc["STOP"]
        assert (bool(fast["event"]), fast["duration_days"]) == (event, days)
        assert (bool(stop["event"]), stop["duration_days"]) == (False, 100)
        assert frame["drop_size"].eq(size).all()
    default = time_to_drop.drop_outcome(
        TTD_PRICES["FAST"], TTD_START, ttd_end()
    )
    assert default[:2] == (True, 40)


def test_bonferroni_bar():
    """0.01 divided by nine drop sizes = 0.00111."""
    assert drop_sizes.bonferroni_bar() == pytest.approx(0.01 / 9)


# ---------------------------------------------------------------------------
# Test 13: quarterly flags and blowups (src/scores/quarterly_blowups.py)
# ---------------------------------------------------------------------------
def test13_entry_is_strictly_after_and_cohort_is_the_entry_quarter():
    """A score available on Fri Mar 29, 2024 enters on the next trading
    day, Mon Apr 1 (cohort 2024Q2, not 2024Q1); one available on a
    non-trading Saturday enters on the Monday."""
    from src.scores import quarterly_blowups as qb

    calendar = pd.DatetimeIndex(
        pd.to_datetime(["2024-03-28", "2024-03-29", "2024-04-01"])
    )
    entries = qb.entry_days(
        pd.to_datetime(["2024-03-29", "2024-03-30"]), calendar
    )
    assert list(entries) == [pd.Timestamp("2024-04-01")] * 2
    assert list(qb.cohort(entries)) == ["2024Q2", "2024Q2"]
    assert list(qb.cohort(pd.to_datetime(["2024-03-28"]))) == ["2024Q1"]


def test13_annual_flag_is_point_in_time():
    """On entry 2024-03-01 the annual status comes from the FY2023 10-K
    filed 2024-02-15 (1 flag); the FY2024 10-K filed 2025-02-15, after
    entry, is ignored. On entry 2025-06-01 the FY2023 10-K is more than
    15 months old, but the FY2024 one (0 flags) is used."""
    from src.scores import quarterly_blowups as qb

    scores = pd.DataFrame(
        {
            "cik": [1, 1],
            "fiscal_year": [2023, 2024],
            "flags_raised": pd.array([1, 0], dtype="Int64"),
            "m_score": [-1.0, -2.5],
            "z_score": [1.0, 3.0],
            "f_score": pd.array([3, 7], dtype="Int64"),
        }
    )
    financials = pd.DataFrame(
        {
            "cik": [1, 1],
            "fiscal_year": [2023, 2024],
            "period_end": pd.to_datetime(["2023-12-31", "2024-12-31"]),
            "filed_date": pd.to_datetime(["2024-02-15", "2025-02-15"]),
        }
    )
    entries = pd.DataFrame(
        {
            "cik": [1, 1],
            "entry": pd.to_datetime(["2024-03-01", "2025-06-01"]),
        }
    )
    annual = qb.annual_point_in_time(entries, scores, financials)
    annual = annual.sort_values("entry")
    assert annual["annual_flagged"].tolist() == [1.0, 0.0]
    assert annual["annual_filed_date"].tolist() == list(
        pd.to_datetime(["2024-02-15", "2025-02-15"])
    )
    assert annual["annual_usable"].tolist() == [True, True]


def test13_newly_and_persistently_flagged():
    """A fake company's quarters: FY2023 Q2 flagged; FY2024 Q1 clean;
    FY2024 Q2 flagged. FY2024 Q2 is newly flagged (clean the quarter
    before) AND persistently flagged (flagged in FY2023 Q2). FY2024 Q3 is
    flagged but its previous quarter (FY2024 Q2) was flagged and its
    year-ago quarter is missing: neither."""
    from src.scores import quarterly_blowups as qb

    quarters = [(2023, 2, 1), (2024, 1, 0), (2024, 2, 2), (2024, 3, 1)]
    scores_q = pd.DataFrame(
        {
            "cik": 1,
            "fiscal_year": [q[0] for q in quarters],
            "fiscal_quarter": [q[1] for q in quarters],
            "flags_raised": pd.array([q[2] for q in quarters], "Int64"),
            "m_score": -2.0,
            "z_score": 3.0,
            "f_score": pd.array([5] * 4, dtype="Int64"),
        }
    )
    obs = scores_q[scores_q["fiscal_year"] == 2024].assign(
        quarterly_flagged=lambda f: (f["flags_raised"] >= 1).astype(int)
    )
    out = qb.earlier_status(obs, scores_q).set_index("fiscal_quarter")
    assert bool(out.loc[2, "newly_flagged"]) is True
    assert bool(out.loc[2, "persistently_flagged"]) is True
    assert bool(out.loc[3, "newly_flagged"]) is False
    assert bool(out.loc[3, "persistently_flagged"]) is False
    assert bool(out.loc[1, "newly_flagged"]) is False


# ---------------------------------------------------------------------------
# Test 14: large companies without flagged stocks (src/scores/overlay.py)
# ---------------------------------------------------------------------------
def test14_quarterly_flags_are_point_in_time():
    """On trade date 2024-03-28: company 1's row available 2024-03-28
    (the trade date itself) is ignored, so its 2023-11-01 row (flagged)
    is used, and the same quarter a year earlier was flagged too
    (persistent). Company 2's only row is from 2022, more than 15 months
    old: no usable flag. Company 3's row is available after the date:
    not listed."""
    from src.scores import overlay

    rows = [
        (1, 2023, 3, "2023-11-01", 1),
        (1, 2023, 4, "2024-03-28", 0),
        (1, 2022, 3, "2022-11-01", 2),
        (2, 2022, 1, "2022-05-01", 3),
        (3, 2023, 4, "2024-04-15", 1),
    ]
    scores_q = pd.DataFrame(
        {
            "cik": [r[0] for r in rows],
            "fiscal_year": [r[1] for r in rows],
            "fiscal_quarter": [r[2] for r in rows],
            "available_date": pd.to_datetime([r[3] for r in rows]),
            "period_end": pd.to_datetime([r[3] for r in rows]),
            "flags_raised": pd.array([r[4] for r in rows], dtype="Int64"),
        }
    )
    flags = overlay.quarterly_flags(scores_q, pd.Timestamp("2024-03-28"))
    assert flags["cik"].tolist() == [1]
    assert bool(flags["quarterly_flagged"].iloc[0]) is True
    assert bool(flags["persistent_flagged"].iloc[0]) is True


def test14_exclusion_logic():
    """Four pool stocks: W annual-flagged, X quarterly-flagged, Y clean on
    both, Z with no usable flag at all. A drops W; B drops W and X; P
    drops only persistent quarterly flags (X here); Z always stays."""
    from src.scores import overlay

    pool = pd.DataFrame(
        {
            "cik": [1, 2, 3, 4],
            "ticker": ["W", "X", "Y", "Z"],
            "flags_raised": pd.array([2, 0, 0, pd.NA], dtype="Int64"),
        }
    )
    flags = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "quarterly_flagged": [False, True, False],
            "persistent_flagged": [False, True, False],
            "quarterly_available": pd.to_datetime(["2024-01-01"] * 3),
        }
    )
    held = overlay.members(pool, flags).set_index("ticker")
    assert held["in_base"].all()
    assert held.index[held["in_A"]].tolist() == ["X", "Y", "Z"]
    assert held.index[held["in_B"]].tolist() == ["Y", "Z"]
    assert held.index[held["in_P"]].tolist() == ["W", "Y", "Z"]


def test14_maximum_drawdown_hand_checked():
    """100, 120, 90, 110, 60, 130: the worst fall from a peak is 120 to
    60, -50%."""
    values = pd.Series([100.0, 120, 90, 110, 60, 130])
    assert backtest.max_drawdown(values) == pytest.approx(-0.5)


def test14_turnover_on_three_stocks():
    """Held: 100 shares each of A, B, C bought at $1; at the trade date A
    is $2, so the $400 portfolio is 50% A, 25% B, 25% C. Targets A, B, D
    (one third each): weight changes 1/6 + 1/12 + 1/4 + 1/3 = 10/12,
    turnover half of that (5/12), cost 10 bps x 10/12 x $400."""
    from src.scores import overlay

    positions = {"A": 100.0, "B": 100.0, "C": 100.0}
    prices = pd.Series({"A": 2.0, "B": 1.0, "C": 1.0, "D": 1.0})
    new, turnover, cost, after = overlay.rebalance(
        positions, prices, 0.0, ["A", "B", "D"], 10
    )
    assert turnover == pytest.approx(5 / 12)
    assert cost == pytest.approx(0.001 * 10 / 12 * 400)
    assert after == pytest.approx(400 - cost)
    assert new["A"] * 2.0 == pytest.approx(after / 3)
    assert set(new) == {"A", "B", "D"}
