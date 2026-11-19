"""Stock prices and 10-K warning markers for one company's price chart.

The dashboard's price chart (app/components/price_chart.py) only draws
what this module returns; every date and value is decided here, so it
can be tested outside the app (CLAUDE.md section 3).

For one company this returns:
- its daily adjusted close, read from prices.parquet for its ticker only;
- one marker per scored fiscal year, placed on the date that year's
  original 10-K became public, with the flag count and the three
  verdicts from the scores table.

It reads the finished tables only: companies, prices and
financials_annual (Phase 1) and scores (Phase 2). Nothing is written.
"""

from pathlib import Path
from typing import NamedTuple

import pandas as pd

import config

MARKER_COLUMNS = [
    "fiscal_year",
    "filed_date",
    "marker_date",
    "adj_close",
    "flags_raised",
    "m_score",
    "m_flag",
    "z_zone",
    "f_band",
]
SKIPPED_COLUMNS = ["fiscal_year", "filed_date", "reason"]
SCORE_COLUMNS = [
    "cik",
    "fiscal_year",
    "flags_raised",
    "m_score",
    "m_flag",
    "z_zone",
    "f_band",
]

# Why a marker was left out of the chart.
BEFORE_PRICES = "before_price_history"
AFTER_PRICES = "after_price_history"

# What the chart can show for the company.
STATUS_OK = "ok"
STATUS_NO_TICKER = "no_ticker"
STATUS_NO_PRICES = "no_prices"


class PriceMarkers(NamedTuple):
    """Everything the price chart needs for one company.

    status: "ok", "no_ticker" or "no_prices". prices: date, adj_close.
    markers: MARKER_COLUMNS. skipped: filings left off the chart because
    they fall outside the price history (fiscal_year, filed_date,
    reason). With no ticker or no prices, the three tables are empty.
    """

    status: str
    ticker: str | None
    prices: pd.DataFrame
    markers: pd.DataFrame
    skipped: pd.DataFrame


def empty_prices():
    """Return an empty price table with the right columns and types."""
    return pd.DataFrame(
        {
            "date": pd.Series([], dtype="datetime64[ns]"),
            "adj_close": pd.Series([], dtype="float64"),
        }
    )


def empty_markers():
    """Return an empty marker table with the right columns."""
    return pd.DataFrame(columns=MARKER_COLUMNS)


def empty_skipped():
    """Return an empty skipped-filings table with the right columns."""
    return pd.DataFrame(columns=SKIPPED_COLUMNS)


def ticker_for(companies_path, cik):
    """Return the company's ticker, or None if it has none."""
    row = pd.read_parquet(
        companies_path,
        columns=["cik", "ticker"],
        filters=[("cik", "==", int(cik))],
    )
    if row.empty or pd.isna(row["ticker"].iloc[0]):
        return None
    return str(row["ticker"].iloc[0])


def ticker_prices(prices_path, ticker):
    """Return date and adj_close for one ticker, oldest first.

    The filter is applied while reading, so only that ticker's rows are
    loaded, not the whole prices file (about 9 million rows in full). A
    folder with no prices file (the app's test fixtures) gives an empty
    table: prices are optional for the dashboard.
    """
    if not Path(prices_path).exists():
        return empty_prices()
    prices = pd.read_parquet(
        prices_path,
        columns=["ticker", "date", "adj_close"],
        filters=[("ticker", "==", ticker)],
    )
    prices = prices.dropna(subset=["adj_close"])
    return (
        prices[["date", "adj_close"]]
        .sort_values("date")
        .reset_index(drop=True)
    )


