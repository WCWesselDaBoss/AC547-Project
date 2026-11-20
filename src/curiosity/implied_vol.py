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

import argparse
import difflib
import json
import math
import re
import zipfile

import matplotlib

matplotlib.use("Agg")  # draw to a file; no window
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm  # noqa: E402

import config  # noqa: E402
from src.curiosity import vol_matched  # noqa: E402
from src.scores import drop_sizes  # noqa: E402
from src.scores import backtest  # noqa: E402

WRDS_DIR = config.RAW_DIR / "wrds"
SURFACE_FILE = WRDS_DIR / "vsurf_puts_730d.csv.gz"
PRICES_FILE = WRDS_DIR / "secprd_prices.csv.gz"
# The last date in the security-price file (checked 2026-11-19). A put
# expiring after it is not yet expired in the data.
PRICE_FILE_END = pd.Timestamp("2025-08-29")
OPTION_DAYS = 730
EXIT_THRESHOLD = 0.7  # analysis 4: sell at a 30% fall
# Extension (exploratory, added before any result): sell at a 50% or a
# 70% fall instead. Each is its own rule. The 30% rule keeps its
# original field names, so the committed 30% results reproduce.
EXTRA_EXITS = {50: 0.5, 70: 0.3}
MIN_ROWS_TO_READ = 50  # fewer puts or observations: too small to read
COST_MARKUPS = [0.0, 0.05, 0.10]  # analysis 5: price paid above mid
NAMES_FILE = WRDS_DIR / "secnmd_names.csv.gz"
# Below-threshold pairs for hand review. It holds licensed names, so it
# stays in the gitignored WRDS folder.
REVIEW_FILE = WRDS_DIR / "name_review.csv"
OBSERVATIONS_FILE = config.LOG_DIR / "curiosity_vol_matched.csv"
# Derived values per observation (no raw WRDS rows); data/logs/ is
# gitignored.
DETAILS_FILE = config.LOG_DIR / "curiosity_implied_vol.csv"
PUT_CHART_FILE = config.PROJECT_ROOT / "docs" / "curiosity" / "put_returns.png"
CHART_FILE = (
    config.PROJECT_ROOT / "docs" / "curiosity" / "implied_vol_benchmark.png"
)

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
    """Write the below-threshold pairs for hand review, keeping the
    "approved" mark and any "review_note" already typed into an earlier
    copy of the file (matched on cik and secid)."""
    review = review_df.copy()
    review["approved"] = ""
    review["review_note"] = ""
    if path.exists() and not review.empty:
        earlier = pd.read_csv(path, dtype="string")
        for column in ("approved", "review_note"):
            if column not in earlier.columns:
                continue
            kept = {
                (int(cik), int(secid)): value
                for cik, secid, value in zip(
                    earlier["cik"], earlier["secid"], earlier[column]
                )
                if isinstance(value, str) and value.strip()
            }
            review[column] = [
                kept.get((int(cik), int(secid)), "")
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


def option_data(matched_df, surface_df, calendar):
    """Return one row per matched observation with, for each delta, the
    option date, implied volatility, strike and premium from the usable
    surface row on the start date or the fallback day (blank if none),
    plus whether the security is an ADR (issue type F).

    matched_df has cik, fiscal_year, secid and start. The surface values
    stay in this derived table only; they are written to data/logs/
    (gitignored), never to docs.
    """
    by_key = {
        key: rows.set_index("date")
        for key, rows in surface_df.groupby(["secid", "delta"])
    }
    adr = set(
        surface_df.loc[surface_df["issue_type"] == ADR_ISSUE_TYPE, "secid"]
    )
    records = []
    for obs in matched_df.itertuples(index=False):
        record = {
            "cik": obs.cik,
            "fiscal_year": obs.fiscal_year,
            "is_adr": obs.secid in adr,
        }
        for delta in DELTAS:
            suffix = str(abs(delta))
            rows = by_key.get((obs.secid, delta))
            row = (
                None if rows is None else option_row(rows, calendar, obs.start)
            )
            record[f"option_date_{suffix}"] = None if row is None else row.name
            for column, name in [
                ("impl_volatility", "iv"),
                ("impl_strike", "strike"),
                ("impl_premium", "premium"),
            ]:
                record[f"{name}_{suffix}"] = (
                    np.nan if row is None else row[column]
                )
        records.append(record)
    return pd.DataFrame(records)


def tradeability(obs_df, matches_df, options_df):
    """Return, for Clean, Flagged, 2 flags and 3 flags: observations,
    matched, with delta -50 data and with delta -25 data."""
    frame = obs_df[["cik", "fiscal_year", "group", "tier"]].merge(
        matches_df[["cik", "fiscal_year", "secid"]], on=["cik", "fiscal_year"]
    )
    frame = frame.merge(options_df, on=["cik", "fiscal_year"], how="left")
    groups = [
        ("Clean", frame["group"] == "clean"),
        ("Flagged", frame["group"] == "flagged"),
        ("2 flags", frame["tier"] == "2 flags"),
        ("3 flags", frame["tier"] == "3 flags"),
    ]
    rows = []
    for label, mask in groups:
        part = frame[mask]
        rows.append(
            {
                "group": label,
                "observations": len(part),
                "matched": int(part["secid"].notna().sum()),
                "with_delta_50": int(part["iv_50"].notna().sum()),
                "with_delta_25": int(part["iv_25"].notna().sum()),
            }
        )
    return pd.DataFrame(rows)


def benchmark_chart(implied_tables, trailing_tables, path=CHART_FILE):
    """Save actual vs predicted 24-month drop shares by group, with the
    prediction from trailing and from implied volatility, one panel per
    drop size (PNG)."""
    groups = ["Clean", "Flagged", "1 flag", "2 flags", "3 flags"]
    figure, axes = plt.subplots(
        1, len(vol_matched.DROPS), figsize=(12, 5), dpi=150
    )
    for axis, drop in zip(axes, vol_matched.DROPS):
        implied = implied_tables[drop].set_index("group").reindex(groups)
        trailing = trailing_tables[drop].set_index("group").reindex(groups)
        x = np.arange(len(groups))
        axis.bar(
            x - 0.27,
            implied["pct_actual"],
            0.27,
            color="#52514e",
            label="Actual",
        )
        axis.bar(
            x,
            trailing["pct_predicted"],
            0.27,
            color="#2a78d6",
            label="Predicted from trailing volatility",
        )
        axis.bar(
            x + 0.27,
            implied["pct_predicted"],
            0.27,
            color="#eb6834",
            label="Predicted from implied volatility",
        )
        axis.set_xticks(x, groups, fontsize=9)
        axis.set_title(
            f"Fell {int(100 * drop)}% within 24 months", fontsize=11
        )
        axis.set_ylabel("Share (%)")
        axis.set_ylim(0, 100)
        axis.grid(axis="y", color="#e1e0d9")
        axis.legend(loc="upper left", fontsize=8)
    figure.suptitle(
        "Actual vs predicted drops, observations with option data "
        "(zero-drift barrier formula; curiosity analysis)",
        fontsize=12,
    )
    figure.text(
        0.01,
        0.01,
        "Not part of the test register. OptionMetrics data via WRDS. "
        "Current tickers only. Correlation, not cause. Not investment advice.",
        fontsize=8,
        color="#52514e",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.95))
    figure.savefig(path)
    plt.close(figure)
    return path


