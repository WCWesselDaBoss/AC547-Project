"""Altman Z'' (non-manufacturer model): the 4 ratios, score and zone.

Formula and zones are CLAUDE.md section 5; coefficients and zone cutoffs
are read from config.py. Z'' uses book equity, so it needs no price data
and works for every industry in our universe.

Z'' uses year-t values only, so there is no prior-year matching here.
A missing input or zero denominator makes that ratio NaN, and any NaN
ratio makes z_score and z_zone blank (no partial scores).
"""

import pandas as pd

import config
from src.scores import common

INPUT_COLUMNS = [
    "current_assets",
    "current_liabilities",
    "retained_earnings",
    "operating_income",
    "stockholders_equity",
    "total_liabilities",
    "total_assets",
]
RATIO_COLUMNS = list(config.ALTMAN_Z2_COEFFICIENTS)

# Inputs per ratio, used to tell a zero denominator from a missing input.
RATIO_INPUTS = {
    "z_x1": ["current_assets", "current_liabilities", "total_assets"],
    "z_x2": ["retained_earnings", "total_assets"],
    "z_x3": ["operating_income", "total_assets"],
    "z_x4": ["stockholders_equity", "total_liabilities"],
}


def z_x1(frame):
    """X1 = working capital / total assets (liquidity)."""
    working_capital = frame["current_assets"] - frame["current_liabilities"]
    return common.safe_divide(working_capital, frame["total_assets"])


def z_x2(frame):
    """X2 = retained earnings / total assets (cumulative profitability)."""
    return common.safe_divide(
        frame["retained_earnings"], frame["total_assets"]
    )


def z_x3(frame):
    """X3 = EBIT / total assets, with operating income as EBIT.

    Operating income is the proxy agreed in section 5; it excludes
    non-operating gains and losses that true EBIT would include.
    """
    return common.safe_divide(frame["operating_income"], frame["total_assets"])


def z_x4(frame):
    """X4 = book equity / total liabilities (solvency cushion)."""
    return common.safe_divide(
        frame["stockholders_equity"], frame["total_liabilities"]
    )


RATIO_FUNCTIONS = {"z_x1": z_x1, "z_x2": z_x2, "z_x3": z_x3, "z_x4": z_x4}


def z_score(ratios_df):
    """Return Z'' from the four ratio columns; NaN if any ratio is NaN."""
    weighted = ratios_df[RATIO_COLUMNS].mul(
        pd.Series(config.ALTMAN_Z2_COEFFICIENTS)
    )
    return weighted.sum(axis=1, skipna=False)


def z_zone(z_scores):
    """Return 'safe', 'grey' or 'distress'; NA when there is no score.

    Strict inequalities put a score of exactly 2.60 or 1.10 in the grey
    zone, matching "above 2.60 safe ... below 1.10 distress".
    """
    zone = pd.Series(pd.NA, index=z_scores.index, dtype="string")
    zone[z_scores > config.ALTMAN_Z2_SAFE_ABOVE] = "safe"
    zone[
        (z_scores <= config.ALTMAN_Z2_SAFE_ABOVE)
        & (z_scores >= config.ALTMAN_Z2_DISTRESS_BELOW)
    ] = "grey"
    zone[z_scores < config.ALTMAN_Z2_DISTRESS_BELOW] = "distress"
    return zone


def compute_altman(financials_df):
    """Return one row per company-year with X1-X4, z_score and z_zone.

    Also returns altman_notes explaining any blank value.
    """
    frame = financials_df[common.KEY_COLUMNS + INPUT_COLUMNS].reset_index(
        drop=True
    )
    result_df = frame[common.KEY_COLUMNS].copy()
    conditions = common.missing_input_conditions(frame, {0: INPUT_COLUMNS})
    for ratio_name, ratio_function in RATIO_FUNCTIONS.items():
        values = ratio_function(frame)
        all_present = frame[RATIO_INPUTS[ratio_name]].notna().all(axis=1)
        conditions.append(
            (values.isna() & all_present, f"{ratio_name}_zero_denominator")
        )
        result_df[ratio_name] = values
    result_df["z_score"] = z_score(result_df)
    result_df["z_zone"] = z_zone(result_df["z_score"])
    result_df["altman_notes"] = common.build_notes(frame.index, conditions)
    return result_df
