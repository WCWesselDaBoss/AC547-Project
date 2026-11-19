"""Case studies page: did the warning signs show up before known events?

Walks through each company in data/case_studies.csv: the event and its
SEC source, then what the radar showed in the years whose 10-K was filed
before the event. Misses and unscorable cases are shown as plainly as
hits (app/case_view.py).
"""

import streamlit as st

import config
from app import case_view, charts, company_view, data, labels

st.title("Case studies")
st.markdown(
    "Companies with a documented problem, such as an SEC enforcement "
    "action or a restatement. For each one: what would an analyst "
    "reading the 10-Ks have seen **before** the event became public?"
)
st.caption(
    "The event date is the first public disclosure of the problem in a "
    "company filing (an investigation, a delayed filing or a "
    "non-reliance notice), which is usually years before the SEC "
    "action described in the note. A year counts as before the event "
    "only if its 10-K was filed before that date. Cases use the "
    f"published M-Score cutoff of {config.BENEISH_FLAG_CUTOFF}, not the "
    "screener slider, so the cutoff cannot be tuned to make a case look "
    "like a hit."
)

raw_cases = data.load_case_studies(data.case_studies_path())
if raw_cases is None or raw_cases.empty:
    st.info(
        "No case studies yet. Add rows to data/case_studies.csv, then run "
        "python run_pipeline.py --sample-only so they are in the sample.",
        icon=":material/info:",
    )
    st.stop()
cases_df = case_view.read_case_studies(raw_cases)

# ---- Choose a case: a list, plus Previous / Next to walk through them ----
case_count = len(cases_df)
# A deep link (?case=2) opens a case by its number, counting from 1.
linked_case = data.pop_int_param("case")
if linked_case is not None:
    st.session_state[data.CASE_INDEX] = linked_case - 1
if not 0 <= st.session_state.get(data.CASE_INDEX, 0) < case_count:
    st.session_state[data.CASE_INDEX] = 0


def step_case(step):
    """Move to the previous (-1) or next (+1) case, wrapping around."""
    current = st.session_state.get(data.CASE_INDEX, 0)
    st.session_state[data.CASE_INDEX] = (current + step) % case_count


picker, previous_column, next_column = st.columns([6, 1, 1])
case_index = picker.selectbox(
    "Case",
    range(case_count),
    format_func=lambda i: f"{i + 1}. {cases_df.loc[i, 'name']}",
    key=data.CASE_INDEX,
)
previous_column.button(
    "◀ Previous",
    on_click=step_case,
    args=(-1,),
    width="stretch",
    key="case_previous",
)
next_column.button(
    "Next ▶", on_click=step_case, args=(1,), width="stretch", key="case_next"
)
case = cases_df.loc[case_index]

# ---- The event -------------------------------------------------------------
# Escape text from the CSV: "$408 million ... $9 million" would
# otherwise render as a math formula.
st.subheader(labels.escape_markdown(case["name"]))
st.markdown(
    f"**{labels.escape_markdown(case['event_type'])}**, "
    f"{company_view.long_date(case['event_date'])}  \n"
    f"{labels.escape_markdown(case['note'])}"
)
st.link_button(
    "Read the disclosure on EDGAR",
    case["source_url"],
    icon=":material/open_in_new:",
)
st.caption("The source opens sec.gov and needs an internet connection.")

# ---- What the radar showed -------------------------------------------------
scores_df = data.scores()
cik = int(case["cik"])
if cik not in set(scores_df["cik"]):
    st.warning(
        "This company has no scores in the current data. If it was just "
        "added, run python run_pipeline.py --sample-only to put it in the "
        "sample.",
        icon=":material/warning:",
    )
    st.stop()

history = case_view.case_history(
    scores_df, data.financials_filings(), cik, case["event_date"]
)
st.subheader(case_view.headline(history))
for check in case_view.CHECKS:
    st.markdown(f"- {case_view.check_sentence(history, check)}")
st.caption(case_view.CONTEXT_NOTE)

before_years = history.loc[
    history[case_view.BEFORE_EVENT], "fiscal_year"
].tolist()
st.plotly_chart(
    charts.case_m_trend(history, before_years, config.BENEISH_FLAG_CUTOFF),
    width="stretch",
)
st.dataframe(
    case_view.case_table(history),
    hide_index=True,
    width="stretch",
    column_config={
        "Concerns": st.column_config.NumberColumn(format="%d of 3"),
        "M-Score": st.column_config.NumberColumn(format="%.2f"),
    },
)
st.caption(labels.SCOPE_NOTE)

# Open the last year an analyst could have read, with its trace buttons.
last_year = case_view.last_year_before_event(history)
if st.button(
    "Open this company's detail page",
    icon=":material/domain:",
    key="case_open_company",
):
    st.session_state[data.SELECTED_CIK] = cik
    st.session_state[data.SELECTED_YEAR] = (
        last_year
        if last_year is not None
        else int(history["fiscal_year"].max())
    )
    st.switch_page("views/company.py")
