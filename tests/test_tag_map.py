"""Tests for tag_map.py, periods.py and derived_items.py."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.pipeline import derived_items, periods, tag_map

# ---- tag_map ---------------------------------------------------------------


def test_every_item_is_well_formed():
    """Each item has tags, a valid period type and a known unit."""
    for name, spec in tag_map.ALL_ITEMS.items():
        assert spec["tags"], name
        assert spec["period"] in (tag_map.DURATION, tag_map.INSTANT), name
        assert spec["unit"] in ("USD", "shares"), name
        assert len(spec["tags"]) == len(set(spec["tags"])), name


def test_section_5_inputs_are_all_mapped():
    """Every input the section 5 formulas need has a line item."""
    needed = {
        "revenue", "cost_of_revenue", "sga", "depreciation",
        "operating_income", "income_continuing_ops", "net_income", "cfo",
        "receivables", "current_assets", "ppe_net", "total_assets",
        "current_liabilities", "long_term_debt", "total_liabilities",
        "retained_earnings", "stockholders_equity", "shares_outstanding",
    }  # fmt: skip
    assert needed == set(tag_map.LINE_ITEMS)


def test_pick_first_tag_uses_map_order():
    """With no company override, the earliest listed tag wins."""
    available = {"SalesRevenueNet", "Revenues"}
    assert tag_map.pick_first_tag(available, "revenue") == "Revenues"


def test_pick_first_tag_returns_none_when_missing():
    """No mapped tag available means missing, never a guess."""
    assert tag_map.pick_first_tag({"SomethingElse"}, "revenue") is None


def test_company_tag_order_prefers_most_used_tag():
    """A company reporting Depreciation in 10 years and D&A in 3 uses
    Depreciation first, so its years stay comparable."""
    order = tag_map.company_tag_order(
        {"DepreciationDepletionAndAmortization": 3, "Depreciation": 10},
        "depreciation",
    )
    assert order[0] == "Depreciation"


def test_company_tag_order_ties_keep_map_order():
    """Equal year counts fall back to the map's preference."""
    order = tag_map.company_tag_order(
        {"Depreciation": 5, "DepreciationDepletionAndAmortization": 5},
        "depreciation",
    )
    assert order[0] == "DepreciationDepletionAndAmortization"


# ---- periods ---------------------------------------------------------------


def test_period_days_counts_both_ends():
    """A calendar year is 365 days."""
    assert periods.period_days(date(2025, 1, 1), date(2025, 12, 31)) == 365


@pytest.mark.parametrize(
    "start, end, expected",
    [
        (date(2025, 1, 1), date(2025, 12, 31), True),  # calendar year
        (date(2024, 9, 29), date(2025, 9, 27), True),  # 52 weeks, 364 days
        (date(2024, 9, 29), date(2025, 10, 4), True),  # 53 weeks, 371 days
        (date(2025, 7, 1), date(2025, 9, 30), False),  # one quarter
        (date(2025, 1, 1), date(2025, 9, 30), False),  # nine months YTD
    ],
)
def test_is_annual_duration(start, end, expected):
    """Annual periods pass; quarters and year-to-date periods do not."""
    assert periods.is_annual_duration(start, end) is expected


# ---- derived_items ---------------------------------------------------------


def make_wide(**columns):
    """Build a one-row-per-case wide table with every item column."""
    wide_df = pd.DataFrame({item: [np.nan] for item in tag_map.ALL_ITEMS})
    rows = len(next(iter(columns.values())))
    wide_df = pd.concat([wide_df] * rows, ignore_index=True)
    for name, values in columns.items():
        wide_df[name] = values
    return wide_df


def test_continuing_ops_tagged_value_is_kept():
    """A reported value is never replaced by a calculation."""
    wide_df = make_wide(
        income_continuing_ops=[90.0],
        net_income=[100.0],
        income_discontinued_ops=[10.0],
    )
    values, derived = derived_items.derive_income_continuing_ops(wide_df)
    assert values[0] == 90.0 and not derived[0]


def test_continuing_ops_derived_from_net_income():
    """Net income 100, discontinued 30 -> continuing 70; none -> 100."""
    wide_df = make_wide(
        net_income=[100.0, 100.0],
        income_discontinued_ops=[30.0, np.nan],
    )
    values, derived = derived_items.derive_income_continuing_ops(wide_df)
    assert values.tolist() == [70.0, 100.0]
    assert derived.all()


def test_continuing_ops_stays_missing_without_net_income():
    """No net income means nothing to calculate from: stays missing."""
    wide_df = make_wide(net_income=[np.nan])
    values, derived = derived_items.derive_income_continuing_ops(wide_df)
    assert np.isnan(values[0]) and not derived[0]


def test_total_liabilities_derivation():
    """L&E 1,000 - equity incl. NCI 400 - temporary equity 50 = 550."""
    wide_df = make_wide(
        liabilities_and_equity=[1000.0],
        equity_including_nci=[400.0],
        stockholders_equity=[380.0],
        temporary_equity_parent=[30.0],
        redeemable_nci=[20.0],
    )
    values, derived = derived_items.derive_total_liabilities(wide_df)
    assert values[0] == 550.0 and derived[0]


def test_total_liabilities_falls_back_to_parent_equity():
    """No NCI total: use parent equity. 1,000 - 380 = 620."""
    wide_df = make_wide(
        liabilities_and_equity=[1000.0], stockholders_equity=[380.0]
    )
    values, _ = derived_items.derive_total_liabilities(wide_df)
    assert values[0] == 620.0


def test_total_liabilities_needs_equity():
    """Without any equity figure the calculation is not attempted."""
    wide_df = make_wide(liabilities_and_equity=[1000.0])
    values, derived = derived_items.derive_total_liabilities(wide_df)
    assert np.isnan(values[0]) and not derived[0]


def test_apply_derivations_labels_rows():
    """derived_items names what was calculated, or is null."""
    wide_df = make_wide(
        net_income=[100.0, np.nan],
        total_liabilities=[np.nan, 500.0],
        liabilities_and_equity=[1000.0, np.nan],
        stockholders_equity=[400.0, np.nan],
    )
    result = derived_items.apply_derivations(wide_df)
    assert result["derived_items"][0] == (
        "income_continuing_ops; total_liabilities"
    )
    assert pd.isna(result["derived_items"][1])
    assert result["total_liabilities"][1] == 500.0
