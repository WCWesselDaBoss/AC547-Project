"""What the company page says in quarterly (TTM) mode.

The annual page's own functions (app/company_view.py) build the cards,
sentences and tables; this module only adds what differs for a quarter:
the quarter picker, the "not enough quarterly data" wording, the
trailing-twelve-month header and peer sentence, and the same-quarter
history the trend charts use. Nothing here computes a score.

Pure Python and pandas, no Streamlit, so pytest checks every sentence.
"""

from app import basis, company_view, labels, screening
from src.scores import peers


def company_quarters(scores_quarterly_df, cik, cutoff):
    """Return one company's quarterly scores rows, oldest first, with the
    M flag and concern count at the analyst's cutoff (the same Phase 2
    functions as the annual page, via screening.apply_cutoff)."""
    rows = scores_quarterly_df[scores_quarterly_df["cik"] == cik]
    rows = rows.sort_values("period_end")
    return screening.apply_cutoff(rows, cutoff).reset_index(drop=True)


def period_choices(company_quarters_df):
    """Return the company's scored (fiscal_year, fiscal_quarter) pairs,
    latest first, for the quarter picker."""
    return basis.quarter_options(company_quarters_df)


def same_quarter_history(company_quarters_df, fiscal_quarter):
    """Return the company's rows for one fiscal quarter across years
    (e.g. every Q3). Quarterly scores compare a quarter with the same
    quarter a year earlier, and with one row per fiscal year the annual
    trend charts work unchanged."""
    rows = company_quarters_df[
        company_quarters_df["fiscal_quarter"] == fiscal_quarter
    ]
    return rows.sort_values("fiscal_year").reset_index(drop=True)


def quarterly_cards(row, cutoff):
    """Return the three verdict cards for a quarterly row: the annual
    cards, except that a check without a score says why in quarterly
    terms (basis.NOT_ENOUGH_DATA), never a blank card."""
    cards = company_view.verdict_cards(row, cutoff)
    return [
        (
            card._replace(
                verdict=basis.NOT_ENOUGH_DATA_SHORT,
                detail=f"{basis.NOT_ENOUGH_DATA}.",
            )
            if card.status == company_view.NOT_SCORED
            else card
        )
        for card in cards
    ]


def quarterly_summary(row):
    """Return the one-line answer above the cards, for a quarter."""
    concerns = row[screening.CONCERNS_AT_CUTOFF]
    if labels.is_missing(concerns):
        return f"{basis.NOT_ENOUGH_DATA} for any of the three checks."
    return company_view.verdict_summary(row)


def ttm_sentence(row):
    """Return what a quarter's numbers are: the trailing twelve months to
    the quarter end, as first reported, and the date they were complete
    (available_date: the latest filing among the score's inputs)."""
    return (
        f"Trailing twelve months ending "
        f"{company_view.long_date(row['period_end'])} "
        f"({basis.period_label(row['fiscal_year'], row['fiscal_quarter'])}),"
        " from 10-Q and 10-K filings as first reported; available on "
        f"{company_view.long_date(row['available_date'])}, the filing date "
        "of the latest input."
    )


def quarterly_peer_description(row):
    """Return who the company is compared with, for a quarter: peers are
    companies at the same fiscal year and quarter."""
    count = int(row["peer_group_size"])
    if row["peer_group_level"] == peers.LEVEL_INDUSTRY_SIZE:
        return (
            f"Compared with {count} similar-sized companies in its "
            f"industry ({row['peer_group']}) in the same fiscal quarter."
        )
    return (
        f"Compared with {count} companies in its industry "
        f"({row['peer_group']}) in the same fiscal quarter. Too few were "
        "of a similar size to compare by size as well."
    )


def quarter_drivers(drivers_quarterly_df, cik, fiscal_year, fiscal_quarter):
    """Return the stored driver sentences for one company-quarter, ranked
    (company_view.driver_sentences on that quarter's rows)."""
    rows = basis.one_quarter(drivers_quarterly_df, fiscal_year, fiscal_quarter)
    return company_view.driver_sentences(rows, cik, fiscal_year)


def no_driver_message(row):
    """Return why there are no driver sentences for this company-quarter
    (company_view.no_driver_message, worded for a quarter)."""
    if labels.is_missing(row["m_score"]):
        return (
            f"{basis.NOT_ENOUGH_DATA} for the earnings manipulation score, so "
            "there is nothing to explain."
        )
    return (
        "None of the eight measures pushed the earnings manipulation "
        "score up this quarter."
    )


def peer_sentences(row):
    """Return {score: sentence} from the stored percentile ranks
    (company_view.peer_sentences), worded for a quarter."""
    return {
        score: sentence.replace("this year", "this quarter")
        for score, sentence in company_view.peer_sentences(row).items()
    }


def unscored_note(cards):
    """Return the note on checks without a score (company_view.
    unscored_note), giving the quarterly reason."""
    note = company_view.unscored_note(cards)
    if note is None:
        return None
    return note.replace(
        "because an input was not reported",
        "because there is not enough quarterly data",
    )
