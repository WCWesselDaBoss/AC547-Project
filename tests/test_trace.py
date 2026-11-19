"""Tests for click-to-trace (app/trace.py) on the hand-checkable fixture.

Fixture values (tests/fixtures/build_app_fixtures.py), in $ millions:
- Steady Co (101) FY2023: receivables 121, revenue 1,210; FY2022:
  receivables 110, revenue 1,100. 10-K accession 0000000101-24-000001.
- Stretch Co (102) FY2022 revenue: 750 as first reported, restated to
  700 in the FY2023 10-K. FY2023 10-K shows FY2022 shares as 120M
  (after a 2-for-1 split).
- Service Co (103): no cost of revenue in any year.
"""

import pandas as pd
import pytest

import config
from app import trace
from src.pipeline import facts, tag_map
from src.scores import beneish, piotroski

MILLION = 1_000_000


def read_fixture(table):
    """Read one app fixture table."""
    return pd.read_parquet(config.APP_FIXTURE_DIR / f"{table}.parquet")


def company(table, cik):
    """Return one company's rows of a fixture table."""
    table_df = read_fixture(table)
    return table_df[table_df["cik"] == cik].reset_index(drop=True)


def run_trace(cik, fiscal_year, score, part=trace.ALL_PARTS, fin=None):
    """Trace one part for one fixture company-year; return (table, notes)."""
    if fin is None:
        fin = company("financials_annual", cik)
    return trace.trace_inputs(
        trace.SCORES[score][part].inputs,
        fiscal_year,
        fin,
        company("facts_long", cik),
    )


def test_trace_uses_phase_2_input_maps():
    """Each part lists exactly the inputs Phase 2's code reads."""
    for index, inputs in beneish.INDEX_INPUTS.items():
        assert trace.SCORES["m_score"][index].inputs == inputs
    for signal, inputs in piotroski.SIGNAL_INPUTS.items():
        assert trace.SCORES["f_score"][signal].inputs == inputs


def test_every_part_has_a_formula_and_function():
    """No part is missing its formula, label or computing function."""
    for parts in trace.SCORES.values():
        for part in parts.values():
            assert part.formula and part.label
            assert trace.function_name(part.function).startswith("src.scores.")


def test_formulas_come_from_config_coefficients():
    """The M and Z'' equations print config's published coefficients."""
    m_text = trace.m_formula()
    assert m_text.startswith("M = -4.84 + 0.920 x DSRI + 0.528 x GMI")
    assert "- 0.172 x SGAI" in m_text and "- 0.327 x LVGI" in m_text
    assert trace.z_formula().startswith(
        "Z'' = 6.560 x X1 + 3.260 x X2 + 6.720 x X3 + 1.050 x X4"
    )


def test_dsri_inputs_trace_to_the_10k():
    """Steady Co FY2023 DSRI: four reported values with tags and links."""
    table, notes = run_trace(101, 2023, "m_score", "dsri")
    assert list(table["Value used"]) == [
        "$121,000,000",
        "$1,210,000,000",
        "$110,000,000",
        "$1,100,000,000",
    ]
    assert list(table["Fiscal year"]) == ["FY2023", "FY2023", "FY2022"] + [
        "FY2022"
    ]
    assert set(table["Source"]) == {trace.REPORTED}
    first = table.iloc[0]
    assert first["XBRL tag"] == tag_map.LINE_ITEMS["receivables"]["tags"][0]
    assert first["Accession"] == "0000000101-24-000001"
    assert first["10-K filed"] == "2024-02-20"
    assert first["Period"] == "at Dec 31, 2023"
    assert first["Filing"] == facts.edgar_filing_url(
        101, "0000000101-24-000001"
    )
    assert table.iloc[1]["Period"] == "Jan 1, 2023 to Dec 31, 2023"
    assert notes == []


def test_original_value_used_and_restatement_shown():
    """Stretch Co FY2023 SGI: FY2022 revenue is the original $750M."""
    table, _ = run_trace(102, 2023, "m_score", "sgi")
    prior = table[table["Fiscal year"] == "FY2022"].iloc[0]
    assert prior["Value used"] == "$750,000,000"
    assert prior["Accession"] == "0000000102-23-000001"
    assert prior["Later filings"] == (
        "Restated to $700,000,000 in the 10-K filed 2024-02-20"
    )
    current = table[table["Fiscal year"] == "FY2023"].iloc[0]
    assert current["Later filings"] == ""


def test_missing_input_is_shown_not_hidden():
    """Service Co GMI: cost of revenue is "Not reported" in both years."""
    table, _ = run_trace(103, 2023, "m_score", "gmi")
    cost = table[table["Input"] == "Cost of revenue"]
    assert list(cost["Source"]) == [trace.NOT_REPORTED] * 2
    assert list(cost["Value used"]) == ["Not available"] * 2


def test_year_before_first_10k_says_no_data():
    """FY2021 SGI needs FY2020, which the fixture does not have."""
    table, _ = run_trace(101, 2021, "m_score", "sgi")
    assert table.iloc[1]["Source"] == trace.NO_YEAR


def test_prior_shares_come_from_the_same_10k():
    """Signal 7 uses 120M from the FY2023 10-K, not the original 60M."""
    table, _ = run_trace(102, 2023, "f_score", "f_no_new_shares")
    prior = table[table["Input"] == trace.PRIOR_SHARES_LABEL].iloc[0]
    assert prior["Value used"] == "120,000,000 shares"
    assert prior["Accession"] == "0000000102-24-000001"
    assert prior["Fiscal year"] == "FY2022"


def test_calculated_value_shows_its_parts_and_function():
    """A derived item is labeled, its parts traced, its function named."""
    fin = company("financials_annual", 101)
    fin["derived_items"] = fin["derived_items"].astype("string")
    fin.loc[fin["fiscal_year"] == 2023, "derived_items"] = (
        "income_continuing_ops"
    )
    table, notes = run_trace(101, 2023, "m_score", "tata", fin=fin)
    assert table.iloc[0]["Source"] == trace.CALCULATED
    assert table.iloc[0]["Accession"] == ""
    part = table.iloc[1]
    assert part["Input"] == "↳ Net income"
    assert part["Source"] == trace.COMPONENT
    assert part["Value used"] == "$121,000,000"
    assert len(notes) == 1
    assert "derive_income_continuing_ops()" in notes[0]


def test_value_without_a_matching_fact_is_flagged():
    """If no filing fact has the value used, the panel says so."""
    fin = company("financials_annual", 101)
    fin.loc[fin["fiscal_year"] == 2023, "revenue"] = 1_234 * MILLION
    table, _ = run_trace(101, 2023, "m_score", "sgi", fin=fin)
    assert table.iloc[0]["Source"] == trace.NOT_MATCHED
    assert pd.isna(table.iloc[0]["Filing"])


@pytest.mark.parametrize(
    ("score", "part", "expected"),
    [
        ("m_score", trace.ALL_PARTS, "-2.484"),
        ("f_score", trace.ALL_PARTS, "4 of 9"),
        ("f_score", "f_cfo_positive", "✅ Yes (1 point)"),
        ("m_score", "gmi", "1.000"),
    ],
)
def test_stored_result_text(score, part, expected):
    """The stored result is shown as stored, in readable form."""
    scores_df = read_fixture("scores")
    row = scores_df[
        (scores_df["cik"] == 101) & (scores_df["fiscal_year"] == 2023)
    ].iloc[0]
    assert trace.stored_result_text(row, trace.SCORES[score][part]) == expected
