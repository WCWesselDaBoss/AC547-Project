"""Tests for quarterly click-to-trace (app/trace_quarterly.py), with one
made-up company whose numbers can be checked by hand, and a check on the
committed sample."""

import pandas as pd
import pytest

import config
from app import trace, trace_quarterly as tq
from src.pipeline import ttm
from src.scores import piotroski

Q3_END = pd.Timestamp("2024-09-30")
Q4_2023 = pd.Timestamp("2023-12-31")
Q3_2023 = pd.Timestamp("2023-09-30")


def ttm_rows():
    """FY2023 Q3, FY2023 Q4 and FY2024 Q3 TTM rows (made up)."""
    rows = []
    for year, quarter, end, revenue, derived in [
        (2023, 3, Q3_2023, 380.0, pd.NA),
        (2023, 4, Q4_2023, 400.0, pd.NA),
        (2024, 3, Q3_END, 440.0, "income_continuing_ops"),
    ]:
        row = {column: float("nan") for column in ttm.TTM_COLUMNS}
        row.update(
            cik=1,
            fiscal_year=year,
            fiscal_quarter=quarter,
            period_end=end,
            available_date=end,
            derived_items=derived,
            revenue=revenue,
            total_assets=1_000.0,
            net_income=50.0,
            income_discontinued_ops=5.0,
            income_continuing_ops=45.0,
            shares_outstanding=100.0,
        )
        rows.append(row)
    return pd.DataFrame(rows)


def source(end, item, start, stop, value, method, accession):
    """Return one ttm_sources row."""
    return {
        "cik": 1,
        "period_end": end,
        "line_item": item,
        "component_period_start": pd.Timestamp(start) if start else pd.NaT,
        "component_period_end": pd.Timestamp(stop),
        "value": value,
        "method": method,
        "accession": accession,
        "filing_url": f"https://www.sec.gov/{accession}",
    }


def sources():
    """FY2024 Q3 revenue = 100 + 110 + 120 + (230 - 120): four quarters,
    the last from a year-to-date difference (+230, -120); the balances
    and the derived value's parts have one row each."""
    m = ttm.METHOD_REPORTED
    return pd.DataFrame(
        [
            source(Q3_END, "revenue", "2023-10-01", "2023-12-31", 100, m, "a"),
            source(Q3_END, "revenue", "2024-01-01", "2024-03-31", 110, m, "b"),
            source(Q3_END, "revenue", "2024-04-01", "2024-06-30", 120, m, "c"),
            source(
                Q3_END,
                "revenue",
                "2024-07-01",
                "2024-09-30",
                230,
                ttm.METHOD_YTD,
                "d",
            ),
            source(
                Q3_END,
                "revenue",
                "2024-07-01",
                "2024-09-30",
                -120,
                ttm.METHOD_YTD,
                "c",
            ),
            source(
                Q3_END,
                "total_assets",
                None,
                "2024-09-30",
                1_000,
                ttm.METHOD_BALANCE,
                "d",
            ),
            source(
                Q3_END, "net_income", "2023-10-01", "2024-09-30", 50, m, "d"
            ),
            source(
                Q3_END,
                "income_discontinued_ops",
                "2023-10-01",
                "2024-09-30",
                5,
                m,
                "d",
            ),
            source(
                Q3_END,
                "shares_outstanding",
                None,
                "2024-09-30",
                100,
                ttm.METHOD_BALANCE,
                "d",
            ),
        ]
    )


def share_facts():
    """The FY2024 Q3 10-Q ("d") reports 98 shares at the prior fiscal
    year end (Dec 31, 2023) and 90 at Sep 30, 2023 (not used in Q3)."""
    return pd.DataFrame(
        {
            "line_item": "shares_outstanding",
            "accession": ["d", "d"],
            "period_end": [Q4_2023, Q3_2023],
            "value": [98.0, 90.0],
            "filing_url": "https://www.sec.gov/d",
        }
    )


def traced(inputs):
    """Trace inputs for FY2024 Q3."""
    return tq.trace_ttm_inputs(
        inputs, 2024, 3, ttm_rows(), sources(), share_facts()
    )


