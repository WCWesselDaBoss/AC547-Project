"""Company detail page: one company's verdict, reasons, peers and detail.

Built in layers, simple to detailed, so a non-expert gets the answer in
five seconds and an expert can keep digging:
1. Verdict: one summary line and three traffic-light cards.
2. Why: the stored score_drivers sentences, shown exactly as stored.
3. Peers: one sentence per score from the stored percentile ranks.
4. Detail: trend charts, peer-rank bars and every score component.
Click-to-trace (the SEC source of every input) is added in step 5.
"""

import streamlit as st

import config
from app import charts, company_view, data, labels, screening, style

st.title("Company detail")

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
cards = company_view.verdict_cards(row, cutoff)
st.subheader(company_view.verdict_summary(row, cards))
for column, card in zip(st.columns(len(cards)), cards):
    column.markdown(style.verdict_card_html(*card), unsafe_allow_html=True)
# Shown on every company page (Phase 3 brief).
st.caption(labels.SCOPE_NOTE)
if cutoff != config.BENEISH_FLAG_CUTOFF:
    st.caption(
        f"Using the screener's M-Score cutoff of {cutoff:.2f} "
        f"(published cutoff {config.BENEISH_FLAG_CUTOFF:.2f})."
    )

# ---- 2. Why ----------------------------------------------------------------
st.subheader("Why: what pushed the manipulation score up")
drivers_df = company_view.driver_sentences(
    data.score_drivers(), cik, fiscal_year
)
if drivers_df.empty:
    st.markdown(company_view.no_driver_message(row))
for driver in drivers_df.itertuples():
    st.markdown(f"**{driver.driver_rank}. {driver.explanation}**")
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
st.caption(company_view.peer_description(row))
for score, sentence in company_view.peer_sentences(row).items():
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
trends_tab, peers_tab, components_tab = st.tabs(
    ["Trends over time", "Peer ranks", "All score components"]
)
with trends_tab:
    st.plotly_chart(
        charts.m_trend(history_df, fiscal_year, cutoff), width="stretch"
    )
    st.plotly_chart(charts.z_trend(history_df, fiscal_year), width="stretch")
    st.plotly_chart(
        charts.f_trend(history_df, fiscal_year, company_view.F_SCORE_MAX),
        width="stretch",
    )
    st.caption("Gaps mean the score could not be calculated that year.")
with peers_tab:
    st.plotly_chart(charts.percentile_figure(row), width="stretch")
    st.caption(
        "Each bar is the share of other companies in the peer group with "
        "a lower value (ties count as half). Scores that are not ranked "
        "are left off."
    )
with components_tab:
    m_column, z_column = st.columns(2)
    m_text = labels.format_number(row["m_score"])
    m_column.markdown(f"**Earnings manipulation score: {m_text}**")
    m_column.caption("Index values: 1.00 means no change from last year.")
    m_column.dataframe(
        company_view.m_index_table(row),
        hide_index=True,
        column_config={"Value": st.column_config.NumberColumn(format="%.3f")},
    )
    z_column.markdown(
        f"**Financial distress score: {labels.format_number(row['z_score'])}**"
    )
    z_column.dataframe(
        company_view.z_ratio_table(row),
        hide_index=True,
        column_config={"Value": st.column_config.NumberColumn(format="%.3f")},
    )
    f_value = row["f_score"]
    f_text = "Not available" if labels.is_missing(f_value) else int(f_value)
    st.markdown(f"**Financial strength score: {f_text}**")
    st.dataframe(company_view.f_signal_table(row), hide_index=True)

st.info(
    "Click-to-trace (the SEC filing behind every input) arrives in the "
    "next build step.",
    icon=":material/construction:",
)
