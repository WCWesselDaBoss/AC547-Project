"""Test 15: does excluding flagged stocks matter more in a concentrated
portfolio?

Registered in docs/backtest.md ("Test 15") before any result was
computed; the definitions here follow that entry. Pools, flags and
price rules are test 14's (src/scores/overlay.py).

- Dates: test 14's first 44 rebalance dates (holdings starting 2014Q1
  to 2024Q4); each stock is held from its trade-date close to the last
  trading day on or before the trade date + 12 months; a stock whose
  prices stop exits at its last real price (the money earns nothing).
- Pools: test 14's base pool and overlay B's pool.
- Random portfolios: 10,000 per date, pool and size (20, 10, 15
  stocks), drawn without replacement, equal-weighted, bought and held,
  so a portfolio's return is the average of its stocks' 12-month
  returns. numpy.random.default_rng(SEED), used in the registered
  order: dates oldest first; sizes 20, 10, 15; base pool, then B.
- Measures: mean return; 5th percentile (numpy.percentile, linear);
  probability of holding at least one blowup (test 10's 50% rule; an
  unknown outcome counts as no blowup and is reported); probability of
  trailing the pool's own equal-weighted return by more than 10 points.
- Registered question (a): 20-stock 5th percentile, B minus base, 44
  quarters; passes if the mean is positive and t >= 3.0, with
  Newey-West standard errors (3 lags) because each 12-month window
  overlaps the next three quarters' windows.

Read-only: writes data/logs/backtest_concentrated.csv and
docs/screenshots/test15_concentrated.png. Changes no table.

Run: python -m src.scores.concentrated
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402

import config  # noqa: E402
from src.scores import backtest, blowups, overlay, public_float  # noqa: E402
from src.scores import quarterly_scores as qs  # noqa: E402

SEED = 20261123
DRAWS = 10_000
SIZES = (20, 10, 15)  # the registered draw order
POOLS = ("base", "B")  # the registered draw order
DATES_USED = 44
HOLD_MONTHS = 12
TRAIL_POINTS = 0.10
PERCENTILE = 5
NEWEY_WEST_LAGS = 3
PASS_T = 3.0
QUESTION_SIZE = 20
DETAILS_PATH = config.LOG_DIR / "backtest_concentrated.csv"
CHART_PATH = (
    config.PROJECT_ROOT / "docs" / "screenshots" / "test15_concentrated.png"
)


# ---------------------------------------------------------------------------
# Stock returns and draws
# ---------------------------------------------------------------------------
def hold_end(calendar, start):
    """Return the last trading day on or before start + 12 months."""
    limit = start + pd.DateOffset(months=HOLD_MONTHS)
    return calendar[calendar <= limit][-1]


def stock_returns(price_wide, tickers, start, end):
    """Return each stock's 12-month return: its last real price on or
    before end over its trade-date price, minus 1 (a stock whose prices
    stop exits at its last real price; the money earns nothing)."""
    window = backtest.price_window(price_wide, start, end)[list(tickers)]
    last = window.ffill().iloc[-1]
    return (last / window.iloc[0] - 1).to_numpy()


def draw_indices(rng, pool_size, portfolio_size, draws=DRAWS):
    """Return a (draws x portfolio_size) array of stock positions, each
    row a draw without replacement in which every stock is equally
    likely: the portfolio_size stocks with the smallest random keys."""
    keys = rng.random((draws, pool_size))
    return np.argpartition(keys, portfolio_size - 1, axis=1)[
        :, :portfolio_size
    ]


def portfolio_returns(returns, indices):
    """Return each equal-weighted, bought-and-held portfolio's return:
    the average of its stocks' returns."""
    return returns[indices].mean(axis=1)


def fifth_percentile(values):
    """Return the 5th percentile (numpy.percentile, linear)."""
    return float(np.percentile(values, PERCENTILE))


def measures(returns, blowup, indices):
    """Return the registered measures for one date, pool and size."""
    portfolio = portfolio_returns(returns, indices)
    pool_return = float(returns.mean())
    return {
        "mean_return": float(portfolio.mean()),
        "p5_return": fifth_percentile(portfolio),
        "p_any_blowup": float(blowup[indices].any(axis=1).mean()),
        "p_trail_10": float((portfolio < pool_return - TRAIL_POINTS).mean()),
        "pool_return": pool_return,
    }, portfolio


