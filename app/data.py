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


def companies():
    """Return the companies table for the current data source."""
    return load_table(resolve_data_source()[1], "companies")


def scores():
    """Return the scores table for the current data source."""
    return load_table(resolve_data_source()[1], "scores")


def score_drivers():
    """Return the score_drivers table for the current data source."""
    return load_table(resolve_data_source()[1], "score_drivers")


def company_facts(cik):
    """Return facts_long rows for one company in the current source."""
    return load_company_facts(resolve_data_source()[1], cik)
