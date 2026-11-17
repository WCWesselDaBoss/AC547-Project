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


# ---- Tag switch across filings (company 11, modeled on Analog Devices) -----
# The FY2017 and FY2018 10-Ks tag revenue as SalesRevenueNet. From the
# FY2019 10-K the company uses RevenueFromContractWith...ExcludingAssessed-
# Tax (ASC 606) and restates FY2017 to 5,246,354,000. The new tag is the
# company's preferred tag (4 fiscal years against 3), but the original
# FY2017 value must still be the 5,107,503,000 first reported.

REVENUE_606 = "RevenueFromContractWithCustomerExcludingAssessedTax"


@pytest.fixture
def tag_switch(tmp_path):
    """Build facts_long for fixture company 11 only."""
    zip_path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(
            FIXTURE / "CIK0000000011.json", arcname="CIK0000000011.json"
        )
    return facts.build_facts_long(zip_path, [11])


def revenue_rows(facts_long_df, fiscal_year):
    """Return company 11's revenue rows for one fiscal year."""
    revenue = rows_for(facts_long_df, "revenue")
    return revenue[revenue["fiscal_year"] == fiscal_year]


def test_original_comes_from_earliest_filing_across_tags(tag_switch):
    """FY2017 original = first 10-K's 5,107,503,000, not the restatement."""
    fy2017 = revenue_rows(tag_switch[0], 2017)
    original = fy2017[fy2017["is_original"]]
    assert original["value"].item() == 5_107_503_000
    assert original["xbrl_tag"].item() == "SalesRevenueNet"
    assert original["accession"].item() == "0000000011-17-000144"


def test_restated_value_kept_but_not_original(tag_switch):
    """The FY2019 10-K's restated 5,246,354,000 stays for restatements."""
    fy2017 = revenue_rows(tag_switch[0], 2017)
    restated = fy2017[fy2017["value"] == 5_246_354_000]
    assert restated["xbrl_tag"].item() == REVENUE_606
    assert not restated["is_original"].item()
    # One row per filing: FY2017, FY2018 and FY2019 10-Ks.
    assert len(fy2017) == 3


def test_preferred_tag_chosen_within_a_filing(tag_switch):
    """The FY2019 10-K reports FY2018 under both tags: its one row uses
    the company's preferred (ASC 606) tag, and the other is counted."""
    facts_long_df, drops = tag_switch
    fy2018 = revenue_rows(facts_long_df, 2018)
    in_2019_10k = fy2018[fy2018["accession"] == "0000000011-19-000144"]
    assert in_2019_10k["xbrl_tag"].tolist() == [REVENUE_606]
    assert drops[facts.DROP_OTHER_TAG] == 1
    # FY2018's original is still its own 10-K's value.
    original = fy2018[fy2018["is_original"]]
    assert original["accession"].item() == "0000000011-18-000101"


def test_one_original_per_period_after_tag_switch(tag_switch):
    """Every company, line item and period still has one original."""
    facts_long_df, _ = tag_switch
    per_period = facts_long_df.groupby(
        ["cik", "line_item", "period_start", "period_end"], dropna=False
    )["is_original"].sum()
    assert (per_period == 1).all()
    assert sorted(
        facts_long_df.loc[facts_long_df["is_original"], "fiscal_year"]
    ) == [2016, 2017, 2018, 2019, 2020]


# ---- Revenue tags that disagree within one filing (company 12) -------------
# Modeled on Apogee: from its FY2014 10-K on, a small figure is tagged
# Revenues next to the true total under SalesRevenueNet. Revenues is the
# preferred tag (tie on years, earlier in the map), so without the guard
# FY2014 revenue would be $72.7mm instead of $933.9mm.


@pytest.fixture
def revenue_conflict(tmp_path):
    """Build facts_long for fixture company 12 only."""
    zip_path = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(
            FIXTURE / "CIK0000000012.json", arcname="CIK0000000012.json"
        )
    return facts.build_facts_long(zip_path, [12])


def original_revenue(facts_long_df, fiscal_year):
    """Return the original revenue row for one fiscal year."""
    rows = revenue_rows(facts_long_df, fiscal_year)
    return rows[rows["is_original"]].iloc[0]


def test_conflicting_revenue_tags_use_the_larger(revenue_conflict):
    """$933.9mm is more than 3x $72.7mm in the same filing: use it."""
    row = original_revenue(revenue_conflict[0], 2014)
    assert row["value"] == 933_936_000
    assert row["xbrl_tag"] == "SalesRevenueNet"
    assert original_revenue(revenue_conflict[0], 2015)["value"] == 981_189_000


def test_modest_revenue_gap_keeps_preferred_tag(revenue_conflict):
    """1,000 vs 1,050 (5%) is not a conflict: preferred Revenues kept."""
    row = original_revenue(revenue_conflict[0], 2016)
    assert row["xbrl_tag"] == "Revenues"
    assert row["value"] == 1_000_000_000


def test_guard_counted_as_adjustment_not_drop(revenue_conflict):
    """FY2013 (in the FY2014 10-K), FY2014 and FY2015 were overridden."""
    facts_long_df, drops = revenue_conflict
    assert drops[facts.ADJUSTED_REVENUE_LARGEST] == 3
    log = facts.drop_log(facts_long_df, drops)
    assert facts.ADJUSTED_REVENUE_LARGEST in set(log["measure"])
    # FY2013's original is still its own 10-K's value.
    assert original_revenue(facts_long_df, 2013)["value"] == 771_445_000


def test_guard_only_touches_revenue():
    """Other line items keep the preferred-tag rule even with big gaps."""
    import pandas as pd

    rows = pd.DataFrame(
        {
            "cik": [1, 1],
            "line_item": ["cfo", "cfo"],
            "tag": ["A", "B"],
            "value": [10.0, 100.0],
            "period_start": [None, None],
            "period_end": [None, None],
            "accession": ["X", "X"],
        }
    )
    rank = pd.Series([0, 1])
    drops = facts.Counter()
    assert facts.apply_revenue_guard(rows, rank, drops).tolist() == [0, 1]
    assert drops[facts.ADJUSTED_REVENUE_LARGEST] == 0


def test_guard_works_when_rows_are_not_in_rank_order():
    """Real batches are not sorted by preference: the larger value must
    still win (regression test for a row-alignment crash)."""
    import pandas as pd

    rows = pd.DataFrame(
        {
            "cik": [1, 1, 2, 2],
            "line_item": ["revenue"] * 4,
            "tag": ["SalesRevenueNet", "Revenues", "Revenues", "Other"],
            "value": [933.9, 72.7, 50.0, 49.0],
            "period_start": [None] * 4,
            "period_end": [None] * 4,
            "accession": ["X", "X", "Y", "Y"],
        },
        index=[7, 3, 9, 1],
    )
    # Revenues preferred (rank 0) for company 1, listed second.
    rank = pd.Series([2, 0, 0, 1], index=[7, 3, 9, 1])
    drops = facts.Counter()
    new_rank = facts.apply_revenue_guard(rows, rank, drops)
    assert new_rank.idxmin() == 7  # SalesRevenueNet 933.9 now first
    assert new_rank[9] == 0  # company 2: 50 vs 49 is no conflict
    assert drops[facts.ADJUSTED_REVENUE_LARGEST] == 1
