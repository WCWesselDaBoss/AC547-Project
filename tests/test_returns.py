"""Tests for src/scores/returns.py with hand-made prices.

Prices: SPY trades every weekday of 2024-2025. Stock AAA trades on the
same days at a price that is easy to read: 100 until 2024-12-31, then
120. Stock DDD is delisted (stops trading) on 2024-06-28.
"""

import numpy as np
import pandas as pd
import pytest

from src.scores import returns

DAYS = pd.bdate_range("2024-01-01", "2025-12-31").astype("datetime64[ns]")


def make_prices():
    """Return a prices table (section 4 types) for SPY, AAA and DDD."""
    spy = pd.DataFrame({"ticker": "SPY", "date": DAYS, "adj_close": 400.0})
    # SPY 400 -> 440 (+10%) from 2025.
    spy.loc[spy["date"] >= "2025-01-01", "adj_close"] = 440.0
    aaa = pd.DataFrame({"ticker": "AAA", "date": DAYS, "adj_close": 100.0})
    aaa.loc[aaa["date"] >= "2025-01-01", "adj_close"] = 120.0
    ddd_days = DAYS[DAYS <= "2024-06-28"]
    ddd = pd.DataFrame({"ticker": "DDD", "date": ddd_days, "adj_close": 50.0})
    prices = pd.concat([spy, aaa, ddd], ignore_index=True)
    return prices.astype({"ticker": "string"})


def make_inputs(rows):
    """Return (scores, financials, companies) for (cik, ticker, filed,
    m_flag) rows, all fiscal year 2023."""
    scores_df = pd.DataFrame(
        {
            "cik": [r[0] for r in rows],
            "fiscal_year": 2023,
            "m_flag": pd.array([r[3] for r in rows], dtype="boolean"),
        }
    )
    financials_df = pd.DataFrame(
        {
            "cik": [r[0] for r in rows],
            "fiscal_year": 2023,
            "filed_date": pd.to_datetime([r[2] for r in rows]),
        }
    )
    companies_df = pd.DataFrame(
        {
            "cik": [r[0] for r in rows],
            "ticker": pd.array([r[1] for r in rows], dtype="string"),
        }
    )
    return scores_df, financials_df, companies_df


def test_window_starts_after_filing_and_lasts_12_months():
    """Filed Friday 2024-03-01 -> start Monday 2024-03-04 (the day AFTER
    filing); end = last trading day on/before 2025-03-04 = 2025-03-04."""
    filed = pd.Series(pd.to_datetime(["2024-03-01"]))
    starts, ends = returns.window_dates(filed, pd.Series(DAYS))
    assert starts[0] == pd.Timestamp("2024-03-04")
    assert ends[0] == pd.Timestamp("2025-03-04")


def test_window_not_complete_yet_gives_no_dates():
    """Filed 2025-06-02: start + 12 months is past the last price
    (2025-12-31), so there is no complete window yet."""
    filed = pd.Series(pd.to_datetime(["2025-06-02"]))
    starts, ends = returns.window_dates(filed, pd.Series(DAYS))
    assert pd.isna(starts[0]) and pd.isna(ends[0])


def test_buy_and_hold_and_excess_return():
    """AAA bought at 100 (2024-03-04), worth 120 on 2025-03-04: +20%.
    SPY 400 -> 440: +10%. Excess = 20% - 10% = +10%."""
    inputs = make_inputs([(1, "AAA", "2024-03-01", True)])
    result = returns.compute_returns(*inputs, make_prices()).iloc[0]
    assert result["ret_12m"] == pytest.approx(0.20)
    assert result["mkt_ret_12m"] == pytest.approx(0.10)
    assert result["excess_ret_12m"] == pytest.approx(0.10)
    assert result["has_full_price_history"]


def test_delisted_mid_window_gets_no_return():
    """DDD stops trading 2024-06-28, inside the window: no return (a
    partial-window return would be an estimate), flagged as not full."""
    inputs = make_inputs([(2, "DDD", "2024-03-01", True)])
    result = returns.compute_returns(*inputs, make_prices()).iloc[0]
    assert np.isnan(result["ret_12m"])
    assert not result["has_full_price_history"]


def test_company_without_ticker_is_left_out():
    """No ticker -> no row (reported in coverage as scored minus with
    ticker), never a guessed ticker."""
    inputs = make_inputs(
        [(1, "AAA", "2024-03-01", True), (3, pd.NA, "2024-03-01", False)]
    )
    result_df = returns.compute_returns(*inputs, make_prices())
    assert result_df["cik"].tolist() == [1]


def test_compare_flagged_counts_mean_median_and_skips_na_flags():
    """Two flagged AAA years (+10% excess each) and one unflagged DDD
    year with no full window: flagged count 2, mean 0.10; not_flagged
    has no usable rows. An NA flag (no M-Score) is in neither group."""
    inputs = make_inputs(
        [
            (1, "AAA", "2024-03-01", True),
            (4, "AAA", "2024-03-01", True),
            (2, "DDD", "2024-03-01", False),
            (5, "AAA", "2024-03-01", None),
        ]
    )
    returns_df = returns.compute_returns(*inputs, make_prices())
    summary = returns.compare_flagged(inputs[0], returns_df)
    assert summary.loc["flagged", "count"] == 2
    assert summary.loc["flagged", "mean"] == pytest.approx(0.10)
    assert summary.loc["flagged", "median"] == pytest.approx(0.10)
    assert pd.isna(summary.loc["not_flagged", "count"])


def test_returns_table_contract_types():
    """Columns and types match section 4."""
    inputs = make_inputs([(1, "AAA", "2024-03-01", True)])
    result_df = returns.compute_returns(*inputs, make_prices())
    assert list(result_df.columns) == returns.RETURNS_COLUMNS
    assert str(result_df["ticker"].dtype) == "string"
    assert str(result_df["has_full_price_history"].dtype) == "bool"