def build_markers(prices_df, filings_df):
    """Return (markers, skipped) from one company's prices and filings.

    filings_df has one row per scored fiscal year: fiscal_year,
    filed_date and the score columns in SCORE_COLUMNS.

    Each marker goes on the first trading day ON OR AFTER the 10-K's
    filed_date (a Saturday filing moves to Monday), and never on the
    fiscal year-end. A 10-K is filed weeks or months after its year
    ends, and until then nobody outside the company could see its
    numbers or the warnings computed from them. Placing the marker
    earlier would show the chart "knowing" a warning before the public
    did. "Trading day" means a day this stock has a price, so every
    marker sits on a real price.

    A filing dated before the first price or after the last one is not
    moved to another date; it is returned in skipped with the reason.
    """
    dates = pd.DatetimeIndex(prices_df["date"])
    filings = filings_df.sort_values("fiscal_year").reset_index(drop=True)
    filed = pd.to_datetime(filings["filed_date"])
    before = filed < dates[0]
    after = filed > dates[-1]

    skipped = filings.loc[before | after, ["fiscal_year", "filed_date"]]
    skipped = skipped.assign(
        reason=[
            BEFORE_PRICES if b else AFTER_PRICES
            for b in before[before | after]
        ]
    )

    placed = filings[~(before | after)].copy()
    # searchsorted(side="left") finds the first price date >= filed_date.
    positions = dates.searchsorted(
        pd.to_datetime(placed["filed_date"]), side="left"
    )
    placed["marker_date"] = dates[positions]
    placed["adj_close"] = prices_df["adj_close"].to_numpy()[positions]
    return (
        placed[MARKER_COLUMNS].reset_index(drop=True),
        skipped[SKIPPED_COLUMNS].reset_index(drop=True),
    )


def company_filings(data_dir, cik):
    """Return the scored fiscal years for one company, with the filing
    date of each year's original 10-K.

    filed_date comes from financials_annual, which keeps only filings
    whose form is exactly "10-K" (src/pipeline/financials.py), so it is
    the original filing, never a 10-K/A. The scores table supplies the
    flags; only fiscal years it scored get a marker.
    """
    data_dir = Path(data_dir)
    scores = pd.read_parquet(
        data_dir / "scores.parquet",
        columns=SCORE_COLUMNS,
        filters=[("cik", "==", int(cik))],
    )
    filed = pd.read_parquet(
        data_dir / "financials_annual.parquet",
        columns=["cik", "fiscal_year", "filed_date"],
        filters=[("cik", "==", int(cik))],
    )
    filings = scores.merge(filed, on=["cik", "fiscal_year"], how="left")
    return filings.dropna(subset=["filed_date"])


def price_markers(data_dir, cik):
    """Return PriceMarkers for one company from the tables in data_dir.

    A company with no ticker, or a ticker with no prices, gets the
    matching status and empty tables rather than an error, so the chart
    can show a plain message instead.
    """
    data_dir = Path(data_dir)
    ticker = ticker_for(data_dir / "companies.parquet", cik)
    if ticker is None:
        return PriceMarkers(
            STATUS_NO_TICKER,
            None,
            empty_prices(),
            empty_markers(),
            empty_skipped(),
        )
    prices = ticker_prices(data_dir / "prices.parquet", ticker)
    if prices.empty:
        return PriceMarkers(
            STATUS_NO_PRICES,
            ticker,
            empty_prices(),
            empty_markers(),
            empty_skipped(),
        )
    markers, skipped = build_markers(prices, company_filings(data_dir, cik))
    return PriceMarkers(STATUS_OK, ticker, prices, markers, skipped)


def market_prices(data_dir):
    """Return the market benchmark's (SPY's) adjusted closes, oldest
    first; empty if the folder has no prices."""
    return ticker_prices(
        Path(data_dir) / "prices.parquet", config.MARKET_BENCHMARK_TICKER
    )


def rebase_to_100(prices_df, markers_df, market_df):
    """Return (company line, market line, markers) rebased to 100.

    For comparing the company with SPY on one scale: each line is
    divided by its own adjusted close on the first date shown (the
    company's first price date) and multiplied by 100, so both start at
    100 and 130 means "up 30% since then". The market line covers only
    the company's date range. Marker heights are rebased with the
    company's line so they stay on it. Each returned table has a value
    column in place of adj_close.
    """
    start, end = prices_df["date"].iloc[0], prices_df["date"].iloc[-1]
    base = prices_df["adj_close"].iloc[0]
    company = prices_df.assign(value=prices_df["adj_close"] / base * 100)
    in_range = market_df[
        (market_df["date"] >= start) & (market_df["date"] <= end)
    ]
    market = in_range.copy()
    if market.empty:
        market["value"] = pd.Series([], dtype="float64")
    else:
        market["value"] = (
            market["adj_close"] / market["adj_close"].iloc[0] * 100
        )
    markers = markers_df.assign(value=markers_df["adj_close"] / base * 100)
    return (
        company[["date", "value"]].reset_index(drop=True),
        market[["date", "value"]].reset_index(drop=True),
        markers.drop(columns="adj_close").reset_index(drop=True),
    )
