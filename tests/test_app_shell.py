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


def screener_count_text(app_test):
    """Return the "N of M companies ... match" line on the screener."""
    return next(
        md.value
        for md in app_test.markdown
        if "match your filters" in md.value
    )


def test_screener_defaults_to_latest_year_and_shows_all(fixture_source):
    """Fixture FY2023: all 3 scored companies shown, riskiest first."""
    app_test = run_app()
    assert app_test.selectbox(key="screener_year").value == 2023
    assert screener_count_text(app_test).startswith("**3** of 3")
    table = app_test.dataframe[0].value
    assert list(table["Company"]) == ["Stretch Co", "Steady Co", "Service Co"]


def test_screener_cutoff_slider_changes_warnings(fixture_source):
    """Lowering the cutoff below Stretch Co's -2.66 adds its 3rd concern."""
    app_test = run_app()
    app_test.slider(key="screener_cutoff").set_value(-2.70).run()
    table = app_test.dataframe[0].value.set_index("Company")
    assert table.loc["Stretch Co", "Concerns"] == 3
    assert table.loc["Stretch Co", labels.CHECK_NAMES["m"]] == "🔴 Warning"


def test_screener_empty_filter_shows_message(fixture_source):
    """Filters that match nothing explain how to widen them."""
    app_test = run_app()
    app_test.multiselect(key="screener_zones").set_value(["grey"]).run()
    assert screener_count_text(app_test).startswith("**0** of 3")
    assert "No companies match" in app_test.warning[0].value
    assert not app_test.dataframe


def test_filters_survive_a_trip_to_another_page(fixture_source):
    """Leaving the screener and coming back keeps the analyst's filters."""
    app_test = run_app()
    app_test.slider(key=data.SCREENER_CUTOFF).set_value(-2.70).run()
    app_test.switch_page("views/about.py").run()
    app_test.switch_page("views/screener.py").run()
    assert app_test.slider(key=data.SCREENER_CUTOFF).value == -2.70


def test_company_page_opens_on_screener_choice(fixture_source):
    """A company chosen in the screener opens with its verdict."""
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
    app_test.session_state[data.SELECTED_CIK] = 102
    app_test.session_state[data.SELECTED_YEAR] = 2023
    app_test.run()
    app_test.switch_page("views/company.py").run()
    assert not app_test.exception
    assert app_test.selectbox(key=data.SELECTED_CIK).value == 102
    subheaders = [header.value for header in app_test.subheader]
    assert subheaders[0].startswith("2 of 3 checks raised concerns")
    assert labels.SCOPE_NOTE in [caption.value for caption in app_test.caption]


def test_company_page_uses_screener_cutoff(fixture_source):
    """The card agrees with the screener when the cutoff is moved."""
    app_test = run_app()
    app_test.slider(key=data.SCREENER_CUTOFF).set_value(-2.70).run()
    app_test.session_state[data.SELECTED_CIK] = 102
    app_test.session_state[data.SELECTED_YEAR] = 2023
    app_test.switch_page("views/company.py").run()
    assert app_test.subheader[0].value.startswith("3 of 3")


def test_company_page_runs_for_every_company_year(fixture_source):
    """No company-year in the fixture crashes the page."""
    scores_df = pd.read_parquet(config.APP_FIXTURE_DIR / "scores.parquet")
    for cik, year in zip(scores_df["cik"], scores_df["fiscal_year"]):
        app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
        app_test.session_state[data.SELECTED_CIK] = int(cik)
        app_test.session_state[data.SELECTED_YEAR] = int(year)
        app_test.run()
        app_test.switch_page("views/company.py").run()
        assert not app_test.exception, (cik, year)


def open_company(cik, fiscal_year):
    """Return the app showing one fixture company-year's detail page."""
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
    app_test.session_state[data.SELECTED_CIK] = cik
    app_test.session_state[data.SELECTED_YEAR] = fiscal_year
    app_test.run()
    app_test.switch_page("views/company.py").run()
    return app_test


def test_trace_tab_shows_inputs_and_filing_links(fixture_source):
    """The trace tab lists the M-Score inputs with EDGAR links."""
    app_test = open_company(102, 2023)
    trace_table = next(
        frame.value
        for frame in app_test.dataframe
        if "XBRL tag" in frame.value.columns
    )
    assert (
        trace_table["Filing"]
        .str.startswith("https://www.sec.gov/Archives/edgar/data/102/")
        .all()
    )
    assert "Restated to $700,000,000" in " ".join(trace_table["Later filings"])


def test_trace_button_opens_the_panel(fixture_source):
    """Each card has a trace button, and clicking it opens the trace."""
    app_test = open_company(102, 2023)
    before = len(app_test.dataframe)
    app_test.button(key="trace_button_z_score").click().run()
    assert not app_test.exception
    assert len(app_test.dataframe) == before + 1


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
