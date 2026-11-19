"""Stretch goal: does the flag count predict returns? A long-short backtest.

Strategy (dollar neutral, stocks only):
- Each June 30 in config.BACKTEST_FORMATION_DATES (the last trading day
  on or before it), buy the companies with 0 flags raised and short the
  companies with 3, using each company's latest score whose 10-K was
  filed strictly before the trade date. Nothing filed later is used.
- Half of equity goes long and half short, equal-weighted within each
  leg; positions are held, unchanged, until the next formation date,
  where everything is sold and the new portfolio bought. The final
  period ends on the latest price date in the data.
- A stock whose prices stop mid-period (delisted) is sold or covered at
  its last available price; the cash then earns nothing. No price is
  ever invented.

This is an analysis for a class project, not investment advice. See
docs/backtest.md for the results and their limitations.
"""

import numpy as np
import pandas as pd

import config

DAYS_PER_YEAR = 365.0


def trading_calendar(prices_df):
    """Return the benchmark's (SPY's) trading days, sorted.

    SPY trades every market day, so its dates are the market calendar.
    """
    is_market = prices_df["ticker"] == config.MARKET_BENCHMARK_TICKER
    return pd.DatetimeIndex(np.sort(prices_df.loc[is_market, "date"]))


def holding_periods(calendar, formation_dates):
    """Return one row per holding period: formation_date, start, end.

    start = last trading day on or before the formation date (June 30 can
    fall on a weekend); end = the next period's start, or the last
    trading day in the data for the final period.
    """
    formation = pd.to_datetime(pd.Series(formation_dates))
    positions = calendar.searchsorted(formation.to_numpy(), side="right") - 1
    starts = calendar[positions]
    ends = list(starts[1:]) + [calendar[-1]]
    return pd.DataFrame(
        {"formation_date": formation, "start": starts, "end": ends}
    )


def price_table(prices_df, calendar):
    """Return adjusted closes as a date x ticker table on the calendar."""
    wide = prices_df.pivot_table(
        index="date", columns="ticker", values="adj_close"
    )
    return wide.reindex(calendar)


def position_paths(price_wide, tickers, start, end, capital):
    """Return (daily values, positions) for equal dollar amounts.

    Each ticker gets capital / n dollars at its start price. Its daily
    value is shares x price. After the last available price (delisting),
    the value is frozen at that price, which is the same as exiting there
    and holding cash. For a short leg the same numbers are the amount
    owed to buy the shares back.
    """
    days = price_window(price_wide, start, end)
    if len(tickers) == 0:
        return pd.DataFrame(index=days.index), empty_positions()
    window = days[list(tickers)]
    entry_prices = window.iloc[0]
    if entry_prices.isna().any():
        missing = entry_prices[entry_prices.isna()].index.tolist()
        raise ValueError(f"no price on {start.date()} for {missing}")
    shares = (capital / len(tickers)) / entry_prices
    # Forward fill only inside the window: a delisted stock stays at its
    # last real price (the exit), never at a made-up later one.
    values = window.ffill() * shares
    exit_prices = window.ffill().iloc[-1]
    # Delisted = no price anywhere in the data after its last one in the
    # window, so a single missing day is not mistaken for a delisting.
    last_ever = price_wide[list(tickers)].apply(pd.Series.last_valid_index)
    delisted = (last_ever < end).to_numpy()
    last_in_window = window.apply(pd.Series.last_valid_index)
    exit_dates = np.where(delisted, last_in_window.to_numpy(), end)
    positions = pd.DataFrame(
        {
            "ticker": pd.array(list(tickers), dtype="string"),
            "entry_price": entry_prices.to_numpy(),
            "exit_price": exit_prices.to_numpy(),
            "exit_date": pd.to_datetime(exit_dates).astype("datetime64[ns]"),
            "delisted": delisted,
        }
    )
    positions["stock_return"] = (
        positions["exit_price"] / positions["entry_price"] - 1
    )
    return values, positions


def price_window(price_wide, start, end):
    """Return the price rows from start through end (inclusive)."""
    in_window = (price_wide.index >= start) & (price_wide.index <= end)
    return price_wide.loc[in_window]


def empty_positions():
    """Return an empty positions table with the right columns."""
    return pd.DataFrame(
        {
            "ticker": pd.array([], dtype="string"),
            "entry_price": pd.Series([], dtype="float64"),
            "exit_price": pd.Series([], dtype="float64"),
            "exit_date": pd.Series([], dtype="datetime64[ns]"),
            "delisted": pd.Series([], dtype="bool"),
            "stock_return": pd.Series([], dtype="float64"),
        }
    )


