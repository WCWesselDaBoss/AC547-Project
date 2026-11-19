"""Case studies: what the radar showed before a documented event.

Pure pandas, no Streamlit, so every sentence is tested. The question
each case answers is "would an analyst reading the 10-Ks have seen
warning signs before the problem became public?" The event date in
data/case_studies.csv is therefore the FIRST public disclosure of the
problem in a company filing, not the later SEC action (which is often
years after the problem was known). Two more rules keep the answer
honest:

- A year counts as "before the event" only if its 10-K was FILED before
  the event date (filed_date from financials_annual), not merely if the
  fiscal year ended before it: an analyst cannot read a 10-K that has
  not been filed yet.
- Cases use the published M-Score cutoff (config.BENEISH_FLAG_CUTOFF),
  never the screener slider, so no one can tune the cutoff until a case
  looks like a hit.

Each check ends in one of three outcomes, all reported: warned, scored
but no warning (a miss), or could not be scored.
"""

import pandas as pd

import config
from app import labels, screening

CASE_COLUMNS = [
    "cik",
    "name",
    "event_type",
    "event_date",
    "source_url",
    "note",
]
BEFORE_EVENT = "known_before_event"
WHEN_LABELS = {True: "Before the event", False: "After the event"}

# How each check signals a warning, and the column holding its score.
# (Same definitions as flags_raised, CLAUDE.md section 4.)
# .eq keeps a blank as blank (NA) instead of raising.
CHECKS = {
    "m": ("m_score", lambda df: df[screening.M_FLAG_AT_CUTOFF].eq(True)),
    "z": ("z_score", lambda df: df["z_zone"].eq("distress")),
    "f": ("f_score", lambda df: df["f_band"].eq("weak")),
}

HIT, MISS, UNSCORED, NO_YEARS = "hit", "miss", "unscored", "no_years"
HEADLINES = {
    HIT: "The earnings manipulation check warned before the event.",
    MISS: (
        "The earnings manipulation check did not warn before the event: "
        "a miss."
    ),
    UNSCORED: (
        "The earnings manipulation check could not score this company "
        "before the event, because key inputs were not reported."
    ),
    NO_YEARS: "No 10-K in this data was filed before the event.",
}
CONTEXT_NOTE = (
    "Distress and strength are shown for context only: they measure "
    "financial health, not manipulation, so a warning there is not "
    "counted as catching the case."
)


def read_case_studies(raw_df):
    """Return the case table with section 4 types, checking its columns.

    Raises ValueError naming any missing column, so a malformed CSV is
    reported instead of half-drawn.
    """
    missing = [c for c in CASE_COLUMNS if c not in raw_df.columns]
    if missing:
        raise ValueError(
            f"case_studies.csv is missing columns: {', '.join(missing)}"
        )
    cases_df = raw_df[CASE_COLUMNS].copy()
    cases_df["cik"] = cases_df["cik"].astype("int64")
    cases_df["event_date"] = pd.to_datetime(
        cases_df["event_date"], format="%Y-%m-%d"
    )
    for column in ["name", "event_type", "source_url", "note"]:
        cases_df[column] = cases_df[column].astype("string")
    return cases_df.reset_index(drop=True)


def case_history(scores_df, filings_df, cik, event_date):
    """Return one company's scored years, marked before / after the event.

    Adds filed_date (from financials_annual) and BEFORE_EVENT, and flags
    the M-Score at the published cutoff via screening.apply_cutoff.
    """
    history = scores_df[scores_df["cik"] == cik].merge(
        filings_df[["cik", "fiscal_year", "filed_date"]],
        on=["cik", "fiscal_year"],
        how="left",
    )
    history = screening.apply_cutoff(history, config.BENEISH_FLAG_CUTOFF)
    history[BEFORE_EVENT] = history["filed_date"] < event_date
    return history.sort_values("fiscal_year").reset_index(drop=True)


def check_outcome(history, check):
    """Return (outcome, warned fiscal years, scored count, year count).

    Looks only at years whose 10-K was filed before the event.
    """
    score_column, warns = CHECKS[check]
    before = history[history[BEFORE_EVENT]]
    if before.empty:
        return NO_YEARS, [], 0, 0
    scored = before[before[score_column].notna()]
    if scored.empty:
        return UNSCORED, [], 0, len(before)
    warned_mask = warns(scored).fillna(False).astype(bool)
    warned = [int(year) for year in scored.loc[warned_mask, "fiscal_year"]]
    outcome = HIT if warned else MISS
    return outcome, warned, len(scored), len(before)


def _years_text(years):
    """Return "FY2013, FY2015"."""
    return ", ".join(f"FY{year}" for year in years)


def _years(count):
    """Return "1 year" or "3 years"."""
    return f"{count} year" if count == 1 else f"{count} years"


def _in_any_of(count):
    """Return "in the 1 year" or "in any of the 3 years"."""
    if count == 1:
        return "in the 1 year"
    return f"in any of the {count} years"


def check_sentence(history, check):
    """Return one plain-English sentence on how a check did."""
    name = labels.CHECK_NAMES[check]
    outcome, warned, scored, total = check_outcome(history, check)
    if outcome == NO_YEARS:
        return f"**{name}:** no 10-K in this data was filed before the event."
    if outcome == UNSCORED:
        return (
            f"**{name}:** could not be scored {_in_any_of(total)} filed "
            "before the event, because inputs were "
            "not reported. The radar cannot speak to this case on this "
            "check."
        )
    if outcome == HIT:
        return (
            f"**{name}:** warned in {len(warned)} of {_years(scored)} "
            f"scored before the event ({_years_text(warned)})."
        )
    return (
        f"**{name}:** no warning {_in_any_of(scored)} scored before the "
        "event. On this check, the radar missed this case."
    )


def headline(history):
    """Return the one-line answer for a case, from the M-Score check.

    Only the earnings manipulation check is designed to flag accounting
    problems; distress and strength measure financial health, so a
    distress warning is not credited as catching an accounting scandal.
    The page shows those two checks as context.
    """
    outcome = check_outcome(history, "m")[0]
    return HEADLINES[outcome]


def case_table(history):
    """Return the year-by-year table shown for a case."""
    table = pd.DataFrame(
        {
            "Fiscal year": [f"FY{year}" for year in history["fiscal_year"]],
            "10-K filed": history["filed_date"].dt.strftime("%Y-%m-%d"),
            "When": history[BEFORE_EVENT].map(WHEN_LABELS),
            "Concerns": history[screening.CONCERNS_AT_CUTOFF],
            labels.CHECK_NAMES["m"]: [
                labels.verdict_label(value, labels.M_FLAG_LABELS)
                for value in history[screening.M_FLAG_AT_CUTOFF]
            ],
            "M-Score": history["m_score"],
            labels.CHECK_NAMES["z"]: [
                labels.verdict_label(value, labels.Z_ZONE_LABELS)
                for value in history["z_zone"]
            ],
            labels.CHECK_NAMES["f"]: [
                labels.verdict_label(value, labels.F_BAND_LABELS)
                for value in history["f_band"]
            ],
        }
    )
    return table.reset_index(drop=True)


def last_year_before_event(history):
    """Return the last fiscal year filed before the event, or None."""
    before = history[history[BEFORE_EVENT]]
    if before.empty:
        return None
    return int(before["fiscal_year"].max())
