"""Plain-English labels and number formats for every screen.

Kept in one place so a term reads the same on every page, and kept free
of Streamlit so pytest can check it directly. Nothing here computes a
score; it only names and formats values the scores table already holds.
"""

import math

import config

APP_TITLE = "Earnings Quality Radar"
APP_TAGLINE = (
    "Checks whether a company's reported earnings show warning signs "
    "worth investigating, using its own SEC filings."
)

# Shown on every company page (Phase 3 brief): the scores are screening
# tools, not forecasts or proof.
SCOPE_NOTE = (
    "These checks flag warning signs in reported numbers. They do not "
    "predict stock performance or prove fraud."
)

# What the analyst is looking at, shown in the sidebar on every page.
DATA_SOURCE_NOTES = {
    "fixture": (
        "**Test data.** Five made-up companies used to build and test "
        "the app. Not for analysis."
    ),
    "sample": (
        "**Sample data.** 50 real companies. Each company is ranked only "
        "against other sample companies, so peer rankings are "
        "illustrative."
    ),
    "full": (
        "**Full data.** US companies filing 10-Ks, fiscal years "
        f"{config.FIRST_FISCAL_YEAR} to {config.LAST_FISCAL_YEAR}, "
        "excluding banks, insurers and REITs."
    ),
}

# Column -> label. The model name follows in brackets so an expert can
# still find the familiar term.
COLUMN_LABELS = {
    "m_score": "Earnings manipulation score (Beneish M-Score)",
    "z_score": "Financial distress score (Altman Z'')",
    "f_score": "Financial strength score (Piotroski F-Score)",
    "accruals_ratio": "Accruals ratio",
    "cash_conversion": "Cash conversion",
    "flags_raised": "Checks raising concerns",
    "fiscal_year": "Fiscal year",
    "name": "Company",
    "ticker": "Ticker",
    "sic_description": "Industry",
    "peer_group": "Peer group",
}

# One sentence per score, for tooltips and the About page.
SCORE_HELP = {
    "m_score": (
        "Combines eight ratios that tend to move when earnings are "
        "overstated. Higher means more warning signs."
    ),
    "z_score": (
        "Combines liquidity, retained profit, operating profit and "
        "book leverage. Lower means closer to financial distress."
    ),
    "f_score": (
        "Counts nine yes/no tests of profitability, cash flow, debt and "
        "efficiency (0 to 9). Higher means stronger."
    ),
    "accruals_ratio": (
        "Net income minus operating cash flow, as a share of average "
        "assets. Higher means less of the profit is backed by cash."
    ),
    "cash_conversion": (
        "Operating cash flow divided by net income. Blank when net "
        "income is zero or negative."
    ),
}

NOT_AVAILABLE = "Not available"

# (divisor, suffix), largest first, for compact money display.
_MONEY_SCALES = [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]


def is_missing(value):
    """Return True for None, NaN, NaT and pandas NA."""
    if value is None:
        return True
    try:
        return bool(value != value)  # NaN and NaT are not equal to self
    except TypeError:
        return True  # pandas NA raises TypeError when cast to bool


def format_money(value, decimals=1):
    """Return dollars as compact text, e.g. 1_234_000_000 -> "$1.2B".

    Missing values show as "Not available", never "$0", because a
    missing input is not zero (CLAUDE.md section 4).
    """
    if is_missing(value):
        return NOT_AVAILABLE
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    for divisor, suffix in _MONEY_SCALES:
        if magnitude >= divisor:
            return f"{sign}${magnitude / divisor:,.{decimals}f}{suffix}"
    return f"{sign}${magnitude:,.0f}"


def format_number(value, decimals=2):
    """Return a plain number with fixed decimals, or "Not available"."""
    if is_missing(value) or (isinstance(value, float) and math.isinf(value)):
        return NOT_AVAILABLE
    return f"{value:,.{decimals}f}"
