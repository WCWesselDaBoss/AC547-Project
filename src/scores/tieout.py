"""Build verification/tieout.xlsx: Excel recomputes every score by hand.

For each chosen company-year, one sheet holds:
- the raw inputs for t-2, t-1 and t exactly as stored in
  financials_annual (blue), each traced to its XBRL tag and 10-K through
  facts_long, with a yellow column to type the figure read from the 10-K;
- Excel formulas (black) recomputing every M-Score index, Z'' ratio,
  F-Score signal, accruals ratio and cash conversion from those inputs;
- the Python result from scores.parquet next to each formula, and a
  match check.

The Excel formulas are written independently from the Python code (same
section 5 formulas, different implementation), so agreement is evidence
the Python is right, not just that it agrees with itself.

Run with:
    python -m src.scores.tieout            # uses data/processed/
    python -m src.scores.tieout --sample   # uses data/sample/
Then recalculate the formulas (open in Excel, or the xlsx skill's
recalc.py) before reading the match columns.
"""

import argparse

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config
from src.pipeline.tieout import trace_value

TIEOUT_XLSX = config.PROJECT_ROOT / "verification" / "tieout.xlsx"

# (cik, fiscal_year, sheet name, why it was chosen). Add the case-study
# company here once data/case_studies.csv exists (Phase 3 owns it).
TIEOUT_CASES = [
    (320193, 2024, "AAPL FY2024", "Inputs hand-verified in Phase 1"),
    (320193, 2020, "AAPL FY2020", "4-for-1 stock split in Aug 2020"),
    (2488, 2018, "AMD FY2018", "Flagged by the M-Score"),
    (6281, 2017, "ADI FY2017", "Flagged; long-term debt untagged"),
]

INPUT_ITEMS = [
    "revenue",
    "cost_of_revenue",
    "sga",
    "depreciation",
    "operating_income",
    "income_continuing_ops",
    "net_income",
    "cfo",
    "receivables",
    "current_assets",
    "ppe_net",
    "total_assets",
    "current_liabilities",
    "long_term_debt",
    "total_liabilities",
    "retained_earnings",
    "stockholders_equity",
    "shares_outstanding",
]
PRIOR_SHARES_ROW_LABEL = "shares t-1 as reported in year t's 10-K"

# Fonts and fills (financial-model colour convention).
FONT = "Arial"
BLUE = Font(name=FONT, color="0000FF")  # hard-coded input
BLACK = Font(name=FONT)  # formula
GREEN = Font(name=FONT, color="008000")  # link to another sheet
BOLD = Font(name=FONT, bold=True)
TITLE = Font(name=FONT, bold=True, size=13)
YELLOW = PatternFill("solid", start_color="FFFF00")
GREY = PatternFill("solid", start_color="D9D9D9")
WRAP = Alignment(wrap_text=True, vertical="top")

# Layout of each company sheet.
INPUT_HEADER_ROW = 8
FIRST_INPUT_ROW = INPUT_HEADER_ROW + 1
LAG_COLUMNS = {2: "B", 1: "C", 0: "D"}  # t-2, t-1, t
TOLERANCE_CELL = "B5"  # match tolerance for numbers
MILLIONS_TOLERANCE_CELL = "B6"  # $mm tolerance for the 10-K check


def input_rows():
    """Return {item: row number} for the input block."""
    rows = {item: FIRST_INPUT_ROW + i for i, item in enumerate(INPUT_ITEMS)}
    rows["prior_shares"] = FIRST_INPUT_ROW + len(INPUT_ITEMS)
    return rows


ROWS = input_rows()


def ref(item, years_back):
    """Return the absolute cell holding an input, e.g. '$D$9'."""
    return f"${LAG_COLUMNS[years_back]}${ROWS[item]}"


def guarded(expression, items):
    """Wrap a formula so it is blank unless every input cell has a value.

    Excel treats an empty cell as 0, which would silently turn a missing
    input into a number (CLAUDE.md section 2 forbids that). The Python
    code returns NaN in the same cases.
    """
    cells = [ref(item, lag) for item, lag in items]
    checks = ",".join(cells)
    return f'=IF(COUNT({checks})<{len(cells)},"",{expression})'


