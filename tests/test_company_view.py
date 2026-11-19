"""Tests for the company page's sentences, cards and charts.

Fixture companies (tests/fixtures/build_app_fixtures.py):
- 102 Stretch Co FY2022: M -0.46 (warning), Z'' safe, no F-Score;
  drivers DSRI, TATA, SGI. FY2023: M -2.66, Z'' distress, F 2 weak.
- 101 Steady Co FY2023: M -2.48, Z'' safe, F 4 middle.
- 103 Service Co: no M or F (no cost of revenue); alone in its industry.
"""

import pandas as pd
import pytest

import config
from app import charts, company_view, labels, style
from src.scores import explanations

DEFAULT_CUTOFF = config.BENEISH_FLAG_CUTOFF


def read_fixture(table):
    """Read one app fixture table."""
    return pd.read_parquet(config.APP_FIXTURE_DIR / f"{table}.parquet")


def fixture_row(cik, fiscal_year, cutoff=DEFAULT_CUTOFF):
    """Return one company-year from the fixture, flagged at cutoff."""
    history = company_view.company_scores(read_fixture("scores"), cik, cutoff)
    return history[history["fiscal_year"] == fiscal_year].iloc[0]


def test_company_choices_only_scored_companies_by_name():
    """Excluded companies (104, 105) cannot be picked; no ticker is fine."""
    choices = company_view.company_choices(
        read_fixture("companies"), read_fixture("scores")
    )
    assert choices == {
        103: "Service Co",
        101: "Steady Co (STDY)",
        102: "Stretch Co (STRC)",
    }


def test_cards_for_a_flagged_year():
    """Stretch Co FY2022: M warning, Z'' safe, F not scored."""
    row = fixture_row(102, 2022)
    m, z, f = company_view.verdict_cards(row, DEFAULT_CUTOFF)
    assert (m.status, m.verdict) == ("critical", "🔴 Warning")
    assert "-0.46 is above the warning cutoff of -1.78" in m.detail
    assert (z.status, z.verdict) == ("good", "🟢 Safe zone")
    assert (f.status, f.verdict) == ("none", labels.NO_SCORE)


def test_cards_for_distress_and_weak():
    """Stretch Co FY2023: Z'' distress and F weak are both concerns."""
    row = fixture_row(102, 2023)
    m, z, f = company_view.verdict_cards(row, DEFAULT_CUTOFF)
    assert m.status == "good"
    assert "at or below" in m.detail
    assert (z.status, f.status) == ("critical", "critical")
    assert f.detail.startswith("F-Score 2 of 9 tests passed.")


def test_grey_and_middle_are_caution_not_concern():
    """Middle F-Score is amber but not counted as a concern."""
    row = fixture_row(101, 2023)
    cards = company_view.verdict_cards(row, DEFAULT_CUTOFF)
    assert cards[2].status == "warning"
    assert company_view.verdict_summary(row) == (
        "None of the 3 checks raised concerns."
    )


@pytest.mark.parametrize(
    ("cik", "year", "expected"),
    [
        (
            102,
            2023,
            "2 of 3 checks raised concerns: warning signs worth "
            "investigating.",
        ),
        (
            102,
            2022,
            "1 of 3 checks raised concerns: warning signs worth "
            "investigating.",
        ),
        (
            103,
            2023,
            "None of the 3 checks raised concerns.",
        ),
    ],
)
def test_verdict_summary(cik, year, expected):
    """One line that counts concerns and admits unscored checks."""
    row = fixture_row(cik, year)
    cards = company_view.verdict_cards(row, DEFAULT_CUTOFF)
    assert company_view.verdict_summary(row) == expected


def test_summary_never_predicts_failure():
    """No forecasting or investment language in any summary or card."""
    banned = ["will fail", "bad investment", "fraud", "bankrupt"]
    scores_df = read_fixture("scores")
    for cik, year in zip(scores_df["cik"], scores_df["fiscal_year"]):
        row = fixture_row(cik, year)
        cards = company_view.verdict_cards(row, DEFAULT_CUTOFF)
        text = company_view.verdict_summary(row) + " ".join(
            card.verdict + card.detail for card in cards
        )
        assert not any(word in text.lower() for word in banned)


def test_stricter_cutoff_changes_card_and_summary():
    """At -2.70, Stretch Co FY2023 gets a third concern."""
    row = fixture_row(102, 2023, cutoff=-2.70)
    cards = company_view.verdict_cards(row, -2.70)
    assert cards[0].status == "critical"
    assert company_view.verdict_summary(row).startswith("3 of 3")


def test_driver_sentences_are_shown_exactly_as_stored():
    """Stretch Co FY2022: DSRI, TATA, SGI, with the approved sentences."""
    drivers_df = company_view.driver_sentences(
        read_fixture("score_drivers"), 102, 2022
    )
    assert list(drivers_df["component"]) == ["DSRI", "TATA", "SGI"]
    for component, sentence in zip(
        drivers_df["component"], drivers_df["explanation"]
    ):
        assert sentence == explanations.explain(component)


