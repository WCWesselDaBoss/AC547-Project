"""Curiosity: do flagged companies' stocks fall more after a warning filing?

Not part of the class project's test register. Definitions were fixed
in docs/curiosity/events.md before any result was computed
(exploratory); this module follows them.

Two kinds of event, analyzed separately:
- NT 10-K: a notice that the annual report will be late;
- 8-K Item 4.01: a change in the company's auditor (resignations,
  dismissals and routine changes alike; the item number cannot tell
  them apart).
For each event, the company's flag status comes from its latest score
filed before the event. The outcome is the stock's return minus SPY's
over trading days +1 to +63 after the filing, entering at the close of
the first trading day after the filing date.

Public data only (the SEC submissions bulk file and the price table).
This is an analysis for a class project, not investment advice.
"""

import argparse
import json
import zipfile

import matplotlib

matplotlib.use("Agg")  # draw to a file; no window
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402

import config  # noqa: E402
from src.scores import backtest  # noqa: E402

DETAILS_FILE = config.LOG_DIR / "curiosity_events.csv"
CHART_FILE = config.PROJECT_ROOT / "docs" / "curiosity" / "events_car.png"

NT_10K = "NT 10-K"
AUDITOR_8K = "8-K Item 4.01"
EVENT_TYPES = [NT_10K, AUDITOR_8K]
AUDITOR_ITEM = "4.01"
FIRST_YEAR, LAST_YEAR = 2014, 2025
REPEAT_DAYS = 63  # a same-type event within this many trading days is dropped
MAX_SCORE_AGE_MONTHS = 15
HISTORY_DAYS = 20  # a price on each of days -20 to -1
MIN_PRICE = 5.0
REGISTERED_WINDOW = 63
DESCRIPTIVE_WINDOWS = [21, 126, 252]
CAR_START, CAR_END = -5, 252  # chart days; measured from the close on day -6
PASS_T = 3.0
FLAGGED_COLOR, CLEAN_COLOR = "#d03b3b", "#0ca30c"  # app verdict colors


# ---------------------------------------------------------------------------
# Events from the SEC submissions file
# ---------------------------------------------------------------------------
def event_type_of(form, items):
    """Return the event type of one filing, or None.

    NT 10-K counts only as the form "NT 10-K" (not amendments). An
    auditor change is an original 8-K (form "8-K", not "8-K/A") whose
    listed items include 4.01.
    """
    if form == "NT 10-K":
        return NT_10K
    if form == "8-K":
        listed = [item.strip() for item in str(items or "").split(",")]
        if AUDITOR_ITEM in listed:
            return AUDITOR_8K
    return None


def load_filings(ciks, zip_path=None):
    """Return every NT 10-K and auditor-change 8-K filed 2014-2025 by
    the given companies: cik, event_type, accession, filed. Reads each
    company's main file and its overflow files (older filings)."""
    zip_path = zip_path or config.SUBMISSIONS_ZIP
    rows = []
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for cik in ciks:
            main = f"CIK{int(cik):010d}.json"
            if main not in names:
                continue
            record = json.loads(archive.read(main))
            tables = [record["filings"]["recent"]] + [
                json.loads(archive.read(extra["name"]))
                for extra in record["filings"].get("files", [])
                if extra["name"] in names
            ]
            for table in tables:
                items = table.get("items", [""] * len(table["form"]))
                for form, filed, item_list, accession in zip(
                    table["form"],
                    table["filingDate"],
                    items,
                    table["accessionNumber"],
                ):
                    kind = event_type_of(form, item_list)
                    if kind is not None:
                        rows.append((int(cik), kind, accession, filed))
    events = pd.DataFrame(
        rows, columns=["cik", "event_type", "accession", "filed"]
    ).drop_duplicates("accession")
    events["filed"] = pd.to_datetime(events["filed"])
    years = events["filed"].dt.year
    return events[years.between(FIRST_YEAR, LAST_YEAR)].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Event days, repeats and flag status
# ---------------------------------------------------------------------------
def event_days(calendar, filed):
    """Return (day 0 position, day +1 position) in the market calendar.

    Day 0 is the filing date if it is a trading day, otherwise the last
    trading day before it. Day +1, the entry day, is the first trading
    day AFTER the filing date: a filing may come after the market
    closes, so the filing day itself is not tradeable (a Friday filing
    enters on Monday).
    """
    filed = pd.Timestamp(filed)
    day0 = calendar.searchsorted(filed, side="right") - 1
    entry = calendar.searchsorted(filed, side="right")
    return int(day0), int(entry)


