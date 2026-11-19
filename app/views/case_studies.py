"""Case studies page: did the warning signs show up before known events?

Step 2 placeholder; built in Phase 3 step 6 from data/case_studies.csv.
"""

import streamlit as st

st.title("Case studies")
st.markdown(
    "Companies with a documented accounting problem, such as an SEC "
    "enforcement action or a major restatement, and what the radar "
    "showed in the years before it became public, including cases the "
    "radar missed."
)

st.info(
    "Case studies arrive in a later build step.",
    icon=":material/construction:",
)
