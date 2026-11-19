"""Test 10: do flagged companies blow up more often?

Registered in docs/backtest.md ("Test 10") before any result was
computed; the definitions here follow that entry exactly.

For each June 30 formation date from 2014 to 2025 (the backtest's
trade-date rule), every stock in the comparison group is followed to
the next trade date (the 2025 window ends 2026-06-30):
- blowup: its adjusted close falls to config.BLOWUP_THRESHOLD (50%) or
  less of its trade-date close on any trading day in the window;
- unknown: its prices stop mid-window without ever reaching 50%. It is
  reported separately and left out of the rate, never counted as a
  non-blowup;
- no_blowup: otherwise.

Groups, among companies whose latest score has all three scores (so a
missing score never counts as "no warning"): Clean (0 flags), Flagged
(1 or more), and 0, 1, 2 and 3 flags separately (descriptive). The
questions compare Flagged's and Clean's yearly rates in the comparison
group (a) and in the test-9 large_500 pool (b).

This is an analysis for a class project, not investment advice.
Results and limitations: docs/backtest.md.
"""

import numpy as np
import pandas as pd

import config
from src.scores import backtest, public_float

POOLS = ("comparison", "large_500")
OUTCOMES = ("blowup", "no_blowup", "unknown")
# Floating-point slack so a price of exactly half counts as 50%.
RATIO_SLACK = 1e-12


def blowup_periods(calendar):
    """Return the holding windows: formation_date, start, end.

    The backtest's holding_periods, except that the last window ends on
    the last trading day on or before config.BLOWUP_FINAL_END.
    """
    periods = backtest.holding_periods(calendar, config.BLOWUP_FORMATION_DATES)
    final_end = calendar[calendar <= pd.Timestamp(config.BLOWUP_FINAL_END)]
    periods.loc[periods.index[-1], "end"] = final_end[-1]
    return periods


def classify_window(price_wide, tickers, start, end):
    """Return one row per ticker: ticker, outcome, min_ratio, stopped.

    min_ratio is the lowest adjusted close in the window divided by the
    trade-date close. stopped means the stock has no price anywhere in
    the data after its last price in the window, and that last price is
    before the window's end (the backtest's delisting rule).
    """
    window = backtest.price_window(price_wide, start, end)[list(tickers)]
    ratios = window / window.iloc[0]
    min_ratio = ratios.min()
    hit = min_ratio <= config.BLOWUP_THRESHOLD + RATIO_SLACK
    last_ever = price_wide[list(tickers)].apply(pd.Series.last_valid_index)
    stopped = last_ever < end
    outcome = np.where(
        hit, "blowup", np.where(stopped, "unknown", "no_blowup")
    )
    return pd.DataFrame(
        {
            "ticker": pd.array(list(tickers), dtype="string"),
            "outcome": outcome,
            "min_ratio": min_ratio.to_numpy(),
            "stopped": stopped.to_numpy(),
        }
    )


def flag_group(flags_raised, all_three_scores):
    """Return "clean", "flagged" or "not_grouped" for each company.

    Only companies with all three scores are grouped, so a missing
    score never counts as "no warning".
    """
    flags = pd.Series(flags_raised).astype("Float64")
    grouped = pd.Series(all_three_scores).astype(bool).to_numpy()
    return pd.Series(
        np.where(
            ~grouped,
            "not_grouped",
            np.where(flags.fillna(0).to_numpy() >= 1, "flagged", "clean"),
        ),
        index=flags.index,
        dtype="string",
    )


def blowup_details(pool_df, price_wide, periods_df):
    """Return one row per pool, formation date and stock with its
    outcome and group.

    pool_df has columns pool, formation_date, cik, ticker, flags_raised
    and all_three_scores.
    """
    frames = []
    for period in periods_df.itertuples(index=False):
        in_period = pool_df[pool_df["formation_date"] == period.formation_date]
        for pool, members in in_period.groupby("pool", sort=False):
            outcomes = classify_window(
                price_wide,
                members["ticker"].tolist(),
                period.start,
                period.end,
            )
            members = members.reset_index(drop=True)
            frames.append(
                members.assign(
                    start=period.start,
                    end=period.end,
                    outcome=outcomes["outcome"].to_numpy(),
                    min_ratio=outcomes["min_ratio"].to_numpy(),
                    stopped=outcomes["stopped"].to_numpy(),
                )
            )
    details = pd.concat(frames, ignore_index=True)
    details["year"] = details["formation_date"].dt.year
    details["group"] = flag_group(
        details["flags_raised"], details["all_three_scores"]
    ).to_numpy()
    return details


def count_outcomes(frame):
    """Return stocks, blowups, unknowns and rate for a set of stocks.

    rate = blowups / (stocks - unknowns); NaN when every stock is
    unknown or there are none.
    """
    stocks = len(frame)
    blowups = int((frame["outcome"] == "blowup").sum())
    unknowns = int((frame["outcome"] == "unknown").sum())
    known = stocks - unknowns
    return {
        "stocks": stocks,
        "blowups": blowups,
        "unknowns": unknowns,
        "rate": blowups / known if known else np.nan,
    }


def group_frames(details):
    """Yield (group label, rows) for Clean, Flagged, 0-3 flags and the
    whole pool (every stock, grouped or not: market context)."""
    grouped = details[details["group"] != "not_grouped"]
    yield "clean", grouped[grouped["group"] == "clean"]
    yield "flagged", grouped[grouped["group"] == "flagged"]
    flags = grouped["flags_raised"].astype("Float64").fillna(0)
    for count in range(4):
        yield f"{count}_flags", grouped[flags.to_numpy() == count]
    yield "whole_pool", details