def drop_repeats(events_df):
    """Keep, for each company and event type, the first event of each
    run: an event within REPEAT_DAYS trading days after a KEPT event of
    the same type is dropped (measured on day 0 positions)."""
    keep = []
    ordered = events_df.sort_values(["cik", "event_type", "day0"])
    for _, group in ordered.groupby(["cik", "event_type"], sort=False):
        last_kept = None
        for index, day0 in zip(group.index, group["day0"]):
            if last_kept is None or day0 - last_kept > REPEAT_DAYS:
                keep.append(index)
                last_kept = day0
    return events_df.loc[sorted(keep)]


def flag_status(events_df, scores_df, financials_df):
    """Add the company's flag status at each event.

    The latest score whose 10-K was filed strictly before the event's
    filing date (ties: the later fiscal year), no more than
    MAX_SCORE_AGE_MONTHS before it, with an M-Score, a Z'' and an
    F-Score present. Columns added: fiscal_year, score_filed,
    flags_raised, group (clean / flagged) and score_status ("ok", or
    why the event has no usable score).
    """
    dated = scores_df[
        ["cik", "fiscal_year", "flags_raised", "m_score", "z_score", "f_score"]
    ].merge(
        financials_df[["cik", "fiscal_year", "filed_date"]],
        on=["cik", "fiscal_year"],
    )
    dated = dated.dropna(subset=["filed_date"])
    # merge_asof needs both date keys at the same precision.
    dated["filed_date"] = dated["filed_date"].astype("datetime64[ns]")
    dated = dated.sort_values(["filed_date", "fiscal_year"])
    events = events_df.sort_values("filed").reset_index()
    events["filed"] = events["filed"].astype("datetime64[ns]")
    merged = pd.merge_asof(
        events,
        dated.rename(columns={"filed_date": "score_filed"}),
        left_on="filed",
        right_on="score_filed",
        by="cik",
        allow_exact_matches=False,  # filed ON the event day: not before it
        direction="backward",
    ).set_index("index")
    oldest = merged["filed"] - pd.DateOffset(months=MAX_SCORE_AGE_MONTHS)
    complete = (
        merged["m_score"].notna()
        & merged["z_score"].notna()
        & merged["f_score"].notna()
    )
    merged["score_status"] = np.select(
        [
            merged["score_filed"].isna(),
            merged["score_filed"] < oldest,
            ~complete,
        ],
        ["no_score_before", "score_too_old", "missing_a_score"],
        default="ok",
    )
    merged["group"] = np.where(
        merged["flags_raised"].fillna(0) >= 1, "flagged", "clean"
    )
    merged.loc[merged["score_status"] != "ok", "group"] = None
    columns = [
        "fiscal_year",
        "score_filed",
        "flags_raised",
        "group",
        "score_status",
    ]
    return events_df.join(merged[columns])


# ---------------------------------------------------------------------------
# Prices: eligibility and market-adjusted returns
# ---------------------------------------------------------------------------
def eligibility(prices, day0, entry):
    """Return (has_history, entry_price) for one stock's price array
    (on the market calendar, NaN without a price): a price on each of
    days -20 to -1, and the close on day +1 (NaN if none)."""
    first = day0 - HISTORY_DAYS
    has_history = first >= 0 and not np.isnan(prices[first:day0]).any()
    entry_price = prices[entry] if entry < len(prices) else np.nan
    return bool(has_history), float(entry_price)


def market_adjusted(stock, market, start, end):
    """Return the stock's return minus the market's from the close on
    position start to the close on position end; NaN if the stock has no
    price on either day or end is past the data."""
    if end >= len(stock) or start < 0:
        return np.nan
    if np.isnan(stock[start]) or np.isnan(stock[end]):
        return np.nan
    return (stock[end] / stock[start] - 1) - (market[end] / market[start] - 1)


def event_outcomes(events_df, price_wide):
    """Add eligibility and every return window to each event. price_wide
    is the price table on the market calendar (SPY included)."""
    market = price_wide[config.MARKET_BENCHMARK_TICKER].to_numpy(float)
    calendar = price_wide.index
    rows = []
    for event in events_df.itertuples():
        record = {"index": event.Index}
        ticker = event.ticker
        if pd.isna(ticker) or ticker not in price_wide.columns:
            record["price_status"] = "no_prices"
            rows.append(record)
            continue
        stock = price_wide[ticker].to_numpy(float)
        has_history, entry_price = eligibility(stock, event.day0, event.entry)
        record["entry_price"] = entry_price
        record["price_status"] = (
            "ok"
            if has_history and not np.isnan(entry_price)
            else ("short_history" if not has_history else "no_entry_price")
        )
        for window in [REGISTERED_WINDOW] + DESCRIPTIVE_WINDOWS:
            # Day +1 is the entry; day +w is w - 1 trading days later.
            record[f"car_1_{window}"] = market_adjusted(
                stock, market, event.entry, event.entry + window - 1
            )
        filed_on_trading_day = calendar[event.day0] == pd.Timestamp(
            event.filed
        )
        record["filing_day_move"] = (
            market_adjusted(stock, market, event.day0 - 1, event.day0)
            if filed_on_trading_day
            else np.nan
        )
        rows.append(record)
    out = pd.DataFrame(rows).set_index("index")
    return events_df.join(out)


