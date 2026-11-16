"""Shared pytest fixtures for the Phase 2 score tests.

The fixture tables and the meaning of each made-up company are described
in tests/fixtures/build_fixtures.py.
"""

import pandas as pd
import pytest

from tests.fixtures import build_fixtures


@pytest.fixture
def financials_fixture():
    """Return a fresh copy of the 9-row financials_annual fixture.

    Each test gets its own copy, so a test that edits a value (zero
    sales, a missing item) cannot leak into another test.
    """
    return pd.read_parquet(build_fixtures.FINANCIALS_FIXTURE_PATH)


@pytest.fixture
def facts_long_fixture():
    """Return a fresh copy of the share-count facts_long fixture."""
    return pd.read_parquet(build_fixtures.FACTS_LONG_FIXTURE_PATH)


def row(result_df, cik, fiscal_year):
    """Return the single result row for one company-year as a Series."""
    match = result_df[
        (result_df["cik"] == cik) & (result_df["fiscal_year"] == fiscal_year)
    ]
    assert len(match) == 1, f"expected one row for {cik} FY{fiscal_year}"
    return match.iloc[0]


def set_value(financials_df, cik, fiscal_year, column, value):
    """Change one input in the fixture copy (for edge-case tests)."""
    mask = (financials_df["cik"] == cik) & (
        financials_df["fiscal_year"] == fiscal_year
    )
    financials_df.loc[mask, column] = value
    return financials_df
