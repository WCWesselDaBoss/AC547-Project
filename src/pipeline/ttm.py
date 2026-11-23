"""Quarterly upgrade, step 3: single quarters and trailing twelve months.

Builds two NEW tables (CLAUDE.md section 4) from facts_quarterly:

- financials_ttm: one row per company and fiscal quarter end, with the
  same line-item and component columns as financials_annual. A flow
  (revenue, net income, cash flow...) is the trailing-twelve-month
  (TTM) sum of the four most recent consecutive single quarters; a
  balance sheet item is the quarter-end value.
- ttm_sources: the filings behind every value, for click-to-trace.

Only original values (is_original, the earliest filing) are used, as in
the annual scores: they are what investors saw at the time.

How a single quarter is found, in order of preference:
1. "reported 3 months": the filing reported the 3-month value itself.
2. "year-to-date difference": 10-Qs often report only year-to-date
   (YTD) figures, especially cash flow. Q2 = 6-month YTD minus Q1;
   Q3 = 9-month YTD minus 6-month YTD.
3. "annual minus 9 months": no filing reports the fourth quarter alone,
   so Q4 = the 10-K's 12-month value minus the 9-month YTD.
If none works, that quarter has no value, every TTM that needs it is
NaN, and the reason is counted in the log. Nothing is estimated.

This module changes no annual table, function or result; it only reads
facts_quarterly and calls existing functions (derived_items.
apply_derivations, financials.passes_size_floor) without changing them.

Run: python -m src.pipeline.ttm
"""

from collections import Counter

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import config
from src.pipeline import derived_items, facts, financials, quarterly
from src.pipeline import tag_map

TTM_PATH = config.PROCESSED_DIR / "financials_ttm.parquet"
TTM_SOURCES_PATH = config.PROCESSED_DIR / "ttm_sources.parquet"
TTM_LOG = config.LOG_DIR / "financials_ttm_log.csv"

FLOW_ITEMS = [
    item
    for item, info in tag_map.ALL_ITEMS.items()
    if info["period"] == tag_map.DURATION
]
BALANCE_ITEMS = [
    item
    for item, info in tag_map.ALL_ITEMS.items()
    if info["period"] == tag_map.INSTANT
]

METHOD_REPORTED = "reported 3 months"
METHOD_YTD = "year-to-date difference"
METHOD_ANNUAL = "annual minus 9 months"
METHOD_BALANCE = "quarter-end balance"

QUARTERS_IN_TTM = 4
# The four quarters must add up to a year: the same 350-380 day rule
# (counting both ends) as annual flows, so 52 and 53-week years pass.
TTM_DAYS = (350, 380)
# Consecutive quarters: the next quarter starts the day after the
# previous one ends. A few days' slack allows for filers whose period
# dates are a day or two apart; a missing quarter is a gap of ~90 days.
MAX_GAP_DAYS = 8
# Two YTD values can only be differenced if they start at the same
# fiscal year start (within this many days).
START_TOLERANCE_DAYS = 10
# Companies per batch. Only memory and speed depend on it, not results:
# each company is computed on its own.
BATCH_COMPANIES = 1000

QUARTER_KEY = ["cik", "fiscal_year", "fiscal_quarter"]
ITEM_QUARTER_KEY = ["cik", "line_item", "fiscal_year", "fiscal_quarter"]

TTM_ID_COLUMNS = [
    "cik",
    "fiscal_year",
    "fiscal_quarter",
    "period_end",
    "available_date",
    "passes_size_floor",
    "derived_items",
]
TTM_COLUMNS = TTM_ID_COLUMNS + financials.VALUE_COLUMNS
SOURCES_COLUMNS = [
    "cik",
    "period_end",
    "line_item",
    "component_period_start",
    "component_period_end",
    "value",
    "method",
    "accession",
    "filing_url",
]
REASON_MISSING = "a_quarter_has_no_3_month_value_or_ytd_pair"
REASON_GAP = "quarters_not_consecutive"
REASON_SPAN = "four_quarters_not_350_to_380_days"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def quarters_covered(duration_days):
    """Return how many quarters each flow covers (1 to 4), from its
    length in days (quarterly.DURATION_BINS); 0 for balance sheet
    instants (no length)."""
    covered = pd.Series(0, index=duration_days.index, dtype="int64")
    for months, (low, high) in quarterly.DURATION_BINS.items():
        in_bin = duration_days.between(low, high).fillna(False)
        covered[in_bin.astype(bool)] = months // 3
    return covered


