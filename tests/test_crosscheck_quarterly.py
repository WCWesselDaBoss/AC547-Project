"""Tests for the step 5 cross-check (src/scores/crosscheck_quarterly.py)
and the quarterly tie-out's M-Score guard, with hand-checkable data."""

import pandas as pd
from openpyxl import Workbook

from src.pipeline import ttm
from src.scores import crosscheck_quarterly as cc
from src.scores import tieout, tieout_quarterly


def test_agrees_uses_half_a_percent_or_ten_thousand_dollars():
    """$1B vs $1.004B agrees (0.4%); $1B vs $1.006B does not; $50,000 vs
    $58,000 agrees ($8,000 is under the $10,000 floor)."""
    left = pd.Series([1.004e9, 1.006e9, 58_000.0])
    right = pd.Series([1.0e9, 1.0e9, 50_000.0])
    assert cc.agrees(left, right).tolist() == [True, False, True]


def base_row(**changes):
    """Return one disagreeing Q4 row for cause()."""
    row = {
        "line_item": "revenue",
        "q4_method": ttm.METHOD_ANNUAL,
        "twelve_month_value": 400e6,
        "annual_value": 400e6,
        "balance_accession": None,
        "accession": "k1",
    }
    row.update(changes)
    return pd.Series(row)


def test_cause_for_flows():
    """The 12-month value agrees: the quarters do not add to 9 months.
    It differs: the annual value differs. A Q4 reported as 3 months, a
    year-to-date Q4 and a derived value each have their own cause."""
    assert cc.cause(base_row()) == "quarters_do_not_add_to_9_months"
    assert (
        cc.cause(base_row(twelve_month_value=500e6)) == "annual_value_differs"
    )
    assert (
        cc.cause(base_row(q4_method=ttm.METHOD_REPORTED))
        == "q4_reported_3_months"
    )
    assert cc.cause(base_row(q4_method=ttm.METHOD_YTD)) == "other"
    assert cc.cause(base_row(q4_method=pd.NA)) == "derived_in_ttm"


def test_cause_for_balances():
    """A balance first reported in another filing than the year's 10-K,
    or in the same 10-K under another tag."""
    balance = dict(line_item="total_assets", q4_method=ttm.METHOD_BALANCE)
    assert (
        cc.cause(base_row(balance_accession="q9", **balance))
        == "first_reported_in_another_filing"
    )
    assert (
        cc.cause(base_row(balance_accession="k1", **balance))
        == "same_filing_other_tag"
    )


def test_q4_components_finds_the_fourth_quarter():
    """For a TTM ending Dec 31 whose Q4 is +460 (10-K) and -330 (Q3
    10-Q), the method is "annual minus 9 months" and the 12-month value
    is 460; the earlier quarters are ignored."""
    end = pd.Timestamp("2023-12-31")
    sources = pd.DataFrame(
        {
            "cik": 1,
            "period_end": end,
            "line_item": "revenue",
            "component_period_end": pd.to_datetime(
                ["2023-03-31", "2023-12-31", "2023-12-31"]
            ),
            "value": [100.0, 460.0, -330.0],
            "method": [
                ttm.METHOD_REPORTED,
                ttm.METHOD_ANNUAL,
                ttm.METHOD_ANNUAL,
            ],
            "accession": ["q1", "k", "q3"],
        }
    )
    found = cc.q4_components(sources).iloc[0]
    assert found["q4_method"] == ttm.METHOD_ANNUAL
    assert found["twelve_month_value"] == 460.0


def test_guard_m_score_wraps_the_two_formulas():
    """The M-Score becomes blank when any index is blank, and the flag
    "NA" when the M-Score is blank; the original formulas are kept
    inside the guard."""
    sheet = Workbook().active
    m_row = tieout.CALC_FIRST_ROW + 8
    sheet.cell(m_row, 1, "M-Score")
    sheet.cell(m_row, 2, "=1+2")
    sheet.cell(m_row + 1, 1, "M flag (M > cutoff)")
    sheet.cell(m_row + 1, 2, f"=$B${m_row}>3")
    tieout_quarterly.guard_m_score(sheet)
    first, last = tieout.CALC_FIRST_ROW, tieout.CALC_FIRST_ROW + 7
    assert (
        sheet.cell(m_row, 2).value
        == f'=IF(COUNT($B${first}:$B${last})<8,"",1+2)'
    )
    assert (
        sheet.cell(m_row + 1, 2).value
        == f'=IF($B${m_row}="","NA",$B${m_row}>3)'
    )
