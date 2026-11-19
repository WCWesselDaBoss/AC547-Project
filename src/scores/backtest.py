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