def quarter_index(fiscal_year, fiscal_quarter):
    """Return a running quarter number (fiscal_year * 4 + quarter - 1), so
    the quarter before Q1 of 2024 (2024*4) is Q4 of 2023 (2024*4 - 1)."""
    return fiscal_year * 4 + fiscal_quarter - 1


def earliest_per_key(facts_df, key):
    """Return one fact per key: the earliest filed (then the lowest
    accession), the same tie-break as is_original."""
    return facts_df.sort_values(
        ["filed_date", "accession"], kind="stable"
    ).drop_duplicates(subset=key, keep="first")


# ---------------------------------------------------------------------------
# Quarter ends
# ---------------------------------------------------------------------------
def choose_quarter_ends(facts_df, report_ends, log):
    """Return one period_end per company and fiscal quarter.

    Rarely (about 0.2% of quarters, usually around a change of fiscal
    year end), facts with two different period ends are labeled the same
    fiscal quarter. The one within 7 days of the company's own 10-Q or
    10-K report date is kept; then the one with more facts; then the
    later date. Facts on the other date are left out and counted, never
    mixed into the chosen quarter.
    """
    dates = (
        facts_df.groupby(QUARTER_KEY + ["period_end"])
        .size()
        .rename("facts")
        .reset_index()
    )
    dates["near_report"] = [
        quarterly.near_a_report_date(end, report_ends.get(cik))
        for cik, end in zip(dates["cik"], dates["period_end"])
    ]
    dates = dates.sort_values(
        QUARTER_KEY + ["near_report", "facts", "period_end"],
        ascending=[True, True, True, False, False, False],
    )
    chosen = dates.drop_duplicates(subset=QUARTER_KEY, keep="first")
    others = dates.drop(chosen.index)
    log["quarters:with_a_second_period_end"] += len(
        others.drop_duplicates(subset=QUARTER_KEY)
    )
    log["dropped_facts:on_the_second_period_end"] += int(others["facts"].sum())
    chosen = chosen[QUARTER_KEY + ["period_end"]].reset_index(drop=True)
    chosen["quarter_index"] = quarter_index(
        chosen["fiscal_year"], chosen["fiscal_quarter"]
    )
    return chosen


# ---------------------------------------------------------------------------
# Single quarters (flows)
# ---------------------------------------------------------------------------
def source_rows(facts_df, method, sign=1.0, suffix=""):
    """Return ttm_sources-style rows (before the TTM period_end is added)
    for facts used directly: the fact's own period, its value times sign
    (so a subtracted value is negative, and a quarter's rows add up to
    the quarter), the method and its filing. suffix picks the fact's
    columns in a merged table (for example "_earlier"); the quarter key
    columns are always the quarter being computed."""
    method = method.to_numpy() if isinstance(method, pd.Series) else method
    return pd.DataFrame(
        {
            "cik": facts_df["cik"].to_numpy(),
            "line_item": facts_df["line_item"].to_numpy(),
            "fiscal_year": facts_df["fiscal_year"].to_numpy(),
            "fiscal_quarter": facts_df["fiscal_quarter"].to_numpy(),
            "component_period_start": facts_df[
                f"period_start{suffix}"
            ].to_numpy(),
            "component_period_end": facts_df[f"period_end{suffix}"].to_numpy(),
            "value": sign * facts_df[f"value{suffix}"].to_numpy(),
            "method": method,
            "accession": facts_df[f"accession{suffix}"].to_numpy(),
            "filed_date": facts_df[f"filed_date{suffix}"].to_numpy(),
        }
    )


