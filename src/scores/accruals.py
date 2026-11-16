"""Accruals ratio and cash conversion (CLAUDE.md section 5).

Both measure how much of reported profit is backed by operating cash:
- accruals_ratio = (net income - CFO) / average total assets. Higher means
  more of the profit is accruals rather than cash. Average assets need
  the t-1 balance sheet, so a missing prior year leaves it blank.
- cash_conversion = CFO / net income. Blank when net income is zero or
  negative: dividing by a loss flips the sign (a loss-maker burning cash
  would show a "healthy" positive ratio), so the number would mislead.
"""

from src.scores import common

INPUT_COLUMNS = ["net_income", "cfo", "total_assets"]


def average_total_assets(frame):
    """Return (TotalAssets_t + TotalAssets_t-1) / 2."""
    return (frame["total_assets"] + frame["total_assets_prior"]) / 2


def accruals_ratio(frame):
    """Return (NetIncome_t - CFO_t) / average total assets."""
    return common.safe_divide(
        frame["net_income"] - frame["cfo"], average_total_assets(frame)
    )


def cash_conversion(frame):
    """Return CFO_t / NetIncome_t, NaN where net income is not positive."""
    positive_income = frame["net_income"].where(frame["net_income"] > 0)
    return frame["cfo"] / positive_income


def compute_accruals(financials_df):
    """Return cik, fiscal_year, accruals_ratio, cash_conversion, notes."""
    frame = common.with_prior_years(financials_df, INPUT_COLUMNS, 1)
    result_df = frame[common.KEY_COLUMNS].copy()
    result_df["accruals_ratio"] = accruals_ratio(frame)
    result_df["cash_conversion"] = cash_conversion(frame)

    # Only the inputs actually used are reported: the prior year matters
    # for total assets only.
    conditions = common.missing_input_conditions(
        frame, {0: INPUT_COLUMNS, 1: ["total_assets"]}
    )
    conditions += [
        (
            result_df["accruals_ratio"].isna()
            & frame[["net_income", "cfo", "total_assets"]].notna().all(axis=1)
            & frame["total_assets_prior"].notna(),
            "accruals_ratio_zero_denominator",
        ),
        # Not a missing input, but recorded so a blank cash_conversion
        # always has a stated reason.
        (frame["net_income"] <= 0, "net_income_not_positive"),
    ]
    result_df["accruals_notes"] = common.build_notes(frame.index, conditions)
    return result_df
