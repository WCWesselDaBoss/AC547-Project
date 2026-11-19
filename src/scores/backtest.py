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
- Long-only variants: the long leg alone, optionally restricted to the
  companies whose three checks are all at their best (best_scores), and
  optionally sold as soon as a newer 10-K raises any warning
  (long_only_sell_on_flag).

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


def position_paths(price_wide, tickers, start, end, capital, sell_dates=None):
    """Return (daily values, positions) for equal dollar amounts.

    Each ticker gets capital / n dollars at its start price. Its daily
    value is shares x price. After the last available price (delisting),
    the value is frozen at that price, which is the same as exiting there
    and holding cash. For a short leg the same numbers are the amount
    owed to buy the shares back.

    sell_dates (optional) maps a ticker to a day it is sold early, at
    that day's close; its value is then frozen the same way. A sell date
    on or after the end, or after the stock's last price, changes
    nothing (the stock was already exiting).
    """
    days = price_window(price_wide, start, end)
    if len(tickers) == 0:
        return pd.DataFrame(index=days.index), empty_positions()
    window = days[list(tickers)].copy()
    entry_prices = window.iloc[0]
    if entry_prices.isna().any():
        missing = entry_prices[entry_prices.isna()].index.tolist()
        raise ValueError(f"no price on {start.date()} for {missing}")
    shares = (capital / len(tickers)) / entry_prices
    last_in_window = window.apply(pd.Series.last_valid_index)
    sold = pd.Series(False, index=window.columns)
    for ticker, sell_date in (sell_dates or {}).items():
        if (
            ticker in window.columns
            and pd.notna(sell_date)
            and sell_date < end
            and sell_date <= last_in_window[ticker]
        ):
            window.loc[window.index > sell_date, ticker] = np.nan
            sold[ticker] = True
    # Forward fill only inside the window: a delisted stock stays at its
    # last real price (the exit), never at a made-up later one.
    values = window.ffill() * shares
    exit_prices = window.ffill().iloc[-1]
    # Delisted = no price anywhere in the data after its last one in the
    # window, so a single missing day is not mistaken for a delisting.
    # A stock sold early counts as sold, not delisted, even if it later
    # stopped trading.
    last_ever = price_wide[list(tickers)].apply(pd.Series.last_valid_index)
    delisted = ((last_ever < end) & ~sold).to_numpy()
    exit_dates = window.apply(pd.Series.last_valid_index)
    exit_dates = np.where(delisted | sold.to_numpy(), exit_dates, end)
    positions = pd.DataFrame(
        {
            "ticker": pd.array(list(tickers), dtype="string"),
            "entry_price": entry_prices.to_numpy(),
            "exit_price": exit_prices.to_numpy(),
            "exit_date": pd.to_datetime(exit_dates).astype("datetime64[ns]"),
            "delisted": delisted,
            "sold_on_flag": sold.to_numpy(),
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
            "sold_on_flag": pd.Series([], dtype="bool"),
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
    long_sell_dates=None,
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
    and exit cost is taken on the last day, so the path shows them. A
    long sold early (long_sell_dates, see position_paths) pays its exit
    cost on the last day too: the amount is the same, only its timing in
    the daily path differs.
    """
    long_capital = equity * weights[0]
    short_capital = equity * weights[1]
    long_values, long_positions = position_paths(
        price_wide, longs, start, end, long_capital, long_sell_dates
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

    # Costs apply only to a leg that holds stocks: an empty leg is cash,
    # which is neither traded nor borrowed.
    traded_long = long_capital if len(longs) else 0.0
    traded_short = short_capital if len(shorts) else 0.0
    rate = cost_bps / 10_000
    entry_cost = rate * (traded_long + traded_short)
    exit_cost = rate * (
        (long_total.iloc[-1] if len(longs) else 0.0)
        + (owed_total.iloc[-1] if len(shorts) else 0.0)
    )
    elapsed_days = (days - start).days.to_numpy()
    borrow = borrow_rate * traded_short * elapsed_days / DAYS_PER_YEAR
    net = gross - entry_cost - borrow
    net.iloc[-1] -= exit_cost

    # Wiped out: once the account is worth nothing (shorts owe more than
    # everything it holds), a broker would close it. Its value stays at
    # 0; a negative balance is never carried forward.
    wiped_out = bool((net <= 0).any())
    if wiped_out:
        first_zero = net.index[(net <= 0).to_numpy()][0]
        net[net.index >= first_zero] = 0.0

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
        "wiped_out": wiped_out,
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
    sell_on_flag=False,
):
    """Run every period in turn; return (period summary, daily path).

    Each period starts with the previous period's ending value (after
    costs), split again by weights, so the portfolio is rebalanced once
    a year. picks_df has columns formation_date, leg, ticker, and
    sell_date (from flag_sell_dates) when sell_on_flag is True. After a
    period that wipes the account out, later periods hold nothing and
    stay at 0 (their period_return is NaN: there is no capital to earn
    a return on).
    """
    equity = start_capital
    rows, paths = [], []
    for period in periods_df.itertuples(index=False):
        if equity <= 0:
            days = price_window(price_wide, period.start, period.end).index
            paths.append(pd.Series(0.0, index=days))
            rows.append(
                {
                    "formation_date": period.formation_date,
                    "start": period.start,
                    "end": period.end,
                    "start_value": 0.0,
                    "end_value": 0.0,
                    "period_return": np.nan,
                    "n_long": 0,
                    "n_short": 0,
                    "n_sold_on_flag": 0,
                    "trading_cost": 0.0,
                    "borrow_cost": 0.0,
                    "wiped_out": True,
                }
            )
            continue
        chosen = picks_df[picks_df["formation_date"] == period.formation_date]
        longs = chosen.loc[chosen["leg"] == "long", "ticker"].tolist()
        shorts = chosen.loc[chosen["leg"] == "short", "ticker"].tolist()
        sell_dates = None
        if sell_on_flag:
            is_long = chosen["leg"] == "long"
            sell_dates = dict(
                zip(
                    chosen.loc[is_long, "ticker"],
                    chosen.loc[is_long, "sell_date"],
                )
            )
        path, positions, costs = simulate_period(
            price_wide,
            longs,
            shorts,
            period.start,
            period.end,
            equity,
            weights,
            cost_bps,
            borrow_rate,
            sell_dates,
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
                "n_sold_on_flag": int(positions["sold_on_flag"].sum()),
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
    "as_specified": "flags_raised = 0",
    # Stricter: all three scores exist and none raises a warning, so the
    # long leg is held to the same evidence standard as the short leg
    # (3 flags always means all three scores exist).
    "all_three_scores": "0 flags and M, Z'' and F scores all exist",
    # Strictest: every check at its best, not merely "no warning" (0
    # flags still allows a grey-zone Z'' and a middle F-Score).
    "best_scores": "M-Score not flagged, Z'' safe and F-Score strong",
}
BEST_Z_ZONE = "safe"
BEST_F_BAND = "strong"
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
    flags_raised, m_flag, z_zone, f_band, leg, all_three_scores, status.
    Status is stale_score
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
        "m_flag",
        "z_zone",
        "f_band",
        "leg",
        "all_three_scores",
        "status",
    ]
    candidates = pd.concat(frames, ignore_index=True)[columns]
    return candidates.astype(
        {
            "leg": "string",
            "ticker": "string",
            "m_flag": "boolean",
            "z_zone": "string",
            "f_band": "string",
        }
    )


def picks_for_variant(candidates_df, variant):
    """Return the traded picks (formation_date, leg, cik, ticker) for a
    long-leg variant in LONG_VARIANTS. The short leg is the same in all.
    """
    if variant not in LONG_VARIANTS:
        raise ValueError(f"unknown variant {variant}")
    traded = candidates_df["status"] == STATUS_ELIGIBLE
    is_long = candidates_df["leg"] == "long"
    if variant in ("all_three_scores", "best_scores"):
        traded &= ~is_long | candidates_df["all_three_scores"]
    if variant == "best_scores":
        # Each test is filled separately: a missing verdict is never best
        # (and pandas cannot combine nullable masks that contain NA).
        is_best = (
            candidates_df["m_flag"].eq(False).fillna(False).astype(bool)
            & candidates_df["z_zone"]
            .eq(BEST_Z_ZONE)
            .fillna(False)
            .astype(bool)
            & candidates_df["f_band"]
            .eq(BEST_F_BAND)
            .fillna(False)
            .astype(bool)
        )
        traded &= ~is_long | is_best
    columns = ["formation_date", "leg", "cik", "ticker"]
    return candidates_df.loc[traded, columns].reset_index(drop=True)


def flag_sell_dates(picks_df, scores_df, financials_df, calendar, periods):
    """Return picks_df with sell_date: when a long would be sold on a flag.

    A long is sold when a newer 10-K, filed on or after the period's
    trade date and before its end, raises at least one warning
    (flags_raised >= 1). The sale is at the close of the first trading
    day after that 10-K's filed_date, the first day an investor could act
    on it; the money then waits in cash until the next rebalance. A new
    10-K that is merely less than "best" (say an F-Score falling from 7
    to 6) raises no flag and does not trigger a sale. Shorts and longs
    with no such 10-K get NaT.
    """
    filed = financials_df[["cik", "fiscal_year", "filed_date"]]
    dated = scores_df.merge(filed, on=["cik", "fiscal_year"], how="left")
    flagged = dated.loc[dated["flags_raised"].fillna(0) >= 1]
    flagged = flagged[["cik", "filed_date"]]
    picks = picks_df.copy()
    picks["sell_date"] = pd.Series(pd.NaT, index=picks.index).astype(
        "datetime64[ns]"
    )
    for period in periods.itertuples(index=False):
        in_period = flagged[
            (flagged["filed_date"] >= period.start)
            & (flagged["filed_date"] < period.end)
        ]
        first_flag = in_period.groupby("cik")["filed_date"].min()
        if first_flag.empty:
            continue
        is_row = (picks["formation_date"] == period.formation_date) & (
            picks["leg"] == "long"
        )
        filed_dates = picks.loc[is_row, "cik"].map(first_flag).dropna()
        # Next trading day strictly after the filing date.
        positions = calendar.searchsorted(filed_dates.to_numpy(), side="right")
        sell_days = [
            calendar[i] if i < len(calendar) else pd.NaT for i in positions
        ]
        picks.loc[filed_dates.index, "sell_date"] = sell_days
    return picks


# ---------------------------------------------------------------------------
# Benchmark, hit rates and summary metrics
# ---------------------------------------------------------------------------
PORTFOLIOS = {
    # name: ((share of equity long, share short), sell longs on a flag)
    "strategy": ((0.5, 0.5), False),
    "long_only": ((1.0, 0.0), False),
    "long_only_sell_on_flag": ((1.0, 0.0), True),
    "short_only": ((0.0, 1.0), False),
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


def position_log(price_wide, picks_df, periods_df, sell_on_flag=False):
    """Return one row per pick with its return and SPY's.

    stock_return runs from the start price to the exit price (the last
    price for a delisted stock, after which the money is cash), so it
    matches how the portfolio is valued. beat_spy: a long that returned
    more than SPY; lagged_spy: a short that returned less than SPY. With
    sell_on_flag, longs are sold on their sell_date (flag_sell_dates).
    """
    spy_returns = period_benchmark_returns(price_wide, periods_df)
    frames = []
    for period, spy_return in zip(
        periods_df.itertuples(index=False), spy_returns
    ):
        chosen = picks_df[picks_df["formation_date"] == period.formation_date]
        for leg in ("long", "short"):
            in_leg = chosen[chosen["leg"] == leg]
            tickers = in_leg["ticker"].tolist()
            sell_dates = None
            if sell_on_flag and leg == "long":
                sell_dates = dict(zip(tickers, in_leg["sell_date"]))
            _, positions = position_paths(
                price_wide, tickers, period.start, period.end, 1.0, sell_dates
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
    "n_sold_on_flag",
    "trading_cost",
    "borrow_cost",
    "wiped_out",
]


def run_backtest(scores_df, financials_df, companies_df, prices_df):
    """Run every long-leg variant, portfolio and cost level, plus SPY.

    Returns a dict of tables:
    - results: one row per variant, portfolio, cost level and period
      (RESULT_COLUMNS); SPY rows have variant and portfolio "spy";
    - summary: one row per variant, portfolio and cost level, plus SPY,
      with ending value, total and annualized return and max drawdown;
    - daily: the daily value of each of those portfolios;
    - positions: one row per variant, rule (hold or sell_on_flag) and
      pick, with returns vs SPY (sell_on_flag rows are longs only);
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
        picks = flag_sell_dates(
            picks_for_variant(candidates, variant),
            scores_df,
            financials_df,
            calendar,
            periods,
        )
        for rule in ("hold", "sell_on_flag"):
            log = position_log(
                price_wide, picks, periods, rule == "sell_on_flag"
            )
            if rule == "sell_on_flag":
                log = log[log["leg"] == "long"]
            position_logs.append(log.assign(variant=variant, rule=rule))
        for portfolio, (weights, sell_on_flag) in PORTFOLIOS.items():
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
                    sell_on_flag,
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
        {
            "variant": "string",
            "portfolio": "string",
            "cost_bps": "int64",
            "wiped_out": "bool",
        }
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
        n_sold_on_flag=0,
        wiped_out=False,
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
        .groupby(["variant", "rule", "year", "leg"])
        .agg(
            picks=("delisted", "size"),
            delisted_mid_period=("delisted", "sum"),
            sold_on_flag=("sold_on_flag", "sum"),
        )
    )
    return by_status, delisted


