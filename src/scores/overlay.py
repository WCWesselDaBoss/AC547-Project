"""Test 14: large companies without flagged stocks, rebalanced quarterly.

Registered in docs/backtest.md ("Test 14") before any result was
computed; the definitions here follow that entry.

- Rebalance dates: the ends of 2013Q4 to 2025Q3; trades on the last
  trading day on or before each (backtest.holding_periods), so the
  portfolios hold the calendar quarters 2014Q1 to 2025Q4.
- Base: the test-9 large_500 pool, built each quarter by test 9's own
  functions (universe_picks, book_to_market with fixes 9a and 9b,
  large_cap_picks), equal-weighted.
- Point-in-time flags: annual from backtest.latest_scores (the row the
  pool uses); quarterly from the latest scores_quarterly row available
  strictly before the trade date and at most 15 months before it.
- Overlays: A drops annual-flagged stocks; B drops annual- or
  quarterly-flagged stocks; P (exploratory, chosen after test 13)
  drops persistently quarterly-flagged stocks. No usable flag: stays.
- Simulation (written for this test, because earlier tests sell
  everything each period): equal weights at each trade date, buy and
  hold between them; a stock whose prices stop is held at its last
  real price (the money earns nothing) and becomes cash at the next
  trade date. Turnover = half the sum of absolute weight changes
  (cash counts); cost = c x the full sum, at c = 0 and 10 bps.
- Registered questions (|t| >= 3.0): (a) B's quarterly blowup share
  minus the base's, 2014Q1 to 2025Q3, must be negative with t <= -3.0;
  (b) B's quarterly return minus the base's (10 bps), 48 quarters: mean,
  95% confidence interval and t.

Read-only: writes data/logs/backtest_overlay_*.csv and
docs/screenshots/test14_overlay.png. Changes no table.

Run: python -m src.scores.overlay
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

import config  # noqa: E402
from src.scores import backtest, blowups, public_float  # noqa: E402
from src.scores import quarterly_scores as qs  # noqa: E402

REBALANCE_DATES = [
    date.strftime("%Y-%m-%d")
    for date in pd.date_range("2013-12-31", "2025-09-30", freq="QE")
]
FINAL_END = pd.Timestamp("2025-12-31")
QUARTERLY_MAX_AGE_MONTHS = config.BACKTEST_MAX_SCORE_AGE_MONTHS
BLOWUP_FOLLOW_MONTHS = 12
COSTS_BPS = (0, 10)
QUESTION_COST_BPS = 10
PASS_T = 3.0
PORTFOLIOS = {
    "base": "large_500 pool, equal-weighted",
    "A": "base minus annual-flagged stocks",
    "B": "base minus annual- or quarterly-flagged stocks",
    "P": "base minus persistently quarterly-flagged stocks "
    "(exploratory, chosen after test 13)",
}
LOG_PREFIX = config.LOG_DIR / "backtest_overlay"
CHART_PATH = (
    config.PROJECT_ROOT / "docs" / "screenshots" / "test14_overlay.png"
)


# ---------------------------------------------------------------------------
# Dates, pool and flags
# ---------------------------------------------------------------------------
def overlay_periods(calendar):
    """Return the holding periods: formation_date, start, end, and the
    calendar quarter held (the quarter after the formation date); the
    last period ends on the last trading day on or before FINAL_END."""
    periods = backtest.holding_periods(calendar, REBALANCE_DATES)
    last = calendar[calendar <= FINAL_END][-1]
    periods.loc[periods.index[-1], "end"] = last
    periods["quarter_end"] = periods["formation_date"] + pd.offsets.QuarterEnd(
        1
    )
    periods["quarter"] = periods["quarter_end"].dt.to_period("Q").astype(str)
    return periods


def quarterly_flags(scores_quarterly_df, trade_date):
    """Return each company's quarterly flag status known on trade_date:
    the latest row available strictly before it and at most 15 months
    before it; columns cik, quarterly_flagged, persistent_flagged,
    quarterly_available. A company without such a row is not listed."""
    oldest = trade_date - pd.DateOffset(months=QUARTERLY_MAX_AGE_MONTHS)
    rows = scores_quarterly_df[
        (scores_quarterly_df["available_date"] < trade_date)
        & (scores_quarterly_df["available_date"] >= oldest)
    ]
    latest = rows.sort_values(["available_date", "period_end"])
    latest = latest.drop_duplicates("cik", keep="last")
    flagged = (latest["flags_raised"] >= 1).fillna(False).astype(bool)
    year_ago = scores_quarterly_df[
        ["cik", "fiscal_year", "fiscal_quarter", "flags_raised"]
    ].rename(columns={"flags_raised": "year_ago_flags"})
    year_ago = year_ago.assign(fiscal_year=year_ago["fiscal_year"] + 1)
    joined = latest[["cik", "fiscal_year", "fiscal_quarter"]].merge(
        year_ago, on=["cik", "fiscal_year", "fiscal_quarter"], how="left"
    )
    year_ago_flagged = (
        (joined["year_ago_flags"] >= 1).fillna(False).astype(bool)
    )
    return pd.DataFrame(
        {
            "cik": latest["cik"].to_numpy(),
            "quarterly_flagged": flagged.to_numpy(),
            "persistent_flagged": (
                flagged.to_numpy() & year_ago_flagged.to_numpy()
            ),
            "quarterly_available": latest["available_date"].to_numpy(),
        }
    )


def members(pool_df, flags_df):
    """Return the pool with one boolean column per portfolio saying
    whether each stock is held. pool_df: cik, ticker and
    annual flags_raised; flags_df: quarterly_flags' columns. A stock
    with no usable flag stays in."""
    frame = pool_df.merge(flags_df, on="cik", how="left")
    annual = (frame["flags_raised"] >= 1).fillna(False).astype(bool)
    quarterly = frame["quarterly_flagged"].fillna(False).astype(bool)
    persistent = frame["persistent_flagged"].fillna(False).astype(bool)
    return frame.assign(
        annual_flagged=annual,
        in_base=True,
        in_A=~annual,
        in_B=~(annual | quarterly),
        in_P=~persistent,
    )


def build_holdings(
    scores_df,
    financials_df,
    companies_df,
    price_wide,
    calendar,
    periods,
    floats_df,
    scores_quarterly_df,
):
    """Return one row per rebalance and pool stock: formation_date,
    start, cik, ticker, flags and the in_<portfolio> columns."""
    universe, _ = backtest.universe_picks(
        scores_df, financials_df, companies_df, price_wide, calendar, periods
    )
    ranks = backtest.book_to_market(universe, financials_df, floats_df)
    pool = backtest.large_cap_picks(ranks, "large_500")
    pool = pool.merge(
        ranks[["formation_date", "cik", "flags_raised"]],
        on=["formation_date", "cik"],
        how="left",
    )
    frames = []
    for period in periods.itertuples(index=False):
        quarter_pool = pool[pool["formation_date"] == period.formation_date]
        flags = quarterly_flags(scores_quarterly_df, period.start)
        frames.append(
            members(
                quarter_pool[["cik", "ticker", "flags_raised"]], flags
            ).assign(formation_date=period.formation_date, start=period.start)
        )
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
def rebalance(positions, prices_at_start, cash, targets, cost_bps):
    """Rebalance to equal weights over targets; return (new positions in
    shares, turnover, cost, value after cost).

    positions: {ticker: shares}. A held stock with no price at the trade
    date is already cash (its last real value was moved into cash).
    Turnover = half the sum of absolute weight changes, counting cash as
    a weight to trade; cost = cost_bps x the full sum x value."""
    values = {
        ticker: shares * prices_at_start[ticker]
        for ticker, shares in positions.items()
    }
    value = sum(values.values()) + cash
    old_weights = {ticker: v / value for ticker, v in values.items()}
    target_weight = 1 / len(targets) if targets else 0.0
    tickers = set(old_weights) | set(targets)
    changes = sum(
        abs((target_weight if t in targets else 0.0) - old_weights.get(t, 0.0))
        for t in tickers
    )
    # Cash is a weight too: fully invested when there are stocks to buy,
    # kept (target weight 1) when there are none.
    target_cash = 0.0 if targets else 1.0
    changes += abs(target_cash - cash / value)
    cost = cost_bps / 10_000 * changes * value
    after = value - cost
    new_positions = {
        ticker: after * target_weight / prices_at_start[ticker]
        for ticker in targets
    }
    return new_positions, changes / 2, cost, after


def simulate(price_wide, holdings, periods, portfolio, cost_bps):
    """Return (quarter table, daily values) for one portfolio and cost.

    Daily values run from the first trade date to the last end; on each
    trade date the value shown is after that day's trading cost."""
    positions, cash = {}, config.BACKTEST_START_CAPITAL
    daily_parts, rows = [], []
    column = f"in_{portfolio}"
    for period in periods.itertuples(index=False):
        held = holdings[
            (holdings["formation_date"] == period.formation_date)
            & holdings[column]
        ]
        window = backtest.price_window(price_wide, period.start, period.end)
        start_prices = window.iloc[0]
        # A held stock with no price on the trade date was exited at its
        # last real price: its value moves to cash.
        for ticker in list(positions):
            if pd.isna(start_prices.get(ticker, np.nan)):
                last = price_wide[ticker].loc[: period.start].dropna()
                cash += positions.pop(ticker) * last.iloc[-1]
        value_before = (
            sum(s * start_prices[t] for t, s in positions.items()) + cash
        )
        targets = list(dict.fromkeys(held["ticker"]))
        positions, turnover, cost, after = rebalance(
            positions, start_prices, cash, targets, cost_bps
        )
        cash = 0.0 if targets else after
        # Buy and hold; a price that stops is held at its last real
        # value (forward-filled), never invented.
        path = window[list(positions)].ffill()
        values = (
            path.mul(pd.Series(positions)).sum(axis=1) + cash
            if positions
            else pd.Series(cash, index=window.index)
        )
        values.iloc[0] = after
        daily_parts.append(values)
        rows.append(
            {
                "formation_date": period.formation_date,
                "quarter": period.quarter,
                "start": period.start,
                "end": period.end,
                "n_held": len(targets),
                "value_before": value_before,
                "turnover": turnover,
                "cost": cost,
                "end_value": float(values.iloc[-1]),
            }
        )
        # Positions whose prices stopped inside the window are carried at
        # their last price; the next trade date turns them into cash.
    quarters = pd.DataFrame(rows)
    previous = (
        quarters["end_value"].shift(1).fillna(config.BACKTEST_START_CAPITAL)
    )
    quarters["quarter_return"] = quarters["end_value"] / previous - 1
    daily = pd.concat(daily_parts)
    daily = daily[~daily.index.duplicated(keep="last")]
    return quarters, daily


