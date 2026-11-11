"""Tests for src/pipeline/companies.py using small fixture JSON files.

Fixture companies (tests/fixtures/sec/):
    1  SIC 3571, 10-K in recent filings             -> included
    2  SIC 6022 (bank), 10-K                        -> excluded, financial
    3  SIC 3711, 10-K only in an overflow file      -> included
    4  blank SIC, files 20-F (foreign)              -> excluded, two reasons
    5  SIC 6770 (blank check), 10-K/A, no ticker    -> excluded, financial
    6  SIC 3571, 10-K, but companyfacts file is {}  -> excluded, no facts
"""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline import companies

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sec"


def zip_fixture_folder(folder, zip_path):
    """Pack every JSON file in a fixture folder into a ZIP, like SEC's."""
    with zipfile.ZipFile(zip_path, "w") as archive:
        for json_path in sorted(folder.glob("*.json")):
            archive.write(json_path, arcname=json_path.name)
    return zip_path


@pytest.fixture
def companies_result(tmp_path):
    """Build the companies table from the fixture ZIPs."""
    facts_zip = zip_fixture_folder(
        FIXTURE_DIR / "companyfacts", tmp_path / "companyfacts.zip"
    )
    subs_zip = zip_fixture_folder(
        FIXTURE_DIR / "submissions", tmp_path / "submissions.zip"
    )
    return companies.build_companies(facts_zip, subs_zip)


@pytest.mark.parametrize(
    "sic, expected",
    [(5999, False), (6000, True), (6770, True), (6799, True), (6800, False)],
)
def test_financial_sic_boundaries(sic, expected):
    """Both ends of 6000-6799 are excluded; neighbors are not."""
    assert companies.is_financial_sic(sic) is expected


@pytest.mark.parametrize(
    "raw, expected", [("3571", 3571), ("", None), (None, None), ("abc", None)]
)
def test_parse_sic(raw, expected):
    """SIC text becomes an int; blank or junk becomes None."""
    assert companies.parse_sic(raw) == expected


def test_pick_ticker_never_guesses():
    """First listed ticker is used; no tickers means None."""
    assert companies.pick_ticker(["GOOGL", "GOOG"]) == "GOOGL"
    assert companies.pick_ticker([]) is None
    assert companies.pick_ticker(None) is None


def test_pick_ticker_skips_warrants_and_preferreds():
    """Hertz lists its warrant first; preferred-only companies get None."""
    assert companies.pick_ticker(["HTZWW", "HTZ"]) == "HTZ"
    assert companies.pick_ticker(["CTA-PB", "CTA-PA"]) is None
    assert companies.pick_ticker(["XYZ-WT", "XYZ"]) == "XYZ"


@pytest.mark.parametrize(
    "ticker, expected",
    [
        ("AAPL", True),
        ("BRK-B", True),  # share class B is common stock
        ("SNOW", True),  # 4 letters ending in W: ordinary common
        ("HTZWW", False),  # Nasdaq warrant
        ("ABCDU", False),  # Nasdaq unit
        ("ABCDR", False),  # Nasdaq right
        ("TRTN-PA", False),  # preferred series A
        ("XYZ-WT", False),  # NYSE warrant
    ],
)
def test_is_common_stock_ticker(ticker, expected):
    """Common stock passes; warrants, units, rights, preferreds do not."""
    assert companies.is_common_stock_ticker(ticker) is expected


def test_exclusion_reasons_lists_every_reason():
    """A company failing two rules gets both reasons."""
    assert companies.exclusion_reasons(None, False) == [
        companies.REASON_MISSING_SIC,
        companies.REASON_NO_10K,
    ]
    assert companies.exclusion_reasons(3571, True) == []


def test_columns_match_section_4_contract(companies_result):
    """Exactly the contract columns, in order, and no helper columns."""
    companies_df, _ = companies_result
    assert list(companies_df.columns) == [
        "cik",
        "name",
        "sic",
        "sic_description",
        "ticker",
        "is_excluded",
        "exclusion_reason",
    ]


def test_every_companyfacts_cik_is_kept(companies_result):
    """Excluded companies are labeled, never dropped."""
    companies_df, _ = companies_result
    assert companies_df["cik"].tolist() == [1, 2, 3, 4, 5, 6]


def test_fixture_exclusions(companies_result):
    """Each fixture company gets the expected flag and reason."""
    companies_df, _ = companies_result
    by_cik = companies_df.set_index("cik")
    assert not by_cik.loc[1, "is_excluded"]
    assert by_cik.loc[2, "exclusion_reason"] == "financial_sic_6000_6799"
    assert by_cik.loc[4, "exclusion_reason"] == "missing_sic; no_10k_filings"
    assert by_cik.loc[5, "exclusion_reason"] == "financial_sic_6000_6799"
    assert by_cik.loc[6, "exclusion_reason"] == "no_xbrl_facts"


def test_overflow_file_finds_older_10k(companies_result):
    """A 10-K only in an overflow file still counts (company 3)."""
    companies_df, _ = companies_result
    row = companies_df.set_index("cik").loc[3]
    assert not row["is_excluded"]
    assert pd.isna(row["exclusion_reason"])


def test_missing_values_are_null_not_blank(companies_result):
    """Blank SIC, description and ticker are stored as null."""
    companies_df, _ = companies_result
    row = companies_df.set_index("cik").loc[4]
    assert pd.isna(row["sic"])
    assert pd.isna(row["sic_description"])
    assert pd.isna(row["ticker"])


def test_summary_counts(companies_result):
    """Log counts: 6 companies, 4 excluded, 2 included, 1 multi-ticker."""
    summary = companies.summarize_exclusions(*companies_result)
    counts = dict(zip(summary["measure"], summary["count"]))
    assert counts["companies_with_xbrl_facts"] == 6
    assert counts["excluded_total"] == 4
    assert counts["included_total"] == 2
    assert counts["reason:financial_sic_6000_6799"] == 2
    assert counts["reason:missing_sic"] == 1
    assert counts["reason:no_10k_filings"] == 1
    assert counts["reason:no_xbrl_facts"] == 1
    assert counts["included_without_ticker"] == 0
    assert counts["included_with_multiple_tickers"] == 1


def test_empty_facts_file_is_detected(tmp_path):
    """Only the file holding "{}" is reported as having no facts."""
    facts_zip = zip_fixture_folder(
        FIXTURE_DIR / "companyfacts", tmp_path / "companyfacts.zip"
    )
    assert companies.find_ciks_without_facts(facts_zip) == {6}


def test_no_facts_reason_comes_first():
    """A company with no facts is labeled even if other rules pass."""
    assert companies.exclusion_reasons(3571, True, has_facts=False) == [
        companies.REASON_NO_XBRL_FACTS
    ]
