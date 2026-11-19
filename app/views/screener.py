"""Screener page: find companies whose reported earnings show warning signs.

Step 2 placeholder. It proves the data loads and shows what is in it;
the filters and results table are built in Phase 3 step 3.
"""

import streamlit as st

from app import data

st.title("Screener")
st.markdown(
    "Filter companies by year, industry, size and score to find those "
    "whose reported earnings show warning signs worth investigating."
)

scores_df = data.scores()
companies_df = data.companies()

# Counts read straight from the tables, so they always match the data.
year_column, company_column, excluded_column = st.columns(3)
year_column.metric(
    "Fiscal years",
    f"{scores_df['fiscal_year'].min()} to {scores_df['fiscal_year'].max()}",
)
company_column.metric("Companies scored", f"{scores_df['cik'].nunique():,}")
excluded_column.metric(
    "Companies left out of scoring",
    f"{int(companies_df['is_excluded'].sum()):,}",
    help="Banks, insurers, REITs, shell companies, companies with no "
    "industry code, and companies that never filed a 10-K.",
)

st.info(
    "Filters and the results table arrive in the next build step.",
    icon=":material/construction:",
)
