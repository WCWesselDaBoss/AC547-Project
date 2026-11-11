"""Tests for src/pipeline/financials.py.

Submissions fixture (company 20, tests/fixtures/sec/financials/):
  recent:   10-K FY2024, 10-K/A FY2024 (ignored), 10-Q (ignored),
            10-K FY2023
  overflow: 10-K ending 2022-05-31 (FY2021 by the Compustat rule),
            10-K ending 2021-12-31 (also FY2021 -> duplicate label),
            8-K (ignored)
"""

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.pipeline import financials, tag_map

FIXTURE = Path(__file__).parent / "fixtures" / "sec" / "financials"


@pytest.fixture
def index_and_log(tmp_path):
    """Build the 10-K index for company 20 from the fixture ZIP."""
    zip_path = tmp_path / "submissions.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for json_path in FIXTURE.glob("*.json"):
            archive.write(json_path, arcname=json_path.name)
    log = {}
    return financials.annual_report_index(zip_path, [20], log), log


def test_index_keeps_only_original_10ks(index_and_log):
    """Amendments, 10-Qs and 8-Ks never create a fiscal year."""
    index_df, _ = index_and_log
    assert index_df["fiscal_year"].tolist() == [2021, 2023, 2024]


def test_index_reads_overflow_files(index_and_log):
    """The FY2021 10-K exists only in the overflow file."""
    index_df, _ = index_and_log
    fy2021 = index_df[index_df["fiscal_year"] == 2021]
    assert fy2021["accession"].item() == "0000000020-22-000001"


def test_duplicate_fiscal_year_label_keeps_earlier_and_is_counted(
    index_and_log,
):
    """Two 10-Ks labeled FY2021: the earlier year end is kept, 1 logged."""
    index_df, log = index_and_log
    fy2021 = index_df[index_df["fiscal_year"] == 2021]
    assert fy2021["period_end"].item() == pd.Timestamp("2021-12-31")
    assert log["dropped:duplicate_fiscal_year_label"] == 1


def test_index_uses_contract_date_type(index_and_log):
    """Dates are datetime64[ns], matching facts_long, so merges work."""
    index_df, _ = index_and_log
    assert index_df["period_end"].dtype == "datetime64[ns]"


# ---- matching and building from small hand-made tables --------------------


def make_index(rows):
    """Build a 10-K index from (cik, fy, period_end, filed, accession)."""
    index_df = pd.DataFrame(
        rows,
        columns=[
            "cik",
            "fiscal_year",
            "period_end",
            "filed_date",
            "accession",
        ],
    )
    for column in ("period_end", "filed_date"):
        index_df[column] = pd.to_datetime(index_df[column]).astype(
            "datetime64[ns]"
        )
    return index_df


def make_facts(rows):
    """Build facts_long rows from (cik, item, value, end, fy, original,
    accession, filed)."""
    facts_df = pd.DataFrame(
        rows,
        columns=[
            "cik",
            "line_item",
            "value",
            "period_end",
            "fiscal_year",
            "is_original",
            "accession",
            "filed_date",
        ],
    )
    for column in ("period_end", "filed_date"):
        facts_df[column] = pd.to_datetime(facts_df[column]).astype(
            "datetime64[ns]"
        )
    return facts_df


def fact_row(
    item,
    value,
    end="2024-12-28",
    fy=2024,
    original=True,
    accession="A24",
    filed="2025-02-20",
):
    """Return one make_facts row for company 1 (defaults: FY2024 10-K)."""
    return (1, item, value, end, fy, original, accession, filed)


INDEX = make_index(
    [
        (1, 2024, "2024-12-28", "2025-02-20", "A24"),  # 52-week year
        (1, 2025, "2025-12-27", "2026-02-19", "A25"),
    ]
)


def test_fact_within_7_days_matches_and_92_days_does_not():
    """A Dec 31 value matches a Dec 28 year end; a Sept 30 one does not."""
    facts_df = make_facts(
        [
            fact_row("revenue", 500.0, "2024-12-31"),
            fact_row("total_assets", 9.0, "2024-09-30"),
            fact_row(
                "revenue",
                999.0,
                "2024-12-31",
                original=False,
                accession="A25",
                filed="2026-02-19",
            ),
        ]
    )
    log = {}
    matched = financials.match_originals_to_years(facts_df, INDEX, log)
    assert matched["value"].tolist() == [500.0]  # the non-original is ignored
    assert log["unused:original_facts_matching_no_10k_year"] == 1


def test_comparative_year_added_before_first_10k():
    """The first 10-K (FY2024) also reports 2023 assets: FY2023 is added
    and traced to the 10-K that reported it."""
    facts_df = make_facts(
        [fact_row("total_assets", 800.0, "2023-12-30", fy=2023)]
    )
    log = {}
    added = financials.comparative_year_index(facts_df, INDEX, log)
    assert added["fiscal_year"].tolist() == [2023]
    assert added["accession"].tolist() == ["A24"]
    assert log["added:comparative_only_years"] == 1


def test_comparative_year_not_added_when_year_has_own_10k():
    """A year that has its own 10-K is never duplicated."""
    facts_df = make_facts([fact_row("total_assets", 900.0)])
    log = {}
    added = financials.comparative_year_index(facts_df, INDEX, log)
    assert added.empty


@pytest.mark.parametrize(
    "revenue, assets, expected",
    [
        (100_000_000, np.nan, True),  # exactly at the floor passes
        (99_999_999, np.nan, False),
        (np.nan, 100_000_000, True),  # assets alone can pass
        (5_000_000, 250_000_000, True),  # small revenue, large assets
        (np.nan, np.nan, False),  # untestable cannot pass
    ],
)
def test_size_floor(revenue, assets, expected):
    """Revenue OR total assets of at least $100M, each year separately."""
    result = financials.passes_size_floor(
        pd.Series([revenue]), pd.Series([assets])
    )
    assert bool(result[0]) is expected


def test_build_financials_end_to_end():
    """One complete year, one year with no facts (dropped and logged)."""
    facts_df = make_facts(
        [
            fact_row("revenue", 2e8),
            fact_row("total_assets", 5e8),
            fact_row("net_income", 3e7),
            fact_row("liabilities_and_equity", 5e8),
            fact_row("stockholders_equity", 2e8),
        ]
    )
    log = {}
    result = financials.build_financials(facts_df, INDEX, log)
    assert list(result.columns) == financials.FINANCIALS_COLUMNS
    assert len(result) == 1  # FY2025 had a 10-K but no facts
    assert log["dropped:10k_year_with_no_facts"] == 1
    row = result.iloc[0]
    assert row["accession"] == "A24"
    assert bool(row["passes_size_floor"])
    # Untagged items were calculated from reported facts and labeled.
    assert row["income_continuing_ops"] == 3e7
    assert row["total_liabilities"] == 3e8
    assert row["derived_items"] == "income_continuing_ops; total_liabilities"
    assert np.isnan(row["sga"])  # missing stays missing


def test_contract_lists_every_item_column():
    """The output columns follow the section 4 contract order."""
    assert financials.VALUE_COLUMNS[:18] == list(tag_map.LINE_ITEMS)
    assert financials.FINANCIALS_COLUMNS[:7] == [
        "cik",
        "fiscal_year",
        "period_end",
        "filed_date",
        "accession",
        "passes_size_floor",
        "derived_items",
    ]
