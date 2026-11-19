"""Run the dashboard headlessly on the fixture data and check the shell.

Streamlit's AppTest executes the real app/app.py script without a
browser, so these tests catch a page that crashes before the demo does.
"""

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import config
from app import data, labels

APP_SCRIPT = str(config.PROJECT_ROOT / "app" / "app.py")
VIEW_PAGES = [
    "views/screener.py",
    "views/company.py",
    "views/case_studies.py",
    "views/about.py",
]


@pytest.fixture
def fixture_source(monkeypatch):
    """Point the app at tests/fixtures/app/ with an empty cache."""
    monkeypatch.setattr(config, "APP_DATA_SOURCE", "fixture")
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def run_app(page=None):
    """Run the app (optionally switching to one page) and return it."""
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
    app_test.run()
    if page is not None:
        app_test.switch_page(page)
        app_test.run()
    return app_test


@pytest.mark.parametrize("page", VIEW_PAGES)
def test_every_page_runs_without_error(fixture_source, page):
    """Each page draws on the fixture data without raising."""
    app_test = run_app(page)
    assert not app_test.exception
    assert not app_test.error


def test_sidebar_names_the_data_source(fixture_source):
    """The analyst can always see which data the screens are built on."""
    app_test = run_app()
    sidebar_notes = [box.value for box in app_test.sidebar.info]
    assert labels.DATA_SOURCE_NOTES["fixture"] in sidebar_notes


def test_screener_counts_come_from_the_tables(fixture_source):
    """Fixture: 3 companies scored, FY2021 to FY2023, 2 excluded."""
    metrics = {m.label: m.value for m in run_app().metric}
    assert metrics["Companies scored"] == "3"
    assert metrics["Fiscal years"] == "2021 to 2023"
    assert metrics["Companies left out of scoring"] == "2"


def test_bad_data_source_shows_message_not_crash(monkeypatch):
    """A typo in EQR_DATA_SOURCE gives a readable error, not a traceback."""
    monkeypatch.setattr(config, "APP_DATA_SOURCE", "smaple")
    app_test = run_app()
    assert not app_test.exception
    assert "cannot find its data" in app_test.sidebar.error[0].value


def test_company_facts_reads_only_that_company():
    """load_company_facts returns one company's rows, in contract types."""
    all_facts_df = pd.read_parquet(
        config.APP_FIXTURE_DIR / "facts_long.parquet"
    )
    one_company_df = data.load_company_facts(config.APP_FIXTURE_DIR, 102)
    assert set(one_company_df["cik"]) == {102}
    assert len(one_company_df) == (all_facts_df["cik"] == 102).sum()
    pd.testing.assert_series_equal(one_company_df.dtypes, all_facts_df.dtypes)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1_234_000_000, "$1.2B"),
        (750_000_000, "$750.0M"),
        (-50_000_000, "-$50.0M"),
        (2_500, "$2.5K"),
        (999, "$999"),
        (float("nan"), "Not available"),
        (pd.NA, "Not available"),
        (None, "Not available"),
    ],
)
def test_format_money(value, expected):
    """Compact dollars; missing is "Not available", never "$0"."""
    assert labels.format_money(value) == expected


def test_format_number_handles_missing_and_infinite():
    """Ratios show two decimals; blanks and infinities are not shown."""
    assert labels.format_number(-1.78) == "-1.78"
    assert labels.format_number(float("nan")) == "Not available"
    assert labels.format_number(float("inf")) == "Not available"
