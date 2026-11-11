"""Build the Phase 1 hand-verification sheet (verification/).

For a few companies and one fiscal year, lists revenue, net income, total
assets and CFO as stored in financials_annual, traced through facts_long
to the XBRL tag, accession and filing link. Blank columns are filled in
by hand from the actual 10-K.

Run with:
    python -m src.pipeline.tieout
"""

import pandas as pd

import config

# Chosen to test three fiscal year ends: Apple (September), Walmart
# (January, labeled the PRIOR year by the Compustat convention), and
# Coca-Cola (December).
TIEOUT_COMPANIES = {320193: "Apple", 104169: "Walmart", 21344: "Coca-Cola"}
TIEOUT_FISCAL_YEAR = 2024
TIEOUT_ITEMS = ["revenue", "net_income", "total_assets", "cfo"]
TIEOUT_PATH = config.PROJECT_ROOT / "verification" / "phase1_tieout.csv"

# Same window financials.py uses to attach a fact to a fiscal year end.
REPORT_DATE_TOLERANCE = pd.Timedelta(days=7)


def trace_value(facts_long_df, cik, line_item, period_end):
    """Return the original facts_long row behind one financials value.

    Returns None when no original fact is within the window, which means
    the value was derived (see derived_items) or is missing.
    """
    rows = facts_long_df[
        (facts_long_df["cik"] == cik)
        & (facts_long_df["line_item"] == line_item)
        & facts_long_df["is_original"]
    ]
    gap = (rows["period_end"] - period_end).abs()
    rows = rows[gap <= REPORT_DATE_TOLERANCE]
    return None if rows.empty else rows.iloc[0]


def build_tieout(
    financials_df,
    facts_long_df,
    companies=TIEOUT_COMPANIES,
    fiscal_year=TIEOUT_FISCAL_YEAR,
    items=TIEOUT_ITEMS,
):
    """Return one row per company and line item for hand checking."""
    rows = []
    for cik, name in companies.items():
        year = financials_df[
            (financials_df["cik"] == cik)
            & (financials_df["fiscal_year"] == fiscal_year)
        ]
        if year.empty:
            continue
        year = year.iloc[0]
        for item in items:
            fact = trace_value(facts_long_df, cik, item, year["period_end"])
            value = year[item]
            rows.append(
                {
                    "company": name,
                    "cik": cik,
                    "fiscal_year": fiscal_year,
                    "period_end": year["period_end"].date(),
                    "line_item": item,
                    "pipeline_value_usd": value,
                    # 10-Ks usually present figures in millions.
                    "pipeline_value_millions": round(value / 1e6, 1),
                    "xbrl_tag": None if fact is None else fact["xbrl_tag"],
                    "form": None if fact is None else fact["form"],
                    "accession": None if fact is None else fact["accession"],
                    "filed_date": (
                        None if fact is None else fact["filed_date"].date()
                    ),
                    "filing_url": None if fact is None else fact["filing_url"],
                    # Filled in by hand from the 10-K:
                    "ten_k_value_millions": "",
                    "ten_k_page_or_statement": "",
                    "matches": "",
                    "notes": "",
                }
            )
    return pd.DataFrame(rows)


def main():
    """Write verification/phase1_tieout.csv from data/processed/."""
    financials_df = pd.read_parquet(config.FINANCIALS_PATH)
    facts_long_df = pd.read_parquet(config.FACTS_LONG_PATH)
    tieout_df = build_tieout(financials_df, facts_long_df)
    TIEOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tieout_df.to_csv(TIEOUT_PATH, index=False)
    print(tieout_df.drop(columns=["filing_url"]).to_string(index=False))


if __name__ == "__main__":
    main()