def coefficient(name):
    """Return the Coefficients-sheet cell for a coefficient name."""
    return f"Coefficients!$B${COEFFICIENT_ROWS[name]}"


COEFFICIENT_ROWS = {
    name: 2 + i
    for i, name in enumerate(
        ["intercept"]
        + list(config.BENEISH_COEFFICIENTS)
        + ["m_cutoff"]
        + list(config.ALTMAN_Z2_COEFFICIENTS)
        + ["z_safe_above", "z_distress_below"]
    )
}


def metric_rows():
    """Return [(label, kind, excel_formula, python_column, words)].

    kind is 'number', 'bool' or 'text', which sets the match test.
    Formulas refer to the input block by absolute address.
    """
    r = ref
    gm_t = f"(({r('revenue', 0)}-{r('cost_of_revenue', 0)})/{r('revenue', 0)})"
    gm_1 = f"(({r('revenue', 1)}-{r('cost_of_revenue', 1)})/{r('revenue', 1)})"
    roa_t = f"({r('net_income', 0)}/{r('total_assets', 1)})"
    roa_1 = f"({r('net_income', 1)}/{r('total_assets', 2)})"
    ltd_missing = (
        f'OR({r("long_term_debt", 0)}="",{r("long_term_debt", 1)}="")'
    )
    sga_missing = f'OR({r("sga", 0)}="",{r("sga", 1)}="")'
    both = (0, 1)

    def items(names, lags=both):
        return [(name, lag) for name in names for lag in lags]

    rows = [
        (
            "DSRI",
            "number",
            guarded(
                f"({r('receivables', 0)}/{r('revenue', 0)})"
                f"/({r('receivables', 1)}/{r('revenue', 1)})",
                items(["receivables", "revenue"]),
            ),
            "dsri",
            "(Rec/Sales)t / (Rec/Sales)t-1",
        ),
        (
            "GMI",
            "number",
            guarded(f"{gm_1}/{gm_t}", items(["revenue", "cost_of_revenue"])),
            "gmi",
            "Gross margin t-1 / gross margin t",
        ),
        (
            "AQI",
            "number",
            guarded(
                f"(1-({r('current_assets', 0)}+{r('ppe_net', 0)})"
                f"/{r('total_assets', 0)})"
                f"/(1-({r('current_assets', 1)}+{r('ppe_net', 1)})"
                f"/{r('total_assets', 1)})",
                items(["current_assets", "ppe_net", "total_assets"]),
            ),
            "aqi",
            "[1-(CA+PPE)/TA]t / same t-1",
        ),
        (
            "SGI",
            "number",
            guarded(
                f"{r('revenue', 0)}/{r('revenue', 1)}", items(["revenue"])
            ),
            "sgi",
            "Sales t / Sales t-1",
        ),
        (
            "DEPI",
            "number",
            guarded(
                f"({r('depreciation', 1)}/({r('depreciation', 1)}"
                f"+{r('ppe_net', 1)}))/({r('depreciation', 0)}"
                f"/({r('depreciation', 0)}+{r('ppe_net', 0)}))",
                items(["depreciation", "ppe_net"]),
            ),
            "depi",
            "[Dep/(Dep+PPE)]t-1 / same t",
        ),
        (
            "SGAI",
            "number",
            f"=IF({sga_missing},1,({r('sga', 0)}/{r('revenue', 0)})"
            f"/({r('sga', 1)}/{r('revenue', 1)}))",
            "sgai",
            "(SGA/Sales)t / (SGA/Sales)t-1; 1 if SGA missing",
        ),
        (
            "TATA",
            "number",
            guarded(
                f"({r('income_continuing_ops', 0)}-{r('cfo', 0)})"
                f"/{r('total_assets', 0)}",
                items(["income_continuing_ops", "cfo", "total_assets"], (0,)),
            ),
            "tata",
            "(Income cont. ops - CFO)t / TA t",
        ),
        (
            "LVGI",
            "number",
            f"=IF({ltd_missing},1,(({r('current_liabilities', 0)}"
            f"+{r('long_term_debt', 0)})/{r('total_assets', 0)})"
            f"/(({r('current_liabilities', 1)}+{r('long_term_debt', 1)})"
            f"/{r('total_assets', 1)}))",
            "lvgi",
            "[(CL+LTD)/TA]t / same t-1; 1 if LTD missing",
        ),
    ]
    index_cells = {
        name: f"$B${CALC_FIRST_ROW + i}"
        for i, name in enumerate(config.BENEISH_COEFFICIENTS)
    }
    m_terms = "+".join(
        f"{coefficient(name)}*{cell}" for name, cell in index_cells.items()
    )
    rows += [
        (
            "M-Score",
            "number",
            f"={coefficient('intercept')}+{m_terms}",
            "m_score",
            "-4.84 + sum of coefficient x index",
        ),
        (
            "M flag (M > cutoff)",
            "bool",
            f"=$B${CALC_FIRST_ROW + 8}>{coefficient('m_cutoff')}",
            "m_flag",
            "TRUE = likely manipulator at -1.78",
        ),
        (
            "Z'' X1",
            "number",
            f"=({r('current_assets', 0)}-{r('current_liabilities', 0)})"
            f"/{r('total_assets', 0)}",
            "z_x1",
            "(CA - CL) / TA",
        ),
        (
            "Z'' X2",
            "number",
            f"={r('retained_earnings', 0)}/{r('total_assets', 0)}",
            "z_x2",
            "Retained earnings / TA",
        ),
        (
            "Z'' X3",
            "number",
            f"={r('operating_income', 0)}/{r('total_assets', 0)}",
            "z_x3",
            "Operating income / TA",
        ),
        (
            "Z'' X4",
            "number",
            f"={r('stockholders_equity', 0)}/{r('total_liabilities', 0)}",
            "z_x4",
            "Equity / total liabilities",
        ),
    ]
    x_cells = [f"$B${CALC_FIRST_ROW + 10 + i}" for i in range(4)]
    z_terms = "+".join(
        f"{coefficient(name)}*{cell}"
        for name, cell in zip(config.ALTMAN_Z2_COEFFICIENTS, x_cells)
    )
    z_cell = f"$B${CALC_FIRST_ROW + 14}"
    rows += [
        ("Z''-Score", "number", f"={z_terms}", "z_score", "6.56X1+...+1.05X4"),
        (
            "Z'' zone",
            "text",
            f'=IF({z_cell}>{coefficient("z_safe_above")},"safe",'
            f'IF({z_cell}>={coefficient("z_distress_below")},"grey",'
            f'"distress"))',
            "z_zone",
            "> 2.60 safe; < 1.10 distress",
        ),
        (
            "F1 ROA > 0",
            "bool",
            f"={roa_t}>0",
            "f_roa_positive",
            "NI t / TA t-1 > 0",
        ),
        ("F2 CFO > 0", "bool", f"={r('cfo', 0)}>0", "f_cfo_positive", ""),
        (
            "F3 ROA up",
            "bool",
            f"={roa_t}>{roa_1}",
            "f_roa_improved",
            "NI t/TA t-1 > NI t-1/TA t-2",
        ),
        (
            "F4 CFO > ROA",
            "bool",
            f"={r('cfo', 0)}/{r('total_assets', 1)}>{roa_t}",
            "f_cfo_exceeds_roa",
            "CFO t/TA t-1 > ROA t",
        ),
        (
            "F5 leverage down",
            "bool",
            f'=IF({ltd_missing},"NA",'
            f"{r('long_term_debt', 0)}/(({r('total_assets', 0)}"
            f"+{r('total_assets', 1)})/2)<{r('long_term_debt', 1)}"
            f"/(({r('total_assets', 1)}+{r('total_assets', 2)})/2))",
            "f_leverage_down",
            "LTD/avg TA lower; NA (0 pts) if LTD missing",
        ),
        (
            "F6 current ratio up",
            "bool",
            f"={r('current_assets', 0)}/{r('current_liabilities', 0)}"
            f">{r('current_assets', 1)}/{r('current_liabilities', 1)}",
            "f_current_ratio_up",
            "CA/CL t > CA/CL t-1",
        ),
        (
            "F7 no new shares",
            "bool",
            f"={r('shares_outstanding', 0)}<=$D${ROWS['prior_shares']}",
            "f_no_new_shares",
            "Shares t <= t-1 shares in the same 10-K",
        ),
        (
            "F8 gross margin up",
            "bool",
            f"={gm_t}>{gm_1}",
            "f_gross_margin_up",
            "",
        ),
        (
            "F9 asset turnover up",
            "bool",
            f"={r('revenue', 0)}/{r('total_assets', 1)}"
            f">{r('revenue', 1)}/{r('total_assets', 2)}",
            "f_asset_turnover_up",
            "Sales t/TA t-1 > Sales t-1/TA t-2",
        ),
    ]
    first_signal = CALC_FIRST_ROW + 16
    signal_range = f"$B${first_signal}:$B${first_signal + 8}"
    rows += [
        (
            "F-Score",
            "number",
            f"=COUNTIF({signal_range},TRUE)",
            "f_score",
            "Count of TRUE signals (NA counts 0)",
        ),
        (
            "Accruals ratio",
            "number",
            f"=({r('net_income', 0)}-{r('cfo', 0)})"
            f"/(({r('total_assets', 0)}+{r('total_assets', 1)})/2)",
            "accruals_ratio",
            "(NI - CFO) / average TA",
        ),
        (
            "Cash conversion",
            "number",
            f'=IF({r("net_income", 0)}>0,{r("cfo", 0)}/{r("net_income", 0)},"")',
            "cash_conversion",
            "CFO / NI; blank if NI <= 0",
        ),
    ]
    return rows


