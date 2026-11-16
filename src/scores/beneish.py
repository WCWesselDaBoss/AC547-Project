"""Beneish M-Score: the 8 indexes, the score and the flag.

Formulas are CLAUDE.md section 5 (Beneish 1999, 8-variable model).
Coefficients and the cutoff are read from config.py, never typed here.

Each index has its own small function so that any value on the dashboard
traces to one named function (CLAUDE.md section 6). Every function takes
the "frame" built by ``prepare_frame``: one row per company-year with the
year-t inputs and the same inputs for t-1 (suffix ``_prior``).

Missing data rules (CLAUDE.md sections 2 and 5):
- A missing input makes its index NaN, and a NaN index makes m_score NaN.
- Two documented exceptions use a neutral index of 1: SGAI when SGA is
  missing and LVGI when long-term debt is missing, but only when that item
  is the index's ONLY missing input (otherwise the index stays NaN).
- A zero denominator makes the index NaN (see common.safe_divide).
Every blank or neutral value is explained in the missing_inputs notes.
"""

import pandas as pd

import config
from src.scores import common

INPUT_COLUMNS = [
    "revenue",
    "cost_of_revenue",
    "sga",
    "depreciation",
    "income_continuing_ops",
    "cfo",
    "receivables",
    "current_assets",
    "ppe_net",
    "total_assets",
    "current_liabilities",
    "long_term_debt",
]
INDEX_COLUMNS = list(config.BENEISH_COEFFICIENTS)

# Inputs each index reads, as (column, years_back) pairs. Used to tell a
# zero-denominator blank (all inputs present) from a missing-input blank.
INDEX_INPUTS = {
    "dsri": [("receivables", 0), ("revenue", 0)]
    + [("receivables", 1), ("revenue", 1)],
    "gmi": [("revenue", 0), ("cost_of_revenue", 0)]
    + [("revenue", 1), ("cost_of_revenue", 1)],
    "aqi": [("current_assets", k) for k in (0, 1)]
    + [("ppe_net", k) for k in (0, 1)]
    + [("total_assets", k) for k in (0, 1)],
    "sgi": [("revenue", 0), ("revenue", 1)],
    "depi": [("depreciation", k) for k in (0, 1)]
    + [("ppe_net", k) for k in (0, 1)],
    "sgai": [("sga", k) for k in (0, 1)] + [("revenue", k) for k in (0, 1)],
    "tata": [("income_continuing_ops", 0), ("cfo", 0), ("total_assets", 0)],
    "lvgi": [("current_liabilities", k) for k in (0, 1)]
    + [("long_term_debt", k) for k in (0, 1)]
    + [("total_assets", k) for k in (0, 1)],
}

# Indexes set to 1 when this one input is missing (section 5).
NEUTRAL_WHEN_MISSING = {"sgai": "sga", "lvgi": "long_term_debt"}


def prepare_frame(financials_df):
    """Return year-t rows with every M-Score input for t and t-1."""
    return common.with_prior_years(financials_df, INPUT_COLUMNS, 1)


def _value(frame, column, years_back):
    """Return input ``column`` at t (0) or t-1 (1)."""
    return frame[common.lagged(column, years_back)]


def dsri(frame):
    """Days Sales in Receivables Index.

    (Receivables_t / Sales_t) / (Receivables_t-1 / Sales_t-1). Above 1
    means receivables grew faster than sales, which can signal revenue
    booked before cash is collected.
    """
    ratio_t = common.safe_divide(
        _value(frame, "receivables", 0), _value(frame, "revenue", 0)
    )
    ratio_prior = common.safe_divide(
        _value(frame, "receivables", 1), _value(frame, "revenue", 1)
    )
    return common.safe_divide(ratio_t, ratio_prior)


def gross_margin(frame, years_back):
    """Return (Sales - COGS) / Sales for year t or t-1."""
    revenue = _value(frame, "revenue", years_back)
    cost = _value(frame, "cost_of_revenue", years_back)
    return common.safe_divide(revenue - cost, revenue)


def gmi(frame):
    """Gross Margin Index: GrossMargin_t-1 / GrossMargin_t.

    Above 1 means margins shrank, which Beneish found makes firms more
    likely to manipulate. Note the prior year is on TOP.
    """
    return common.safe_divide(gross_margin(frame, 1), gross_margin(frame, 0))


def soft_asset_share(frame, years_back):
    """Return 1 - (CurrentAssets + NetPPE) / TotalAssets for a year.

    The share of assets that are neither current nor PP&E: intangibles,
    deferred costs and other assets whose value is harder to verify.
    """
    hard_assets = _value(frame, "current_assets", years_back) + _value(
        frame, "ppe_net", years_back
    )
    return 1 - common.safe_divide(
        hard_assets, _value(frame, "total_assets", years_back)
    )


def aqi(frame):
    """Asset Quality Index: soft-asset share at t over t-1.

    Above 1 means more costs are being capitalized as soft assets.
    """
    return common.safe_divide(
        soft_asset_share(frame, 0), soft_asset_share(frame, 1)
    )


def sgi(frame):
    """Sales Growth Index: Sales_t / Sales_t-1."""
    return common.safe_divide(
        _value(frame, "revenue", 0), _value(frame, "revenue", 1)
    )