# ---------------------------------------------------------------------------
# The whole test
# ---------------------------------------------------------------------------
def newey_west(differences, lags=NEWEY_WEST_LAGS):
    """Return (mean, standard error, t, 95% interval) of a series with
    Newey-West (HAC, Bartlett) standard errors."""
    values = pd.Series(differences).dropna().to_numpy()
    fit = sm.OLS(values, np.ones(len(values))).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags}
    )
    low, high = fit.conf_int()[0]
    return (
        float(fit.params[0]),
        float(fit.bse[0]),
        float(fit.tvalues[0]),
        (float(low), float(high)),
    )


def run_concentrated(
    scores_df,
    financials_df,
    companies_df,
    prices_df,
    floats_df,
    scores_quarterly_df,
    seed=SEED,
):
    """Run test 15; return the per-date table, the pooled 20-stock
    portfolio returns, the registered question and descriptive tables."""
    calendar = backtest.trading_calendar(prices_df)
    price_wide = backtest.price_table(prices_df, calendar)
    periods = overlay.overlay_periods(calendar).iloc[:DATES_USED]
    holdings = overlay.build_holdings(
        scores_df,
        financials_df,
        companies_df,
        price_wide,
        calendar,
        periods,
        floats_df,
        scores_quarterly_df,
    )
    rng = np.random.default_rng(seed)
    rows, pooled = [], {pool: [] for pool in POOLS}
    for period in periods.itertuples(index=False):
        end = hold_end(calendar, period.start)
        quarter = holdings[holdings["formation_date"] == period.formation_date]
        pool_tickers = {
            pool: list(
                dict.fromkeys(quarter.loc[quarter[f"in_{pool}"], "ticker"])
            )
            for pool in POOLS
        }
        everyone = pool_tickers["base"]
        returns_all = pd.Series(
            stock_returns(price_wide, everyone, period.start, end),
            index=everyone,
        )
        outcomes = blowups.classify_window(
            price_wide, everyone, period.start, end
        ).set_index("ticker")["outcome"]
        for size in SIZES:
            for pool in POOLS:
                tickers = pool_tickers[pool]
                returns = returns_all.loc[tickers].to_numpy()
                blowup = (outcomes.loc[tickers] == "blowup").to_numpy()
                indices = draw_indices(rng, len(tickers), size)
                result, portfolio = measures(returns, blowup, indices)
                rows.append(
                    {
                        "quarter": period.quarter,
                        "start": period.start,
                        "end": end,
                        "pool": pool,
                        "size": size,
                        "pool_stocks": len(tickers),
                        "unknown_stocks": int(
                            (outcomes.loc[tickers] == "unknown").sum()
                        ),
                        **result,
                    }
                )
                if size == QUESTION_SIZE:
                    pooled[pool].append(portfolio)
    table = pd.DataFrame(rows)

    def wide(measure, size=QUESTION_SIZE):
        part = table[table["size"] == size]
        return part.pivot(index="quarter", columns="pool", values=measure)

    p5 = wide("p5_return")
    mean, se, t_value, interval = newey_west(p5["B"] - p5["base"])
    question = {
        "question": "(a) 20-stock 5th-percentile return, B minus base",
        "quarters": int(len(p5)),
        "mean_difference": mean,
        "newey_west_se": se,
        "t": t_value,
        "ci_low": interval[0],
        "ci_high": interval[1],
        "quarters_B_higher": int((p5["B"] > p5["base"]).sum()),
        "passed": bool(mean > 0 and t_value >= PASS_T),
    }
    descriptive = []
    for size in SIZES:
        for measure in (
            "mean_return",
            "p5_return",
            "p_any_blowup",
            "p_trail_10",
        ):
            values = wide(measure, size)
            mean_d, se_d, t_d, (low, high) = newey_west(
                values["B"] - values["base"]
            )
            descriptive.append(
                {
                    "size": size,
                    "measure": measure,
                    "base_mean": float(values["base"].mean()),
                    "B_mean": float(values["B"].mean()),
                    "difference": mean_d,
                    "ci_low": low,
                    "ci_high": high,
                    "t_newey_west": t_d,
                }
            )
    yearly = (
        table.assign(year=pd.to_datetime(table["start"]).dt.year)
        .groupby(["year", "size", "pool"])[
            ["mean_return", "p5_return", "p_any_blowup", "p_trail_10"]
        ]
        .mean()
        .reset_index()
    )
    return {
        "table": table,
        "question": question,
        "descriptive": pd.DataFrame(descriptive),
        "yearly": yearly,
        "pooled": {pool: np.concatenate(pooled[pool]) for pool in POOLS},
    }


