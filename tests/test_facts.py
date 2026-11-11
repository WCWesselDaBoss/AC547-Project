"""Tests for src/pipeline/facts.py using one hand-built company.

Fixture company 10 (tests/fixtures/sec/facts_long/CIK0000000010.json):
  Revenues FY2023: 10-K (1,000, original), same-day 10-K/A (1,000), later
      comparative restated to 1,050; FY2024: 1,100.
  Dropped: a Q4-only value, a 10-Q, an FY2009 value, an instant revenue,
      a EUR value, and SalesRevenueNet (company prefers Revenues).
  Assets 2023 (original + comparative) and 2024.
  LiabilitiesAndStockholdersEquity 2024: kept as the component, dropped as
      a total_assets fallback because Assets is reported.
  CommonStockSharesOutstanding 2024 in shares.
Expected: 9 rows.
"""

import zipfile
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline import facts

FIXTURE = Path(__file__).parent / "fixtures" / "sec" / "facts_long"


@pytest.fixture
def built(tmp_path):
    """Build facts_long from the fixture company; return (table, drops)."""
    zip_path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for json_path in FIXTURE.glob("*.json"):
            archive.write(json_path, arcname=json_path.name)
    return facts.build_facts_long(zip_path, [10])


def rows_for(facts_long_df, line_item):
    """Return one line item's rows, oldest period and filing first."""
    return facts_long_df[facts_long_df["line_item"] == line_item]


def test_columns_and_types_match_contract(built):
    """Exact section 4 columns, in order, with the agreed types."""
    facts_long_df, _ = built
    assert list(facts_long_df.columns) == facts.FACTS_LONG_COLUMNS
    assert facts_long_df["cik"].dtype == "int64"
    assert facts_long_df["period_end"].dtype == "datetime64[ns]"
    assert facts_long_df["is_original"].dtype == "bool"


def test_row_count_and_items(built):
    """9 rows across four line items."""
    facts_long_df, _ = built
    counts = facts_long_df["line_item"].value_counts().to_dict()
    assert counts == {
        "revenue": 4,
        "total_assets": 3,
        "liabilities_and_equity": 1,
        "shares_outstanding": 1,
    }


def test_original_is_earliest_10k_not_amendment_or_restatement(built):
    """FY2023 revenue: only the first 10-K's 1,000 is original."""
    revenue = rows_for(built[0], "revenue")
    fy2023 = revenue[revenue["fiscal_year"] == 2023]
    originals = fy2023[fy2023["is_original"]]
    assert len(originals) == 1
    assert originals["form"].item() == "10-K"
    assert originals["value"].item() == 1000.0
    # The restated value is kept for the restatement feature.
    assert 1050.0 in fy2023["value"].tolist()


def test_exactly_one_original_per_period(built):
    """Every company, line item and period has one original value."""
    facts_long_df, _ = built
    per_period = facts_long_df.groupby(
        ["cik", "line_item", "period_start", "period_end"], dropna=False
    )["is_original"].sum()
    assert (per_period == 1).all()


def test_company_preferred_tag_only(built):
    """SalesRevenueNet is dropped; total_assets uses Assets only."""
    facts_long_df, _ = built
    assert set(rows_for(facts_long_df, "revenue")["xbrl_tag"]) == {"Revenues"}
    assert set(rows_for(facts_long_df, "total_assets")["xbrl_tag"]) == {
        "Assets"
    }


def test_instants_have_no_start_and_flows_do(built):
    """Balance sheet rows have NaT start; flow rows have a start date."""
    facts_long_df, _ = built
    assert rows_for(facts_long_df, "total_assets")["period_start"].isna().all()
    assert rows_for(facts_long_df, "revenue")["period_start"].notna().all()


def test_shares_keep_shares_unit(built):
    """shares_outstanding is the one line item counted in shares."""
    shares = rows_for(built[0], "shares_outstanding")
    assert shares["unit"].item() == "shares"
    assert shares["value"].item() == 100.0


def test_every_drop_is_counted(built):
    """Each removed fact appears in the drop counts with its reason."""
    _, drops = built
    assert drops[facts.DROP_FORM] == 1
    assert drops[facts.DROP_UNIT] == 1
    assert drops[facts.DROP_NOT_ANNUAL] == 1
    assert drops[facts.DROP_YEAR] == 1
    assert drops[facts.DROP_WRONG_UNIT_OR_PERIOD] == 1
    assert drops[facts.DROP_OTHER_TAG] == 2
    assert drops[facts.DROP_DUPLICATE] == 0


def test_filing_url_built_from_cik_and_accession():
    """Folder drops the dashes; CIK is not zero-padded in the path."""
    assert facts.edgar_filing_url(320193, "0000320193-26-000026") == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019326000026/0000320193-26-000026-index.htm"
    )


def test_fiscal_year_from_period_end_not_fy_field(built):
    """The fixture's fy field is 0 everywhere; years still come out right."""
    facts_long_df, _ = built
    assert set(facts_long_df["fiscal_year"]) == {2023, 2024}


def test_drop_log_includes_kept_counts(built):
    """The log reports kept rows and originals next to drop reasons."""
    log = facts.drop_log(*built)
    counts = dict(zip(log["measure"], log["count"]))
    assert counts["kept:rows"] == 9
    assert counts["kept:original_rows"] == 6
    assert counts[f"dropped:{facts.DROP_OTHER_TAG}"] == 2
    assert isinstance(log, pd.DataFrame)
