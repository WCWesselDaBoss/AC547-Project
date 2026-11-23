"""Tests for the company page's quarterly wording (app/company_quarterly.py)."""

import pandas as pd

from app import basis, company_quarterly, company_view
from src.scores import peers


def quarter_rows():
    """One company, Q3 and Q4 of FY2023 and Q3 of FY2024 (made up)."""
    return pd.DataFrame(
        {
            "cik": 1,
            "fiscal_year": [2023, 2023, 2024],
            "fiscal_quarter": [3, 4, 3],
            "period_end": pd.to_datetime(
                ["2023-09-30", "2023-12-31", "2024-09-30"]
            ),
            "available_date": pd.to_datetime(
                ["2023-11-01", "2024-02-20", "2024-11-01"]
            ),
            "m_score": [-2.5, float("nan"), -1.0],
            "m_flag": pd.array([False, pd.NA, True], dtype="boolean"),
            "z_zone": pd.array(["safe", pd.NA, "grey"], dtype="string"),
            "z_score": [3.0, float("nan"), 2.0],
            "f_band": pd.array(["strong", pd.NA, pd.NA], dtype="string"),
            "f_score": pd.array([8, pd.NA, pd.NA], dtype="Int64"),
            "flags_raised": pd.array([0, pd.NA, 1], dtype="Int64"),
            "peer_group": "SIC 35 large",
            "peer_group_level": peers.LEVEL_INDUSTRY_SIZE,
            "peer_group_size": 12,
        }
    )


def test_quarters_are_listed_latest_first():
    """The picker offers FY2024 Q3 first."""
    history = company_quarterly.company_quarters(quarter_rows(), 1, -1.78)
    assert company_quarterly.period_choices(history) == [
        (2024, 3),
        (2023, 4),
        (2023, 3),
    ]


def test_trend_history_is_the_same_quarter_across_years():
    """For Q3, the trend uses FY2023 Q3 and FY2024 Q3 only."""
    history = company_quarterly.company_quarters(quarter_rows(), 1, -1.78)
    same = company_quarterly.same_quarter_history(history, 3)
    assert same["fiscal_year"].tolist() == [2023, 2024]


def test_missing_quarterly_score_cards_say_not_enough_data():
    """FY2024 Q3 has an M-Score and a Z'' zone but no F-Score: the F card
    says why in quarterly terms; the scored cards are the annual ones."""
    history = company_quarterly.company_quarters(quarter_rows(), 1, -1.78)
    row = history.iloc[-1]
    cards = company_quarterly.quarterly_cards(row, -1.78)
    annual = company_view.verdict_cards(row, -1.78)
    assert cards[:2] == annual[:2]
    assert cards[2].status == company_view.NOT_SCORED
    assert cards[2].verdict == basis.NOT_ENOUGH_DATA_SHORT
    assert cards[2].detail == (
        "Not enough quarterly data (needs four complete quarters this "
        "year and last)."
    )


def test_summary_when_no_check_has_a_score():
    """FY2023 Q4 has no scores at all: the headline says not enough
    quarterly data, never a blank."""
    history = company_quarterly.company_quarters(quarter_rows(), 1, -1.78)
    row = history[history["fiscal_quarter"] == 4].iloc[0]
    assert company_quarterly.quarterly_summary(row).startswith(
        "Not enough quarterly data"
    )
    scored = history.iloc[-1]
    assert company_quarterly.quarterly_summary(scored) == (
        company_view.verdict_summary(scored)
    )


def test_header_and_peer_sentences():
    """The header names the trailing twelve months and its available
    date; peers are the same fiscal quarter."""
    row = company_quarterly.company_quarters(quarter_rows(), 1, -1.78).iloc[-1]
    assert company_quarterly.ttm_sentence(row) == (
        "Trailing twelve months ending September 30, 2024 (FY2024 Q3), "
        "from 10-Q and 10-K filings as first reported; available on "
        "November 1, 2024, the filing date of the latest input."
    )
    assert company_quarterly.quarterly_peer_description(row).endswith(
        "in the same fiscal quarter."
    )


def test_drivers_for_one_quarter():
    """Only the chosen quarter's driver rows are shown, ranked."""
    drivers = pd.DataFrame(
        {
            "cik": 1,
            "fiscal_year": [2024, 2024, 2024],
            "fiscal_quarter": [3, 3, 2],
            "driver_rank": [2, 1, 1],
            "component": ["SGI", "DSRI", "AQI"],
            "component_value": [1.3, 1.5, 1.2],
            "explanation": ["b", "a", "other quarter"],
        }
    )
    rows = company_quarterly.quarter_drivers(drivers, 1, 2024, 3)
    assert rows["explanation"].tolist() == ["a", "b"]


def test_quarterly_wording_says_this_quarter():
    """No M-Score: the drivers section says not enough quarterly data;
    an unranked score says "no score this quarter"."""
    history = company_quarterly.company_quarters(quarter_rows(), 1, -1.78)
    empty = history[history["fiscal_quarter"] == 4].iloc[0]
    assert company_quarterly.no_driver_message(empty) == (
        "Not enough quarterly data (needs four complete quarters this year "
        "and last) for the earnings manipulation score, so there is nothing "
        "to explain."
    )
    row = empty.copy()
    for score in company_view.PEER_SENTENCES:
        row[score] = float("nan")
        row[f"{score}_pctile"] = float("nan")
    sentences = company_quarterly.peer_sentences(row)
    assert set(sentences.values()) == {"Not ranked: no score this quarter."}
