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


# A sample company-quarter with an M-Score but no F-Score (checked in the
# committed sample), to show the missing-score card.
MISSING_F = {"cik": 8858, "fiscal_year": 2027, "fiscal_quarter": 1}


def test_quarterly_company_page_shows_why_a_score_is_missing(sample_source):
    """In quarterly mode the company page draws one quarter: the note,
    a quarter picker starting on the quarter handed over, a card saying
    "Not enough quarterly data" for the missing F-Score, and the
    quarterly trace buttons in place of the annual ones."""
    app_test = run()
    basis_radio(app_test).set_value(basis.QUARTERLY)
    app_test = run(app_test)
    app_test.session_state["selected_cik"] = MISSING_F["cik"]
    app_test.session_state["selected_fiscal_year"] = MISSING_F["fiscal_year"]
    app_test.session_state["selected_fiscal_quarter"] = MISSING_F[
        "fiscal_quarter"
    ]
    app_test.switch_page("views/company.py")
    app_test.run()
    assert not app_test.exception
    assert not app_test.error
    assert basis.QUARTERLY_NOTE in [box.value for box in app_test.info]
    picker = next(s for s in app_test.selectbox if s.label == "Fiscal quarter")
    assert picker.value == (2027, 1)
    page_text = " ".join(m.value for m in app_test.markdown)
    assert basis.NOT_ENOUGH_DATA in page_text
    assert not [b for b in app_test.button if "Trace to the 10-K" in b.label]


def test_annual_company_page_keeps_its_trace_buttons(sample_source):
    """Annual mode (the default) still offers the three trace buttons."""
    app_test = run()
    app_test.switch_page("views/company.py")
    app_test.run()
    assert not app_test.exception
    assert len([b for b in app_test.button if "Trace" in b.label]) == 3


def open_quarterly_company(app_test=None):
    """Switch to Quarterly and open the MISSING_F company-quarter."""
    app_test = run(app_test)
    basis_radio(app_test).set_value(basis.QUARTERLY)
    app_test = run(app_test)
    app_test.session_state["selected_cik"] = MISSING_F["cik"]
    app_test.session_state["selected_fiscal_year"] = MISSING_F["fiscal_year"]
    app_test.session_state["selected_fiscal_quarter"] = MISSING_F[
        "fiscal_quarter"
    ]
    app_test.switch_page("views/company.py")
    app_test.run()
    return app_test


def test_quarterly_trace_tab_shows_the_quarters_and_filings(sample_source):
    """In quarterly mode the trace tab draws the quarterly panel: the
    inputs table and the quarters-and-filings table, with no error."""
    app_test = open_quarterly_company()
    assert not app_test.exception
    assert not app_test.error
    page_text = " ".join(m.value for m in app_test.markdown)
    assert "Inputs (trailing twelve months, or quarter-end values)" in (
        page_text
    )
    assert "The quarters and filings behind each input" in page_text
    assert len(app_test.dataframe) >= 2


def test_quarterly_trace_buttons_open_the_quarterly_pop_up(sample_source):
    """Each card has a quarterly trace button, and clicking one opens
    the pop-up without an error."""
    app_test = open_quarterly_company()
    buttons = [b for b in app_test.button if "Trace to the filings" in b.label]
    assert len(buttons) == 3
    buttons[0].click()
    app_test.run()
    assert not app_test.exception
    assert not app_test.error


def test_quarterly_company_page_draws_the_price_chart(sample_source):
    """The quarterly company page draws the price chart heading and its
    diamond caption without an error (the company has prices)."""
    app_test = open_quarterly_company()
    assert not app_test.exception
    page_text = " ".join(m.value for m in app_test.markdown)
    assert "Stock price, 10-K and quarterly warnings" in page_text
    captions = " ".join(c.value for c in app_test.caption)
    assert "Diamonds: quarterly (TTM) scores" in captions


def test_deep_link_opens_quarterly_mode_once(sample_source):
    """?basis=quarterly&quarter=3 on the company page opens quarterly
    mode on FY2015 Q3; the parameters are removed once read."""
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=60)
    app_test.query_params["basis"] = "quarterly"
    app_test.query_params["cik"] = "1336917"
    app_test.query_params["year"] = "2015"
    app_test.query_params["quarter"] = "3"
    app_test.switch_page("views/company.py")
    app_test.run()
    assert not app_test.exception
    assert basis_radio(app_test).value == basis.QUARTERLY
    picker = next(s for s in app_test.selectbox if s.label == "Fiscal quarter")
    assert picker.value == (2015, 3)
    assert "basis" not in app_test.query_params


def test_about_page_has_the_quarterly_section(sample_source):
    """The About page explains quarterly scores, with the note."""
    app_test = run()
    app_test.switch_page("views/about.py")
    app_test.run()
    assert not app_test.exception
    assert "Quarterly (TTM) scores" in [h.value for h in app_test.subheader]
    assert basis.QUARTERLY_NOTE in [w.value for w in app_test.warning]
