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

# ---------------------------------------------------------------------------
# Verdicts: an icon AND a word, so color is never the only cue.
# ---------------------------------------------------------------------------
NO_SCORE = "⚪ No score"
M_FLAG_LABELS = {True: "🔴 Warning", False: "🟢 No warning"}
Z_ZONE_LABELS = {
    "distress": "🔴 Distress zone",
    "grey": "🟡 Grey zone",
    "safe": "🟢 Safe zone",
}
F_BAND_LABELS = {
    "weak": "🔴 Weak",
    "middle": "🟡 Middle",
    "strong": "🟢 Strong",
}

# Short names for the three checks, used as filter and column headings.
CHECK_NAMES = {
    "m": "Earnings manipulation risk",
    "z": "Financial distress risk",
    "f": "Financial strength",
}

# ---------------------------------------------------------------------------
# Score components (expert detail on the company page)
# ---------------------------------------------------------------------------
# The eight Beneish indexes. 1.00 means "no change from last year".
M_INDEX_LABELS = {
    "dsri": "Receivables growing faster than sales (DSRI)",
    "gmi": "Gross margin shrinking (GMI)",
    "aqi": "More costs being capitalized (AQI)",
    "sgi": "Sales growth (SGI)",
    "depi": "Depreciation slowing (DEPI)",
    "sgai": "Overhead growing faster than sales (SGAI)",
    "tata": "Profit not backed by cash (TATA)",
    "lvgi": "Leverage increasing (LVGI)",
}

# The four Altman Z'' ratios (CLAUDE.md section 5).
Z_RATIO_LABELS = {
    "z_x1": "Working capital / total assets (X1)",
    "z_x2": "Retained earnings / total assets (X2)",
    "z_x3": "Operating income / total assets (X3)",
    "z_x4": "Book equity / total liabilities (X4)",
}

# The nine Piotroski signals, phrased as the yes/no question each asks.
F_SIGNAL_LABELS = {
    "f_roa_positive": "1. Profitable (return on assets above zero)?",
    "f_cfo_positive": "2. Operating cash flow above zero?",
    "f_roa_improved": "3. Return on assets higher than last year?",
    "f_cfo_exceeds_roa": "4. Cash flow return above profit return?",
    "f_leverage_down": "5. Long-term debt lower relative to assets?",
    "f_current_ratio_up": "6. Current ratio higher than last year?",
    "f_no_new_shares": "7. No new shares issued?",
    "f_gross_margin_up": "8. Gross margin higher than last year?",
    "f_asset_turnover_up": "9. Asset turnover higher than last year?",
}
SIGNAL_RESULT_LABELS = {True: "✅ Yes (1 point)", False: "❌ No (0 points)"}
SIGNAL_UNDETERMINED = "⚪ Cannot tell (input missing)"

# ---------------------------------------------------------------------------
# Why companies or scores are missing
# ---------------------------------------------------------------------------
# Keys are the exclusion_reason codes written by src/pipeline/companies.py.
EXCLUSION_REASON_LABELS = {
    "financial_sic_6000_6799": (
        "Banks, insurers, REITs and shell companies (SIC 6000 to 6799)"
    ),
    "missing_sic": "No industry code, so no peer group",
    "no_10k_filings": "Never filed a 10-K (e.g. foreign filers)",
    "no_xbrl_facts": "No machine-readable (XBRL) financial data",
    "no_submissions_record": "No SEC filing history found",
}

# financials_annual line items, in words an analyst would use.
LINE_ITEM_LABELS = {
    "revenue": "Revenue",
    "cost_of_revenue": "Cost of revenue",
    "sga": "Selling, general and administrative expense",
    "depreciation": "Depreciation and amortization",
    "operating_income": "Operating income",
    "income_continuing_ops": "Income from continuing operations",
    "net_income": "Net income",
    "cfo": "Operating cash flow",
    "receivables": "Accounts receivable",
    "current_assets": "Current assets",
    "ppe_net": "Property, plant and equipment (net)",
    "total_assets": "Total assets",
    "current_liabilities": "Current liabilities",
    "long_term_debt": "Long-term debt",
    "total_liabilities": "Total liabilities",
    "retained_earnings": "Retained earnings",
    "stockholders_equity": "Stockholders' equity",
    "shares_outstanding": "Shares outstanding",
}

# Fixed missing_inputs codes (see the scores modules in src/scores/).
_FIXED_REASON_LABELS = {
    "no_row_t-1": "No filing data for the prior year",
    "no_row_t-2": "No filing data for two years earlier",
    "shares_t-1_same_filing": (
        "Prior-year share count not shown in the same 10-K"
    ),
    "net_income_not_positive": (
        "Net income zero or negative, so cash conversion is not shown"
    ),
    "f_leverage_down_no_point": (
        "Long-term debt not reported, so the debt test earned no point"
    ),
}
_YEAR_SUFFIXES = {"_t-1": "prior year", "_t": "this year"}


def describe_missing_input(code):
    """Return a plain-English sentence for one missing_inputs code.

    Patterns: "<line item>_t" or "_t-1" (not reported), "<index>_set_to_1"
    (set to neutral), "<index>_zero_denominator" (division by zero).
    Unknown codes are returned unchanged rather than guessed at.
    """
    if code in _FIXED_REASON_LABELS:
        return _FIXED_REASON_LABELS[code]
    if code.endswith("_set_to_1"):
        index = code.removesuffix("_set_to_1").upper()
        return f"{index} set to neutral (1) because an input is missing"
    if code.endswith("_zero_denominator"):
        index = code.removesuffix("_zero_denominator").upper()
        return f"{index} not computable (division by zero)"
    # The item must be a known line item, so a code that merely happens
    # to end in "_t" is not mislabeled; it falls through unchanged.
    for suffix, year_text in _YEAR_SUFFIXES.items():
        item = code.removesuffix(suffix)
        if code.endswith(suffix) and item in LINE_ITEM_LABELS:
            return f"{LINE_ITEM_LABELS[item]} not reported ({year_text})"
    return code


def verdict_label(value, labels_by_value):
    """Return the icon-and-word label for a verdict value, or NO_SCORE."""
    if is_missing(value):
        return NO_SCORE
    return labels_by_value[value]


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
