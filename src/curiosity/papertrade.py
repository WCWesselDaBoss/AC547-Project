"""Paper-trading tracker for the late-filing rule (hypothetical trades).

Curiosity work, NOT part of the class project. The rules are frozen in
docs/curiosity/paper_trade_rules.md (version 1) and this module follows
them. It never connects to a brokerage and never places an order; it
only reads public data (SEC EDGAR, Yahoo Finance prices) and writes
logs. This is a hypothetical research log, not investment advice.

Run weekly:  python -m src.curiosity.papertrade
Each run:
1. finds new NT 10-K filings in SEC's daily form indexes since the last
   run (catching up on missed days), from the rules' start date on;
2. scores each company point in time, from its SEC company facts and
   filings dated before the NT 10-K, with the project's own pipeline
   and score functions;
3. fills entry and exit prices as the trading days arrive;
4. checks that no earlier logged field was changed, and stops with an
   error if one was;
5. rewrites docs/curiosity/paper_trade_status.md (monitoring only).
"""

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import re
import zipfile
from collections import Counter

import numpy as np
import pandas as pd

import config
from src.pipeline import download, facts, financials, prices
from src.scores import build_scores, verdicts

RULES_VERSION = 1
RULES_START = pd.Timestamp("2026-11-20")  # date of the rules' commit (7722c0a)

PAPER_DIR = config.DATA_DIR / "papertrade"
EVENTS_LOG = PAPER_DIR / "events_log.csv"
TRADES_LOG = PAPER_DIR / "trades_log.csv"
LEDGER = PAPER_DIR / "ledger.csv"
STATE_FILE = PAPER_DIR / "state.json"
PRICE_CACHE = PAPER_DIR / "prices"
STATUS_DOC = (
    config.PROJECT_ROOT / "docs" / "curiosity" / "paper_trade_status.md"
)

NOTIONAL = 10_000.0
HOLD_DAYS = 63  # exit on trading day 63; the entry day is day 1
HISTORY_DAYS = 20
MIN_PRICE = 5.0
REPEAT_DAYS = 63
STOPPED_DAYS = 5  # no stock price for this many trading days: stopped
MAX_SCORE_AGE_MONTHS = 15
BORROW_RATE = 0.10  # a year
BORROW_COST = BORROW_RATE * HOLD_DAYS / 252  # 2.5% of the short side
BORROW_NOTE = "borrowing availability unknown"
INDEX_GRACE_DAYS = 3  # a missing daily index this old is a non-trading day
SPY = config.MARKET_BENCHMARK_TICKER

DAILY_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{quarter}/"
    "form.{day}.idx"
)
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Log columns. FROZEN columns never change once a row is written;
# FILLABLE ones may be filled once (empty -> value) by a later run, and
# status may only move forward. Any other change stops the run.
EVENT_COLUMNS = [
    "row_id",
    "row_type",
    "corrects_row_id",
    "correction_reason",
    "rules_version",
    "accession",
    "cik",
    "company_name",
    "ticker",
    "form",
    "filing_date",
    "date_logged",
    "sic",
    "score_status",
    "score_fiscal_year",
    "score_10k_filed",
    "m_score",
    "z_score",
    "f_score",
    "flags_raised",
    "group",
    "entry_date",
    "eligibility",
    "trade_row_id",
]
EVENT_FILLABLE = ["entry_date", "eligibility", "trade_row_id"]
TRADE_COLUMNS = [
    "row_id",
    "row_type",
    "corrects_row_id",
    "correction_reason",
    "rules_version",
    "event_row_id",
    "accession",
    "cik",
    "ticker",
    "group",
    "flags_raised",
    "filing_date",
    "entry_date",
    "entry_price_stock",
    "entry_price_spy",
    "borrowing_note",
    "status",
    "exit_date",
    "exit_price_stock",
    "exit_price_spy",
    "exit_note",
    "stock_return",
    "spy_return",
    "result",
    "result_after_borrow",
    "result_dollars",
]
TRADE_FILLABLE = [
    "status",
    "exit_date",
    "exit_price_stock",
    "exit_price_spy",
    "exit_note",
    "stock_return",
    "spy_return",
    "result",
    "result_after_borrow",
    "result_dollars",
]
STATUS_ORDER = {"open": 0, "closed": 1, "closed_at_last_price": 1}


