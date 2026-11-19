"""Tests for case-study logic (app/case_view.py) and the real case file.

Fixture case (tests/fixtures/app/case_studies.csv): Stretch Co, event
2023-06-30. Its FY2021 and FY2022 10-Ks were filed before (2022-02-20,
2023-02-20); FY2023 after (2024-02-20). FY2022's M-Score of -0.46 is
above the -1.78 cutoff. Service Co (event 2024-06-30) has no M-Score or
F-Score in any year (no cost of revenue).
"""

import pandas as pd
import pytest

import config
from app import case_view, screening
from tests.fixtures import build_app_fixtures


def read_fixture(table):
    """Read one app fixture table."""
    return pd.read_parquet(config.APP_FIXTURE_DIR / f"{table}.parquet")


def fixture_cases():
    """Return the fixture case table, typed."""
    return case_view.read_case_studies(
        pd.read_csv(config.APP_FIXTURE_DIR / "case_studies.csv")
    )


def history_for(cik, event_date, scores_df=None):
    """Return a fixture company's case history for an event date."""
    if scores_df is None:
        scores_df = read_fixture("scores")
    return case_view.case_history(
        scores_df,
        read_fixture("financials_annual"),
        cik,
        pd.Timestamp(event_date),
    )


def test_committed_fixture_case_file_matches_builder():
    """The fixture CSV equals what the builder script writes."""
    committed = pd.read_csv(config.APP_FIXTURE_DIR / "case_studies.csv")
    pd.testing.assert_frame_equal(
        committed, build_app_fixtures.build_case_studies_fixture()
    )


def test_read_case_studies_types_and_missing_columns():
    """Typed per section 4; a missing column is reported by name."""
    cases = fixture_cases()
    assert cases["cik"].dtype == "int64"
    assert cases.loc[0, "event_date"] == pd.Timestamp("2023-06-30")
    with pytest.raises(ValueError, match="source_url"):
        case_view.read_case_studies(pd.DataFrame({"cik": [1], "name": ["x"]}))


def test_before_event_uses_filing_date_not_year_end():
    """FY2022 ended 2022-12-31 and was filed 2023-02-20: before 2023-06-30.

    With an event on 2023-01-31, FY2022 ended before it but its 10-K was
    not yet filed, so it does not count.
    """
    history = history_for(102, "2023-06-30")
    assert history.loc[
        history[case_view.BEFORE_EVENT], "fiscal_year"
    ].tolist() == [2021, 2022]
    early = history_for(102, "2023-01-31")
    assert early.loc[
        early[case_view.BEFORE_EVENT], "fiscal_year"
    ].tolist() == [2021]


def test_hit_is_reported_with_its_years():
    """Stretch Co: M warned in FY2022, the one scored year before."""
    history = history_for(102, "2023-06-30")
    assert case_view.check_outcome(history, "m") == (
        case_view.HIT,
        [2022],
        1,
        2,
    )
    assert case_view.check_sentence(history, "m") == (
        "**Earnings manipulation risk:** warned in 1 of 1 year scored "
        "before the event (FY2022)."
    )
    assert case_view.headline(history) == (
        "The earnings manipulation check warned before the event."
    )


def test_miss_is_reported_plainly():
    """Z'' was scored (safe) both years before the event: a miss."""
    history = history_for(102, "2023-06-30")
    assert case_view.check_outcome(history, "z")[0] == case_view.MISS
    assert "the radar missed this case" in case_view.check_sentence(
        history, "z"
    )


def test_headline_says_miss_when_m_scored_without_warning():
    """Lower Stretch Co's FY2022 M-Score to -3.00: scored, no warning."""
    scores_df = read_fixture("scores")
    mask = (scores_df["cik"] == 102) & (scores_df["fiscal_year"] == 2022)
    scores_df.loc[mask, "m_score"] = -3.0
    history = history_for(102, "2023-06-30", scores_df)
    assert case_view.headline(history) == (
        "The earnings manipulation check did not warn before the event: "
        "a miss."
    )


