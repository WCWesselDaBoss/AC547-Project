"""Plotly figures for the company page.

One score per chart, never two y-axes, so each chart has a single scale
a reader can trust. Charts only draw stored values; reference lines come
from config.py (the published cutoffs and the team's display bands).
"""

import plotly.graph_objects as go

import config
from app import labels, style
from src.scores import peers

TREND_HEIGHT = 260
PERCENTILE_HEIGHT = 300
# Peer percentiles run from 0 (lowest in group) to 100 (highest).
PERCENTILE_RANGE = (0, 100)
PERCENTILE_MIDDLE = 50
# Extra room right of 100 so a bar's value label is not cut off.
PERCENTILE_LABEL_ROOM = 8
# Half a point above and below the F-Score range so 0 and 9 markers show.
F_AXIS_PADDING = 0.5

# Percentile bar labels say which way is "more risk", because the five
# scores point in different directions (CLAUDE.md section 4).
PERCENTILE_BAR_LABELS = {
    "m_score": "Manipulation score (higher = more warning signs)",
    "z_score": "Distress score (higher = safer)",
    "f_score": "Strength score (higher = stronger)",
    "accruals_ratio": "Accruals ratio (higher = less cash-backed)",
    "cash_conversion": "Cash conversion (higher = more cash)",
}


def _reference_line(figure, y_value, text):
    """Add a thin dashed horizontal line with a label at the right end."""
    figure.add_hline(
        y=y_value,
        line={"color": style.INK_MUTED, "width": 1, "dash": "dash"},
        annotation_text=text,
        annotation_position="top right",
        annotation_font={"color": style.INK_SECONDARY, "size": 11},
    )


def trend_figure(scores_df, column, title, selected_year, references=()):
    """Return a line chart of one score across the company's years.

    Missing years show as gaps (connectgaps=False) rather than a line
    drawn through a value that does not exist. The selected year gets a
    faint vertical marker so the chart and the cards agree visually.
    references is a list of (y value, label) for cutoff lines.
    """
    figure = go.Figure(
        go.Scatter(
            x=scores_df["fiscal_year"],
            y=scores_df[column].astype("float64"),
            mode="lines+markers",
            line={"color": style.SERIES_COLORS[0], "width": 2},
            marker={"size": 8},
            connectgaps=False,
            name=title,
            hovertemplate="FY%{x}: %{y:.2f}<extra></extra>",
        )
    )
    for y_value, text in references:
        _reference_line(figure, y_value, text)
    # selected_year None means no year is selected (case studies).
    if selected_year is not None:
        figure.add_vline(
            x=selected_year, line={"color": style.GRIDLINE, "width": 8}
        )
    figure.update_layout(
        title={"text": title, "font": {"size": 15}},
        height=TREND_HEIGHT,
        showlegend=False,
        hovermode="x",
    )
    figure.update_xaxes(dtick=1, tickformat="d")
    return figure


def m_trend(scores_df, selected_year, cutoff):
    """Return the M-Score trend with the analyst's warning cutoff."""
    return trend_figure(
        scores_df,
        "m_score",
        "Earnings manipulation score (M-Score)",
        selected_year,
        [(cutoff, f"Warning above {cutoff:.2f}")],
    )


def z_trend(scores_df, selected_year):
    """Return the Z''-Score trend with the distress and safe lines."""
    return trend_figure(
        scores_df,
        "z_score",
        "Financial distress score (Z''-Score)",
        selected_year,
        [
            (
                config.ALTMAN_Z2_SAFE_ABOVE,
                f"Safe above {config.ALTMAN_Z2_SAFE_ABOVE:.2f}",
            ),
            (
                config.ALTMAN_Z2_DISTRESS_BELOW,
                f"Distress below {config.ALTMAN_Z2_DISTRESS_BELOW:.2f}",
            ),
        ],
    )


def f_trend(scores_df, selected_year, f_score_max):
    """Return the F-Score trend with the weak and strong band edges."""
    figure = trend_figure(
        scores_df,
        "f_score",
        "Financial strength score (F-Score)",
        selected_year,
        [
            (
                config.F_SCORE_STRONG_MIN,
                f"Strong at {config.F_SCORE_STRONG_MIN} or more",
            ),
            (
                config.F_SCORE_WEAK_MAX,
                f"Weak at {config.F_SCORE_WEAK_MAX} or fewer",
            ),
        ],
    )
    figure.update_yaxes(
        range=[-F_AXIS_PADDING, f_score_max + F_AXIS_PADDING], dtick=1
    )
    return figure


def percentile_figure(row):
    """Return horizontal bars of the five peer percentiles for one year.

    Scores without a percentile are left off the chart (the peer
    sentences explain why), so a missing rank never shows as 0.
    """
    ranked = [
        (PERCENTILE_BAR_LABELS[score], row[peers.percentile_column(score)])
        for score in PERCENTILE_BAR_LABELS
    ]
    ranked = [
        (label, value)
        for label, value in ranked
        if not labels.is_missing(value)
    ]
    figure = go.Figure(
        go.Bar(
            x=[value for _, value in ranked],
            y=[label for label, _ in ranked],
            orientation="h",
            marker={
                "color": style.SERIES_COLORS[0],
                "cornerradius": 4,
            },
            text=[f"{value:.0f}" for _, value in ranked],
            textposition="outside",
            hovertemplate="%{y}: %{x:.0f}<extra></extra>",
        )
    )
    figure.add_vline(
        x=PERCENTILE_MIDDLE,
        line={"color": style.INK_MUTED, "width": 1, "dash": "dash"},
        annotation_text="Middle of peers",
        annotation_position="top",
        annotation_font={"color": style.INK_SECONDARY, "size": 11},
    )
    figure.update_layout(
        title={"text": "Rank among peers (0 to 100)", "font": {"size": 15}},
        height=PERCENTILE_HEIGHT,
        showlegend=False,
        bargap=0.35,
    )
    figure.update_xaxes(
        range=[
            PERCENTILE_RANGE[0],
            PERCENTILE_RANGE[1] + PERCENTILE_LABEL_ROOM,
        ]
    )
    figure.update_yaxes(autorange="reversed")
    return figure


def shade_years(figure, first_year, last_year, text):
    """Shade fiscal years first_year to last_year with a label on top.

    Used by case studies to mark the years whose 10-K was filed before
    the event: the only years an analyst could have read at the time.
    """
    figure.add_vrect(
        x0=first_year - 0.5,
        x1=last_year + 0.5,
        fillcolor=style.GRIDLINE,
        opacity=0.5,
        line_width=0,
        layer="below",
        annotation_text=text,
        annotation_position="top left",
        annotation_font={"color": style.INK_SECONDARY, "size": 11},
    )
    return figure


def case_m_trend(history, before_years, cutoff):
    """Return the M-Score trend for a case, pre-event years shaded."""
    figure = m_trend(history, None, cutoff)
    if before_years:
        shade_years(
            figure,
            min(before_years),
            max(before_years),
            "10-K filed before the event",
        )
    return figure
