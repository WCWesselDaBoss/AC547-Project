"""Turn one company's rows into what the company page says.

Pure Python and pandas, no Streamlit, so every sentence the page shows
is tested. Nothing here calculates a score: verdicts restate the scores
table, the M-Score flag at the analyst's cutoff comes from
screening.apply_cutoff (Phase 2's own function), driver sentences are
shown exactly as stored, and peer sentences read the stored percentiles.
"""

from collections import namedtuple

import pandas as pd

import config
from app import labels, screening
from src.scores import peers

# Card status keys, matching style.STATUS_COLORS. Amber ("warning") is
# used for the in-between verdicts (Z'' grey zone, F-Score middle band),
# which do NOT count as concerns in flags_raised (CLAUDE.md section 4).
GOOD, CAUTION, CONCERN, NOT_SCORED = "good", "warning", "critical", "none"

VerdictCard = namedtuple("VerdictCard", "title status verdict detail")

Z_ZONE_STATUS = {"safe": GOOD, "grey": CAUTION, "distress": CONCERN}
F_BAND_STATUS = {"strong": GOOD, "middle": CAUTION, "weak": CONCERN}
F_SCORE_MAX = screening.F_SCORE_RANGE[1]
CHECK_COUNT = len(labels.CHECK_NAMES)

# Peer sentence openings: (when at or above the middle, when below it).
# The percentile is in the raw score's direction (CLAUDE.md section 4: a
# high m_score_pctile means more risk; a high z or f percentile,
# stronger). Below the middle, "more than 0%" reads badly, so the
# opposite phrase is used with 100 minus the percentile. That is exact:
# ties count as half on both sides, so the two shares add to 100.
PEER_SENTENCES = {
    "m_score": (
        "Shows more earnings-manipulation warning signs than",
        "Shows fewer earnings-manipulation warning signs than",
    ),
    "z_score": (
        "Further from financial distress than",
        "Closer to financial distress than",
    ),
    "f_score": ("Financially stronger than", "Financially weaker than"),
    "accruals_ratio": (
        "Less of its profit backed by cash than",
        "More of its profit backed by cash than",
    ),
    "cash_conversion": (
        "Turns more of its profit into cash than",
        "Turns less of its profit into cash than",
    ),
}
PERCENTILE_MIDDLE = 50
PERCENTILE_TOP = 100
PEER_SCORE_NAMES = {
    "m_score": "Earnings manipulation (M-Score)",
    "z_score": "Financial distress (Z''-Score)",
    "f_score": "Financial strength (F-Score)",
    "accruals_ratio": "Accruals ratio",
    "cash_conversion": "Cash conversion",
}


def company_label(name, ticker):
    """Return "Apple Inc. (AAPL)", or just the name when no ticker."""
    if labels.is_missing(ticker):
        return str(name)
    return f"{name} ({ticker})"


def company_choices(companies_df, scores_df):
    """Return {cik: label} for every company with a scores row, by name."""
    scored = companies_df[companies_df["cik"].isin(scores_df["cik"])]
    scored = scored.sort_values("name")
    return {
        int(cik): company_label(name, ticker)
        for cik, name, ticker in zip(
            scored["cik"], scored["name"], scored["ticker"]
        )
    }


def company_scores(scores_df, cik, cutoff):
    """Return one company's scores rows, by year, flagged at cutoff."""
    rows = scores_df[scores_df["cik"] == cik].sort_values("fiscal_year")
    return screening.apply_cutoff(rows, cutoff).reset_index(drop=True)


def m_card(row, cutoff):
    """Return the earnings manipulation card for one company-year row."""
    title = labels.CHECK_NAMES["m"]
    if labels.is_missing(row["m_score"]):
        return VerdictCard(
            title,
            NOT_SCORED,
            labels.NO_SCORE,
            "An input the M-Score needs was not reported in the 10-K.",
        )
    flagged = bool(row[screening.M_FLAG_AT_CUTOFF])
    position = "above" if flagged else "at or below"
    return VerdictCard(
        title,
        CONCERN if flagged else GOOD,
        labels.M_FLAG_LABELS[flagged],
        f"M-Score {row['m_score']:.2f} is {position} the warning cutoff "
        f"of {cutoff:.2f}.",
    )