def hit_rate_table(positions_df):
    """Return hit rates by variant, rule and year, plus an "all" row per
    variant and rule: picks, share of longs that beat SPY, share of
    shorts that lagged SPY (NaN when a rule has no shorts)."""
    rows = []
    groups_by_rule = positions_df.groupby(["variant", "rule"], sort=False)
    for (variant, rule), picks in groups_by_rule:
        years = picks["formation_date"].dt.year
        groups = [
            (str(year), picks[years == year])
            for year in sorted(years.unique())
        ]
        for label, group in groups + [("all", picks)]:
            long_rate, short_rate = hit_rates(group)
            rows.append(
                {
                    "variant": variant,
                    "rule": rule,
                    "year": label,
                    "n_long": int((group["leg"] == "long").sum()),
                    "long_beat_spy": long_rate,
                    "n_short": int((group["leg"] == "short").sum()),
                    "short_lagged_spy": short_rate,
                }
            )
    return pd.DataFrame(rows)


def write_outputs(tables):
    """Write the results Parquet file and the CSV logs; return the log
    paths by name."""
    tables["results"].to_parquet(config.BACKTEST_RESULTS_PATH, index=False)
    by_status, delisted = coverage_table(
        tables["candidates"], tables["positions"]
    )
    logs = {
        "summary": tables["summary"],
        "hit_rates": hit_rate_table(tables["positions"]),
        "coverage_status": by_status.reset_index(),
        "coverage_delisted": delisted.reset_index(),
        "positions": tables["positions"],
        "candidates": tables["candidates"],
        "daily": tables["daily"],
    }
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, frame in logs.items():
        paths[name] = config.LOG_DIR / f"backtest_{name}.csv"
        frame.to_csv(paths[name], index=False)
    return paths


def main():
    """Run the backtest on data/processed/ and write the outputs.

    There is no --sample option: 50 sample companies give almost no
    3-flag shorts, so a sample backtest would mean nothing.
    """
    tables = run_backtest(
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        pd.read_parquet(config.COMPANIES_PATH),
        pd.read_parquet(config.PRICES_PATH),
    )
    paths = write_outputs(tables)
    summary = tables["summary"].drop(columns=["start"])
    summary["end"] = summary["end"].dt.date  # round() skips dates
    print(summary.round(4).to_string(index=False))
    print()
    print(pd.read_csv(paths["hit_rates"]).round(3).to_string(index=False))
    print(
        "\nCaution: companies that delisted have no current ticker and are"
        " left out\n(survivorship and look-ahead bias); 5 periods and 7-11"
        " shorts a year are a\nsmall sample; correlation, not cause. Not"
        " investment advice."
    )
    print(
        f"Wrote {len(tables['results'])} rows to {config.BACKTEST_RESULTS_PATH}"
    )
    print(f"Logs: {', '.join(p.name for p in paths.values())}")


if __name__ == "__main__":
    main()