# ---------------------------------------------------------------------------
# Measures, blowup exposure and questions
# ---------------------------------------------------------------------------
def measures(daily, quarters):
    """Return the registered measures for one portfolio's daily values."""
    returns = daily.pct_change().dropna()
    annual = backtest.annualized_return(
        daily.iloc[0], daily.iloc[-1], daily.index[0], daily.index[-1]
    )
    volatility = float(returns.std(ddof=1) * np.sqrt(252))
    return {
        "annualized_return": annual,
        "annualized_volatility": volatility,
        "max_drawdown": backtest.max_drawdown(daily),
        "return_over_volatility": annual / volatility,
        "avg_turnover_after_first": float(
            quarters["turnover"].iloc[1:].mean()
        ),
        "avg_turnover_all": float(quarters["turnover"].mean()),
        "end_value": float(daily.iloc[-1]),
    }


def blowup_exposure(price_wide, holdings, periods, calendar):
    """Return one row per quarter and portfolio: stocks held, blowups,
    unknowns, the blowup share and whether the 12-month follow-up was
    complete in the price data."""
    last_day = calendar[-1]
    rows = []
    for period in periods.itertuples(index=False):
        limit = period.quarter_end + pd.DateOffset(months=BLOWUP_FOLLOW_MONTHS)
        end = calendar[calendar <= limit][-1]
        complete = limit <= last_day
        quarter_holdings = holdings[
            holdings["formation_date"] == period.formation_date
        ]
        tickers = list(dict.fromkeys(quarter_holdings["ticker"]))
        outcomes = blowups.classify_window(
            price_wide, tickers, period.start, end
        ).set_index("ticker")["outcome"]
        for portfolio in PORTFOLIOS:
            held = quarter_holdings.loc[
                quarter_holdings[f"in_{portfolio}"], "ticker"
            ].unique()
            result = outcomes.loc[held]
            known = (result != "unknown").sum()
            blown = (result == "blowup").sum()
            rows.append(
                {
                    "quarter": period.quarter,
                    "portfolio": portfolio,
                    "held": len(held),
                    "blowups": int(blown),
                    "unknowns": int((result == "unknown").sum()),
                    "blowup_share": blown / known if known else np.nan,
                    "follow_up_complete": bool(complete),
                }
            )
    return pd.DataFrame(rows)


