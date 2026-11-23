"""Load the finished Parquet tables for the dashboard, with caching.

The app only reads tables built by Phases 1 and 2; nothing here computes
a score (CLAUDE.md section 3). Which folder is read (fixture, sample or
full) is decided by config.app_data_dir and the EQR_DATA_SOURCE setting.

Caching: st.cache_data keeps each table in memory after the first read,
so changing a filter does not re-read files. The data folder is part of
every cache key, so two data sources can never mix.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import config
from app import basis

# Session-state keys that carry the company chosen on one page (screener,
# case studies) to the company detail page. They are also the keys of the
# company page's own pickers, so choosing there updates them directly.
SELECTED_CIK = "selected_cik"
SELECTED_YEAR = "selected_fiscal_year"
# Quarterly mode also hands over the fiscal quarter (1 to 4).
SELECTED_QUARTER = "selected_fiscal_quarter"

# Screener widget keys. The company page reads SCREENER_CUTOFF so its
# M-Score card uses the same cutoff the analyst chose in the screener.
SCREENER_CUTOFF = "screener_cutoff"
SCREENER_KEYS = [
    "screener_year",
    "screener_industries",
    "screener_sizes",
    SCREENER_CUTOFF,
    "screener_zones",
    "screener_f_range",
    # Quarterly mode's period picker: (fiscal_year, fiscal_quarter).
    "screener_quarter",
]

# The case shown on the case studies page.
CASE_INDEX = "case_index"

# Every widget value that must survive moving between pages (see
# keep_widget_state).
PERSISTENT_KEYS = SCREENER_KEYS + [
    SELECTED_CIK,
    SELECTED_YEAR,
    SELECTED_QUARTER,
    CASE_INDEX,
    basis.BASIS_KEY,
]

# The fixture source has its own made-up case file, so tests never depend
# on the real, hand-curated data/case_studies.csv.
CASE_STUDIES_FILE = "case_studies.csv"


def pop_int_param(name):
    """Return URL query parameter ``name`` as an int, then remove it.

    Deep links such as /company?cik=320193&year=2024 open a page on a
    chosen company (used for demo bookmarks and the screenshot script).
    The parameter is removed once read, so it is applied a single time
    and never overrides what the analyst picks afterwards. A missing or
    non-numeric value returns None and is ignored.
    """
    value = st.query_params.get(name)
    if value is None:
        return None
    del st.query_params[name]
    try:
        return int(value)
    except ValueError:
        return None


def keep_widget_state():
    """Stop Streamlit from forgetting widget values on other pages.

    Streamlit deletes a widget's value at the end of any run in which
    that widget is not drawn, so leaving the screener would reset its
    filters. Re-saving each value as plain session state at the start of
    every run (app/app.py calls this) keeps it. This is the workaround
    Streamlit's documentation gives for multipage apps.
    """
    for key in PERSISTENT_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def resolve_data_source():
    """Return (source name, data folder) for this session.

    Raises ValueError or FileNotFoundError (from config.app_data_dir)
    when the setting is wrong or the tables are missing; app/app.py
    shows those as a readable message.
    """
    data_dir = config.app_data_dir()
    source = next(
        name
        for name, folder in config.APP_DATA_DIRS.items()
        if folder == data_dir
    )
    return source, data_dir


@st.cache_data(show_spinner="Loading data...")
def load_table(data_dir, table, columns=None):
    """Read one whole table (or some of its columns) from data_dir.

    For the small tables only: companies, scores, score_drivers and
    selected financials_annual columns. columns is a tuple (not a list)
    because cache keys must be hashable.
    """
    path = Path(data_dir) / f"{table}.parquet"
    return pd.read_parquet(path, columns=list(columns) if columns else None)


@st.cache_data(show_spinner="Loading filing details...", max_entries=64)
def load_company_facts(data_dir, cik):
    """Return facts_long rows for one company.

    The full facts_long is about 2.4 million rows (630 MB in memory), so
    it is never cached whole: reading one company with a Parquet filter
    takes under half a second, and the last 64 companies viewed stay in
    the cache.
    """
    path = Path(data_dir) / "facts_long.parquet"
    return pd.read_parquet(path, filters=[("cik", "==", int(cik))])


@st.cache_data(show_spinner="Loading filing details...", max_entries=64)
def load_company_financials(data_dir, cik):
    """Return every financials_annual row (all columns) for one company.

    Click-to-trace needs each input's value, period end and derived_items
    for one company only, so it reads that company rather than the
    whole table.
    """
    path = Path(data_dir) / "financials_annual.parquet"
    return pd.read_parquet(path, filters=[("cik", "==", int(cik))])


def companies():
    """Return the companies table for the current data source."""
    return load_table(resolve_data_source()[1], "companies")


def scores():
    """Return the scores table for the current data source."""
    return load_table(resolve_data_source()[1], "scores")


def score_drivers():
    """Return the score_drivers table for the current data source."""
    return load_table(resolve_data_source()[1], "score_drivers")


def financials_size():
    """Return the financials_annual columns the screener needs.

    Only four columns: the size band (total assets) and the size-floor
    count. Reading the whole table would load data the app never shows.
    """
    columns = ("cik", "fiscal_year", "total_assets", "passes_size_floor")
    return load_table(resolve_data_source()[1], "financials_annual", columns)


def financials_filings():
    """Return each company-year's period end, 10-K filing date and accession.

    The company page header says which 10-K a year's numbers come from.
    """
    columns = ("cik", "fiscal_year", "period_end", "filed_date", "accession")
    return load_table(resolve_data_source()[1], "financials_annual", columns)


def company_facts(cik):
    """Return facts_long rows for one company in the current source."""
    return load_company_facts(resolve_data_source()[1], cik)


def company_financials(cik):
    """Return financials_annual rows for one company in the source."""
    return load_company_financials(resolve_data_source()[1], cik)


def quarterly_available():
    """Return True if the current data source has the quarterly tables
    (the test fixtures and an annual-only build do not)."""
    return basis.quarterly_tables_present(resolve_data_source()[1])


def current_basis():
    """Return basis.QUARTERLY if the analyst chose it and the tables are
    there, else basis.ANNUAL (the default, always)."""
    chosen = st.session_state.get(basis.BASIS_KEY, basis.ANNUAL)
    if chosen == basis.QUARTERLY and quarterly_available():
        return basis.QUARTERLY
    return basis.ANNUAL


def scores_quarterly():
    """Return the scores_quarterly table for the current data source."""
    return load_table(resolve_data_source()[1], "scores_quarterly")


def score_drivers_quarterly():
    """Return score_drivers_quarterly for the current data source."""
    return load_table(resolve_data_source()[1], "score_drivers_quarterly")


def financials_ttm_size():
    """Return the financials_ttm columns the quarterly screener needs:
    quarter-end total assets (size band) and the size-floor flag."""
    columns = (
        "cik",
        "fiscal_year",
        "fiscal_quarter",
        "total_assets",
        "passes_size_floor",
    )
    return load_table(resolve_data_source()[1], "financials_ttm", columns)


def case_studies_path():
    """Return the case studies CSV for the current data source.

    Real data (sample or full) uses the committed, hand-curated
    data/case_studies.csv; the fixture source uses its own copy.
    """
    source, data_dir = resolve_data_source()
    if source == "fixture":
        return data_dir / CASE_STUDIES_FILE
    return config.CASE_STUDIES_PATH


@st.cache_data(show_spinner="Loading case studies...")
def load_case_studies(path):
    """Read the case studies CSV, or return None if it does not exist."""
    path = Path(path)
    if not path.exists():
        return None
    return pd.read_csv(path)
