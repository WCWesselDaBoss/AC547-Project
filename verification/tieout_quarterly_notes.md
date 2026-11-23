# Quarterly (TTM) verification notes (step 5)

Quarterly scores use TTM data from unaudited 10-Q filings, apply the
annual formulas and cutoffs unchanged, and have NOT been backtested;
tests 1 to 12 apply to annual scores only (CLAUDE.md section 5).

Built Nov 22, 2026 from the November 17 SEC download, on branch
`quarterly`. Reproduce with:

```text
python -m src.pipeline.quarterly          # facts_quarterly
python -m src.pipeline.ttm                # financials_ttm, ttm_sources
python -m src.scores.quarterly_scores     # scores_quarterly, drivers
python -m src.scores.tieout_quarterly     # tieout_quarterly.xlsx
python -m src.scores.crosscheck_quarterly # the three CSVs below
```

## 1. Excel tie-out (`tieout_quarterly.xlsx`)

Five company-quarters, two sheets each:

- **Score sheet:** the annual tie-out sheet (`src/scores/tieout.py`,
  reused unchanged). Excel formulas recompute all 28 outputs (8 M-Score
  indexes, M-Score, flag, 4 Z'' ratios, Z'', zone, 9 F-Score signals,
  F-Score, accruals, cash conversion) from the TTM inputs for t, t-1 and
  t-2, where t-1 and t-2 are the same quarter one and two years earlier.
- **TTM sheet:** every TTM input of quarters t and t-1, rebuilt from its
  source filings in `ttm_sources`. Excel adds each quarter's rows (a
  year-to-date difference is a + row and a - row) and then the four
  quarters, and compares the total with `financials_ttm`. Every row has
  its accession number and EDGAR link.

| Case | Why chosen | M-Score | Z'' | F | Scores match | TTM inputs match |
| --- | --- | --- | --- | --- | --- | --- |
| AAPL FY24 Q3 | Mid-year quarter; option C shares | -2.518 | 2.539 | 8 | 28 of 28 | 34 of 34 |
| AAPL FY24 Q4 | Q4 = annual rule | -2.727 | 1.871 | 7 | 28 of 28 | 34 of 34 |
| AMD FY19 Q1 | Flagged by the quarterly M-Score | -1.523 | -1.260 | 5 | 28 of 28 | 32 of 32 |
| COST FY24 Q2 | 12/12/12/16-week calendar | none (no receivables tag) | 1.825 | 7 | 28 of 28 (2 both blank) | 32 of 32 |
| AAP FY25 Q2 | 16/12/12/12-week calendar; after a discontinued operation | -3.158 | 1.774 | 3 | 28 of 28 (1 both blank) | 34 of 34 |

**Result: 140 of 140 score outputs and 166 of 166 TTM inputs match, with
no Excel errors.** Recalculated in Microsoft Excel 16.0 (through its
automation interface) on Nov 22, 2026. The committed file stores the
formulas without cached values, so Excel calculates them on opening.

- **AAPL FY24 Q4 equals the annual tie-out.** Its M-Score, Z'' and F
  (-2.727, 1.871, 7) are the annual `tieout.xlsx` AAPL FY2024 values,
  and all 19 of its inputs tie to the figures read by hand from the
  FY2024 10-K (`tenk_values.csv`).
- **One formula guard added (quarterly workbook only).** The annual
  sheet writer guards every formula against blank inputs except the
  M-Score and its flag, so a company with no M-Score (Costco: no
  receivables tag, so no DSRI) showed `#VALUE!` instead of "OK (both
  blank)". The four annual cases all have M-Scores, so this never shows
  in `tieout.xlsx`. `tieout.py` is not changed (quarterly work changes
  no existing function); `tieout_quarterly.guard_m_score` wraps the
  same two formulas in the same guard.

## 2. Q4 TTM vs annual, every company-year (`quarterly_crosscheck_line_items.csv`)

A Q4 TTM covers the same fiscal year as the 10-K. "Agree" means within
0.5% of the annual value or $10,000 (filers report in thousands, so four
rounded quarters can miss the total by a few thousand dollars).

| Line item | Pairs | Agree |
| --- | --- | --- |
| Balance sheet items and shares (10 items) | 26,447 to 73,926 each | 99.1% to 99.6% |
| cfo | 68,984 | 99.2% |
| revenue | 54,755 | 94.1% |
| cost_of_revenue | 39,236 | 94.2% |
| net_income | 65,062 | 93.7% |
| sga | 27,760 | 93.2% |
| operating_income | 61,860 | 92.3% |
| income_continuing_ops | 65,694 | 89.3% |
| depreciation | 58,226 | 84.0% |

