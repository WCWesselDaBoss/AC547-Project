"""Curiosity: do the flags predict large drops beyond volatility?

Not part of the class project's test register. Definitions were fixed
in docs/curiosity/vol_matched.md before any result was computed; this
module follows them and reuses test 11's and test 12's functions for the
observations, start days, eligibility and drop detection.

Why ask: flagged companies are weaker and often more volatile, and a
volatile stock touches any lower price more often just by moving around
more. If the flags only "found" volatile stocks, they would add nothing
that the price history did not already show. Three ways to check:
1. compare Clean and Flagged within buckets of similar volatility;
2. a Cox regression with Flagged and volatility together;
3. compare actual drops with what volatility alone predicts.

This is an analysis for a class project, not investment advice.
"""

import matplotlib

matplotlib.use("Agg")  # draw to a file; no window
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm  # noqa: E402
from statsmodels.duration.hazard_regression import PHReg  # noqa: E402

import config  # noqa: E402
from src.scores import backtest, drop_sizes, time_to_drop  # noqa: E402

CURIOSITY_DIR = config.PROJECT_ROOT / "docs" / "curiosity"
CHART_PATH = CURIOSITY_DIR / "vol_buckets.png"
DETAILS_PATH = config.LOG_DIR / "curiosity_vol_matched.csv"

TRADING_DAYS_PER_YEAR = 252
VOLATILITY_WINDOW = 252  # trading days ending the day before the start
MIN_RETURNS = 200  # fewer valid daily returns: no volatility
BUCKETS = 5  # quintiles
MIN_PER_GROUP = 30  # fewer Clean or Flagged in a bucket: too few
CLIP_PERCENTILES = (1, 99)  # robustness check
DROPS = [0.3, 0.5]
FOLLOW_UP_YEARS = config.TIME_TO_DROP_FOLLOW_UP_MONTHS / 12
DAY_24_MONTHS = config.TIME_TO_DROP_HORIZON_DAYS[24]
COLORS = {"clean": "#0ca30c", "flagged": "#d03b3b"}  # app verdict colors


# ---------------------------------------------------------------------------
# Observations and volatility
# ---------------------------------------------------------------------------
def eligible_observations(
    scores_df, financials_df, companies_df, price_wide, calendar
):
    """Return test 11's eligible observations, from test 11's own
    functions (same filters, start day and eligibility checks)."""
    followed = time_to_drop.follow_observations(
        time_to_drop.observations(scores_df, financials_df, companies_df),
        price_wide,
        calendar,
    )
    eligible = followed[followed["status"] == backtest.STATUS_ELIGIBLE]
    return eligible[
        [
            "cik",
            "fiscal_year",
            "ticker",
            "flags_raised",
            "filed_date",
            "start",
            "end",
            "tier",
            "group",
        ]
    ].reset_index(drop=True)


def window_returns(stock_prices, calendar, start):
    """Return the daily log returns over the VOLATILITY_WINDOW market
    trading days ending the day before start.

    A return for day t is ln(close on t / close on the previous market
    trading day). It is NaN unless the stock has a price on both days,
    so a missing day never stretches one return over two days.
    """
    position = calendar.get_loc(start)
    first = max(position - VOLATILITY_WINDOW - 1, 0)
    days = calendar[first:position]  # the window, plus the day before it
    closes = stock_prices.reindex(days)
    return np.log(closes / closes.shift(1)).iloc[1:]


