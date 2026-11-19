"""Reshape the finished tables for the screener page.

Pure pandas, no Streamlit, so every function is tested in pytest. Nothing
here calculates a score. Re-applying the analyst's M-Score cutoff (which
CLAUDE.md section 4 allows the slider to do) reuses Phase 2's own
functions, beneish.m_flag and verdicts.flags_raised, so the screener can
never disagree with the scores table about what a flag means.
"""

import pandas as pd

import config
from app import labels
from src.scores import beneish, verdicts

# Column names added by this module (the scores table's own columns keep
# their contract names).
M_FLAG_AT_CUTOFF = "m_flag_at_cutoff"
CONCERNS_AT_CUTOFF = "concerns_at_cutoff"
SIZE_BAND = "size_band"
INDUSTRY = "industry"

# Filter value for "this check has no score", so a blank can be chosen.
NO_SCORE_KEY = "no_score"

# The F-Score is nine one-point signals, so it runs from 0 to 9.
F_SCORE_RANGE = (0, 9)

# Results-table headings, in display order. Verdicts come right after
# the name, so they stay visible on a laptop screen; the long industry
# and size labels go last.
TABLE_COLUMNS = {
    "name": "Company",
    "ticker": "Ticker",
    CONCERNS_AT_CUTOFF: "Concerns",
    M_FLAG_AT_CUTOFF: labels.CHECK_NAMES["m"],
    "m_score": "M-Score",
    "z_zone": labels.CHECK_NAMES["z"],
    "z_score": "Z''-Score",
    "f_band": labels.CHECK_NAMES["f"],
    "f_score": "F-Score",
    INDUSTRY: "Industry",
    SIZE_BAND: "Size",
}


def apply_cutoff(scores_df, cutoff):
    """Return scores_df with the M flag and concern count at cutoff.

    At config.BENEISH_FLAG_CUTOFF these equal the stored m_flag and
    flags_raised columns exactly (tested), because the same Phase 2
    functions produce both.
    """
    screen_df = scores_df.copy()
    screen_df[M_FLAG_AT_CUTOFF] = beneish.m_flag(screen_df["m_score"], cutoff)
    screen_df[CONCERNS_AT_CUTOFF] = verdicts.flags_raised(
        screen_df[M_FLAG_AT_CUTOFF], screen_df["z_zone"], screen_df["f_band"]
    )
    return screen_df


def size_band(total_assets):
    """Return the config.APP_SIZE_BANDS label for each total-assets value.

    Missing total assets gets no band (NA), never a guess.
    """
    band = pd.Series(pd.NA, index=total_assets.index, dtype="string")
    for label, (low, high) in config.APP_SIZE_BANDS.items():
        band[(total_assets >= low) & (total_assets < high)] = label
    return band


def industry_label(sic, sic_description):
    """Return e.g. "Electronic Computers (SIC 3571)" for the filter."""
    if labels.is_missing(sic_description):
        return f"SIC {sic}"
    return f"{sic_description} (SIC {sic})"


def screen_table(scores_df, companies_df, financials_df, fiscal_year):
    """Return one row per scored company in fiscal_year, ready to filter.

    Adds the company name, ticker and industry (from companies) and the
    size band (from that year's total assets in financials_annual).
    """
    year_df = scores_df[scores_df["fiscal_year"] == fiscal_year]
    company_columns = ["cik", "name", "ticker", "sic", "sic_description"]
    year_df = year_df.merge(
        companies_df[company_columns], on="cik", how="left"
    )
    year_df = year_df.merge(
        financials_df[["cik", "fiscal_year", "total_assets"]],
        on=["cik", "fiscal_year"],
        how="left",
    )
    year_df[SIZE_BAND] = size_band(year_df["total_assets"])
    year_df[INDUSTRY] = [
        industry_label(sic, description)
        for sic, description in zip(year_df["sic"], year_df["sic_description"])
    ]
    return year_df


def _zone_key(z_zone):
    """Return z_zone with blanks replaced by NO_SCORE_KEY, for filtering."""
    return z_zone.astype("string").fillna(NO_SCORE_KEY)


