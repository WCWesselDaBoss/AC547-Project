"""Curiosity, part 2: did put prices on flagged stocks underestimate
crashes?

Not part of the class project's test register. Definitions were fixed
in docs/curiosity/implied_vol.md before any result was computed; this
module follows them.

Licensed data. The OptionMetrics files from WRDS stay in data/raw/wrds/
(gitignored) and are read by their exact names, never with a wildcard.
At most 5 raw rows are ever printed. Anything written outside
data/raw/wrds/ holds derived values, not raw WRDS rows.

Step 3a (this run): match our observations to OptionMetrics securities
and write the below-threshold name pairs for hand review. No result is
computed until that review is done.

This is an analysis for a class project, not investment advice.
"""

import difflib
import json
import math
import re
import zipfile

import numpy as np
import pandas as pd
from scipy.stats import norm

import config
from src.scores import backtest

WRDS_DIR = config.RAW_DIR / "wrds"
SURFACE_FILE = WRDS_DIR / "vsurf_puts_730d.csv.gz"
NAMES_FILE = WRDS_DIR / "secnmd_names.csv.gz"
# Below-threshold pairs for hand review. It holds licensed names, so it
# stays in the gitignored WRDS folder.
REVIEW_FILE = WRDS_DIR / "name_review.csv"
OBSERVATIONS_FILE = config.LOG_DIR / "curiosity_vol_matched.csv"

SURFACE_COLUMNS = [
    "secid",
    "date",
    "delta",
    "impl_volatility",
    "impl_strike",
    "impl_premium",
    "ticker",
    "issue_type",
]
DELTAS = [-50, -25]
FALLBACK_TRADING_DAYS = 5  # look back at most this far; never forward
NAME_THRESHOLD = 0.85
ADR_ISSUE_TYPE = "F"  # ADR/ADS (IvyDB US Reference Manual v5.0)
MAX_PRINTED_ROWS = 5
# Words dropped before comparing names, so "Apple Inc." and "APPLE INC"
# compare as the same name.
NAME_STOP_WORDS = {
    "THE",
    "INC",
    "INCORPORATED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "LTD",
    "LIMITED",
    "PLC",
    "LLC",
    "LP",
    "HOLDINGS",
    "HOLDING",
    "GROUP",
    "CLASS",
    "CL",
    "A",
    "B",
    "NEW",
}
REJECT_NO_WRDS_TICKER = "no_wrds_ticker"
REJECT_NO_NAME = "no_name_on_start"
REJECT_NAME = "name_below_threshold"
REJECT_AMBIGUOUS = "ambiguous_two_secids"


# ---------------------------------------------------------------------------
# Reading the WRDS files (exact names only)
# ---------------------------------------------------------------------------
def usable_rows(surface_df):
    """Return only usable surface rows: implied volatility present and
    strike and premium both above zero. OptionMetrics writes -99.99 (and
    sometimes 0) when a value is missing, so those rows are dropped and
    the fallback may fill the day from an earlier one."""
    usable = (
        surface_df["impl_volatility"].notna()
        & (surface_df["impl_strike"] > 0)
        & (surface_df["impl_premium"] > 0)
    )
    return surface_df[usable]


def load_surface(path=SURFACE_FILE):
    """Read the volatility-surface file by its exact name and return the
    usable rows."""
    surface = pd.read_csv(path, usecols=SURFACE_COLUMNS, low_memory=False)
    surface["date"] = pd.to_datetime(surface["date"])
    return usable_rows(surface).reset_index(drop=True)