def simulate_period(
    price_wide,
    longs,
    shorts,
    start,
    end,
    equity,
    weights,
    cost_bps,
    borrow_rate,
):
    """Simulate one holding period; return (daily path, positions, costs).

    weights = (long share, short share) of equity, e.g. (0.5, 0.5) for
    the strategy, (1, 0) for long only, (0, 1) for short only.

    Account value = cash + long value - amount owed on shorts, where
    cash = equity - long capital + short sale proceeds. Costs:
    - trading: cost_bps / 10,000 of every dollar traded, on entry (the
      capital deployed) and on exit (the long value plus the amount
      paid to cover the shorts);
    - borrowing: borrow_rate a year on the short capital, pro-rated by
      calendar days.
    Entry cost is taken on the first day, borrowing accrues day by day
    and exit cost is taken on the last day, so the path shows them.
    """
    long_capital = equity * weights[0]
    short_capital = equity * weights[1]
    long_values, long_positions = position_paths(
        price_wide, longs, start, end, long_capital
    )
    short_owed, short_positions = position_paths(
        price_wide, shorts, start, end, short_capital
    )
    days = price_window(price_wide, start, end).index
    long_total = long_values.sum(axis=1).reindex(days, fill_value=0.0)
    owed_total = short_owed.sum(axis=1).reindex(days, fill_value=0.0)
    # An empty leg keeps its capital as cash.
    if len(longs) == 0:
        long_total = long_total + long_capital
    if len(shorts) == 0:
        owed_total = owed_total + short_capital
    gross = equity - long_capital + short_capital + long_total - owed_total

    rate = cost_bps / 10_000
    entry_cost = rate * (long_capital + short_capital)
    exit_cost = rate * (long_total.iloc[-1] + owed_total.iloc[-1])
    elapsed_days = (days - start).days.to_numpy()
    borrow = borrow_rate * short_capital * elapsed_days / DAYS_PER_YEAR
    net = gross - entry_cost - borrow
    net.iloc[-1] -= exit_cost

    path = pd.DataFrame(
        {"long_value": long_total, "short_owed": owed_total, "gross": gross}
    )
    path["value"] = net
    long_positions["leg"] = "long"
    short_positions["leg"] = "short"
    positions = pd.concat([long_positions, short_positions], ignore_index=True)
    costs = {
        "trading_cost": entry_cost + exit_cost,
        "borrow_cost": float(borrow[-1]),
    }
    return path, positions, costs


def run_portfolio(
    price_wide,
    picks_df,
    periods_df,
    weights,
    cost_bps,
    borrow_rate,
    start_capital,
):
    """Run every period in turn; return (period summary, daily path).

    Each period starts with the previous period's ending value (after
    costs), split again by weights, so the portfolio is rebalanced once
    a year. picks_df has columns formation_date, leg, ticker.
    """
    equity = start_capital
    rows, paths = [], []
    for period in periods_df.itertuples(index=False):
        chosen = picks_df[picks_df["formation_date"] == period.formation_date]
        longs = chosen.loc[chosen["leg"] == "long", "ticker"].tolist()
        shorts = chosen.loc[chosen["leg"] == "short", "ticker"].tolist()
        path, _, costs = simulate_period(
            price_wide,
            longs,
            shorts,
            period.start,
            period.end,
            equity,
            weights,
            cost_bps,
            borrow_rate,
        )
        end_value = path["value"].iloc[-1]
        rows.append(
            {
                "formation_date": period.formation_date,
                "start": period.start,
                "end": period.end,
                "start_value": equity,
                "end_value": end_value,
                "period_return": end_value / equity - 1,
                "n_long": len(longs) if weights[0] > 0 else 0,
                "n_short": len(shorts) if weights[1] > 0 else 0,
                **costs,
            }
        )
        paths.append(path["value"])
        equity = end_value
    daily = join_paths(paths)
    return pd.DataFrame(rows), daily


def join_paths(paths):
    """Join period paths into one daily series.

    A rebalance day is both one period's last day and the next one's
    first; the later value (after the switch) is kept.
    """
    daily = pd.concat(paths)
    return daily[~daily.index.duplicated(keep="last")]


def total_return(start_value, end_value):
    """Return end / start - 1."""
    return end_value / start_value - 1


