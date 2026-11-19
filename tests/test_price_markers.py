"""Tests for src/pipeline/price_markers.py with a tiny fake data folder.

Prices: ticker TST trades every weekday from Monday 2024-01-08 to Friday
2024-03-29 at a price that is easy to read: 100 on the first day, then
1 more each trading day (so 2024-02-12, the 26th trading day, is 125).
A second ticker, OTHER, checks that only TST's rows are read.

Company 1 (TST) has three scored years:
- FY2022, 10-K filed 2023-02-15: before prices begin -> left out;
- FY2023, 10-K filed Saturday 2024-02-10 -> marker on Monday 2024-02-12;
- FY2024, 10-K filed 2025-02-03: after prices end -> left out.
Its FY2021 10-K is in financials_annual but was not scored -> no marker.
Company 2 has no ticker; company 3's ticker GONE has no prices.
"""

import pandas as pd
import pytest

from src.pipeline import price_markers as pm

DAYS = pd.bdate_range("2024-01-08", "2024-03-29").astype("datetime64[ns]")


def write_tables(folder):
    """Write companies, prices, financials_annual and scores."""
    pd.DataFrame(
        {
            "cik": [1, 2, 3],
            "ticker": pd.array(["TST", None, "GONE"], dtype="string"),
        }
    ).to_parquet(folder / "companies.parquet")
    tst = pd.DataFrame(
        {
            "ticker": "TST",
            "date": DAYS,
            "adj_close": [100.0 + day for day in range(len(DAYS))],
        }
    )
    other = pd.DataFrame({"ticker": "OTHER", "date": DAYS, "adj_close": 5.0})
    pd.concat([tst, other], ignore_index=True).astype(
        {"ticker": "string"}
    ).to_parquet(folder / "prices.parquet")
    pd.DataFrame(
        {
            "cik": [1, 1, 1, 1],
            "fiscal_year": [2021, 2022, 2023, 2024],
            "filed_date": pd.to_datetime(
                ["2022-02-15", "2023-02-15", "2024-02-10", "2025-02-03"]
            ),
        }
    ).to_parquet(folder / "financials_annual.parquet")
    pd.DataFrame(
        {
            "cik": [1, 1, 1],
            "fiscal_year": [2022, 2023, 2024],
            "flags_raised": pd.array([0, 2, 1], dtype="Int64"),
            "m_score": [-2.5, -1.2, -1.5],
            "m_flag": pd.array([False, True, True], dtype="boolean"),
            "z_zone": pd.array(["safe", "distress", "grey"], dtype="string"),
            "f_band": pd.array(["strong", "middle", "middle"], dtype="string"),
        }
    ).to_parquet(folder / "scores.parquet")


@pytest.fixture
def data_dir(tmp_path):
    """Return a folder holding the fake tables."""
    write_tables(tmp_path)
    return tmp_path


def test_reads_only_the_company_ticker(data_dir):
    """TST's 60 trading days are returned, oldest first; no OTHER rows."""
    result = pm.price_markers(data_dir, 1)
    assert result.status == pm.STATUS_OK
    assert result.ticker == "TST"
    assert len(result.prices) == len(DAYS)
    assert result.prices["adj_close"].iloc[0] == 100.0
    assert result.prices["date"].is_monotonic_increasing


def test_saturday_filing_moves_to_monday(data_dir):
    """Filed Saturday 2024-02-10 -> marker on Monday 2024-02-12 at its
    close, 125 (the 26th trading day: 100 + 25)."""
    markers = pm.price_markers(data_dir, 1).markers
    assert markers["fiscal_year"].tolist() == [2023]
    marker = markers.iloc[0]
    assert marker["filed_date"] == pd.Timestamp("2024-02-10")
    assert marker["marker_date"] == pd.Timestamp("2024-02-12")
    assert marker["adj_close"] == 125.0
    assert marker["flags_raised"] == 2
    assert bool(marker["m_flag"])
    assert marker["z_zone"] == "distress"
    assert marker["f_band"] == "middle"


def test_filings_outside_the_prices_are_left_out_with_a_reason(data_dir):
    """FY2022 (filed before prices begin) and FY2024 (after they end)
    are not moved to another date; they are listed as skipped. FY2021
    was never scored, so it is neither a marker nor skipped."""
    skipped = pm.price_markers(data_dir, 1).skipped
    assert skipped[["fiscal_year", "reason"]].values.tolist() == [
        [2022, pm.BEFORE_PRICES],
        [2024, pm.AFTER_PRICES],
    ]


def test_filing_on_a_trading_day_stays_on_that_day():
    """A filing on a day with a price is marked that same day."""
    prices = pd.DataFrame({"date": DAYS, "adj_close": 1.0})
    filings = pd.DataFrame(
        {
            "fiscal_year": [2023],
            "filed_date": [pd.Timestamp("2024-02-14")],
            "flags_raised": [0],
            "m_score": [-3.0],
            "m_flag": [False],
            "z_zone": ["safe"],
            "f_band": ["strong"],
        }
    )
    markers, skipped = pm.build_markers(prices, filings)
    assert markers["marker_date"].tolist() == [pd.Timestamp("2024-02-14")]
    assert skipped.empty


def test_no_ticker_returns_an_empty_result(data_dir):
    """Company 2 has no ticker: status no_ticker, empty tables."""
    result = pm.price_markers(data_dir, 2)
    assert result.status == pm.STATUS_NO_TICKER
    assert result.ticker is None
    assert result.prices.empty and result.markers.empty
    assert result.skipped.empty


def test_ticker_without_prices_returns_an_empty_result(data_dir):
    """Company 3's ticker GONE has no price rows: status no_prices."""
    result = pm.price_markers(data_dir, 3)
    assert result.status == pm.STATUS_NO_PRICES
    assert result.ticker == "GONE"
    assert result.prices.empty and result.markers.empty
