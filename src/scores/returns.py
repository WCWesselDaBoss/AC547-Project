"""Stretch goal: 12-month returns after each 10-K, flagged vs. unflagged.

For each scored company-year whose company has a ticker:
- start = the first trading day (SPY's calendar) AFTER filed_date, so
  the 10-K was public before the "purchase";
- end = the last trading day on or before start + 12 months;
- ret_12m = adj_close(end) / adj_close(start) - 1. Adjusted closes
  include dividends and splits, so this is a buy-and-hold total return;
- mkt_ret_12m = the same for SPY over the same dates;
- excess_ret_12m = ret_12m - mkt_ret_12m.

A return is computed only when the stock has a price within
config.PRICE_COVERAGE_TOLERANCE_DAYS of BOTH dates
(has_full_price_history). A company delisted mid-window gets no return:
a partial-window return would be an estimate (CLAUDE.md section 2).

READ BEFORE USING THE RESULTS
- Survivorship bias: companies that failed or were delisted (often the
  worst performers, and plausibly the manipulators) mostly have no
  Yahoo prices, so they drop out. Results are biased UPWARD and cover
  mainly survivors.
- Correlation, not cause: a return gap between flagged and unflagged
  companies does not show that the flag causes or predicts returns;
  size, industry and timing differ between the groups.
- Windows overlap in calendar time (most 10-Ks are filed Feb-Mar), so
  observations are not independent; treat counts as descriptive only.
- Tickers are current tickers from SEC; a reused ticker could attach
  another company's history to an old filing.
"""

import argparse

import numpy as np
import pandas as pd

import config

RETURNS_COLUMNS = [
    "cik",
    "fiscal_year",
    "filed_date",
    "ticker",
    "ret_12m",
    "mkt_ret_12m",
    "excess_ret_12m",
    "has_full_price_history",
]
HOLDING_PERIOD = pd.DateOffset(months=12)


def window_dates(filed_dates, market_dates):
    """Return (start, end) trading days for each filing date.

    start = first market trading day strictly after the filing date;
    end = last market trading day on or before start + 12 months.
    NaT when the window is not complete in the price data yet.
    """
    calendar = pd.Series(np.sort(market_dates.unique()))
    start_index = calendar.searchsorted(filed_dates.to_numpy(), side="right")
    starts = pd.Series(pd.NaT, index=filed_dates.index, dtype="datetime64[ns]")
    has_start = start_index < len(calendar)
    starts[has_start] = calendar.to_numpy()[start_index[has_start]]

    targets = starts + HOLDING_PERIOD
    end_index = calendar.searchsorted(targets.to_numpy(), side="right") - 1
    ends = pd.Series(pd.NaT, index=filed_dates.index, dtype="datetime64[ns]")
    # The window is complete only if the data run past the target date.
    complete = has_start & (targets <= calendar.iloc[-1]).to_numpy()
    ends[complete] = calendar.to_numpy()[end_index[complete]]
    starts[~complete] = pd.NaT
    return starts, ends


def price_near(prices_df, tickers, dates, direction, tolerance_days):
    """Return each ticker's adj_close nearest a date, within tolerance.

    direction 'forward' takes the first price on or after the date (for
    the start), 'backward' the last on or before it (for the end).
    """
    lookup = pd.DataFrame(
        {"ticker": tickers.to_numpy(), "date": dates.to_numpy()},
        index=tickers.index,
    )
    # merge_asof needs identical key types on both sides, so both use
    # the contract's types ("string" tickers, nanosecond dates).
    lookup = lookup.astype({"ticker": "string", "date": "datetime64[ns]"})
    lookup["order"] = np.arange(len(lookup))
    valid = lookup.dropna(subset=["ticker", "date"]).sort_values("date")
    prices = prices_df.astype(
        {"ticker": "string", "date": "datetime64[ns]"}
    ).sort_values("date")
    matched = pd.merge_asof(
        valid,
        prices,
        on="date",
        by="ticker",
        direction=direction,
        tolerance=pd.Timedelta(days=tolerance_days),
    )
    result = pd.Series(np.nan, index=lookup.index)
    result.iloc[matched["order"].to_numpy()] = matched["adj_close"].to_numpy()
    return result


