"""Tests for src/pipeline/sample.py and run_pipeline.py."""

import pandas as pd

import config
import run_pipeline
from src.pipeline import sample


def make_profiles(rows):
    """Build profiles (cik, division, years, prices, full, stopped),
    sorted the way company_profiles sorts them."""
    profiles = pd.DataFrame(
        rows,
        columns=[
            "cik",
            "sic_division",
            "passing_years",
            "has_prices",
            "has_full_price_history",
            "stopped_filing",
        ],
    )
    return profiles.sort_values(
        ["passing_years", "cik"], ascending=[False, True]
    ).reset_index(drop=True)


# 6 full-history companies in divisions 2 and 3, 2 stopped, 1 partial.
PROFILES = make_profiles(
    [
        (1, 2, 14, True, True, False),
        (2, 2, 13, True, True, False),
        (3, 2, 12, True, True, False),
        (4, 3, 11, True, True, False),
        (5, 3, 10, True, True, False),
        (6, 3, 9, True, True, False),
        (7, 4, 5, False, False, True),
        (8, 5, 4, False, False, True),
        (9, 7, 3, True, False, False),
    ]
)


def test_round_robin_alternates_divisions():
    """Divisions take turns: 2, 3, 2, 3 rather than 2, 2, 2, 3."""
    full = PROFILES[PROFILES["has_full_price_history"]]
    assert sample.round_robin_by_division(full, 4) == [1, 4, 2, 5]


def test_anchor_and_extras_always_first():
    """Apple-style anchors and case-study extras come first, once each."""
    ciks = sample.select_sample_ciks(
        PROFILES, size=5, anchors=[6], extras=[999, 6]
    )
    assert ciks[:2] == [6, 999]
    assert len(ciks) == len(set(ciks))


def test_every_kind_of_company_is_represented(monkeypatch):
    """With small quotas the sample still has each edge case."""
    monkeypatch.setattr(sample, "QUOTA_FULL_HISTORY", 2)
    monkeypatch.setattr(sample, "QUOTA_STOPPED_NO_PRICES", 1)
    monkeypatch.setattr(sample, "QUOTA_PARTIAL_PRICES", 1)
    ciks = sample.select_sample_ciks(PROFILES, size=6, anchors=[], extras=[])
    assert ciks[:4] == [1, 4, 7, 9]  # full, full, stopped, partial
    assert len(ciks) == 6  # topped up from the remaining companies


def test_selection_is_deterministic():
    """Shuffled input gives the same sample after the standard sort."""
    rows = PROFILES.sample(frac=1, random_state=3).itertuples(index=False)
    shuffled = make_profiles([tuple(row) for row in rows])
    assert sample.select_sample_ciks(
        shuffled, anchors=[], extras=[]
    ) == sample.select_sample_ciks(PROFILES, anchors=[], extras=[])


def test_sample_tables_keep_only_sample_companies_and_spy():
    """Tables are cut to the CIKs; prices keep their tickers plus SPY."""
    tables = {
        "companies": pd.DataFrame({"cik": [1, 2], "ticker": ["AAA", None]}),
        "facts_long": pd.DataFrame({"cik": [1, 2, 2]}),
        "financials_annual": pd.DataFrame({"cik": [1, 2]}),
        "prices": pd.DataFrame({"ticker": ["AAA", "BBB", "SPY"]}),
    }
    cut = sample.sample_tables(tables, [1])
    assert cut["facts_long"]["cik"].tolist() == [1]
    assert sorted(cut["prices"]["ticker"]) == [
        "AAA",
        config.MARKET_BENCHMARK_TICKER,
    ]


def test_pipeline_runs_stages_in_order(monkeypatch):
    """--skip-download skips the SEC download and price download."""
    calls = []
    monkeypatch.setattr(
        run_pipeline,
        "run_stage",
        lambda name, function, *a, **k: calls.append((name, k)),
    )
    run_pipeline.main(["--skip-download"])
    names = [name for name, _ in calls]
    assert names == [
        "2. companies",
        "3. facts_long",
        "4. financials_annual",
        "5. prices",
        "6. sample",
    ]
    assert calls[3][1] == {"download": False}


def test_sample_only_runs_just_the_sample(monkeypatch):
    """--sample-only touches nothing but data/sample/."""
    calls = []
    monkeypatch.setattr(
        run_pipeline,
        "run_stage",
        lambda name, function, *a, **k: calls.append(name),
    )
    run_pipeline.main(["--sample-only"])
    assert calls == ["6. sample"]


def test_tieout_traces_value_to_original_fact():
    """The sheet shows the stored value and the original fact behind it;
    a later restated fact is not used."""
    from src.pipeline import tieout

    end = pd.Timestamp("2024-12-31")
    financials_df = pd.DataFrame(
        {
            "cik": [1],
            "fiscal_year": [2024],
            "period_end": [end],
            "revenue": [500e6],
        }
    )
    facts_long_df = pd.DataFrame(
        {
            "cik": [1, 1],
            "line_item": ["revenue", "revenue"],
            "is_original": [True, False],
            "period_end": [end, end],
            "xbrl_tag": ["Revenues", "Revenues"],
            "form": ["10-K", "10-K"],
            "accession": ["A1", "A2"],
            "filed_date": pd.to_datetime(["2025-02-01", "2026-02-01"]),
            "filing_url": ["url1", "url2"],
        }
    )
    sheet = tieout.build_tieout(
        financials_df, facts_long_df, {1: "Test Co"}, 2024, ["revenue"]
    )
    row = sheet.iloc[0]
    assert row["pipeline_value_millions"] == 500.0
    assert row["accession"] == "A1"
    assert row["matches"] == ""
