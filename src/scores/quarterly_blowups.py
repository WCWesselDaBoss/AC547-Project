"""Test 13: do quarterly (TTM) flags predict blowups, and do they add
anything beyond the annual flags?

Registered in docs/backtest.md ("Test 13", with wording fix 13a) before
any result was computed; the definitions here follow that entry and
reuse tests 10 and 11's code wherever a rule is the same:
- eligibility: backtest.price_status on the entry day (current ticker,
  a price on each of the 20 trading days through entry, close >= $5);
- outcome: blowups.classify_window (a close at or below 50% of the entry
  close within 12 months; prices that stop first with no blowup are
  "unknown" and left out of every rate and model);
- annual flag at the same date: backtest.latest_scores (latest 10-K
  filed strictly before entry; stale if filed more than 15 months
  before entry).

Observations: company-quarters in scores_quarterly with all three
scores and available_date from 2014-01-01 to 2025-10-31. Entry: the
first SPY trading day strictly after available_date.

Registered questions (pass: positive quarterly-Flagged coefficient with
t >= 3.0), linear probability models with entry-quarter cohort fixed
effects and standard errors clustered by company:
(a) blowup ~ quarterly-Flagged;
(b) among observations with a usable annual flag status,
    blowup ~ quarterly-Flagged + annual-Flagged.

Read-only: it reads the processed tables and writes
data/logs/backtest_quarterly_blowups.csv and
docs/screenshots/test13_blowups.png. It changes no table.

Run: python -m src.scores.quarterly_blowups
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402

import config  # noqa: E402
from src.scores import backtest, blowups  # noqa: E402
from src.scores import quarterly_scores as qs  # noqa: E402

FIRST_AVAILABLE = pd.Timestamp("2014-01-01")
LAST_AVAILABLE = pd.Timestamp("2025-10-31")
FOLLOW_UP_MONTHS = 12
PASS_T = 3.0
DETAILS_PATH = config.LOG_DIR / "backtest_quarterly_blowups.csv"
CHART_PATH = (
    config.PROJECT_ROOT / "docs" / "screenshots" / "test13_blowups.png"
)
ANNUAL_LOG = config.LOG_DIR / "backtest_blowups.csv"

BLOWUP = "blowup"
UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Observations, entry and cohorts
# ---------------------------------------------------------------------------
def all_three(frame):
    """Return True where M-Score, Z'' and F-Score are all present."""
    return (
        frame["m_score"].notna()
        & frame["z_score"].notna()
        & frame["f_score"].notna()
    )


def observations(scores_quarterly_df, companies_df):
    """Return the registered observations: scored company-quarters with
    all three scores and available_date in the registered window, with
    the company's ticker and quarterly flag status."""
    frame = scores_quarterly_df[
        all_three(scores_quarterly_df)
        & scores_quarterly_df["available_date"].between(
            FIRST_AVAILABLE, LAST_AVAILABLE
        )
    ]
    frame = frame[
        [
            "cik",
            "fiscal_year",
            "fiscal_quarter",
            "period_end",
            "available_date",
            "flags_raised",
        ]
    ].merge(companies_df[["cik", "ticker"]], on="cik", how="left")
    frame["quarterly_flagged"] = (frame["flags_raised"] >= 1).astype(int)
    return frame.sort_values(["cik", "period_end"]).reset_index(drop=True)


def entry_days(available_dates, calendar):
    """Return the first trading day strictly after each date (NaT if
    there is none in the calendar)."""
    positions = calendar.searchsorted(
        pd.DatetimeIndex(available_dates), side="right"
    )
    return pd.DatetimeIndex(
        [calendar[i] if i < len(calendar) else pd.NaT for i in positions]
    )


def cohort(entry):
    """Return the calendar quarter of each entry day, e.g. "2016Q3"."""
    return pd.DatetimeIndex(entry).to_period("Q").astype(str)


def follow_up_end(calendar, entry):
    """Return the last trading day on or before entry + 12 months."""
    limit = entry + pd.DateOffset(months=FOLLOW_UP_MONTHS)
    return calendar[calendar <= limit][-1]


