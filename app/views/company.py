"""Company detail page: one company's verdict, reasons, peers and detail.

Built in layers, simple to detailed, so a non-expert gets the answer in
five seconds and an expert can keep digging:
1. Verdict: one summary line and three traffic-light cards.
2. Why: the stored score_drivers sentences, shown exactly as stored.
3. Peers: one sentence per score from the stored percentile ranks.
4. Detail: trend charts, peer-rank bars and every score component.
5. Trace: every number back to its SEC filing, from a button under each
   card (pop-up) or the "Trace to SEC filing" tab (app/trace_panel.py).

In quarterly (TTM) mode the same layers show one fiscal quarter, with
the wording from app/company_quarterly.py; annual mode is unchanged.
"""

import streamlit as st

import config
from app import basis, charts, company_quarterly, company_view, data
from app import labels, screening, style, trace, trace_panel
from app import trace_panel_quarterly
from app.components import price_chart

# The score behind each verdict card, in card order (M, Z'', F).
CARD_SCORES = ["m_score", "z_score", "f_score"]

st.title("Company detail")

quarterly = data.current_basis() == basis.QUARTERLY
if quarterly:
    st.info(basis.QUARTERLY_NOTE, icon=":material/warning:")
    scores_df = data.scores_quarterly()
else:
    scores_df = data.scores()
companies_df = data.companies()
choices = company_view.company_choices(companies_df, scores_df)

if not choices:
    st.warning("No scored companies in this data.", icon=":material/info:")
    st.stop()

# ---- Pick a company and year ----------------------------------------------
# The pickers' keys are the same session keys the screener sets, so a row
# clicked there opens here. A stale choice (e.g. after switching data
# sources) falls back to the first company rather than raising an error.
# A deep link (?cik=...&year=...) picks the company-year once.
linked_cik = data.pop_int_param("cik")
linked_year = data.pop_int_param("year")
# Quarterly mode: ?quarter=3 picks the fiscal quarter once.
linked_quarter = data.pop_int_param("quarter")
if linked_quarter is not None:
    st.session_state[data.SELECTED_QUARTER] = linked_quarter
if linked_cik is not None:
    st.session_state[data.SELECTED_CIK] = linked_cik
if linked_year is not None:
    st.session_state[data.SELECTED_YEAR] = linked_year
if st.session_state.get(data.SELECTED_CIK) not in choices:
    st.session_state[data.SELECTED_CIK] = next(iter(choices))

company_column, year_column = st.columns([3, 1])
cik = company_column.selectbox(
    "Company (type to search by name or ticker)",
    list(choices),
    format_func=choices.get,
    key=data.SELECTED_CIK,
)

# The analyst's screener cutoff, so both pages give the same verdict.
cutoff = st.session_state.get(data.SCREENER_CUTOFF, config.BENEISH_FLAG_CUTOFF)
if quarterly:
    # The quarter picker starts on the quarter handed over by the
    # screener (or the latest), and writes the choice back to the same
    # session keys, so it survives moving between pages.
    quarters_df = company_quarterly.company_quarters(scores_df, cik, cutoff)
    periods = company_quarterly.period_choices(quarters_df)
    handed_over = (
        st.session_state.get(data.SELECTED_YEAR),
        st.session_state.get(data.SELECTED_QUARTER),
    )
    start = periods.index(handed_over) if handed_over in periods else 0
    fiscal_year, fiscal_quarter = year_column.selectbox(
        "Fiscal quarter",
        periods,
        index=start,
        format_func=lambda period: basis.period_label(*period),
    )
    st.session_state[data.SELECTED_YEAR] = fiscal_year
    st.session_state[data.SELECTED_QUARTER] = fiscal_quarter
    row = basis.one_quarter(quarters_df, fiscal_year, fiscal_quarter).iloc[0]
    # Trends: the same quarter across years, as the scores compare it.
    history_df = company_quarterly.same_quarter_history(
        quarters_df, fiscal_quarter
    )
