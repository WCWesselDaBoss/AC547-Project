"""Project-wide settings for the Earnings Quality Radar.

Every path, year range, threshold and SEC setting lives here so that no
module hard-codes a number (CLAUDE.md section 6, Traceability). Phase 2
adds the published score coefficients to this same file.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Build paths from this file's location rather than the current working
# directory, so scripts and tests work no matter where they are run from.
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # SEC and price downloads (gitignored)
PROCESSED_DIR = DATA_DIR / "processed"  # Parquet tables from section 4
SAMPLE_DIR = DATA_DIR / "sample"  # small committed copy for fresh clones
LOG_DIR = DATA_DIR / "logs"  # drop counts and coverage reports
INTERIM_DIR = DATA_DIR / "interim"  # cached extracts between steps

# ---------------------------------------------------------------------------
# Universe rules (CLAUDE.md section 2)
# ---------------------------------------------------------------------------
# FY2012 start: smaller filers phased into detailed XBRL tagging around
# 2011, so earlier years would have patchy coverage.
FIRST_FISCAL_YEAR = 2012
# Latest complete fiscal year per the spec. Kept as a constant (not derived
# from today's date) so the universe does not shift between runs.
LAST_FISCAL_YEAR = 2025

# Size floor in nominal US dollars. A company-year qualifies if revenue OR
# total assets meets the floor, tested separately in each fiscal year.
SIZE_FLOOR_USD = 100_000_000

# SIC codes 6000-6799 inclusive: banks, insurers, REITs and blank-check
# shells (6770). Their financial statements do not fit the score formulas.
EXCLUDED_SIC_MIN = 6000
EXCLUDED_SIC_MAX = 6799

# Only domestic annual reports. 20-F and 40-F filers use IFRS or other
# formats, so they are excluded by this rule.
ANNUAL_FORMS = ("10-K", "10-K/A")

# Fiscal year label (Compustat convention): a fiscal year ending in January
# through May belongs to the PRIOR calendar year. Beneish (1999) and
# Piotroski (2000) used Compustat data, so this keeps our year labels
# consistent with the papers, and it groups a January-year-end retailer with
# the calendar-year peers whose fiscal year covered mostly the same months.
FISCAL_YEAR_CUTOFF_MONTH = 5

# A flow item (revenue, net income, CFO) counts as annual only if its period
# covers roughly a year. The window allows 52/53-week fiscal years.
MIN_ANNUAL_PERIOD_DAYS = 350
MAX_ANNUAL_PERIOD_DAYS = 380

# If one 10-K reports the same year's revenue under two mapped revenue tags
# and one is more than this many times the other, they cannot both be total
# revenue; the larger is used (evidence in docs/methodology.md, Tag mapping).
REVENUE_TAG_CONFLICT_RATIO = 3

# ---------------------------------------------------------------------------
# SEC access (CLAUDE.md section 6)
# ---------------------------------------------------------------------------
# SEC requires a User-Agent naming the requester and a contact email. It is
# read from an environment variable so no personal email is committed to
# the repo. Example (PowerShell):
#   $env:SEC_USER_AGENT = "Team Name AC547 your.name@school.edu"
SEC_USER_AGENT_PLACEHOLDER = "EarningsQualityRadar AC547 contact@example.edu"
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", SEC_USER_AGENT_PLACEHOLDER)

# SEC's published limit is 10 requests per second. We stay below it to
# leave a safety margin.
SEC_MAX_REQUESTS_PER_SECOND = 8

# SEC bulk files, confirmed on SEC's "EDGAR Application Programming
# Interfaces" and "Accessing EDGAR Data" pages. The two ZIPs are rebuilt
# nightly (about 3:00 a.m. ET); bulk files are far kinder to SEC than
# thousands of per-company API calls (CLAUDE.md section 6).
SEC_BULK_FILES = {
    # Every company's XBRL facts (one JSON per CIK inside the ZIP).
    "companyfacts.zip": (
        "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
    ),
    # Every company's name, SIC, tickers and filing history.
    "submissions.zip": (
        "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/"
        "submissions.zip"
    ),
    # CIK-ticker-exchange map. SEC does not guarantee its accuracy, so it
    # is a cross-check for tickers, not the primary source.
    "company_tickers_exchange.json": (
        "https://www.sec.gov/files/company_tickers_exchange.json"
    ),
}

# Records what was downloaded and when, because the bulk files change
# nightly and results must be traceable to a specific download.
DOWNLOAD_MANIFEST = RAW_DIR / "download_manifest.json"

# Downloaded bulk files, by name, so readers never rebuild these paths.
COMPANYFACTS_ZIP = RAW_DIR / "companyfacts.zip"
SUBMISSIONS_ZIP = RAW_DIR / "submissions.zip"

# Retry policy for SEC "slow down" (429) and server (5xx) responses.
SEC_MAX_RETRIES = 3
SEC_RETRY_BACKOFF_SECONDS = 10

# ---------------------------------------------------------------------------
# Processed tables and logs (CLAUDE.md section 4)
# ---------------------------------------------------------------------------
COMPANIES_PATH = PROCESSED_DIR / "companies.parquet"
COMPANIES_EXCLUSION_LOG = LOG_DIR / "companies_exclusions.csv"
FACTS_LONG_PATH = PROCESSED_DIR / "facts_long.parquet"
FINANCIALS_PATH = PROCESSED_DIR / "financials_annual.parquet"
PRICES_PATH = PROCESSED_DIR / "prices.parquet"
SCORES_PATH = PROCESSED_DIR / "scores.parquet"
SCORES_LOG = LOG_DIR / "scores_log.csv"
SCORE_DRIVERS_PATH = PROCESSED_DIR / "score_drivers.parquet"
RETURNS_PATH = PROCESSED_DIR / "returns.parquet"

# ---------------------------------------------------------------------------
# Score coefficients and cutoffs (CLAUDE.md section 5)
# ---------------------------------------------------------------------------
# These are the ONLY hard-coded numbers allowed outside data (section 6).
# Sources and page references are in docs/methodology.md, "Phase 2:
# coefficient sources"; check them against the papers before citing.

# Beneish (1999), 8-variable unweighted probit model. Keys are the index
# column names in the scores table.
BENEISH_INTERCEPT = -4.84
BENEISH_COEFFICIENTS = {
    "dsri": 0.920,
    "gmi": 0.528,
    "aqi": 0.404,
    "sgi": 0.892,
    "depi": 0.115,
    "sgai": -0.172,
    "tata": 4.679,
    "lvgi": -0.327,
}
# m_flag uses the 8-variable cutoff; the dashboard slider also offers the
# widely used -2.22 so the analyst can see how sensitive the flag is.
BENEISH_FLAG_CUTOFF = -1.78
BENEISH_ALTERNATE_CUTOFF = -2.22

# Altman Z'' (non-manufacturer, book-equity model). Keys are the ratio
# column names in the scores table. No constant term: the 3.25 "emerging
# market" constant is a different variant and is not used here.
ALTMAN_Z2_COEFFICIENTS = {
    "z_x1": 6.56,
    "z_x2": 3.26,
    "z_x3": 6.72,
    "z_x4": 1.05,
}
# Above SAFE is safe; below DISTRESS is distress; the boundaries
# themselves (exactly 2.60 or 1.10) fall in the grey zone.
ALTMAN_Z2_SAFE_ABOVE = 2.60
ALTMAN_Z2_DISTRESS_BELOW = 1.10

# Two F-Score ratios differing by no more than this fraction of the larger
# one count as a tie (no point). Without it, rounding in the 15th decimal
# place could award or deny a point (CLAUDE.md section 5).
F_SCORE_TIE_TOLERANCE = 1e-9

# F-Score display bands (CLAUDE.md section 4, "Verdict columns"): 0-3
# weak, 4-6 middle, 7-9 strong. A team convention for display, not
# Piotroski's; his paper compared the highest and lowest scores.
F_SCORE_WEAK_MAX = 3
F_SCORE_STRONG_MIN = 7

# score_drivers (src/scores/drivers.py) keeps at most this many
# M-Score components per company-year, and only contributions above
# DRIVER_MIN_CONTRIBUTION: an index meant to be exactly 1 ("no change")
# can come out as 1.0000000000000002, and a 1e-16 contribution must not
# be reported as something pushing the score up.
MAX_DRIVERS = 3
DRIVER_MIN_CONTRIBUTION = 1e-9

# Peer groups (src/scores/peers.py): an industry-size group smaller than
# this falls back to the whole 2-digit SIC industry (Phase 2 spec).
MIN_PEER_GROUP_SIZE = 5

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
# SPY is the market benchmark for the 12-month return test (stretch goal).
MARKET_BENCHMARK_TICKER = "SPY"

# Daily prices start with calendar 2012, the first scored fiscal year;
# returns run 12 months after each 10-K filing date.
PRICE_START_DATE = "2012-01-01"

# Yahoo Finance throttles bursts and yfinance's threaded mode locks its
# SQLite cache on Windows, so downloads run unthreaded in small batches.
PRICE_BATCH_SIZE = 50
PRICE_PAUSE_SECONDS = 2

# A company has "full" price history if its prices start within this many
# days of the first needed date and end within this many of the last.
PRICE_COVERAGE_TOLERANCE_DAYS = 7

PRICES_RAW_DIR = RAW_DIR / "prices"  # one Parquet file per ticker
PRICES_MANIFEST = PRICES_RAW_DIR / "manifest.json"

# ---------------------------------------------------------------------------
# Committed sample (CLAUDE.md section 6, Reproducible)
# ---------------------------------------------------------------------------
# A fresh clone runs the app from these small tables, with no downloads.
SAMPLE_SIZE = 50
# Always included so the demo has a familiar company to show.
SAMPLE_ANCHOR_CIKS = [320193]  # Apple
# Case studies are read from this file (owned by Phase 3, section 4) and
# always included in the sample, so no one edits Phase 1 code to add one.
CASE_STUDIES_PATH = DATA_DIR / "case_studies.csv"
# Any other companies the team wants in the sample, beyond case studies.
SAMPLE_EXTRA_CIKS = []

# ---------------------------------------------------------------------------
# Dashboard data source (Phase 3)
# ---------------------------------------------------------------------------
# The app reads one folder of finished Parquet tables and never computes a
# score (CLAUDE.md section 3). Three folders hold the same table names, so
# switching data needs no code change, only this setting:
#   fixture: tiny made-up tables in tests/fixtures/app/ (hand-checkable)
#   sample:  the committed 50-company sample in data/sample/
#   full:    every company, in data/processed/ (gitignored, built locally)
#   auto:    full if all its tables exist, otherwise sample (the default,
#            so a fresh clone with only data/sample/ runs with no setup)
# Set it per session, e.g. (PowerShell): $env:EQR_DATA_SOURCE = "fixture"
APP_FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "app"
APP_DATA_DIRS = {
    "fixture": APP_FIXTURE_DIR,
    "sample": SAMPLE_DIR,
    "full": PROCESSED_DIR,
}
APP_DATA_SOURCE_AUTO = "auto"
APP_DATA_SOURCE = os.environ.get("EQR_DATA_SOURCE", APP_DATA_SOURCE_AUTO)

# Tables the dashboard needs, by file stem. prices and returns are left
# out: the app does not chart prices, and returns is a stretch goal that
# the app shows only if its file happens to be present.
APP_TABLES = (
    "companies",
    "facts_long",
    "financials_annual",
    "scores",
    "score_drivers",
)


# Screener M-Score cutoff slider. Its range brackets both published
# cutoffs (BENEISH_FLAG_CUTOFF -1.78 and BENEISH_ALTERNATE_CUTOFF -2.22)
# with room on each side, so the analyst can see how sensitive the flag is.
APP_M_CUTOFF_MIN = -3.0
APP_M_CUTOFF_MAX = -1.0
APP_M_CUTOFF_STEP = 0.01

# Screener size filter: bands of total assets in the fiscal year shown.
# A team display convention (like the F-Score bands), not a published
# rule. Absolute bands are used rather than the peer groups' size
# terciles because those terciles exist only where an industry has
# enough companies (none do in the 50-company sample). On the Nov 17
# full data, of the size-floor company-years FY2012-FY2025, 45% are
# small, 40% mid and 15% large (21 have no total assets, so no band).
# Each band includes its lower edge and excludes its upper.
APP_SIZE_BANDS = {
    "Small (under $1B assets)": (0, 1_000_000_000),
    "Mid ($1B to $10B)": (1_000_000_000, 10_000_000_000),
    "Large ($10B and over)": (10_000_000_000, float("inf")),
}


def missing_app_tables(data_dir):
    """Return the APP_TABLES file names that are missing from data_dir."""
    return [
        f"{table}.parquet"
        for table in APP_TABLES
        if not (data_dir / f"{table}.parquet").exists()
    ]


def app_data_dir(source=None):
    """Return the folder the dashboard should read its tables from.

    source is "auto", "fixture", "sample" or "full" (default: the
    EQR_DATA_SOURCE setting). "auto" prefers full data but falls back to
    the sample, because data/processed/ is gitignored and may be partly
    built (e.g. Phase 1 tables present but no scores yet). A source named
    explicitly is never swapped for another: if its tables are missing,
    this raises, so the analyst cannot mistake sample results for full
    ones (CLAUDE.md section 6, no silent fixes).
    """
    if source is None:
        source = APP_DATA_SOURCE
    source = source.strip().lower()
    if source == APP_DATA_SOURCE_AUTO:
        if not missing_app_tables(APP_DATA_DIRS["full"]):
            return APP_DATA_DIRS["full"]
        source = "sample"
    if source not in APP_DATA_DIRS:
        valid = ", ".join([APP_DATA_SOURCE_AUTO, *APP_DATA_DIRS])
        raise ValueError(
            f"Unknown data source {source!r}; use one of: {valid}"
        )
    data_dir = APP_DATA_DIRS[source]
    missing = missing_app_tables(data_dir)
    if missing:
        raise FileNotFoundError(
            f"Data source {source!r} ({data_dir}) is missing: "
            f"{', '.join(missing)}"
        )
    return data_dir


def fiscal_year_from_period_end(period_end):
    """Return the fiscal year label for a period ending on period_end.

    Uses the period end date, never SEC's fy field, because fy describes
    the filing rather than the period (CLAUDE.md section 4). Periods ending
    January through FISCAL_YEAR_CUTOFF_MONTH map to the prior year.
    """
    if period_end.month <= FISCAL_YEAR_CUTOFF_MONTH:
        return period_end.year - 1
    return period_end.year


def user_agent_is_placeholder(user_agent=SEC_USER_AGENT):
    """Return True if the SEC User-Agent has not been set by the user.

    The downloader calls this and refuses to contact SEC with the
    placeholder, because SEC may block anonymous-looking traffic.
    """
    return user_agent.strip() == SEC_USER_AGENT_PLACEHOLDER
