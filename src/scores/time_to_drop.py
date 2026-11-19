"""Test 11: after a 10-K becomes public, how fast do stocks fall 50%?

Registered in docs/backtest.md ("Test 11", with method change 11a)
before any result was computed; the definitions here follow that entry.

Each observation is one scored company-year whose original 10-K was
filed on or before config.TIME_TO_DROP_LAST_FILING and whose score has
an M-Score, a Z'' and an F-Score. It starts on the first market trading
day on or after the filing date and is followed for 24 months:
- event: the first trading day after the start with an adjusted close
  at or below 50% of the start-day close;
- censored: no such day by the end of follow-up, or the prices stop
  first (then censored at the last price day).

Survival analysis in plain English. A survival curve answers "what
share of these stocks had NOT yet fallen 50% by day t?" It starts at
100% on day 0 and steps down each day some stock first hits the drop.
"Censored" means we stopped watching a stock before it dropped: either
the 24 months ran out or its prices stopped. We know it had not dropped
by then, but not what came after. The Kaplan-Meier method uses each
stock for exactly as long as we watched it, then removes it from the
count of stocks "still at risk", instead of wrongly counting it as
never dropping. The log-rank test asks whether two curves differ by
more than chance would explain.

The statistics come from scipy (scipy.stats.ecdf for Kaplan-Meier on
censored data, scipy.stats.logrank); lifelines, named when the test was
registered, cannot be installed with the project's pandas 3 (method
change 11a in docs/backtest.md).

This is an analysis for a class project, not investment advice.
"""

import matplotlib

matplotlib.use("Agg")  # draw to a file; no window (and no display needed)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import CensoredData, ecdf, logrank  # noqa: E402

import config  # noqa: E402
from src.scores import backtest  # noqa: E402

CHART_PATH = (
    config.PROJECT_ROOT / "docs" / "screenshots" / "test11_survival.png"
)
DETAILS_PATH = config.LOG_DIR / "backtest_time_to_drop.csv"
TIERS = ["0 flags", "1 flag", "2 flags", "3 flags"]
# The dashboard's marker colors (app/style.py), so the slide matches the
# app: green, yellow, orange, red.
TIER_COLORS = {
    "0 flags": "#0ca30c",
    "1 flag": "#fab219",
    "2 flags": "#eb6834",
    "3 flags": "#d03b3b",
}
# Floating-point slack so a close of exactly half counts as 50%.
RATIO_SLACK = 1e-12


def tier_label(flags):
    """Return "0 flags", "1 flag", "2 flags" or "3 flags"."""
    count = int(flags)
    return f"{count} flag" if count == 1 else f"{count} flags"


def follow_up_end(calendar, start):
    """Return the last trading day on or before start + 24 months."""
    limit = start + pd.DateOffset(months=config.TIME_TO_DROP_FOLLOW_UP_MONTHS)
    return calendar[calendar <= limit][-1]


def drop_outcome(stock_prices, start, end):
    """Return (event, duration_days, drop_date) for one observation.

    stock_prices is the stock's whole adjusted-close series (date index,
    NaN on days without a price). The reference is the close on start.
    - event = True: the first day after start with a close at or below
      50% of the reference; duration = calendar days from start to it.
    - event = False, censored at end: no such day within follow-up.
    - event = False, censored at the last price: the prices stop before
      end (no price anywhere after the stock's last one) without a drop.
    """
    window = stock_prices.loc[start:end].dropna()
    reference = window.iloc[0]
    after_start = window.iloc[1:]
    hit = after_start[
        after_start <= config.TIME_TO_DROP_THRESHOLD * reference + RATIO_SLACK
    ]
    if not hit.empty:
        drop_date = hit.index[0]
        return True, (drop_date - start).days, drop_date
    last_ever = stock_prices.last_valid_index()
    censor_date = last_ever if last_ever < end else end
    return False, (censor_date - start).days, pd.NaT


