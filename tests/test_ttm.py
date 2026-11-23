"""Tests for single quarters and TTM (src/pipeline/ttm.py), with a small
fake company whose every number can be checked by hand."""

from collections import Counter

import pandas as pd
import pytest

from src.pipeline import ttm

K_FILED = "2024-02-20"  # the FY2023 10-K


def fact(item, start, end, value, year, quarter, accession, filed):
    """Return one original fact row as facts_quarterly holds it (start
    None for a balance sheet instant)."""
    end = pd.Timestamp(end)
    start = pd.Timestamp(start) if start else pd.NaT
    days = (end - start).days + 1 if start is not pd.NaT else pd.NA
    return {
        "cik": 1,
        "line_item": item,
        "value": float(value),
        "period_start": start,
        "period_end": end,
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "duration_days": days,
        "accession": accession,
        "filed_date": pd.Timestamp(filed),
    }


def calendar_company(drop_q2_revenue=False):
    """A calendar-year company (FY2023 and Q1 2024):

    revenue: 3-month values 100, 110, 120 in the 10-Qs, 9-month 330, and
    the 10-K's 460, so Q4 = 460 - 330 = 130; Q1 2024 is 105.
    cfo: year-to-date only (10, 25, 45, then 70 in the 10-K), so the
    quarters are 10, 15, 20 and 25.
    total_assets: 1,000 at every quarter end, 1,100 at Q1 2024.
    """
    rows = [
        fact(
            "revenue",
            "2023-01-01",
            "2023-03-31",
            100,
            2023,
            1,
            "q1",
            "2023-05-01",
        ),
        fact(
            "revenue",
            "2023-04-01",
            "2023-06-30",
            110,
            2023,
            2,
            "q2",
            "2023-08-01",
        ),
        fact(
            "revenue",
            "2023-07-01",
            "2023-09-30",
            120,
            2023,
            3,
            "q3",
            "2023-11-01",
        ),
        fact(
            "revenue",
            "2023-01-01",
            "2023-09-30",
            330,
            2023,
            3,
            "q3",
            "2023-11-01",
        ),
        fact(
            "revenue", "2023-01-01", "2023-12-31", 460, 2023, 4, "k", K_FILED
        ),
        fact(
            "revenue",
            "2024-01-01",
            "2024-03-31",
            105,
            2024,
            1,
            "q5",
            "2024-05-01",
        ),
        fact(
            "cfo", "2023-01-01", "2023-03-31", 10, 2023, 1, "q1", "2023-05-01"
        ),
        fact(
            "cfo", "2023-01-01", "2023-06-30", 25, 2023, 2, "q2", "2023-08-01"
        ),
        fact(
            "cfo", "2023-01-01", "2023-09-30", 45, 2023, 3, "q3", "2023-11-01"
        ),
        fact("cfo", "2023-01-01", "2023-12-31", 70, 2023, 4, "k", K_FILED),
    ]
    for end, quarter, accession, filed in [
        ("2023-03-31", 1, "q1", "2023-05-01"),
        ("2023-06-30", 2, "q2", "2023-08-01"),
        ("2023-09-30", 3, "q3", "2023-11-01"),
        ("2023-12-31", 4, "k", K_FILED),
    ]:
        rows.append(
            fact(
                "total_assets",
                None,
                end,
                1000,
                2023,
                quarter,
                accession,
                filed,
            )
        )
    rows.append(
        fact(
            "total_assets",
            None,
            "2024-03-31",
            1100,
            2024,
            1,
            "q5",
            "2024-05-01",
        )
    )
    if drop_q2_revenue:
        rows = [
            r
            for r in rows
            if not (r["line_item"] == "revenue" and r["accession"] == "q2")
        ]
    table = pd.DataFrame(rows)
    table["duration_days"] = table["duration_days"].astype("Int64")
    return table


def build(facts_df):
    """Return (financials_ttm rows, sources, log) for fake facts."""
    log = Counter()
    wide, sources = ttm.build_batch(facts_df, {}, log)
    return ttm.ttm_to_contract_types(wide), sources, log


def row(wide, year, quarter):
    """Return the financials_ttm row for one fiscal quarter."""
    match = wide[
        (wide["fiscal_year"] == year) & (wide["fiscal_quarter"] == quarter)
    ]
    assert len(match) == 1
    return match.iloc[0]


def test_quarters_covered_and_quarter_index():
    """Flow lengths map to quarters covered; instants to 0. The quarter
    before Q1 2024 is Q4 2023."""
    days = pd.Series([91, 182, 273, 365, pd.NA], dtype="Int64")
    assert ttm.quarters_covered(days).tolist() == [1, 2, 3, 4, 0]
    assert ttm.quarter_index(2024, 1) - 1 == ttm.quarter_index(2023, 4)


def test_ttm_from_reported_quarters_and_annual_minus_9_months():
    """FY2023 Q4 TTM revenue = 100 + 110 + 120 + (460 - 330) = 460, and
    Q1 2024 TTM = 110 + 120 + 130 + 105 = 465."""
    wide, _, _ = build(calendar_company())
    assert row(wide, 2023, 4)["revenue"] == 460
    assert row(wide, 2024, 1)["revenue"] == 465


def test_year_to_date_differences():
    """cfo is reported only year to date: quarters 10, 25-10, 45-25 and
    70-45 sum to a Q4 TTM of 70; Q1 2024 has no cfo, so its TTM is NaN."""
    wide, _, _ = build(calendar_company())
    assert row(wide, 2023, 4)["cfo"] == 70
    assert pd.isna(row(wide, 2024, 1)["cfo"])