def depreciation_rate(frame, years_back):
    """Return Dep / (Dep + NetPPE) for year t or t-1."""
    depreciation = _value(frame, "depreciation", years_back)
    return common.safe_divide(
        depreciation, depreciation + _value(frame, "ppe_net", years_back)
    )


def depi(frame):
    """Depreciation Index: depreciation rate at t-1 over t.

    Above 1 means assets are being depreciated more slowly, which raises
    earnings. The prior year is on TOP.
    """
    return common.safe_divide(
        depreciation_rate(frame, 1), depreciation_rate(frame, 0)
    )


def sgai(frame):
    """SG&A Index: (SGA_t / Sales_t) / (SGA_t-1 / Sales_t-1).

    Returns NaN if SGA is missing; ``compute_beneish`` applies the
    neutral-value rule so this function stays a pure formula.
    """
    ratio_t = common.safe_divide(
        _value(frame, "sga", 0), _value(frame, "revenue", 0)
    )
    ratio_prior = common.safe_divide(
        _value(frame, "sga", 1), _value(frame, "revenue", 1)
    )
    return common.safe_divide(ratio_t, ratio_prior)


def tata(frame):
    """Total Accruals to Total Assets, year t only.

    (IncomeContinuingOps_t - CFO_t) / TotalAssets_t. Positive means
    reported profit is higher than the cash it brought in.
    """
    accruals = _value(frame, "income_continuing_ops", 0) - _value(
        frame, "cfo", 0
    )
    return common.safe_divide(accruals, _value(frame, "total_assets", 0))


def leverage(frame, years_back):
    """Return (CurrentLiab + LongTermDebt) / TotalAssets for a year."""
    debt = _value(frame, "current_liabilities", years_back) + _value(
        frame, "long_term_debt", years_back
    )
    return common.safe_divide(debt, _value(frame, "total_assets", years_back))


def lvgi(frame):
    """Leverage Index: leverage at t over t-1. Above 1 = more debt."""
    return common.safe_divide(leverage(frame, 0), leverage(frame, 1))


INDEX_FUNCTIONS = {
    "dsri": dsri,
    "gmi": gmi,
    "aqi": aqi,
    "sgi": sgi,
    "depi": depi,
    "sgai": sgai,
    "tata": tata,
    "lvgi": lvgi,
}


def _inputs_present(frame, index_name, skip_column=None):
    """Return True where every input of an index is present.

    ``skip_column`` leaves one input out of the check (used for the
    neutral-value rule, which applies when only that input is missing).
    """
    present = pd.Series(True, index=frame.index)
    for column, years_back in INDEX_INPUTS[index_name]:
        if column != skip_column:
            present &= _value(frame, column, years_back).notna()
    return present


def m_score(indexes_df):
    """Return the M-Score from the 8 index columns.

    NaN if any index is NaN: a partial M-Score would be a different model
    (CLAUDE.md section 2, no estimates).
    """
    weighted = indexes_df[INDEX_COLUMNS].mul(
        pd.Series(config.BENEISH_COEFFICIENTS)
    )
    return config.BENEISH_INTERCEPT + weighted.sum(axis=1, skipna=False)


def m_flag(m_scores, cutoff=config.BENEISH_FLAG_CUTOFF):
    """Return True where M > cutoff (likely manipulator), NA if no score."""
    flag = (m_scores > cutoff).astype("boolean")
    flag[m_scores.isna()] = pd.NA
    return flag


def compute_beneish(financials_df, cutoff=config.BENEISH_FLAG_CUTOFF):
    """Return one row per company-year with the 8 indexes, M and flag.

    Columns: cik, fiscal_year, dsri ... lvgi, m_score, m_flag,
    beneish_notes (why any value is blank or neutral, else NA).
    """
    frame = prepare_frame(financials_df)
    result_df = frame[common.KEY_COLUMNS].copy()
    conditions = common.missing_input_conditions(
        frame, {0: INPUT_COLUMNS, 1: INPUT_COLUMNS}
    )

    for index_name, index_function in INDEX_FUNCTIONS.items():
        values = index_function(frame)
        all_present = _inputs_present(frame, index_name)
        # Inputs all there but the index is blank: a denominator was 0.
        conditions.append(
            (values.isna() & all_present, f"{index_name}_zero_denominator")
        )
        result_df[index_name] = values

    for index_name, column in NEUTRAL_WHEN_MISSING.items():
        # Neutral only if this one item is what is missing and the prior
        # row exists; otherwise the gap is real and the index stays NaN.
        item_missing = (
            _value(frame, column, 0).isna() | _value(frame, column, 1).isna()
        )
        use_neutral = (
            item_missing
            & frame[common.has_row_column(1)]
            & _inputs_present(frame, index_name, skip_column=column)
        )
        result_df.loc[use_neutral, index_name] = 1.0
        conditions.append((use_neutral, f"{index_name}_set_to_1"))

    result_df["m_score"] = m_score(result_df)
    result_df["m_flag"] = m_flag(result_df["m_score"], cutoff)
    result_df["beneish_notes"] = common.build_notes(frame.index, conditions)
    return result_df
