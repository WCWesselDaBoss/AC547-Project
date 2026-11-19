"""Earnings Quality Radar: the Streamlit entry point.

Run from the project root:  streamlit run app/app.py

This file sets up the page, the shared style, the sidebar and the page
navigation. Each page lives in app/views/ and only loads, filters and
draws finished tables (CLAUDE.md section 3).
"""

import sys
from pathlib import Path

# Streamlit puts app/ on the import path, not the project root, so add
# the root first: config and the app package are imported from there.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from app import data, labels, style  # noqa: E402

st.set_page_config(
    page_title=labels.APP_TITLE,
    page_icon=":material/radar:",
    layout="wide",
)
style.apply_style()

# Pages are grouped by what the analyst is doing: analyzing companies, or
# learning how the tool works and where it has been right or wrong.
VIEWS_DIR = Path(__file__).resolve().parent / "views"
PAGES = {
    "Analyze": [
        st.Page(
            VIEWS_DIR / "screener.py",
            title="Screener",
            icon=":material/filter_list:",
            default=True,
        ),
        st.Page(
            VIEWS_DIR / "company.py",
            title="Company detail",
            icon=":material/domain:",
            url_path="company",
        ),
    ],
    "Learn": [
        st.Page(
            VIEWS_DIR / "case_studies.py",
            title="Case studies",
            icon=":material/history_edu:",
            url_path="case-studies",
        ),
        st.Page(
            VIEWS_DIR / "about.py",
            title="About and limitations",
            icon=":material/info:",
            url_path="about",
        ),
    ],
}
navigation = st.navigation(PAGES)

with st.sidebar:
    st.markdown(f"### {labels.APP_TITLE}")
    st.caption(labels.APP_TAGLINE)
    try:
        source, data_dir = data.resolve_data_source()
    except (ValueError, FileNotFoundError) as error:
        # A readable message with the fix, instead of a stack trace in
        # front of the audience. st.stop ends the run so no page tries to
        # draw from data that is not there.
        st.error(
            f"The app cannot find its data. {error}\n\n"
            "Set EQR_DATA_SOURCE to auto, sample or fixture, or rebuild "
            "the tables with python run_pipeline.py."
        )
        st.stop()
    st.info(labels.DATA_SOURCE_NOTES[source], icon=":material/database:")

navigation.run()
