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
from app.components import price_chart

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
    # The count is computed from the data: 3 scored fixture companies.
    assert labels.data_source_note("fixture", 3) in sidebar_notes


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


def test_case_page_shows_hit_and_steps_through_cases(fixture_source):
    """Fixture case 1 is a hit; Next moves to case 2, Previous back."""
    app_test = run_app("views/case_studies.py")
    assert not app_test.exception
    assert app_test.subheader[1].value == (
        "The earnings manipulation check warned before the event."
    )
    app_test.button(key="case_next").click().run()
    assert app_test.selectbox(key=data.CASE_INDEX).value == 1
    assert app_test.subheader[0].value == "Service Co"
    app_test.button(key="case_previous").click().run()
    assert app_test.selectbox(key=data.CASE_INDEX).value == 0


def test_every_real_case_runs_on_the_sample(monkeypatch):
    """Each case in data/case_studies.csv draws on the sample data."""
    monkeypatch.setattr(config, "APP_DATA_SOURCE", "sample")
    st.cache_data.clear()
    cases = pd.read_csv(config.CASE_STUDIES_PATH)
    for index in range(len(cases)):
        app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
        app_test.session_state[data.CASE_INDEX] = index
        app_test.run()
        app_test.switch_page("views/case_studies.py").run()
        assert not app_test.exception, cases.loc[index, "name"]
        assert not app_test.warning, cases.loc[index, "name"]
    st.cache_data.clear()


def test_about_page_uses_live_counts_and_sources(fixture_source):
    """About shows counts from the data and cites the three papers."""
    app_test = run_app("views/about.py")
    text = " ".join(md.value for md in app_test.markdown)
    assert "3 companies and 9 scored company-years" in text
    assert "February 20, 2024" in text
    for citation in ["Beneish, M. D. (1999)", "Altman, E. I. (2000)"]:
        assert citation in text
    assert "Piotroski, J. D. (2000)" in text


def test_company_page_explains_missing_charts(fixture_source):
    """Service Co has no M or F in any year: a message, not a blank chart."""
    app_test = open_company(103, 2023)
    infos = " ".join(box.value for box in app_test.info)
    assert "Earnings manipulation score (Beneish M-Score): not available" in (
        infos
    )
    assert "Financial strength score (Piotroski F-Score): not available" in (
        infos
    )
    assert "No peer ranks this year" in infos


def test_deep_link_opens_company_year_once(fixture_source):
    """?cik=102&year=2022 opens Stretch Co FY2022, then leaves the URL."""
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
    app_test.run()
    app_test.switch_page("views/company.py")
    app_test.query_params["cik"] = "102"
    app_test.query_params["year"] = "2022"
    app_test.run()
    assert app_test.selectbox(key=data.SELECTED_CIK).value == 102
    assert app_test.selectbox(key=data.SELECTED_YEAR).value == 2022
    assert "cik" not in app_test.query_params


def test_bad_deep_links_are_ignored(fixture_source):
    """A non-numeric or unknown link falls back instead of crashing."""
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
    app_test.run()
    app_test.switch_page("views/company.py")
    app_test.query_params["cik"] = "not-a-number"
    app_test.run()
    assert not app_test.exception
    app_test.switch_page("views/case_studies.py")
    app_test.query_params["case"] = "99"
    app_test.run()
    assert not app_test.exception
    assert app_test.selectbox(key=data.CASE_INDEX).value == 0


def test_deep_link_opens_a_case_by_number(fixture_source):
    """?case=2 opens the second case (counting from 1)."""
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
    app_test.run()
    app_test.switch_page("views/case_studies.py")
    app_test.query_params["case"] = "2"
    app_test.run()
    assert app_test.selectbox(key=data.CASE_INDEX).value == 1


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


def test_escape_markdown_stops_dollar_math():
    """A note with two dollar amounts must not render as a formula."""
    assert labels.escape_markdown("$408 million and $9 million") == (
        r"\$408 million and \$9 million"
    )


def test_price_chart_message_without_prices(fixture_source):
    """The fixture data has no prices file: the company page and the
    case page show the plain message, never a blank chart or an error."""
    for app_test in [
        open_company(103, 2023),
        run_app("views/case_studies.py"),
    ]:
        assert not app_test.exception
        infos = " ".join(box.value for box in app_test.info)
        assert price_chart.NO_DATA_MESSAGE in infos


def test_price_chart_draws_on_the_sample(monkeypatch):
    """On the sample (which has prices), Apple's company page shows the
    chart with its caption and the SPY toggle, off by default."""
    monkeypatch.setattr(config, "APP_DATA_SOURCE", "sample")
    st.cache_data.clear()
    app_test = AppTest.from_file(APP_SCRIPT, default_timeout=30)
    app_test.session_state[data.SELECTED_CIK] = 320193
    app_test.run()
    app_test.switch_page("views/company.py").run()
    assert not app_test.exception
    captions = " ".join(caption.value for caption in app_test.caption)
    assert price_chart.CAPTION in captions
    toggle = app_test.toggle(key="price_chart_spy_company")
    assert toggle.value is False
    toggle.set_value(True).run()
    assert not app_test.exception
    st.cache_data.clear()
