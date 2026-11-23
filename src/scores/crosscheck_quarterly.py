"""Quarterly upgrade, step 5: cross-check TTM data and scores against the
annual tables, and report coverage. Read-only; writes CSV files to
verification/.

1. Q4 TTM vs financials_annual, line item by line item. A fourth-quarter
   TTM covers the same fiscal year as the 10-K, so the two should agree.
   Every disagreement is put into one cause, from the ttm_sources rows:
   - flows whose Q4 is "annual minus 9 months":
     "annual_value_differs": the 12-month value used is not the one in
       financials_annual (a different tag or filing was the original);
     "quarters_do_not_add_to_9_months": the original Q1 to Q3 values do
       not add up to the 9-month year to date (a quarter was re-reported
       or restated in a later 10-Q). By algebra, TTM - annual = (Q1 + Q2
       + Q3) - 9 months whenever the 12-month value agrees.
   - flows whose Q4 was reported as a 3-month value: "q4_reported_3_months".
   - flows whose Q4 is a year-to-date difference that never used the
     12-month value (rare): "other".
   - balances: "first_reported_in_another_filing" (the quarter-end value's
     original filing is not that year's 10-K) or "same_filing_other_tag".
   - values derived from other columns in the TTM row (no source rows):
     "derived_in_ttm".
2. Q4 scores vs annual scores for the same company-year.
3. Coverage: each score by fiscal quarter, next to annual.

Run: python -m src.scores.crosscheck_quarterly
"""

import numpy as np
import pandas as pd

import config
from src.pipeline import financials, ttm
from src.scores import quarterly_scores as qs

VERIFICATION_DIR = config.PROJECT_ROOT / "verification"
LINE_ITEM_CSV = VERIFICATION_DIR / "quarterly_crosscheck_line_items.csv"
SCORES_CSV = VERIFICATION_DIR / "quarterly_crosscheck_scores.csv"
COVERAGE_CSV = VERIFICATION_DIR / "quarterly_coverage.csv"

ITEMS = financials.VALUE_COLUMNS[:18]  # the 18 line items, no components
FLOW_ITEMS = [item for item in ITEMS if item in ttm.FLOW_ITEMS]
# Agreement: within 0.5% of the annual value, or $10,000 (filers report in
# thousands, so four rounded quarters can miss the annual total by a few
# thousand dollars without any real difference).
RELATIVE_TOLERANCE = 0.005
ABSOLUTE_TOLERANCE = 10_000
SCORE_TOLERANCE = 0.01


def agrees(left, right):
    """Return True where two values agree within the tolerances."""
    limit = np.maximum(RELATIVE_TOLERANCE * right.abs(), ABSOLUTE_TOLERANCE)
    return (left - right).abs() <= limit


def q4_pairs(ttm_df, annual_df):
    """Return long rows: one per company-year and line item present in
    both the Q4 TTM row and financials_annual."""
    q4 = ttm_df[ttm_df["fiscal_quarter"] == 4]
    keep = ["cik", "fiscal_year", "period_end"]
    ttm_long = q4[keep + ITEMS].melt(
        id_vars=keep, var_name="line_item", value_name="ttm_value"
    )
    annual_long = annual_df[["cik", "fiscal_year", "accession"] + ITEMS].melt(
        id_vars=["cik", "fiscal_year", "accession"],
        var_name="line_item",
        value_name="annual_value",
    )
    pairs = ttm_long.merge(annual_long, on=["cik", "fiscal_year", "line_item"])
    return pairs.dropna(subset=["ttm_value", "annual_value"])


def q4_components(sources_df):
    """Return, per Q4 TTM value, how its fourth quarter was found: the
    method, the + 12-month value (if used) and the balance's filing."""
    last = sources_df.groupby(["cik", "period_end", "line_item"])[
        "component_period_end"
    ].transform("max")
    fourth = sources_df[sources_df["component_period_end"] == last]
    method = (
        fourth.groupby(["cik", "period_end", "line_item"])["method"]
        .first()
        .rename("q4_method")
    )
    annual_plus = (
        fourth[(fourth["method"] == ttm.METHOD_ANNUAL) & (fourth["value"] > 0)]
        .groupby(["cik", "period_end", "line_item"])["value"]
        .first()
        .rename("twelve_month_value")
    )
    balance_accession = (
        fourth[fourth["method"] == ttm.METHOD_BALANCE]
        .groupby(["cik", "period_end", "line_item"])["accession"]
        .first()
        .rename("balance_accession")
    )
    return pd.concat(
        [method, annual_plus, balance_accession], axis=1
    ).reset_index()


def cause(row):
    """Return the cause of one Q4 disagreement (see the module text)."""
    if pd.isna(row["q4_method"]):
        # No source rows: the TTM value was derived from other columns
        # (derived_items), so the difference comes from those columns.
        return "derived_in_ttm"
    if row["line_item"] not in FLOW_ITEMS:
        if row["balance_accession"] == row["accession"]:
            return "same_filing_other_tag"
        return "first_reported_in_another_filing"
    if row["q4_method"] == ttm.METHOD_REPORTED:
        return "q4_reported_3_months"
    if row["q4_method"] == ttm.METHOD_ANNUAL:
        if (
            pd.notna(row["twelve_month_value"])
            and agrees(
                pd.Series([row["twelve_month_value"]]),
                pd.Series([row["annual_value"]]),
            ).iloc[0]
        ):
            return "quarters_do_not_add_to_9_months"
        return "annual_value_differs"
    return "other"


