"""Build verification/tieout_quarterly.xlsx: Excel re-checks quarterly
(TTM) scores and the TTM inputs behind them.

For each chosen company-quarter the workbook has two sheets:

1. "<case>": the annual tie-out sheet (src/scores/tieout.py,
   write_company_sheet, reused UNCHANGED). Excel formulas recompute every
   M-Score index, Z'' ratio, F-Score signal, accruals ratio and cash
   conversion from the TTM inputs for t, t-1 and t-2 (the same quarter
   one and two years earlier) and compare them with scores_quarterly.
   A few labels are then relabeled for the quarterly basis.
2. "<case> TTM": every TTM input of quarters t and t-1, rebuilt from its
   source filings in ttm_sources. Each source value is typed in (blue);
   Excel adds each quarter's rows (a year-to-date difference is a + row
   and a - row) and then the four quarters, and compares the total with
   financials_ttm. Each row carries its accession and EDGAR link, so
   any figure can be opened in the filing.

Run:  python -m src.scores.tieout_quarterly
Then recalculate the formulas (open in Excel) before reading the match
columns; verification/tieout_quarterly_notes.md has the results.
"""

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

import config
from src.pipeline import quarterly, ttm
from src.scores import piotroski
from src.scores import quarterly_scores as qs
from src.scores import tieout

TIEOUT_QUARTERLY_XLSX = (
    config.PROJECT_ROOT / "verification" / "tieout_quarterly.xlsx"
)

# (cik, fiscal_year, fiscal_quarter, sheet name, why chosen). Sheet names
# stay short: Excel allows 31 characters and " TTM" is added.
TIEOUT_QUARTERLY_CASES = [
    (320193, 2024, 3, "AAPL FY24 Q3", "Mid-year quarter; option C shares"),
    (
        320193,
        2024,
        4,
        "AAPL FY24 Q4",
        "Q4 = annual rule; compare tieout.xlsx AAPL FY2024",
    ),
    (2488, 2019, 1, "AMD FY19 Q1", "Flagged by the quarterly M-Score"),
    (909832, 2024, 2, "COST FY24 Q2", "12/12/12/16-week calendar"),
    (
        1158449,
        2025,
        2,
        "AAP FY25 Q2",
        "16/12/12/12-week calendar; after a discontinued operation",
    ),
]

TTM_TOLERANCE_CELL = "B5"
LINK = Font(name=tieout.FONT, color="0563C1", underline="single")


# ---------------------------------------------------------------------------
# Score sheet (annual writer, relabeled)
# ---------------------------------------------------------------------------
def guard_m_score(sheet):
    """Make the M-Score and flag blank / "NA" when an index is blank.

    The annual writer guards every formula against blank inputs except
    these two, so a company without an M-Score (Costco tags no
    receivables, so DSRI is blank) shows #VALUE! instead of "OK (both
    blank)". The annual cases all have M-Scores, so it never shows
    there, and tieout.py is not changed (quarterly work changes no
    existing function). Here the same guard is applied to the two cells:
    the formulas are otherwise identical.
    """
    first_index = tieout.CALC_FIRST_ROW
    m_row, flag_row = first_index + 8, first_index + 9
    assert sheet.cell(m_row, 1).value == "M-Score"
    assert sheet.cell(flag_row, 1).value == "M flag (M > cutoff)"
    indexes = f"$B${first_index}:$B${first_index + 7}"
    m_formula = sheet.cell(m_row, 2).value.removeprefix("=")
    sheet.cell(m_row, 2).value = f'=IF(COUNT({indexes})<8,"",{m_formula})'
    flag_formula = sheet.cell(flag_row, 2).value.removeprefix("=")
    sheet.cell(flag_row, 2).value = f'=IF($B${m_row}="","NA",{flag_formula})'


