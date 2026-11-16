"""Shared building blocks for the score modules.

Every score compares year t with year t-1 (and the F-Score with t-2), so
the same three questions come up in every module:

1. Where is the prior year? ``with_prior_years`` lines each company-year
   up with the row for EXACTLY the fiscal year before. If that row does
   not exist, the prior values are missing; we never borrow an older year,
   because a two-year change is not the one-year change the papers define.
2. What happens when a denominator is zero? ``safe_divide`` returns NaN.
   Plain pandas division would return +/-infinity, which would then sort
   to the top or bottom of every percentile rank and could flip a flag.
   NaN means "not computable", which is the honest answer, and the reason
   is written to missing_inputs.
3. Why is a value blank? ``build_notes`` turns a list of (condition,
   reason) pairs into the "; "-separated missing_inputs text that the
   scores table carries (CLAUDE.md section 4), so no blank is unexplained.
"""

import numpy as np
import pandas as pd

# Column-name suffixes for lagged values: revenue_prior is revenue at t-1.
LAG_SUFFIXES = {1: "_prior", 2: "_prior2"}
# How each lag is written in missing_inputs notes, e.g. "revenue_t-1".
LAG_LABELS = {0: "t", 1: "t-1", 2: "t-2"}
KEY_COLUMNS = ["cik", "fiscal_year"]


def lagged(column, years_back):
    """Return the column name holding ``column`` from ``years_back`` ago."""
    if years_back == 0:
        return column
    return f"{column}{LAG_SUFFIXES[years_back]}"


def has_row_column(years_back):
    """Return the name of the flag saying the t-k row exists."""
    return f"has_row{LAG_SUFFIXES[years_back]}"


def input_label(column, years_back):
    """Return the missing_inputs label for an input, e.g. 'sga_t-1'."""
    return f"{column}_{LAG_LABELS[years_back]}"


def with_prior_years(financials_df, columns, years_back=1):
    """Return year-t rows with the same columns for t-1 (and t-2) added.

    The prior row is matched on fiscal_year - k exactly. Columns from t-k
    get a suffix (see LAG_SUFFIXES), and a has_row_prior / has_row_prior2
    flag records whether that row existed at all, so a whole missing year
    can be reported once instead of as twenty missing items.
    """
    keys = financials_df[KEY_COLUMNS]
    if keys.duplicated().any():
        # Two rows for one company-year would make "the prior year"
        # ambiguous; Phase 1 guarantees uniqueness, so fail loudly.
        raise ValueError("financials_df has duplicate (cik, fiscal_year)")

    current_df = financials_df[KEY_COLUMNS + list(columns)].copy()
    for k in range(1, years_back + 1):
        prior_df = financials_df[KEY_COLUMNS + list(columns)].copy()
        # Shifting the prior row's year forward by k lets a plain merge
        # on (cik, fiscal_year) line t-k up with t.
        prior_df["fiscal_year"] = prior_df["fiscal_year"] + k
        prior_df = prior_df.rename(
            columns={column: lagged(column, k) for column in columns}
        )
        prior_df[has_row_column(k)] = True
        current_df = current_df.merge(prior_df, on=KEY_COLUMNS, how="left")
        current_df[has_row_column(k)] = (
            current_df[has_row_column(k)].fillna(False).astype(bool)
        )
    return current_df


def safe_divide(numerator, denominator):
    """Return numerator / denominator, with NaN where denominator is 0.

    NaN inputs give NaN as usual. See the module docstring for why a zero
    denominator gives NaN rather than infinity.
    """
    nonzero_denominator = denominator.where(denominator != 0)
    return numerator / nonzero_denominator


def is_higher(current, prior, tolerance):
    """Return a nullable boolean: is ``current`` strictly above ``prior``?

    NA when either side is missing. Values whose gap is within
    ``tolerance`` times the larger absolute value count as equal (False),
    so floating-point rounding cannot award an F-Score point.
    """
    scale = np.maximum(current.abs(), prior.abs())
    result = ((current - prior) > tolerance * scale).astype("boolean")
    # Comparisons with NaN return False in pandas; that would silently
    # turn "unknown" into "failed", so restore NA explicitly.
    result[current.isna() | prior.isna()] = pd.NA
    return result


def is_positive(values):
    """Return a nullable boolean: is the value above zero? NA if missing."""
    result = (values > 0).astype("boolean")
    result[values.isna()] = pd.NA
    return result


def missing_input_conditions(frame, columns_by_lag):
    """Return (condition, label) pairs for missing inputs.

    ``columns_by_lag`` maps a lag (0 = t, 1 = t-1, 2 = t-2) to the inputs
    a score reads from that year, so only inputs actually used are
    reported. If the whole t-k row is absent, one "no_row_t-k" note is
    produced; otherwise each missing column is listed by name (e.g.
    "receivables_t-1").
    """
    conditions = []
    for k, columns in columns_by_lag.items():
        row_exists = (
            frame[has_row_column(k)]
            if k > 0
            else pd.Series(True, index=frame.index)
        )
        if k > 0:
            conditions.append((~row_exists, f"no_row_{LAG_LABELS[k]}"))
        for column in columns:
            is_missing = frame[lagged(column, k)].isna() & row_exists
            conditions.append((is_missing, input_label(column, k)))
    return conditions


def build_notes(index, conditions):
    """Return a "; "-joined note per row from (condition, note) pairs.

    Rows where no condition holds get NA, matching the contract rule that
    missing_inputs is null when the row is complete.
    """
    notes = pd.Series([[] for _ in index], index=index, dtype=object)
    for condition, note in conditions:
        for row in condition[condition.fillna(False)].index:
            if note not in notes[row]:
                notes[row].append(note)
    joined = notes.map(lambda items: "; ".join(items) if items else pd.NA)
    return joined.astype("string")


def combine_notes(*note_series):
    """Merge several notes columns into one, keeping order, no repeats."""
    combined = []
    for row_notes in zip(*note_series):
        items = []
        for text in row_notes:
            if pd.isna(text):
                continue
            for item in text.split("; "):
                if item not in items:
                    items.append(item)
        combined.append("; ".join(items) if items else pd.NA)
    return pd.Series(combined, index=note_series[0].index, dtype="string")