def test_no_driver_message_distinguishes_why():
    """No M-Score vs. an M-Score with nothing pushing it up."""
    no_score = company_view.no_driver_message(fixture_row(103, 2023))
    assert "no earnings manipulation score" in no_score
    assert company_view.driver_sentences(
        read_fixture("score_drivers"), 103, 2023
    ).empty


def test_missing_input_sentences():
    """Service Co lacks cost of revenue in both years."""
    sentences = company_view.missing_input_sentences(fixture_row(103, 2023))
    assert sentences == [
        "Cost of revenue not reported (this year)",
        "Cost of revenue not reported (prior year)",
    ]
    assert company_view.missing_input_sentences(fixture_row(101, 2023)) == []


def test_peer_sentences_follow_score_direction():
    """Steady Co FY2023 has the higher M of two peers: 100th percentile."""
    row = fixture_row(101, 2023)
    sentences = company_view.peer_sentences(row)
    assert sentences["m_score"] == (
        "Shows more earnings-manipulation warning signs than 100% of its "
        "peers."
    )
    assert company_view.peer_description(row) == (
        "Compared with 2 companies in its industry (SIC 35) in the same "
        "year. Too few were of a similar size to compare by size as well."
    )


def test_low_percentile_uses_the_opposite_phrase():
    """Stretch Co FY2023 is 0th on M: "fewer ... than 100%", not "0%"."""
    sentences = company_view.peer_sentences(fixture_row(102, 2023))
    assert sentences["m_score"] == (
        "Shows fewer earnings-manipulation warning signs than 100% of its "
        "peers."
    )


def test_percentile_phrasing_switches_at_the_middle():
    """50 uses the "above" phrase; 49 flips to "below" with 51."""
    row = fixture_row(101, 2023).copy()
    row["f_score_pctile"] = 50.0
    assert company_view.peer_sentences(row)["f_score"] == (
        "Financially stronger than 50% of its peers."
    )
    row["f_score_pctile"] = 49.0
    assert company_view.peer_sentences(row)["f_score"] == (
        "Financially weaker than 51% of its peers."
    )


def test_peer_sentences_explain_blank_ranks():
    """Service Co: no M-Score, and no other company in its group."""
    sentences = company_view.peer_sentences(fixture_row(103, 2023))
    assert sentences["m_score"] == "Not ranked: no score this year."
    assert sentences["z_score"].startswith(
        "Not ranked: no other company in its peer group"
    )
    assert company_view.small_peer_group(fixture_row(103, 2023))


def test_component_tables():
    """8 indexes, 4 ratios, 9 tests; undetermined tests say so."""
    row = fixture_row(102, 2022)
    assert len(company_view.m_index_table(row)) == 8
    assert len(company_view.z_ratio_table(row)) == 4
    signals = company_view.f_signal_table(row)
    assert len(signals) == 9
    assert labels.SIGNAL_UNDETERMINED in set(signals["Result"])


def test_filing_sentence_names_the_10k():
    """FY2023 fixture: year ended Dec 31, 2023, filed Feb 20, 2024."""
    sentence = company_view.filing_sentence(
        read_fixture("financials_annual"), 102, 2023
    )
    assert sentence == (
        "Fiscal year ended December 31, 2023; numbers as first reported "
        "in the 10-K filed February 20, 2024 (accession "
        "0000000102-24-000001)."
    )


def test_trend_chart_leaves_gaps_for_missing_years():
    """Stretch Co FY2021 has no M-Score: a gap, not a zero."""
    history = company_view.company_scores(
        read_fixture("scores"), 102, DEFAULT_CUTOFF
    )
    figure = charts.m_trend(history, 2023, DEFAULT_CUTOFF)
    y_values = list(figure.data[0].y)
    assert pd.isna(y_values[0])
    assert figure.data[0].connectgaps is False
    assert len(figure.data) == 1  # one series, one axis


def test_percentile_chart_omits_unranked_scores():
    """Service Co has only a Z'' with no peers ranked: no bars drawn."""
    figure = charts.percentile_figure(fixture_row(103, 2023))
    assert len(figure.data[0].x) == 0
    figure = charts.percentile_figure(fixture_row(101, 2023))
    assert 100.0 in list(figure.data[0].x)


def test_card_html_escapes_text():
    """A "<" or "&" in text cannot inject HTML into the page."""
    card = style.verdict_card_html("A & B", "good", "<b>x</b>", "ok")
    assert "A &amp; B" in card
    assert "&lt;b&gt;" in card


def test_unscored_note_sits_under_the_headline():
    """Unscored checks get their own short note, not the headline."""
    cards = company_view.verdict_cards(fixture_row(102, 2022), -1.78)
    assert company_view.unscored_note(cards) == (
        "1 check could not be scored, because an input was not reported; "
        "see the cards below."
    )
    full = company_view.verdict_cards(fixture_row(102, 2023), -1.78)
    assert company_view.unscored_note(full) is None