def relabel_score_sheet(sheet, case, ttm_row):
    """Relabel the annual sheet's wording for a TTM quarter. Only text
    labels change; no number or formula is touched."""
    cik, year, quarter, name, _ = case
    sheet["A1"] = f"{name}: quarterly (TTM) score tie-out (CIK {cik})"
    sheet["A3"] = (
        f"Quarter t = FY{year} Q{quarter}, quarter end "
        f"{ttm_row['period_end'].date()}, available "
        f"{ttm_row['available_date'].date()}; t-1 and t-2 are Q{quarter} "
        "one and two years earlier. Inputs are TTM sums (flows) and "
        "quarter-end balances; see the TTM sheet."
    )
    sheet.cell(tieout.INPUT_HEADER_ROW, 1, "Line item (financials_ttm)")
    for column, lag in [(2, 2), (3, 1), (4, 0)]:
        label = "t" if lag == 0 else f"t-{lag}"
        sheet.cell(
            tieout.INPUT_HEADER_ROW,
            column,
            f"{label} (FY{year - lag} Q{quarter})",
        )
    sheet.cell(tieout.INPUT_HEADER_ROW, 5, "XBRL tag (quarter t)")
    sheet.cell(tieout.INPUT_HEADER_ROW, 6, "Derived? (quarter t)")
    sheet.cell(tieout.CALC_HEADER_ROW, 3, "Python (scores_quarterly)")
    if quarter < 4:
        shares_row = tieout.ROWS["prior_shares"]
        sheet.cell(
            shares_row,
            1,
            "shares at the prior fiscal year end, as reported in quarter "
            "t's 10-Q",
        )
        sheet.cell(
            shares_row,
            9,
            "F-Score signal 7 in Q1-Q3 (option C, CLAUDE.md section 5)",
        )


# ---------------------------------------------------------------------------
# TTM build sheet
# ---------------------------------------------------------------------------
def write_ttm_block(sheet, start_row, label, ttm_row, sources_df):
    """Write one quarter's TTM rebuild; return (next free row, the
    list of Match cells)."""
    sheet.cell(start_row, 1, label).font = tieout.BOLD
    headers = [
        "Line item",
        "Quarter (component)",
        "Method",
        "Source value ($ or shares; signed)",
        "Accession",
        "Quarter value (Excel)",
        "TTM (Excel)",
        "Python (financials_ttm)",
        "Match?",
        "Filing on EDGAR",
    ]
    row = start_row + 1
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row, column, header)
        cell.font = tieout.BOLD
        cell.fill = tieout.GREY
        cell.alignment = tieout.WRAP
    row += 1
    match_cells = []
    derived = (
        []
        if pd.isna(ttm_row["derived_items"])
        else str(ttm_row["derived_items"]).split("; ")
    )
    tolerance = f"${TTM_TOLERANCE_CELL[0]}${TTM_TOLERANCE_CELL[1:]}"
    for item in tieout.INPUT_ITEMS:
        python_value = ttm_row[item]
        rows = sources_df[sources_df["line_item"] == item].sort_values(
            ["component_period_end", "value"], ascending=[True, False]
        )
        sheet.cell(row, 1, item).font = tieout.BOLD
        if rows.empty:
            note = (
                "derived from other columns (derived_items)"
                if item in derived
                else "no value (blank in financials_ttm)"
            )
            sheet.cell(row, 3, note)
            if pd.notna(python_value):
                cell = sheet.cell(row, 8, float(python_value))
                cell.font = tieout.BLUE
                cell.number_format = "#,##0"
            row += 2
            continue
        first_row = row
        quarter_first = {}
        for source in rows.itertuples(index=False):
            period = (
                f"{source.component_period_start.date()} to "
                f"{source.component_period_end.date()}"
                if pd.notna(source.component_period_start)
                else f"balance at {source.component_period_end.date()}"
            )
            sheet.cell(row, 2, period)
            sheet.cell(row, 3, source.method)
            value_cell = sheet.cell(row, 4, float(source.value))
            value_cell.font = tieout.BLUE
            value_cell.number_format = "#,##0"
            sheet.cell(row, 5, source.accession)
            link = sheet.cell(row, 10, source.filing_url)
            link.hyperlink = source.filing_url
            link.font = LINK
            quarter_first.setdefault(source.component_period_end, []).append(
                row
            )
            row += 1
        last_row = row - 1
        # Each quarter's value: the sum of its rows (one row, or the +
        # and - rows of a difference), shown on the quarter's first row.
        for rows_of_quarter in quarter_first.values():
            top, bottom = rows_of_quarter[0], rows_of_quarter[-1]
            cell = sheet.cell(top, 6, f"=SUM(D{top}:D{bottom})")
            cell.number_format = "#,##0"
        ttm_cell = sheet.cell(first_row, 7, f"=SUM(D{first_row}:D{last_row})")
        ttm_cell.number_format = "#,##0"
        python_cell = sheet.cell(
            first_row,
            8,
            None if pd.isna(python_value) else float(python_value),
        )
        python_cell.font = tieout.BLUE
        python_cell.number_format = "#,##0"
        sheet.cell(
            first_row,
            9,
            f'=IF(H{first_row}="","DIFF",'
            f'IF(ABS(G{first_row}-H{first_row})<={tolerance},"OK","DIFF"))',
        )
        match_cells.append(f"I{first_row}")
        row += 1
    return row + 1, match_cells


