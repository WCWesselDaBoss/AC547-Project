"""Stock price chart with a marker on each 10-K, colored by warnings.

This file only draws. Every date, price and marker comes from
src/pipeline/price_markers.py (CLAUDE.md section 3: calculations live in
src/, the app only displays). It reads local Parquet files only, so the
chart works offline during the demo.

Pages call render_price_chart(cik, key). price_figure() builds the
Plotly figure without Streamlit, so it can be tested on its own.
"""

import textwrap

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import data, style
from src.pipeline import price_markers

CHART_HEIGHT = 360
LINE_COLOR = style.SERIES_COLORS[0]  # blue, the app's first series color
MARKET_COLOR = style.INK_MUTED  # gray, so SPY reads as the background

# Marker color by number of warnings raised. Green, yellow and red are
# the app's reserved verdict colors; orange (between yellow and red) is
# the chart-series orange. Every marker also carries a text label, so
# color is never the only cue.
FLAG_COLORS = {
    0: style.STATUS_COLORS["good"],
    1: style.STATUS_COLORS["warning"],
    2: style.SERIES_COLORS[1],
    3: style.STATUS_COLORS["critical"],
}
NO_SCORE_COLOR = style.STATUS_COLORS["none"]
NO_SCORE_LABEL = "no scores"

CAPTION = (
    "Prices: Yahoo Finance adjusted close (adjusted for splits and "
    "dividends). Markers appear on the date each 10-K became public. "
    "Warning flags signal a higher risk of large price drops, not the "
    "direction of the price."
)
NO_DATA_MESSAGE = (
    "Price history not available for this company (no current ticker or "
    "no price data)."
)
MARKET_TOGGLE_LABEL = "Compare with SPY (both rebased to 100)"
EVENT_LABEL_WIDTH = 40  # characters per line of the event label
PRICE_AXIS_TITLE = "Adjusted close ($)"
REBASED_AXIS_TITLE = "Value (first date shown = 100)"


@st.cache_data(show_spinner="Loading prices...", max_entries=64)
def load_chart_data(data_dir, cik):
    """Return price_markers.PriceMarkers for one company (cached: the
    last 64 companies viewed stay in memory, like the other per-company
    loaders in app/data.py)."""
    return price_markers.price_markers(data_dir, cik)


@st.cache_data(show_spinner="Loading prices...")
def load_market(data_dir):
    """Return SPY's adjusted closes (cached)."""
    return price_markers.market_prices(data_dir)


def flag_label(flags):
    """Return the marker label: "0 flags", "1 flag", ... or "no scores"
    when the year has no flag count."""
    if pd.isna(flags):
        return NO_SCORE_LABEL
    count = int(flags)
    return f"{count} flag" if count == 1 else f"{count} flags"


def flag_color(flags):
    """Return the marker color for a flag count (gray when missing)."""
    if pd.isna(flags):
        return NO_SCORE_COLOR
    return FLAG_COLORS[int(flags)]


def _text_or_no_score(value):
    """Return a verdict word, or "no score" when it is missing."""
    return "no score" if pd.isna(value) else str(value)


def marker_hover(marker):
    """Return the hover text for one marker row (HTML line breaks)."""
    filed = marker["filed_date"]
    shown = marker["marker_date"]
    filed_line = f"10-K filed {filed:%Y-%m-%d}"
    if shown != filed:
        # Weekends and holidays: the marker sits on the next trading day.
        filed_line += f" (shown on the next trading day, {shown:%a %Y-%m-%d})"
    if pd.isna(marker["m_score"]):
        m_line = "M-Score: no score"
    else:
        is_flagged = pd.notna(marker["m_flag"]) and bool(marker["m_flag"])
        flagged = "flagged" if is_flagged else "not flagged"
        m_line = f"M-Score: {marker['m_score']:.2f} ({flagged})"
    return "<br>".join(
        [
            f"<b>Fiscal year {int(marker['fiscal_year'])}</b>",
            filed_line,
            f"Flags raised: {flag_label(marker['flags_raised'])}",
            m_line,
            f"Z'' zone: {_text_or_no_score(marker['z_zone'])}",
            f"F-Score band: {_text_or_no_score(marker['f_band'])}",
        ]
    )