CALC_HEADER_ROW = FIRST_INPUT_ROW + len(INPUT_ITEMS) + 3
CALC_FIRST_ROW = CALC_HEADER_ROW + 1


def python_value(value):
    """Return a scores value in a form Excel can compare (blank for NA).

    Booleans (numpy or Python) become TRUE/FALSE, zones stay text, and
    numbers become floats.
    """
    if pd.isna(value):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return float(value)


def match_formula(kind, row):
    """Return the Match formula for a calculation row."""
    excel, python = f"B{row}", f"C{row}"
    if kind == "number":
        return (
            f'=IF(AND({excel}="",{python}=""),"OK (both blank)",'
            f'IF(OR({excel}="",{python}=""),"DIFF",'
            f"IF(ABS({excel}-{python})<=${TOLERANCE_CELL[0]}"
            f'${TOLERANCE_CELL[1:]},"OK","DIFF")))'
        )
    # Booleans and text: Python NA is written "NA" to match Excel's "NA".
    return f'=IF({excel}={python},"OK","DIFF")'


def write_company_sheet(
    workbook,
    case,
    financials_df,
    facts_long_df,
    scores_df,
    prior_shares,
    hand_checked,
):
    """Add one company-year sheet to the workbook."""
    cik, fiscal_year, sheet_name, reason = case
    sheet = workbook.create_sheet(sheet_name)
    years = {
        lag: financials_df[
            (financials_df["cik"] == cik)
            & (financials_df["fiscal_year"] == fiscal_year - lag)
        ]
        for lag in (0, 1, 2)
    }
    current = years[0].iloc[0]
    score = scores_df[
        (scores_df["cik"] == cik) & (scores_df["fiscal_year"] == fiscal_year)
    ].iloc[0]

    sheet["A1"] = f"{sheet_name}: score tie-out (CIK {cik})"
    sheet["A1"].font = TITLE
    sheet["A2"] = f"Why chosen: {reason}"
    sheet["A3"] = (
        f"Year t = FY{fiscal_year}, period end "
        f"{current['period_end'].date()}, 10-K accession "
        f"{current['accession']}"
    )
    sheet["A4"] = "Year-t 10-K on EDGAR:"
    trace = trace_value(facts_long_df, cik, "revenue", current["period_end"])
    if trace is not None:
        sheet["B4"] = trace["filing_url"]
        sheet["B4"].hyperlink = trace["filing_url"]
    sheet["A5"] = "Match tolerance (absolute)"
    sheet[TOLERANCE_CELL] = 1e-9
    sheet[TOLERANCE_CELL].font = BLUE
    sheet[TOLERANCE_CELL].comment = Comment(
        "Python and Excel use the same double-precision arithmetic; 1e-9 "
        "only absorbs differences in the order of operations.",
        "tieout",
    )
    sheet["A6"] = "10-K check tolerance ($mm)"
    sheet[MILLIONS_TOLERANCE_CELL] = 0.5
    sheet[MILLIONS_TOLERANCE_CELL].font = BLUE
    sheet[MILLIONS_TOLERANCE_CELL].comment = Comment(
        "10-Ks usually print $ millions rounded to 1 decimal or whole "
        "millions, so a gap under $0.5mm is rounding.",
        "tieout",
    )
    for cell in ["A2", "A3", "A4", "A5", "A6"]:
        sheet[cell].font = BLACK

    headers = [
        "Line item (financials_annual)",
        f"t-2 (FY{fiscal_year - 2})",
        f"t-1 (FY{fiscal_year - 1})",
        f"t (FY{fiscal_year})",
        "XBRL tag (year t)",
        "Derived? (year t)",
        "10-K value, year t ($mm) - FILL IN",
        "Ties to 10-K?",
        "Where in 10-K / notes",
    ]
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(INPUT_HEADER_ROW, column, header)
        cell.font = BOLD
        cell.fill = GREY
        cell.alignment = WRAP

    # derived_items is NA when every value was reported (section 4).
    derived = (
        ""
        if pd.isna(current["derived_items"])
        else str(current["derived_items"])
    )
    for item in INPUT_ITEMS:
        row = ROWS[item]
        sheet.cell(row, 1, item).font = BLACK
        for lag, column in LAG_COLUMNS.items():
            if years[lag].empty:
                continue
            value = years[lag].iloc[0][item]
            if pd.notna(value):
                cell = sheet[f"{column}{row}"]
                cell.value = float(value)
                cell.font = BLUE
                cell.number_format = "#,##0"
        fact = trace_value(facts_long_df, cik, item, current["period_end"])
        sheet.cell(row, 5, None if fact is None else fact["xbrl_tag"])
        sheet.cell(row, 6, "derived" if item in derived.split("; ") else "")
        check_cell = sheet.cell(row, 7)
        check_cell.fill = YELLOW
        check_cell.font = BLUE
        check_cell.number_format = "#,##0.0"
        note_cell = sheet.cell(row, 9)
        if (cik, fiscal_year, item) in hand_checked:
            check_cell.value, note_cell.value = hand_checked[
                (cik, fiscal_year, item)
            ]
        unit = 1 if item == "shares_outstanding" else 1e6
        sheet.cell(
            row,
            8,
            f'=IF(G{row}="","",IF(D{row}="","10-K has it; we do not",'
            f"IF(ABS(D{row}/{unit:.0f}-G{row})<="
            f"${MILLIONS_TOLERANCE_CELL[0]}${MILLIONS_TOLERANCE_CELL[1:]},"
            f'"OK","CHECK")))',
        ).font = BLACK
        if item == "shares_outstanding":
            check_cell.number_format = "#,##0"
            sheet.cell(row, 7).comment = Comment(
                "Shares: type the full count, not millions.", "tieout"
            )

    shares_row = ROWS["prior_shares"]
    sheet.cell(shares_row, 1, PRIOR_SHARES_ROW_LABEL).font = BLACK
    if pd.notna(prior_shares):
        cell = sheet[f"D{shares_row}"]
        cell.value = float(prior_shares)
        cell.font = BLUE
        cell.number_format = "#,##0"
    sheet.cell(shares_row, 5, "CommonStockSharesOutstanding (comparative)")
    sheet.cell(
        shares_row,
        9,
        "Used only by F-Score signal 7 (section 4: split-safe comparison)",
    )

    calc_headers = [
        "Metric",
        "Excel (formula)",
        "Python (scores.parquet)",
        "Difference",
        "Match?",
        "Formula in words",
    ]
    for column, header in enumerate(calc_headers, start=1):
        cell = sheet.cell(CALC_HEADER_ROW, column, header)
        cell.font = BOLD
        cell.fill = GREY
    for offset, (label, kind, formula, column_name, words) in enumerate(
        metric_rows()
    ):
        row = CALC_FIRST_ROW + offset
        sheet.cell(row, 1, label).font = BLACK
        excel_cell = sheet.cell(row, 2, formula)
        excel_cell.font = GREEN if "Coefficients!" in formula else BLACK
        value = python_value(score[column_name])
        if value == "" and kind in ("bool", "text"):
            value = "NA"
        python_cell = sheet.cell(row, 3, value)
        python_cell.font = BLUE
        if kind == "number":
            excel_cell.number_format = "0.000000"
            python_cell.number_format = "0.000000"
            sheet.cell(
                row,
                4,
                f'=IF(OR(B{row}="",C{row}=""),"",B{row}-C{row})',
            ).number_format = "0.0E+00"
        sheet.cell(row, 5, match_formula(kind, row)).font = BLACK
        sheet.cell(row, 6, words).font = BLACK

    last_calc = CALC_FIRST_ROW + len(metric_rows()) - 1
    summary_row = last_calc + 2
    sheet.cell(summary_row, 1, "Scores that differ").font = BOLD
    sheet.cell(
        summary_row,
        2,
        f'=COUNTIF(E{CALC_FIRST_ROW}:E{last_calc},"DIFF")',
    ).font = BOLD
    sheet.cell(summary_row + 1, 1, "missing_inputs (Python)").font = BLACK
    sheet.cell(
        summary_row + 1,
        2,
        "" if pd.isna(score["missing_inputs"]) else score["missing_inputs"],
    )

    widths = [38, 20, 20, 34, 18, 16, 22, 22, 50]
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = f"B{FIRST_INPUT_ROW}"
    return sheet_name, summary_row