# ---------------------------------------------------------------------------
# Annual flag at the same date, and earlier quarterly status
# ---------------------------------------------------------------------------
def annual_point_in_time(entries, scores_df, financials_df):
    """Return one row per (cik, entry) with the annual flag status known
    on the entry day: test 10's backtest.latest_scores (latest 10-K
    filed strictly before entry; stale if more than 15 months old). The
    status is usable only if not stale and all three annual scores are
    present. Also returns the annual period end and filing date (for the
    flag's age)."""
    period_ends = financials_df[["cik", "fiscal_year", "period_end"]]
    frames = []
    for entry, ciks in entries.groupby("entry")["cik"]:
        latest = backtest.latest_scores(scores_df, financials_df, entry)
        latest = latest[latest["cik"].isin(ciks)]
        frames.append(latest.assign(entry=entry))
    if not frames:
        return pd.DataFrame(
            columns=[
                "cik",
                "entry",
                "annual_usable",
                "annual_flagged",
                "annual_period_end",
                "annual_filed_date",
            ]
        )
    annual = pd.concat(frames, ignore_index=True).merge(
        period_ends, on=["cik", "fiscal_year"], how="left"
    )
    usable = ~annual["is_stale"] & all_three(annual)
    return pd.DataFrame(
        {
            "cik": annual["cik"],
            "entry": annual["entry"],
            "annual_usable": usable.to_numpy(),
            "annual_flagged": np.where(
                usable, (annual["flags_raised"] >= 1).astype(float), np.nan
            ),
            "annual_period_end": annual["period_end"],
            "annual_filed_date": annual["filed_date"],
        }
    )


def earlier_status(obs_df, scores_quarterly_df):
    """Return obs_df with the quarterly flag status of the previous
    fiscal quarter and of the same quarter one year earlier (1 flagged,
    0 clean, NaN when that quarter does not have all three scores), and
    the newly / persistently flagged indicators."""
    scored = scores_quarterly_df[all_three(scores_quarterly_df)]
    status = scored[["cik", "fiscal_year", "fiscal_quarter"]].assign(
        flagged=(scored["flags_raised"] >= 1).astype(float).to_numpy(),
        index=scored["fiscal_year"] * 4 + scored["fiscal_quarter"] - 1,
    )[["cik", "index", "flagged"]]
    frame = obs_df.assign(
        index=obs_df["fiscal_year"] * 4 + obs_df["fiscal_quarter"] - 1
    )
    for name, back in [("previous_flagged", 1), ("year_ago_flagged", 4)]:
        earlier = status.assign(index=status["index"] + back).rename(
            columns={"flagged": name}
        )
        frame = frame.merge(earlier, on=["cik", "index"], how="left")
    now = frame["quarterly_flagged"] == 1
    frame["newly_flagged"] = now & (frame["previous_flagged"] == 0)
    frame["persistently_flagged"] = now & (frame["year_ago_flagged"] == 1)
    return frame.drop(columns="index")


# ---------------------------------------------------------------------------
# Follow-up
# ---------------------------------------------------------------------------
def follow(obs_df, price_wide, calendar):
    """Return obs_df with entry, end, cohort, eligibility status, and for
    eligible rows the outcome (blowup, no_blowup or unknown)."""
    frame = obs_df.copy()
    frame["entry"] = entry_days(frame["available_date"], calendar)
    frame["status"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame["outcome"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    frame["min_ratio"] = np.nan
    frame["end"] = pd.NaT
    for entry, group in frame.groupby("entry"):
        status = backtest.price_status(
            group["ticker"], price_wide, calendar, entry
        )
        frame.loc[group.index, "status"] = status.to_numpy()
        end = follow_up_end(calendar, entry)
        frame.loc[group.index, "end"] = end
        eligible = group[(status == backtest.STATUS_ELIGIBLE).to_numpy()]
        if eligible.empty:
            continue
        tickers = list(dict.fromkeys(eligible["ticker"]))
        outcomes = blowups.classify_window(
            price_wide, tickers, entry, end
        ).set_index("ticker")
        frame.loc[eligible.index, "outcome"] = outcomes.loc[
            eligible["ticker"], "outcome"
        ].to_numpy()
        frame.loc[eligible.index, "min_ratio"] = outcomes.loc[
            eligible["ticker"], "min_ratio"
        ].to_numpy()
    frame["cohort"] = cohort(frame["entry"])
    return frame


def known_outcomes(frame):
    """Return eligible rows with a known outcome and a 0/1 blowup."""
    known = frame[
        (frame["status"] == backtest.STATUS_ELIGIBLE)
        & frame["outcome"].isin([BLOWUP, "no_blowup"])
    ].copy()
    known["blowup"] = (known["outcome"] == BLOWUP).astype(int)
    return known


# ---------------------------------------------------------------------------
# Registered questions
# ---------------------------------------------------------------------------
def clustered_model(data, formula):
    """Return an OLS (linear probability) fit with cohort fixed effects
    in the formula and standard errors clustered by company."""
    return smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["cik"].to_numpy()}
    )


