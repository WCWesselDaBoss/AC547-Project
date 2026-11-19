"""Build the tiny made-up tables the Phase 3 dashboard is developed on.

Run from the project root:  python tests/fixtures/build_app_fixtures.py

Writes five Parquet files to tests/fixtures/app/ with the same names,
columns and types as data/sample/, so the app reads them exactly like
real data (set EQR_DATA_SOURCE=fixture; see config.app_data_dir).

Where the numbers come from:

- financials_annual: Phase 2's hand-checkable fixture, unchanged (three
  companies, FY2021 to FY2023; see build_fixtures.py for what each one
  is meant to test).
- companies: those three companies plus two excluded ones, so the
  screener's "how many were excluded and why" note has something to show.
- facts_long: one original fact per line item per year, under each item's
  first-choice tag in Phase 1's tag map, plus Phase 2's prior-year share
  comparatives and ONE restated value (see RESTATED_FACT). The restated
  value lets the trace panel prove it shows the original, not the latest.
- scores and score_drivers: built by Phase 2's own functions from the
  tables above. Hand-typing scores would let a displayed score disagree
  with the inputs the trace panel shows for it; building them keeps the
  two consistent. This runs in test setup, never in the app, so the rule
  that the app does not compute scores (CLAUDE.md section 3) still holds.

The files are committed; tests/test_app_fixtures.py fails if they ever
differ from what this script builds.
"""

import sys
from pathlib import Path

import pandas as pd

# Allow running this file directly: put the project root on the import
# path so config, src and tests can be imported.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
from src.pipeline import facts, tag_map  # noqa: E402
from src.scores import build_scores, drivers  # noqa: E402
from tests.fixtures import build_fixtures  # noqa: E402

APP_FIXTURE_DIR = config.APP_FIXTURE_DIR

# Made-up companies. CIKs 101-103 match Phase 2's financials fixture.
# 101 and 102 share a 2-digit industry (35) so they rank against each
# other; 103 is alone in industry 73, so its percentile ranks are blank,
# which the dashboard must handle. 104 and 105 are excluded and have no
# financials, like the excluded companies in the real companies table.
# Columns: cik, name, sic, sic_description, ticker, is_excluded,
#   exclusion_reason
COMPANY_ROWS = [
    (101, "Steady Co", 3571, "Electronic Computers", "STDY", False, None),
    (102, "Stretch Co", 3576, "Computer Communications Equipment", "STRC",
     False, None),
    # No ticker: section 4 allows it, and real delisted filers lack one.
    (103, "Service Co", 7372, "Services-Prepackaged Software", None,
     False, None),
    (104, "Fixture Bank Co", 6022, "State Commercial Banks", "FBNK", True,
     "financial_sic_6000_6799"),
    (105, "No Industry Co", None, None, None, True, "missing_sic"),
]  # fmt: skip

# One restatement: Stretch Co's FY2023 10-K shows FY2022 revenue as $700M
# instead of the $750M first reported. Scores must still use $750M, the
# number investors saw at the time (CLAUDE.md section 4).
RESTATED_FACT = {
    "cik": 102,
    "line_item": "revenue",
    "fiscal_year": 2022,
    "value": 700 * build_fixtures.MILLION,
    "restating_10k_year": 2023,
}

# Items whose value is a total over the year rather than a balance on one
# date; only these have a period_start (section 4: NaT for instants).
DURATION_ITEMS = {
    item
    for item, spec in tag_map.ALL_ITEMS.items()
    if spec["period"] == tag_map.DURATION
}


def build_companies_fixture():
    """Return the companies fixture in section 4 column order and types."""
    companies_df = pd.DataFrame(
        COMPANY_ROWS,
        columns=[
            "cik",
            "name",
            "sic",
            "sic_description",
            "ticker",
            "is_excluded",
            "exclusion_reason",
        ],
    )
    # Same type map as Phase 1's build_companies, so the fixture cannot
    # drift from the real table.
    return companies_df.astype(
        {
            "cik": "int64",
            "name": "string",
            "sic": "Int64",
            "sic_description": "string",
            "ticker": "string",
            "is_excluded": "bool",
            "exclusion_reason": "string",
        }
    )


