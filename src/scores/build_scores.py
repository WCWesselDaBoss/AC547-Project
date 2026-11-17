"""Build the scores table (CLAUDE.md section 4) from Phase 1's tables.

Usage:
    python -m src.scores.build_scores            # data/processed/
    python -m src.scores.build_scores --sample   # data/sample/

Steps:
1. Run each score module on the WHOLE financials_annual table, including
   FY2011 and below-floor rows, because those rows can be the t-1 or t-2
   year for a scored year (section 4).
2. Keep only scored company-years: FY2012-FY2025, passing the size floor,
   from a company that is not excluded. Every other row is counted in the
   log with its reason (section 6, no silent drops).
3. Merge the per-module notes into one missing_inputs column.
4. Assign peer groups and percentile ranks.
5. Put columns in section 4 order and types, write Parquet and the log.
"""

import argparse

import pandas as pd

import config
from src.scores import accruals, altman, beneish, common, peers, piotroski
from src.scores import verdicts

NOTES_COLUMNS = [
    "beneish_notes",
    "altman_notes",
    "piotroski_notes",
    "accruals_notes",
]
SCORES_COLUMNS = (
    ["cik", "fiscal_year", "m_score", "m_flag"]
    + beneish.INDEX_COLUMNS
    + ["z_score", "z_zone"]
    + altman.RATIO_COLUMNS
    + ["f_score", "f_band"]
    + piotroski.SIGNAL_COLUMNS
    + ["flags_raised"]
    + ["accruals_ratio", "cash_conversion"]
    + ["peer_group", "peer_group_level", "peer_group_size"]
    + [peers.percentile_column(score) for score in peers.RANKED_SCORES]
    + ["missing_inputs"]
)
SCORES_TYPES = {
    "cik": "int64",
    "fiscal_year": "int64",
    "m_flag": "boolean",
    "z_zone": "string",
    "f_score": "Int64",
    "f_band": "string",
    "flags_raised": "Int64",
    "peer_group": "string",
    "peer_group_level": "string",
    "peer_group_size": "int64",
    "missing_inputs": "string",
    **{column: "float64" for column in beneish.INDEX_COLUMNS},
    **{column: "float64" for column in altman.RATIO_COLUMNS},
    **{column: "boolean" for column in piotroski.SIGNAL_COLUMNS},
    **{
        column: "float64"
        for column in [
            "m_score",
            "z_score",
            "accruals_ratio",
            "cash_conversion",
        ]
        + [peers.percentile_column(score) for score in peers.RANKED_SCORES]
    },
}
SCORE_NAMES = [
    "m_score",
    "z_score",
    "f_score",
    "accruals_ratio",
    "cash_conversion",
]


def compute_all_scores(financials_df, facts_long_df):
    """Return every score for every financials row, merged on the keys."""
    keys = common.KEY_COLUMNS
    all_df = beneish.compute_beneish(financials_df)
    for module_df in [
        altman.compute_altman(financials_df),
        piotroski.compute_piotroski(financials_df, facts_long_df),
        accruals.compute_accruals(financials_df),
    ]:
        all_df = all_df.merge(module_df, on=keys, how="left")
    return all_df


def scored_row_mask(financials_df, companies_df):
    """Return a dict of reason -> boolean mask, plus the 'scored' mask.

    Reasons are checked in order and each row is counted once, under the
    first reason that applies, so the counts add up to the table size.
    """
    included_ciks = companies_df.loc[
        ~companies_df["is_excluded"] & companies_df["sic"].notna(), "cik"
    ]
    year = financials_df["fiscal_year"]
    reasons = {
        "prior_year_only_before_first_year": year < config.FIRST_FISCAL_YEAR,
        "after_last_year": year > config.LAST_FISCAL_YEAR,
        "company_excluded_or_no_sic": ~financials_df["cik"].isin(
            included_ciks
        ),
        "fails_size_floor": ~financials_df["passes_size_floor"],
    }
    not_yet_counted = pd.Series(True, index=financials_df.index)
    first_reason = {}
    for reason, mask in reasons.items():
        first_reason[reason] = mask & not_yet_counted
        not_yet_counted &= ~mask
    return first_reason, not_yet_counted


