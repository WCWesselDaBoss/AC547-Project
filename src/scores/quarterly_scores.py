"""Quarterly upgrade, step 4: scores_quarterly and score_drivers_quarterly.

Applies the annual score code, UNCHANGED, to the TTM rows in
financials_ttm (CLAUDE.md section 4 and section 5, "Quarterly (TTM)
scores"). Quarterly scores use unaudited 10-Q data and have NOT been
backtested; tests 1 to 12 apply to annual scores only.

How the annual code is reused without changing it. Every annual score
function compares a row with the row for fiscal_year - 1 of the same
company (common.with_prior_years). So the TTM rows are scored ONE FISCAL
QUARTER AT A TIME: all Q1 rows together, then all Q2 rows, and so on.
Inside the Q2 run, a company's "prior year" row is its Q2 TTM one year
earlier, which is exactly "the TTM ending four quarters earlier", and
that row's balance sheet is the balance "four quarters earlier" used as
the beginning-of-year balance. Peer groups and percentiles, computed
per fiscal year inside each run, then compare companies at the same
fiscal year and quarter, as the spec requires.

Three deliberate differences from build_scores.build_scores (whose
building blocks are reused, not changed):
- F-Score signal 7 in Q1 to Q3 compares the share count with the prior
  FISCAL YEAR END count reported in the same 10-Q (decided Nov 22,
  option C; see prior_year_end_share_facts). Such rows carry the note
  "shares_compared_with_prior_year_end"; for them, the annual note
  "shares_t-1_same_filing" means that year-end count was not found.
- No upper year limit: the newest quarters (FY2026, and FY2027 Q1 for
  June year ends) are the point of quarterly mode, so every quarter from
  FY2012 to the latest filed is scored. build_scores stops at FY2025.
- available_date is the latest available_date of the rows a score uses
  (t, t-1 and t-2), so a score never appears before all of its inputs
  were public.

Run: python -m src.scores.quarterly_scores            (data/processed/)
     python -m src.scores.quarterly_scores --sample   (data/sample/)
"""

import argparse
from collections import Counter

import pandas as pd

import config
from src.pipeline import quarterly, ttm
from src.scores import build_scores, common, drivers, peers, verdicts

SCORES_QUARTERLY_PATH = config.PROCESSED_DIR / "scores_quarterly.parquet"
DRIVERS_QUARTERLY_PATH = (
    config.PROCESSED_DIR / "score_drivers_quarterly.parquet"
)
SCORES_QUARTERLY_LOG = config.LOG_DIR / "scores_quarterly_log.csv"