def observations(scores_df, financials_df, companies_df):
    """Return the candidate observations: scored company-years with all
    three scores and an original 10-K filed on or before the last
    filing date, with ticker and flags."""
    has_all = (
        scores_df["m_score"].notna()
        & scores_df["z_score"].notna()
        & scores_df["f_score"].notna()
    )
    scored = scores_df.loc[has_all, ["cik", "fiscal_year", "flags_raised"]]
    filed = financials_df[["cik", "fiscal_year", "filed_date"]]
    frame = scored.merge(filed, on=["cik", "fiscal_year"], how="inner")
    frame = frame[
        frame["filed_date"] <= pd.Timestamp(config.TIME_TO_DROP_LAST_FILING)
    ]
    frame = frame.merge(companies_df[["cik", "ticker"]], on="cik", how="left")
    return frame.sort_values(["cik", "fiscal_year"]).reset_index(drop=True)


def follow_observations(obs_df, price_wide, calendar):
    """Return obs_df with start, end, status and the outcome of each
    eligible observation (event, duration_days, drop_date, tier, group).

    status is "eligible" or why not (no_ticker, no_prices, short_history,
    under_min_price), from the same checks as earlier tests, applied on
    each observation's own start day.
    """
    frame = obs_df.copy()
    positions = calendar.searchsorted(frame["filed_date"].to_numpy())
    frame["start"] = [
        calendar[i] if i < len(calendar) else pd.NaT for i in positions
    ]
    frame["end"] = [follow_up_end(calendar, s) for s in frame["start"]]
    frame["status"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    for start, group in frame.groupby("start"):
        frame.loc[group.index, "status"] = backtest.price_status(
            group["ticker"], price_wide, calendar, start
        ).to_numpy()

    outcomes = []
    for row in frame.itertuples():
        if row.status != backtest.STATUS_ELIGIBLE:
            outcomes.append((np.nan, np.nan, pd.NaT))
            continue
        outcomes.append(
            drop_outcome(price_wide[row.ticker], row.start, row.end)
        )
    frame["event"] = pd.array([o[0] for o in outcomes], dtype="boolean")
    frame["duration_days"] = [o[1] for o in outcomes]
    frame["drop_date"] = pd.to_datetime([o[2] for o in outcomes])
    frame["tier"] = frame["flags_raised"].map(tier_label)
    frame["group"] = np.where(frame["flags_raised"] >= 1, "flagged", "clean")
    return frame


def censored_data(frame):
    """Return scipy CensoredData for eligible rows: drops are exact
    (uncensored) times; censored rows are "right-censored", meaning the
    drop, if any, came after that time."""
    dropped = frame["event"].astype(bool)
    return CensoredData(
        uncensored=frame.loc[dropped, "duration_days"].to_numpy(float),
        right=frame.loc[~dropped, "duration_days"].to_numpy(float),
    )


def survival_curve(frame):
    """Return the Kaplan-Meier survival function (scipy) for rows."""
    return ecdf(censored_data(frame)).sf


def tier_summary(eligible_df):
    """Return one row per tier and group: observations, drops, censored,
    Kaplan-Meier percent dropped by each horizon, and the median days to
    the drop only among stocks that dropped."""
    rows = []
    groups = [
        (tier, eligible_df[eligible_df["tier"] == tier]) for tier in TIERS
    ]
    groups += [
        ("Clean", eligible_df[eligible_df["group"] == "clean"]),
        ("Flagged", eligible_df[eligible_df["group"] == "flagged"]),
    ]
    for label, frame in groups:
        if frame.empty:
            continue
        curve = survival_curve(frame)
        dropped = frame["event"].astype(bool)
        row = {
            "group": label,
            "observations": len(frame),
            "drops": int(dropped.sum()),
            "censored": int((~dropped).sum()),
        }
        for months, days in config.TIME_TO_DROP_HORIZON_DAYS.items():
            row[f"pct_dropped_{months}m"] = 100 * (
                1 - float(curve.evaluate(days))
            )
        row["median_days_only_among_dropped"] = (
            float(frame.loc[dropped, "duration_days"].median())
            if dropped.any()
            else np.nan
        )
        rows.append(row)
    return pd.DataFrame(rows)


def registered_question(eligible_df):
    """Return question (a): two-sided log-rank test of Flagged (first)
    against Clean. statistic > 0 means Flagged's drops came earlier than
    expected if the groups were alike. Passes only if p is below
    config.TIME_TO_DROP_PASS_P and statistic > 0."""
    flagged = eligible_df[eligible_df["group"] == "flagged"]
    clean = eligible_df[eligible_df["group"] == "clean"]
    result = logrank(censored_data(flagged), censored_data(clean))
    return {
        "statistic": float(result.statistic),
        "p_value": float(result.pvalue),
        "flagged_faster": bool(result.statistic > 0),
        "passes": bool(
            result.pvalue < config.TIME_TO_DROP_PASS_P and result.statistic > 0
        ),
    }


def survival_chart(eligible_df, path=CHART_PATH):
    """Save the four tiers' Kaplan-Meier curves on one chart (PNG)."""
    days = np.arange(0, max(config.TIME_TO_DROP_HORIZON_DAYS.values()) + 1)
    figure, axis = plt.subplots(figsize=(10, 5.5), dpi=150)
    for tier in TIERS:
        frame = eligible_df[eligible_df["tier"] == tier]
        if frame.empty:
            continue
        share = 100 * survival_curve(frame).evaluate(days)
        axis.step(
            days,
            share,
            where="post",
            color=TIER_COLORS[tier],
            linewidth=2,
            label=f"{tier} (n = {len(frame):,})",
        )
    for months, day in config.TIME_TO_DROP_HORIZON_DAYS.items():
        axis.axvline(day, color="#c3c2b7", linewidth=0.8, linestyle="--")
        axis.text(day, 101, f"{months} mo", ha="center", fontsize=8)
    axis.set_xlim(0, days[-1] + 10)
    axis.set_ylim(None, 104)
    axis.set_xlabel("Days after the 10-K became public")
    axis.set_ylabel("Share not yet down 50% (%)")
    axis.set_title(
        "Time to a 50% price drop after a 10-K, by warnings raised "
        "(Kaplan-Meier, 10-Ks filed 2012 to mid-2024)",
        fontsize=11,
    )
    axis.legend(title="Warnings in that 10-K", loc="lower left")
    axis.grid(axis="y", color="#e1e0d9")
    figure.text(
        0.01,
        0.01,
        "Current tickers only (failed companies are mostly missing). "
        "Correlation, not cause. Class project, not investment advice.",
        fontsize=8,
        color="#52514e",
    )
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    figure.savefig(path)
    plt.close(figure)
    return path


def run_time_to_drop(scores_df, financials_df, companies_df, prices_df):
    """Run test 11; return the observation table, summary and question."""
    calendar = backtest.trading_calendar(prices_df)
    price_wide = backtest.price_table(prices_df, calendar)
    followed = follow_observations(
        observations(scores_df, financials_df, companies_df),
        price_wide,
        calendar,
    )
    eligible = followed[followed["status"] == backtest.STATUS_ELIGIBLE]
    return {
        "details": followed,
        "summary": tier_summary(eligible),
        "question": registered_question(eligible),
        "eligible": eligible,
    }


def main():
    """Run test 11 on data/processed/, save the details CSV and the
    chart, and print the results."""
    tables = run_time_to_drop(
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        pd.read_parquet(config.COMPANIES_PATH),
        pd.read_parquet(config.PRICES_PATH),
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    tables["details"].to_csv(DETAILS_PATH, index=False)
    survival_chart(tables["eligible"])
    print(tables["details"]["status"].value_counts().to_string())
    print()
    print(tables["summary"].round(2).to_string(index=False))
    print("\nRegistered question (a), Flagged vs Clean, log-rank:")
    print(tables["question"])
    print(f"\nSaved {DETAILS_PATH} and {CHART_PATH}")
    print(
        "Caution: current tickers only; overlapping observations make the"
        " p-value too optimistic;\ncorrelation, not cause; years already"
        " studied. Not investment advice."
    )


if __name__ == "__main__":
    main()
