"""Tests for app/components/price_chart.py (the figure, no Streamlit).

Three markers: FY2022 with 0 flags, FY2023 with 2 flags (filed on a
Saturday, shown on Monday) and FY2024 with no scores.
"""

import numpy as np
import pandas as pd

from app.components import price_chart
from src.pipeline import price_markers

DAYS = pd.bdate_range("2023-01-02", "2024-12-31").astype("datetime64[ns]")


def make_result():
    """Return a PriceMarkers result with three markers."""
    prices = pd.DataFrame({"date": DAYS, "adj_close": 50.0})
    markers = pd.DataFrame(
        {
            "fiscal_year": [2022, 2023, 2024],
            "filed_date": pd.to_datetime(
                ["2023-02-15", "2024-02-10", "2024-11-01"]
            ),
            "marker_date": pd.to_datetime(
                ["2023-02-15", "2024-02-12", "2024-11-01"]
            ),
            "adj_close": [50.0, 50.0, 50.0],
            "flags_raised": pd.array([0, 2, None], dtype="Int64"),
            "m_score": [-2.5, -1.2, np.nan],
            "m_flag": pd.array([False, True, None], dtype="boolean"),
            "z_zone": pd.array(["safe", "distress", None], dtype="string"),
            "f_band": pd.array(["strong", "middle", None], dtype="string"),
        }
    )
    return price_markers.PriceMarkers(
        price_markers.STATUS_OK,
        "TST",
        prices,
        markers,
        price_markers.empty_skipped(),
    )


def traces_by_name(figure):
    """Return {trace name: trace}."""
    return {trace.name: trace for trace in figure.data}


def test_labels_and_colors_by_flag_count():
    """0 = green, 1 = yellow, 2 = orange, 3 = red, missing = gray; every
    marker also has a text label."""
    assert price_chart.flag_label(0) == "0 flags"
    assert price_chart.flag_label(1) == "1 flag"
    assert price_chart.flag_label(pd.NA) == "no scores"
    assert price_chart.flag_color(0) == "#0ca30c"
    assert price_chart.flag_color(1) == "#fab219"
    assert price_chart.flag_color(2) == "#eb6834"
    assert price_chart.flag_color(3) == "#d03b3b"
    assert price_chart.flag_color(pd.NA) == "#898781"


def test_figure_has_a_line_and_one_marker_group_per_flag_count():
    """Line, then 0 flags, 2 flags and no scores, each labeled."""
    figure = price_chart.price_figure(make_result())
    traces = traces_by_name(figure)
    assert list(traces) == [
        "TST",
        "10-K: 0 flags",
        "10-K: 2 flags",
        "10-K: no scores",
    ]
    two = traces["10-K: 2 flags"]
    assert list(two.text) == ["2 flags"]
    assert two.marker.color == "#eb6834"
    assert list(two.x) == [pd.Timestamp("2024-02-12")]
    assert figure.layout.yaxis.title.text == price_chart.PRICE_AXIS_TITLE


def test_hover_text():
    """The hover names the year, filing date (and the trading day it is
    shown on), flags, M-Score with its flag, Z'' zone and F band."""
    figure = price_chart.price_figure(make_result())
    hover = traces_by_name(figure)["10-K: 2 flags"].hovertext[0]
    assert "Fiscal year 2023" in hover
    assert "10-K filed 2024-02-10" in hover
    assert "next trading day, Mon 2024-02-12" in hover
    assert "Flags raised: 2 flags" in hover
    assert "M-Score: -1.20 (flagged)" in hover
    assert "Z'' zone: distress" in hover
    assert "F-Score band: middle" in hover
    missing = traces_by_name(figure)["10-K: no scores"].hovertext[0]
    assert "M-Score: no score" in missing
    assert "Z'' zone: no score" in missing


def test_spy_line_only_when_comparing():
    """With SPY prices, a SPY line is added and both are rebased."""
    market = pd.DataFrame({"date": DAYS, "adj_close": 400.0})
    figure = price_chart.price_figure(make_result(), market)
    traces = traces_by_name(figure)
    assert "SPY" in traces
    assert list(traces["SPY"].y)[0] == 100.0
    assert list(traces["TST"].y)[0] == 100.0
    assert figure.layout.yaxis.title.text == price_chart.REBASED_AXIS_TITLE
    assert "SPY" not in traces_by_name(price_chart.price_figure(make_result()))


def test_skipped_note():
    """Filings outside the prices are named; none gives no note."""
    skipped = pd.DataFrame(
        {
            "fiscal_year": [2012],
            "filed_date": pd.to_datetime(["2012-02-01"]),
            "reason": [price_markers.BEFORE_PRICES],
        }
    )
    assert "FY2012" in price_chart.skipped_note(skipped)
    assert price_chart.skipped_note(price_markers.empty_skipped()) is None


def test_event_line_only_when_given():
    """A case event adds one dashed vertical line spanning the chart
    (yref "paper", 0 to 1) and its label, wrapped at 40 characters."""
    label = (
        "First public disclosure: SEC and DOJ investigation of "
        "accounting practices"
    )
    figure = price_chart.price_figure(
        make_result(), event=("2024-06-03", label)
    )
    assert len(figure.layout.shapes) == 1
    line = figure.layout.shapes[0]
    assert line.line.dash == "dash"
    assert pd.Timestamp(line.x0) == pd.Timestamp("2024-06-03")
    assert (line.y0, line.y1, line.yref) == (0, 1, "paper")
    text = figure.layout.annotations[0].text
    assert text.replace("<br>", " ") == label
    assert all(len(part) <= 40 for part in text.split("<br>"))
    plain = price_chart.price_figure(make_result())
    assert len(plain.layout.shapes) == 0
