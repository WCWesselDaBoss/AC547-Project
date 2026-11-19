"""Check the Phase 3 app fixtures and the dashboard data-source switch.

The dashboard is built against tests/fixtures/app/ before it ever sees
real data, so a fixture whose columns or types differ from data/sample/
would let a screen work in development and break in the demo.
"""

import pandas as pd
import pytest

import config
from tests.fixtures import build_app_fixtures


def read_table(data_dir, table):
    """Read one Parquet table from a data folder."""
    return pd.read_parquet(data_dir / f"{table}.parquet")


@pytest.mark.parametrize("table", config.APP_TABLES)
def test_fixture_columns_and_types_match_sample(table):
    """Each fixture table has the sample's exact columns, order and types.

    data/sample/ is built by the real Phase 1 and 2 code, so matching it
    means matching the section 4 contract the app will meet in the demo.
    """
    fixture_df = read_table(config.APP_FIXTURE_DIR, table)
    sample_df = read_table(config.SAMPLE_DIR, table)
    pd.testing.assert_series_equal(fixture_df.dtypes, sample_df.dtypes)


@pytest.mark.parametrize("table", config.APP_TABLES)
def test_committed_fixture_matches_builder(table):
    """The committed Parquet file equals what the builder script makes.

    Fails if someone edits the script without re-running it, or if a
    Phase 2 formula change alters the fixture scores; either way, rerun
    python tests/fixtures/build_app_fixtures.py and review the diff.
    """
    built_df = build_app_fixtures.build_app_fixtures()[table]
    pd.testing.assert_frame_equal(
        read_table(config.APP_FIXTURE_DIR, table), built_df
    )


def test_one_original_value_per_company_item_period():
    """Section 4: each company, line item and period has one original."""
    facts_df = read_table(config.APP_FIXTURE_DIR, "facts_long")
    originals = facts_df[facts_df["is_original"]]
    keys = ["cik", "line_item", "period_end"]
    assert not originals.duplicated(keys).any()


def test_restated_value_is_kept_but_not_original():
    """Stretch Co FY2022 revenue: $750M original, $700M restated later.

    The trace panel must show the $750M the score used.
    """
    facts_df = read_table(config.APP_FIXTURE_DIR, "facts_long")
    revenue = facts_df[
        (facts_df["cik"] == 102)
        & (facts_df["line_item"] == "revenue")
        & (facts_df["fiscal_year"] == 2022)
    ].set_index("is_original")["value"]
    assert revenue[True] == 750_000_000
    assert revenue[False] == 700_000_000


def test_fixture_covers_the_display_states():
    """The fixture includes the cases each screen must be able to draw."""
    scores_df = read_table(config.APP_FIXTURE_DIR, "scores")
    companies_df = read_table(config.APP_FIXTURE_DIR, "companies")
    # A flagged, an unflagged and a blank M-Score.
    assert scores_df["m_flag"].isna().any()
    assert set(scores_df["m_flag"].dropna()) == {True, False}
    # A company alone in its industry, so its percentile ranks are blank.
    assert scores_df["m_score_pctile"].isna().any()
    # Excluded companies, so the screener's exclusion note has content.
    assert companies_df["is_excluded"].sum() == 2
    assert companies_df["ticker"].isna().any()


@pytest.mark.parametrize("source", ["fixture", "sample"])
def test_named_source_returns_its_folder(source):
    """A source named explicitly is used as asked."""
    assert config.app_data_dir(source) == config.APP_DATA_DIRS[source]


def test_auto_falls_back_to_sample_when_full_is_incomplete(
    tmp_path, monkeypatch
):
    """auto uses the sample when data/processed/ lacks a table."""
    monkeypatch.setitem(config.APP_DATA_DIRS, "full", tmp_path)
    assert config.app_data_dir("auto") == config.SAMPLE_DIR


def test_auto_prefers_full_when_every_table_exists(tmp_path, monkeypatch):
    """auto uses full data as soon as every app table is present."""
    for table in config.APP_TABLES:
        (tmp_path / f"{table}.parquet").touch()
    monkeypatch.setitem(config.APP_DATA_DIRS, "full", tmp_path)
    assert config.app_data_dir("auto") == tmp_path


def test_named_source_with_missing_tables_raises(tmp_path, monkeypatch):
    """Asking for full data never silently shows the sample instead."""
    monkeypatch.setitem(config.APP_DATA_DIRS, "full", tmp_path)
    with pytest.raises(FileNotFoundError, match="scores.parquet"):
        config.app_data_dir("full")


def test_unknown_source_raises():
    """A typo in EQR_DATA_SOURCE is reported, not ignored."""
    with pytest.raises(ValueError, match="Unknown data source"):
        config.app_data_dir("smaple")
