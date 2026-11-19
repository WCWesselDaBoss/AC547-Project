"""Click-to-trace: every input behind a score, back to its SEC filing.

For a score (or one part of it, such as DSRI), this module returns the
formula, the stored result, the function that computed it, and one row
per input: the value the score used, its XBRL tag, period, 10-K filing
date, accession number and EDGAR link (CLAUDE.md section 6,
Traceability).

Which inputs a score reads comes from Phase 2's own maps
(beneish.INDEX_INPUTS, altman.RATIO_INPUTS, piotroski.SIGNAL_INPUTS),
so the panel cannot list different inputs from the ones the score used.
Nothing here recomputes a score; it looks values up and shows them.
"""

from collections import namedtuple

import numpy as np
import pandas as pd

import config
from app import labels, screening
from src.pipeline import derived_items, financials
from src.scores import accruals, altman, beneish, piotroski

ALL_PARTS = "all"

# label: what the analyst picks; stored_column: the scores-table column
# holding the result; formula: text from CLAUDE.md section 5; inputs:
# (financials column, years back) pairs; function: the Python function
# that computed the stored result.
Part = namedtuple("Part", "label stored_column formula inputs function")

# Statuses for each input row. Icon AND words, never color alone.
REPORTED = "✅ Reported in the 10-K"
CALCULATED = "🧮 Calculated from other reported facts"
COMPONENT = "↳ Used in the calculation above"
NOT_REPORTED = "⚪ Not reported"
NO_YEAR = "⚪ No 10-K data for this year"
NOT_MATCHED = "⚠️ Not matched to a filing fact"

# Values match when they agree to this relative tolerance. They come
# from the same Parquet source, so any real difference is far larger.
VALUE_MATCH_TOLERANCE = 1e-9

PRIOR_SHARES_LABEL = (
    "Shares outstanding (prior year, as shown in this year's 10-K)"
)

# Phase 1 component columns used by the two derived line items, and the
# plain names shown in the trace. Derivation rules are in
# src/pipeline/derived_items.py.
COMPONENT_LABELS = {
    "income_discontinued_ops": "Income from discontinued operations",
    "liabilities_and_equity": "Total liabilities and equity",
    "equity_including_nci": "Equity including minority interests",
    "temporary_equity_total": "Temporary (mezzanine) equity, total",
    "temporary_equity_parent": "Temporary equity, parent",
    "redeemable_nci": "Redeemable minority interests",
}
DERIVED_COMPONENTS = {
    "income_continuing_ops": ["net_income", "income_discontinued_ops"],
    "total_liabilities": [
        "liabilities_and_equity",
        "equity_including_nci",
        "stockholders_equity",
        "temporary_equity_total",
        "temporary_equity_parent",
        "redeemable_nci",
    ],
}
DERIVATION_NOTES = {
    "income_continuing_ops": (
        "Income from continuing operations was not tagged, so Phase 1 "
        "calculated it as net income minus income from discontinued "
        "operations (none counted as zero)"
    ),
    "total_liabilities": (
        "Total liabilities was not tagged, so Phase 1 calculated it as "
        "total liabilities and equity, minus equity (including minority "
        "interests when reported), minus temporary equity"
    ),
}

