"""Build the hand-checkable Phase 2 test fixture tables.

Run from the project root:  python tests/fixtures/build_fixtures.py

The Parquet file is committed, but this script is its source of truth:
Parquet cannot be read in a text editor, so the numbers live here in a
readable table where a reviewer can check every input on a calculator.
tests/test_fixtures.py fails if the committed file and this script ever
disagree.

Three made-up companies, FY2021 to FY2023. FY2021 is a prior year only
(like FY2011 in the real table), so FY2022 and FY2023 are the scored years.

- cik 101, Steady Co: every line item grows exactly 10% a year, so every
  ratio stays the same. All M-Score indexes equal 1 except SGI (1.1), and
  the "higher than last year" F-Score tests tie, which checks that a tie
  does not earn a point.
- cik 102, Stretch Co: FY2022 looks like aggressive accounting
  (receivables triple while sales grow 50%, profit not backed by cash);
  FY2023 collapses into a loss and does a 2-for-1 stock split. Covers a
  flagged M-Score, negative net income, a distress-zone Z'' and the
  same-filing share comparison for F-Score signal 7.
- cik 103, Service Co: reports no cost_of_revenue in any year, like the
  13,612 real company-years in CLAUDE.md section 4. This is the missing
  input: GMI and F-Score signal 8 cannot be computed.

Edge cases that need a broken row (zero sales, a missing prior year row)
are made inside the tests by editing a copy of this table, so this file
stays a clean, readable baseline.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Allow running this file directly (python tests/fixtures/...): put the
# project root on the import path so config and src can be imported.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline import facts, financials  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent
FINANCIALS_FIXTURE_PATH = FIXTURE_DIR / "financials_annual_fixture.parquet"
FACTS_LONG_FIXTURE_PATH = FIXTURE_DIR / "facts_long_fixture.parquet"

# Money is entered in millions so the table is easy to read, then scaled
# to whole dollars, because section 4 stores money in whole US dollars.
MILLION = 1_000_000

# Line items in $ millions (shares_outstanding in plain shares).
# Each row: cik, fiscal_year, then the 18 line items in section 4 order.
LINE_ITEM_COLUMNS = [
    "revenue",
    "cost_of_revenue",
    "sga",
    "depreciation",
    "operating_income",
    "income_continuing_ops",
    "net_income",
    "cfo",
    "receivables",
    "current_assets",
    "ppe_net",
    "total_assets",
    "current_liabilities",
    "long_term_debt",
    "total_liabilities",
    "retained_earnings",
    "stockholders_equity",
    "shares_outstanding",
]

NAN = np.nan

# fmt: off
# black would put one number per line; a grid is far easier to check.
# Columns: cik, fy, revenue, cogs, sga, dep, op_inc, inc_cont, net_inc,
#   cfo, receivables, cur_assets, ppe_net, tot_assets, cur_liab, lt_debt,
#   tot_liab, ret_earn, equity, shares
FIXTURE_ROWS = [
    # Steady Co: FY2022 = FY2021 x 1.1, FY2023 = FY2021 x 1.21.
    (101, 2021, 1000, 600, 200, 50, 150, 100, 100, 120,
     100, 400, 500, 1000, 200, 300, 500, 300, 500, 100_000_000),
    (101, 2022, 1100, 660, 220, 55, 165, 110, 110, 132,
     110, 440, 550, 1100, 220, 330, 550, 330, 550, 100_000_000),
    (101, 2023, 1210, 726, 242, 60.5, 181.5, 121, 121, 145.2,
     121, 484, 605, 1210, 242, 363, 605, 363, 605, 100_000_000),
    # Stretch Co: FY2022 aggressive growth, FY2023 a loss.
    (102, 2021, 500, 300, 100, 20, 80, 50, 50, 60,
     50, 200, 200, 500, 100, 100, 250, 100, 250, 50_000_000),
    (102, 2022, 750, 500, 100, 25, 125, 100, 100, 20,
     150, 350, 250, 800, 200, 200, 500, 200, 300, 60_000_000),
    # FY2023: 2-for-1 stock split, so 60M shares became 120M.
    (102, 2023, 600, 480, 120, 25, -25, -50, -50, -10,
     120, 300, 260, 800, 300, 250, 600, 150, 200, 120_000_000),
    # Service Co: no cost_of_revenue reported (NaN, never 0).
    (103, 2021, 200, NAN, 50, 10, 40, 30, 30, 40,
     20, 80, 100, 300, 50, 100, 150, 60, 150, 20_000_000),
    (103, 2022, 220, NAN, 55, 10, 44, 33, 33, 30,
     22, 90, 110, 320, 60, 90, 160, 70, 160, 20_000_000),
    (103, 2023, 250, NAN, 60, 12, 50, 40, 40, 50,
     30, 100, 120, 350, 70, 80, 170, 90, 180, 19_000_000),
]
# fmt: on


def build_financials_fixture():
    """Return the fixture financials_annual table in contract types.

    Uses financials.to_contract_types, the same function Phase 1 uses for
    the real table, so the fixture cannot drift from section 4's column
    order and types.
    """
    fixture_df = pd.DataFrame(
        FIXTURE_ROWS, columns=["cik", "fiscal_year"] + LINE_ITEM_COLUMNS
    )
    money_columns = [c for c in LINE_ITEM_COLUMNS if c != "shares_outstanding"]
    fixture_df[money_columns] = fixture_df[money_columns] * MILLION

    # Calendar-year companies: period ends Dec 31, 10-K filed late
    # February. Accession numbers follow SEC's dashed format but are fake.
    year = fixture_df["fiscal_year"]
    fixture_df["period_end"] = pd.to_datetime(year.astype(str) + "-12-31")
    fixture_df["filed_date"] = pd.to_datetime(
        (year + 1).astype(str) + "-02-20"
    )
    fixture_df["accession"] = (
        fixture_df["cik"].astype(str).str.zfill(10)
        + "-"
        + ((year + 1) % 100).astype(str).str.zfill(2)
        + "-000001"
    )
    fixture_df["passes_size_floor"] = financials.passes_size_floor(
        fixture_df["revenue"], fixture_df["total_assets"]
    )
    # Every value is "reported", so no line item is derived.
    fixture_df["derived_items"] = pd.NA

    # Component columns. No company has discontinued operations,
    # non-controlling interests or temporary equity, so those are missing
    # (NaN, not 0, per section 4). The two totals mirror the balance sheet.
    fixture_df["income_discontinued_ops"] = NAN
    fixture_df["liabilities_and_equity"] = fixture_df["total_assets"]
    fixture_df["equity_including_nci"] = fixture_df["stockholders_equity"]
    fixture_df["temporary_equity_total"] = NAN
    fixture_df["temporary_equity_parent"] = NAN
    fixture_df["redeemable_nci"] = NAN

    return financials.to_contract_types(fixture_df)


# Prior-year share counts as printed in each 10-K's comparative column,
# keyed by (cik, fiscal year of the 10-K). Stretch Co's FY2023 10-K shows
# FY2022 as 120M, not the 60M originally reported, because the 2-for-1
# split is applied to the comparative figure. F-Score signal 7 must use
# this restated number (CLAUDE.md section 4).
PRIOR_SHARES_IN_FILING = {
    (101, 2022): 100_000_000,
    (101, 2023): 100_000_000,
    (102, 2022): 50_000_000,
    (102, 2023): 120_000_000,
    (103, 2022): 20_000_000,
    (103, 2023): 20_000_000,
}


def build_facts_long_fixture(financials_df):
    """Return a facts_long fixture holding the share-count facts.

    Each 10-K reports its own year's shares (the original value) and,
    where listed in PRIOR_SHARES_IN_FILING, the prior year's shares as a
    comparative (not original). Only shares are included because signal
    7 is the only score input read from facts_long.
    """
    fact_rows = []
    for row in financials_df.itertuples():
        filing = {
            "cik": row.cik,
            "line_item": "shares_outstanding",
            "tag": "CommonStockSharesOutstanding",
            "unit": "shares",
            "period_start": pd.NaT,
            "form": "10-K",
            "accession": row.accession,
            "filed_date": row.filed_date,
        }
        fact_rows.append(
            filing
            | {
                "value": row.shares_outstanding,
                "period_end": row.period_end,
                "fiscal_year": row.fiscal_year,
                "is_original": True,
            }
        )
        prior_shares = PRIOR_SHARES_IN_FILING.get((row.cik, row.fiscal_year))
        if prior_shares is not None:
            fact_rows.append(
                filing
                | {
                    "value": prior_shares,
                    "period_end": row.period_end - pd.DateOffset(years=1),
                    "fiscal_year": row.fiscal_year - 1,
                    "is_original": False,
                }
            )
    return facts.to_contract_types(pd.DataFrame(fact_rows))


def main():
    """Write the fixture Parquet files next to this script."""
    financials_df = build_financials_fixture()
    financials_df.to_parquet(FINANCIALS_FIXTURE_PATH, index=False)
    print(f"Wrote {len(financials_df)} rows to {FINANCIALS_FIXTURE_PATH}")
    facts_long_df = build_facts_long_fixture(financials_df)
    facts_long_df.to_parquet(FACTS_LONG_FIXTURE_PATH, index=False)
    print(f"Wrote {len(facts_long_df)} rows to {FACTS_LONG_FIXTURE_PATH}")


if __name__ == "__main__":
    main()