def question_row(name, fit, data, term="quarterly_flagged"):
    """Return one registered question's result."""
    coefficient = float(fit.params[term])
    t_value = float(fit.tvalues[term])
    return {
        "question": name,
        "observations": len(data),
        "companies": int(data["cik"].nunique()),
        "cohorts": int(data["cohort"].nunique()),
        "coefficient": coefficient,
        "std_error": float(fit.bse[term]),
        "t": t_value,
        "passed": bool(coefficient > 0 and t_value >= PASS_T),
    }


def registered_questions(known):
    """Return the two registered questions' results (and the annual
    coefficient in (b))."""
    fit_a = clustered_model(known, "blowup ~ quarterly_flagged + C(cohort)")
    rows = [question_row("(a) quarterly-Flagged", fit_a, known)]
    with_annual = known[known["annual_usable"].fillna(False).astype(bool)]
    fit_b = clustered_model(
        with_annual,
        "blowup ~ quarterly_flagged + annual_flagged + C(cohort)",
    )
    row_b = question_row(
        "(b) quarterly-Flagged, with annual-Flagged", fit_b, with_annual
    )
    row_b["annual_coefficient"] = float(fit_b.params["annual_flagged"])
    row_b["annual_t"] = float(fit_b.tvalues["annual_flagged"])
    rows.append(row_b)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Descriptive tables
# ---------------------------------------------------------------------------
def rate_table(frame, by):
    """Return observations, blowups, unknowns and the blowup rate by a
    column (the rate leaves unknowns out)."""
    eligible = frame[frame["status"] == backtest.STATUS_ELIGIBLE]
    grouped = eligible.groupby(by, dropna=False)["outcome"]
    table = pd.DataFrame(
        {
            "observations": grouped.size(),
            "blowups": grouped.apply(lambda s: int((s == BLOWUP).sum())),
            "unknowns": grouped.apply(lambda s: int((s == UNKNOWN).sum())),
        }
    )
    known = table["observations"] - table["unknowns"]
    table["blowup_rate"] = table["blowups"] / known
    return table.reset_index()


def annual_test10_rates(path=ANNUAL_LOG):
    """Return test 10's pooled blowup rate by annual flag count (the
    comparison pool, all three scores), from test 10's own log."""
    log = pd.read_csv(path)
    pool = log[(log["pool"] == "comparison") & log["all_three_scores"]]
    known = pool[pool["outcome"] != UNKNOWN]
    rates = known.groupby("flags_raised")["outcome"].apply(
        lambda s: (s == BLOWUP).mean()
    )
    counts = known.groupby("flags_raised").size()
    return pd.DataFrame(
        {
            "flags": rates.index.astype(int),
            "annual_rate": rates.to_numpy(),
            "annual_known": counts.to_numpy(),
        }
    )


def flag_ages(known):
    """Return the median age of the flag at entry, in days, annual vs
    quarterly: from the end of the period described, and from the day
    the flag became public."""
    usable = known[known["annual_usable"].fillna(False).astype(bool)]
    return pd.DataFrame(
        [
            {
                "basis": "quarterly",
                "observations": len(known),
                "days_since_period_end": (
                    known["entry"] - known["period_end"]
                ).dt.days.median(),
                "days_since_public": (
                    known["entry"] - known["available_date"]
                ).dt.days.median(),
            },
            {
                "basis": "annual (same observations, usable status)",
                "observations": len(usable),
                "days_since_period_end": (
                    usable["entry"] - usable["annual_period_end"]
                ).dt.days.median(),
                "days_since_public": (
                    usable["entry"] - usable["annual_filed_date"]
                ).dt.days.median(),
            },
        ]
    )