def z_card(row):
    """Return the financial distress card for one company-year row."""
    title = labels.CHECK_NAMES["z"]
    if labels.is_missing(row["z_zone"]):
        return VerdictCard(
            title,
            NOT_SCORED,
            labels.NO_SCORE,
            "An input the Z''-Score needs was not reported in the 10-K.",
        )
    return VerdictCard(
        title,
        Z_ZONE_STATUS[row["z_zone"]],
        labels.Z_ZONE_LABELS[row["z_zone"]],
        f"Z''-Score {row['z_score']:.2f}. Below "
        f"{config.ALTMAN_Z2_DISTRESS_BELOW:.2f} is the distress zone; "
        f"above {config.ALTMAN_Z2_SAFE_ABOVE:.2f} is safe.",
    )


def f_card(row):
    """Return the financial strength card for one company-year row."""
    title = labels.CHECK_NAMES["f"]
    if labels.is_missing(row["f_band"]):
        return VerdictCard(
            title,
            NOT_SCORED,
            labels.NO_SCORE,
            "An input the F-Score needs was not reported in the 10-K.",
        )
    return VerdictCard(
        title,
        F_BAND_STATUS[row["f_band"]],
        labels.F_BAND_LABELS[row["f_band"]],
        f"F-Score {row['f_score']} of {F_SCORE_MAX} tests passed. "
        f"{config.F_SCORE_WEAK_MAX} or fewer is weak; "
        f"{config.F_SCORE_STRONG_MIN} or more is strong.",
    )


def verdict_cards(row, cutoff):
    """Return the three verdict cards, in the order the page shows them."""
    return [m_card(row, cutoff), z_card(row), f_card(row)]


def verdict_summary(row):
    """Return the one-line answer shown above the cards.

    Kept to one short line so a non-expert gets the answer at a glance;
    unscored checks are reported by unscored_note underneath. Uses the
    concern count at the analyst's cutoff, and never says a company will
    fail or is a bad investment: concerns are "warning signs worth
    investigating" (Phase 3 brief).
    """
    concerns = row[screening.CONCERNS_AT_CUTOFF]
    if labels.is_missing(concerns):
        return "None of the three checks could be scored for this year."
    concerns = int(concerns)
    if concerns == 0:
        return f"None of the {CHECK_COUNT} checks raised concerns."
    # "1 of 3 checks", not "1 of 3 check": the noun counts the 3.
    return (
        f"{concerns} of {CHECK_COUNT} checks raised concerns: warning "
        "signs worth investigating."
    )


def unscored_note(cards):
    """Return a note on checks that could not be scored, or None.

    None when every check was scored, and also when none was (the
    headline already says so).
    """
    unscored = sum(card.status == NOT_SCORED for card in cards)
    if unscored in (0, len(cards)):
        return None
    noun = "check" if unscored == 1 else "checks"
    return (
        f"{unscored} {noun} could not be scored, because an input was not "
        "reported; see the cards below."
    )


def driver_sentences(drivers_df, cik, fiscal_year):
    """Return the stored score_drivers rows for one company-year, ranked.

    Returns a DataFrame with component and explanation, exactly as Phase
    2 stored them (the dashboard never writes its own explanation).
    """
    rows = drivers_df[
        (drivers_df["cik"] == cik) & (drivers_df["fiscal_year"] == fiscal_year)
    ]
    return rows.sort_values("driver_rank")[
        ["driver_rank", "component", "component_value", "explanation"]
    ].reset_index(drop=True)


