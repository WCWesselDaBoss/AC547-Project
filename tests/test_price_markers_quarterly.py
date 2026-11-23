"""Tests for quarterly price-chart markers
(src/pipeline/price_markers_quarterly.py), with hand-checkable dates."""

import pandas as pd

from src.pipeline import price_markers
from src.pipeline import price_markers_quarterly as pmq


def prices():
    """Trading days Mon Jan 6 to Fri Jan 10, 2025 (prices 10 to 14)."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2025-01-06",
                    "2025-01-07",
                    "2025-01-08",
                    "2025-01-09",
                    "2025-01-10",
                ]
            ),
            "adj_close": [10.0, 11.0, 12.0, 13.0, 14.0],
        }
    )


def quarters(available):
    """One scored quarter per available date (FY2025 Q1, Q2, ...)."""
    return pd.DataFrame(
        {
            "cik": 1,
            "fiscal_year": 2025,
            "fiscal_quarter": list(range(1, len(available) + 1)),
            "available_date": pd.to_datetime(available),
            "flags_raised": pd.array([1] * len(available), dtype="Int64"),
            "m_score": -2.0,
            "m_flag": pd.array([False] * len(available), dtype="boolean"),
            "z_zone": "safe",
            "f_band": "weak",
        }
    )


def test_marker_on_the_first_trading_day_on_or_after_available():
    """A score available on a trading day (Wed Jan 8) is marked that
    day, at that day's price (12)."""
    markers, skipped = pmq.build_quarterly_markers(
        prices(), quarters(["2025-01-08"])
    )
    assert markers["marker_date"].tolist() == [pd.Timestamp("2025-01-08")]
    assert markers["adj_close"].tolist() == [12.0]
    assert skipped.empty


def test_a_non_trading_day_moves_to_the_next_trading_day():
    """With no price on Wed Jan 8 (as on a weekend or holiday), a score
    available that day moves forward to the next trading day, Thu Jan 9
    (price 13), never back."""
    gap = prices().drop(index=[2])  # no price on Wed Jan 8
    markers, _ = pmq.build_quarterly_markers(gap, quarters(["2025-01-08"]))
    assert markers["marker_date"].tolist() == [pd.Timestamp("2025-01-09")]
    assert markers["adj_close"].tolist() == [13.0]


def test_scores_outside_the_price_history_are_skipped_with_a_reason():
    """Before Jan 6 and after Jan 10: skipped, never moved."""
    markers, skipped = pmq.build_quarterly_markers(
        prices(), quarters(["2025-01-02", "2025-01-07", "2025-01-15"])
    )
    assert markers["fiscal_quarter"].tolist() == [2]
    assert skipped["reason"].tolist() == [
        price_markers.BEFORE_PRICES,
        price_markers.AFTER_PRICES,
    ]


def test_no_quarterly_scores_file_gives_no_markers(tmp_path):
    """A folder without scores_quarterly (the app's test fixtures) gives
    empty tables, not an error."""
    markers, skipped = pmq.quarterly_markers(tmp_path, 1, prices())
    assert markers.empty and skipped.empty
    assert list(markers.columns) == pmq.QUARTERLY_MARKER_COLUMNS


# ---------------------------------------------------------------------------
# The chart (app/components/price_chart.py)
# ---------------------------------------------------------------------------
def chart_result():
    """A PriceMarkers result with prices and one 10-K marker."""
    annual = pd.DataFrame(
        {
            "fiscal_year": [2024],
            "filed_date": pd.to_datetime(["2025-01-07"]),
            "marker_date": pd.to_datetime(["2025-01-07"]),
            "adj_close": [11.0],
            "flags_raised": pd.array([0], dtype="Int64"),
            "m_score": [-2.5],
            "m_flag": pd.array([False], dtype="boolean"),
            "z_zone": ["safe"],
            "f_band": ["strong"],
        }
    )
    return price_markers.PriceMarkers(
        price_markers.STATUS_OK,
        "TEST",
        prices(),
        annual,
        price_markers.empty_skipped(),
    )


def symbols(figure):
    """Return {trace name: marker symbol} for the marker traces."""
    return {
        trace.name: trace.marker.symbol
        for trace in figure.data
        if trace.mode and "markers" in trace.mode
    }


def test_annual_chart_has_no_diamonds():
    """Without quarterly markers the figure is the annual one: round
    10-K markers only."""
    from app.components import price_chart

    figure = price_chart.price_figure(chart_result())
    assert set(symbols(figure).values()) == {None}


def test_quarterly_chart_adds_diamonds_with_their_own_legend():
    """With quarterly markers, diamond traces are added, named by flag
    count, next to the unchanged 10-K trace; with SPY on, they are
    rebased with the company's line (first price 10 -> 100, so a
    diamond at 12 sits at 120)."""
    from app.components import price_chart

    markers, _ = pmq.build_quarterly_markers(
        prices(), quarters(["2025-01-08"])
    )
    figure = price_chart.price_figure(
        chart_result(), quarterly_markers=markers
    )
    assert symbols(figure) == {
        "10-K: 0 flags": None,
        "Quarterly (TTM): 1 flag": price_chart.QUARTERLY_SYMBOL,
    }
    market = prices().assign(adj_close=[100.0, 101, 102, 103, 104])
    rebased = price_chart.price_figure(
        chart_result(), market_df=market, quarterly_markers=markers
    )
    diamond = next(
        t for t in rebased.data if t.name == "Quarterly (TTM): 1 flag"
    )
    assert list(diamond.y) == [120.0]
    assert "FY2025 Q1, trailing twelve months" in diamond.hovertext[0]
