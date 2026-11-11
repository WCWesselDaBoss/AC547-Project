"""Download daily adjusted closing prices and build the prices table.

Tickers come only from SEC's data (companies.ticker). Companies without a
ticker, mostly ones that were acquired, delisted or went bankrupt, stay
unmatched: guessing a ticker by name could attach another company's
prices (CLAUDE.md section 6, No silent fixes).

Run on its own with:
    python -m src.pipeline.prices
"""

import json
import time
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf

import config

PRICES_COVERAGE_LOG = config.LOG_DIR / "prices_coverage.csv"
PRICES_COMPANY_LOG = config.LOG_DIR / "prices_by_company.csv"


def ticker_cache_path(ticker):
    """Return the cache file for one ticker.

    The "ticker_" prefix matters on Windows: names like CON, PRN or AUX
    are reserved device names there, even with a file extension.
    """
    return config.PRICES_RAW_DIR / f"ticker_{ticker}.parquet"


def scored_companies(companies_df, financials_df):
    """Return companies with at least one size-floor year FY2012 onward.

    These are the companies Phase 2 can score, so they are the ones that
    need prices. Each row carries the first and last passing year's
    filing dates, which set the dates the prices must cover.
    """
    passing = financials_df[
        financials_df["passes_size_floor"]
        & (financials_df["fiscal_year"] >= config.FIRST_FISCAL_YEAR)
    ]
    windows = passing.groupby("cik").agg(
        first_filed=("filed_date", "min"),
        last_filed=("filed_date", "max"),
    )
    last_year = financials_df.groupby("cik")["fiscal_year"].max()
    scored = companies_df[["cik", "name", "ticker"]].merge(
        windows, left_on="cik", right_index=True
    )
    scored["last_10k_fiscal_year"] = scored["cik"].map(last_year)
    return scored.reset_index(drop=True)


def adj_close_to_long(raw_df, tickers):
    """Turn yfinance's wide download into (ticker, date, adj_close) rows.

    Returns (long DataFrame, list of tickers with no prices). yfinance
    reports a failed ticker only as an all-NaN column, so every requested
    ticker is checked explicitly.
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame(columns=["ticker", "date", "adj_close"]), list(
            tickers
        )
    adj_close = raw_df["Adj Close"]
    if isinstance(adj_close, pd.Series):  # a single ticker comes back 1-D
        adj_close = adj_close.to_frame(tickers[0])
    long_df = (
        adj_close.rename_axis(index="date", columns="ticker")
        .stack()
        .rename("adj_close")
        .reset_index()
    )
    long_df = long_df.dropna(subset=["adj_close"])
    found = set(long_df["ticker"])
    return long_df, [ticker for ticker in tickers if ticker not in found]


def download_batch(tickers, start, end, downloader=yf.download):
    """Download one batch and return (long DataFrame, failed tickers).

    downloader is a parameter so tests can pass a fake instead of
    calling Yahoo.
    """
    raw_df = downloader(
        tickers,
        start=start,
        end=end,
        # Keep Yahoo's split- and dividend-adjusted close in its own
        # column, rather than silently replacing Close with it.
        auto_adjust=False,
        actions=False,
        threads=False,
        progress=False,
    )
    return adj_close_to_long(raw_df, tickers)


def save_ticker_files(long_df):
    """Write each ticker's rows to its own cache file."""
    config.PRICES_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for ticker, ticker_df in long_df.groupby("ticker"):
        ticker_df.to_parquet(ticker_cache_path(ticker), index=False)


def download_prices(
    tickers,
    start=config.PRICE_START_DATE,
    end=None,
    batch_size=config.PRICE_BATCH_SIZE,
    pause_seconds=config.PRICE_PAUSE_SECONDS,
    downloader=yf.download,
    sleep=time.sleep,
):
    """Download every ticker not already cached; return failed tickers.

    Failures are retried once, one ticker at a time, because a single bad
    response in a batch can fail tickers that are actually fine.
    """
    end = end or date.today().isoformat()
    to_fetch = [t for t in tickers if not ticker_cache_path(t).exists()]
    failed = []
    for start_index in range(0, len(to_fetch), batch_size):
        batch = to_fetch[start_index : start_index + batch_size]
        long_df, batch_failed = download_batch(batch, start, end, downloader)
        save_ticker_files(long_df)
        failed.extend(batch_failed)
        print(f"  {start_index + len(batch):,} of {len(to_fetch):,} tickers")
        sleep(pause_seconds)

    still_failed = []
    for ticker in failed:
        long_df, retry_failed = download_batch(
            [ticker], start, end, downloader
        )
        save_ticker_files(long_df)
        still_failed.extend(retry_failed)
        sleep(pause_seconds)
    return still_failed


def load_cached_prices(tickers):
    """Combine cached ticker files into the prices table (contract types)."""
    frames = [
        pd.read_parquet(ticker_cache_path(ticker))
        for ticker in tickers
        if ticker_cache_path(ticker).exists()
    ]
    prices_df = pd.concat(frames, ignore_index=True)
    dates = pd.to_datetime(prices_df["date"])
    # Yahoo dates can carry the exchange's time zone; the contract wants
    # plain calendar dates.
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    prices_df["date"] = dates.dt.normalize()
    prices_df = prices_df.astype(
        {"ticker": "string", "date": "datetime64[ns]", "adj_close": "float64"}
    )
    # Contract column order (section 4), whatever order the cache used.
    prices_df = prices_df[["ticker", "date", "adj_close"]]
    return prices_df.sort_values(["ticker", "date"]).reset_index(drop=True)