def write_ttm_sheet(workbook, case, ttm_rows, sources_df):
    """Add the TTM build sheet for one case; return (name, summary row)."""
    cik, year, quarter, name, reason = case
    sheet = workbook.create_sheet(f"{name} TTM")
    sheet["A1"] = f"{name}: TTM inputs rebuilt from the filings (CIK {cik})"
    sheet["A1"].font = tieout.TITLE
    sheet["A2"] = f"Why chosen: {reason}"
    sheet["A3"] = (
        "Each TTM flow = the sum of four single quarters; a quarter is a "
        "reported 3-month value, a year-to-date difference (+ later YTD, "
        "- earlier YTD) or annual minus 9 months. Balances are the "
        "quarter-end value. Rows come from ttm_sources."
    )
    sheet["A5"] = "Match tolerance ($ or shares)"
    sheet[TTM_TOLERANCE_CELL] = 0.01
    sheet[TTM_TOLERANCE_CELL].font = tieout.BLUE
    summary_row = 7
    row = 9
    all_matches = []
    for lag in (0, 1):
        ttm_row = ttm_rows[lag]
        if ttm_row is None:
            continue
        label = (
            f"{'t' if lag == 0 else 't-1'}: FY{year - lag} Q{quarter}, "
            f"quarter end {ttm_row['period_end'].date()}"
        )
        block_sources = sources_df[
            sources_df["period_end"] == ttm_row["period_end"]
        ]
        row, matches = write_ttm_block(
            sheet, row, label, ttm_row, block_sources
        )
        all_matches += matches
    sheet.cell(summary_row, 1, "TTM inputs that differ").font = tieout.BOLD
    sheet.cell(
        summary_row,
        2,
        "=" + "+".join(f'COUNTIF({cell},"DIFF")' for cell in all_matches),
    ).font = tieout.BOLD
    sheet.cell(summary_row + 1, 1, "TTM inputs checked")
    sheet.cell(summary_row + 1, 2, len(all_matches))
    widths = [24, 26, 24, 22, 24, 20, 20, 22, 10, 60]
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    return sheet.title, summary_row


# ---------------------------------------------------------------------------
# The workbook
# ---------------------------------------------------------------------------
def load_inputs(cases):
    """Read the quarterly tables for the cases' companies only."""
    ciks = sorted({case[0] for case in cases})
    ttm_df = pd.read_parquet(ttm.TTM_PATH, filters=[("cik", "in", ciks)])
    sources_df = pd.read_parquet(
        ttm.TTM_SOURCES_PATH, filters=[("cik", "in", ciks)]
    )
    facts_df = pd.read_parquet(
        quarterly.FACTS_QUARTERLY_PATH, filters=[("cik", "in", ciks)]
    )
    scores_df = pd.read_parquet(
        qs.SCORES_QUARTERLY_PATH, filters=[("cik", "in", ciks)]
    )
    return ttm_df, sources_df, facts_df, scores_df