def test_sources_name_each_quarter_and_add_up():
    """The Q4 2023 revenue trace has four quarters; Q4 uses two filings
    (+460 from the 10-K, -330 from the Q3 10-Q, method "annual minus 9
    months"), and all rows add up to the TTM value."""
    _, sources, _ = build(calendar_company())
    trace = sources[
        (sources["period_end"] == pd.Timestamp("2023-12-31"))
        & (sources["line_item"] == "revenue")
    ]
    assert trace["value"].sum() == 460
    assert trace["component_period_end"].nunique() == 4
    q4 = trace[trace["component_period_end"] == pd.Timestamp("2023-12-31")]
    assert sorted(q4["value"]) == [-330, 460]
    assert set(q4["method"]) == {ttm.METHOD_ANNUAL}
    assert set(q4["component_period_start"]) == {pd.Timestamp("2023-10-01")}
    cfo_q2 = sources[
        (sources["line_item"] == "cfo")
        & (sources["component_period_end"] == pd.Timestamp("2023-06-30"))
    ]
    assert sorted(cfo_q2["value"]) == [-10, 25]
    assert set(cfo_q2["method"]) == {ttm.METHOD_YTD}


def test_missing_quarter_blocks_the_ttm():
    """With Q2 revenue gone (no 3-month value and no 6-month YTD), every
    TTM that needs Q2 is NaN, and the reason is counted, not estimated."""
    wide, _, log = build(calendar_company(drop_q2_revenue=True))
    assert pd.isna(row(wide, 2023, 4)["revenue"])
    assert pd.isna(row(wide, 2024, 1)["revenue"])
    assert log[f"ttm_missing:revenue:{ttm.REASON_MISSING}"] >= 2


def test_available_date_is_the_latest_filing_used():
    """Q4 2023's latest filing is the 10-K (Feb 20, 2024). Q1 2024 also
    uses the Q1 10-Q filed May 1, 2024, so that is its date."""
    wide, _, _ = build(calendar_company())
    assert row(wide, 2023, 4)["available_date"] == pd.Timestamp(K_FILED)
    assert row(wide, 2024, 1)["available_date"] == pd.Timestamp("2024-05-01")


def test_balance_sheet_is_the_quarter_end_value_and_size_floor():
    """total_assets is the quarter-end balance, not a sum; with tiny fake
    values the size floor is not met."""
    wide, _, _ = build(calendar_company())
    assert row(wide, 2024, 1)["total_assets"] == 1100
    assert not row(wide, 2024, 1)["passes_size_floor"]


def test_53_week_year_ttm():
    """A 53-week year (Jan 29, 2023 to Feb 3, 2024: 371 days) with a
    14-week fourth quarter still gives a TTM: 50 + 50 + 50 + 60 = 210."""
    quarters = [
        ("2023-01-29", "2023-04-29", 1),
        ("2023-04-30", "2023-07-29", 2),
        ("2023-07-30", "2023-10-28", 3),
        ("2023-10-29", "2024-02-03", 4),
    ]
    rows = [
        fact(
            "revenue", start, end, 60 if q == 4 else 50, 2023, q, f"f{q}", end
        )
        for start, end, q in quarters
    ]
    table = pd.DataFrame(rows)
    table["duration_days"] = table["duration_days"].astype("Int64")
    wide, _, _ = build(table)
    assert row(wide, 2023, 4)["revenue"] == 210


@pytest.mark.parametrize(
    "q2_start, reason",
    [
        ("2023-04-10", ttm.REASON_GAP),  # Q2 starts 10 days after Q1 ends
    ],
)
def test_non_consecutive_quarters_block_the_ttm(q2_start, reason):
    """If a quarter does not start the day after the previous one ends,
    the TTM is NaN and the gap is counted."""
    rows = [
        fact(
            "revenue",
            "2023-01-01",
            "2023-03-31",
            100,
            2023,
            1,
            "a",
            "2023-05-01",
        ),
        fact(
            "revenue", q2_start, "2023-06-30", 50, 2023, 2, "b", "2023-08-01"
        ),
        fact(
            "revenue",
            "2023-07-01",
            "2023-09-30",
            100,
            2023,
            3,
            "c",
            "2023-11-01",
        ),
        fact(
            "revenue", "2023-10-01", "2023-12-31", 100, 2023, 4, "d", K_FILED
        ),
        # A balance so the Q4 row exists even with no TTM revenue.
        fact("total_assets", None, "2023-12-31", 500, 2023, 4, "d", K_FILED),
    ]
    table = pd.DataFrame(rows)
    table["duration_days"] = table["duration_days"].astype("Int64")
    wide, _, log = build(table)
    assert pd.isna(row(wide, 2023, 4)["revenue"])
    assert log[f"ttm_missing:revenue:{reason}"] == 1


def test_build_ttm_writes_sources_with_contract_types(tmp_path):
    """The batch writer stores ttm_sources with the section 4 types (text
    columns read back as pandas "string"), and returns financials_ttm in
    the contract column order."""
    path = tmp_path / "ttm_sources.parquet"
    wide, log = ttm.build_ttm(calendar_company(), {}, path)
    sources = pd.read_parquet(path)
    assert list(sources.columns) == ttm.SOURCES_COLUMNS
    for column in ["line_item", "method", "accession", "filing_url"]:
        assert sources[column].dtype == "string"
    assert list(wide.columns) == ttm.TTM_COLUMNS
    assert log["ttm_sources:rows"] == len(sources)