def drop_invalid_series(prices_df):
    """Remove every ticker whose adjusted close is ever zero or negative.

    A real price cannot be zero or negative. When Yahoo's adjusted close
    is, its adjustment factor is wrong (seen after large special
    distributions or repeated reverse splits), which mis-scales the whole
    series, not only those days. Dropping just the bad rows would keep
    wrong-but-plausible prices, so the whole ticker is removed and named.
    Returns (clean DataFrame, sorted list of removed tickers).
    """
    invalid = sorted(
        prices_df.loc[prices_df["adj_close"] <= 0, "ticker"].unique()
    )
    clean_df = prices_df[~prices_df["ticker"].isin(invalid)]
    return clean_df.reset_index(drop=True), invalid


def company_price_coverage(scored_df, prices_df, tolerance_days=None):
    """Return one row per scored company describing its price coverage.

    Needed window: from the first passing year's 10-K filing date to 12
    months after the last passing year's filing (capped at the latest
    trading day in the data). "Full" means prices start and end within
    the tolerance of that window.
    """
    tolerance = pd.Timedelta(
        days=tolerance_days or config.PRICE_COVERAGE_TOLERANCE_DAYS
    )
    spans = prices_df.groupby("ticker")["date"].agg(["min", "max"])
    latest_trading_day = prices_df["date"].max()
    coverage = scored_df.merge(
        spans, left_on="ticker", right_index=True, how="left"
    )
    needed_end = (coverage["last_filed"] + pd.DateOffset(years=1)).clip(
        upper=latest_trading_day
    )
    coverage["has_ticker"] = coverage["ticker"].notna()
    coverage["has_prices"] = coverage["min"].notna()
    coverage["has_full_price_history"] = (
        coverage["has_prices"]
        & (coverage["min"] <= coverage["first_filed"] + tolerance)
        & (coverage["max"] >= needed_end - tolerance)
    )
    coverage["stopped_filing"] = (
        coverage["last_10k_fiscal_year"] < config.LAST_FISCAL_YEAR - 1
    )
    return coverage.rename(
        columns={"min": "first_price_date", "max": "last_price_date"}
    )


def coverage_summary(coverage_df, failed_tickers, invalid_tickers=()):
    """Return the headline counts for the README and the go/no-go call."""
    stopped = coverage_df["stopped_filing"]
    rows = [
        ("scored_companies", len(coverage_df)),
        ("with_sec_ticker", int(coverage_df["has_ticker"].sum())),
        ("without_sec_ticker", int((~coverage_df["has_ticker"]).sum())),
        ("with_any_prices", int(coverage_df["has_prices"].sum())),
        (
            "with_full_price_history",
            int(coverage_df["has_full_price_history"].sum()),
        ),
        ("ticker_but_yahoo_returned_nothing", len(failed_tickers)),
        ("ticker_removed_invalid_adjusted_close", len(invalid_tickers)),
        ("stopped_filing_by_fy2023", int(stopped.sum())),
        (
            "stopped_filing_with_no_prices",
            int((stopped & ~coverage_df["has_prices"]).sum()),
        ),
    ]
    return pd.DataFrame(rows, columns=["measure", "count"])


def write_manifest(tickers, failed_tickers, end, invalid_tickers=()):
    """Record when prices were downloaded and which tickers failed.

    Yahoo recalculates adjusted closes after every split or dividend, so
    results can only be reproduced against a known download date.
    """
    manifest = {
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": config.PRICE_START_DATE,
        "end_exclusive": end,
        "tickers_requested": len(tickers),
        "tickers_failed": sorted(failed_tickers),
        "tickers_removed_invalid_adjusted_close": list(invalid_tickers),
    }
    config.PRICES_MANIFEST.write_text(json.dumps(manifest, indent=2))


def main(download=True):
    """Build the prices table for scored companies plus SPY.

    With download=False nothing is fetched: the table is rebuilt from the
    cached ticker files, so the pipeline can run offline. Tickers with no
    cache file are then reported as failed.
    """
    companies_df = pd.read_parquet(config.COMPANIES_PATH)
    financials_df = pd.read_parquet(config.FINANCIALS_PATH)
    scored_df = scored_companies(companies_df, financials_df)
    tickers = sorted(scored_df["ticker"].dropna().unique())
    tickers.append(config.MARKET_BENCHMARK_TICKER)
    config.PRICES_RAW_DIR.mkdir(parents=True, exist_ok=True)

    if download:
        # Keep yfinance's timezone cache inside the project, not the
        # user's profile, so runs are self-contained.
        yf.set_tz_cache_location(str(config.RAW_DIR / "yfinance_cache"))
        end = date.today().isoformat()
        print(f"Downloading prices for {len(tickers):,} tickers")
        failed = download_prices(tickers, end=end)
    else:
        failed = [t for t in tickers if not ticker_cache_path(t).exists()]
    prices_df, invalid = drop_invalid_series(load_cached_prices(tickers))
    if download:
        write_manifest(tickers, failed, end, invalid)

    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    prices_df.to_parquet(config.PRICES_PATH, index=False)

    coverage_df = company_price_coverage(scored_df, prices_df)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    coverage_df.to_csv(PRICES_COMPANY_LOG, index=False)
    summary_df = coverage_summary(coverage_df, failed, invalid)
    summary_df.to_csv(PRICES_COVERAGE_LOG, index=False)
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
