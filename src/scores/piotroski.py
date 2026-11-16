"""Piotroski F-Score: the 9 signals and the 0-9 score.

Signals are CLAUDE.md section 5 (Piotroski 2000); missing-data and tie
rules are the "Missing inputs and ties" paragraph under it.

Each signal is True (1 point), False (0 points) or NA (cannot be
determined). Several signals compare this year's ratio with last year's
ratio, and last year's ratio uses beginning-of-year assets, so the F-Score
needs three balance sheets: t, t-1 and t-2. A company's first two scored
years therefore have no F-Score unless the earlier rows exist.

Signal 7 (no new shares) is the exception to "prior year = prior row".
Share counts are restated after stock splits, so comparing this year's
count with last year's ORIGINAL count would make a 2-for-1 split look
like issuing 100% more shares. Section 4 therefore requires the prior
year's count as reported in the SAME 10-K, read from facts_long.
"""

import pandas as pd

import config
from src.scores import common

INPUT_COLUMNS = [
    "net_income",
    "cfo",
    "total_assets",
    "long_term_debt",
    "current_assets",
    "current_liabilities",
    "revenue",
    "cost_of_revenue",
    "shares_outstanding",
    "period_end",
    "accession",
]
# Inputs read from each year (0 = t, 1 = t-1, 2 = t-2), for the notes.
INPUTS_BY_LAG = {
    0: [
        "net_income",
        "cfo",
        "total_assets",
        "long_term_debt",
        "current_assets",
        "current_liabilities",
        "revenue",
        "cost_of_revenue",
        "shares_outstanding",
    ],
    1: [
        "net_income",
        "total_assets",
        "long_term_debt",
        "current_assets",
        "current_liabilities",
        "revenue",
        "cost_of_revenue",
    ],
    2: ["total_assets"],
}
SIGNAL_COLUMNS = [
    "f_roa_positive",
    "f_cfo_positive",
    "f_roa_improved",
    "f_cfo_exceeds_roa",
    "f_leverage_down",
    "f_current_ratio_up",
    "f_no_new_shares",
    "f_gross_margin_up",
    "f_asset_turnover_up",
]
PRIOR_SHARES = "shares_prior_same_filing"
TOLERANCE = config.F_SCORE_TIE_TOLERANCE


def _value(frame, column, years_back):
    """Return input ``column`` at t (0), t-1 (1) or t-2 (2)."""
    return frame[common.lagged(column, years_back)]


def prior_shares_same_filing(frame, facts_long_df):
    """Return the t-1 share count reported in year t's own 10-K.

    Matches facts_long on the year-t accession number and on the t-1
    balance-sheet date (period_end of the t-1 row). Matching the exact
    date, not just the fiscal year, matters: some 10-Ks also tag share
    counts at mid-year dates (e.g. on the equity statement).

    Returns (shares, is_ambiguous). If the filing reports two different
    values for that date, the count is NaN and is_ambiguous is True,
    because picking one would be a guess.
    """
    share_facts = facts_long_df.loc[
        facts_long_df["line_item"] == "shares_outstanding",
        ["cik", "accession", "period_end", "value"],
    ]
    per_key = (
        share_facts.groupby(["cik", "accession", "period_end"])["value"]
        .agg(["first", "nunique"])
        .reset_index()
    )
    lookup = frame[["cik", "accession", "period_end_prior"]].rename(
        columns={"period_end_prior": "period_end"}
    )
    matched = lookup.merge(
        per_key, on=["cik", "accession", "period_end"], how="left"
    )
    is_ambiguous = (matched["nunique"] > 1).to_numpy()
    shares = matched["first"].where(~is_ambiguous)
    return (
        pd.Series(shares.to_numpy(), index=frame.index, dtype="float64"),
        pd.Series(is_ambiguous, index=frame.index),
    )


def prepare_frame(financials_df, facts_long_df):
    """Return year-t rows with inputs for t, t-1, t-2 and prior shares."""
    frame = common.with_prior_years(financials_df, INPUT_COLUMNS, 2)
    shares, is_ambiguous = prior_shares_same_filing(frame, facts_long_df)
    frame[PRIOR_SHARES] = shares
    frame["prior_shares_ambiguous"] = is_ambiguous
    return frame


