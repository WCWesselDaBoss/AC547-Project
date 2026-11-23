"""Draw the click-to-trace panel for quarterly (TTM) scores (the
Streamlit side of app/trace_quarterly.py).

Like the annual panel (app/trace_panel.py), it appears as a pop-up from
the button under each verdict card and inline in the trace tab; both call
render_trace, so they always show the same thing. It has the same
signatures as the annual panel, so the company page can use either.
"""

import streamlit as st

from app import basis, data, trace, trace_quarterly

INPUT_COLUMNS = ["Input", "Quarter", "Value used", "How", "Quarter end"]
COMPONENT_COLUMNS = [
    "Input",
    "Quarter",
    "Single quarter",
    "Method",
    "Value",
    "Filing",
    "Accession",
]
COMPONENT_CONFIG = {
    "Filing": st.column_config.LinkColumn(
        "Filing", display_text="Open on EDGAR"
    ),
    "Input": st.column_config.TextColumn("Input", width="medium"),
}


def render_trace(score, row, key_prefix):
    """Draw the trace for one score of one company-quarter row."""
    parts = trace.SCORES[score]
    part_key = st.selectbox(
        "Which part of the score?",
        list(parts),
        format_func=lambda key: parts[key].label,
        key=f"{key_prefix}_{score}_part_quarterly",
    )
    part = parts[part_key]

    st.markdown("**Formula** (the annual formula, applied to TTM values)")
    st.code(part.formula, language=None, wrap_lines=True)
    st.markdown(
        f"**Stored result:** {trace.stored_result_text(row, part)}  \n"
        f"Computed by `{trace.function_name(part.function)}`, run one fiscal "
        'quarter at a time by `src.scores.quarterly_scores`. "t-1" is the '
        "same quarter one year earlier."
    )

    cik = int(row["cik"])
    with st.spinner("Collecting each input's quarters and filings..."):
        inputs, components, notes = trace_quarterly.trace_ttm_inputs(
            part.inputs,
            int(row["fiscal_year"]),
            int(row["fiscal_quarter"]),
            data.company_ttm(cik),
            data.company_ttm_sources(cik),
            data.company_facts_quarterly(cik),
        )
    st.markdown("**Inputs (trailing twelve months, or quarter-end values)**")
    st.dataframe(
        inputs,
        hide_index=True,
        width="stretch",
        column_order=INPUT_COLUMNS,
    )
    for note in notes:
        st.caption(note)
    st.markdown("**The quarters and filings behind each input**")
    if components.empty:
        st.markdown("No input of this part has a value to trace.")
    else:
        st.dataframe(
            components,
            hide_index=True,
            width="stretch",
            column_config=COMPONENT_CONFIG,
            column_order=COMPONENT_COLUMNS,
        )
    st.caption(
        "A flow (revenue, net income, cash flow...) is the sum of four "
        "single quarters. A quarter is the 3-month value reported in its "
        "10-Q; or a year-to-date difference (the later filing's year to "
        "date, minus the earlier one's, shown negative); the fourth quarter "
        "is the 10-K's year minus the 9-month year to date. Each value is "
        "as first reported. The EDGAR links open sec.gov and need an "
        "internet connection; everything else works offline."
    )
    st.caption(basis.QUARTERLY_NOTE)


@st.dialog("Trace to the SEC filings", width="large")
def trace_dialog(score, row):
    """Open the quarterly trace for one score as a pop-up."""
    period = basis.period_label(row["fiscal_year"], row["fiscal_quarter"])
    st.markdown(f"#### {trace.SCORE_LABELS[score]}, {period} (TTM)")
    render_trace(score, row, key_prefix="dialog")