def write_coefficients_sheet(workbook):
    """Add the Coefficients sheet (values from config.py, with sources)."""
    sheet = workbook.create_sheet("Coefficients")
    sheet.append(["Constant", "Value", "Source (see docs/methodology.md)"])
    for cell in sheet[1]:
        cell.font = BOLD
        cell.fill = GREY
    beneish = "Beneish (1999), FAJ 55(5), 8-variable model"
    altman = "Altman Z'' (non-manufacturers); verify edition"
    values = (
        [("intercept", config.BENEISH_INTERCEPT, beneish)]
        + [
            (name, value, beneish)
            for name, value in config.BENEISH_COEFFICIENTS.items()
        ]
        + [("m_cutoff", config.BENEISH_FLAG_CUTOFF, beneish)]
        + [
            (name, value, altman)
            for name, value in config.ALTMAN_Z2_COEFFICIENTS.items()
        ]
        + [
            ("z_safe_above", config.ALTMAN_Z2_SAFE_ABOVE, altman),
            ("z_distress_below", config.ALTMAN_Z2_DISTRESS_BELOW, altman),
        ]
    )
    for name, value, source in values:
        assert sheet.max_row + 1 == COEFFICIENT_ROWS[name]
        sheet.append([name, value, source])
        sheet.cell(sheet.max_row, 2).font = BLUE
    sheet.column_dimensions["A"].width = 18
    sheet.column_dimensions["C"].width = 50