# ---------------------------------------------------------------------------
# Formulas (CLAUDE.md section 5). Coefficients are read from config.py.
# ---------------------------------------------------------------------------
M_INDEX_FORMULAS = {
    "dsri": "DSRI = (Receivables_t / Sales_t) / "
    "(Receivables_t-1 / Sales_t-1)",
    "gmi": "GMI = GrossMargin_t-1 / GrossMargin_t\n"
    "GrossMargin = (Sales - Cost of revenue) / Sales",
    "aqi": "AQI = [1 - (CurrentAssets_t + NetPPE_t) / TotalAssets_t] / "
    "[same for t-1]",
    "sgi": "SGI = Sales_t / Sales_t-1",
    "depi": "DEPI = [Dep_t-1 / (Dep_t-1 + NetPPE_t-1)] / "
    "[Dep_t / (Dep_t + NetPPE_t)]",
    "sgai": "SGAI = (SGA_t / Sales_t) / (SGA_t-1 / Sales_t-1)\n"
    "Set to 1 (neutral) when SG&A is not reported.",
    "tata": "TATA = (IncomeContinuingOps_t - CFO_t) / TotalAssets_t",
    "lvgi": "LVGI = [(CurrentLiab_t + LongTermDebt_t) / TotalAssets_t] / "
    "[same for t-1]\n"
    "Set to 1 (neutral) when long-term debt is not reported.",
}
Z_RATIO_FORMULAS = {
    "z_x1": "X1 = (Current assets_t - Current liabilities_t) / "
    "Total assets_t",
    "z_x2": "X2 = Retained earnings_t / Total assets_t",
    "z_x3": "X3 = Operating income_t / Total assets_t  "
    "(operating income stands in for EBIT)",
    "z_x4": "X4 = Stockholders' equity_t / Total liabilities_t",
}
F_SIGNAL_FORMULAS = {
    "f_roa_positive": "ROA_t = Net income_t / Total assets_t-1 > 0",
    "f_cfo_positive": "CFO_t > 0",
    "f_roa_improved": "ROA_t > ROA_t-1, where ROA_t-1 = "
    "Net income_t-1 / Total assets_t-2",
    "f_cfo_exceeds_roa": "CFO_t / Total assets_t-1 > ROA_t",
    "f_leverage_down": "Long-term debt_t / avg(Total assets_t, t-1) < "
    "Long-term debt_t-1 / avg(Total assets_t-1, t-2)\n"
    "No point (but F-Score still computed) when long-term debt is "
    "not reported.",
    "f_current_ratio_up": "Current assets_t / Current liabilities_t > "
    "same ratio for t-1",
    "f_no_new_shares": "Shares outstanding_t <= prior-year shares as "
    "shown in year t's own 10-K (so a stock split is not mistaken for "
    "new shares)",
    "f_gross_margin_up": "GrossMargin_t > GrossMargin_t-1, where "
    "GrossMargin = (Sales - Cost of revenue) / Sales",
    "f_asset_turnover_up": "Sales_t / Total assets_t-1 > "
    "Sales_t-1 / Total assets_t-2",
}
TIE_NOTE = (
    '\n"Higher" and "lower" are strict: a tie (within '
    f"{config.F_SCORE_TIE_TOLERANCE:g} relative) earns no point."
)


def _signed_term(coefficient, name):
    """Return "+ 0.920 x DSRI" or "- 0.327 x LVGI"."""
    sign = "-" if coefficient < 0 else "+"
    return f"{sign} {abs(coefficient):.3f} x {name}"


def m_formula():
    """Return the M-Score equation built from config's coefficients."""
    terms = " ".join(
        _signed_term(coefficient, column.upper())
        for column, coefficient in config.BENEISH_COEFFICIENTS.items()
    )
    return (
        f"M = {config.BENEISH_INTERCEPT:.2f} {terms}\n"
        f"Warning when M is above the cutoff "
        f"(published: {config.BENEISH_FLAG_CUTOFF})."
    )


def z_formula():
    """Return the Z''-Score equation built from config's coefficients."""
    terms = " ".join(
        _signed_term(coefficient, column.removeprefix("z_").upper())
        for column, coefficient in config.ALTMAN_Z2_COEFFICIENTS.items()
    ).removeprefix("+ ")
    return (
        f"Z'' = {terms}\n"
        f"Safe above {config.ALTMAN_Z2_SAFE_ABOVE:.2f}; distress below "
        f"{config.ALTMAN_Z2_DISTRESS_BELOW:.2f}; grey in between."
    )


def _unique(pairs):
    """Return the (column, years back) pairs without repeats, in order."""
    return list(dict.fromkeys(pairs))