# ---------------------------------------------------------------------------
# Tests of the registered questions, and the chart
# ---------------------------------------------------------------------------
def clustered_tests(frame, outcome):
    """Return questions (a) and (b) for one event type and outcome.

    (a) the outcome on a constant, over Flagged events; (b) the outcome
    on a constant and a Flagged indicator, over all events. Ordinary
    least squares with standard errors clustered by company. A question
    passes only if |t| >= PASS_T (four questions are tested)."""
    data = frame.dropna(subset=[outcome])
    flagged = data[data["group"] == "flagged"]
    result = {
        "events": len(data),
        "flagged": len(flagged),
        "clean": len(data) - len(flagged),
    }
    if len(flagged) >= 2 and flagged["cik"].nunique() >= 2:
        fit = sm.OLS(
            flagged[outcome].to_numpy(float), np.ones(len(flagged))
        ).fit(
            cov_type="cluster", cov_kwds={"groups": flagged["cik"].to_numpy()}
        )
        result.update(
            flagged_mean=float(fit.params[0]),
            t_a=float(fit.tvalues[0]),
            passes_a=bool(abs(fit.tvalues[0]) >= PASS_T),
        )
    if result["clean"] >= 2 and len(flagged) >= 2:
        design = sm.add_constant(
            (data["group"] == "flagged").astype(float).to_numpy()
        )
        fit = sm.OLS(data[outcome].to_numpy(float), design).fit(
            cov_type="cluster", cov_kwds={"groups": data["cik"].to_numpy()}
        )
        result.update(
            clean_mean=float(fit.params[0]),
            difference=float(fit.params[1]),
            t_b=float(fit.tvalues[1]),
            passes_b=bool(abs(fit.tvalues[1]) >= PASS_T),
            companies=int(data["cik"].nunique()),
        )
    return result


def car_curve(frame, price_wide):
    """Return the average cumulative market-adjusted return for days
    CAR_START to CAR_END, measured from the close on day CAR_START - 1,
    averaging on each day the events with a price that day; plus the
    number of events behind each day."""
    market = price_wide[config.MARKET_BENCHMARK_TICKER].to_numpy(float)
    days = np.arange(CAR_START, CAR_END + 1)
    paths = []
    for event in frame.itertuples():
        stock = price_wide[event.ticker].to_numpy(float)
        base = event.day0 + CAR_START - 1
        path = np.full(len(days), np.nan)
        if base >= 0 and not np.isnan(stock[base]):
            for i, day in enumerate(days):
                position = event.day0 + day
                if position < len(stock) and not np.isnan(stock[position]):
                    path[i] = (stock[position] / stock[base] - 1) - (
                        market[position] / market[base] - 1
                    )
        paths.append(path)
    paths = np.array(paths) if paths else np.empty((0, len(days)))
    return days, np.nanmean(paths, axis=0), np.sum(~np.isnan(paths), axis=0)