def line_item_crosscheck(ttm_df, annual_df, sources_df):
    """Return the per-line-item agreement table with disagreement causes."""
    pairs = q4_pairs(ttm_df, annual_df)
    pairs["agrees"] = agrees(pairs["ttm_value"], pairs["annual_value"])
    differ = pairs[~pairs["agrees"]].merge(
        q4_components(
            sources_df[
                sources_df["period_end"].isin(pairs["period_end"].unique())
            ]
        ),
        on=["cik", "period_end", "line_item"],
        how="left",
    )
    differ["cause"] = differ.apply(cause, axis=1)
    differ["gap_pct"] = (
        differ["ttm_value"] - differ["annual_value"]
    ).abs() / differ["annual_value"].abs()
    summary = pairs.groupby("line_item", sort=False).agg(
        pairs=("agrees", "size"), agree=("agrees", "sum")
    )
    summary["agree_pct"] = (summary["agree"] / summary["pairs"] * 100).round(2)
    causes = (
        differ.pivot_table(
            index="line_item",
            columns="cause",
            values="cik",
            aggfunc="size",
            fill_value=0,
        )
        .reindex(summary.index)
        .fillna(0)
        .astype(int)
    )
    summary["median_gap_pct_when_differ"] = (
        differ.groupby("line_item")["gap_pct"].median().mul(100).round(1)
    )
    return summary.join(causes).reset_index()


def score_crosscheck(scores_q_df, scores_a_df):
    """Return Q4-vs-annual agreement for each score and verdict."""
    q4 = scores_q_df[scores_q_df["fiscal_quarter"] == 4].merge(
        scores_a_df, on=["cik", "fiscal_year"], suffixes=("_q", "_a")
    )
    rows = []
    for score in ["m_score", "z_score", "accruals_ratio", "cash_conversion"]:
        both = q4[f"{score}_q"].notna() & q4[f"{score}_a"].notna()
        gap = (q4[f"{score}_q"] - q4[f"{score}_a"]).abs()[both]
        rows.append(
            (
                score,
                int(both.sum()),
                f"within {SCORE_TOLERANCE}",
                round((gap <= SCORE_TOLERANCE).mean() * 100, 2),
            )
        )
    for verdict in ["m_flag", "z_zone", "f_score", "f_band", "flags_raised"]:
        both = q4[f"{verdict}_q"].notna() & q4[f"{verdict}_a"].notna()
        same = (q4[f"{verdict}_q"] == q4[f"{verdict}_a"])[both]
        rows.append(
            (verdict, int(both.sum()), "equal", round(same.mean() * 100, 2))
        )
    only_one = {
        score: int(
            (q4[f"{score}_q"].notna() != q4[f"{score}_a"].notna()).sum()
        )
        for score in ["m_score", "z_score", "f_score"]
    }
    table = pd.DataFrame(
        rows, columns=["measure", "pairs", "test", "agree_pct"]
    )
    table["present_in_only_one"] = table["measure"].map(only_one)
    return table, len(q4)


def coverage(scores_q_df, scores_a_df):
    """Return the share of rows with each score, by quarter and annual."""
    columns = ["m_score", "z_score", "f_score", "accruals_ratio"]
    by_quarter = scores_q_df.groupby("fiscal_quarter")[columns].apply(
        lambda frame: frame.notna().mean() * 100
    )
    by_quarter.index = [f"Q{q}" for q in by_quarter.index]
    by_quarter["rows"] = scores_q_df.groupby("fiscal_quarter").size().values
    annual = scores_a_df[columns].notna().mean() * 100
    annual["rows"] = len(scores_a_df)
    table = pd.concat([by_quarter, annual.to_frame("annual").T])
    note = scores_q_df["missing_inputs"].fillna("").str.contains(qs.SHARE_NOTE)
    table["option_c_rows"] = [
        int((note & (scores_q_df["fiscal_quarter"] == q)).sum())
        for q in range(1, 5)
    ] + [0]
    return table.round(1).rename_axis("basis").reset_index()


def main():
    """Write the three cross-check CSVs and print them."""
    ttm_df = pd.read_parquet(ttm.TTM_PATH)
    annual_df = pd.read_parquet(config.FINANCIALS_PATH)
    sources_df = pd.read_parquet(
        ttm.TTM_SOURCES_PATH,
        filters=[("line_item", "in", ITEMS)],
    )
    items = line_item_crosscheck(ttm_df, annual_df, sources_df)
    del sources_df
    scores_q_df = pd.read_parquet(qs.SCORES_QUARTERLY_PATH)
    scores_a_df = pd.read_parquet(config.SCORES_PATH)
    scores, pair_count = score_crosscheck(scores_q_df, scores_a_df)
    cover = coverage(scores_q_df, scores_a_df)
    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    items.to_csv(LINE_ITEM_CSV, index=False)
    scores.to_csv(SCORES_CSV, index=False)
    cover.to_csv(COVERAGE_CSV, index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(items.to_string(index=False))
        print(f"\nQ4 vs annual scores ({pair_count:,} company-years):")
        print(scores.to_string(index=False))
        print("\nCoverage (% of scored rows):")
        print(cover.to_string(index=False))


if __name__ == "__main__":
    main()