class AppendOnlyError(RuntimeError):
    """Raised when an earlier logged field has changed."""


# ---------------------------------------------------------------------------
# SEC access (public data, our User-Agent, under 10 requests a second)
# ---------------------------------------------------------------------------
class SecClient:
    """Fetch SEC pages with the project's User-Agent and rate limit.
    Returns None for a page that does not exist (for example, a daily
    index on a weekend)."""

    def __init__(self, session=None, limiter=None):
        """Use the pipeline's session (refuses the placeholder User-Agent)
        and rate limiter."""
        self.session = session or download.build_session()
        self.limiter = limiter or download.RateLimiter(
            config.SEC_MAX_REQUESTS_PER_SECOND
        )

    def get(self, url):
        """Return the response text, or None if the page is missing."""
        self.limiter.wait()
        response = self.session.get(url, timeout=60)
        if response.status_code in (403, 404):
            return None
        response.raise_for_status()
        return response.text

    def get_json(self, url):
        """Return parsed JSON, or None if the page is missing."""
        text = self.get(url)
        return None if text is None else json.loads(text)


INDEX_LINE = re.compile(
    r"^(?P<form>\S.*?)\s{2,}(?P<company>.+?)\s{2,}(?P<cik>\d+)\s{2,}"
    r"(?P<date>\d{4}-?\d{2}-?\d{2})\s{2,}(?P<file>\S+)\s*$"
)


def parse_form_index(text):
    """Return the NT 10-K rows (form, company, cik, date, accession) of
    one SEC daily form index. Only the exact form "NT 10-K" counts;
    "NT 10-K/A" and every other form are ignored."""
    rows = []
    for line in text.splitlines():
        match = INDEX_LINE.match(line)
        if not match or match["form"].strip() != "NT 10-K":
            continue
        accession = match["file"].rsplit("/", 1)[-1].removesuffix(".txt")
        rows.append(
            {
                "form": "NT 10-K",
                "company_name": match["company"].strip(),
                "cik": int(match["cik"]),
                "filing_date": pd.Timestamp(match["date"]),
                "accession": accession,
            }
        )
    return rows


def daily_index_url(day):
    """Return the URL of SEC's form index for one day."""
    quarter = (day.month - 1) // 3 + 1
    return DAILY_INDEX_URL.format(
        year=day.year, quarter=quarter, day=day.strftime("%Y%m%d")
    )


def new_filings(fetch, last_processed, today):
    """Return (NT 10-K filings since last_processed, new last processed
    day). fetch(url) returns the page text or None.

    Days run from the day after last_processed (or RULES_START) to
    yesterday. A missing index is treated as a non-trading day only once
    it is INDEX_GRACE_DAYS old; a more recent one may simply not be
    posted yet, so processing stops there and resumes next run.
    """
    day = (
        RULES_START
        if last_processed is None
        else pd.Timestamp(last_processed) + pd.Timedelta(days=1)
    )
    rows, processed = [], last_processed
    while day < today:
        text = fetch(daily_index_url(day))
        if text is None and (today - day).days < INDEX_GRACE_DAYS:
            break
        if text is not None:
            rows.extend(
                row
                for row in parse_form_index(text)
                if row["filing_date"] >= RULES_START
            )
        processed = day
        day += pd.Timedelta(days=1)
    return rows, processed


# ---------------------------------------------------------------------------
# Point-in-time scoring with the project's own functions
# ---------------------------------------------------------------------------
def facts_before(company_facts, event_date):
    """Return a copy of a company-facts JSON keeping only facts from
    filings made strictly before event_date."""
    kept = copy.deepcopy(company_facts)
    cutoff = event_date.strftime("%Y-%m-%d")
    for taxonomy in kept.get("facts", {}).values():
        for tag_info in taxonomy.values():
            for unit, unit_facts in tag_info.get("units", {}).items():
                tag_info["units"][unit] = [
                    fact
                    for fact in unit_facts
                    if fact.get("filed", "") < cutoff
                ]
    return kept


