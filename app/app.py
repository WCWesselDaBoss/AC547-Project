"""Earnings Quality Radar: the Streamlit entry point.

Run from the project root:  streamlit run app/app.py

This file sets up the page, the shared style, the sidebar and the page
navigation. Each page lives in app/views/ and only loads, filters and
draws finished tables (CLAUDE.md section 3).
"""

import sys
from pathlib import Path

# Streamlit puts app/ at the front of the import path. The project root
# must come BEFORE it, or "import app" finds this file (app/app.py)
# instead of the app package. Moving the root to the front, even when it
# is already on the path further back (as with "python -m streamlit
# run"), keeps the import right however the app is started.
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
while PROJECT_ROOT in sys.path:
    sys.path.remove(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

import streamlit as st  # noqa: E402

from app import data, labels, style  # noqa: E402

st.set_page_config(
    page_title=labels.APP_TITLE,
    page_icon=":material/radar:",
    layout="wide",
)
style.apply_style()
# Before any page draws, so filters survive a trip between pages.
data.keep_widget_state()

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
    company_count = data.scores()["cik"].nunique()
    st.info(
        labels.data_source_note(source, company_count),
        icon=":material/database:",
    )

navigation.run()