def compute_returns(scores_df, financials_df, companies_df, prices_df):
    """Return the returns table: one row per scored year with a ticker."""
    tolerance = config.PRICE_COVERAGE_TOLERANCE_DAYS
    benchmark = config.MARKET_BENCHMARK_TICKER
    keys = ["cik", "fiscal_year"]
    years_df = (
        scores_df[keys]
        .merge(financials_df[keys + ["filed_date"]], on=keys, how="left")
        .merge(companies_df[["cik", "ticker"]], on="cik", how="left")
    )
    years_df = years_df[years_df["ticker"].notna()].reset_index(drop=True)

    market_prices = prices_df[prices_df["ticker"] == benchmark]
    starts, ends = window_dates(years_df["filed_date"], market_prices["date"])

    stock_start = price_near(
        prices_df, years_df["ticker"], starts, "forward", tolerance
    )
    stock_end = price_near(
        prices_df, years_df["ticker"], ends, "backward", tolerance
    )
    benchmark_tickers = pd.Series(benchmark, index=years_df.index)
    market_start = price_near(
        prices_df, benchmark_tickers, starts, "forward", 0
    )
    market_end = price_near(prices_df, benchmark_tickers, ends, "backward", 0)

    years_df["has_full_price_history"] = (
        stock_start.notna() & stock_end.notna() & market_start.notna()
    ).to_numpy()
    full = years_df["has_full_price_history"]
    years_df["ret_12m"] = (stock_end / stock_start - 1).where(full)
    years_df["mkt_ret_12m"] = (market_end / market_start - 1).where(full)
    years_df["excess_ret_12m"] = years_df["ret_12m"] - years_df["mkt_ret_12m"]
    return years_df[RETURNS_COLUMNS].astype(
        {
            "cik": "int64",
            "fiscal_year": "int64",
            "filed_date": "datetime64[ns]",
            "ticker": "string",
            "ret_12m": "float64",
            "mkt_ret_12m": "float64",
            "excess_ret_12m": "float64",
            "has_full_price_history": "bool",
        }
    )


def coverage_summary(scores_df, returns_df):
    """Return (metric, count) rows describing price coverage."""
    return [
        ("scored_company_years", len(scores_df)),
        ("with_ticker", len(returns_df)),
        (
            "with_full_12m_prices",
            int(returns_df["has_full_price_history"].sum()),
        ),
        ("with_m_flag", int(scores_df["m_flag"].notna().sum())),
    ]


def compare_flagged(scores_df, returns_df):
    """Return count, mean and median excess return by M-Score flag.

    Only company-years with a full 12-month window and an M-Score are
    compared; NA flags (no score) are left out rather than counted as
    unflagged.
    """
    merged = returns_df[returns_df["has_full_price_history"]].merge(
        scores_df[["cik", "fiscal_year", "m_flag"]],
        on=["cik", "fiscal_year"],
    )
    merged = merged[merged["m_flag"].notna()]
    merged["group"] = np.where(
        merged["m_flag"].astype(bool), "flagged", "not_flagged"
    )
    summary = merged.groupby("group")["excess_ret_12m"].agg(
        ["count", "mean", "median"]
    )
    return summary.reindex(["flagged", "not_flagged"])


def main(argv=None):
    """Build returns from data/processed/ (or data/sample/ with --sample)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args(argv)
    source_dir = config.SAMPLE_DIR if args.sample else config.PROCESSED_DIR
    scores_path = (
        source_dir / "scores.parquet" if args.sample else config.SCORES_PATH
    )
    output_path = (
        source_dir / "returns.parquet" if args.sample else config.RETURNS_PATH
    )
    scores_df = pd.read_parquet(scores_path)
    returns_df = compute_returns(
        scores_df,
        pd.read_parquet(source_dir / "financials_annual.parquet"),
        pd.read_parquet(source_dir / "companies.parquet"),
        pd.read_parquet(source_dir / "prices.parquet"),
    )
    returns_df.to_parquet(output_path, index=False)

    suffix = "_sample" if args.sample else ""
    coverage = pd.DataFrame(
        coverage_summary(scores_df, returns_df), columns=["metric", "count"]
    )
    comparison = compare_flagged(scores_df, returns_df)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(config.LOG_DIR / f"returns{suffix}_coverage.csv")
    comparison.to_csv(config.LOG_DIR / f"returns{suffix}_by_flag.csv")
    print(coverage.to_string(index=False))
    print("\n12-month excess return vs SPY, by M-Score flag (-1.78):")
    print(comparison.to_string())
    print(
        "\nCaution: delisted companies mostly lack prices, so these results"
        " are biased upward,\nand a difference shows correlation, not"
        " cause."
    )
    print(f"Wrote {len(returns_df)} rows to {output_path}")


if __name__ == "__main__":
    main()