def test_a_ttm_flow_shows_its_four_quarters_and_adds_up():
    """Revenue FY2024 Q3 is 440, a sum of four quarters; the component
    rows (+100, +110, +120, +230, -120) add up to it."""
    inputs, components, _ = traced([("revenue", 0)])
    assert inputs.iloc[0]["Value used"] == "$440"
    assert inputs.iloc[0]["How"] == tq.TTM_SUM
    assert len(components) == 5
    assert components["Single quarter"].nunique() == 4
    assert set(components["Method"]) == {
        ttm.METHOD_REPORTED,
        ttm.METHOD_YTD,
    }


def test_a_balance_is_the_quarter_end_value():
    """Total assets: one row, the quarter-end balance."""
    inputs, components, _ = traced([("total_assets", 0)])
    assert inputs.iloc[0]["How"] == tq.BALANCE
    assert components["Single quarter"].tolist() == ["at 2024-09-30"]


def test_prior_year_input_is_the_same_quarter_a_year_earlier():
    """Revenue "t-1" for FY2024 Q3 is FY2023 Q3 (380), not FY2023 Q4."""
    inputs, _, _ = traced([("revenue", 1)])
    assert inputs.iloc[0]["Quarter"] == "FY2023 Q3"
    assert inputs.iloc[0]["Value used"] == "$380"


def test_missing_values_and_quarters_are_named():
    """No FY2022 Q3 row: "no quarterly data"; a blank flow: "needs four
    complete quarters"."""
    inputs, _, _ = traced([("revenue", 2), ("cfo", 0)])
    assert inputs["How"].tolist() == [tq.NO_ROW, tq.NOT_AVAILABLE]


def test_a_calculated_value_lists_its_parts():
    """Income from continuing operations was derived (50 - 5 = 45): it is
    marked calculated, its two parts follow, and a note names the
    function."""
    inputs, components, notes = traced([("income_continuing_ops", 0)])
    assert inputs.iloc[0]["How"] == tq.CALCULATED
    assert inputs["Input"].tolist()[1:] == [
        f"↳ {trace.input_label('net_income')}",
        f"↳ {trace.input_label('income_discontinued_ops')}",
    ]
    assert len(components) == 2
    assert "derive_income_continuing_ops" in notes[0]


def test_signal_7_in_q3_uses_the_prior_fiscal_year_end():
    """Option C: the Q3 10-Q's own count at the prior fiscal year end
    (98 at Dec 31, 2023), not the count at Sep 30, 2023 (90)."""
    inputs, components, _ = traced([(piotroski.PRIOR_SHARES, 1)])
    assert inputs.iloc[0]["Input"] == tq.PRIOR_SHARES_Q1_Q3
    assert inputs.iloc[0]["Value used"] == "98 shares"
    assert components.iloc[0]["Single quarter"] == "at 2023-12-31"


def test_every_sample_value_adds_up_to_its_sources():
    """On the committed sample, for one company-quarter with an M-Score,
    every value the whole M-Score uses is traced and adds up to its
    source rows (no "not matched")."""
    sample = config.SAMPLE_DIR
    scores = pd.read_parquet(sample / "scores_quarterly.parquet")
    row = scores[scores["m_score"].notna()].iloc[-1]
    cik = int(row["cik"])
    ttm_df = pd.read_parquet(
        sample / "financials_ttm.parquet", filters=[("cik", "==", cik)]
    )
    sources_df = pd.read_parquet(
        sample / "ttm_sources.parquet", filters=[("cik", "==", cik)]
    )
    facts_df = pd.read_parquet(
        sample / "facts_quarterly.parquet", filters=[("cik", "==", cik)]
    )
    part = trace.SCORES["m_score"][trace.ALL_PARTS]
    inputs, components, _ = tq.trace_ttm_inputs(
        part.inputs,
        int(row["fiscal_year"]),
        int(row["fiscal_quarter"]),
        ttm_df,
        sources_df,
        facts_df,
    )
    assert trace.NOT_MATCHED not in set(inputs["How"])
    assert not components.empty


@pytest.mark.parametrize(
    "value, total, expected", [(440, 440, True), (440, 439, False)]
)
def test_adds_up(value, total, expected):
    """A value adds up when its rows sum to it (within 50 cents)."""
    rows = pd.DataFrame({"value": [total]})
    assert tq.adds_up(value, rows) is expected
