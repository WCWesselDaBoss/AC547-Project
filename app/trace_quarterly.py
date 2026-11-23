"""Click-to-trace for quarterly (TTM) scores: every input back to its
four quarters and the 10-Q and 10-K filings behind them.

The score parts, formulas and input lists are the annual trace's own
(app/trace.py, built from Phase 2's maps), so the quarterly trace lists
exactly the inputs the score functions read. An input "years back" k
means the financials_ttm row for the SAME fiscal quarter k years
earlier, which is how quarterly scores compare (src/scores/
quarterly_scores.py).

Two tables:
- inputs: one row per input: the value used, the quarter it belongs to,
  and how it was formed (sum of four quarters, quarter-end balance, or
  calculated from other values);
- components: for every value, the rows of ttm_sources behind it: each
  single quarter, its method (reported 3 months, year-to-date
  difference, annual minus 9 months, quarter-end balance) and the
  filing, with the earlier filing of a difference shown negative, so
  the rows add up to the value used.

Pure pandas, no Streamlit. Nothing here recomputes a score.
"""

import numpy as np
import pandas as pd

from app import basis, labels, trace
from src.pipeline import derived_items, ttm
from src.scores import piotroski

# Status of each input, icon AND words (never color alone).
TTM_SUM = "➕ Sum of the four quarters below"
BALANCE = "✅ Quarter-end balance"
CALCULATED = trace.CALCULATED
NOT_AVAILABLE = "⚪ Not available (needs four complete quarters)"
NOT_REPORTED = "⚪ Not reported at the quarter end"
NO_ROW = "⚪ No quarterly data for this quarter"
SHARES_SAME_FILING = "✅ Reported in the same filing"

PRIOR_SHARES_Q4 = trace.PRIOR_SHARES_LABEL
PRIOR_SHARES_Q1_Q3 = (
    "Shares outstanding (prior fiscal year end, as shown in this "
    "quarter's 10-Q)"
)

# Balance sheet items are quarter-end values (one source row each);
# every other item is a TTM sum of four quarters.
BALANCE_COLUMNS = set(ttm.BALANCE_ITEMS)

# The rows of a value add up to it within this absolute amount (sums
# of floating-point dollars).
ADDS_UP_TOLERANCE = 0.5


def _row(label, period, column, value, status, quarter_end=None):
    """Return one inputs-table row."""
    return {
        "Input": label,
        "Quarter": period,
        "Value used": trace.value_text(value, column),
        "How": status,
        "Quarter end": (
            "" if quarter_end is None else f"{quarter_end:%Y-%m-%d}"
        ),
    }


def _component_rows(label, period, sources):
    """Return the components-table rows for one value's sources."""
    rows = []
    for source in sources.sort_values(
        ["component_period_end", "value"], ascending=[True, False]
    ).itertuples(index=False):
        if pd.isna(source.component_period_start):
            quarter = f"at {source.component_period_end:%Y-%m-%d}"
        else:
            quarter = (
                f"{source.component_period_start:%Y-%m-%d} to "
                f"{source.component_period_end:%Y-%m-%d}"
            )
        rows.append(
            {
                "Input": label,
                "Quarter": period,
                "Single quarter": quarter,
                "Method": source.method,
                "Value": trace.value_text(source.value, source.line_item),
                "Accession": source.accession,
                "Filing": source.filing_url,
            }
        )
    return rows


def adds_up(value, sources):
    """Return True if a value's source rows add up to it."""
    if sources.empty or labels.is_missing(value):
        return False
    return bool(abs(sources["value"].sum() - value) <= ADDS_UP_TOLERANCE)