def distribution_chart(pooled, path=CHART_PATH):
    """Save the pooled 20-stock return distributions, base vs B."""
    figure, axis = plt.subplots(figsize=(9, 4.8))
    bins = np.linspace(-0.6, 1.0, 81)
    colors = {"base": "#4C78A8", "B": "#54A24B"}
    names = {
        "base": "Base pool (large_500)",
        "B": "Overlay B (minus annual- or quarterly-flagged)",
    }
    for pool in POOLS:
        values = np.clip(pooled[pool], bins[0], bins[-1])
        axis.hist(
            values * 100,
            bins=bins * 100,
            density=True,
            alpha=0.45,
            color=colors[pool],
            label=names[pool],
        )
        p5 = np.percentile(pooled[pool], PERCENTILE) * 100
        axis.axvline(p5, color=colors[pool], linestyle="--", linewidth=1.5)
        axis.text(
            p5,
            axis.get_ylim()[1] * (0.92 if pool == "base" else 0.82),
            f" 5th pct {p5:.1f}%",
            color=colors[pool],
            fontsize=8,
        )
    axis.set_xlabel("12-month return of a random 20-stock portfolio (%)")
    axis.set_ylabel("Density")
    axis.set_title(
        "Random 20-stock portfolios, 44 quarters pooled (2014-2024 starts)"
    )
    axis.legend()
    axis.grid(alpha=0.3)
    figure.text(
        0.01,
        0.01,
        "Class project analysis, not investment advice. Random picks; "
        "current tickers only; returns beyond -60%/+100% shown at the ends.",
        fontsize=7,
        color="gray",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main():
    """Run test 15 on data/processed/, save the details and the chart,
    and print every result."""
    companies_df = pd.read_parquet(config.COMPANIES_PATH)
    floats_df = public_float.load_public_float(
        companies_df.loc[~companies_df["is_excluded"], "cik"].tolist()
    )
    tables = run_concentrated(
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        companies_df,
        pd.read_parquet(config.PRICES_PATH),
        floats_df,
        pd.read_parquet(qs.SCORES_QUARTERLY_PATH),
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    tables["table"].to_csv(DETAILS_PATH, index=False)
    distribution_chart(tables["pooled"])
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print("Registered question:")
        for key, value in tables["question"].items():
            print(f"  {key}: {value}")
        print(
            "\nDescriptive (means across quarters; B minus base with "
            "Newey-West 95% interval):"
        )
        print(tables["descriptive"].round(4).to_string(index=False))
        print("\nBy year (20 stocks):")
        yearly = tables["yearly"]
        print(
            yearly[yearly["size"] == QUESTION_SIZE]
            .pivot(index="year", columns="pool")
            .round(4)
            .to_string()
        )
        table = tables["table"]
        print(
            "\nPool sizes: base",
            table[table["pool"] == "base"]["pool_stocks"].unique(),
            "| B min/median/max",
            table[table["pool"] == "B"]["pool_stocks"]
            .agg(["min", "median", "max"])
            .to_dict(),
            "| unknown stocks",
            int(table["unknown_stocks"].sum()),
        )
        for pool, values in tables["pooled"].items():
            print(
                f"Pooled 20-stock {pool}: 5th pct "
                f"{np.percentile(values, 5):.4f}, mean {values.mean():.4f}"
            )
    print(f"\nSaved {DETAILS_PATH} and {CHART_PATH}")
    print(
        "Caution: random picks; current tickers only; equal weights; years "
        "already studied;\noverlapping windows; correlation, not cause. Not "
        "investment advice."
    )


if __name__ == "__main__":
    main()
