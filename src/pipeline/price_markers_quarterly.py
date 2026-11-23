"""Quarterly (TTM) score markers for one company's price chart.

The quarterly counterpart of src/pipeline/price_markers.py (which is not
changed). The dashboard's price chart only draws what this returns.

One marker per scored fiscal quarter in scores_quarterly, placed on the
first trading day ON OR AFTER the score's available_date: the filing
date of the latest filing among the score's inputs, the first day anyone
outside the company could have computed it. Placing it earlier (at the
quarter end, say) would show the chart "knowing" a warning before the
public did; this is the same rule the 10-K markers follow with each
10-K's filing date. A score available before the first price or after
the last one is not moved; it is returned in skipped with the reason.

Reads scores_quarterly only (the prices come from price_markers).
Nothing is written.
"""

from pathlib import Path

import pandas as pd

from src.pipeline import price_markers

QUARTERLY_MARKER_COLUMNS = [
    "fiscal_year",
    "fiscal_quarter",
    "available_date",
    "marker_date",
    "adj_close",
    "flags_raised",
    "m_score",
    "m_flag",
    "z_zone",
    "f_band",
]
QUARTER_SCORE_COLUMNS = [
    "cik",
    "fiscal_year",
    "fiscal_quarter",
    "available_date",
    "flags_raised",
    "m_score",
    "m_flag",
    "z_zone",
    "f_band",
]
QUARTERLY_SKIPPED_COLUMNS = [
    "fiscal_year",
    "fiscal_quarter",
    "available_date",
    "reason",
]


def company_quarters(data_dir, cik):
    """Return one company's scored quarters from scores_quarterly in
    data_dir, or an empty table if that folder has no quarterly scores
    (the app's test fixtures)."""
    path = Path(data_dir) / "scores_quarterly.parquet"
    if not path.exists():
        return pd.DataFrame(columns=QUARTER_SCORE_COLUMNS)
    return pd.read_parquet(
        path,
        columns=QUARTER_SCORE_COLUMNS,
        filters=[("cik", "==", int(cik))],
    )


def build_quarterly_markers(prices_df, quarters_df):
    """Return (markers, skipped) from one company's prices (date,
    adj_close, oldest first) and scored quarters: each marker on the
    first trading day on or after available_date (a day this stock has a
    price, so every marker sits on a real price)."""
    if prices_df.empty or quarters_df.empty:
        return (
            pd.DataFrame(columns=QUARTERLY_MARKER_COLUMNS),
            pd.DataFrame(columns=QUARTERLY_SKIPPED_COLUMNS),
        )
    dates = pd.DatetimeIndex(prices_df["date"])
    quarters = quarters_df.sort_values(
        ["fiscal_year", "fiscal_quarter"]
    ).reset_index(drop=True)
    available = pd.to_datetime(quarters["available_date"])
    before = available < dates[0]
    after = available > dates[-1]
    outside = before | after
    skipped = quarters.loc[
        outside, ["fiscal_year", "fiscal_quarter", "available_date"]
    ].assign(
        reason=[
            price_markers.BEFORE_PRICES if b else price_markers.AFTER_PRICES
            for b in before[outside]
        ]
    )
    placed = quarters[~outside].copy()
    # searchsorted(side="left") finds the first price date >= the date.
    positions = dates.searchsorted(
        pd.to_datetime(placed["available_date"]), side="left"
    )
    placed["marker_date"] = dates[positions]
    placed["adj_close"] = prices_df["adj_close"].to_numpy()[positions]
    return (
        placed[QUARTERLY_MARKER_COLUMNS].reset_index(drop=True),
        skipped[QUARTERLY_SKIPPED_COLUMNS].reset_index(drop=True),
    )


def quarterly_markers(data_dir, cik, prices_df):
    """Return (markers, skipped) for one company: its scored quarters
    in data_dir placed on prices_df (from price_markers.price_markers)."""
    return build_quarterly_markers(prices_df, company_quarters(data_dir, cik))