def _all_inputs(input_map):
    """Return every input in a {part: inputs} map, without repeats."""
    return _unique(pair for inputs in input_map.values() for pair in inputs)


def function_name(function):
    """Return e.g. "src.scores.beneish.dsri()" for display."""
    return f"{function.__module__}.{function.__name__}()"


def _build_scores():
    """Return {score: {part key: Part}} for every traceable score."""
    m_parts = {
        ALL_PARTS: Part(
            "Whole M-Score",
            "m_score",
            m_formula(),
            _all_inputs(beneish.INDEX_INPUTS),
            beneish.m_score,
        )
    }
    for index in beneish.INDEX_COLUMNS:
        m_parts[index] = Part(
            labels.M_INDEX_LABELS[index],
            index,
            M_INDEX_FORMULAS[index],
            beneish.INDEX_INPUTS[index],
            getattr(beneish, index),
        )

    z_parts = {
        ALL_PARTS: Part(
            "Whole Z''-Score",
            "z_score",
            z_formula(),
            _all_inputs(
                {
                    ratio: [(column, 0) for column in columns]
                    for ratio, columns in altman.RATIO_INPUTS.items()
                }
            ),
            altman.z_score,
        )
    }
    for ratio, columns in altman.RATIO_INPUTS.items():
        z_parts[ratio] = Part(
            labels.Z_RATIO_LABELS[ratio],
            ratio,
            Z_RATIO_FORMULAS[ratio],
            [(column, 0) for column in columns],
            altman.RATIO_FUNCTIONS[ratio],
        )

    f_parts = {
        ALL_PARTS: Part(
            "Whole F-Score",
            "f_score",
            "F-Score = number of the nine tests passed (0 to 9)",
            _all_inputs(piotroski.SIGNAL_INPUTS),
            piotroski.f_score,
        )
    }
    for signal, inputs in piotroski.SIGNAL_INPUTS.items():
        f_parts[signal] = Part(
            labels.F_SIGNAL_LABELS[signal],
            signal,
            F_SIGNAL_FORMULAS[signal] + TIE_NOTE,
            inputs,
            piotroski.SIGNAL_FUNCTIONS[signal],
        )

    return {
        "m_score": m_parts,
        "z_score": z_parts,
        "f_score": f_parts,
        "accruals_ratio": {
            ALL_PARTS: Part(
                "Accruals ratio",
                "accruals_ratio",
                "Accruals ratio = (Net income_t - CFO_t) / "
                "average(Total assets_t, Total assets_t-1)",
                [("net_income", 0), ("cfo", 0)]
                + [("total_assets", 0), ("total_assets", 1)],
                accruals.accruals_ratio,
            )
        },
        "cash_conversion": {
            ALL_PARTS: Part(
                "Cash conversion",
                "cash_conversion",
                "Cash conversion = CFO_t / Net income_t\n"
                "Blank when net income is zero or negative.",
                [("cfo", 0), ("net_income", 0)],
                accruals.cash_conversion,
            )
        },
    }


SCORES = _build_scores()
SCORE_LABELS = {
    "m_score": labels.COLUMN_LABELS["m_score"],
    "z_score": labels.COLUMN_LABELS["z_score"],
    "f_score": labels.COLUMN_LABELS["f_score"],
    "accruals_ratio": labels.COLUMN_LABELS["accruals_ratio"],
    "cash_conversion": labels.COLUMN_LABELS["cash_conversion"],
}


# ---------------------------------------------------------------------------
# Looking up the facts behind each input
# ---------------------------------------------------------------------------
def input_label(column):
    """Return the plain name for a financials column."""
    if column == piotroski.PRIOR_SHARES:
        return PRIOR_SHARES_LABEL
    return labels.LINE_ITEM_LABELS.get(
        column, COMPONENT_LABELS.get(column, column)
    )


