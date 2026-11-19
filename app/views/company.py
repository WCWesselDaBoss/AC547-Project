"""Company detail page: one company's verdict, reasons, peers and sources.

Step 2 placeholder; built in Phase 3 step 4 (verdict, why, peers,
detail) and step 5 (click-to-trace).
"""

import streamlit as st

from app import data, labels

st.title("Company detail")

# Placeholder handoff check: show which company the screener selected.
selected_cik = st.session_state.get(data.SELECTED_CIK)
if selected_cik is not None:
    companies_df = data.companies()
    name = companies_df.loc[companies_df["cik"] == selected_cik, "name"]
    year = st.session_state.get(data.SELECTED_YEAR)
    st.subheader(f"{name.iloc[0]} (FY{year})")
st.markdown(
    "See one company's three checks at a glance, the reasons behind "
    "them, how it compares with similar companies, and the SEC filing "
    "behind every number."
)
# The scope note appears on every company page (Phase 3 brief).
st.caption(labels.SCOPE_NOTE)

st.info(
    "The company view arrives in a later build step.",
    icon=":material/construction:",
)