def filter_screen(
    screen_df, industries=(), sizes=(), z_zones=(), f_range=F_SCORE_RANGE
):
    """Return the rows matching every filter.

    An empty selection means "no filter" for industries, sizes and zones.
    z_zones may include NO_SCORE_KEY to keep companies with no Z''.
    Companies with no F-Score are kept only while f_range is the full
    F_SCORE_RANGE: once the analyst narrows it, a blank score cannot be said
    to fall inside the range.
    """
    keep = pd.Series(True, index=screen_df.index)
    if industries:
        keep &= screen_df[INDUSTRY].isin(industries)
    if sizes:
        keep &= screen_df[SIZE_BAND].isin(sizes).fillna(False)
    if z_zones:
        keep &= _zone_key(screen_df["z_zone"]).isin(z_zones)
    low, high = f_range
    if (low, high) != F_SCORE_RANGE:
        in_range = screen_df["f_score"].between(low, high)
        keep &= in_range.fillna(False).astype(bool)
    return screen_df[keep]


def sort_by_risk(screen_df):
    """Return rows with the most concerns first.

    Order: concerns at the chosen cutoff (most first), then M-Score
    (highest first, the closest to or furthest past the cutoff), then
    company name so ties always list the same way. Blanks sort last.
    """
    return screen_df.sort_values(
        [CONCERNS_AT_CUTOFF, "m_score", "name"],
        ascending=[False, False, True],
        na_position="last",
    ).reset_index(drop=True)


def exclusion_counts(companies_df):
    """Return companies left out before scoring, counted by reason.

    A company can have several reasons (e.g. no SIC and no 10-K), so it
    is counted under each; the counts can add to more than the number of
    excluded companies. Returns a Series: plain-English reason -> count.
    """
    reasons = (
        companies_df.loc[companies_df["is_excluded"], "exclusion_reason"]
        .dropna()
        .str.split("; ")
        .explode()
    )
    counts = reasons.value_counts()
    counts.index = [
        labels.EXCLUSION_REASON_LABELS.get(code, code) for code in counts.index
    ]
    return counts


def below_size_floor_count(financials_df, companies_df, fiscal_year):
    """Return how many in-scope companies missed the size floor that year.

    These have a 10-K for the year but are not scored (CLAUDE.md
    section 2: revenue or total assets of at least config.SIZE_FLOOR_USD).
    """
    in_scope = companies_df.loc[~companies_df["is_excluded"], "cik"]
    year_rows = financials_df[
        (financials_df["fiscal_year"] == fiscal_year)
        & financials_df["cik"].isin(in_scope)
    ]
    return int((~year_rows["passes_size_floor"]).sum())


def blank_score_counts(screen_df):
    """Return {check name: number of companies without that score}."""
    return {
        labels.CHECK_NAMES["m"]: int(screen_df["m_score"].isna().sum()),
        labels.CHECK_NAMES["z"]: int(screen_df["z_score"].isna().sum()),
        labels.CHECK_NAMES["f"]: int(screen_df["f_score"].isna().sum()),
    }


def _never_blanks_a_score(code):
    """Return True for missing_inputs codes that leave M, Z'', F intact.

    CLAUDE.md section 5: missing SG&A and long-term debt set SGAI and
    LVGI to neutral and cost signal 5 its point, but the scores are still
    computed; non-positive net income only blanks cash conversion.
    """
    return (
        code.endswith("_set_to_1")
        or code.startswith(("sga_", "long_term_debt_"))
        or code in {"f_leverage_down_no_point", "net_income_not_positive"}
    )


def top_missing_reasons(screen_df, top_n=3):
    """Return the most common reasons a score is blank, in plain English.

    Looks only at companies missing at least one of the three scores,
    and skips codes that never blank M, Z'' or F (see
    _never_blanks_a_score). Returns a Series: sentence -> number of
    companies.
    """
    any_blank = screen_df[["m_score", "z_score", "f_score"]].isna().any(axis=1)
    codes = (
        screen_df.loc[any_blank, "missing_inputs"]
        .dropna()
        .str.split("; ")
        .explode()
    )
    codes = codes[~codes.map(_never_blanks_a_score).astype(bool)]
    counts = codes.value_counts().head(top_n)
    counts.index = [labels.describe_missing_input(c) for c in counts.index]
    return counts


def display_table(shown_df):
    """Return the results table with plain-English headings and verdicts.

    Verdicts become icon-and-word labels (labels.verdict_label); scores
    stay numbers so the table can still be sorted by clicking a heading.
    """
    display_df = shown_df[list(TABLE_COLUMNS)].copy()
    verdict_maps = {
        M_FLAG_AT_CUTOFF: labels.M_FLAG_LABELS,
        "z_zone": labels.Z_ZONE_LABELS,
        "f_band": labels.F_BAND_LABELS,
    }
    for column, labels_by_value in verdict_maps.items():
        display_df[column] = [
            labels.verdict_label(value, labels_by_value)
            for value in display_df[column]
        ]
    return display_df.rename(columns=TABLE_COLUMNS).reset_index(drop=True)