def single_quarters(flow_facts_df, log):
    """Return (quarters, sources) for flows.

    quarters: one row per company, line item and fiscal quarter, with
    the quarter's value, start, end and method. sources: the facts used
    (one row, or two for a difference), with signed values.

    flow_facts_df holds original flow facts at the chosen quarter ends,
    with a "covered" column (quarters covered, 1 to 4).
    """
    flows = flow_facts_df
    # 3-month values, and year-to-date values (a flow that covers as
    # many quarters as its quarter number: 6 months at Q2, 9 at Q3, 12
    # at Q4; a Q1 3-month value is also Q1's year to date).
    three = earliest_per_key(flows[flows["covered"] == 1], ITEM_QUARTER_KEY)
    ytd = earliest_per_key(
        flows[flows["covered"] == flows["fiscal_quarter"]], ITEM_QUARTER_KEY
    )

    reported = three.assign(
        start=three["period_start"],
        end=three["period_end"],
        method=METHOD_REPORTED,
    )

    # Pair each YTD value (Q2 to Q4) with the YTD value one quarter
    # earlier in the same fiscal year.
    later = ytd[ytd["fiscal_quarter"] >= 2]
    earlier = ytd.assign(fiscal_quarter=ytd["fiscal_quarter"] + 1)
    pairs = later.merge(
        earlier, on=ITEM_QUARTER_KEY, suffixes=("", "_earlier")
    )
    pairs = pairs.merge(
        reported[ITEM_QUARTER_KEY],
        on=ITEM_QUARTER_KEY,
        how="left",
        indicator=True,
    )
    pairs = pairs[pairs["_merge"] == "left_only"].drop(columns="_merge")
    same_start = (
        pairs["period_start"] - pairs["period_start_earlier"]
    ).abs() <= pd.Timedelta(days=START_TOLERANCE_DAYS)
    log["single_quarters:ytd_pair_with_different_start_dates"] += int(
        (~same_start).sum()
    )
    pairs = pairs[same_start]
    method = pairs["fiscal_quarter"].map(
        lambda q: METHOD_ANNUAL if q == 4 else METHOD_YTD
    )
    differenced = pairs.assign(
        value=pairs["value"] - pairs["value_earlier"],
        start=pairs["period_end_earlier"] + pd.Timedelta(days=1),
        end=pairs["period_end"],
        method=method,
    )

    columns = ITEM_QUARTER_KEY + ["value", "start", "end", "method"]
    quarters = pd.concat(
        [reported[columns], differenced[columns]], ignore_index=True
    )
    for method_name, count in quarters["method"].value_counts().items():
        log[f"single_quarters:{method_name}"] += int(count)

    # Sources: the later YTD value counts +, the earlier one -, so a
    # quarter's source rows always add up to the quarter's value. Each
    # row is labeled with the single quarter it helps compute (the
    # "component"), not the fact's own longer YTD period, so a trace
    # shows four quarters, each with the filing or filings behind it.
    sources = pd.concat(
        [
            source_rows(reported, METHOD_REPORTED),
            source_rows(pairs, method),
            source_rows(pairs, method, sign=-1.0, suffix="_earlier"),
        ],
        ignore_index=True,
    ).drop(columns=["component_period_start", "component_period_end"])
    sources = sources.merge(
        quarters[ITEM_QUARTER_KEY + ["start", "end"]].rename(
            columns={
                "start": "component_period_start",
                "end": "component_period_end",
            }
        ),
        on=ITEM_QUARTER_KEY,
    )
    return quarters, sources


# ---------------------------------------------------------------------------
# TTM sums (flows) and quarter-end balances
# ---------------------------------------------------------------------------
def ttm_flows(quarter_ends_df, quarters_df, log):
    """Return one row per company, fiscal quarter end and flow item, with
    the TTM value (NaN when it cannot be computed) and, for each of the
    four quarters used, its quarter key.

    A TTM needs the quarter itself and the three before it (by running
    quarter number), all present, each starting the day after the
    previous one ends (within MAX_GAP_DAYS), together covering 350 to
    380 days. Otherwise the TTM is NaN and the reason is counted.
    """
    targets = quarter_ends_df.merge(
        pd.DataFrame({"line_item": FLOW_ITEMS}), how="cross"
    )
    quarters_df = quarters_df.assign(
        quarter_index=quarter_index(
            quarters_df["fiscal_year"], quarters_df["fiscal_quarter"]
        )
    )[["cik", "line_item", "quarter_index", "value", "start", "end"]]
    for back in range(QUARTERS_IN_TTM):
        targets[f"index_{back}"] = targets["quarter_index"] - back
        targets = targets.merge(
            quarters_df.rename(
                columns={
                    "quarter_index": f"index_{back}",
                    "value": f"value_{back}",
                    "start": f"start_{back}",
                    "end": f"end_{back}",
                }
            ),
            on=["cik", "line_item", f"index_{back}"],
            how="left",
        )
    values = targets[[f"value_{b}" for b in range(QUARTERS_IN_TTM)]]
    complete = values.notna().all(axis=1)
    consecutive = pd.Series(True, index=targets.index)
    for back in range(QUARTERS_IN_TTM - 1):
        gap = (targets[f"start_{back}"] - targets[f"end_{back + 1}"]).dt.days
        consecutive &= gap.between(1, MAX_GAP_DAYS).fillna(False)
    last = QUARTERS_IN_TTM - 1
    span = (targets["end_0"] - targets[f"start_{last}"]).dt.days + 1
    one_year = span.between(*TTM_DAYS).fillna(False)

    reason = pd.Series(pd.NA, index=targets.index, dtype="string")
    reason[~complete] = REASON_MISSING
    reason[complete & ~consecutive] = REASON_GAP
    reason[complete & consecutive & ~one_year] = REASON_SPAN
    ok = reason.isna()
    targets["value"] = values.sum(axis=1).where(ok)
    for (item, why), count in (
        targets.assign(reason=reason)[~ok]
        .groupby(["line_item", "reason"])
        .size()
        .items()
    ):
        log[f"ttm_missing:{item}:{why}"] += int(count)
    log["ttm_values:computed"] += int(ok.sum())
    return targets


