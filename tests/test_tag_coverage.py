"""Tests for tag_coverage.py using small hand-built facts."""

from datetime import date

import pandas as pd

from src.pipeline import tag_coverage


def fact(end, val, filed, start=None, form="10-K", accn="0000000001-25-1"):
    """Build one companyfacts-style fact dict."""
    entry = {"end": end, "val": val, "accn": accn, "fy": 2025, "fp": "FY"}
    entry.update({"form": form, "filed": filed})
    if start:
        entry["start"] = start
    return entry


def test_annual_facts_filters_forms_periods_and_years():
    """Keep annual 10-K facts; drop quarters, 10-Qs and out-of-range."""
    revenue_facts = [
        # Full year 2024: kept.
        fact("2024-12-31", 500, "2025-02-01", "2024-01-01"),
        # Fourth quarter only: dropped (not 350-380 days).
        fact("2024-12-31", 120, "2025-02-01", "2024-10-01"),
        # From a 10-Q: dropped.
        fact("2024-06-30", 250, "2024-08-01", "2024-01-01", form="10-Q"),
        # FY2009: dropped (before FY2011).
        fact("2009-12-31", 300, "2010-02-01", "2009-01-01"),
    ]
    company_facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": revenue_facts}},
                # Not a mapped or candidate tag: ignored.
                "UnrelatedTag": {
                    "units": {"USD": [fact("2024-12-31", 1, "x")]}
                },
            }
        }
    }
    rows = tag_coverage.annual_facts_from_company(
        7, company_facts, tag_coverage.combined_candidate_regex()
    )
    assert len(rows) == 1
    assert rows[0]["value"] == 500.0
    assert rows[0]["fiscal_year"] == 2024
    assert rows[0]["cik"] == 7


def test_empty_companyfacts_file_yields_no_rows():
    """SEC's empty '{}' files must not crash the scan."""
    assert (
        tag_coverage.annual_facts_from_company(
            1, {}, tag_coverage.combined_candidate_regex()
        )
        == []
    )


def test_keep_earliest_filed_keeps_original():
    """A later restatement of the same period is not the original."""
    facts_df = pd.DataFrame(
        {
            "cik": [1, 1],
            "tag": ["Revenues", "Revenues"],
            "unit": ["USD", "USD"],
            "period_start": [date(2024, 1, 1)] * 2,
            "period_end": [date(2024, 12, 31)] * 2,
            "filed_date": [date(2026, 2, 1), date(2025, 2, 1)],
            "value": [520.0, 500.0],
        }
    )
    kept = tag_coverage.keep_earliest_filed(facts_df)
    assert kept["value"].tolist() == [500.0]


def winners_input(rows):
    """Build an item_facts DataFrame from (cik, year, tag, value) rows."""
    return pd.DataFrame(rows, columns=["cik", "fiscal_year", "tag", "value"])


def test_winning_values_prefers_company_consistent_tag():
    """Company uses Depreciation in 3 years and D&A in 1: Depreciation
    wins in the overlapping year, so all three years use one concept."""
    item_facts_df = winners_input(
        [
            (1, 2022, "Depreciation", 10.0),
            (1, 2023, "Depreciation", 11.0),
            (1, 2023, "DepreciationDepletionAndAmortization", 15.0),
            (1, 2024, "Depreciation", 12.0),
        ]
    )
    winners = tag_coverage.winning_values(item_facts_df, "depreciation")
    assert winners.sort_values("fiscal_year")["value"].tolist() == [
        10.0,
        11.0,
        12.0,
    ]
    assert tag_coverage.count_tag_switches(winners) == 0


def test_count_tag_switches_only_consecutive_years():
    """A switch across a gap year is not counted."""
    winners = winners_input(
        [
            (1, 2020, "A", 1.0),
            (1, 2021, "B", 1.0),  # switch
            (1, 2023, "A", 1.0),  # gap year: not counted
        ]
    )
    assert tag_coverage.count_tag_switches(winners) == 1