def car_chart(curves, path=CHART_FILE):
    """Save the cumulative market-adjusted return for Flagged and Clean,
    one panel per event type (PNG). curves: {event type: {group: (days,
    mean, counts)}}."""
    figure, axes = plt.subplots(1, len(EVENT_TYPES), figsize=(12, 5), dpi=150)
    for axis, kind in zip(axes, EVENT_TYPES):
        for group, color, label in [
            ("flagged", FLAGGED_COLOR, "Flagged (1+ flags)"),
            ("clean", CLEAN_COLOR, "Clean (0 flags)"),
        ]:
            days, mean, counts = curves[kind][group]
            axis.plot(
                days,
                100 * mean,
                color=color,
                linewidth=2,
                label=f"{label}, n = {counts[0]:,}",
            )
        axis.axvline(1, color="#52514e", linestyle="--", linewidth=1)
        axis.text(
            3, axis.get_ylim()[1], "entry (day +1)", va="top", fontsize=8
        )
        axis.axhline(0, color="#0b0b0b", linewidth=0.8)
        axis.set_title(kind, fontsize=11)
        axis.set_xlabel("Trading days from the filing (day 0)")
        axis.set_ylabel("Average cumulative return minus SPY (%)")
        axis.grid(color="#e1e0d9")
        axis.legend(loc="lower left", fontsize=8)
    figure.suptitle(
        "Stock moves around warning filings, by flag status (curiosity "
        "analysis, exploratory)",
        fontsize=12,
    )
    figure.text(
        0.01,
        0.01,
        "Measured from the close on day -6. Current tickers only. "
        "Correlation, not cause. Not investment advice.",
        fontsize=8,
        color="#52514e",
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.95))
    figure.savefig(path)
    plt.close(figure)
    return path


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def build_events():
    """Return (events with days, repeats dropped, flag status and
    outcomes; the price table)."""
    companies = pd.read_parquet(
        config.COMPANIES_PATH, columns=["cik", "ticker", "is_excluded"]
    )
    universe = companies[~companies["is_excluded"]]
    prices = pd.read_parquet(config.PRICES_PATH)
    calendar = backtest.trading_calendar(prices)
    price_wide = backtest.price_table(prices, calendar)
    events = load_filings(universe["cik"].tolist())
    days = [event_days(calendar, filed) for filed in events["filed"]]
    events["day0"] = [d[0] for d in days]
    events["entry"] = [d[1] for d in days]
    events["day0_date"] = calendar[events["day0"]]
    before_repeats = events.groupby("event_type").size()
    events = drop_repeats(events)
    events = flag_status(
        events,
        pd.read_parquet(config.SCORES_PATH),
        pd.read_parquet(config.FINANCIALS_PATH),
    )
    events = events.merge(universe[["cik", "ticker"]], on="cik", how="left")
    events["tier"] = events["flags_raised"].map(
        lambda f: (
            None
            if pd.isna(f)
            else (f"{int(f)} flag" if int(f) == 1 else f"{int(f)} flags")
        )
    )
    usable = events["score_status"] == "ok"
    with_outcomes = event_outcomes(events[usable], price_wide)
    new_columns = [c for c in with_outcomes.columns if c not in events.columns]
    events = events.join(with_outcomes[new_columns])
    return events, price_wide, before_repeats


def main(argv=None):
    """Run the analysis on data/processed/, write the details and the
    chart, and print every count and result."""
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(
        argv
    )
    events, price_wide, before_repeats = build_events()
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    events.to_csv(DETAILS_FILE, index=False)
    pd.set_option("display.width", 220)
    print("events before the repeat rule:", before_repeats.to_dict())
    print(
        "after the repeat rule:", events.groupby("event_type").size().to_dict()
    )
    print("\nscore status:")
    print(events.groupby(["event_type", "score_status"]).size().to_string())
    scored = events[events["score_status"] == "ok"]
    print("\nprice status (scored events):")
    print(scored.groupby(["event_type", "price_status"]).size().to_string())
    curves = {}
    for kind in EVENT_TYPES:
        kind_rows = scored[
            (scored["event_type"] == kind) & (scored["price_status"] == "ok")
        ]
        main_rows = kind_rows[kind_rows["entry_price"] >= MIN_PRICE]
        print(
            f"\n===== {kind}: eligible {len(main_rows)} (without the $5 rule: {len(kind_rows)})"
        )
        print("by group and year:")
        print(
            main_rows.groupby(["group", main_rows["filed"].dt.year])
            .size()
            .unstack(fill_value=0)
            .to_string()
        )
        for label, frame in [
            ("main ($5 rule)", main_rows),
            ("without $5 rule", kind_rows),
        ]:
            for window in [REGISTERED_WINDOW] + DESCRIPTIVE_WINDOWS:
                outcome = f"car_1_{window}"
                tests = clustered_tests(frame, outcome)
                tag = (
                    "REGISTERED"
                    if window == REGISTERED_WINDOW and label.startswith("main")
                    else "descriptive"
                )
                print(
                    f"{label}, days +1 to +{window} [{tag}]:",
                    {
                        k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in tests.items()
                    },
                )
        print("by flag count (days +1 to +63, $5 rule): mean, events")
        print(
            main_rows.groupby("tier")[f"car_1_{REGISTERED_WINDOW}"]
            .agg(["mean", "count"])
            .round(4)
            .to_string()
        )
        print(
            "filing-day move (filed on a trading day), by group: mean, events"
        )
        print(
            main_rows.groupby("group")["filing_day_move"]
            .agg(["mean", "count"])
            .round(4)
            .to_string()
        )
        curves[kind] = {
            group: car_curve(
                main_rows[main_rows["group"] == group], price_wide
            )
            for group in ("flagged", "clean")
        }
    car_chart(curves)
    print(f"\nSaved {DETAILS_FILE} and {CHART_FILE}")


if __name__ == "__main__":
    main()