def roa(frame, years_back):
    """Return ROA for year t-k: net income / BEGINNING total assets.

    Beginning assets are the prior year's ending assets, as in Piotroski.
    """
    return common.safe_divide(
        _value(frame, "net_income", years_back),
        _value(frame, "total_assets", years_back + 1),
    )


def average_assets(frame, years_back):
    """Return the average of total assets at t-k and t-k-1."""
    return (
        _value(frame, "total_assets", years_back)
        + _value(frame, "total_assets", years_back + 1)
    ) / 2


def leverage(frame, years_back):
    """Return long-term debt / average total assets for year t-k."""
    return common.safe_divide(
        _value(frame, "long_term_debt", years_back),
        average_assets(frame, years_back),
    )


def current_ratio(frame, years_back):
    """Return current assets / current liabilities for year t-k."""
    return common.safe_divide(
        _value(frame, "current_assets", years_back),
        _value(frame, "current_liabilities", years_back),
    )


def gross_margin(frame, years_back):
    """Return (revenue - cost of revenue) / revenue for year t-k."""
    revenue = _value(frame, "revenue", years_back)
    cost = _value(frame, "cost_of_revenue", years_back)
    return common.safe_divide(revenue - cost, revenue)


def asset_turnover(frame, years_back):
    """Return revenue / beginning total assets for year t-k."""
    return common.safe_divide(
        _value(frame, "revenue", years_back),
        _value(frame, "total_assets", years_back + 1),
    )


def f_roa_positive(frame):
    """Signal 1: ROA_t > 0."""
    return common.is_positive(roa(frame, 0))


def f_cfo_positive(frame):
    """Signal 2: CFO_t > 0."""
    return common.is_positive(_value(frame, "cfo", 0))


def f_roa_improved(frame):
    """Signal 3: ROA_t higher than ROA_t-1."""
    return common.is_higher(roa(frame, 0), roa(frame, 1), TOLERANCE)


def f_cfo_exceeds_roa(frame):
    """Signal 4: CFO_t / beginning assets > ROA_t (cash beats accruals)."""
    cfo_return = common.safe_divide(
        _value(frame, "cfo", 0), _value(frame, "total_assets", 1)
    )
    return common.is_higher(cfo_return, roa(frame, 0), TOLERANCE)


def f_leverage_down(frame):
    """Signal 5: long-term debt / average assets LOWER than last year."""
    return common.is_higher(leverage(frame, 1), leverage(frame, 0), TOLERANCE)


def f_current_ratio_up(frame):
    """Signal 6: current ratio higher than last year."""
    return common.is_higher(
        current_ratio(frame, 0), current_ratio(frame, 1), TOLERANCE
    )


def f_no_new_shares(frame):
    """Signal 7: shares_t NOT higher than t-1 shares from the same 10-K.

    Equal counts pass (no issuance). NA stays NA through the negation.
    """
    issued = common.is_higher(
        _value(frame, "shares_outstanding", 0), frame[PRIOR_SHARES], TOLERANCE
    )
    return ~issued


def f_gross_margin_up(frame):
    """Signal 8: gross margin higher than last year."""
    return common.is_higher(
        gross_margin(frame, 0), gross_margin(frame, 1), TOLERANCE
    )


def f_asset_turnover_up(frame):
    """Signal 9: revenue / beginning assets higher than last year."""
    return common.is_higher(
        asset_turnover(frame, 0), asset_turnover(frame, 1), TOLERANCE
    )


SIGNAL_FUNCTIONS = {
    "f_roa_positive": f_roa_positive,
    "f_cfo_positive": f_cfo_positive,
    "f_roa_improved": f_roa_improved,
    "f_cfo_exceeds_roa": f_cfo_exceeds_roa,
    "f_leverage_down": f_leverage_down,
    "f_current_ratio_up": f_current_ratio_up,
    "f_no_new_shares": f_no_new_shares,
    "f_gross_margin_up": f_gross_margin_up,
    "f_asset_turnover_up": f_asset_turnover_up,
}

