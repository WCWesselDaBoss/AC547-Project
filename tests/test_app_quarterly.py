"""Run the dashboard headlessly on the committed sample and check the
annual/quarterly switch (Part 2 of the quarterly upgrade).

The sample (data/sample/) is used because the test fixtures have no
quarterly tables; that case is checked too (the switch is hidden)."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import config
from app import basis

APP_SCRIPT = str(config.PROJECT_ROOT / "app" / "app.py")


@pytest.fixture
def sample_source(monkeypatch):
    """Point the app at data/sample/ with an empty cache."""
    monkeypatch.setattr(config, "APP_DATA_SOURCE", "sample")
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def fixture_source(monkeypatch):
    """Point the app at tests/fixtures/app/ (no quarterly tables)."""
    monkeypatch.setattr(config, "APP_DATA_SOURCE", "fixture")
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def run(app_test=None):
    """Run (or re-run) the app on the screener and return it."""
    app_test = app_test or AppTest.from_file(APP_SCRIPT, default_timeout=60)
    app_test.run()
    return app_test


def basis_radio(app_test):
    """Return the sidebar's Scores radio."""
    return next(r for r in app_test.sidebar.radio if r.label == "Scores")


def test_annual_is_the_default(sample_source):
    """A new session starts on Annual: the radio says so, no quarterly
    note is shown, and the screener picks a fiscal year."""
    app_test = run()
    assert not app_test.exception
    assert basis_radio(app_test).value == basis.ANNUAL
    assert basis.QUARTERLY_NOTE not in [w.value for w in app_test.warning]
    assert [s.label for s in app_test.selectbox][0] == "Fiscal year"


def test_quarterly_screener_runs_with_its_note(sample_source):
    """Switching to Quarterly shows the required note in the sidebar and
    on the page, a quarter picker (latest first), and no error."""
    app_test = run()
    basis_radio(app_test).set_value(basis.QUARTERLY)
    app_test = run(app_test)
    assert not app_test.exception
    assert not app_test.error
    assert basis.QUARTERLY_NOTE in [w.value for w in app_test.sidebar.warning]
    assert basis.QUARTERLY_NOTE in [box.value for box in app_test.info]
    picker = app_test.selectbox[0]
    assert picker.label == "Fiscal quarter"
    first = picker.options[0]
    assert first.startswith("FY") and " Q" in first
    assert any(
        basis.NOT_ENOUGH_DATA in caption.value for caption in app_test.caption
    )


def test_switch_hidden_without_quarterly_tables(fixture_source):
    """The fixture data has no quarterly tables: no radio, a short note,
    and annual mode works as before."""
    app_test = run()
    assert not app_test.exception
    assert not [r for r in app_test.sidebar.radio if r.label == "Scores"]
    assert any(
        "Quarterly scores are not in this data source" in c.value
        for c in app_test.sidebar.caption
    )
