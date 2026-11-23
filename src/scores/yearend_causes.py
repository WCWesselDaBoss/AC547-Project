"""Quarterly verification: why does a Q4 TTM differ from the annual table?

For every value in financials_annual (FY2012 onward, the 18 line items
the scores use) of a company with quarterly data, the same company-year's
Q4 TTM row should hold the same value, because a fourth-quarter TTM covers
the same fiscal year as the 10-K. A mismatch is either:

- "value differs": the TTM differs by more than 0.5% or $10,000 (the
  cross-check tolerance, crosscheck_quarterly.agrees), or
- "TTM blank": the annual table has a value and the TTM does not.

Each mismatch gets ONE cause, the first that applies, in this order:

1. misaligned_or_missing_quarter: the TTM is blank (a quarter is missing,
   the quarters are not consecutive, or there is no Q4 row; the reasons
   are counted in data/logs/financials_ttm_log.csv), or the Q4 quarter
   end is more than 7 days from the 10-K year end.
2. week_52_53_alignment: the TTM's four quarters span a different number
   of days than the annual fiscal year (more than 3 days apart).
3. derived_value: the value was calculated from other columns
   (derived_items) in the TTM row or the annual row.
4. tag_mixing_and_restatement, tag_mixing, restatement: tag mixing means
   the TTM's source facts use more than one XBRL tag, or a different tag
   from the annual value's; restatement means a source fact's period was
   later reported with a different value (in the 10-K or a later 10-Q).
5. unexplained: none of the above. Unexplained mismatches are then split:
   (a) kept_revision: a quarter of that fiscal year has a reported
       3-month value that differs from its year-to-date difference and was
       kept as reported (fix A, data/logs/ttm_overrides.csv), the pattern
       of a revision of an earlier quarter;
   (b) truly_unexplained: no cause found.

Read-only: it reads the processed tables and writes one CSV,
verification/quarterly_yearend_causes.csv (counts by line item and
cause). It changes no table.

Run: python -m src.scores.yearend_causes   (after the quarterly build)
"""

import numpy as np
import pandas as pd

import config
from src.pipeline import financials, quarterly, ttm
from src.scores import crosscheck_quarterly

OUTPUT_CSV = (
    config.PROJECT_ROOT / "verification" / "quarterly_yearend_causes.csv"
)
ITEMS = financials.VALUE_COLUMNS[:18]
FLOWS = [item for item in ITEMS if item in ttm.FLOW_ITEMS]
MISALIGNED_DAYS = 7
SPAN_TOLERANCE_DAYS = 3

CAUSE_MISSING = "misaligned_or_missing_quarter"
CAUSE_WEEKS = "week_52_53_alignment"
CAUSE_DERIVED = "derived_value"
CAUSE_BOTH = "tag_mixing_and_restatement"
CAUSE_TAGS = "tag_mixing"
CAUSE_RESTATED = "restatement"
CAUSE_UNEXPLAINED = "unexplained"
CAUSES = [
    CAUSE_RESTATED,
    CAUSE_TAGS,
    CAUSE_BOTH,
    CAUSE_MISSING,
    CAUSE_WEEKS,
    CAUSE_DERIVED,
    CAUSE_UNEXPLAINED,
]
SPLIT_KEPT = "kept_revision"
SPLIT_TRULY = "truly_unexplained"


# ---------------------------------------------------------------------------
# Pairs: each annual value next to the Q4 TTM value
# ---------------------------------------------------------------------------
def yearend_pairs(annual_df, ttm_df):
    """Return one row per annual value (FY2012 on, companies with
    quarterly data) with the Q4 TTM value and a status: agree, value
    (differs) or blank (no TTM value)."""
    prior = annual_df[["cik", "fiscal_year", "period_end"]].rename(
        columns={"period_end": "prior_end"}
    )
    prior = prior.assign(fiscal_year=prior["fiscal_year"] + 1)
    annual = annual_df.merge(prior, on=["cik", "fiscal_year"], how="left")
    annual["year_days"] = (annual["period_end"] - annual["prior_end"]).dt.days
    keys = ["cik", "fiscal_year", "period_end", "derived_items"]
    a_long = annual[keys + ["year_days"] + ITEMS].melt(
        id_vars=keys + ["year_days"],
        var_name="line_item",
        value_name="annual_value",
    )
    a_long = a_long[
        a_long["annual_value"].notna()
        & a_long["cik"].isin(ttm_df["cik"].unique())
        & (a_long["fiscal_year"] >= config.FIRST_FISCAL_YEAR)
    ]
    q4 = ttm_df[ttm_df["fiscal_quarter"] == 4]
    t_long = q4[keys + ITEMS].melt(
        id_vars=keys, var_name="line_item", value_name="ttm_value"
    )
    pairs = a_long.merge(
        t_long,
        on=["cik", "fiscal_year", "line_item"],
        how="left",
        suffixes=("_a", "_t"),
    )
    pairs["line_item"] = pairs["line_item"].astype("string")
    agree = crosscheck_quarterly.agrees(
        pairs["ttm_value"], pairs["annual_value"]
    )
    pairs["status"] = np.where(
        pairs["ttm_value"].isna(),
        "blank",
        np.where(agree, "agree", "value"),
    )
    return pairs.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Evidence for value mismatches: span, tags, restatements