def ttm_flow_sources(targets_df, sources_df):
    """Return the source rows of every computed TTM value: the source rows
    of its four quarters, labeled with the TTM row's period_end."""
    computed = targets_df[targets_df["value"].notna()]
    sources_df = sources_df.assign(
        quarter_index=quarter_index(
            sources_df["fiscal_year"], sources_df["fiscal_quarter"]
        )
    ).drop(columns=["fiscal_year", "fiscal_quarter"])
    pieces = []
    for back in range(QUARTERS_IN_TTM):
        keys = computed[["cik", "line_item", "period_end", f"index_{back}"]]
        pieces.append(
            keys.rename(columns={f"index_{back}": "quarter_index"}).merge(
                sources_df, on=["cik", "line_item", "quarter_index"]
            )
        )
    return pd.concat(pieces, ignore_index=True).drop(columns="quarter_index")


def quarter_end_balances(balance_facts_df):
    """Return (balances, sources) for balance sheet items: the original
    value at each chosen quarter end (earliest filing if two)."""
    balances = earliest_per_key(balance_facts_df, ITEM_QUARTER_KEY)
    sources = source_rows(balances, METHOD_BALANCE).assign(
        component_period_start=pd.NaT
    )
    sources["period_end"] = balances["period_end"].to_numpy()
    return balances, sources.drop(columns=["fiscal_year", "fiscal_quarter"])


# ---------------------------------------------------------------------------
# One batch of companies
# ---------------------------------------------------------------------------
def build_batch(facts_df, report_ends, log):
    """Return (financials_ttm rows, ttm_sources rows) for the companies in
    facts_df (original facts from facts_quarterly)."""
    quarter_ends_df = choose_quarter_ends(facts_df, report_ends, log)
    on_chosen = facts_df.merge(
        quarter_ends_df[QUARTER_KEY + ["period_end"]],
        on=QUARTER_KEY + ["period_end"],
    )
    on_chosen = on_chosen.assign(
        covered=quarters_covered(on_chosen["duration_days"])
    )
    is_flow = on_chosen["line_item"].isin(FLOW_ITEMS)

    quarters_df, quarter_sources = single_quarters(on_chosen[is_flow], log)
    targets = ttm_flows(quarter_ends_df, quarters_df, log)
    flow_sources = ttm_flow_sources(targets, quarter_sources)
    balances, balance_sources = quarter_end_balances(
        on_chosen[~is_flow & (on_chosen["covered"] == 0)]
    )

    long_values = pd.concat(
        [
            targets.loc[
                targets["value"].notna(), QUARTER_KEY + ["line_item", "value"]
            ],
            balances[QUARTER_KEY + ["line_item", "value"]],
        ],
        ignore_index=True,
    )
    wide = long_values.pivot(
        index=QUARTER_KEY, columns="line_item", values="value"
    ).reindex(columns=financials.VALUE_COLUMNS)
    wide_df = quarter_ends_df.merge(
        wide.reset_index(), on=QUARTER_KEY, how="left"
    )
    no_values = wide_df[financials.VALUE_COLUMNS].isna().all(axis=1)
    log["dropped_rows:quarter_with_no_values"] += int(no_values.sum())
    wide_df = wide_df[~no_values]

    sources = pd.concat([flow_sources, balance_sources], ignore_index=True)
    available = (
        sources.groupby(["cik", "period_end"])["filed_date"]
        .max()
        .rename("available_date")
        .reset_index()
    )
    wide_df = wide_df.merge(available, on=["cik", "period_end"], how="left")
    if wide_df.empty:
        # apply_derivations (annual code, unchanged) needs at least one
        # row; an empty batch simply has no derived items.
        wide_df = wide_df.assign(derived_items=pd.Series(dtype="string"))
    else:
        wide_df = derived_items.apply_derivations(wide_df)
    wide_df["passes_size_floor"] = financials.passes_size_floor(
        wide_df["revenue"], wide_df["total_assets"]
    )
    return wide_df[TTM_COLUMNS], sources


