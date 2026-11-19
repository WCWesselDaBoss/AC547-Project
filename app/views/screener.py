"""Screener page: find companies whose reported earnings show warning signs.

The analyst picks a year and narrows the list; companies with the most
concerns come first. Every value shown comes from the scores table; the
only thing recalculated is the M-Score flag at the analyst's cutoff,
using Phase 2's own function (see app/screening.py).
"""

import streamlit as st

import config
from app import data, labels, screening

st.title("Screener")
st.markdown(
    "Find companies whose reported earnings show warning signs worth "
    "investigating. Pick a year and narrow the list; companies with the "
    "most concerns are listed first."
)

scores_df = data.scores()
companies_df = data.companies()
financials_df = data.financials_size()
source, _ = data.resolve_data_source()

# ---- Filters, row 1: which companies -------------------------------------
years = sorted(scores_df["fiscal_year"].unique(), reverse=True)
year_column, industry_column, size_column = st.columns([1, 3, 2])
fiscal_year = year_column.selectbox(
    "Fiscal year",
    years,
    format_func=lambda year: f"FY{year}",
    key="screener_year",
    help="Scores use the numbers as first reported in that year's 10-K.",
)
screen_df = screening.screen_table(
    scores_df, companies_df, financials_df, fiscal_year
)
industries = industry_column.multiselect(
    "Industry",
    sorted(screen_df[screening.INDUSTRY].unique()),
    placeholder="All industries",
    key="screener_industries",
)
sizes = size_column.multiselect(
    "Size (total assets that year)",
    list(config.APP_SIZE_BANDS),
    placeholder="All sizes",
    key="screener_sizes",
)

# ---- Filters, row 2: the three checks ------------------------------------
cutoff_column, zone_column, f_column = st.columns(3)
cutoff = cutoff_column.slider(
    f"{labels.CHECK_NAMES['m']}: warn when M-Score is above",
    min_value=config.APP_M_CUTOFF_MIN,
    max_value=config.APP_M_CUTOFF_MAX,
    value=config.BENEISH_FLAG_CUTOFF,
    step=config.APP_M_CUTOFF_STEP,
    format="%.2f",
    key=data.SCREENER_CUTOFF,
    help=(
        f"Beneish's published cutoff is {config.BENEISH_FLAG_CUTOFF}. "
        f"Many practitioners use {config.BENEISH_ALTERNATE_CUTOFF}, "
        "which warns about more companies. Moving the slider left warns "
        "about more companies; right, fewer."
    ),
)
zone_options = {
    **labels.Z_ZONE_LABELS,
    screening.NO_SCORE_KEY: labels.NO_SCORE,
}
z_zones = zone_column.multiselect(
    f"{labels.CHECK_NAMES['z']} (Altman Z'' zone)",
    list(zone_options),
    format_func=zone_options.get,
    placeholder="All zones",
    key="screener_zones",
)
f_range = f_column.slider(
    f"{labels.CHECK_NAMES['f']} (Piotroski F-Score)",
    min_value=screening.F_SCORE_RANGE[0],
    max_value=screening.F_SCORE_RANGE[1],
    value=screening.F_SCORE_RANGE,
    key="screener_f_range",
    help=(
        "0 to 9; higher is stronger. Companies without an F-Score are "
        "hidden once you narrow this range."
    ),
)

# ---- Results --------------------------------------------------------------
screen_df = screening.apply_cutoff(screen_df, cutoff)
shown_df = screening.sort_by_risk(
    screening.filter_screen(screen_df, industries, sizes, z_zones, f_range)
)

st.markdown(
    f"**{len(shown_df):,}** of {len(screen_df):,} companies scored in "
    f"FY{fiscal_year} match your filters."
)

if shown_df.empty:
    st.warning(
        "No companies match these filters. Try removing an industry or "
        "size, choosing more zones, or widening the F-Score range.",
        icon=":material/filter_alt_off:",
    )
else:
    selection = st.dataframe(
        screening.display_table(shown_df),
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Concerns": st.column_config.NumberColumn(
                format="%d of 3",
                help=(
                    "How many of the three checks show a warning. A check "
                    "with no score counts as no warning; blank means none "
                    "of the three could be scored."
                ),
            ),
            "M-Score": st.column_config.NumberColumn(format="%.2f"),
            "Z''-Score": st.column_config.NumberColumn(format="%.2f"),
            "F-Score": st.column_config.NumberColumn(format="%d"),
        },
    )
    st.caption(
        "Select a row to open that company's detail page. " + labels.SCOPE_NOTE
    )
    # Hand the chosen company to the detail page through session state.
    if selection.selection.rows:
        chosen = shown_df.iloc[selection.selection.rows[0]]
        st.session_state[data.SELECTED_CIK] = int(chosen["cik"])
        st.session_state[data.SELECTED_YEAR] = int(fiscal_year)
        st.switch_page("views/company.py")

# ---- Who is not in this list, and why ------------------------------------
excluded_total = int(companies_df["is_excluded"].sum())
below_floor = screening.below_size_floor_count(
    financials_df, companies_df, fiscal_year
)
floor_text = labels.format_money(config.SIZE_FLOOR_USD, decimals=0)
if source == "sample" and excluded_total == 0:
    # The committed sample holds only in-scope companies, so a count of
    # zero would wrongly suggest nothing is ever excluded.
    excluded_text = (
        "This sample holds only companies in scope, so companies excluded "
        "from the full data (such as banks and foreign filers) do not "
        "appear here."
    )
else:
    excluded_text = (
        f"{excluded_total:,} companies are outside the scope (such as "
        "banks, insurers and foreign filers)."
    )
st.caption(
    f"**Not in this list:** {excluded_text} {below_floor:,} companies "
    f"fell below the {floor_text} size floor in FY{fiscal_year}."
)

with st.expander("Why are some companies or scores missing?"):
    st.markdown(
        "**Companies outside the scope.** A company can have more than "
        "one reason, so these can add up to more than the total."
    )
    reason_counts = screening.exclusion_counts(companies_df)
    if reason_counts.empty:
        st.markdown("None in this data.")
    for reason, count in reason_counts.items():
        st.markdown(f"- {reason}: {count:,}")

    st.markdown(
        f"**Companies below the size floor.** A company-year is scored "
        f"only if revenue or total assets is at least {floor_text}. "
        f"FY{fiscal_year}: {below_floor:,}."
    )

    st.markdown(
        f"**Scores that could not be calculated in FY{fiscal_year}.** "
        "A score is left blank rather than estimated when an input was "
        "not reported in the 10-K."
    )
    for check, count in screening.blank_score_counts(screen_df).items():
        st.markdown(f"- {check}: {count:,} of {len(screen_df):,} blank")
    top_reasons = screening.top_missing_reasons(screen_df)
    if not top_reasons.empty:
        st.markdown("Most common gaps among companies missing a score:")
        for reason, count in top_reasons.items():
            st.markdown(f"- {reason}: {count:,} companies")
