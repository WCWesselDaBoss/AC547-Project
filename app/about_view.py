"""Figures for the About page, computed from the tables on screen.

Coverage numbers are calculated from the loaded data every time rather
than typed into the page, so they are always true for the data source
in use (fixture, sample or full) and never go stale after a refresh
(CLAUDE.md section 6: no hard-coded numbers).
"""

import pandas as pd

from app import labels

# Scores whose coverage the About page reports, with plain names.
COVERED_SCORES = {
    "m_score": labels.CHECK_NAMES["m"],
    "z_score": labels.CHECK_NAMES["z"],
    "f_score": labels.CHECK_NAMES["f"],
    "accruals_ratio": labels.COLUMN_LABELS["accruals_ratio"],
    "cash_conversion": labels.COLUMN_LABELS["cash_conversion"],
}

# Neutral substitutions allowed by CLAUDE.md section 5, by note code.
NEUTRAL_NOTES = {
    "sgai_set_to_1": "SGAI set to neutral (SG&A not reported)",
    "lvgi_set_to_1": "LVGI set to neutral (long-term debt not reported)",
    "f_leverage_down_no_point": (
        "F-Score debt test given no point (long-term debt not reported)"
    ),
}


def data_summary(scores_df, filings_df):
    """Return a dict describing the data on screen.

    latest_filing is the most recent 10-K filing date among scored
    company-years, so the analyst knows how current the data is.
    """
    scored = filings_df.merge(
        scores_df[["cik", "fiscal_year"]], on=["cik", "fiscal_year"]
    )
    return {
        "companies": int(scores_df["cik"].nunique()),
        "company_years": len(scores_df),
        "first_year": int(scores_df["fiscal_year"].min()),
        "last_year": int(scores_df["fiscal_year"].max()),
        "latest_filing": scored["filed_date"].max(),
    }


def percent(part, whole):
    """Return part / whole as text like "42%" (or "0%" for no rows)."""
    if whole == 0:
        return "0%"
    return f"{part / whole:.0%}"


def coverage_table(scores_df):
    """Return how many scored company-years have each score."""
    total = len(scores_df)
    rows = []
    for column, name in COVERED_SCORES.items():
        has_score = int(scores_df[column].notna().sum())
        rows.append(
            {
                "Score": name,
                "Company-years with a score": f"{has_score:,} of {total:,}",
                "Share": percent(has_score, total),
            }
        )
    return pd.DataFrame(rows)


def neutral_substitution_table(scores_df):
    """Return how often each neutral substitution was used."""
    total = len(scores_df)
    notes = scores_df["missing_inputs"].fillna("")
    rows = []
    for code, description in NEUTRAL_NOTES.items():
        # Match the whole code between "; " separators, not a substring.
        used = int(
            notes.str.split("; ").apply(lambda codes: code in codes).sum()
        )
        rows.append(
            {
                "Substitution": description,
                "Company-years": f"{used:,} of {total:,}",
                "Share": percent(used, total),
            }
        )
    return pd.DataFrame(rows)