def question_a(exposure):
    """Registered (a): B's blowup share minus the base's, quarters with a
    complete follow-up; passes if negative with t <= -3.0."""
    wide = exposure[exposure["follow_up_complete"]].pivot(
        index="quarter", columns="portfolio", values="blowup_share"
    )
    differences = wide["B"] - wide["base"]
    t_value = backtest.t_statistic(differences)
    return {
        "question": "(a) blowup share, B minus base",
        "quarters": int(differences.notna().sum()),
        "mean_difference": float(differences.mean()),
        "t": t_value,
        "passed": bool(differences.mean() < 0 and t_value <= -PASS_T),
    }


def question_b(quarters_b, quarters_base):
    """Registered (b): B's quarterly return minus the base's (10 bps):
    mean, 95% confidence interval and t; a difference is found only if
    |t| >= 3.0."""
    differences = (
        quarters_b.set_index("quarter")["quarter_return"]
        - quarters_base.set_index("quarter")["quarter_return"]
    )
    n = int(differences.notna().sum())
    mean = float(differences.mean())
    se = float(differences.std(ddof=1) / np.sqrt(n))
    margin = float(stats.t.ppf(0.975, n - 1) * se)
    t_value = backtest.t_statistic(differences)
    return {
        "question": "(b) quarterly return, B minus base (10 bps)",
        "quarters": n,
        "mean_difference": mean,
        "ci_low": mean - margin,
        "ci_high": mean + margin,
        "t": t_value,
        "difference_found": bool(abs(t_value) >= PASS_T),
    }