def value_text(value, column):
    """Return the exact value: "$1,234,000" or "15,000,000 shares".

    Whole numbers, not "$1.2M", so the analyst can tie the figure to
    the 10-K by eye.
    """
    if labels.is_missing(value):
        return labels.NOT_AVAILABLE
    if column in ("shares_outstanding", piotroski.PRIOR_SHARES):
        return f"{value:,.0f} shares"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def period_text(fact):
    """Return "Jan 1, 2023 to Dec 31, 2023" or "at Dec 31, 2023"."""
    end = f"{fact['period_end']:%b} {fact['period_end'].day}, " + (
        f"{fact['period_end']:%Y}"
    )
    if pd.isna(fact["period_start"]):
        return f"at {end}"
    start = fact["period_start"]
    return f"{start:%b} {start.day}, {start:%Y} to {end}"


def matching_fact(facts_df, line_item, value, period_end):
    """Return the original facts_long row behind one financials value.

    Mirrors how Phase 1 built financials_annual
    (financials.match_originals_to_years): an ORIGINAL fact for the line
    item, dated within financials.REPORT_DATE_TOLERANCE of the year's
    period end, whose value equals the value used. When several qualify
    (the same value tagged with two start dates), the nearest date and
    then the earliest filing win. Returns None if nothing matches, so
    the panel can say so instead of guessing.
    """
    candidates = facts_df[
        facts_df["is_original"]
        & (facts_df["line_item"] == line_item)
        & (
            (facts_df["period_end"] - period_end).abs()
            <= financials.REPORT_DATE_TOLERANCE
        )
    ]
    candidates = candidates[
        np.isclose(
            candidates["value"], value, rtol=VALUE_MATCH_TOLERANCE, atol=0
        )
    ]
    if candidates.empty:
        return None
    gap = (candidates["period_end"] - period_end).abs()
    return (
        candidates.assign(gap=gap).sort_values(["gap", "filed_date"]).iloc[0]
    )


def later_restatement(facts_df, fact):
    """Return text on the latest restated value of a fact, or "".

    A later 10-K can report the same period with a different value. The
    score keeps the original (what investors saw at the time, CLAUDE.md
    section 4); the restatement is shown so it is never hidden.
    """
    later = facts_df[
        ~facts_df["is_original"]
        & (facts_df["line_item"] == fact["line_item"])
        & (facts_df["period_end"] == fact["period_end"])
    ]
    later = later[
        ~np.isclose(
            later["value"], fact["value"], rtol=VALUE_MATCH_TOLERANCE, atol=0
        )
    ]
    if later.empty:
        return ""
    latest = later.sort_values("filed_date").iloc[-1]
    return (
        f"Restated to {value_text(latest['value'], fact['line_item'])} "
        f"in the 10-K filed {latest['filed_date']:%Y-%m-%d}"
    )


def _row(label, fiscal_year, column, value, status, fact=None, later=""):
    """Return one trace table row as a dict."""
    has_fact = fact is not None
    return {
        "Input": label,
        "Fiscal year": f"FY{fiscal_year}",
        "Value used": value_text(value, column),
        "Source": status,
        "XBRL tag": fact["xbrl_tag"] if has_fact else "",
        "Period": period_text(fact) if has_fact else "",
        "10-K filed": f"{fact['filed_date']:%Y-%m-%d}" if has_fact else "",
        "Accession": fact["accession"] if has_fact else "",
        "Filing": fact["filing_url"] if has_fact else None,
        "Later filings": later,
    }


def _reported_row(label, column, year, value, period_end, facts_df):
    """Return the row for a reported value, matched to its filing fact."""
    fact = matching_fact(facts_df, column, value, period_end)
    if fact is None:
        return _row(label, year, column, value, NOT_MATCHED)
    return _row(
        label,
        year,
        column,
        value,
        REPORTED,
        fact,
        later_restatement(facts_df, fact),
    )