def trailing_volatility(returns, bounds=None, min_returns=MIN_RETURNS):
    """Return the annualized volatility of daily log returns, or NaN
    with fewer than min_returns valid returns.

    Sample standard deviation (n - 1) x sqrt(252). bounds (low, high)
    clips each return first, for the robustness check: a one-day price
    glitch then counts as an ordinary large move, not an extreme one.
    """
    valid = pd.Series(returns).dropna()
    if len(valid) < min_returns:
        return np.nan
    if bounds is not None:
        valid = valid.clip(lower=bounds[0], upper=bounds[1])
    return float(valid.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def clip_bounds(all_returns):
    """Return the pooled 1st and 99th percentiles of every valid daily
    return in every observation's window."""
    pooled = pd.concat(all_returns).dropna()
    low, high = np.percentile(pooled, CLIP_PERCENTILES)
    return float(low), float(high)


def add_volatility(eligible_df, price_wide, calendar):
    """Return (eligible_df with n_returns, volatility and
    volatility_clipped; the clip bounds)."""
    frame = eligible_df.copy()
    returns = [
        window_returns(price_wide[row.ticker], calendar, row.start)
        for row in frame.itertuples()
    ]
    bounds = clip_bounds(returns)
    frame["n_returns"] = [int(r.notna().sum()) for r in returns]
    frame["volatility"] = [trailing_volatility(r) for r in returns]
    frame["volatility_clipped"] = [
        trailing_volatility(r, bounds) for r in returns
    ]
    return frame, bounds


def assign_buckets(values):
    """Return (bucket 1 to 5 for each value, cutoffs): quintiles of the
    pooled values, so each bucket holds a fifth of the observations.
    Missing values get no bucket."""
    buckets, cutoffs = pd.qcut(
        pd.Series(values), BUCKETS, labels=range(1, BUCKETS + 1), retbins=True
    )
    return buckets.astype("Int64"), cutoffs


# ---------------------------------------------------------------------------
# Method 1: within-bucket comparison
# ---------------------------------------------------------------------------
def share_dropped_24m(frame):
    """Return the Kaplan-Meier share (0 to 1) that dropped within 24
    months (test 11's survival curve), or NaN with no observations."""
    if frame.empty:
        return np.nan
    curve = time_to_drop.survival_curve(frame)
    return 1 - float(curve.evaluate(DAY_24_MONTHS))


def within_bucket(frame, bucket_column):
    """Return one row per bucket: Clean and Flagged counts and 24-month
    shares, the gap (points), the ratio and too_few_to_compare."""
    rows = []
    for bucket, group in frame.groupby(bucket_column, sort=True):
        clean = group[group["group"] == "clean"]
        flagged = group[group["group"] == "flagged"]
        share_clean = share_dropped_24m(clean)
        share_flagged = share_dropped_24m(flagged)
        rows.append(
            {
                "bucket": int(bucket),
                "n_clean": len(clean),
                "n_flagged": len(flagged),
                "pct_clean": 100 * share_clean,
                "pct_flagged": 100 * share_flagged,
                "gap_pts": 100 * (share_flagged - share_clean),
                "ratio": (
                    share_flagged / share_clean if share_clean else np.nan
                ),
                "too_few_to_compare": bool(
                    len(clean) < MIN_PER_GROUP or len(flagged) < MIN_PER_GROUP
                ),
            }
        )
    return pd.DataFrame(rows)


def adjusted_gap(bucket_table):
    """Return the volatility-adjusted gap: the within-bucket gaps
    averaged with weights equal to each bucket's total observations,
    over buckets that are not too few to compare."""
    usable = bucket_table[~bucket_table["too_few_to_compare"]]
    if usable.empty:
        return np.nan
    weights = usable["n_clean"] + usable["n_flagged"]
    return float(np.average(usable["gap_pts"], weights=weights))


# ---------------------------------------------------------------------------
# Method 2: Cox regression
# ---------------------------------------------------------------------------
def cox_flagged(frame):
    """Return the Flagged hazard ratio from a Cox model of time to the
    drop with Flagged (0/1) and ln(volatility), Efron ties, and standard
    errors clustered by company (statsmodels PHReg with groups).

    A hazard ratio of 1.5 means flagged stocks reached the drop at 1.5
    times the rate of clean stocks with the same volatility; 1 means no
    difference once volatility is accounted for.
    """
    data = frame.dropna(subset=["volatility"])
    flagged = (data["group"] == "flagged").astype(float).to_numpy()
    log_vol = np.log(data["volatility"].to_numpy(float))
    model = PHReg(
        data["duration_days"].to_numpy(float),
        np.column_stack([flagged, log_vol]),
        status=data["event"].astype(bool).astype(int).to_numpy(),
        ties="efron",
    )
    result = model.fit(groups=data["cik"].to_numpy())
    low, high = np.exp(result.conf_int()[0])
    return {
        "hazard_ratio_flagged": float(np.exp(result.params[0])),
        "ci_low": float(low),
        "ci_high": float(high),
        "p_value": float(result.pvalues[0]),
        "hazard_ratio_log_volatility": float(np.exp(result.params[1])),
        "observations": len(data),
        "drops": int(data["event"].astype(bool).sum()),
        "companies": int(data["cik"].nunique()),
    }


# ---------------------------------------------------------------------------
# Method 3: volatility-only benchmark
# ---------------------------------------------------------------------------
def barrier_probability(sigma, drop, years=FOLLOW_UP_YEARS):
    """Return the chance a zero-drift stock touches (1 - drop) of its
    start price within the years, from volatility sigma alone:
    P = 2 x N(ln(1 - drop) / (sigma x sqrt(years))).

    It comes from the reflection principle for a random walk in the log
    price with no drift and normal returns. Real stocks have trends and
    fat tails, so this is a rough yardstick, not a price.
    """
    sigma = np.asarray(sigma, dtype=float)
    return 2 * norm.cdf(np.log(1 - drop) / (sigma * np.sqrt(years)))


def benchmark_table(frame, drop):
    """Return actual vs predicted share by group (Clean, Flagged, 0 to 3
    flags): observations, actual share (drops / observations), average
    predicted chance from volatility alone, and actual / predicted."""
    data = frame.dropna(subset=["volatility"]).copy()
    data["predicted"] = barrier_probability(data["volatility"], drop)
    groups = [
        ("Clean", data[data["group"] == "clean"]),
        ("Flagged", data[data["group"] == "flagged"]),
    ] + [(tier, data[data["tier"] == tier]) for tier in time_to_drop.TIERS]
    rows = []
    for label, group in groups:
        if group.empty:
            continue
        actual = group["event"].astype(bool).mean()
        predicted = group["predicted"].mean()
        rows.append(
            {
                "group": label,
                "observations": len(group),
                "median_volatility": group["volatility"].median(),
                "pct_actual": 100 * actual,
                "pct_predicted": 100 * predicted,
                "actual_over_predicted": actual / predicted,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Chart and run
# ---------------------------------------------------------------------------
def bucket_chart(tables, cutoffs, path=CHART_PATH):
    """Save the 24-month drop share by volatility bucket, Clean and
    Flagged side by side, one panel per drop size (PNG)."""
    figure, axes = plt.subplots(1, len(DROPS), figsize=(12, 5), dpi=150)
    labels = [
        f"{i + 1}\n{100 * cutoffs[i]:.0f}-{100 * cutoffs[i + 1]:.0f}%"
        for i in range(BUCKETS)
    ]
    for axis, drop in zip(axes, DROPS):
        table = tables[drop]
        x = np.arange(len(table))
        for offset, (key, name) in zip(
            (-0.2, 0.2),
            [("clean", "Clean (0 flags)"), ("flagged", "Flagged (1+)")],
        ):
            axis.bar(
                x + offset,
                table[f"pct_{key}"],
                width=0.4,
                color=COLORS[key],
                label=name,
            )
        for i, row in table.iterrows():
            if row["too_few_to_compare"]:
                axis.text(x[i], 2, "too few", ha="center", fontsize=8)
        axis.set_xticks(x, labels[: len(table)], fontsize=8)
        axis.set_title(
            f"Fell {int(100 * drop)}% within 24 months", fontsize=11
        )
        axis.set_xlabel("Volatility bucket (trailing annualized volatility)")
        axis.set_ylabel("Share that dropped (%)")
        axis.set_ylim(0, 100)
        axis.grid(axis="y", color="#e1e0d9")
        axis.legend(loc="upper left")
    figure.suptitle(
        "Flagged vs Clean within buckets of similar volatility (curiosity "
        "analysis, Kaplan-Meier)",
        fontsize=12,
    )
    figure.text(
        0.01,
        0.01,
        "Not part of the test register. Current tickers only. Correlation, "
        "not cause. Class project, not investment advice.",
        fontsize=8,
        color="#52514e",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.95))
    figure.savefig(path)
    plt.close(figure)
    return path


def run_vol_matched(scores_df, financials_df, companies_df, prices_df):
    """Run all three methods and the robustness check; return a dict of
    tables (see main for what is printed)."""
    calendar = backtest.trading_calendar(prices_df)
    price_wide = backtest.price_table(prices_df, calendar)
    eligible = eligible_observations(
        scores_df, financials_df, companies_df, price_wide, calendar
    )
    with_vol, bounds = add_volatility(eligible, price_wide, calendar)
    has_vol = with_vol.dropna(subset=["volatility"]).copy()
    has_vol["bucket"], cutoffs = assign_buckets(has_vol["volatility"])
    has_vol["bucket_clipped"], cutoffs_clipped = assign_buckets(
        has_vol["volatility_clipped"]
    )

    details, results = [], {}
    for drop in DROPS:
        frame = drop_sizes.outcomes_at(has_vol, price_wide, drop)
        frame["predicted"] = barrier_probability(frame["volatility"], drop)
        details.append(frame)
        buckets = within_bucket(frame, "bucket")
        buckets_clipped = within_bucket(frame, "bucket_clipped")
        results[drop] = {
            "buckets": buckets,
            "adjusted_gap": adjusted_gap(buckets),
            "buckets_clipped": buckets_clipped,
            "adjusted_gap_clipped": adjusted_gap(buckets_clipped),
            "raw_gap": 100
            * (
                share_dropped_24m(frame[frame["group"] == "flagged"])
                - share_dropped_24m(frame[frame["group"] == "clean"])
            ),
            "cox": cox_flagged(frame),
            "benchmark": benchmark_table(frame, drop),
        }
    return {
        "details": pd.concat(details, ignore_index=True),
        "results": results,
        "cutoffs": cutoffs,
        "cutoffs_clipped": cutoffs_clipped,
        "clip_bounds": bounds,
        "eligible": len(eligible),
        "excluded_short_history": int(with_vol["volatility"].isna().sum()),
    }


def main():
    """Run on data/processed/, save the details and chart, print all."""
    run = run_vol_matched(
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        pd.read_parquet(config.COMPANIES_PATH),
        pd.read_parquet(config.PRICES_PATH),
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    run["details"].to_csv(DETAILS_PATH, index=False)
    bucket_chart(
        {drop: run["results"][drop]["buckets"] for drop in DROPS},
        run["cutoffs"],
    )
    pd.set_option("display.width", 220)
    print(
        f"eligible {run['eligible']}, excluded (< {MIN_RETURNS} returns) "
        f"{run['excluded_short_history']}"
    )
    print("bucket cutoffs:", np.round(run["cutoffs"], 4))
    print("clipped cutoffs:", np.round(run["cutoffs_clipped"], 4))
    print("clip bounds:", np.round(run["clip_bounds"], 4))
    for drop in DROPS:
        result = run["results"][drop]
        print(f"\n===== {int(100 * drop)}% drop")
        print(result["buckets"].round(3).to_string(index=False))
        print(
            f"raw gap {result['raw_gap']:.2f} pts | volatility-adjusted gap "
            f"{result['adjusted_gap']:.2f} | clipped {result['adjusted_gap_clipped']:.2f}"
        )
        print(result["buckets_clipped"].round(3).to_string(index=False))
        print(
            "Cox:",
            {
                k: round(v, 6) if isinstance(v, float) else v
                for k, v in result["cox"].items()
            },
        )
        print(result["benchmark"].round(3).to_string(index=False))
    print(f"\nSaved {DETAILS_PATH} and {CHART_PATH}")


if __name__ == "__main__":
    main()