def run_analyses_1_2(obs_df, matches_df, options_df):
    """Return analyses 1 and 2 on the observations with delta -50 data.

    For each drop size: the volatility-only benchmark with implied
    volatility (analysis 1), the same with trailing volatility on the
    same observations, and the Cox model with log implied volatility
    and, for comparison, with log trailing volatility (analysis 2), both
    clustered by company.
    """
    details = pd.read_csv(OBSERVATIONS_FILE)
    details["event"] = (
        details["event"].astype(str).str.lower().eq("true").astype("boolean")
    )
    keep = options_df.loc[
        options_df["iv_50"].notna(), ["cik", "fiscal_year", "iv_50"]
    ]
    results = {}
    for drop in vol_matched.DROPS:
        frame = details[details["drop_size"] == drop].merge(
            keep, on=["cik", "fiscal_year"]
        )
        implied = frame.assign(volatility=frame["iv_50"])
        results[drop] = {
            "observations": len(frame),
            "benchmark_implied": vol_matched.benchmark_table(implied, drop),
            "benchmark_trailing": vol_matched.benchmark_table(frame, drop),
            "cox_implied": vol_matched.cox_flagged(implied),
            "cox_trailing": vol_matched.cox_flagged(frame),
        }
    return results


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
# ---------------------------------------------------------------------------
# Analyses 3 to 5: put payoffs from security prices
# ---------------------------------------------------------------------------
STATUS_DONE = "valued"
STATUS_NOT_EXPIRED = "not_yet_expired_in_data"
STATUS_NO_START_PRICE = "no_price_on_option_date"
STATUS_STOPPED = "valued_at_last_price_security_stopped"