def prior_shares_for(case, ttm_df, sources_df, facts_df):
    """Return the share count signal 7 compared with, found exactly as
    quarterly_scores does (the same functions)."""
    cik, year, quarter = case[0], case[1], case[2]
    rows = qs.with_accession(ttm_df, qs.share_accessions(sources_df))
    quarter_rows = rows[rows["fiscal_quarter"] == quarter]
    share_facts = facts_df[facts_df["line_item"] == "shares_outstanding"]
    if quarter < 4:
        share_facts = qs.prior_year_end_share_facts(
            quarter_rows, rows, share_facts
        )
    frame = piotroski.prepare_frame(quarter_rows, share_facts)
    match = frame[(frame["cik"] == cik) & (frame["fiscal_year"] == year)]
    return match[piotroski.PRIOR_SHARES].iloc[0]


def build_workbook(cases=TIEOUT_QUARTERLY_CASES, output=TIEOUT_QUARTERLY_XLSX):
    """Write the quarterly tie-out workbook."""
    ttm_df, sources_df, facts_df, scores_df = load_inputs(cases)
    originals = facts_df[facts_df["is_original"]]
    annual_hand_checked = tieout.hand_checked_values()
    workbook = Workbook()
    summaries, ttm_summaries = [], []
    for case in cases:
        cik, year, quarter, name, reason = case
        quarter_ttm = ttm_df[
            (ttm_df["cik"] == cik) & (ttm_df["fiscal_quarter"] == quarter)
        ]
        quarter_scores = scores_df[scores_df["fiscal_quarter"] == quarter]
        # A Q4 TTM covers the fiscal year, so it is checked against the
        # 10-K figures read by hand for the annual tie-out; Q1-Q3 TTMs
        # span two fiscal years and have no single 10-K to compare with.
        hand_checked = annual_hand_checked if quarter == 4 else {}
        summaries.append(
            tieout.write_company_sheet(
                workbook,
                (cik, year, name, reason),
                # The score code reads the row's share-count filing
                # (signal 7), exactly as quarterly_scores supplies it.
                qs.with_accession(
                    quarter_ttm, qs.share_accessions(sources_df)
                ),
                originals,
                quarter_scores,
                prior_shares_for(case, ttm_df, sources_df, facts_df),
                hand_checked,
            )
        )
        rows_by_lag = {}
        for lag in (0, 1):
            match = quarter_ttm[quarter_ttm["fiscal_year"] == year - lag]
            rows_by_lag[lag] = None if match.empty else match.iloc[0]
        relabel_score_sheet(workbook[name], case, rows_by_lag[0])
        guard_m_score(workbook[name])
        ttm_summaries.append(
            write_ttm_sheet(
                workbook,
                case,
                rows_by_lag,
                sources_df[sources_df["cik"] == cik],
            )
        )
    tieout.write_coefficients_sheet(workbook)
    tieout.write_readme_sheet(workbook, summaries + ttm_summaries)
    readme = workbook["README"]
    readme["A1"] = "Earnings Quality Radar: quarterly (TTM) tie-out"
    readme["A2"] = (
        "Score sheets recompute every quarterly score with Excel formulas "
        "from the TTM inputs; TTM sheets rebuild those inputs from the "
        "filings. Quarterly scores are unaudited 10-Q data and NOT "
        "backtested."
    )
    readme["A3"] = "Built by: python -m src.scores.tieout_quarterly"
    readme["A4"] = (
        "Results and differences: verification/tieout_quarterly_notes.md"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    print(f"Wrote {output}")


def main():
    """Build verification/tieout_quarterly.xlsx."""
    build_workbook()


if __name__ == "__main__":
    main()
