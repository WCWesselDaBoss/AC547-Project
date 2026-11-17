# Phase 2 score tie-out notes

Workbook: `verification/tieout.xlsx`, built by
`python -m src.scores.tieout` from the full tables in `data/processed/`
(November 17, 2026 download; `--sample` builds it from `data/sample/`).
First built from the sample on 2026-11-16; the full-data rebuild gives
identical results.

## What was checked

Four company-years. Each sheet recomputes all 28 outputs with Excel
formulas from the raw inputs: 8 M-Score indexes, M-Score, flag, 4 Z''
ratios, Z'', zone, 9 F-Score signals, F-Score, accruals ratio and cash
conversion. Each result is then compared with the value in
`scores.parquet`.

| Sheet | Why chosen | M-Score | Flag | Z'' (zone) | F | Excel vs Python |
| --- | --- | --- | --- | --- | --- | --- |
| AAPL FY2024 | Inputs hand-verified in Phase 1 | -2.727 | No | 1.871 (grey) | 7 | 28 of 28 match |
| AAPL FY2020 | 4-for-1 stock split (Aug 2020) | -3.068 | No | 2.567 (grey) | 7 | 28 of 28 match |
| AMD FY2018 | Flagged by the M-Score | -0.641 | Yes | -2.011 (distress) | 7 | 28 of 28 match |
| ADI FY2017 | Flagged; long-term debt untagged | -1.348 | Yes | 2.299 (grey) | 4 | 28 of 28 match |

**Result: 112 of 112 outputs match with no differences.** The largest
numeric gap is about 1e-15, floating-point noise from a different order
of operations. The match tolerance on each sheet (cell B5) is 1e-9.

**How the formulas were evaluated.** LibreOffice was not available on the
build machine. The workbook's formulas were evaluated with `pycel`, an
independent Excel-formula engine, which found no formula errors. The
file stores formulas without cached values, so Excel calculates them
when the file is opened. **To do: open the workbook in Excel and confirm
the README summary shows 0 differences for every sheet.**

**Why this is evidence.** The Excel formulas were written separately
from the Python, cell by cell from CLAUDE.md section 5. A shared
misreading of the spec would not be caught, so the formulas were also
checked by hand on the fixture (tests/), and the coefficients must still
be checked against the papers (docs/methodology.md).

## Inputs vs. the 10-K

The blue input cells are the values stored in `financials_annual`
(original 10-K XBRL facts). Each row names its XBRL tag, and the sheet
links to the year-t 10-K on EDGAR.

- **Done:** the four Apple FY2024 inputs verified by hand in Phase 1 are
  pre-filled in the yellow column: revenue $391,035mm, net income
  $93,736mm, CFO $118,254mm and total assets $364,980mm. All four tie
  ("OK").
- **To do (team):** fill the remaining yellow cells from each 10-K's
  financial statements, in $ millions. Column H then shows OK, or CHECK
  for a gap over $0.5mm. Record the statement or page in column I. Prior
  years (t-1, t-2) come from the comparative columns of the same 10-K
  or from the prior 10-K. Our values are the ORIGINAL figures, so a
  later 10-K may show restated comparatives that differ legitimately.
- **Rows marked "derived"** (e.g. Apple's `income_continuing_ops`, which
  Apple does not tag separately) were calculated by Phase 1 from other
  reported facts (see `derived_items`). Check them against the line on
  the income statement they represent.

## Differences and findings to explain

There are no Excel-vs-Python differences. The tie-out did surface these
data and model issues, which belong in the results discussion:

1. **ADI long-term debt is missing for FY2015-FY2021 (Phase 1 data
   gap).** `long_term_debt` is blank, so LVGI was set to 1 and F-Score
   signal 5 earned no point (`lvgi_set_to_1`,
   `f_leverage_down_no_point`). Analog Devices clearly had long-term
   debt: total liabilities rose from $2.8bn (FY2016) to $11.0bn (FY2017)
   after the Linear Technology acquisition. From FY2022 the debt appears
   under `LongTermDebtNoncurrent`, so earlier years probably use a tag
   Phase 1 does not map. On the full raw data, ADI reports this debt as
   `UnsecuredLongTermDebt` ($7.55bn at FY2017 year-end), which no mapped
   tag captures; across the universe, 12,237 of the 19,027 size-floor
   years missing `long_term_debt` report other debt tags (see
   docs/methodology.md). **Raised with the Phase 1 owner.** The neutral
   rule worked as designed, but here the true LVGI would differ from 1.
   **Checked with the unmapped tag:** using `UnsecuredLongTermDebt`
   from the raw SEC file (original 10-K values), FY2017's true LVGI is
   1.371 (debt $1.73bn -> $7.55bn), which moves M from -1.348 to -1.469:
   still flagged. FY2021 (Maxim acquisition) has a true LVGI of 0.569:
   debt rose ($5.15bn -> $6.25bn), but the mostly stock-financed deal
   roughly doubled total assets, so leverage *fell*, and M moves from
   -1.741 to -1.600: still flagged, more strongly. Both flags hold.
2. **ADI's flag looks like an acquisition false positive.** The drivers
   are AQI 2.83 (goodwill and intangibles from Linear) and SGI 1.53
   (acquired revenue). The M-Score cannot tell acquired growth from
   manipulation; Beneish's sample was not built to separate them.
3. **AMD FY2018 is flagged mainly by DSRI 2.50.** Receivables grew 2.5
   times faster than sales. This is a lead to investigate in the 10-K's
   receivables note, not a conclusion.
4. **Z'' penalizes accumulated deficits and buybacks.** Apple sits in
   the grey zone (Z'' 1.87 in FY2024): heavy buybacks made retained
   earnings negative (X2 = -0.05), and working capital is negative.
   AMD is "distress" (-2.01) almost entirely because of its accumulated
   deficit (X2 = -1.63), despite a profitable FY2018. Book-equity models
   are known to misread such firms; state this when presenting Z''.
5. **The stock-split rule works on real data.** For Apple FY2020, the
   original FY2019 share count is 4.44bn, but the FY2020 10-K restates
   it as 17.77bn after the 4-for-1 split. Compared with the original
   figure, shares would appear to rise 282%, failing signal 7. The
   same-filing comparison (16.98bn vs 17.77bn) correctly passes it.

## Still to do

- Add a case-study company. `data/case_studies.csv` does not exist yet
  (Phase 3 owns it). Once a case is chosen and in the sample, add one
  line to `TIEOUT_CASES` in `src/scores/tieout.py` and rebuild.
- Fill the yellow 10-K columns (see above).
- Open in Excel and confirm the README summary shows 0 differences.
