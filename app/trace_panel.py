"""Draw the click-to-trace panel (the Streamlit side of app/trace.py).

The same panel appears two ways on the company page: as a pop-up from
the "Trace to the 10-K" button under each verdict card, and inline in
the "Trace to SEC filing" tab. Both call render_trace, so they always
show the same thing.
"""

import streamlit as st

from app import data, trace

# The EDGAR link comes right after the status, so the source of each
# input is visible without scrolling sideways.
COLUMN_ORDER = [
    "Input",
    "Fiscal year",
    "Value used",
    "Source",
    "Filing",
    "XBRL tag",
    "Period",
    "10-K filed",
    "Accession",
    "Later filings",
]

TABLE_COLUMNS = {
    "Filing": st.column_config.LinkColumn(
        "Filing", display_text="Open on EDGAR"
    ),
    "Input": st.column_config.TextColumn("Input", width="medium"),
    "Source": st.column_config.TextColumn("Source", width="medium"),
}


def render_trace(score, row, key_prefix):
    """Draw the trace for one score of one company-year row.

    key_prefix keeps the part picker's widget key unique, because the
    pop-up and the tab can both be on the page.
    """
    parts = trace.SCORES[score]
    part_key = st.selectbox(
        "Which part of the score?",
        list(parts),
        format_func=lambda key: parts[key].label,
        key=f"{key_prefix}_{score}_part",
    )
    part = parts[part_key]

    st.markdown("**Formula**")
    st.code(part.formula, language=None, wrap_lines=True)
    st.markdown(
        f"**Stored result:** {trace.stored_result_text(row, part)}  \n"
        f"Computed by `{trace.function_name(part.function)}` "
        "in the Phase 2 score code."
    )

    cik = int(row["cik"])
    fiscal_year = int(row["fiscal_year"])
    with st.spinner("Matching each input to its 10-K filing..."):
        table, notes = trace.trace_inputs(
            part.inputs,
            fiscal_year,
            data.company_financials(cik),
            data.company_facts(cik),
        )
    st.markdown("**Inputs, as first reported in the company's 10-K filings**")
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config=TABLE_COLUMNS,
        column_order=COLUMN_ORDER,
    )
    for note in notes:
        st.caption(note)
    st.caption(
        "Scores use each value as first reported, because that is what "
        "investors saw at the time. Later restatements are listed but "
        "not used. The EDGAR links open sec.gov and need an internet "
        "connection; everything else on this page works offline."
    )


@st.dialog("Trace to the SEC filing", width="large")
def trace_dialog(score, row):
    """Open the trace for one score as a pop-up over the company page."""
    st.markdown(
        f"#### {trace.SCORE_LABELS[score]}, FY{int(row['fiscal_year'])}"
    )
    render_trace(score, row, key_prefix="dialog")
