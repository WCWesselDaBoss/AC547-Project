"""Tests for the year-end cause breakdown (src/scores/yearend_causes.py),
with small hand-checkable rows."""

import pandas as pd
import pytest

from src.pipeline import ttm
from src.scores import yearend_causes as yc

END = pd.Timestamp("2023-12-31")


def mismatch(**changes):
    """Return one 'value differs' revenue row for value_cause: aligned
    dates, a 365-day year and TTM, one tag matching the annual tag, no
    restatement, nothing derived (so it is 'unexplained')."""
    row = {
        "line_item": "revenue",
        "gap_days": 0,
        "period_end_t": END,
        "first_start": pd.Timestamp("2023-01-01"),
        "year_days": 365,
        "derived_items_a": pd.NA,
        "derived_items_t": pd.NA,
        "tags": frozenset({"Revenues"}),
        "annual_tag": "Revenues",
        "restated": False,
    }
    row.update(changes)
    return pd.Series(row)


@pytest.mark.parametrize(
    "changes, cause",
    [
        ({}, yc.CAUSE_UNEXPLAINED),
        ({"gap_days": 30}, yc.CAUSE_MISSING),  # Q4 end a month off
        # Four quarters from Dec 25, 2022: 372 days against a 365-day year.
        (
            {"first_start": pd.Timestamp("2022-12-25")},
            yc.CAUSE_WEEKS,
        ),
        ({"derived_items_t": "revenue"}, yc.CAUSE_DERIVED),
        ({"tags": frozenset({"Revenues", "SalesRevenueNet"})}, yc.CAUSE_TAGS),
        ({"annual_tag": "SalesRevenueNet"}, yc.CAUSE_TAGS),
        ({"restated": True}, yc.CAUSE_RESTATED),
        (
            {"restated": True, "annual_tag": "SalesRevenueNet"},
            yc.CAUSE_BOTH,
        ),
    ],
)
def test_value_cause_takes_the_first_cause_that_applies(changes, cause):
    """Each condition alone gives its cause; misalignment comes before
    everything else, and tag mixing with a restatement is 'both'."""
    assert yc.value_cause(mismatch(**changes)) == cause


def test_misalignment_wins_over_a_restatement():
    """A Q4 end 30 days off is a misaligned quarter even if restated."""
    assert (
        yc.value_cause(mismatch(gap_days=30, restated=True))
        == yc.CAUSE_MISSING
    )


def test_restated_periods_finds_later_different_values():
    """Q1 revenue 100 was later re-reported as 90 (restated); Q2 200 was
    re-reported as 200.5 (within 0.5%: not a restatement)."""
    facts = pd.DataFrame(
        {
            "cik": 1,
            "line_item": "revenue",
            "period_start": pd.to_datetime(
                ["2023-01-01", "2023-01-01", "2023-04-01", "2023-04-01"]
            ),
            "period_end": pd.to_datetime(
                ["2023-03-31", "2023-03-31", "2023-06-30", "2023-06-30"]
            ),
            "value": [100e6, 90e6, 200e6, 200.5e6],
            "is_original": [True, False, True, False],
        }
    )
    restated = yc.restated_periods(facts)
    assert restated["period_end"].tolist() == [pd.Timestamp("2023-03-31")]


def test_unexplained_is_split_by_kept_fix_a_quarters():
    """Two unexplained mismatches: company 1's FY2023 revenue has a
    quarter kept as reported under fix A (a kept revision); company 2's
    has none (truly unexplained). A restatement gets no split."""
    mismatches = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "line_item": pd.array(["revenue"] * 3, dtype="string"),
            "fiscal_year": [2023, 2023, 2023],
            "cause": [
                yc.CAUSE_UNEXPLAINED,
                yc.CAUSE_UNEXPLAINED,
                yc.CAUSE_RESTATED,
            ],
        }
    )
    overrides = pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "line_item": ["revenue"] * 3,
            "fiscal_year": [2023, 2023, 2023],
            "action": [ttm.ACTION_KEPT, ttm.ACTION_REPLACED, ttm.ACTION_KEPT],
        }
    )
    split = yc.split_unexplained(mismatches, overrides)
    assert split["split"].tolist()[:2] == [yc.SPLIT_KEPT, yc.SPLIT_TRULY]
    assert pd.isna(split["split"].iloc[2])


def test_yearend_pairs_labels_agree_value_and_blank():
    """Annual revenue 1,000M against a Q4 TTM of 1,003M (agrees, within
    0.5%), 1,100M (differs) and no TTM value (blank)."""
    columns = ttm.TTM_COLUMNS
    annual_rows, ttm_rows = [], []
    for cik, ttm_revenue in [(1, 1_003e6), (2, 1_100e6), (3, float("nan"))]:
        base = {column: float("nan") for column in columns}
        base.update(cik=cik, fiscal_year=2023, period_end=END)
        annual_rows.append({**base, "derived_items": pd.NA, "revenue": 1e9})
        ttm_rows.append(
            {
                **base,
                "fiscal_quarter": 4,
                "derived_items": pd.NA,
                "revenue": ttm_revenue,
            }
        )
    pairs = yc.yearend_pairs(pd.DataFrame(annual_rows), pd.DataFrame(ttm_rows))
    revenue = pairs[pairs["line_item"] == "revenue"].sort_values("cik")
    assert revenue["status"].tolist() == ["agree", "value", "blank"]