def _value_rows(label, column, ttm_row, period, sources_df, notes):
    """Return (input rows, component rows) for one TTM value, including
    the parts of a calculated value."""
    value = ttm_row[column]
    end = ttm_row["period_end"]
    if labels.is_missing(value):
        missing = NOT_REPORTED if column in BALANCE_COLUMNS else NOT_AVAILABLE
        return [_row(label, period, column, value, missing, end)], []
    derived_text = ttm_row["derived_items"]
    derived = (
        []
        if labels.is_missing(derived_text)
        else derived_text.split(derived_items.SEPARATOR)
    )
    if column in derived:
        inputs = [_row(label, period, column, value, CALCULATED, end)]
        components = []
        function = derived_items.DERIVATIONS[column]
        notes.append(
            f"{period} {label.lower()}: {trace.DERIVATION_NOTES[column]} "
            f"({trace.function_name(function)})."
        )
        for part in trace.DERIVED_COMPONENTS[column]:
            part_inputs, part_components = _value_rows(
                f"↳ {trace.input_label(part)}",
                part,
                ttm_row,
                period,
                sources_df,
                notes,
            )
            if not labels.is_missing(ttm_row[part]):
                inputs += part_inputs
                components += part_components
        return inputs, components
    sources = sources_df[
        (sources_df["period_end"] == end) & (sources_df["line_item"] == column)
    ]
    status = BALANCE if column in BALANCE_COLUMNS else TTM_SUM
    if not adds_up(value, sources):
        status = trace.NOT_MATCHED
    return (
        [_row(label, period, column, value, status, end)],
        _component_rows(label, period, sources),
    )


def prior_shares_rows(fiscal_year, fiscal_quarter, ttm_df, sources_df, facts):
    """Return (input rows, component rows) for F-Score test 7's prior
    share count, found as quarterly_scores finds it: in the filing behind
    quarter t's share count, at the prior fiscal year end (Q1 to Q3,
    option C) or at the same quarter a year earlier (Q4)."""
    label = PRIOR_SHARES_Q4 if fiscal_quarter == 4 else PRIOR_SHARES_Q1_Q3
    period = basis.period_label(fiscal_year, fiscal_quarter)
    column = piotroski.PRIOR_SHARES
    current = basis.one_quarter(ttm_df, fiscal_year, fiscal_quarter)
    lookup_quarter = fiscal_quarter if fiscal_quarter == 4 else 4
    earlier = basis.one_quarter(ttm_df, fiscal_year - 1, lookup_quarter)
    if current.empty or earlier.empty:
        return [_row(label, period, column, np.nan, NO_ROW)], []
    share_sources = sources_df[
        (sources_df["period_end"] == current.iloc[0]["period_end"])
        & (sources_df["line_item"] == "shares_outstanding")
    ]
    if share_sources.empty:
        return [_row(label, period, column, np.nan, NOT_REPORTED)], []
    accession = share_sources.iloc[0]["accession"]
    date = earlier.iloc[0]["period_end"]
    found = facts[
        (facts["line_item"] == "shares_outstanding")
        & (facts["accession"] == accession)
        & (facts["period_end"] == date)
    ]
    # Two different counts in one filing are ambiguous; the score then
    # leaves the test undetermined, so the trace does too.
    if found.empty or found["value"].nunique() > 1:
        return [_row(label, period, column, np.nan, NOT_REPORTED, date)], []
    fact = found.iloc[0]
    return (
        [_row(label, period, column, fact["value"], SHARES_SAME_FILING, date)],
        [
            {
                "Input": label,
                "Quarter": period,
                "Single quarter": f"at {date:%Y-%m-%d}",
                "Method": "share count in the same filing",
                "Value": trace.value_text(fact["value"], column),
                "Accession": fact["accession"],
                "Filing": fact["filing_url"],
            }
        ],
    )


def trace_ttm_inputs(
    inputs, fiscal_year, fiscal_quarter, ttm_df, sources_df, facts_df
):
    """Return (inputs table, components table, notes) for a part's
    inputs. ttm_df, sources_df and facts_df are ONE company's rows of
    financials_ttm, ttm_sources and facts_quarterly."""
    input_rows, component_rows, notes = [], [], []
    for column, years_back in inputs:
        if column == piotroski.PRIOR_SHARES:
            rows, parts = prior_shares_rows(
                fiscal_year, fiscal_quarter, ttm_df, sources_df, facts_df
            )
            input_rows += rows
            component_rows += parts
            continue
        year = fiscal_year - years_back
        period = basis.period_label(year, fiscal_quarter)
        label = trace.input_label(column)
        target = basis.one_quarter(ttm_df, year, fiscal_quarter)
        if target.empty:
            input_rows.append(_row(label, period, column, np.nan, NO_ROW))
            continue
        rows, parts = _value_rows(
            label, column, target.iloc[0], period, sources_df, notes
        )
        input_rows += rows
        component_rows += parts
    return (
        pd.DataFrame(input_rows),
        pd.DataFrame(component_rows),
        notes,
    )