Every disagreement is assigned one cause from the `ttm_sources` rows
(counts per item are in the CSV):

- **Balances:** almost all are "first reported in another filing": the
  quarter-end value's earliest filing is not that year's 10-K.
- **Flows, "quarters do not add up to 9 months":** the original Q1 to
  Q3 values differ from the 9-month year to date the 10-K's Q4 is
  computed from. Two reasons:
  1. **Restatements and reclassifications.** Quarters are kept as first
     reported (what investors saw), so a later restatement or a
     discontinued operation (Advance Auto's 2024 Worldpac sale) makes the
     TTM differ from the 10-K. This follows the "original values" rule.
  2. **Mixed XBRL tags (a method issue; see below).**
- **"Q4 reported 3 months"** and **"annual value differs"**: a Q4 or
  12-month value whose original filing or tag differs from the one
  `financials_annual` used.
- **income_continuing_ops:** 5,654 of its disagreements are derived
  values (net income minus discontinued operations), the known 70 to 79%
  limitation of that derivation (CLAUDE.md section 4).

**Mixed tags.** A 10-Q can report a 3-month value under one tag (for
example depreciation only, on the income statement) and the year to date
under another (depreciation and amortization, on the cash flow
statement). Because a reported 3-month value is preferred, Q1 to Q3 can
use one concept and Q4 (annual minus 9 months) the other:

| Line item | TTMs mixing tags | Agree, one tag | Agree, mixed | Share of disagreements from mixing |
| --- | --- | --- | --- | --- |
| depreciation | 24.1% | 93.6% | 53.6% | 69.6% |
| revenue | 9.4% | 94.8% | 87.6% | 19.8% |
| cost_of_revenue | 5.5% | 94.8% | 84.4% | 14.8% |
| cfo | 7.8% | 99.2% | 98.5% | 14.6% |
| sga, operating_income, net_income | 0% | | | |

Status: open decision (see the step 5 report).

## 3. Q4 scores vs annual scores (`quarterly_crosscheck_scores.csv`)

39,701 company-years have both a Q4 quarterly row and an annual row.

| Measure | Pairs | Agreement |
| --- | --- | --- |
| m_flag | 14,204 | 99.40% equal |
| z_zone | 32,224 | 99.80% equal |
| f_band | 12,157 | 98.55% equal |
| flags_raised | 34,011 | 97.65% equal |
| f_score | 12,157 | 96.13% equal |
| z_score | 32,224 | 95.14% within 0.01 |
| accruals_ratio | 34,246 | 98.27% within 0.01 |
| cash_conversion | 21,517 | 96.33% within 0.01 |
| m_score | 14,204 | 81.48% within 0.01 |

The M-Score agrees least because it has the most flow inputs (eight
indexes from up to eleven line items, for two years), so any input gap
from section 2 moves it. The verdicts agree in 97.7% to 99.8% of
company-years.

## 4. Coverage (`quarterly_coverage.csv`, % of scored rows)

| Basis | Rows | M-Score | Z'' | F-Score | Accruals | Option C rows |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | 42,158 | 32.4 | 78.7 | 25.9 | 81.3 | 24,046 |
| Q2 | 41,844 | 32.4 | 79.0 | 26.7 | 83.9 | 24,549 |
| Q3 | 41,077 | 32.3 | 79.1 | 26.7 | 84.2 | 24,145 |
| Q4 | 40,014 | 36.6 | 81.5 | 31.1 | 86.5 | 0 |
| Annual | 39,860 | 41.7 | 83.5 | 33.7 | 88.9 | |

Quarterly coverage is lower than annual because every TTM flow needs
four consecutive quarters, each either reported or recoverable; a single
gap blanks the TTM (reasons in `data/logs/financials_ttm_log.csv`).

## 5. Tests

The step 5 checks are automated in `tests/test_ttm.py`: a year-to-date
difference, Q4 from annual minus 9 months, a missing quarter blocking
the TTM, available_date, and a 53-week year (plus non-consecutive
quarters and the source rows adding up). The quarter rules for 52/53 and
12/16-week calendars are in `tests/test_quarterly.py`; scores in
`tests/test_quarterly_scores.py`; this cross-check in
`tests/test_crosscheck_quarterly.py`. `tests/test_annual_baseline.py`
confirms that no annual table changed.