def to_contract_types(scores_df):
    """Return the table in section 4 column order and types."""
    return (
        scores_df[SCORES_COLUMNS]
        .astype(SCORES_TYPES)
        .sort_values(common.KEY_COLUMNS)
        .reset_index(drop=True)
    )


def build_scores(financials_df, facts_long_df, companies_df):
    """Return (scores_df, log_rows) built from the Phase 1 tables."""
    all_df = compute_all_scores(financials_df, facts_long_df)
    # compute_all_scores keeps financials' row order and index alignment
    # via the keys; align explicitly to be safe.
    all_df = financials_df[common.KEY_COLUMNS + ["total_assets"]].merge(
        all_df, on=common.KEY_COLUMNS, how="left"
    )
    drop_reasons, is_scored = scored_row_mask(financials_df, companies_df)

    log_rows = [("financials_rows", len(financials_df))]
    log_rows += [
        (f"not_scored_{reason}", int(mask.sum()))
        for reason, mask in drop_reasons.items()
    ]
    log_rows.append(("scored_company_years", int(is_scored.sum())))

    scored_df = all_df[is_scored.to_numpy()].copy()
    scored_df = scored_df.merge(
        companies_df[["cik", "sic"]], on="cik", how="left"
    )
    scored_df["missing_inputs"] = common.combine_notes(
        *[scored_df[column] for column in NOTES_COLUMNS]
    )
    scored_df = peers.add_percentile_ranks(peers.assign_peer_groups(scored_df))
    # Verdicts restate the scores for display (section 4); they are
    # added after the scores so they can never feed back into them.
    scored_df = verdicts.add_verdicts(scored_df)
    scores_df = to_contract_types(scored_df)
    log_rows += coverage_log(scores_df)
    return scores_df, log_rows


def coverage_log(scores_df):
    """Return (metric, count) rows: how many scored years have each score,
    how many fell back to industry peers, and the top blank reasons."""
    rows = []
    for score in SCORE_NAMES:
        rows.append((f"has_{score}", int(scores_df[score].notna().sum())))
        rows.append((f"blank_{score}", int(scores_df[score].isna().sum())))
    rows.append(
        (
            "peer_group_industry_fallback",
            int((scores_df["peer_group_level"] == peers.LEVEL_INDUSTRY).sum()),
        )
    )
    reasons = (
        scores_df["missing_inputs"].dropna().str.split("; ").explode()
    ).value_counts()
    rows += [(f"reason_{reason}", int(n)) for reason, n in reasons.items()]
    return rows


def read_inputs(source_dir):
    """Read the three Phase 1 tables the scores need."""
    return (
        pd.read_parquet(source_dir / "financials_annual.parquet"),
        pd.read_parquet(source_dir / "facts_long.parquet"),
        pd.read_parquet(source_dir / "companies.parquet"),
    )


def main(argv=None):
    """Build scores from data/processed/ (or data/sample/ with --sample)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sample",
        action="store_true",
        help="score the committed sample tables in data/sample/",
    )
    args = parser.parse_args(argv)
    source_dir = config.SAMPLE_DIR if args.sample else config.PROCESSED_DIR
    output_path = (
        config.SAMPLE_DIR / "scores.parquet"
        if args.sample
        else config.SCORES_PATH
    )
    log_path = (
        config.LOG_DIR / "scores_sample_log.csv"
        if args.sample
        else config.SCORES_LOG
    )

    scores_df, log_rows = build_scores(*read_inputs(source_dir))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scores_df.to_parquet(output_path, index=False)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_df = pd.DataFrame(log_rows, columns=["metric", "count"])
    log_df.to_csv(log_path, index=False)
    print(log_df.head(20).to_string(index=False))
    print(f"Wrote {len(scores_df)} rows to {output_path}")
    print(f"Wrote log to {log_path}")


if __name__ == "__main__":
    main()