# ---------------------------------------------------------------------------
# Output types and the full build
# ---------------------------------------------------------------------------
def ttm_to_contract_types(wide_df):
    """Return financials_ttm with the section 4 column order and types."""
    return (
        wide_df[TTM_COLUMNS]
        .astype(
            {
                "cik": "int64",
                "fiscal_year": "int64",
                "fiscal_quarter": "int64",
                "period_end": "datetime64[ns]",
                "available_date": "datetime64[ns]",
                "passes_size_floor": "bool",
                "derived_items": "string",
                **{c: "float64" for c in financials.VALUE_COLUMNS},
            }
        )
        .sort_values(["cik", "period_end"])
        .reset_index(drop=True)
    )


def sources_to_contract_types(sources_df):
    """Return ttm_sources with the section 4 columns and types, adding
    each filing's EDGAR URL (facts.edgar_filing_url, once per filing)."""
    urls = {
        (cik, accession): facts.edgar_filing_url(cik, accession)
        for cik, accession in sources_df[["cik", "accession"]]
        .drop_duplicates()
        .itertuples(index=False)
    }
    sources_df = sources_df.assign(
        filing_url=[
            urls[key]
            for key in zip(sources_df["cik"], sources_df["accession"])
        ]
    )
    return (
        sources_df[SOURCES_COLUMNS]
        .astype(
            {
                "cik": "int64",
                "period_end": "datetime64[ns]",
                "line_item": "string",
                "component_period_start": "datetime64[ns]",
                "component_period_end": "datetime64[ns]",
                "value": "float64",
                "method": "string",
                "accession": "string",
                "filing_url": "string",
            }
        )
        .sort_values(
            [
                "cik",
                "period_end",
                "line_item",
                "component_period_end",
                "component_period_start",
            ]
        )
        .reset_index(drop=True)
    )


FACT_COLUMNS = [
    "cik",
    "line_item",
    "value",
    "period_start",
    "period_end",
    "fiscal_year",
    "fiscal_quarter",
    "duration_days",
    "accession",
    "filed_date",
]


def load_original_facts(path=quarterly.FACTS_QUARTERLY_PATH):
    """Return the original facts from facts_quarterly (read only)."""
    return pd.read_parquet(
        path,
        columns=FACT_COLUMNS,
        filters=[("is_original", "==", True)],
    )


def build_ttm(facts_df, report_ends, sources_path):
    """Return (financials_ttm, log Counter); ttm_sources is written to
    sources_path batch by batch, because it is too large to hold in
    memory at once on a laptop."""
    log = Counter()
    ciks = sorted(facts_df["cik"].unique())
    pieces = []
    writer = None
    try:
        for start in range(0, len(ciks), BATCH_COMPANIES):
            batch_ciks = ciks[start : start + BATCH_COMPANIES]
            batch = facts_df[facts_df["cik"].isin(batch_ciks)]
            wide_df, sources = build_batch(batch, report_ends, log)
            pieces.append(ttm_to_contract_types(wide_df))
            sources = sources_to_contract_types(sources)
            log["ttm_sources:rows"] += len(sources)
            table = pa.Table.from_pandas(sources, preserve_index=False)
            if writer is None:
                # The first batch's schema carries pandas' type notes,
                # so the text columns read back as the spec's "string"
                # type; later batches are converted to the same schema.
                writer = pq.ParquetWriter(sources_path, table.schema)
            writer.write_table(table.cast(writer.schema))
            done = min(start + BATCH_COMPANIES, len(ciks))
            print(f"  processed {done:,} of {len(ciks):,} companies")
    finally:
        if writer is not None:
            writer.close()
    return ttm_to_contract_types(pd.concat(pieces, ignore_index=True)), log


def summary_log(ttm_df, log):
    """Return the log as a DataFrame, plus row and size-floor counts."""
    rows = sorted(log.items())
    rows += [
        ("rows:financials_ttm", len(ttm_df)),
        ("rows:passes_size_floor", int(ttm_df["passes_size_floor"].sum())),
    ]
    return pd.DataFrame(rows, columns=["measure", "count"])


def main():
    """Build financials_ttm and ttm_sources, and write the log."""
    facts_df = load_original_facts()
    report_ends = quarterly.report_period_ends(
        config.SUBMISSIONS_ZIP, sorted(facts_df["cik"].unique())
    )
    ttm_df, log = build_ttm(facts_df, report_ends, TTM_SOURCES_PATH)
    ttm_df.to_parquet(TTM_PATH, index=False)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_df = summary_log(ttm_df, log)
    log_df.to_csv(TTM_LOG, index=False)
    print(log_df.to_string(index=False))
    print(f"Wrote {len(ttm_df):,} rows to {TTM_PATH}")


if __name__ == "__main__":
    main()
