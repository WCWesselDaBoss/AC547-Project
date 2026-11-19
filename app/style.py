"""One visual style for every page: colors, card CSS and chart template.

Colors are the validated reference palette from the team's data-viz
guidelines, not picked by eye:
- Status colors (good / warning / critical) are reserved for verdicts and
  always appear with an icon and a word, so color is never the only cue
  (about 1 in 12 men cannot tell red from green).
- Chart series use a fixed categorical order, so a company keeps its
  color when filters change.
"""

import html

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Reserved verdict colors. "none" is a neutral gray for "no score".
STATUS_COLORS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "critical": "#d03b3b",
    "none": "#898781",
}

# Chart series colors, used in this order and never cycled.
SERIES_COLORS = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#6250d6",  # violet
    "#e34948",  # red
]

# Ink and surfaces (light theme; .streamlit/config.toml fixes the theme
# so the demo looks the same on every laptop).
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
SURFACE = "#fcfcfb"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'

PLOTLY_TEMPLATE_NAME = "radar"

# Card styles for verdicts and peer sentences. Text stays in ink colors;
# only the left edge carries the status color, so text contrast is
# always readable whatever the verdict.
_CSS = f"""
.radar-card {{
    background: {SURFACE};
    border: 1px solid rgba(11, 11, 11, 0.10);
    border-left: 6px solid var(--card-accent, {INK_MUTED});
    border-radius: 8px;
    padding: 0.9rem 1rem;
    height: 100%;
}}
.radar-card .card-title {{
    color: {INK_SECONDARY};
    font-size: 0.85rem;
    margin-bottom: 0.25rem;
}}
.radar-card .card-verdict {{
    color: {INK_PRIMARY};
    font-size: 1.15rem;
    font-weight: 600;
}}
.radar-card .card-detail {{
    color: {INK_SECONDARY};
    font-size: 0.85rem;
    margin-top: 0.35rem;
}}
/* Tighter top padding: the default leaves a large gap above the title. */
.block-container {{ padding-top: 2rem; }}
"""


def apply_style():
    """Add the shared CSS and make the chart template the default.

    Called once per run from app/app.py, before any page draws.
    """
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)
    register_plotly_template()


def register_plotly_template():
    """Register the "radar" Plotly template and set it as the default.

    Recessive hairline grids, a single sans-serif font and the fixed
    series order, so every chart in the app looks like one system.
    """
    axis_style = {
        "gridcolor": GRIDLINE,
        "gridwidth": 1,
        "linecolor": BASELINE,
        "zerolinecolor": BASELINE,
        "tickfont": {"color": INK_MUTED},
        "title": {"font": {"color": INK_SECONDARY}},
    }
    pio.templates[PLOTLY_TEMPLATE_NAME] = go.layout.Template(
        layout={
            "font": {"family": FONT_FAMILY, "color": INK_PRIMARY},
            "colorway": SERIES_COLORS,
            "paper_bgcolor": SURFACE,
            "plot_bgcolor": SURFACE,
            "xaxis": axis_style,
            "yaxis": axis_style,
            "hoverlabel": {"font": {"family": FONT_FAMILY}},
            "margin": {"l": 48, "r": 16, "t": 40, "b": 40},
        }
    )
    pio.templates.default = f"plotly_white+{PLOTLY_TEMPLATE_NAME}"


def verdict_card_html(title, status, verdict, detail):
    """Return the HTML for one verdict card.

    status is a STATUS_COLORS key; it colors only the card's left edge.
    All text is escaped, so a company or label containing "&" or "<"
    cannot break the page.
    """
    accent = STATUS_COLORS[status]
    return (
        f'<div class="radar-card" style="--card-accent: {accent}">'
        f'<div class="card-title">{html.escape(title)}</div>'
        f'<div class="card-verdict">{html.escape(verdict)}</div>'
        f'<div class="card-detail">{html.escape(detail)}</div>'
        "</div>"
    )