def write_readme_sheet(workbook, summaries):
    """Add the first sheet: purpose, legend and a summary of all checks."""
    sheet = workbook.active
    sheet.title = "README"
    lines = [
        ("Earnings Quality Radar: Phase 2 score tie-out", TITLE),
        (
            "Each company sheet recomputes every score with Excel formulas "
            "from the raw inputs and compares it with the Python output.",
            BLACK,
        ),
        ("Built by: python -m src.scores.tieout", BLACK),
        ("Differences are explained in verification/tieout_notes.md.", BLACK),
        ("", BLACK),
        ("Legend", BOLD),
        ("Blue text: hard-coded value copied from our data", BLUE),
        ("Black text: Excel formula", BLACK),
        ("Green text: formula using the Coefficients sheet", GREEN),
        ("Yellow cells: FILL IN by hand from the 10-K ($ millions)", BLACK),
        ("", BLACK),
        ("Summary", BOLD),
    ]
    for text, font in lines:
        sheet.append([text])
        sheet.cell(sheet.max_row, 1).font = font
    sheet.cell(10, 1).fill = YELLOW
    sheet.append(["Sheet", "Scores that differ (should be 0)"])
    for cell in sheet[sheet.max_row]:
        cell.font = BOLD
        cell.fill = GREY
    for sheet_name, summary_row in summaries:
        sheet.append([sheet_name, f"='{sheet_name}'!B{summary_row}"])
        sheet.cell(sheet.max_row, 2).font = GREEN
    sheet.column_dimensions["A"].width = 70
    sheet.column_dimensions["B"].width = 32