def yearly_returns(dailies):
    """Return each portfolio's calendar-year return from daily values
    (each year from the previous year's last value)."""
    table = {}
    for name, daily in dailies.items():
        # The series starts on the last trading day of 2013, so 2013's
        # "year-end" value is the starting value and 2014 is the first
        # full year.
        year_end = daily.groupby(daily.index.year).last()
        table[name] = year_end.pct_change().dropna()
    return pd.DataFrame(table)


def overlay_chart(dailies, path=CHART_PATH):
    """Save cumulative growth and drawdowns for base, A and B (10 bps)."""
    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(9, 6.5), sharex=True, height_ratios=[2, 1]
    )
    colors = {"base": "#4C78A8", "A": "#F58518", "B": "#54A24B"}
    for name in ("base", "A", "B"):
        daily = dailies[name]
        top.plot(
            daily.index,
            daily / daily.iloc[0] * 100,
            label=name,
            color=colors[name],
            linewidth=1.2,
        )
        bottom.plot(
            daily.index,
            (daily / daily.cummax() - 1) * 100,
            color=colors[name],
            linewidth=1,
        )
    top.set_ylabel("Growth of 100")
    top.set_title(
        "Large-company pool, equal-weighted, rebalanced quarterly (10 bps)"
    )
    top.legend(
        [
            "Base (large_500)",
            "A: minus annual-flagged",
            "B: minus annual- or quarterly-flagged",
        ]
    )
    bottom.set_ylabel("Drawdown (%)")
    for axis in (top, bottom):
        axis.grid(alpha=0.3)
    figure.text(
        0.01,
        0.005,
        "Class project analysis, not investment advice. Current tickers "
        "only; no risk-free rate; years already studied.",
        fontsize=7,
        color="gray",
    )
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)


