"""What the About page says about quarterly (TTM) scores.

Every number is computed from the loaded scores_quarterly table, so the
page is always true for the data on screen. Pure pandas, no Streamlit.
"""

import pandas as pd

from app import about_view

QUARTERS_COLUMN = "Company-quarters with a score"


def quarterly_summary(scores_quarterly_df):
    """Return a dict describing the quarterly data on screen: companies,
    scored company-quarters, the latest quarter end and the latest date
    a quarterly score became available."""
    return {
        "companies": int(scores_quarterly_df["cik"].nunique()),
        "company_quarters": len(scores_quarterly_df),
        "latest_quarter_end": pd.Timestamp(
            scores_quarterly_df["period_end"].max()
        ),
        "latest_available": pd.Timestamp(
            scores_quarterly_df["available_date"].max()
        ),
    }


def quarterly_coverage_table(scores_quarterly_df):
    """Return how many scored company-quarters have each score (the
    annual coverage table, counted per quarter)."""
    table = about_view.coverage_table(scores_quarterly_df)
    return table.rename(
        columns={"Company-years with a score": QUARTERS_COLUMN}
    )