def no_driver_message(row):
    """Return why there are no driver sentences for this company-year."""
    if labels.is_missing(row["m_score"]):
        return (
            "There is no earnings manipulation score this year, so there "
            "is nothing to explain."
        )
    return (
        "None of the eight measures pushed the earnings manipulation "
        "score up this year."
    )


def missing_input_sentences(row):
    """Return plain-English sentences for this row's missing_inputs."""
    if labels.is_missing(row["missing_inputs"]):
        return []
    codes = row["missing_inputs"].split("; ")
    return [labels.describe_missing_input(code) for code in codes]


def peer_description(row):
    """Return who the company is compared with, in one sentence.

    Shown once above the peer sentences, which then just say "its peers".
    """
    count = int(row["peer_group_size"])
    if row["peer_group_level"] == peers.LEVEL_INDUSTRY_SIZE:
        return (
            f"Compared with {count} similar-sized companies in its "
            f"industry ({row['peer_group']}) in the same year."
        )
    return (
        f"Compared with {count} companies in its industry "
        f"({row['peer_group']}) in the same year. Too few were of a "
        "similar size to compare by size as well."
    )


def peer_sentences(row):
    """Return {score: sentence} built from the stored percentile ranks.

    A blank percentile is explained rather than hidden: either the score
    itself is blank, or no other company in the group has that score.
    """
    sentences = {}
    for score, (above, below) in PEER_SENTENCES.items():
        percentile = row[peers.percentile_column(score)]
        if labels.is_missing(row[score]):
            sentences[score] = "Not ranked: no score this year."
        elif labels.is_missing(percentile):
            sentences[score] = (
                "Not ranked: no other company in its peer group has this "
                "score this year."
            )
        elif percentile >= PERCENTILE_MIDDLE:
            sentences[score] = f"{above} {percentile:.0f}% of its peers."
        else:
            share = PERCENTILE_TOP - percentile
            sentences[score] = f"{below} {share:.0f}% of its peers."
    return sentences


def small_peer_group(row):
    """Return True when the ranking rests on fewer peers than the floor."""
    return int(row["peer_group_size"]) < config.MIN_PEER_GROUP_SIZE


def m_index_table(row):
    """Return the eight M-Score indexes with plain names and values."""
    return pd.DataFrame(
        {
            "Measure": list(labels.M_INDEX_LABELS.values()),
            "Value": [row[column] for column in labels.M_INDEX_LABELS],
        }
    )


def z_ratio_table(row):
    """Return the four Z''-Score ratios with plain names and values."""
    return pd.DataFrame(
        {
            "Ratio": list(labels.Z_RATIO_LABELS.values()),
            "Value": [row[column] for column in labels.Z_RATIO_LABELS],
        }
    )


def f_signal_table(row):
    """Return the nine F-Score tests with a yes / no / cannot-tell result."""
    results = []
    for column in labels.F_SIGNAL_LABELS:
        value = row[column]
        if labels.is_missing(value):
            results.append(labels.SIGNAL_UNDETERMINED)
        else:
            results.append(labels.SIGNAL_RESULT_LABELS[bool(value)])
    return pd.DataFrame(
        {"Test": list(labels.F_SIGNAL_LABELS.values()), "Result": results}
    )


def filing_sentence(filings_df, cik, fiscal_year):
    """Return which 10-K a year's numbers come from, or None if unknown.

    For a comparative-only year, filed_date is the later 10-K that first
    reported it (CLAUDE.md section 4), so the wording says "first
    reported in", which is true in both cases.
    """
    match = filings_df[
        (filings_df["cik"] == cik) & (filings_df["fiscal_year"] == fiscal_year)
    ]
    if match.empty:
        return None
    filing = match.iloc[0]
    return (
        f"Fiscal year ended {long_date(filing['period_end'])}; numbers as "
        f"first reported in the 10-K filed {long_date(filing['filed_date'])} "
        f"(accession {filing['accession']})."
    )


def long_date(date):
    """Return e.g. "November 1, 2024" (no leading zero on the day)."""
    return f"{date:%B} {date.day}, {date:%Y}"
