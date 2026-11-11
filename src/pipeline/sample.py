"""Build the small committed sample in data/sample/ (CLAUDE.md section 6).

A fresh clone has no data/raw or data/processed (both gitignored), so the
app runs from these four small tables instead. Companies are chosen by a
fixed rule, not at random, so rebuilding the sample from the same data
always gives the same companies.

Run on its own with:
    python -m src.pipeline.sample
"""

import pandas as pd

import config
from src.pipeline import prices

# How many sample slots go to each kind of company. Together they show the
# app's normal case and its edge cases.
QUOTA_FULL_HISTORY = 30  # complete prices: the normal case
QUOTA_STOPPED_NO_PRICES = 10  # stopped filing, no prices: survivorship
QUOTA_PARTIAL_PRICES = 5  # has a ticker but incomplete price history

TABLE_FILES = {
    "companies": config.COMPANIES_PATH,
    "facts_long": config.FACTS_LONG_PATH,
    "financials_annual": config.FINANCIALS_PATH,
    "prices": config.PRICES_PATH,
}


def company_profiles(companies_df, financials_df, prices_df):
    """Return one row per scored company with what the selection needs.

    Columns: cik, sic_division (first digit of SIC), passing_years, and
    the price-coverage flags from prices.company_price_coverage.
    """
    scored_df = prices.scored_companies(companies_df, financials_df)
    coverage_df = prices.company_price_coverage(scored_df, prices_df)
    passing = financials_df[
        financials_df["passes_size_floor"]
        & (financials_df["fiscal_year"] >= config.FIRST_FISCAL_YEAR)
    ]
    passing_years = passing.groupby("cik").size()
    sic = companies_df.set_index("cik")["sic"]
    profiles = coverage_df[
        ["cik", "has_prices", "has_full_price_history", "stopped_filing"]
    ].copy()
    profiles["passing_years"] = profiles["cik"].map(passing_years)
    profiles["sic_division"] = profiles["cik"].map(sic) // 1000
    # Most years first (richest examples), then CIK so ties never depend
    # on row order.
    return profiles.sort_values(
        ["passing_years", "cik"], ascending=[False, True]
    ).reset_index(drop=True)


def round_robin_by_division(candidates_df, count):
    """Take count companies, cycling through SIC divisions in turn.

    Within each division the input order is kept (most years first), so
    the sample covers many industries instead of filling up with the
    largest one (pharmaceuticals is the biggest SIC group).
    """
    queues = {
        division: list(group["cik"])
        for division, group in candidates_df.groupby("sic_division", sort=True)
    }
    chosen = []
    while len(chosen) < count and any(queues.values()):
        for division in sorted(queues):
            if queues[division] and len(chosen) < count:
                chosen.append(queues[division].pop(0))
    return chosen


def select_sample_ciks(
    profiles_df,
    size=config.SAMPLE_SIZE,
    anchors=config.SAMPLE_ANCHOR_CIKS,
    extras=config.SAMPLE_EXTRA_CIKS,
):
    """Return the sample CIKs: anchors and extras first, then the quotas.

    Anchors and case-study extras are always included, even if that makes
    the sample larger than size, because the demo depends on them.
    """
    chosen = list(dict.fromkeys(list(anchors) + list(extras)))

    def remaining(mask):
        """Profiles matching mask that are not already chosen."""
        return profiles_df[mask & ~profiles_df["cik"].isin(chosen)]

    chosen += round_robin_by_division(
        remaining(profiles_df["has_full_price_history"]), QUOTA_FULL_HISTORY
    )
    stopped = remaining(
        profiles_df["stopped_filing"] & ~profiles_df["has_prices"]
    )
    chosen += round_robin_by_division(stopped, QUOTA_STOPPED_NO_PRICES)
    partial = remaining(
        profiles_df["has_prices"] & ~profiles_df["has_full_price_history"]
    )
    chosen += round_robin_by_division(partial, QUOTA_PARTIAL_PRICES)
    if len(chosen) < size:
        rest = remaining(pd.Series(True, index=profiles_df.index))
        chosen += list(rest["cik"].head(size - len(chosen)))
    return chosen


def sample_tables(tables, ciks):
    """Return the four tables cut down to the sample companies.

    prices is cut by those companies' tickers plus SPY, which every
    return calculation needs as the market benchmark.
    """
    ciks = set(ciks)
    sample = {
        name: tables[name][tables[name]["cik"].isin(ciks)]
        for name in ("companies", "facts_long", "financials_annual")
    }
    tickers = set(sample["companies"]["ticker"].dropna())
    tickers.add(config.MARKET_BENCHMARK_TICKER)
    sample["prices"] = tables["prices"][
        tables["prices"]["ticker"].isin(tickers)
    ]
    return {
        name: table.reset_index(drop=True) for name, table in sample.items()
    }


def main():
    """Select the sample and write the four tables to data/sample/."""
    tables = {
        name: pd.read_parquet(path) for name, path in TABLE_FILES.items()
    }
    profiles_df = company_profiles(
        tables["companies"], tables["financials_annual"], tables["prices"]
    )
    ciks = select_sample_ciks(profiles_df)
    config.SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    for name, table in sample_tables(tables, ciks).items():
        table.to_parquet(config.SAMPLE_DIR / f"{name}.parquet", index=False)
        print(f"  {name}: {len(table):,} rows")
    print(f"Sample: {len(ciks)} companies written to {config.SAMPLE_DIR}")


if __name__ == "__main__":
    main()
