"""Check the Phase 2 fixture tables against the section 4 contract.

Every score test reads these fixtures, so a fixture with the wrong
columns, types or numbers would make every later test meaningless.
"""

import pandas as pd

from src.pipeline import financials
from tests.fixtures import build_fixtures

MILLION = build_fixtures.MILLION


def load_fixture():
    """Read the committed financials_annual fixture."""
    return pd.read_parquet(build_fixtures.FINANCIALS_FIXTURE_PATH)


def test_fixture_has_contract_columns_in_order():
    """The fixture has exactly the section 4 columns, in order."""
    assert list(load_fixture().columns) == financials.FINANCIALS_COLUMNS


def test_fixture_types_match_real_financials_types():
    """The fixture has the same column types as the real table."""
    fixture_df = load_fixture()
    expected_types = financials.to_contract_types(fixture_df).dtypes
    pd.testing.assert_series_equal(fixture_df.dtypes, expected_types)


def test_committed_fixture_matches_builder_script():
    """The committed Parquet file equals what the script builds now.

    Catches someone editing the numbers in the script but forgetting to
    re-run it (or the reverse).
    """
    pd.testing.assert_frame_equal(
        load_fixture(), build_fixtures.build_financials_fixture()
    )


def test_fixture_shape_three_companies_three_years():
    """Three companies, each with FY2021 to FY2023, all above the floor."""
    fixture_df = load_fixture()
    years_by_company = fixture_df.groupby("cik")["fiscal_year"].apply(list)
    assert years_by_company.to_dict() == {
        101: [2021, 2022, 2023],
        102: [2021, 2022, 2023],
        103: [2021, 2022, 2023],
    }
    assert fixture_df["passes_size_floor"].all()


def test_fixture_balance_sheets_balance():
    """Liabilities plus equity equals total assets in every row.

    A fixture that does not balance would give misleading hand checks.
    """
    fixture_df = load_fixture()
    gap = (
        fixture_df["total_liabilities"]
        + fixture_df["stockholders_equity"]
        - fixture_df["total_assets"]
    )
    assert (gap.abs() < 1).all()


def test_fixture_money_in_whole_dollars():
    """Money is stored in dollars, not millions (section 4)."""
    fixture_df = load_fixture().set_index(["cik", "fiscal_year"])
    assert fixture_df.loc[(101, 2021), "revenue"] == 1000 * MILLION
    assert fixture_df.loc[(101, 2021), "shares_outstanding"] == 100_000_000


def test_service_co_cost_of_revenue_missing_not_zero():
    """The missing input is NaN, never 0 (section 4 general rules)."""
    fixture_df = load_fixture()
    service_co = fixture_df[fixture_df["cik"] == 103]
    assert service_co["cost_of_revenue"].isna().all()
    other_cos = fixture_df[fixture_df["cik"] != 103]
    assert other_cos["cost_of_revenue"].notna().all()