def test_unscored_case_is_not_called_a_miss():
    """Service Co has no M-Score: "could not be scored", not "missed"."""
    history = history_for(103, "2024-06-30")
    assert case_view.check_outcome(history, "m")[0] == case_view.UNSCORED
    sentence = case_view.check_sentence(history, "m")
    assert sentence.startswith(
        "**Earnings manipulation risk:** could not be scored in any of "
        "the 3 years"
    )
    assert "missed" not in sentence


def test_event_before_any_filing():
    """An event before the first 10-K leaves nothing to test."""
    history = history_for(102, "2020-01-01")
    assert case_view.headline(history) == (
        "No 10-K in this data was filed before the event."
    )
    assert case_view.last_year_before_event(history) is None


def test_cases_use_published_cutoff_not_slider():
    """case_history always flags at config.BENEISH_FLAG_CUTOFF."""
    history = history_for(102, "2023-06-30")
    expected = history["m_score"] > config.BENEISH_FLAG_CUTOFF
    flagged = history[screening.M_FLAG_AT_CUTOFF]
    known = history["m_score"].notna()
    assert (flagged[known] == expected[known]).all()


def test_case_table_labels_before_and_after():
    """Each year says when its 10-K was filed relative to the event."""
    table = case_view.case_table(history_for(102, "2023-06-30"))
    assert list(table["When"]) == [
        "Before the event",
        "Before the event",
        "After the event",
    ]
    assert list(table["10-K filed"]) == [
        "2022-02-20",
        "2023-02-20",
        "2024-02-20",
    ]


# ---------------------------------------------------------------------------
# The real, hand-curated case file (data/case_studies.csv)
# ---------------------------------------------------------------------------
def test_real_case_file_follows_the_contract():
    """Section 4 columns, ISO dates, SEC source links, unique CIKs."""
    raw = pd.read_csv(config.CASE_STUDIES_PATH)
    cases = case_view.read_case_studies(raw)
    assert list(raw.columns) == case_view.CASE_COLUMNS
    assert cases["source_url"].str.startswith("https://www.sec.gov/").all()
    assert not cases["cik"].duplicated().any()
    assert cases["note"].notna().all()


def test_every_case_company_is_in_the_sample():
    """The sample rebuild picked up every case CIK (CLAUDE.md section 4)."""
    cases = case_view.read_case_studies(pd.read_csv(config.CASE_STUDIES_PATH))
    sample_scores = pd.read_parquet(config.SAMPLE_DIR / "scores.parquet")
    assert set(cases["cik"]) <= set(sample_scores["cik"])


def test_distress_warning_alone_is_not_a_hit():
    """A distress warning does not make the headline a hit.

    Fixture: blank Stretch Co's M-Score (so no M warning) and put FY2022
    in the distress zone; the headline must still not claim a catch.
    """
    scores_df = read_fixture("scores")
    mask = (scores_df["cik"] == 102) & (scores_df["fiscal_year"] == 2022)
    scores_df.loc[mask, "m_score"] = float("nan")
    scores_df.loc[mask, "z_zone"] = "distress"
    history = history_for(102, "2023-06-30", scores_df)
    assert case_view.check_outcome(history, "z")[0] == case_view.HIT
    assert (
        case_view.headline(history) == case_view.HEADLINES[case_view.UNSCORED]
    )


def test_single_year_wording():
    """One scored year reads "in the 1 year", not "in any of the 1 year"."""
    scores_df = read_fixture("scores")
    mask = (scores_df["cik"] == 102) & (scores_df["fiscal_year"] == 2022)
    scores_df.loc[mask, "m_score"] = -3.0
    history = history_for(102, "2023-06-30", scores_df)
    assert case_view.check_sentence(history, "m") == (
        "**Earnings manipulation risk:** no warning in the 1 year scored "
        "before the event. On this check, the radar missed this case."
    )