def blowup_chart(by_count, annual_rates, path=CHART_PATH):
    """Save the bar chart of blowup rate by flag count, quarterly
    (test 13) next to annual (test 10)."""
    merged = by_count.rename(columns={"flags_raised": "flags"}).merge(
        annual_rates, on="flags", how="outer"
    )
    x = np.arange(len(merged))
    figure, axis = plt.subplots(figsize=(8, 4.5))
    axis.bar(
        x - 0.2,
        merged["annual_rate"] * 100,
        0.4,
        label="Annual flags (test 10, June 30 portfolios)",
        color="#4C78A8",
    )
    axis.bar(
        x + 0.2,
        merged["blowup_rate"] * 100,
        0.4,
        label="Quarterly (TTM) flags (test 13)",
        color="#F58518",
    )
    axis.set_xticks(
        x, [f"{int(f)} flag{'' if f == 1 else 's'}" for f in merged["flags"]]
    )
    axis.set_ylabel("12-month blowup rate (%)")
    axis.set_title("Share of stocks falling 50% or more within 12 months")
    axis.legend()
    axis.grid(axis="y", alpha=0.3)
    figure.text(
        0.01,
        0.01,
        "Class project analysis, not investment advice. Current tickers "
        "only; quarterly flags not backtested before this test.",
        fontsize=7,
        color="gray",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return merged


# ---------------------------------------------------------------------------
# The whole test
# ---------------------------------------------------------------------------
def run_quarterly_blowups(
    scores_quarterly_df, scores_df, financials_df, companies_df, prices_df
):
    """Run test 13; return every table."""
    calendar = backtest.trading_calendar(prices_df)
    price_wide = backtest.price_table(prices_df, calendar)
    obs = earlier_status(
        observations(scores_quarterly_df, companies_df), scores_quarterly_df
    )
    followed = follow(obs, price_wide, calendar)
    annual = annual_point_in_time(
        followed[["cik", "entry"]].dropna().drop_duplicates(),
        scores_df,
        financials_df,
    )
    followed = followed.merge(annual, on=["cik", "entry"], how="left")
    followed["annual_usable"] = (
        followed["annual_usable"].fillna(False).astype(bool)
    )
    known = known_outcomes(followed)
    eligible = followed[followed["status"] == backtest.STATUS_ELIGIBLE]
    two_by_two = rate_table(
        eligible[eligible["annual_usable"]].assign(
            annual=lambda f: np.where(
                f["annual_flagged"] == 1, "annual-Flagged", "annual-Clean"
            ),
            quarterly=lambda f: np.where(
                f["quarterly_flagged"] == 1,
                "quarterly-Flagged",
                "quarterly-Clean",
            ),
        ),
        ["annual", "quarterly"],
    )
    newly = rate_table(
        eligible.assign(
            group=np.select(
                [
                    eligible["newly_flagged"],
                    eligible["persistently_flagged"],
                ],
                ["newly flagged", "persistently flagged"],
                "other",
            )
        ),
        "group",
    )
    both = rate_table(
        eligible[
            eligible["newly_flagged"] & eligible["persistently_flagged"]
        ].assign(group="newly and persistently (both)"),
        "group",
    )
    return {
        "details": followed,
        "status_counts": followed["status"].value_counts(),
        "known": known,
        "questions": registered_questions(known),
        "by_count": rate_table(eligible, "flags_raised"),
        "two_by_two": two_by_two,
        "newly_vs_persistent": pd.concat([newly, both], ignore_index=True),
        "ages": flag_ages(known),
    }


def main():
    """Run test 13 on data/processed/, save the details and the chart,
    and print every result."""
    tables = run_quarterly_blowups(
        pd.read_parquet(qs.SCORES_QUARTERLY_PATH),
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        pd.read_parquet(config.COMPANIES_PATH),
        pd.read_parquet(config.PRICES_PATH),
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    tables["details"].to_csv(DETAILS_PATH, index=False)
    chart = blowup_chart(tables["by_count"], annual_test10_rates())
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print("Observations by status:")
        print(tables["status_counts"].to_string())
        outcomes = tables["details"]["outcome"].value_counts(dropna=False)
        print("\nOutcomes (eligible only):")
        print(outcomes.to_string())
        print("\nRegistered questions:")
        print(tables["questions"].to_string(index=False))
        print("\nBy quarterly flag count, next to test 10 (annual):")
        print(chart.to_string(index=False))
        print("\nAnnual x quarterly (usable annual status only):")
        print(tables["two_by_two"].to_string(index=False))
        print("\nNewly vs persistently flagged:")
        print(tables["newly_vs_persistent"].to_string(index=False))
        print("\nMedian flag age at entry (days):")
        print(tables["ages"].to_string(index=False))
        known = tables["known"]
        print(
            f"\nKnown outcomes: {len(known):,} observations, "
            f"{known['cik'].nunique():,} companies, "
            f"{known['cohort'].nunique()} cohorts "
            f"({known['cohort'].min()} to {known['cohort'].max()})."
        )
    print(f"\nSaved {DETAILS_PATH} and {CHART_PATH}")
    print(
        "Caution: current tickers only; overlapping observations; "
        "unaudited 10-Q data;\ncorrelation, not cause; years already "
        "studied. Not investment advice."
    )


if __name__ == "__main__":
    main()
