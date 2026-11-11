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

# Retry policy for SEC "slow down" (429) and server (5xx) responses.
SEC_MAX_RETRIES = 3
SEC_RETRY_BACKOFF_SECONDS = 10

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
# SPY is the market benchmark for the 12-month return test (stretch goal).
MARKET_BENCHMARK_TICKER = "SPY"


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
