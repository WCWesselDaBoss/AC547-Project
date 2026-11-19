"""Test 12 (exploratory): test 11 repeated for drops of 10% to 90%.

Registered in docs/backtest.md ("Test 12") before any result was
computed. Test 11 asked how fast stocks fell 50% after a 10-K, by flag
count; this asks whether the Flagged-Clean gap grows or shrinks with the
size of the drop. Every definition is test 11's (src/scores/
time_to_drop.py): the same observations, start, eligibility, 24-month
follow-up, censoring and groups. Only the event changes: the first
close at or below (100% - d) of the start price, for each drop size d in
config.DROP_SIZES.

Eligibility does not depend on the drop size, so it is checked once;
each drop size then re-reads every eligible stock's prices.

This is an analysis for a class project, not investment advice.
"""

import matplotlib

matplotlib.use("Agg")  # draw to a file; no window
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
from src.scores import backtest, time_to_drop  # noqa: E402

CHART_PATH = (
    config.PROJECT_ROOT / "docs" / "screenshots" / "test12_drop_sizes.png"
)
DETAILS_PATH = config.LOG_DIR / "backtest_drop_sizes.csv"


def bonferroni_bar():
    """Return the p-value each log-rank test must beat: the registered
    0.01 divided by the number of drop sizes tested."""
    return config.TIME_TO_DROP_PASS_P / len(config.DROP_SIZES)


def outcomes_at(eligible_df, price_wide, drop_size):
    """Return eligible_df with event, duration_days and drop_date for one
    drop size (0.3 = a 30% drop, so the close must reach 70% or less)."""
    frame = eligible_df.copy()
    threshold = 1 - drop_size
    outcomes = [
        time_to_drop.drop_outcome(
            price_wide[row.ticker], row.start, row.end, threshold
        )
        for row in frame.itertuples()
    ]
    frame["event"] = pd.array([o[0] for o in outcomes], dtype="boolean")
    frame["duration_days"] = [o[1] for o in outcomes]
    frame["drop_date"] = pd.to_datetime([o[2] for o in outcomes])
    frame["drop_size"] = drop_size
    return frame


def size_results(frame):
    """Return (summary rows, log-rank row) for one drop size's outcomes.

    The summary is test 11's tier_summary; the log-rank row adds whether
    p is below the Bonferroni bar with Flagged faster."""
    summary = time_to_drop.tier_summary(frame)
    question = time_to_drop.registered_question(frame)
    bar = bonferroni_bar()
    question["below_bonferroni_bar"] = bool(
        question["p_value"] < bar and question["statistic"] > 0
    )
    drop_size = frame["drop_size"].iloc[0]
    return (
        summary.assign(drop_size=drop_size),
        {"drop_size": drop_size, **question},
    )


def drop_size_chart(summary_df, path=CHART_PATH):
    """Save drop size against the 24-month Kaplan-Meier percent that
    reached it, one line per flag tier (PNG)."""
    figure, axis = plt.subplots(figsize=(10, 5.5), dpi=150)
    for tier in time_to_drop.TIERS:
        rows = summary_df[summary_df["group"] == tier]
        if rows.empty:
            continue
        axis.plot(
            100 * rows["drop_size"],
            rows["pct_dropped_24m"],
            marker="o",
            linewidth=2,
            color=time_to_drop.TIER_COLORS[tier],
            label=f"{tier} (n = {int(rows['observations'].iloc[0]):,})",
        )
    axis.set_xticks(100 * np.array(config.DROP_SIZES))
    axis.set_xticklabels([f"{int(100 * d)}%" for d in config.DROP_SIZES])
    axis.set_xlabel(
        "Size of the price drop from the day the 10-K became public"
    )
    axis.set_ylabel("Share that fell this much within 24 months (%)")
    axis.set_ylim(0, 100)
    axis.set_title(
        "How often stocks fell by each amount within 24 months of a 10-K, "
        "by warnings raised (Kaplan-Meier)",
        fontsize=11,
    )
    axis.legend(title="Warnings in that 10-K", loc="upper right")
    axis.grid(color="#e1e0d9")
    figure.text(
        0.01,
        0.01,
        "Exploratory (chosen after test 11). Current tickers only. "
        "Correlation, not cause. Class project, not investment advice.",
        fontsize=8,
        color="#52514e",
    )
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    figure.savefig(path)
    plt.close(figure)
    return path


def run_drop_sizes(scores_df, financials_df, companies_df, prices_df):
    """Run test 12; return details, summary and log-rank tables."""
    calendar = backtest.trading_calendar(prices_df)
    price_wide = backtest.price_table(prices_df, calendar)
    followed = time_to_drop.follow_observations(
        time_to_drop.observations(scores_df, financials_df, companies_df),
        price_wide,
        calendar,
    )
    eligible = followed[followed["status"] == backtest.STATUS_ELIGIBLE]
    details, summaries, questions = [], [], []
    for drop_size in config.DROP_SIZES:
        frame = outcomes_at(eligible, price_wide, drop_size)
        summary, question = size_results(frame)
        details.append(frame)
        summaries.append(summary)
        questions.append(question)
    return {
        "details": pd.concat(details, ignore_index=True),
        "summary": pd.concat(summaries, ignore_index=True),
        "questions": pd.DataFrame(questions),
    }


def main():
    """Run test 12 on data/processed/, save the details CSV and chart,
    and print the results."""
    tables = run_drop_sizes(
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        pd.read_parquet(config.COMPANIES_PATH),
        pd.read_parquet(config.PRICES_PATH),
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    tables["details"].to_csv(DETAILS_PATH, index=False)
    drop_size_chart(tables["summary"])
    pd.set_option("display.width", 220)
    print(tables["summary"].round(2).to_string(index=False))
    print(f"\nLog-rank, Flagged vs Clean (bar p < {bonferroni_bar():.5f}):")
    print(tables["questions"].to_string(index=False))
    print(f"\nSaved {DETAILS_PATH} and {CHART_PATH}")


if __name__ == "__main__":
    main()