def blowup_rates(details):
    """Return one row per pool, year and group with counts and rate."""
    rows = []
    for (pool, year), frame in details.groupby(["pool", "year"], sort=True):
        for group, rows_in_group in group_frames(frame):
            rows.append(
                {
                    "pool": pool,
                    "year": year,
                    "group": group,
                    **count_outcomes(rows_in_group),
                }
            )
    return pd.DataFrame(rows)


def pooled_rates(details):
    """Return the 12-year pooled counts and rate per pool and group,
    plus each group's rate divided by Clean's (ratio_to_clean)."""
    rows = []
    for pool, frame in details.groupby("pool", sort=False):
        for group, rows_in_group in group_frames(frame):
            rows.append(
                {"pool": pool, "group": group, **count_outcomes(rows_in_group)}
            )
    pooled = pd.DataFrame(rows)
    clean = pooled[pooled["group"] == "clean"].set_index("pool")["rate"]
    pooled["ratio_to_clean"] = pooled["rate"] / pooled["pool"].map(clean)
    return pooled


def registered_questions(rates):
    """Return questions (a) and (b): per pool, the yearly differences
    Flagged rate - Clean rate, with mean, median, years Flagged was
    higher, years compared and the t-statistic. Pass mark t >= 2.2."""
    rows = []
    for pool, frame in rates.groupby("pool", sort=False):
        wide = frame.pivot(index="year", columns="group", values="rate")
        difference = (wide["flagged"] - wide["clean"]).dropna()
        t_stat = backtest.t_statistic(difference)
        rows.append(
            {
                "pool": pool,
                "years": len(difference),
                "mean_difference": difference.mean(),
                "median_difference": difference.median(),
                "years_flagged_higher": int((difference > 0).sum()),
                "t": t_stat,
                "passes": bool(t_stat >= 2.2) if pd.notna(t_stat) else False,
            }
        )
    return pd.DataFrame(rows)


def build_pools(
    scores_df,
    financials_df,
    companies_df,
    price_wide,
    calendar,
    periods,
    floats_df,
):
    """Return the comparison group and the large_500 pool as one table
    (column pool), with flags_raised and all_three_scores."""
    universe, _ = backtest.universe_picks(
        scores_df, financials_df, companies_df, price_wide, calendar, periods
    )
    # Whether the score behind each pick has all three scores (the
    # universe table itself is left unchanged).
    has_all = scores_df[["cik", "fiscal_year"]].assign(
        all_three_scores=(
            scores_df["m_score"].notna()
            & scores_df["z_score"].notna()
            & scores_df["f_score"].notna()
        ).to_numpy()
    )
    universe = universe.merge(has_all, on=["cik", "fiscal_year"], how="left")
    columns = [
        "formation_date",
        "cik",
        "ticker",
        "flags_raised",
        "all_three_scores",
    ]
    comparison = universe[columns].assign(pool="comparison")
    ranks = backtest.book_to_market(universe, financials_df, floats_df)
    large = backtest.large_cap_picks(ranks, "large_500")[
        ["formation_date", "cik"]
    ]
    large = large.merge(
        comparison.drop(columns="pool"), on=["formation_date", "cik"]
    ).assign(pool="large_500")
    return pd.concat([comparison, large], ignore_index=True)


def run_blowup_test(
    scores_df, financials_df, companies_df, prices_df, floats_df
):
    """Run test 10; return details, rates, pooled rates and questions."""
    calendar = backtest.trading_calendar(prices_df)
    periods = blowup_periods(calendar)
    price_wide = backtest.price_table(prices_df, calendar)
    pools = build_pools(
        scores_df,
        financials_df,
        companies_df,
        price_wide,
        calendar,
        periods,
        floats_df,
    )
    details = blowup_details(pools, price_wide, periods)
    rates = blowup_rates(details)
    return {
        "details": details,
        "rates": rates,
        "pooled": pooled_rates(details),
        "questions": registered_questions(rates),
    }


def main():
    """Run test 10 on data/processed/ and write data/logs/
    backtest_blowups.csv (one row per stock and window) and
    backtest_blowup_rates.csv (rates by pool, year and group)."""
    companies_df = pd.read_parquet(config.COMPANIES_PATH)
    floats_df = public_float.load_public_float(
        companies_df.loc[~companies_df["is_excluded"], "cik"].tolist()
    )
    tables = run_blowup_test(
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
        companies_df,
        pd.read_parquet(config.PRICES_PATH),
        floats_df,
    )
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    tables["details"].to_csv(
        config.LOG_DIR / "backtest_blowups.csv", index=False
    )
    tables["rates"].to_csv(
        config.LOG_DIR / "backtest_blowup_rates.csv", index=False
    )
    print("Registered questions (Flagged rate - Clean rate, by year):")
    print(tables["questions"].round(4).to_string(index=False))
    print("\nPooled 12-year rates:")
    print(tables["pooled"].round(4).to_string(index=False))
    print(
        "\nCaution: current tickers only (companies that blew up and"
        " delisted are likely missing);\ncorrelation, not cause; years"
        " already studied. Not investment advice."
    )


if __name__ == "__main__":
    main()