def run_overlay(
    scores_df,
    financials_df,
    companies_df,
    prices_df,
    floats_df,
    scores_quarterly_df,
):
    """Run test 14; return every table."""
    calendar = backtest.trading_calendar(prices_df)
    price_wide = backtest.price_table(prices_df, calendar)
    periods = overlay_periods(calendar)
    holdings = build_holdings(
        scores_df,
        financials_df,
        companies_df,
        price_wide,
        calendar,
        periods,
        floats_df,
        scores_quarterly_df,
    )
    quarter_tables, dailies, summary = [], {}, []
    for portfolio in PORTFOLIOS:
        for cost in COSTS_BPS:
            quarters, daily = simulate(
                price_wide, holdings, periods, portfolio, cost
            )
            quarter_tables.append(
                quarters.assign(portfolio=portfolio, cost_bps=cost)
            )
            if cost == QUESTION_COST_BPS:
                dailies[portfolio] = daily
            summary.append(
                {
                    "portfolio": portfolio,
                    "cost_bps": cost,
                    **measures(daily, quarters),
                }
            )
    quarters_all = pd.concat(quarter_tables, ignore_index=True)
    exposure = blowup_exposure(price_wide, holdings, periods, calendar)

    def at_cost(name):
        return quarters_all[
            (quarters_all["portfolio"] == name)
            & (quarters_all["cost_bps"] == QUESTION_COST_BPS)
        ]

    questions = pd.DataFrame(
        [question_a(exposure), question_b(at_cost("B"), at_cost("base"))]
    )
    # Descriptive: what the quarterly flags add (B against A).
    a_vs_b = question_b(at_cost("B"), at_cost("A"))
    a_vs_b["question"] = "descriptive: quarterly return, B minus A"
    wide = exposure[exposure["follow_up_complete"]].pivot(
        index="quarter", columns="portfolio", values="blowup_share"
    )
    flag_ages = (
        holdings["start"] - pd.to_datetime(holdings["quarterly_available"])
    ).dt.days
    return {
        "holdings": holdings,
        "quarters": quarters_all,
        "exposure": exposure,
        "summary": pd.DataFrame(summary),
        "questions": questions,
        "b_vs_a_return": a_vs_b,
        "b_vs_a_blowup": {
            "mean_difference": float((wide["B"] - wide["A"]).mean()),
            "t": backtest.t_statistic(wide["B"] - wide["A"]),
        },
        "yearly": yearly_returns(dailies),
        "yearly_exposure": exposure.assign(
            year=exposure["quarter"].str[:4]
        ).pivot_table(
            index="year", columns="portfolio", values="blowup_share"
        ),
        "dailies": dailies,
        "median_quarterly_flag_age_days": float(flag_ages.median()),
    }


def main():
    """Run test 14 on data/processed/, save logs and the chart, and
    print every result."""
    companies_df = pd.read_parquet(config.COMPANIES_PATH)
    floats_df = public_float.load_public_float(
        companies_df.loc[~companies_df["is_excluded"], "cik"].tolist()
    )
    tables = run_overlay(
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        companies_df,
        pd.read_parquet(config.PRICES_PATH),
        floats_df,
        pd.read_parquet(qs.SCORES_QUARTERLY_PATH),
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("holdings", "quarters", "exposure", "summary"):
        tables[name].to_csv(f"{LOG_PREFIX}_{name}.csv", index=False)
    overlay_chart(tables["dailies"])
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print("Summary (2014-2025):")
        print(tables["summary"].round(4).to_string(index=False))
        print("\nRegistered questions:")
        print(tables["questions"].to_string(index=False))
        print("\nDescriptive, B minus A:")
        print(tables["b_vs_a_return"])
        print(tables["b_vs_a_blowup"])
        print("\nCalendar-year returns (10 bps):")
        print(tables["yearly"].round(4).to_string())
        print("\nBlowup exposure by year (mean of quarters):")
        print(tables["yearly_exposure"].round(4).to_string())
        held = tables["quarters"][tables["quarters"]["cost_bps"] == 0]
        print("\nStocks held per quarter (min / median / max):")
        print(
            held.groupby("portfolio")["n_held"]
            .agg(["min", "median", "max"])
            .to_string()
        )
        print(
            "\nMedian age of the quarterly flag used (days since "
            f"available): {tables['median_quarterly_flag_age_days']}"
        )
    print(f"\nSaved {LOG_PREFIX}_*.csv and {CHART_PATH}")
    print(
        "Caution: current tickers only; years already studied; equal "
        "weights; no risk-free rate;\ncorrelation, not cause. Not "
        "investment advice."
    )


if __name__ == "__main__":
    main()
