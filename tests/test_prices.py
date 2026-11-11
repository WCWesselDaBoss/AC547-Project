"""Tests for src/pipeline/prices.py. A fake downloader replaces Yahoo."""

import numpy as np
import pandas as pd
import pytest

import config
from src.pipeline import prices

DATES = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])


def fake_yahoo_frame(values_by_ticker):
    """Build a frame shaped like yf.download(auto_adjust=False) output.

    A ticker mapped to None comes back as an all-NaN column, which is how
    yfinance reports a failed ticker.
    """
    columns = pd.MultiIndex.from_product(
        [["Adj Close", "Close"], list(values_by_ticker)],
        names=["Price", "Ticker"],
    )
    data = {}
    for field in ("Adj Close", "Close"):
        for ticker, values in values_by_ticker.items():
            data[(field, ticker)] = (
                [np.nan] * len(DATES) if values is None else values
            )
    return pd.DataFrame(data, index=DATES, columns=columns).rename_axis("Date")


class FakeDownloader:
    """Returns pre-set frames per ticker and records each call."""

    def __init__(self, values_by_ticker):
        """Store what each ticker should return."""
        self.values_by_ticker = values_by_ticker
        self.calls = []

    def __call__(self, tickers, **kwargs):
        """Mimic yf.download for the requested tickers."""
        self.calls.append((list(tickers), kwargs))
        return fake_yahoo_frame(
            {t: self.values_by_ticker.get(t) for t in tickers}
        )


@pytest.fixture(autouse=True)
def temp_price_cache(tmp_path, monkeypatch):
    """Point the price cache at a temporary folder for every test."""
    monkeypatch.setattr(config, "PRICES_RAW_DIR", tmp_path / "prices")


def test_long_format_and_failed_tickers():
    """Good tickers become rows; an all-NaN ticker is reported failed."""
    raw = fake_yahoo_frame({"AAA": [1.0, 2.0, 3.0], "BAD": None})
    long_df, failed = prices.adj_close_to_long(raw, ["AAA", "BAD"])
    assert failed == ["BAD"]
    assert long_df["ticker"].unique().tolist() == ["AAA"]
    assert long_df["adj_close"].tolist() == [1.0, 2.0, 3.0]


def test_download_uses_adjusted_close_unthreaded():
    """Adj Close is kept separate and threads are off (Windows lock)."""
    downloader = FakeDownloader({"AAA": [1.0, 2.0, 3.0]})
    prices.download_batch(["AAA"], "2024-01-01", "2024-01-05", downloader)
    kwargs = downloader.calls[0][1]
    assert kwargs["auto_adjust"] is False
    assert kwargs["threads"] is False


def test_cached_tickers_are_skipped():
    """A second run downloads nothing that is already cached."""
    downloader = FakeDownloader({"AAA": [1.0, 2.0, 3.0]})
    prices.download_prices(
        ["AAA"], end="2024-01-05", downloader=downloader, sleep=lambda s: 0
    )
    prices.download_prices(
        ["AAA"], end="2024-01-05", downloader=downloader, sleep=lambda s: 0
    )
    assert len(downloader.calls) == 1


def test_failed_ticker_retried_alone_then_reported():
    """BAD fails in its batch, is retried once alone, and is returned."""
    downloader = FakeDownloader({"AAA": [1.0, 2.0, 3.0], "BAD": None})
    failed = prices.download_prices(
        ["AAA", "BAD"],
        end="2024-01-05",
        downloader=downloader,
        sleep=lambda s: 0,
    )
    assert failed == ["BAD"]
    assert downloader.calls[-1][0] == ["BAD"]


def test_windows_reserved_ticker_names_are_safe():
    """CON is a reserved Windows name; the cache file is prefixed."""
    assert prices.ticker_cache_path("CON").name == "ticker_CON.parquet"


def test_loaded_prices_match_contract():
    """Exactly ticker, date, adj_close with the agreed types."""
    downloader = FakeDownloader({"AAA": [1.0, 2.0, 3.0]})
    prices.download_prices(
        ["AAA"], end="2024-01-05", downloader=downloader, sleep=lambda s: 0
    )
    prices_df = prices.load_cached_prices(["AAA"])
    assert list(prices_df.columns) == ["ticker", "date", "adj_close"]
    assert prices_df["date"].dtype == "datetime64[ns]"
    assert prices_df["adj_close"].dtype == "float64"


def make_scored(rows):
    """Build scored-company rows (cik, ticker, first_filed, last_filed,
    last_10k_fiscal_year)."""
    scored = pd.DataFrame(
        rows,
        columns=[
            "cik",
            "ticker",
            "first_filed",
            "last_filed",
            "last_10k_fiscal_year",
        ],
    )
    for column in ("first_filed", "last_filed"):
        scored[column] = pd.to_datetime(scored[column])
    return scored


def make_prices(ticker, first, last):
    """Daily prices for one ticker between two dates."""
    days = pd.date_range(first, last, freq="D")
    return pd.DataFrame({"ticker": ticker, "date": days, "adj_close": 1.0})


def test_full_history_needs_start_and_end_covered():
    """FULL covers the window; LATE starts a year late; none for NOTKR."""
    scored = make_scored(
        [
            (1, "FULL", "2015-03-01", "2020-03-01", 2025),
            (2, "LATE", "2015-03-01", "2020-03-01", 2025),
            (3, None, "2015-03-01", "2018-03-01", 2018),
        ]
    )
    prices_df = pd.concat(
        [
            make_prices("FULL", "2015-02-27", "2021-03-05"),
            make_prices("LATE", "2016-03-01", "2021-03-05"),
            make_prices("SPY", "2012-01-03", "2026-11-10"),
        ]
    )
    coverage = prices.company_price_coverage(scored, prices_df).set_index(
        "cik"
    )
    assert coverage.loc[1, "has_full_price_history"]
    assert not coverage.loc[2, "has_full_price_history"]
    assert not coverage.loc[3, "has_ticker"]
    assert coverage.loc[3, "stopped_filing"]

    summary = prices.coverage_summary(coverage.reset_index(), ["GONE"])
    counts = dict(zip(summary["measure"], summary["count"]))
    assert counts["with_full_price_history"] == 1
    assert counts["stopped_filing_with_no_prices"] == 1
    assert counts["ticker_but_yahoo_returned_nothing"] == 1


def test_needed_end_capped_at_latest_trading_day():
    """A 2025 filing cannot need prices beyond the last trading day."""
    scored = make_scored([(1, "NEW", "2025-02-01", "2026-02-01", 2025)])
    prices_df = make_prices("NEW", "2025-02-01", "2026-11-10")
    coverage = prices.company_price_coverage(scored, prices_df)
    assert coverage.loc[0, "has_full_price_history"]


def test_series_with_nonpositive_price_is_removed_whole():
    """BAD has one negative day: all of BAD goes, GOOD stays untouched."""
    prices_df = pd.concat(
        [
            make_prices("GOOD", "2024-01-01", "2024-01-05"),
            make_prices("BAD", "2024-01-01", "2024-01-05").assign(
                adj_close=[5.0, 4.0, -1.0, 3.0, 2.0]
            ),
        ]
    )
    clean_df, invalid = prices.drop_invalid_series(prices_df)
    assert invalid == ["BAD"]
    assert set(clean_df["ticker"]) == {"GOOD"}
    assert len(clean_df) == 5