def fact_row(filing, line_item, value, fiscal_year, period_end, original):
    """Return one facts_long row (before contract types) as a dict.

    filing is a financials_annual row: it supplies the cik, accession and
    filed date of the 10-K that reported the value.
    """
    spec = tag_map.ALL_ITEMS[line_item]
    period_start = pd.NaT
    if line_item in DURATION_ITEMS:
        # A full year ending on period_end, e.g. 2022-01-01 to 2022-12-31.
        period_start = (
            period_end - pd.DateOffset(years=1) + pd.Timedelta(days=1)
        )
    return {
        "cik": filing.cik,
        "line_item": line_item,
        # The first-choice tag, so the trace panel shows a real tag name.
        "tag": spec["tags"][0],
        "value": value,
        "unit": spec["unit"],
        "period_start": period_start,
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "form": "10-K",
        "accession": filing.accession,
        "filed_date": filing.filed_date,
        "is_original": original,
    }


def build_facts_long_fixture(financials_df):
    """Return facts_long: every reported value in the financials fixture.

    A NaN in financials means "not reported", so it gets no fact row (the
    real facts_long never stores a missing value). Share counts come from
    Phase 2's fixture builder, which already holds the split-adjusted
    prior-year comparatives that F-Score signal 7 needs.
    """
    fact_rows = []
    for filing in financials_df.itertuples():
        for line_item in tag_map.ALL_ITEMS:
            value = getattr(filing, line_item)
            if line_item == "shares_outstanding" or pd.isna(value):
                continue
            fact_rows.append(
                fact_row(
                    filing,
                    line_item,
                    value,
                    filing.fiscal_year,
                    filing.period_end,
                    original=True,
                )
            )

    restated = RESTATED_FACT
    restating_filing = financials_df[
        (financials_df["cik"] == restated["cik"])
        & (financials_df["fiscal_year"] == restated["restating_10k_year"])
    ].iloc[0]
    fact_rows.append(
        fact_row(
            restating_filing,
            restated["line_item"],
            restated["value"],
            restated["fiscal_year"],
            restating_filing.period_end - pd.DateOffset(years=1),
            original=False,
        )
    )

    # Phase 2's share facts are already in contract types; rename the
    # tag column back so both parts go through the same conversion below.
    share_facts_df = build_fixtures.build_facts_long_fixture(
        financials_df
    ).rename(columns={"xbrl_tag": "tag"})
    share_facts_df = share_facts_df.drop(columns="filing_url")
    all_facts_df = pd.concat(
        [pd.DataFrame(fact_rows), share_facts_df], ignore_index=True
    )
    # Phase 1's converter adds filing_url and sets section 4 types.
    return facts.to_contract_types(all_facts_df)


def build_app_fixtures():
    """Return a dict of table name -> DataFrame for every APP_TABLES file."""
    financials_df = build_fixtures.build_financials_fixture()
    companies_df = build_companies_fixture()
    facts_long_df = build_facts_long_fixture(financials_df)
    # Phase 2's pipeline, exactly as run_pipeline.py uses it; the log
    # rows (second return value) are not needed for a fixture.
    scores_df, _ = build_scores.build_scores(
        financials_df, facts_long_df, companies_df
    )
    score_drivers_df = drivers.build_score_drivers(scores_df)
    return {
        "companies": companies_df,
        "facts_long": facts_long_df,
        "financials_annual": financials_df,
        "scores": scores_df,
        "score_drivers": score_drivers_df,
    }


def main():
    """Write every app fixture table to tests/fixtures/app/."""
    APP_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for table, table_df in build_app_fixtures().items():
        path = APP_FIXTURE_DIR / f"{table}.parquet"
        table_df.to_parquet(path, index=False)
        print(f"Wrote {len(table_df)} rows to {path}")


if __name__ == "__main__":
    main()