def hand_checked_values():
    """Return Phase 1's hand-verified 10-K figures, keyed for lookup.

    These four Apple FY2024 values were read from the 10-K by a team
    member (verification/phase1_tieout.csv), so they double as the
    example rows showing how to fill in the yellow column.
    """
    path = config.PROJECT_ROOT / "verification" / "phase1_tieout.csv"
    if not path.exists():
        return {}
    phase1_df = pd.read_csv(path).dropna(subset=["ten_k_value_millions"])
    return {
        (row.cik, row.fiscal_year, row.line_item): (
            float(row.ten_k_value_millions),
            f"{row.ten_k_page_or_statement}. {row.notes}",
        )
        for row in phase1_df.itertuples()
    }


def build_workbook(source_dir, cases=TIEOUT_CASES, output=TIEOUT_XLSX):
    """Write the tie-out workbook from the tables in source_dir."""
    financials_df = pd.read_parquet(source_dir / "financials_annual.parquet")
    facts_long_df = pd.read_parquet(source_dir / "facts_long.parquet")
    scores_path = (
        config.SCORES_PATH
        if source_dir == config.PROCESSED_DIR
        else source_dir / "scores.parquet"
    )
    scores_df = pd.read_parquet(scores_path)

    # Reuse the exact Python lookup for signal 7's same-filing count, so
    # the sheet shows the number the score used (and its source rule).
    from src.scores import piotroski

    frame = piotroski.prepare_frame(financials_df, facts_long_df)
    hand_checked = hand_checked_values()

    workbook = Workbook()
    summaries = []
    for case in cases:
        cik, fiscal_year = case[0], case[1]
        prior_shares = frame.loc[
            (frame["cik"] == cik) & (frame["fiscal_year"] == fiscal_year),
            piotroski.PRIOR_SHARES,
        ].iloc[0]
        summaries.append(
            write_company_sheet(
                workbook,
                case,
                financials_df,
                facts_long_df,
                scores_df,
                prior_shares,
                hand_checked,
            )
        )
    write_coefficients_sheet(workbook)
    write_readme_sheet(workbook, summaries)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    print(f"Wrote {output}")


def main(argv=None):
    """Build verification/tieout.xlsx."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args(argv)
    build_workbook(config.SAMPLE_DIR if args.sample else config.PROCESSED_DIR)


if __name__ == "__main__":
    main()