def annualized_return(start_value, end_value, start, end):
    """Return the compound annual growth rate over calendar days."""
    years = (end - start).days / DAYS_PER_YEAR
    return (end_value / start_value) ** (1 / years) - 1


def max_drawdown(daily_values):
    """Return the worst peak-to-trough drop (a negative decimal)."""
    running_peak = daily_values.cummax()
    return float((daily_values / running_peak - 1).min())


# ---------------------------------------------------------------------------
# Choosing the legs (no information filed on or after the trade date)
# ---------------------------------------------------------------------------
LONG_VARIANTS = {
    # The strategy as specified: flags_raised = 0. A missing score counts
    # as "no warning" in flags_raised (CLAUDE.md section 4), so a company
    # with only a safe Z'' also has 0 flags.
    "as_specified": False,
    # Stricter: all three scores exist and none raises a warning, so the
    # long leg is held to the same evidence standard as the short leg
    # (3 flags always means all three scores exist).
    "all_three_scores": True,
}
STATUS_ELIGIBLE = "eligible"


def latest_scores(scores_df, financials_df, trade_date):
    """Return each company's latest score filed before the trade date.

    scores has no filing date, so filed_date comes from the matching
    financials_annual row (the 10-K the score was computed from). Only
    10-Ks filed strictly before trade_date count. The latest one must
    also be no older than config.BACKTEST_MAX_SCORE_AGE_MONTHS; the
    column is_stale marks the rest so they can be counted.
    """
    filed = financials_df[["cik", "fiscal_year", "filed_date"]]
    dated = scores_df.merge(filed, on=["cik", "fiscal_year"], how="left")
    known = dated[dated["filed_date"] < trade_date]
    latest = known.sort_values(["filed_date", "fiscal_year"])
    latest = latest.drop_duplicates("cik", keep="last").copy()
    oldest_allowed = trade_date - pd.DateOffset(
        months=config.BACKTEST_MAX_SCORE_AGE_MONTHS
    )
    latest["is_stale"] = latest["filed_date"] < oldest_allowed
    return latest.reset_index(drop=True)


def price_status(tickers, price_wide, calendar, trade_date):
    """Return each ticker's eligibility on the trade date.

    no_ticker: SEC lists no ticker. no_prices: the ticker has no prices
    at all. short_history: a price is missing on any of the last
    config.BACKTEST_HISTORY_DAYS trading days (through the trade date).
    under_min_price: adjusted close below config.BACKTEST_MIN_PRICE.
    Otherwise eligible.
    """
    history = calendar[calendar <= trade_date][-config.BACKTEST_HISTORY_DAYS :]
    recent = price_wide.loc[history]
    statuses = []
    for ticker in tickers:
        if pd.isna(ticker):
            statuses.append("no_ticker")
        elif ticker not in price_wide.columns:
            statuses.append("no_prices")
        elif recent[ticker].isna().any():
            statuses.append("short_history")
        elif recent[ticker].iloc[-1] < config.BACKTEST_MIN_PRICE:
            statuses.append("under_min_price")
        else:
            statuses.append(STATUS_ELIGIBLE)
    return pd.Series(statuses, index=tickers.index, dtype="string")


def select_candidates(
    scores_df, financials_df, companies_df, price_wide, calendar, periods_df
):
    """Return every long or short candidate on each formation date.

    One row per formation date and company whose latest score has
    config.BACKTEST_LONG_FLAGS or BACKTEST_SHORT_FLAGS flags. Columns:
    formation_date, trade_date, cik, ticker, fiscal_year, filed_date,
    flags_raised, leg, all_three_scores, status. Status is stale_score
    or a price_status value; only "eligible" rows are traded. Keeping
    the rest lets the report count what was dropped and why.
    """
    tickers = companies_df[["cik", "ticker"]]
    frames = []
    for period in periods_df.itertuples(index=False):
        latest = latest_scores(scores_df, financials_df, period.start)
        flags = latest["flags_raised"]
        is_long = flags == config.BACKTEST_LONG_FLAGS
        is_short = flags == config.BACKTEST_SHORT_FLAGS
        chosen = latest[(is_long | is_short).fillna(False)].copy()
        chosen["leg"] = np.where(
            chosen["flags_raised"] == config.BACKTEST_LONG_FLAGS,
            "long",
            "short",
        )
        chosen["all_three_scores"] = (
            chosen["m_score"].notna()
            & chosen["z_score"].notna()
            & chosen["f_score"].notna()
        )
        chosen = chosen.merge(tickers, on="cik", how="left")
        chosen["status"] = price_status(
            chosen["ticker"], price_wide, calendar, period.start
        )
        chosen.loc[chosen["is_stale"], "status"] = "stale_score"
        chosen["formation_date"] = period.formation_date
        chosen["trade_date"] = period.start
        frames.append(chosen)
    columns = [
        "formation_date",
        "trade_date",
        "cik",
        "ticker",
        "fiscal_year",
        "filed_date",
        "flags_raised",
        "leg",
        "all_three_scores",
        "status",
    ]
    candidates = pd.concat(frames, ignore_index=True)[columns]
    return candidates.astype({"leg": "string", "ticker": "string"})


