"""Annual or quarterly (TTM) scores: the switch, its labels and helpers.

Annual is always the default. Quarterly mode reads the quarterly tables
(scores_quarterly, financials_ttm, ...) and reuses the screener's own
reshaping functions on one fiscal quarter at a time; nothing here
computes a score (CLAUDE.md section 3).

Pure Python and pandas, no Streamlit, so pytest checks every function.
"""

import pandas as pd

from app import labels

# Session-state key of the sidebar switch (kept between pages).
BASIS_KEY = "score_basis"
ANNUAL = "annual"
QUARTERLY = "quarterly"
BASIS_LABELS = {ANNUAL: "Annual (10-K)", QUARTERLY: "Quarterly (TTM)"}

# The quarterly mode's required note (CLAUDE.md section 5, "Quarterly
# (TTM) scores"), shown whenever quarterly scores are on screen.
QUARTERLY_NOTE = (
    "Quarterly scores apply the same formulas and cutoffs as the annual "
    "scores to trailing-twelve-month data from unaudited 10-Q filings. "
    "They have not been backtested: tests 1 to 12 used annual scores only."
)
# Shown wherever a quarterly score is missing, never a blank or an error.
NOT_ENOUGH_DATA = (
    "Not enough quarterly data (needs four complete quarters this year "
    "and last)"
)
# The short form for a table cell; the full sentence is in the caption.
NOT_ENOUGH_DATA_SHORT = "⚪ Not enough quarterly data"

# The quarterly tables the app reads. A data source without them (the
# test fixtures, or a data/processed/ built without --quarterly) shows
# annual only, with a note, instead of an error.
QUARTERLY_TABLES = (
    "scores_quarterly",
    "score_drivers_quarterly",
    "financials_ttm",
    "ttm_sources",
)


def quarterly_tables_present(data_dir):
    """Return True if every quarterly table is in data_dir."""
    return all(
        (data_dir / f"{table}.parquet").exists() for table in QUARTERLY_TABLES
    )


def period_label(fiscal_year, fiscal_quarter):
    """Return e.g. "FY2024 Q3"."""
    return f"FY{int(fiscal_year)} Q{int(fiscal_quarter)}"


def quarter_options(scores_quarterly_df):
    """Return the (fiscal_year, fiscal_quarter) pairs with scores, the
    latest first, for the screener's period picker."""
    pairs = (
        scores_quarterly_df[["fiscal_year", "fiscal_quarter"]]
        .drop_duplicates()
        .sort_values(["fiscal_year", "fiscal_quarter"], ascending=False)
    )
    return [(int(y), int(q)) for y, q in pairs.itertuples(index=False)]


def one_quarter(table_df, fiscal_year, fiscal_quarter):
    """Return the rows of one fiscal quarter. Inside a quarter each
    company has one row per fiscal year, so the screener's annual
    functions (which match on cik and fiscal_year) work unchanged."""
    keep = (table_df["fiscal_year"] == fiscal_year) & (
        table_df["fiscal_quarter"] == fiscal_quarter
    )
    return table_df[keep]


def label_missing_quarterly(display_df, verdict_columns):
    """Return the screener's display table with each "No score" verdict
    replaced by NOT_ENOUGH_DATA_SHORT, so a missing quarterly score says
    why instead of looking like an annual blank."""
    shown = display_df.copy()
    for column in verdict_columns:
        shown[column] = shown[column].replace(
            labels.NO_SCORE, NOT_ENOUGH_DATA_SHORT
        )
    return shown


def latest_quarter_end(scores_quarterly_df, fiscal_year, fiscal_quarter):
    """Return the latest quarter end among a quarter's rows (companies
    end their quarters on different dates), or None if there are none."""
    rows = one_quarter(scores_quarterly_df, fiscal_year, fiscal_quarter)
    if rows.empty:
        return None
    return pd.Timestamp(rows["period_end"].max())