def _prior_shares_row(fiscal_year, financials_df, facts_df):
    """Return the row for F-Score test 7's prior-year share count.

    Read like piotroski.prior_shares_same_filing: the share count dated
    at the t-1 balance-sheet date, in year t's own 10-K (matched on that
    10-K's accession number).
    """
    year_t = financials_df[financials_df["fiscal_year"] == fiscal_year]
    prior = financials_df[financials_df["fiscal_year"] == fiscal_year - 1]
    if year_t.empty or prior.empty:
        return _row(
            PRIOR_SHARES_LABEL,
            fiscal_year - 1,
            piotroski.PRIOR_SHARES,
            np.nan,
            NO_YEAR,
        )
    facts = facts_df[
        (facts_df["line_item"] == "shares_outstanding")
        & (facts_df["accession"] == year_t.iloc[0]["accession"])
        & (facts_df["period_end"] == prior.iloc[0]["period_end"])
    ]
    # Two different values in one filing make the input ambiguous;
    # Phase 2 then leaves it blank, so the trace does too.
    if facts.empty or facts["value"].nunique() > 1:
        return _row(
            PRIOR_SHARES_LABEL,
            fiscal_year - 1,
            piotroski.PRIOR_SHARES,
            np.nan,
            NOT_REPORTED,
        )
    fact = facts.iloc[0]
    return _row(
        PRIOR_SHARES_LABEL,
        fiscal_year - 1,
        piotroski.PRIOR_SHARES,
        fact["value"],
        REPORTED,
        fact,
    )


def trace_inputs(inputs, fiscal_year, financials_df, facts_df):
    """Return (table, notes) tracing each input to its SEC filing.

    inputs: (financials column, years back) pairs from a Part.
    financials_df and facts_df: ONE company's rows of financials_annual
    and facts_long. notes: plain-English sentences on any calculated
    values, naming the Phase 1 function that calculated them.
    """
    rows, notes = [], []
    for column, years_back in inputs:
        if column == piotroski.PRIOR_SHARES:
            rows.append(
                _prior_shares_row(fiscal_year, financials_df, facts_df)
            )
            continue
        year = fiscal_year - years_back
        label = input_label(column)
        year_rows = financials_df[financials_df["fiscal_year"] == year]
        if year_rows.empty:
            rows.append(_row(label, year, column, np.nan, NO_YEAR))
            continue
        year_row = year_rows.iloc[0]
        value = year_row[column]
        if labels.is_missing(value):
            rows.append(_row(label, year, column, value, NOT_REPORTED))
            continue
        # derived_items is null when every value was reported; "or" on
        # pandas NA raises, so test for missing explicitly.
        derived_text = year_row["derived_items"]
        derived = (
            []
            if labels.is_missing(derived_text)
            else derived_text.split(derived_items.SEPARATOR)
        )
        if column not in derived:
            rows.append(
                _reported_row(
                    label,
                    column,
                    year,
                    value,
                    year_row["period_end"],
                    facts_df,
                )
            )
            continue
        # A calculated value: show it, then every reported part of it.
        rows.append(_row(label, year, column, value, CALCULATED))
        function = derived_items.DERIVATIONS[column]
        notes.append(
            f"FY{year} {label.lower()}: {DERIVATION_NOTES[column]} "
            f"({function_name(function)})."
        )
        for part in DERIVED_COMPONENTS[column]:
            part_value = year_row[part]
            if labels.is_missing(part_value):
                continue
            part_row = _reported_row(
                f"↳ {input_label(part)}",
                part,
                year,
                part_value,
                year_row["period_end"],
                facts_df,
            )
            if part_row["Source"] == REPORTED:
                part_row["Source"] = COMPONENT
            rows.append(part_row)
    return pd.DataFrame(rows), notes


def stored_result_text(row, part):
    """Return the stored result of a part in words, e.g. "1.114"."""
    value = row[part.stored_column]
    if labels.is_missing(value):
        return labels.NOT_AVAILABLE
    if part.stored_column in labels.F_SIGNAL_LABELS:
        return labels.SIGNAL_RESULT_LABELS[bool(value)]
    if part.stored_column == "f_score":
        return f"{int(value)} of {screening.F_SCORE_RANGE[1]}"
    return f"{value:.3f}"