def load_names(path=NAMES_FILE):
    """Read the name-history file by its exact name: secid, effective
    date and issuer name, oldest first."""
    names = pd.read_csv(path, usecols=["secid", "effect_date", "issuer"])
    names["effect_date"] = pd.to_datetime(names["effect_date"])
    return names.sort_values(["secid", "effect_date"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Name check
# ---------------------------------------------------------------------------
def clean_name(name):
    """Upper-case, drop punctuation and the common corporate words in
    NAME_STOP_WORDS, and return what is left (single-spaced)."""
    words = re.sub(r"[^A-Z0-9 ]", " ", str(name).upper()).split()
    return " ".join(word for word in words if word not in NAME_STOP_WORDS)


def name_similarity(sec_name, wrds_name):
    """Return difflib's similarity ratio (0 to 1) of the cleaned names."""
    return difflib.SequenceMatcher(
        None, clean_name(sec_name), clean_name(wrds_name)
    ).ratio()


def names_match(sec_name, wrds_name):
    """Return True if the cleaned names are similar enough (ratio at
    least NAME_THRESHOLD) or one contains the other. Containment also
    covers OptionMetrics names cut off at 28 characters."""
    sec, wrds = clean_name(sec_name), clean_name(wrds_name)
    if not sec or not wrds:
        return False
    if sec in wrds or wrds in sec:
        return True
    return name_similarity(sec_name, wrds_name) >= NAME_THRESHOLD


def name_on(names_df, secid, date):
    """Return the issuer name in effect for secid on date (the latest
    name-history row with an effective date on or before it), or None
    if the name history does not reach back that far."""
    rows = names_df[
        (names_df["secid"] == secid) & (names_df["effect_date"] <= date)
    ]
    return None if rows.empty else rows["issuer"].iloc[-1]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def approved_pairs(path=REVIEW_FILE):
    """Return the set of (cik, secid) pairs marked "yes" in the review
    file, or an empty set if there is no review file yet."""
    if not path.exists():
        return set()
    review = pd.read_csv(path)
    approved = review["approved"].astype(str).str.strip().str.lower() == "yes"
    return set(zip(review.loc[approved, "cik"], review.loc[approved, "secid"]))


def match_observations(
    obs_df, sec_names, secids_by_ticker, names_df, approved
):
    """Match each observation to one OptionMetrics secid, or reject it.

    For each observation: the candidate secids share its ticker; each
    candidate's name on the start date is compared with the SEC name.
    A candidate passes if the names match, or if the pair was approved
    by hand. Exactly one passing candidate is a match; none or two is a
    rejection. Returns (matches, review pairs below the threshold).
    """
    rows, review = [], {}
    for obs in obs_df.itertuples(index=False):
        sec_name = sec_names.get(obs.cik)
        candidates = secids_by_ticker.get(obs.ticker, [])
        passing, reason = [], REJECT_NO_WRDS_TICKER
        for secid in candidates:
            wrds_name = name_on(names_df, secid, obs.start)
            if wrds_name is None:
                reason = REJECT_NO_NAME
                continue
            if names_match(sec_name, wrds_name):
                passing.append(secid)
                continue
            key = (obs.cik, secid)
            review.setdefault(
                key,
                {
                    "cik": obs.cik,
                    "ticker": obs.ticker,
                    "secid": secid,
                    "sec_name": sec_name,
                    "wrds_name": wrds_name,
                    "similarity": round(
                        name_similarity(sec_name, wrds_name), 3
                    ),
                },
            )
            if key in approved:
                passing.append(secid)
            else:
                reason = REJECT_NAME
        if len(passing) == 1:
            secid, reason = passing[0], None
        else:
            secid = None
            if len(passing) > 1:
                reason = REJECT_AMBIGUOUS
        rows.append(
            {
                "cik": obs.cik,
                "fiscal_year": obs.fiscal_year,
                "secid": secid,
                "reject_reason": reason,
                "candidates": len(candidates),
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(list(review.values()))


def sec_former_names(ciks, zip_path=None):
    """Return {cik: [former names]} from the SEC submissions file
    (formerNames). Used only to help the hand review: a company renamed
    since the start date shows its old name here."""
    zip_path = zip_path or config.SUBMISSIONS_ZIP
    former = {}
    with zipfile.ZipFile(zip_path) as archive:
        files = set(archive.namelist())
        for cik in ciks:
            name = f"CIK{int(cik):010d}.json"
            if name in files:
                record = json.loads(archive.read(name))
                former[int(cik)] = [
                    entry["name"] for entry in record.get("formerNames", [])
                ]
    return former


def add_review_helpers(review_df, former_names, names_df):
    """Add two columns that help a person judge each review pair; they
    approve nothing by themselves (only a typed "yes" does).

    - former_sec_name_matches: one of the company's former SEC names
      matches the WRDS name (the company was renamed, same security);
    - wrds_history_has_sec_name: some name in the secid's own history,
      at any date, matches today's SEC name (the security was renamed,
      rather than its ticker passed to another company).
    sec_former_names lists the former names for reference.
    """
    review = review_df.copy()
    if review.empty:
        return review.assign(
            sec_former_names="",
            former_sec_name_matches=False,
            wrds_history_has_sec_name=False,
        )
    history = names_df.groupby("secid")["issuer"].apply(list).to_dict()
    review["sec_former_names"] = [
        "; ".join(former_names.get(int(cik), [])) for cik in review["cik"]
    ]
    review["former_sec_name_matches"] = [
        any(names_match(old, wrds) for old in former_names.get(int(cik), []))
        for cik, wrds in zip(review["cik"], review["wrds_name"])
    ]
    review["wrds_history_has_sec_name"] = [
        any(names_match(sec, name) for name in history.get(secid, []))
        for sec, secid in zip(review["sec_name"], review["secid"])
    ]
    return review


def write_review(review_df, path=REVIEW_FILE):
    """Write the below-threshold pairs for hand review, keeping any
    "approved" marks already typed into an earlier copy of the file."""
    review = review_df.copy()
    review["approved"] = ""
    if path.exists() and not review.empty:
        earlier = pd.read_csv(path, dtype={"approved": "string"})
        marks = {
            (row.cik, row.secid): row.approved
            for row in earlier.itertuples()
            if isinstance(row.approved, str) and row.approved.strip()
        }
        review["approved"] = [
            marks.get((cik, secid), "")
            for cik, secid in zip(review["cik"], review["secid"])
        ]
    review.sort_values(["similarity", "cik"]).to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Fallback to an earlier trading day
# ---------------------------------------------------------------------------
def option_row(secid_rows, calendar, start):
    """Return the usable surface row for one secid and delta on start,
    or else on the closest EARLIER market trading day within
    FALLBACK_TRADING_DAYS; never a later day. None if there is none.

    secid_rows is indexed by date. Looking only backward means every
    option price used was already known on the start day, so no later
    price can leak in.
    """
    position = calendar.searchsorted(start, side="right") - 1
    for back in range(FALLBACK_TRADING_DAYS + 1):
        if position - back < 0:
            break
        day = calendar[position - back]
        if day in secid_rows.index:
            return secid_rows.loc[day]
    return None


# ---------------------------------------------------------------------------
# Put arithmetic for analyses 3 and 4 (used once prices are available)
# ---------------------------------------------------------------------------
def put_return_at_expiry(strike, price_at_expiry, premium):
    """Return (payoff, return per dollar of premium) for a put held to
    expiry: payoff = max(strike - price, 0); return = (payoff -
    premium) / premium. Exact, no model."""
    payoff = max(strike - price_at_expiry, 0.0)
    return payoff, (payoff - premium) / premium


def first_exit_day(price_ratios, threshold=0.7):
    """Return the position of the first close at or below threshold x
    the reference (a 30% fall for 0.7), or None if there is none.
    price_ratios runs from the day after the option date to expiry."""
    hits = np.flatnonzero(np.asarray(price_ratios, dtype=float) <= threshold)
    return int(hits[0]) if hits.size else None


def black_scholes_put(price, strike, years, sigma, rate=0.0, dividend=0.0):
    """Return the Black-Scholes value of a European put. Used only as an
    estimate for an early exit (rate and dividend default to zero, a
    stated simplification); intrinsic value is the lower bound."""
    if years <= 0 or sigma <= 0:
        return max(strike - price, 0.0)
    root = sigma * math.sqrt(years)
    d1 = (
        math.log(price / strike) + (rate - dividend + sigma**2 / 2) * years
    ) / root
    d2 = d1 - root
    return strike * math.exp(-rate * years) * norm.cdf(-d2) - price * math.exp(
        -dividend * years
    ) * norm.cdf(-d1)


# ---------------------------------------------------------------------------
# Step 3a run: matching and the review file only
# ---------------------------------------------------------------------------
def load_observations():
    """Return part 1's observations (one row each, from its details
    file), not recomputed."""
    details = pd.read_csv(
        OBSERVATIONS_FILE, parse_dates=["filed_date", "start", "end"]
    )
    return details[details["drop_size"] == 0.3].reset_index(drop=True)


def main():
    """Match observations and write the review file; print counts and at
    most MAX_PRINTED_ROWS review rows. No result is computed."""
    obs = load_observations()
    companies = pd.read_parquet(config.COMPANIES_PATH, columns=["cik", "name"])
    sec_names = dict(zip(companies["cik"], companies["name"]))
    surface = load_surface()
    secids_by_ticker = (
        surface.groupby("ticker")["secid"].unique().map(sorted).to_dict()
    )
    names = load_names()
    matches, review = match_observations(
        obs, sec_names, secids_by_ticker, names, approved_pairs()
    )
    review = add_review_helpers(
        review, sec_former_names(review["cik"].unique()), names
    )
    write_review(review)
    print(f"observations: {len(obs):,}")
    print(f"matched: {int(matches['secid'].notna().sum()):,}")
    print("rejected by reason:")
    print(matches["reject_reason"].value_counts().to_string())
    print(
        f"\nname pairs below the threshold, for hand review: {len(review)} "
        f"companies-secid pairs, in {REVIEW_FILE}"
    )
    if not review.empty:
        print(f"first {MAX_PRINTED_ROWS} (lowest similarity first):")
        shown = review.sort_values("similarity").head(MAX_PRINTED_ROWS)
        print(shown.to_string(index=False))


if __name__ == "__main__":
    main()