def picks_for_variant(candidates_df, variant):
    """Return the traded picks (formation_date, leg, ticker) for a long
    leg variant in LONG_VARIANTS. The short leg is the same in both."""
    traded = candidates_df["status"] == STATUS_ELIGIBLE
    if LONG_VARIANTS[variant]:
        is_long = candidates_df["leg"] == "long"
        traded &= ~is_long | candidates_df["all_three_scores"]
    picks = candidates_df.loc[traded, ["formation_date", "leg", "ticker"]]
    return picks.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Benchmark, hit rates and summary metrics
# ---------------------------------------------------------------------------
PORTFOLIO_WEIGHTS = {
    # (share of equity long, share short)
    "strategy": (0.5, 0.5),
    "long_only": (1.0, 0.0),
    "short_only": (0.0, 1.0),
}
BENCHMARK = "spy"


def benchmark_path(price_wide, start, end, capital):
    """Return the daily value of capital in SPY, bought at start and
    held to end (no costs: a buy-and-hold yardstick)."""
    spy = price_window(price_wide, start, end)[config.MARKET_BENCHMARK_TICKER]
    return capital * spy / spy.iloc[0]


def period_benchmark_returns(price_wide, periods_df):
    """Return SPY's return over each holding period."""
    spy = price_wide[config.MARKET_BENCHMARK_TICKER]
    return (
        spy.loc[periods_df["end"]].to_numpy()
        / spy.loc[periods_df["start"]].to_numpy()
        - 1
    )


def position_log(price_wide, picks_df, periods_df):
    """Return one row per pick with its return and SPY's.

    stock_return runs from the start price to the exit price (the last
    price for a delisted stock, after which the money is cash), so it
    matches how the portfolio is valued. beat_spy: a long that returned
    more than SPY; lagged_spy: a short that returned less than SPY.
    """
    spy_returns = period_benchmark_returns(price_wide, periods_df)
    frames = []
    for period, spy_return in zip(
        periods_df.itertuples(index=False), spy_returns
    ):
        chosen = picks_df[picks_df["formation_date"] == period.formation_date]
        for leg in ("long", "short"):
            tickers = chosen.loc[chosen["leg"] == leg, "ticker"].tolist()
            _, positions = position_paths(
                price_wide, tickers, period.start, period.end, 1.0
            )
            positions["leg"] = leg
            positions["formation_date"] = period.formation_date
            positions["spy_return"] = spy_return
            frames.append(positions)
    log = pd.concat(frames, ignore_index=True)
    log["beat_spy"] = log["stock_return"] > log["spy_return"]
    log["lagged_spy"] = log["stock_return"] < log["spy_return"]
    return log


def hit_rates(positions_df):
    """Return (share of longs that beat SPY, share of shorts that
    lagged SPY), as decimals over all periods."""
    longs = positions_df[positions_df["leg"] == "long"]
    shorts = positions_df[positions_df["leg"] == "short"]
    return float(longs["beat_spy"].mean()), float(shorts["lagged_spy"].mean())


def summarize(daily_values, start_capital):
    """Return ending value, total and annualized return and max drawdown
    for one daily value path."""
    start, end = daily_values.index[0], daily_values.index[-1]
    end_value = float(daily_values.iloc[-1])
    return {
        "start": start,
        "end": end,
        "end_value": end_value,
        "total_return": total_return(start_capital, end_value),
        "annualized_return": annualized_return(
            start_capital, end_value, start, end
        ),
        "max_drawdown": max_drawdown(daily_values),
    }


# ---------------------------------------------------------------------------
# Running everything
# ---------------------------------------------------------------------------
RESULT_COLUMNS = [
    "variant",
    "portfolio",
    "cost_bps",
    "formation_date",
    "start",
    "end",
    "start_value",
    "end_value",
    "period_return",
    "spy_return",
    "n_long",
    "n_short",
    "trading_cost",
    "borrow_cost",
]