else:
    history_df = company_view.company_scores(scores_df, cik, cutoff)
    years = sorted(history_df["fiscal_year"].tolist(), reverse=True)
    if st.session_state.get(data.SELECTED_YEAR) not in years:
        st.session_state[data.SELECTED_YEAR] = years[0]
    fiscal_year = year_column.selectbox(
        "Fiscal year",
        years,
        format_func=lambda year: f"FY{year}",
        key=data.SELECTED_YEAR,
    )
    row = history_df[history_df["fiscal_year"] == fiscal_year].iloc[0]

company = companies_df[companies_df["cik"] == cik].iloc[0]
if quarterly:
    filing_text = company_quarterly.ttm_sentence(row)
else:
    filing_text = company_view.filing_sentence(
        data.financials_filings(), cik, fiscal_year
    )
st.caption(
    f"{company_view.company_label(company['name'], company['ticker'])} · "
    f"{screening.industry_label(company['sic'], company['sic_description'])}"
    " · "
    f"CIK {cik}" + (f"  \n{filing_text}" if filing_text else "")
)

# ---- 1. Verdict ------------------------------------------------------------
if quarterly:
    cards = company_quarterly.quarterly_cards(row, cutoff)
    st.subheader(company_quarterly.quarterly_summary(row))
else:
    cards = company_view.verdict_cards(row, cutoff)
    st.subheader(company_view.verdict_summary(row))
unscored_text = (
    company_quarterly.unscored_note(cards)
    if quarterly
    else company_view.unscored_note(cards)
)
if unscored_text:
    st.caption(unscored_text)
for column, card in zip(st.columns(len(cards)), cards):
    column.markdown(style.verdict_card_html(*card), unsafe_allow_html=True)

# One trace button per card, right under it, so the source of every
# verdict is one click away (the headline traceability feature). In
# quarterly mode the panel shows each TTM input's four quarters and the
# 10-Q and 10-K filings behind them.
panel = trace_panel_quarterly if quarterly else trace_panel
if quarterly:
    button_text = "🔎 Trace to the filings"
    button_help = (
        "Show the formula, every input, its four quarters and a link to "
        "each 10-Q or 10-K it came from."
    )
else:
    button_text = "🔎 Trace to the 10-K"
    button_help = (
        "Show the formula, every input, its XBRL tag and a link to the "
        "SEC filing it came from."
    )
for column, score in zip(st.columns(len(cards)), CARD_SCORES):
    if column.button(
        button_text,
        key=f"trace_button_{score}",
        help=button_help,
        width="stretch",
    ):
        panel.trace_dialog(score, row)
# Shown on every company page (Phase 3 brief).
st.caption(labels.SCOPE_NOTE)
if cutoff != config.BENEISH_FLAG_CUTOFF:
    st.caption(
        f"Using the screener's M-Score cutoff of {cutoff:.2f} "
        f"(published cutoff {config.BENEISH_FLAG_CUTOFF:.2f})."
    )

# ---- 2. Why ----------------------------------------------------------------
st.subheader("Why: what pushed the manipulation score up")
if quarterly:
    drivers_df = company_quarterly.quarter_drivers(
        data.score_drivers_quarterly(), cik, fiscal_year, fiscal_quarter
    )
else:
    drivers_df = company_view.driver_sentences(
        data.score_drivers(), cik, fiscal_year
    )
if drivers_df.empty:
    st.markdown(
        company_quarterly.no_driver_message(row)
        if quarterly
        else company_view.no_driver_message(row)
    )
for driver in drivers_df.itertuples():
    st.markdown(f"**{driver.driver_rank}.** {driver.explanation}")
    st.caption(
        f"{labels.M_INDEX_LABELS[driver.component.lower()]}: "
        f"{driver.component_value:.2f}"
    )
missing = company_view.missing_input_sentences(row)
if missing:
    with st.expander(f"What was missing or adjusted ({len(missing)})"):
        st.markdown(
            "Blank scores are left blank rather than estimated. Where the "
            "method allows, a missing input is set to neutral instead."
        )
        for sentence in missing:
            st.markdown(f"- {sentence}")

# ---- 3. Peers --------------------------------------------------------------
st.subheader("Compared with similar companies")
st.caption(
    company_quarterly.quarterly_peer_description(row)
    if quarterly
    else company_view.peer_description(row)
)
sentences = (
    company_quarterly.peer_sentences(row)
    if quarterly
    else company_view.peer_sentences(row)
)
for score, sentence in sentences.items():
    st.markdown(f"**{company_view.PEER_SCORE_NAMES[score]}.** {sentence}")