def load_security_prices(path=PRICES_FILE):
    """Read the security-price file by its exact name and return
    {secid: rows indexed by date with close and cfadj}.

    A negative close is the average of the closing bid and ask on a day
    without a trade (IvyDB manual), so its absolute value is used; a
    zero close counts as no price that day.
    """
    prices = pd.read_csv(path, usecols=["secid", "date", "close", "cfadj"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices["close"] = prices["close"].abs()
    prices = prices[prices["close"] > 0]
    return {
        secid: rows.set_index("date")[["close", "cfadj"]].sort_index()
        for secid, rows in prices.groupby("secid")
    }


def price_on(security_rows, calendar, day):
    """Return the (date, close, cfadj) row for day, or else the latest
    earlier row within FALLBACK_TRADING_DAYS market trading days; None
    if there is none."""
    position = calendar.searchsorted(day, side="right") - 1
    earliest = calendar[max(position - FALLBACK_TRADING_DAYS, 0)]
    rows = security_rows.loc[earliest:day]
    return None if rows.empty else rows.iloc[-1]


def option_expiry(calendar, option_date):
    """Return the last market trading day on or before option date +
    730 days."""
    limit = option_date + pd.Timedelta(days=OPTION_DAYS)
    return calendar[calendar <= limit][-1]


def put_outcome(security_rows, calendar, option_date, strike, premium, sigma):
    """Return the outcome of one put bought on option_date (analyses 3
    and 4), with every price converted to option-date share units:
    price x cfadj that day / cfadj on the option date.

    Keys: status; expiry; value_expiry (analysis 3, held to expiry);
    exit_date, value_exit_intrinsic and value_exit_bs (analysis 4: sold
    at the first close 30% or more below the option-date close, else as
    analysis 3); and for the extension, exit_date_50, value_exit50_* and
    exit_date_70, value_exit70_* (the same at a 50% and a 70% fall). A put expiring after PRICE_FILE_END is "not yet expired
    in the data" and gets no value (never the last available price).
    """
    expiry = option_expiry(calendar, option_date)
    result = {"status": STATUS_DONE, "expiry": expiry, "exit_date": pd.NaT}
    if expiry > PRICE_FILE_END:
        result["status"] = STATUS_NOT_EXPIRED
        return result
    start = price_on(security_rows, calendar, option_date)
    if start is None:
        result["status"] = STATUS_NO_START_PRICE
        return result
    base_price, base_factor = start["close"], start["cfadj"]
    path = security_rows.loc[option_date + pd.Timedelta(days=1) : expiry]
    converted = path["close"] * path["cfadj"] / base_factor

    end = price_on(security_rows, calendar, expiry)
    if end is None:
        # The security's own prices stopped before expiry (the file goes
        # on): intrinsic value on its last price day.
        result["status"] = STATUS_STOPPED
        last_price = converted.iloc[-1] if not converted.empty else base_price
        value_expiry = max(strike - last_price, 0.0)
    else:
        price_at_expiry = end["close"] * end["cfadj"] / base_factor
        value_expiry = put_return_at_expiry(strike, price_at_expiry, premium)[
            0
        ]
    result["value_expiry"] = value_expiry

    ratios = (converted / base_price).to_numpy()
    exit_date, intrinsic, estimate = exit_values(
        converted, ratios, EXIT_THRESHOLD, expiry, strike, sigma, value_expiry
    )
    result["exit_date"] = exit_date
    result["value_exit_intrinsic"] = intrinsic
    result["value_exit_bs"] = estimate
    for fall, threshold in EXTRA_EXITS.items():
        exit_date, intrinsic, estimate = exit_values(
            converted, ratios, threshold, expiry, strike, sigma, value_expiry
        )
        result[f"exit_date_{fall}"] = exit_date
        result[f"value_exit{fall}_intrinsic"] = intrinsic
        result[f"value_exit{fall}_bs"] = estimate
    return result


def exit_values(converted, ratios, threshold, expiry, strike, sigma, held):
    """Return (exit date, intrinsic value, Black-Scholes value) for one
    exit rule: sell at the first close at or below threshold x the
    option-date close; if that never happens, the put is held to expiry
    and both values equal the held-to-expiry value (exit date NaT)."""
    position = first_exit_day(ratios, threshold)
    if position is None:
        return pd.NaT, held, held
    exit_date = converted.index[position]
    exit_price = converted.iloc[position]
    years_left = (expiry - exit_date).days / 365
    return (
        exit_date,
        max(strike - exit_price, 0.0),
        black_scholes_put(exit_price, strike, years_left, sigma),
    )


def put_outcomes(options_df, prices_by_secid, calendar):
    """Return one row per observation and delta with the put outcome.
    options_df comes from option_data, with secid added."""
    rows = []
    for obs in options_df.itertuples(index=False):
        for delta in DELTAS:
            suffix = str(abs(delta))
            premium = getattr(obs, f"premium_{suffix}")
            if pd.isna(premium):
                continue
            outcome = put_outcome(
                prices_by_secid.get(
                    obs.secid, pd.DataFrame(columns=["close", "cfadj"])
                ),
                calendar,
                getattr(obs, f"option_date_{suffix}"),
                getattr(obs, f"strike_{suffix}"),
                premium,
                getattr(obs, f"iv_{suffix}"),
            )
            rows.append(
                {
                    "cik": obs.cik,
                    "fiscal_year": obs.fiscal_year,
                    "delta": delta,
                    "premium": premium,
                    **outcome,
                }
            )
    return pd.DataFrame(rows)


def return_per_premium(value, premium, markup=0.0):
    """Return (value - price paid) / price paid, where the price paid is
    the mid premium raised by markup (analysis 5's stand-in for the
    bid-ask spread)."""
    paid = premium * (1 + markup)
    return (value - paid) / paid


def put_summary(outcomes_df, groups_df):
    """Return mean, median and share positive of the return per dollar
    of premium, by delta, valuation, cost markup and group (Clean,
    Flagged, 0 to 3 flags), over valued puts only."""
    valued = outcomes_df[
        outcomes_df["status"].isin([STATUS_DONE, STATUS_STOPPED])
    ].merge(groups_df, on=["cik", "fiscal_year"])
    # (value column, exit-date column) per valuation; holding to expiry
    # has no exit. "exit" is the 30% rule, under its original names.
    valuations = {
        "hold_to_expiry": ("value_expiry", None),
        "exit_intrinsic": ("value_exit_intrinsic", "exit_date"),
        "exit_black_scholes": ("value_exit_bs", "exit_date"),
    }
    for fall in EXTRA_EXITS:
        valuations[f"exit{fall}_intrinsic"] = (
            f"value_exit{fall}_intrinsic",
            f"exit_date_{fall}",
        )
        valuations[f"exit{fall}_black_scholes"] = (
            f"value_exit{fall}_bs",
            f"exit_date_{fall}",
        )
    rows = []
    for delta in DELTAS:
        part = valued[valued["delta"] == delta]
        for valuation, (column, exit_column) in valuations.items():
            for markup in COST_MARKUPS:
                returns = return_per_premium(
                    part[column], part["premium"], markup
                )
                for label, mask in group_masks(part):
                    picked = returns[mask]
                    hits = (
                        0
                        if exit_column is None
                        else int(part.loc[mask, exit_column].notna().sum())
                    )
                    rows.append(
                        {
                            "delta": delta,
                            "valuation": valuation,
                            "cost_markup": markup,
                            "group": label,
                            "puts": len(picked),
                            "hits": hits,
                            "mean_return": picked.mean(),
                            "median_return": picked.median(),
                            "share_positive": (picked > 0).mean(),
                            "too_small_to_read": len(picked)
                            < MIN_ROWS_TO_READ,
                        }
                    )
    return pd.DataFrame(rows)


def group_masks(frame):
    """Return (label, boolean mask) for Clean, Flagged and 0 to 3 flags."""
    masks = [
        ("Clean", frame["group"] == "clean"),
        ("Flagged", frame["group"] == "flagged"),
    ]
    masks += [
        (tier, frame["tier"] == tier)
        for tier in ["0 flags", "1 flag", "2 flags", "3 flags"]
    ]
    return masks


def status_counts(outcomes_df, groups_df):
    """Return put counts by delta, group and status (valued, not yet
    expired in the data, stopped, no price on the option date)."""
    frame = outcomes_df.merge(groups_df, on=["cik", "fiscal_year"])
    rows = []
    for delta in DELTAS:
        part = frame[frame["delta"] == delta]
        for label, mask in group_masks(part):
            counts = part.loc[mask, "status"].value_counts()
            rows.append({"delta": delta, "group": label, **counts.to_dict()})
    return pd.DataFrame(rows).fillna(0)


def put_chart(summary_df, path=PUT_CHART_FILE):
    """Save the mean return per dollar of premium by group, for holding
    to expiry and for the exit rule (Black-Scholes estimate), at mid
    prices, one panel per delta (PNG)."""
    groups = ["Clean", "Flagged", "1 flag", "2 flags", "3 flags"]
    figure, axes = plt.subplots(1, len(DELTAS), figsize=(12, 5), dpi=150)
    for axis, delta in zip(axes, DELTAS):
        part = summary_df[
            (summary_df["delta"] == delta) & (summary_df["cost_markup"] == 0)
        ]
        x = np.arange(len(groups))
        for offset, (valuation, label, color) in zip(
            (-0.2, 0.2),
            [
                ("hold_to_expiry", "Held to expiry", "#52514e"),
                (
                    "exit_black_scholes",
                    "Sold at a 30% fall (Black-Scholes estimate)",
                    "#eb6834",
                ),
            ],
        ):
            values = (
                part[part["valuation"] == valuation]
                .set_index("group")
                .reindex(groups)
            )
            axis.bar(
                x + offset,
                100 * values["mean_return"],
                0.4,
                color=color,
                label=label,
            )
        axis.axhline(0, color="#0b0b0b", linewidth=0.8)
        axis.set_xticks(x, groups, fontsize=9)
        axis.set_title(f"Delta {delta} two-year puts", fontsize=11)
        axis.set_ylabel("Mean return per dollar of premium (%)")
        axis.grid(axis="y", color="#e1e0d9")
    figure.suptitle(
        "Buying puts on the day the 10-K became public, at mid prices "
        "(curiosity analysis)",
        fontsize=12,
    )
    figure.text(
        0.01,
        0.01,
        "Puts expiring after 2025-08-29 left out. Interpolated standardized "
        "options. Not investment advice.",
        fontsize=8,
        color="#52514e",
    )
    # One shared legend under the panels, so it never covers a bar.
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="lower center",
        ncol=2,
        fontsize=9,
        bbox_to_anchor=(0.5, 0.04),
    )
    figure.tight_layout(rect=(0, 0.1, 1, 0.95))
    figure.savefig(path)
    plt.close(figure)
    return path


def benchmark_70(options_df, prices_df):
    """Return analysis 1 at a 70% drop: actual against implied-volatility
    predicted share by group, on observations with delta -50 data. The
    drop is detected exactly as in tests 11 and 12 (src/scores/
    drop_sizes.py, adjusted closes); rows on fewer than MIN_ROWS_TO_READ
    observations are marked too small to read."""
    details = pd.read_csv(OBSERVATIONS_FILE, parse_dates=["start", "end"])
    frame = details[details["drop_size"] == 0.3].merge(
        options_df.loc[
            options_df["iv_50"].notna(), ["cik", "fiscal_year", "iv_50"]
        ],
        on=["cik", "fiscal_year"],
    )
    calendar = backtest.trading_calendar(prices_df)
    price_wide = backtest.price_table(prices_df, calendar)
    frame = drop_sizes.outcomes_at(
        frame.drop(
            columns=["event", "duration_days", "drop_date", "drop_size"]
        ),
        price_wide,
        0.7,
    )
    frame = frame.assign(volatility=frame["iv_50"])
    table = vol_matched.benchmark_table(frame, 0.7)
    table["too_small_to_read"] = table["observations"] < MIN_ROWS_TO_READ
    return table


def load_observations():
    """Return part 1's observations (one row each, from its details
    file), not recomputed."""
    details = pd.read_csv(
        OBSERVATIONS_FILE, parse_dates=["filed_date", "start", "end"]
    )
    return details[details["drop_size"] == 0.3].reset_index(drop=True)


def main(argv=None):
    """Match observations and write the review file; print counts and at
    most MAX_PRINTED_ROWS review rows. With --results (only after the
    hand review), also compute tradeability and analyses 1 and 2."""
    parser = argparse.ArgumentParser(description="Curiosity part 2")
    parser.add_argument("--results", action="store_true")
    parser.add_argument(
        "--puts",
        action="store_true",
        help="with --results, also run analyses 3 to 5 (security prices)",
    )
    args = parser.parse_args(argv)
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
    if not args.results:
        return

    matched = matches[matches["secid"].notna()].merge(
        obs[["cik", "fiscal_year", "start"]], on=["cik", "fiscal_year"]
    )
    matched["secid"] = matched["secid"].astype(int)
    calendar = backtest.trading_calendar(pd.read_parquet(config.PRICES_PATH))
    options = option_data(matched, surface, calendar)
    options.merge(
        matches[["cik", "fiscal_year", "secid"]], on=["cik", "fiscal_year"]
    ).to_csv(DETAILS_FILE, index=False)
    pd.set_option("display.width", 220)
    print("\nTradeability:")
    print(tradeability(obs, matches, options).to_string(index=False))
    print(
        "matched observations on an ADR (issue type F):",
        int(options["is_adr"].sum()),
    )
    results = run_analyses_1_2(obs, matches, options)
    for drop, result in results.items():
        print(
            f"\n===== {int(100 * drop)}% drop, {result['observations']:,} observations"
        )
        print("Analysis 1, implied volatility:")
        print(result["benchmark_implied"].round(3).to_string(index=False))
        print("Same observations, trailing volatility:")
        print(result["benchmark_trailing"].round(3).to_string(index=False))
        for name in ("cox_implied", "cox_trailing"):
            cox = result[name]
            print(
                f"{name}: HR {cox['hazard_ratio_flagged']:.3f} "
                f"({cox['ci_low']:.3f} to {cox['ci_high']:.3f}), "
                f"p {cox['p_value']:.3e}, volatility HR "
                f"{cox['hazard_ratio_log_volatility']:.3f}, "
                f"{cox['drops']} drops, {cox['companies']} companies"
            )
    benchmark_chart(
        {d: r["benchmark_implied"] for d, r in results.items()},
        {d: r["benchmark_trailing"] for d, r in results.items()},
    )
    print(f"\nSaved {DETAILS_FILE} and {CHART_FILE}")
    if not args.puts:
        return

    # Analyses 3 to 5.
    options = options.merge(
        matches[["cik", "fiscal_year", "secid"]], on=["cik", "fiscal_year"]
    )
    options["secid"] = options["secid"].astype(int)
    outcomes = put_outcomes(options, load_security_prices(), calendar)
    groups = obs[["cik", "fiscal_year", "group", "tier"]]
    details = options.merge(
        outcomes.pivot_table(
            index=["cik", "fiscal_year"],
            columns="delta",
            values=["value_expiry", "value_exit_intrinsic", "value_exit_bs"],
            aggfunc="first",
        )
        .pipe(
            lambda t: t.set_axis(
                [f"{a}_{abs(b)}" for a, b in t.columns], axis=1
            )
        )
        .reset_index(),
        on=["cik", "fiscal_year"],
        how="left",
    )
    details.to_csv(DETAILS_FILE, index=False)
    print("\nPut status counts:")
    print(status_counts(outcomes, groups).to_string(index=False))
    summary = put_summary(outcomes, groups)
    for delta in DELTAS:
        for valuation in summary["valuation"].unique():
            part = summary[
                (summary["delta"] == delta)
                & (summary["valuation"] == valuation)
            ]
            print(f"\n===== delta {delta}, {valuation}")
            print(
                part.pivot_table(
                    index="group",
                    columns="cost_markup",
                    values="mean_return",
                    sort=False,
                )
                .round(3)
                .to_string()
            )
            mid = part[part["cost_markup"] == 0]
            print(
                mid[
                    [
                        "group",
                        "puts",
                        "hits",
                        "median_return",
                        "share_positive",
                        "too_small_to_read",
                    ]
                ]
                .round(3)
                .to_string(index=False)
            )
    summary.to_csv(config.LOG_DIR / "curiosity_put_summary.csv", index=False)
    print("\n===== Analysis 1 extended to 70% drops (implied volatility):")
    print(
        benchmark_70(options, pd.read_parquet(config.PRICES_PATH))
        .round(3)
        .to_string(index=False)
    )
    put_chart(summary)
    print(f"\nSaved {DETAILS_FILE} and {PUT_CHART_FILE}")


if __name__ == "__main__":
    main()