def run_backtest(scores_df, financials_df, companies_df, prices_df):
    """Run every long-leg variant, portfolio and cost level, plus SPY.

    Returns a dict of tables:
    - results: one row per variant, portfolio, cost level and period
      (RESULT_COLUMNS); SPY rows have variant and portfolio "spy";
    - summary: one row per variant, portfolio and cost level, plus SPY,
      with ending value, total and annualized return and max drawdown;
    - daily: the daily value of each of those portfolios;
    - positions: one row per variant and pick, with returns vs SPY;
    - candidates: every long or short candidate with its status.
    The 1% borrowing fee applies at every cost level, because a short
    seller always pays it; cost_bps varies only the trading cost.
    """
    calendar = trading_calendar(prices_df)
    periods = holding_periods(calendar, config.BACKTEST_FORMATION_DATES)
    price_wide = price_table(prices_df, calendar)
    candidates = select_candidates(
        scores_df, financials_df, companies_df, price_wide, calendar, periods
    )
    spy_returns = period_benchmark_returns(price_wide, periods)
    capital = config.BACKTEST_START_CAPITAL

    results, summaries, dailies, position_logs = [], [], [], []
    for variant in LONG_VARIANTS:
        picks = picks_for_variant(candidates, variant)
        log = position_log(price_wide, picks, periods)
        log["variant"] = variant
        position_logs.append(log)
        for portfolio, weights in PORTFOLIO_WEIGHTS.items():
            for cost_bps in config.BACKTEST_COST_BPS:
                labels = {
                    "variant": variant,
                    "portfolio": portfolio,
                    "cost_bps": cost_bps,
                }
                period_df, daily = run_portfolio(
                    price_wide,
                    picks,
                    periods,
                    weights,
                    cost_bps,
                    config.BACKTEST_BORROW_RATE,
                    capital,
                )
                results.append(
                    period_df.assign(spy_return=spy_returns, **labels)
                )
                summaries.append({**labels, **summarize(daily, capital)})
                dailies.append(daily_frame(daily, labels))

    spy_daily = benchmark_path(
        price_wide, periods["start"].iloc[0], periods["end"].iloc[-1], capital
    )
    spy_labels = {"variant": BENCHMARK, "portfolio": BENCHMARK, "cost_bps": 0}
    results.append(
        benchmark_periods(periods, spy_returns, capital, spy_labels)
    )
    summaries.append({**spy_labels, **summarize(spy_daily, capital)})
    dailies.append(daily_frame(spy_daily, spy_labels))

    results_df = pd.concat(results, ignore_index=True)[RESULT_COLUMNS]
    results_df = results_df.astype(
        {"variant": "string", "portfolio": "string", "cost_bps": "int64"}
    )
    return {
        "results": results_df,
        "summary": pd.DataFrame(summaries),
        "daily": pd.concat(dailies, ignore_index=True),
        "positions": pd.concat(position_logs, ignore_index=True),
        "candidates": candidates,
    }


def benchmark_periods(periods_df, spy_returns, capital, labels):
    """Return SPY's period rows, compounding capital through each period."""
    end_values = capital * np.cumprod(1 + spy_returns)
    start_values = np.concatenate([[capital], end_values[:-1]])
    return periods_df.assign(
        start_value=start_values,
        end_value=end_values,
        period_return=spy_returns,
        spy_return=spy_returns,
        n_long=0,
        n_short=0,
        trading_cost=0.0,
        borrow_cost=0.0,
        **labels,
    )


def daily_frame(daily_values, labels):
    """Return a daily path as rows: labels, date, value."""
    frame = daily_values.rename("value").rename_axis("date").reset_index()
    return frame.assign(**labels)


def coverage_table(candidates_df, positions_df):
    """Return counts of candidates by year, leg and status, and of picks
    that delisted mid-period, by variant, year and leg."""
    by_status = (
        candidates_df.assign(year=candidates_df["formation_date"].dt.year)
        .groupby(["year", "leg", "status"])
        .size()
        .unstack(fill_value=0)
    )
    delisted = (
        positions_df.assign(year=positions_df["formation_date"].dt.year)
        .groupby(["variant", "year", "leg"])["delisted"]
        .agg(picks="size", delisted_mid_period="sum")
    )
    return by_status, delisted