# ---------------------------------------------------------------------------
def restated_periods(facts_df):
    """Return the (cik, line_item, period_start, period_end) keys whose
    original value was later reported differently by another filing."""
    key = ["cik", "line_item", "period_start", "period_end"]
    original = facts_df[facts_df["is_original"]][key + ["value"]].rename(
        columns={"value": "original_value"}
    )
    later = facts_df[~facts_df["is_original"]][key + ["value"]].merge(
        original, on=key
    )
    differs = ~crosscheck_quarterly.agrees(
        later["value"], later["original_value"]
    )
    return later.loc[differs, key].drop_duplicates()


def source_evidence(sources_df, facts_df):
    """Return, per (cik, period_end, line_item) TTM value: the first
    quarter's start, the set of XBRL tags of its source facts and whether
    any source period was later restated. Source rows are matched to
    their original fact by company, item, filing and absolute value
    (ttm_sources keeps the quarter, not the fact's own period)."""
    restated = restated_periods(facts_df).assign(restated=True)
    originals = facts_df[facts_df["is_original"]].merge(
        restated,
        on=["cik", "line_item", "period_start", "period_end"],
        how="left",
    )
    originals["restated"] = originals["restated"].fillna(False).astype(bool)
    originals["abs_value"] = originals["value"].abs()
    match_key = ["cik", "line_item", "accession", "abs_value"]
    lookup = originals.drop_duplicates(match_key)[
        match_key + ["xbrl_tag", "restated"]
    ]
    sources = sources_df.assign(abs_value=sources_df["value"].abs())
    matched = sources.merge(lookup, on=match_key, how="left")
    return (
        matched.groupby(["cik", "period_end", "line_item"])
        .agg(
            first_start=("component_period_start", "min"),
            tags=("xbrl_tag", lambda s: frozenset(s.dropna())),
            restated=("restated", lambda s: bool(s.fillna(False).any())),
        )
        .reset_index()
    )


def annual_tags(value_pairs, facts_long_df):
    """Return the XBRL tag behind each annual value: the facts_long
    original nearest the annual year end (within 7 days)."""
    left = (
        value_pairs[["cik", "line_item", "period_end_a"]]
        .drop_duplicates()
        .sort_values("period_end_a")
    )
    right = (
        facts_long_df[facts_long_df["is_original"]][
            ["cik", "line_item", "period_end", "xbrl_tag"]
        ]
        .rename(columns={"period_end": "fact_end", "xbrl_tag": "annual_tag"})
        .astype({"line_item": "string"})
        .sort_values("fact_end")
    )
    left = left.astype({"line_item": "string"})
    return pd.merge_asof(
        left,
        right,
        left_on="period_end_a",
        right_on="fact_end",
        by=["cik", "line_item"],
        direction="nearest",
        tolerance=pd.Timedelta(days=MISALIGNED_DAYS),
    ).drop(columns="fact_end")


# ---------------------------------------------------------------------------
# Causes
# ---------------------------------------------------------------------------
def is_derived(row):
    """Return True if the value was derived in the TTM or annual row."""
    names = []
    for column in ("derived_items_a", "derived_items_t"):
        if pd.notna(row[column]):
            names += str(row[column]).split("; ")
    return row["line_item"] in names


def value_cause(row):
    """Return the cause of one value mismatch (module text, 1 to 5)."""
    if row["gap_days"] > MISALIGNED_DAYS:
        return CAUSE_MISSING
    if (
        row["line_item"] in FLOWS
        and pd.notna(row["first_start"])
        and pd.notna(row["year_days"])
    ):
        ttm_days = (row["period_end_t"] - row["first_start"]).days + 1
        if abs(ttm_days - row["year_days"]) > SPAN_TOLERANCE_DAYS:
            return CAUSE_WEEKS
    if is_derived(row):
        return CAUSE_DERIVED
    tags = row["tags"] if isinstance(row["tags"], frozenset) else frozenset()
    mixing = len(tags) > 1 or (
        pd.notna(row["annual_tag"])
        and len(tags) == 1
        and row["annual_tag"] not in tags
    )
    restated = bool(row["restated"]) if pd.notna(row["restated"]) else False
    if mixing and restated:
        return CAUSE_BOTH
    if mixing:
        return CAUSE_TAGS
    if restated:
        return CAUSE_RESTATED
    return CAUSE_UNEXPLAINED