def filings_before(table, event_date):
    """Return a submissions filings table keeping only filings made
    strictly before event_date."""
    cutoff = event_date.strftime("%Y-%m-%d")
    keep = [i for i, filed in enumerate(table["filingDate"]) if filed < cutoff]
    return {
        key: [values[i] for i in keep]
        for key, values in table.items()
        if isinstance(values, list)
    }


def zip_of(files):
    """Return an in-memory zip holding {name: JSON object}, so the
    pipeline's zip-based functions run unchanged on one company."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, json.dumps(payload))
    buffer.seek(0)
    return buffer


@contextlib.contextmanager
def fiscal_year_cap(year):
    """Temporarily raise config.LAST_FISCAL_YEAR to at least year.

    The project scores fiscal years up to 2025 and the pipeline drops
    later years; the paper trades start in late 2026, so later events
    need later 10-Ks. Only the range of years read changes, not any
    scoring rule, and the project's value is restored afterwards.
    """
    original = config.LAST_FISCAL_YEAR
    config.LAST_FISCAL_YEAR = max(original, year)
    try:
        yield
    finally:
        config.LAST_FISCAL_YEAR = original


def point_in_time_score(cik, event_date, company_facts, submission, overflow):
    """Return the company's flag status as of event_date.

    company_facts and submission are SEC's JSON for the company;
    overflow maps overflow file names to their JSON. Everything filed on
    or after event_date is removed first; then the project's own
    facts_long, financials_annual, score and verdict functions run on
    what is left. Returns a dict with score_status ("ok" or the reason)
    and the latest fiscal year's scores.
    """
    result = {"score_status": "no_prior_10k"}
    sub = copy.deepcopy(submission)
    sub["filings"]["recent"] = filings_before(
        sub["filings"]["recent"], event_date
    )
    files = {f"CIK{cik:010d}.json": sub}
    for name, table in overflow.items():
        files[name] = filings_before(table, event_date)
    if "10-K" not in sub["filings"]["recent"].get("form", []) and not any(
        "10-K" in table.get("form", [])
        for name, table in files.items()
        if name != f"CIK{cik:010d}.json"
    ):
        return result
    try:
        with fiscal_year_cap(event_date.year), contextlib.redirect_stdout(
            io.StringIO()
        ):
            facts_long_df, _ = facts.build_facts_long(
                zip_of(
                    {
                        f"CIK{cik:010d}.json": facts_before(
                            company_facts, event_date
                        )
                    }
                ),
                [cik],
            )
            index_df = financials.annual_report_index(zip_of(files), [cik], {})
            financials_df = financials.build_financials(
                facts_long_df, index_df, {}
            )
            scores_df = verdicts.add_verdicts(
                build_scores.compute_all_scores(financials_df, facts_long_df)
            )
    except (ValueError, KeyError) as error:
        # The pipeline cannot build anything from no facts (for example,
        # a company whose 10-Ks carry no XBRL). Recorded with the message,
        # so a real bug is visible in the log rather than hidden.
        return {
            "score_status": f"no_score_before ({type(error).__name__}: {error})"
        }
    if financials_df.empty:
        return {"score_status": "no_score_before"}
    latest = financials_df.sort_values("fiscal_year").iloc[-1]
    row = scores_df[scores_df["fiscal_year"] == latest["fiscal_year"]].iloc[0]
    result = {
        "score_fiscal_year": int(latest["fiscal_year"]),
        "score_10k_filed": latest["filed_date"].date(),
        "m_score": row["m_score"],
        "z_score": row["z_score"],
        "f_score": row["f_score"],
        "flags_raised": row["flags_raised"],
    }
    oldest = event_date - pd.DateOffset(months=MAX_SCORE_AGE_MONTHS)
    if latest["filed_date"] < oldest:
        result["score_status"] = "score_too_old"
    elif not bool(latest["passes_size_floor"]):
        result["score_status"] = "fails_size_floor"
    elif (
        pd.isna(row["m_score"])
        or pd.isna(row["z_score"])
        or pd.isna(row["f_score"])
    ):
        result["score_status"] = "missing_a_score"
    else:
        result["score_status"] = "ok"
        result["group"] = (
            "flagged" if int(row["flags_raised"]) >= 1 else "clean"
        )
    return result


def screen_and_score(filing, sec, tickers):
    """Return the event row fields for one NT 10-K filing: ticker, SIC
    and, for companies that pass the screen, the point-in-time score."""
    cik, event_date = filing["cik"], filing["filing_date"]
    record = {"ticker": tickers.get(cik), "sic": None}
    if record["ticker"] is None:
        return {**record, "score_status": "no_current_ticker"}
    submission = sec.get_json(
        SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json")
    )
    if submission is None:
        return {**record, "score_status": "no_submissions_record"}
    sic = submission.get("sic")
    record["sic"] = int(sic) if sic else None
    if record["sic"] is None:
        return {**record, "score_status": "missing_sic"}
    if config.EXCLUDED_SIC_MIN <= record["sic"] <= config.EXCLUDED_SIC_MAX:
        return {**record, "score_status": "excluded_sic"}
    overflow = {
        extra["name"]: sec.get_json(SUBMISSIONS_URL.format(name=extra["name"]))
        for extra in submission["filings"].get("files", [])
    }
    company_facts = sec.get_json(FACTS_URL.format(cik=cik)) or {}
    return {
        **record,
        **point_in_time_score(
            cik, event_date, company_facts, submission, overflow
        ),
    }


def current_tickers(sec):
    """Return {cik: ticker} from SEC's company ticker file (the first
    ticker listed for each company)."""
    data = sec.get_json(TICKERS_URL) or {}
    tickers = {}
    for entry in data.values():
        tickers.setdefault(int(entry["cik_str"]), entry["ticker"])
    return tickers


# ---------------------------------------------------------------------------
# Prices (yfinance, cached locally)
# ---------------------------------------------------------------------------
def price_history(tickers, start, end, downloader=None):
    """Return a date x ticker table of adjusted closes from start to
    end, downloaded with the pipeline's yfinance wrapper and saved in
    the local cache (a later download replaces a ticker's cache)."""
    PRICE_CACHE.mkdir(parents=True, exist_ok=True)
    kwargs = {} if downloader is None else {"downloader": downloader}
    long_df, _ = prices.download_batch(
        list(tickers), start=start, end=end + pd.Timedelta(days=1), **kwargs
    )
    for ticker, rows in long_df.groupby("ticker"):
        rows.to_parquet(PRICE_CACHE / f"{ticker}.parquet", index=False)
    if long_df.empty:
        return pd.DataFrame()
    return long_df.pivot_table(
        index="date", columns="ticker", values="adj_close"
    )


def entry_and_checks(table, filing_date, ticker):
    """Return (entry date or None, eligibility) from a price table with
    SPY. Entry is the first SPY trading day after the filing date;
    eligibility is "eligible" or why not (no entry day yet, history,
    price)."""
    calendar = table[SPY].dropna().index
    after = calendar[calendar > filing_date]
    if after.empty:
        return None, None  # entry day not reached yet
    entry = after[0]
    # The 20 trading days strictly before the filing date.
    before = calendar[calendar < filing_date][-HISTORY_DAYS:]
    if ticker not in table or len(before) < HISTORY_DAYS:
        return entry, "ineligible: no price history"
    if table.loc[before, ticker].isna().any():
        return (
            entry,
            "ineligible: fewer than 20 days of prices before the filing",
        )
    price = table.loc[entry, ticker]
    if pd.isna(price):
        return entry, "ineligible: no price on the entry day"
    if price < MIN_PRICE:
        return entry, f"ineligible: entry price below ${MIN_PRICE:.0f}"
    return entry, "eligible"


def exit_plan(table, entry, ticker):
    """Return (exit date, stock close, SPY close, note) once the trade
    can be closed, or None while it stays open.

    The exit is the close on trading day 63 (the entry day is day 1). If
    the stock has no price on that day, its last price on or before it
    is used (a short data gap). If, before day 63, the stock has had no
    price for STOPPED_DAYS trading days in a row, the trade closes at
    its last available price (delisted or halted); no price is invented.
    """
    calendar = table[SPY].dropna().index
    position = calendar.get_loc(entry)
    target = position + HOLD_DAYS - 1
    end = min(target, len(calendar) - 1)
    window = table[ticker].loc[entry : calendar[end]]
    last_seen = window.last_valid_index()
    missing_after = end - calendar.get_loc(last_seen)
    if missing_after >= STOPPED_DAYS:
        return (
            last_seen,
            window.loc[last_seen],
            table.loc[last_seen, SPY],
            ("closed at last price (stock stopped trading)"),
        )
    if target < len(calendar):
        day = calendar[target]
        return (
            day,
            window.loc[last_seen],
            table.loc[day, SPY],
            "exit on day 63",
        )
    return None


def trade_result(entry_stock, entry_spy, exit_stock, exit_spy):
    """Return the result fields: SPY's return minus the stock's
    (positive = the short-against-SPY trade made money), the same after
    the 2.5% borrowing cost, and in dollars on $10,000 a side."""
    stock_return = exit_stock / entry_stock - 1
    spy_return = exit_spy / entry_spy - 1
    result = spy_return - stock_return
    return {
        "stock_return": stock_return,
        "spy_return": spy_return,
        "result": result,
        "result_after_borrow": result - BORROW_COST,
        "result_dollars": NOTIONAL * result,
    }


# ---------------------------------------------------------------------------
# Append-only logs
# ---------------------------------------------------------------------------
def read_log(path, columns):
    """Return a log as strings (empty if missing), in column order."""
    if not path.exists():
        return pd.DataFrame(columns=columns, dtype="string")
    return pd.read_csv(path, dtype="string", keep_default_na=False)[columns]


def fingerprint(values):
    """Return a short SHA-256 fingerprint of a list of strings."""
    joined = "\x1f".join("" if v is None else str(v) for v in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


def frozen_columns(columns, fillable):
    """Return the columns that never change once a row is written."""
    return [c for c in columns if c not in fillable]


def check_append_only(old, new, columns, fillable, name):
    """Raise AppendOnlyError unless new extends old without changing it:
    every old row is still there, in order, with every frozen field
    unchanged; a fillable field may only go from empty to a value, and
    status may only move forward."""
    if len(new) < len(old):
        raise AppendOnlyError(f"{name}: rows were removed")
    for i in range(len(old)):
        before, after = old.iloc[i], new.iloc[i]
        for column in frozen_columns(columns, fillable):
            if before[column] != after[column]:
                raise AppendOnlyError(
                    f"{name} row {before['row_id']}: frozen field '{column}' "
                    f"changed from {before[column]!r} to {after[column]!r}"
                )
        for column in fillable:
            if before[column] in ("", after[column]):
                continue
            if column == "status" and STATUS_ORDER.get(
                after[column], -1
            ) > STATUS_ORDER.get(before[column], 99):
                continue
            raise AppendOnlyError(
                f"{name} row {before['row_id']}: filled field '{column}' "
                f"changed from {before[column]!r} to {after[column]!r}"
            )


def check_ledger(log, columns, fillable, ledger, name):
    """Raise AppendOnlyError if any logged row's frozen fields no longer
    match the fingerprint recorded when it was written (this catches a
    hand edit between runs), or a ledgered row is missing."""
    recorded = ledger[ledger["log"] == name].set_index("row_id")["fingerprint"]
    # Keep row_id as a column too: it is one of the fingerprinted fields.
    rows = log.set_index("row_id", drop=False)
    for row_id, expected in recorded.items():
        if row_id not in rows.index:
            raise AppendOnlyError(f"{name} row {row_id} is missing")
        actual = fingerprint(
            rows.loc[row_id, frozen_columns(columns, fillable)].tolist()
        )
        if actual != expected:
            raise AppendOnlyError(
                f"{name} row {row_id}: a frozen field was edited after it was "
                "logged (fingerprint mismatch)"
            )


def ledger_rows(log, columns, fillable, ledger, name):
    """Return ledger rows for log rows not yet fingerprinted."""
    known = set(ledger.loc[ledger["log"] == name, "row_id"])
    new = log[~log["row_id"].isin(known)]
    return pd.DataFrame(
        {
            "log": name,
            "row_id": new["row_id"],
            "fingerprint": [
                fingerprint(row[frozen_columns(columns, fillable)].tolist())
                for _, row in new.iterrows()
            ],
        }
    )


def next_id(log, prefix):
    """Return the next row id, e.g. E000001."""
    return f"{prefix}{len(log) + 1:06d}"


def as_text(value):
    """Return a log cell: empty for missing, plain text otherwise."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    if value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, (pd.Timestamp, dt.date)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def append_row(log, values, columns):
    """Return log with one new row (missing columns left empty)."""
    row = {column: as_text(values.get(column)) for column in columns}
    return pd.concat(
        [log, pd.DataFrame([row], dtype="string")], ignore_index=True
    )


def add_correction(log, row_id, changes, reason, columns, prefix):
    """Return log with a correction row: a copy of row_id with the given
    field changes, pointing back to it. The original row is untouched."""
    original = log[log["row_id"] == row_id]
    if original.empty:
        raise ValueError(f"no row {row_id}")
    values = original.iloc[0].to_dict()
    values.update(changes)
    values.update(
        row_id=next_id(log, prefix),
        row_type="correction",
        corrects_row_id=row_id,
        correction_reason=reason,
    )
    return append_row(log, values, columns)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------
def read_state():
    """Return the saved state (last processed index day)."""
    if not STATE_FILE.exists():
        return {"last_processed": None}
    return json.loads(STATE_FILE.read_text())


def log_new_events(events, filings, sec, tickers, today):
    """Return the events log with one original row per new filing (the
    accession number is the key, so a filing is never logged twice)."""
    seen = set(events["accession"])
    for filing in filings:
        if filing["accession"] in seen:
            continue
        values = {
            **filing,
            **screen_and_score(filing, sec, tickers),
            "row_id": next_id(events, "E"),
            "row_type": "original",
            "rules_version": RULES_VERSION,
            "date_logged": today,
        }
        events = append_row(events, values, EVENT_COLUMNS)
        seen.add(filing["accession"])
    return events


def originals(log):
    """Return the rows in effect: originals, each replaced by its latest
    correction if it has one."""
    current = log[log["row_type"] == "original"].set_index(
        "row_id", drop=False
    )
    for _, correction in log[log["row_type"] == "correction"].iterrows():
        current.loc[correction["corrects_row_id"]] = correction.to_numpy()
    return current


def is_repeat(trades, cik, entry, calendar):
    """Return True if the company has a trade whose entry day is within
    the REPEAT_DAYS trading days before entry."""
    earlier = trades[
        (trades["cik"] == str(cik)) & (trades["entry_date"] != "")
    ]
    position = calendar.get_loc(entry)
    for value in earlier["entry_date"]:
        other = pd.Timestamp(value)
        if (
            other in calendar
            and 0 <= position - calendar.get_loc(other) <= REPEAT_DAYS
        ):
            return True
    return False


def update_entries_and_exits(events, trades, price_table_for, today):
    """Fill entry checks for events whose entry day has passed (creating
    trades for eligible ones) and exits for open trades whose day 63, or
    stop, has arrived. price_table_for(tickers, start, end) returns a
    date x ticker table including SPY."""
    scored = events[
        (events["score_status"] == "ok") & (events["eligibility"] == "")
    ]
    for index, event in scored.iterrows():
        filed = pd.Timestamp(event["filing_date"])
        table = price_table_for(
            [event["ticker"], SPY], filed - pd.Timedelta(days=60), today
        )
        if table.empty or SPY not in table:
            continue
        entry, eligibility = entry_and_checks(table, filed, event["ticker"])
        if entry is None:
            continue  # pending entry
        calendar = table[SPY].dropna().index
        if eligibility == "eligible" and is_repeat(
            trades, event["cik"], entry, calendar
        ):
            eligibility = "not traded: repeat within 63 trading days"
        events.loc[index, "entry_date"] = as_text(entry)
        events.loc[index, "eligibility"] = eligibility
        if eligibility != "eligible":
            continue
        trade_id = next_id(trades, "T")
        trades = append_row(
            trades,
            {
                "row_id": trade_id,
                "row_type": "original",
                "rules_version": event["rules_version"],
                "event_row_id": event["row_id"],
                "accession": event["accession"],
                "cik": event["cik"],
                "ticker": event["ticker"],
                "group": event["group"],
                "flags_raised": event["flags_raised"],
                "filing_date": event["filing_date"],
                "entry_date": entry,
                "entry_price_stock": table.loc[entry, event["ticker"]],
                "entry_price_spy": table.loc[entry, SPY],
                "borrowing_note": BORROW_NOTE,
                "status": "open",
            },
            TRADE_COLUMNS,
        )
        events.loc[index, "trade_row_id"] = trade_id

    for index, trade in trades[trades["status"] == "open"].iterrows():
        entry = pd.Timestamp(trade["entry_date"])
        table = price_table_for([trade["ticker"], SPY], entry, today)
        if table.empty or SPY not in table:
            continue
        plan = exit_plan(table, entry, trade["ticker"])
        if plan is None:
            continue
        exit_day, exit_stock, exit_spy, note = plan
        # Entry and exit come from the same download, so splits and
        # dividends in between are handled consistently.
        fields = trade_result(
            table.loc[entry, trade["ticker"]],
            table.loc[entry, SPY],
            exit_stock,
            exit_spy,
        )
        fields.update(
            exit_date=exit_day,
            exit_price_stock=exit_stock,
            exit_price_spy=exit_spy,
            exit_note=note,
            status=(
                "closed"
                if note == "exit on day 63"
                else "closed_at_last_price"
            ),
        )
        for column, value in fields.items():
            trades.loc[index, column] = as_text(value)
    return events, trades


def write_status(events, trades, today):
    """Rewrite docs/curiosity/paper_trade_status.md (monitoring only)."""
    current_events = originals(events)
    current_trades = originals(trades)
    lines = [
        "# Paper-trading status (late-filing rule)",
        "",
        "**Monitoring only; the rule is not evaluated until the condition "
        "in the rules file is met.** Hypothetical trades, not investment "
        "advice. Rules: `docs/curiosity/paper_trade_rules.md` (version "
        f"{RULES_VERSION}). Updated {today:%Y-%m-%d}.",
        "",
        "## Events",
        "",
    ]
    counts = Counter(
        (e["score_status"] if e["score_status"] != "ok" else e["group"])
        for _, e in current_events.iterrows()
    )
    if not counts:
        lines.append(
            "No events logged yet (NT 10-K filings count from "
            f"{RULES_START:%Y-%m-%d})."
        )
    else:
        lines += ["| Status | Events |", "| --- | --- |"]
        lines += [
            f"| {key} | {value} |" for key, value in sorted(counts.items())
        ]
    lines += ["", "## Trades", ""]
    if current_trades.empty:
        lines.append("No hypothetical trades yet.")
    else:
        lines += ["| Group | Open | Closed |", "| --- | --- | --- |"]
        for group in ("flagged", "clean"):
            part = current_trades[current_trades["group"] == group]
            lines.append(
                f"| {group} | {(part['status'] == 'open').sum()} | "
                f"{part['status'].str.startswith('closed').sum()} |"
            )
        closed = current_trades[
            current_trades["status"].str.startswith("closed")
        ]
        if not closed.empty:
            closed = closed.assign(
                result=closed["result"].astype(float),
                result_after_borrow=closed["result_after_borrow"].astype(
                    float
                ),
            )
            lines += [
                "",
                "Closed trades, average result (SPY return minus stock "
                "return; after the 2.5% borrowing cost):",
                "",
                "| Group | Flags | Trades | Result | After borrowing |",
                "| --- | --- | --- | --- | --- |",
            ]
            for (group, flags), part in closed.groupby(
                ["group", "flags_raised"]
            ):
                lines.append(
                    f"| {group} | {flags} | {len(part)} | "
                    f"{100 * part['result'].mean():+.1f}% | "
                    f"{100 * part['result_after_borrow'].mean():+.1f}% |"
                )
    STATUS_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(today=None, sec=None, price_table_for=None):
    """Do one tracker run and return (events, trades)."""
    today = pd.Timestamp(today or dt.date.today())
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    events_before = read_log(EVENTS_LOG, EVENT_COLUMNS)
    trades_before = read_log(TRADES_LOG, TRADE_COLUMNS)
    ledger = (
        pd.read_csv(LEDGER, dtype="string")
        if LEDGER.exists()
        else pd.DataFrame(
            columns=["log", "row_id", "fingerprint"], dtype="string"
        )
    )
    # Fail loudly before doing anything if an earlier row was edited.
    check_ledger(
        events_before, EVENT_COLUMNS, EVENT_FILLABLE, ledger, "events"
    )
    check_ledger(
        trades_before, TRADE_COLUMNS, TRADE_FILLABLE, ledger, "trades"
    )

    sec = sec or SecClient()
    price_table_for = price_table_for or price_history
    state = read_state()
    filings, processed = new_filings(sec.get, state["last_processed"], today)
    events = log_new_events(
        events_before.copy(),
        filings,
        sec,
        current_tickers(sec) if filings else {},
        today,
    )
    events, trades = update_entries_and_exits(
        events, trades_before.copy(), price_table_for, today
    )

    check_append_only(
        events_before, events, EVENT_COLUMNS, EVENT_FILLABLE, "events"
    )
    check_append_only(
        trades_before, trades, TRADE_COLUMNS, TRADE_FILLABLE, "trades"
    )
    ledger = pd.concat(
        [
            ledger,
            ledger_rows(
                events, EVENT_COLUMNS, EVENT_FILLABLE, ledger, "events"
            ),
            ledger_rows(
                trades, TRADE_COLUMNS, TRADE_FILLABLE, ledger, "trades"
            ),
        ],
        ignore_index=True,
    )
    events.to_csv(EVENTS_LOG, index=False)
    trades.to_csv(TRADES_LOG, index=False)
    ledger.to_csv(LEDGER, index=False)
    STATE_FILE.write_text(
        json.dumps(
            {
                "last_processed": (
                    None
                    if processed is None
                    else str(pd.Timestamp(processed).date())
                )
            }
        )
    )
    write_status(events, trades, today)
    return events, trades


def main(argv=None):
    """Run the tracker, or add a correction row (--correct)."""
    parser = argparse.ArgumentParser(
        description="Paper-trading tracker (hypothetical)"
    )
    parser.add_argument(
        "--correct", metavar="ROW_ID", help="add a correction row for this row"
    )
    parser.add_argument("--field", help="the field to correct")
    parser.add_argument("--value", help="the corrected value")
    parser.add_argument("--reason", help="why the correction is needed")
    args = parser.parse_args(argv)
    if args.correct:
        if not (args.field and args.reason):
            parser.error("--correct needs --field and --reason")
        is_event = args.correct.startswith("E")
        path, columns, prefix = (
            (EVENTS_LOG, EVENT_COLUMNS, "E")
            if is_event
            else (TRADES_LOG, TRADE_COLUMNS, "T")
        )
        log = add_correction(
            read_log(path, columns),
            args.correct,
            {args.field: args.value or ""},
            args.reason,
            columns,
            prefix,
        )
        log.to_csv(path, index=False)
        print(
            f"Added a correction row for {args.correct}; the original is unchanged."
        )
        return
    events, trades = run()
    print(f"events logged: {len(events)}, trades: {len(trades)}")
    print(f"status: {STATUS_DOC}")


if __name__ == "__main__":
    main()