def price_figure(result, market_df=None, event=None):
    """Return the price chart for a PriceMarkers result with status "ok".

    market_df (SPY prices) is given only when the comparison toggle is
    on; then both lines are rebased to 100 at the first date shown
    (price_markers.rebase_to_100) and the y-axis says so. event is an
    optional (date, label) pair, drawn as a dashed vertical line (case
    study mode: the date the problem first became public).
    """
    prices, markers = result.prices, result.markers
    y_column, axis_title = "adj_close", PRICE_AXIS_TITLE
    figure = go.Figure()
    if market_df is not None:
        prices, market, markers = price_markers.rebase_to_100(
            prices, markers, market_df
        )
        y_column, axis_title = "value", REBASED_AXIS_TITLE
        figure.add_trace(
            go.Scatter(
                x=market["date"],
                y=market["value"],
                mode="lines",
                name="SPY",
                line={"color": MARKET_COLOR, "width": 1.5},
                hovertemplate="SPY %{x|%Y-%m-%d}: %{y:.1f}<extra></extra>",
            )
        )
    figure.add_trace(
        go.Scatter(
            x=prices["date"],
            y=prices[y_column],
            mode="lines",
            name=result.ticker,
            line={"color": LINE_COLOR, "width": 2},
            hovertemplate=f"{result.ticker} %{{x|%Y-%m-%d}}: %{{y:.2f}}"
            "<extra></extra>",
        )
    )
    # One trace per flag count, so the legend lists each color with its
    # meaning; each marker is also labeled with its count.
    labels = markers["flags_raised"].map(flag_label)
    for label in sorted(labels.unique(), key=_label_order):
        group = markers[labels == label]
        figure.add_trace(
            go.Scatter(
                x=group["marker_date"],
                y=group[y_column],
                mode="markers+text",
                name=f"10-K: {label}",
                text=[label] * len(group),
                textposition="top center",
                textfont={"size": 10, "color": style.INK_SECONDARY},
                marker={
                    "size": 12,
                    "color": flag_color(group["flags_raised"].iloc[0]),
                    "line": {"color": style.INK_PRIMARY, "width": 1},
                },
                hovertext=[marker_hover(row) for _, row in group.iterrows()],
                hoverinfo="text",
            )
        )
    if event is not None:
        _add_event_line(figure, *event)
    figure.update_layout(
        height=CHART_HEIGHT,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        yaxis_title=axis_title,
        legend={"orientation": "h", "y": -0.15},
        hovermode="closest",
    )
    return figure


def _add_event_line(figure, event_date, label):
    """Draw a dashed vertical line at event_date with a wrapped label.

    A shape plus a separate annotation rather than add_vline, whose
    built-in label fails on date axes in some Plotly versions. yref
    "paper" spans the full height whatever the price scale.
    """
    when = pd.Timestamp(event_date)
    figure.add_shape(
        type="line",
        x0=when,
        x1=when,
        y0=0,
        y1=1,
        yref="paper",
        line={"color": style.INK_SECONDARY, "width": 1.5, "dash": "dash"},
    )
    figure.add_annotation(
        x=when,
        y=1,
        yref="paper",
        text="<br>".join(textwrap.wrap(str(label), EVENT_LABEL_WIDTH)),
        showarrow=False,
        xanchor="left",
        yanchor="top",
        align="left",
        font={"size": 10, "color": style.INK_SECONDARY},
        bgcolor=style.SURFACE,
    )


def _label_order(label):
    """Sort legend entries 0, 1, 2, 3 flags, then "no scores"."""
    return 99 if label == NO_SCORE_LABEL else int(label.split()[0])


def skipped_note(skipped):
    """Return a sentence naming 10-Ks left off the chart, or None."""
    if skipped.empty:
        return None
    years = ", ".join(f"FY{year}" for year in skipped["fiscal_year"])
    return (
        f"Not marked: {years}, because the 10-K was filed outside the "
        "available price history."
    )


def render_price_chart(cik, key, event=None):
    """Draw the chart for one company, or the no-data message.

    key keeps each page's comparison toggle separate (Streamlit needs a
    unique key per widget). event: optional (date, label) for a dashed
    vertical line (see price_figure).
    """
    data_dir = data.resolve_data_source()[1]
    result = load_chart_data(data_dir, int(cik))
    if result.status != price_markers.STATUS_OK:
        st.info(NO_DATA_MESSAGE)
        return
    compare = st.toggle(
        MARKET_TOGGLE_LABEL, value=False, key=f"price_chart_spy_{key}"
    )
    market_df = load_market(data_dir) if compare else None
    st.plotly_chart(price_figure(result, market_df, event), width="stretch")
    st.caption(CAPTION)
    note = skipped_note(result.skipped)
    if note:
        st.caption(note)