def split_unexplained(mismatches_df, overrides_df):
    """Add a 'split' column to unexplained mismatches: kept_revision when
    a quarter of that company, item and fiscal year was kept as reported
    under fix A, else truly_unexplained (blank for other causes)."""
    kept = overrides_df.loc[
        overrides_df["action"] == ttm.ACTION_KEPT,
        ["cik", "line_item", "fiscal_year"],
    ].drop_duplicates()
    kept = kept.astype({"line_item": "string"}).assign(kept=True)
    out = mismatches_df.merge(
        kept, on=["cik", "line_item", "fiscal_year"], how="left"
    )
    unexplained = out["cause"] == CAUSE_UNEXPLAINED
    out["split"] = pd.Series(pd.NA, index=out.index, dtype="string")
    out.loc[unexplained & out["kept"].eq(True), "split"] = SPLIT_KEPT
    out.loc[unexplained & ~out["kept"].eq(True), "split"] = SPLIT_TRULY
    return out.drop(columns="kept")


def classify(pairs, sources_df, facts_df, facts_long_df, overrides_df):
    """Return every mismatch with its cause (and split, if unexplained)."""
    mismatches = pairs[pairs["status"] != "agree"].copy()
    mismatches["gap_days"] = (
        mismatches["period_end_t"] - mismatches["period_end_a"]
    ).dt.days.abs()
    values = mismatches[mismatches["status"] == "value"]
    values = values.merge(
        source_evidence(sources_df, facts_df).rename(
            columns={"period_end": "period_end_t"}
        ),
        on=["cik", "period_end_t", "line_item"],
        how="left",
    ).merge(
        annual_tags(values, facts_long_df),
        on=["cik", "line_item", "period_end_a"],
        how="left",
    )
    values["cause"] = values.apply(value_cause, axis=1)
    blanks = mismatches[mismatches["status"] == "blank"].assign(
        cause=CAUSE_MISSING
    )
    together = pd.concat([values, blanks], ignore_index=True)
    return split_unexplained(together, overrides_df)


def summary(classified, pairs):
    """Return counts by line item: annual values, mismatches by kind,
    each cause and the split of unexplained."""
    counts = classified.pivot_table(
        index="line_item",
        columns="cause",
        values="cik",
        aggfunc="size",
        fill_value=0,
    ).reindex(index=ITEMS, columns=CAUSES, fill_value=0)
    counts = counts.fillna(0).astype(int)
    split = classified.pivot_table(
        index="line_item",
        columns="split",
        values="cik",
        aggfunc="size",
        fill_value=0,
    ).reindex(index=ITEMS, columns=[SPLIT_KEPT, SPLIT_TRULY], fill_value=0)
    status = classified.pivot_table(
        index="line_item",
        columns="status",
        values="cik",
        aggfunc="size",
        fill_value=0,
    ).reindex(index=ITEMS, columns=["value", "blank"], fill_value=0)
    table = pd.DataFrame(
        {
            "annual_values": pairs.groupby("line_item").size(),
            "mismatches": counts.sum(axis=1),
            "value_differs": status["value"],
            "ttm_blank": status["blank"],
        }
    ).reindex(ITEMS)
    table = table.join(counts).join(split.fillna(0).astype(int))
    table.loc["ALL"] = table.sum()
    return table.fillna(0).astype(int).rename_axis("line_item").reset_index()


# ---------------------------------------------------------------------------
# Reading the tables (only what is needed, to fit a laptop's memory)
# ---------------------------------------------------------------------------
def main():
    """Classify every year-end mismatch and write the summary CSV."""
    annual = pd.read_parquet(config.FINANCIALS_PATH)
    ttm_df = pd.read_parquet(ttm.TTM_PATH)
    pairs = yearend_pairs(annual, ttm_df)
    need = pairs.loc[pairs["status"] == "value", ["cik", "period_end_t"]]
    ciks = sorted(need["cik"].unique().tolist())
    sources = pd.read_parquet(
        ttm.TTM_SOURCES_PATH,
        filters=[("cik", "in", ciks), ("line_item", "in", ITEMS)],
    )
    q4_ends = need.rename(columns={"period_end_t": "period_end"})
    sources = sources.merge(
        q4_ends.drop_duplicates(), on=["cik", "period_end"]
    )
    facts_df = pd.read_parquet(
        quarterly.FACTS_QUARTERLY_PATH,
        columns=[
            "cik",
            "line_item",
            "accession",
            "value",
            "period_start",
            "period_end",
            "xbrl_tag",
            "is_original",
        ],
        filters=[("cik", "in", ciks), ("line_item", "in", ITEMS)],
    )
    facts_long_df = pd.read_parquet(
        config.FACTS_LONG_PATH,
        columns=["cik", "line_item", "period_end", "xbrl_tag", "is_original"],
        filters=[("cik", "in", ciks), ("line_item", "in", ITEMS)],
    )
    overrides = pd.read_csv(ttm.TTM_OVERRIDES_LOG)
    classified = classify(pairs, sources, facts_df, facts_long_df, overrides)
    table = summary(classified, pairs)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUTPUT_CSV, index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        print(table.to_string(index=False))
    print(f"Wrote {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