BASIS = "TTM"
SHARE_NOTE = "shares_compared_with_prior_year_end"
QUARTER_COLUMNS = ["fiscal_quarter", "period_end", "available_date", "basis"]
QUARTER_TYPES = {
    "fiscal_quarter": "int64",
    "period_end": "datetime64[ns]",
    "available_date": "datetime64[ns]",
    "basis": "string",
}
# The quarter columns go right after the keys, so each row reads
# "company, fiscal year, quarter, date" before the scores.
SCORES_QUARTERLY_COLUMNS = (
    build_scores.SCORES_COLUMNS[:2]
    + QUARTER_COLUMNS
    + build_scores.SCORES_COLUMNS[2:]
)
DRIVERS_QUARTERLY_COLUMNS = (
    drivers.DRIVER_COLUMNS[:2] + QUARTER_COLUMNS + drivers.DRIVER_COLUMNS[2:]
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def share_accessions(sources_df):
    """Return (cik, period_end, accession): the filing that reported each
    TTM row's quarter-end share count (from ttm_sources).

    F-Score signal 7 compares this count with last year's count reported
    in the SAME filing (piotroski.prior_shares_same_filing), so a split
    is never mistaken for new shares; the row's "accession" is therefore
    the filing behind its shares_outstanding value."""
    shares = sources_df[sources_df["line_item"] == "shares_outstanding"]
    return shares[["cik", "period_end", "accession"]].drop_duplicates(
        subset=["cik", "period_end"]
    )


def with_accession(ttm_df, accessions_df):
    """Return ttm_df with the accession column the score code expects
    (NA where the row has no share count; signal 7 is then NA)."""
    return ttm_df.merge(accessions_df, on=["cik", "period_end"], how="left")


def prior_year_end_share_facts(ttm_q_df, ttm_df, share_facts_df):
    """Return share facts for signal 7 in Q1 to Q3 (decided Nov 22,
    option C): the count each row's OWN filing reports at the prior
    fiscal year end, labeled with the date the annual code looks up.

    Why: the annual rule compares shares with last year's count as
    reported in the same filing, so a stock split (which restates every
    count in that filing) is never mistaken for new shares. A 10-Q
    compares its balance sheet with the last fiscal year end, not with
    the same quarter a year earlier, so for Q1 to Q3 the same-filing
    comparison uses the prior fiscal year end instead. That window is
    shorter (3, 6 or 9 months), so shares issued earlier in the trailing
    year can be missed; at Q4 the rule is exactly the annual one.

    How (without changing piotroski.prior_shares_same_filing): it looks
    up (cik, accession, period_end of the t-1 row). Each fact found at
    the prior fiscal year end in the row's own filing is given that
    lookup date. Every value is passed on, so if a filing reports two
    different counts for the date, the annual code still marks it
    ambiguous (NA) instead of picking one.
    """
    year_end = ttm_df.loc[
        ttm_df["fiscal_quarter"] == 4, ["cik", "fiscal_year", "period_end"]
    ].rename(columns={"period_end": "prior_year_end"})
    year_end["fiscal_year"] += 1
    prior_row = ttm_df[["cik", "fiscal_year", "fiscal_quarter", "period_end"]]
    prior_row = prior_row.rename(columns={"period_end": "lookup_date"})
    prior_row = prior_row.assign(fiscal_year=prior_row["fiscal_year"] + 1)
    wanted = (
        ttm_q_df[["cik", "fiscal_year", "fiscal_quarter", "accession"]]
        .dropna(subset=["accession"])
        .merge(year_end, on=["cik", "fiscal_year"])
        .merge(prior_row, on=["cik", "fiscal_year", "fiscal_quarter"])
    )
    found = wanted.merge(
        share_facts_df.rename(columns={"period_end": "prior_year_end"}),
        on=["cik", "accession", "prior_year_end"],
    )
    return found.rename(columns={"lookup_date": "period_end"})[
        ["cik", "line_item", "accession", "period_end", "value"]
    ]


def scored_quarter_mask(ttm_q_df, companies_df):
    """Return (reason -> mask, scored mask) for one quarter's rows.

    The annual rules (build_scores.scored_row_mask) without the upper
    year limit; each row is counted once, under its first reason."""
    included_ciks = companies_df.loc[
        ~companies_df["is_excluded"] & companies_df["sic"].notna(), "cik"
    ]
    reasons = {
        "prior_year_only_before_first_year": ttm_q_df["fiscal_year"]
        < config.FIRST_FISCAL_YEAR,
        "company_excluded_or_no_sic": ~ttm_q_df["cik"].isin(included_ciks),
        "fails_size_floor": ~ttm_q_df["passes_size_floor"],
    }
    not_yet_counted = pd.Series(True, index=ttm_q_df.index)
    first_reason = {}
    for reason, mask in reasons.items():
        first_reason[reason] = mask & not_yet_counted
        not_yet_counted &= ~mask
    return first_reason, not_yet_counted


def score_available_date(ttm_q_df):
    """Return the latest available_date of each row and its t-1 and t-2
    rows (same quarter, one and two years earlier), aligned to ttm_q_df.
    Rows that do not exist are ignored."""
    lagged = common.with_prior_years(ttm_q_df, ["available_date"], 2)
    dates = lagged[[common.lagged("available_date", k) for k in range(3)]].max(
        axis=1
    )
    return pd.Series(dates.to_numpy(), index=ttm_q_df.index)


# ---------------------------------------------------------------------------
# Scoring one fiscal quarter
# ---------------------------------------------------------------------------
def score_one_quarter(ttm_q_df, share_facts_df, companies_df, log):
    """Return the scores for one fiscal quarter's TTM rows, with the
    annual functions unchanged (the same steps as build_scores.
    build_scores, minus its FY2025 limit)."""
    ttm_q_df = ttm_q_df.reset_index(drop=True)
    ttm_q_df["score_available_date"] = score_available_date(ttm_q_df)
    all_df = build_scores.compute_all_scores(ttm_q_df, share_facts_df)
    all_df = ttm_q_df[
        common.KEY_COLUMNS
        + ["total_assets", "fiscal_quarter", "period_end"]
        + ["score_available_date"]
    ].merge(all_df, on=common.KEY_COLUMNS, how="left")
    drop_reasons, is_scored = scored_quarter_mask(ttm_q_df, companies_df)
    log["ttm_rows"] += len(ttm_q_df)
    for reason, mask in drop_reasons.items():
        log[f"not_scored_{reason}"] += int(mask.sum())
    log["scored_company_quarters"] += int(is_scored.sum())

    scored_df = all_df[is_scored.to_numpy()].copy()
    if scored_df.empty:
        return scored_df
    scored_df = scored_df.merge(
        companies_df[["cik", "sic"]], on="cik", how="left"
    )
    # Q1 to Q3 signal 7 compares with the prior fiscal year end (see
    # prior_year_end_share_facts); every row where that comparison was
    # made says so, so the shorter window is never hidden.
    share_note = pd.Series(pd.NA, index=scored_df.index, dtype="string")
    if (scored_df["fiscal_quarter"] < 4).all():
        share_note[scored_df["f_no_new_shares"].notna()] = SHARE_NOTE
    scored_df["missing_inputs"] = common.combine_notes(
        *[scored_df[column] for column in build_scores.NOTES_COLUMNS],
        share_note,
    )
    scored_df = peers.add_percentile_ranks(peers.assign_peer_groups(scored_df))
    scored_df = verdicts.add_verdicts(scored_df)
    scored_df["available_date"] = scored_df["score_available_date"]
    scored_df["basis"] = BASIS
    return scored_df


def drivers_one_quarter(scores_q_df):
    """Return score drivers for one quarter (drivers.build_score_drivers,
    unchanged), with the quarter columns added from the scores."""
    contract = build_scores.to_contract_types(scores_q_df)
    drivers_df = drivers.build_score_drivers(contract)
    return drivers_df.merge(
        scores_q_df[common.KEY_COLUMNS + QUARTER_COLUMNS],
        on=common.KEY_COLUMNS,
        how="left",
    )


def to_quarterly_types(table_df, columns, types):
    """Return the table in the given column order and types, sorted by
    company and quarter end."""
    return (
        table_df[columns]
        .astype({**types, **QUARTER_TYPES})
        .sort_values(
            ["cik", "period_end"]
            + (["driver_rank"] if "driver_rank" in columns else [])
        )
        .reset_index(drop=True)
    )


def build_quarterly_scores(ttm_df, accessions_df, share_facts_df, companies):
    """Return (scores_quarterly, score_drivers_quarterly, log Counter)."""
    log = Counter()
    rows = with_accession(ttm_df, accessions_df)
    score_pieces, driver_pieces = [], []
    for quarter in range(1, 5):
        ttm_q_df = rows[rows["fiscal_quarter"] == quarter]
        # Q4 rows come from 10-Ks: the annual same-filing rule as is.
        quarter_shares = (
            share_facts_df
            if quarter == 4
            else prior_year_end_share_facts(ttm_q_df, rows, share_facts_df)
        )
        scores_q = score_one_quarter(ttm_q_df, quarter_shares, companies, log)
        if scores_q.empty:
            continue
        score_pieces.append(scores_q)
        driver_pieces.append(drivers_one_quarter(scores_q))
    scores_df = to_quarterly_types(
        pd.concat(score_pieces, ignore_index=True),
        SCORES_QUARTERLY_COLUMNS,
        build_scores.SCORES_TYPES,
    )
    drivers_df = to_quarterly_types(
        pd.concat(driver_pieces, ignore_index=True),
        DRIVERS_QUARTERLY_COLUMNS,
        drivers.DRIVER_TYPES,
    )
    for row in build_scores.coverage_log(scores_df):
        log[row[0]] += row[1]
    log["driver_rows"] += len(drivers_df)
    return scores_df, drivers_df, log


def input_paths(source_dir):
    """Return the four input paths in source_dir: data/processed/ (the
    pipeline's own paths) or data/sample/ (the same file names)."""
    if source_dir == config.PROCESSED_DIR:
        return (
            ttm.TTM_PATH,
            ttm.TTM_SOURCES_PATH,
            quarterly.FACTS_QUARTERLY_PATH,
            config.COMPANIES_PATH,
        )
    return tuple(
        source_dir / f"{name}.parquet"
        for name in (
            "financials_ttm",
            "ttm_sources",
            "facts_quarterly",
            "companies",
        )
    )


def read_inputs(source_dir=config.PROCESSED_DIR):
    """Read financials_ttm, the share-count filings from ttm_sources, the
    share facts of every filing in facts_quarterly, and companies."""
    ttm_path, sources_path, facts_path, companies_path = input_paths(
        source_dir
    )
    ttm_df = pd.read_parquet(ttm_path)
    accessions_df = share_accessions(
        pd.read_parquet(
            sources_path,
            columns=["cik", "period_end", "line_item", "accession"],
            filters=[("line_item", "==", "shares_outstanding")],
        )
    )
    share_facts_df = pd.read_parquet(
        facts_path,
        columns=["cik", "line_item", "accession", "period_end", "value"],
        filters=[("line_item", "==", "shares_outstanding")],
    )
    companies_df = pd.read_parquet(companies_path)
    return ttm_df, accessions_df, share_facts_df, companies_df


def main(argv=None):
    """Build scores_quarterly and score_drivers_quarterly and the log,
    from data/processed/ or, with --sample, from data/sample/ (written
    back to data/sample/, as the annual sample scores are)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sample",
        action="store_true",
        help="score the committed sample tables in data/sample/",
    )
    args = parser.parse_args(argv)
    source_dir = config.SAMPLE_DIR if args.sample else config.PROCESSED_DIR
    scores_path = (
        config.SAMPLE_DIR / "scores_quarterly.parquet"
        if args.sample
        else SCORES_QUARTERLY_PATH
    )
    drivers_path = (
        config.SAMPLE_DIR / "score_drivers_quarterly.parquet"
        if args.sample
        else DRIVERS_QUARTERLY_PATH
    )
    log_path = (
        config.LOG_DIR / "scores_quarterly_sample_log.csv"
        if args.sample
        else SCORES_QUARTERLY_LOG
    )
    scores_df, drivers_df, log = build_quarterly_scores(
        *read_inputs(source_dir)
    )
    scores_df.to_parquet(scores_path, index=False)
    drivers_df.to_parquet(drivers_path, index=False)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_df = pd.DataFrame(sorted(log.items()), columns=["metric", "count"])
    log_df.to_csv(log_path, index=False)
    print(log_df.to_string(index=False))
    print(f"Wrote {len(scores_df):,} rows to {scores_path}")
    print(f"Wrote {len(drivers_df):,} rows to {drivers_path}")


if __name__ == "__main__":
    main()
