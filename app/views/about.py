"""About page: what the scores mean, where the data comes from, limits.

Step 2 shows the score descriptions; data sources and limitations are
added in Phase 3 step 7 (polish).
"""

import streamlit as st

from app import labels

st.title("About and limitations")
st.markdown(labels.APP_TAGLINE)
st.caption(labels.SCOPE_NOTE)

st.subheader("What each score measures")
for column, description in labels.SCORE_HELP.items():
    st.markdown(f"**{labels.COLUMN_LABELS[column]}.** {description}")

st.info(
    "Data sources and limitations arrive in a later build step.",
    icon=":material/construction:",
)