if company_view.small_peer_group(row):
    st.warning(
        f"This ranking rests on only {int(row['peer_group_size'])} "
        "companies, so treat it with caution.",
        icon=":material/group:",
    )
source, _ = data.resolve_data_source()
if source != "full":
    st.caption(
        "Peers here come only from the companies in this data set, so "
        "the rankings are illustrative."
    )

# ---- 4. Detail -------------------------------------------------------------
st.subheader("Detail")
# The stock price with a marker on each 10-K's filing date, colored by
# the warnings that 10-K raised (app/components/price_chart.py).
st.markdown(
    "**Stock price, 10-K and quarterly warnings**"
    if quarterly
    else "**Stock price and 10-K warnings**"
)
price_chart.render_price_chart(cik, key="company", quarterly=quarterly)
trends_tab, peers_tab, components_tab, trace_tab = st.tabs(
    [
        "Trends over time",
        "Peer ranks",
        "All score components",
        "🔎 Trace to SEC filing",
    ]
)
with trends_tab:
    # A score with no value in any year gets a sentence, not an empty
    # chart, so a blank plot is never mistaken for a loading problem.
    trend_charts = {
        "m_score": charts.m_trend(history_df, fiscal_year, cutoff),
        "z_score": charts.z_trend(history_df, fiscal_year),
        "f_score": charts.f_trend(
            history_df, fiscal_year, company_view.F_SCORE_MAX
        ),
    }
    for score, figure in trend_charts.items():
        if history_df[score].isna().all():
            st.info(
                f"{labels.COLUMN_LABELS[score]}: not available in any year, "
                "because an input it needs was not reported.",
                icon=":material/info:",
            )
        else:
            st.plotly_chart(figure, width="stretch")
    if quarterly:
        st.caption(
            f"Q{fiscal_quarter} of each year (trailing twelve months). "
            "Gaps mean the score could not be calculated that quarter."
        )
    else:
        st.caption("Gaps mean the score could not be calculated that year.")
with peers_tab:
    percentile_chart = charts.percentile_figure(row)
    if len(percentile_chart.data[0].x) == 0:
        st.info(
            "No peer ranks this year: the scores are blank or no other "
            "company in the peer group has them. The sentences above "
            "explain each one.",
            icon=":material/info:",
        )
    else:
        st.plotly_chart(percentile_chart, width="stretch")
        st.caption(
            "Each bar is the share of other companies in the peer group "
            "with a lower value (ties count as half). Scores that are not "
            "ranked are left off."
        )
with components_tab:
    m_column, z_column = st.columns(2)
    m_text = labels.format_number(row["m_score"])
    z_text = labels.format_number(row["z_score"])
    f_value = row["f_score"]
    f_text = "Not available" if labels.is_missing(f_value) else int(f_value)
    if quarterly:
        # A missing quarterly score always says why.
        m_text, z_text, f_text = [
            basis.NOT_ENOUGH_DATA if labels.is_missing(row[score]) else text
            for score, text in zip(CARD_SCORES, [m_text, z_text, f_text])
        ]
    m_column.markdown(f"**Earnings manipulation score: {m_text}**")
    m_column.caption("Index values: 1.00 means no change from last year.")
    m_column.dataframe(
        company_view.m_index_table(row),
        hide_index=True,
        column_config={"Value": st.column_config.NumberColumn(format="%.3f")},
    )
    z_column.markdown(f"**Financial distress score: {z_text}**")
    z_column.dataframe(
        company_view.z_ratio_table(row),
        hide_index=True,
        column_config={"Value": st.column_config.NumberColumn(format="%.3f")},
    )
    st.markdown(f"**Financial strength score: {f_text}**")
    st.dataframe(company_view.f_signal_table(row), hide_index=True)

with trace_tab:
    trace_score = st.selectbox(
        "Which score?",
        list(trace.SCORE_LABELS),
        format_func=trace.SCORE_LABELS.get,
        key="trace_tab_score",
    )
    panel.render_trace(trace_score, row, key_prefix="tab")