# Inputs per signal as (column, years_back), to tell a zero denominator
# from a missing input. PRIOR_SHARES is a frame column, so years_back 0.
SIGNAL_INPUTS = {
    "f_roa_positive": [("net_income", 0), ("total_assets", 1)],
    "f_cfo_positive": [("cfo", 0)],
    "f_roa_improved": [("net_income", 0), ("net_income", 1)]
    + [("total_assets", 1), ("total_assets", 2)],
    "f_cfo_exceeds_roa": [("cfo", 0), ("net_income", 0)]
    + [("total_assets", 1)],
    "f_leverage_down": [("long_term_debt", 0), ("long_term_debt", 1)]
    + [("total_assets", k) for k in (0, 1, 2)],
    "f_current_ratio_up": [("current_assets", k) for k in (0, 1)]
    + [("current_liabilities", k) for k in (0, 1)],
    "f_no_new_shares": [("shares_outstanding", 0), (PRIOR_SHARES, 0)],
    "f_gross_margin_up": [("revenue", k) for k in (0, 1)]
    + [("cost_of_revenue", k) for k in (0, 1)],
    "f_asset_turnover_up": [("revenue", 0), ("revenue", 1)]
    + [("total_assets", 1), ("total_assets", 2)],
}


def _inputs_present(frame, signal_name, skip_column=None):
    """Return True where every input of a signal is present."""
    present = pd.Series(True, index=frame.index)
    for column, years_back in SIGNAL_INPUTS[signal_name]:
        if column != skip_column:
            present &= _value(frame, column, years_back).notna()
    return present


def leverage_exception(frame, signals_df):
    """Return True where signal 5 is NA only because LTD is missing.

    Section 5: such rows still get an F-Score, with signal 5 counted as
    0 points. A missing value never earns a point, so this can only
    understate the score.
    """
    return (
        signals_df["f_leverage_down"].isna()
        & (
            _value(frame, "long_term_debt", 0).isna()
            | _value(frame, "long_term_debt", 1).isna()
        )
        & _inputs_present(frame, "f_leverage_down", "long_term_debt")
    )


def f_score(signals_df, ignore_signal_5_na):
    """Return the number of True signals (0-9) as nullable Int64.

    NA if any signal is NA, except a signal-5 NA covered by the
    long-term-debt exception (``ignore_signal_5_na`` True for that row).
    """
    is_unknown = signals_df[SIGNAL_COLUMNS].isna()
    is_unknown["f_leverage_down"] &= ~ignore_signal_5_na
    points = signals_df[SIGNAL_COLUMNS].fillna(False).astype(int).sum(axis=1)
    score = points.astype("Int64")
    score[is_unknown.any(axis=1)] = pd.NA
    return score


def compute_piotroski(financials_df, facts_long_df):
    """Return one row per company-year with the 9 signals and f_score.

    Also returns piotroski_notes explaining any NA signal or exception.
    """
    frame = prepare_frame(financials_df, facts_long_df)
    result_df = frame[common.KEY_COLUMNS].copy()
    conditions = common.missing_input_conditions(frame, INPUTS_BY_LAG)
    conditions += [
        (
            frame[PRIOR_SHARES].isna()
            & frame["has_row_prior"]
            & ~frame["prior_shares_ambiguous"],
            "shares_t-1_same_filing",
        ),
        (frame["prior_shares_ambiguous"], "shares_t-1_same_filing_ambiguous"),
    ]
    for signal_name, signal_function in SIGNAL_FUNCTIONS.items():
        values = signal_function(frame)
        conditions.append(
            (
                values.isna() & _inputs_present(frame, signal_name),
                f"{signal_name}_zero_denominator",
            )
        )
        result_df[signal_name] = values

    exception = leverage_exception(frame, result_df)
    conditions.append((exception, "f_leverage_down_no_point"))
    result_df["f_score"] = f_score(result_df, exception)
    result_df["piotroski_notes"] = common.build_notes(frame.index, conditions)
    return result_df
