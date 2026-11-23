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
no Excel errors** (re-checked after fixes A and B). Recalculated in Microsoft Excel 16.0 (through its
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
| cfo | 68,986 | 99.3% |
| revenue | 54,757 | 94.6% |
| cost_of_revenue | 39,233 | 94.5% |
| net_income | 65,064 | 93.9% |
| sga | 27,760 | 93.3% |
| depreciation | 58,277 | 93.3% (84.0% before the consistent-tag rule) |
| operating_income | 61,860 | 92.5% |
| income_continuing_ops | 65,697 | 89.5% |

Figures are after fix A (section 2a); the consistent-tag table below
shows the earlier step.

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
  2. **Mixed XBRL tags (a method issue, now mostly fixed; see below).**
- **"Q4 reported 3 months"** and **"annual value differs"**: a Q4 or
  12-month value whose original filing or tag differs from the one
  `financials_annual` used.
- **income_continuing_ops:** 5,654 of its disagreements are derived
  values (net income minus discontinued operations), the known 70 to 79%
  limitation of that derivation (CLAUDE.md section 4).

**Mixed tags, and the consistent-tag rule (Nov 22).** A 10-Q can report
a 3-month value under one tag (for example depreciation only, on the
income statement) and the year to date under another (depreciation and
amortization, on the cash flow statement). When a reported 3-month value
was always preferred, Q1 to Q3 could use one concept and Q4 (annual
minus 9 months) the other. The first cross-check found this behind 70%
of the depreciation disagreements.

Fix (`ttm.year_tags`, `ttm.single_quarters`): each company, line item
and fiscal year gets one year tag (the 10-K's 12-month tag; else the
most used year-to-date tag; else the most used tag), and single quarters
are computed from that tag's facts first. A quarter falls back to
another tag only when the year tag cannot give it, so no value is
blanked (55,269 of 1,774,050 single quarters fell back; counted in
`data/logs/financials_ttm_log.csv`). Some mixing cannot be removed:
when a filing reports one period under two tags, step 2 keeps only the
company's preferred tag (the facts_long rule), so the other tag's value
for that quarter is not available.

| Line item | TTMs mixing tags (before -> after) | Agree with annual (before -> after) | Share of disagreements from mixing (after) |
| --- | --- | --- | --- |
| depreciation | 24.1% -> 9.4% | 84.0% -> 93.2% | 21.9% |
| revenue | 9.4% -> 7.3% | 94.1% -> 94.5% | 13.0% |
| cost_of_revenue | 5.5% -> 5.0% | 94.2% -> 94.4% | 11.0% |
| cfo | 7.8% -> 7.7% | 99.2% -> 99.2% | 11.7% |
| sga, operating_income, net_income | 0% | unchanged | 0% |

Coverage did not change (section 4), and the Excel tie-out still matches
140 of 140 scores and 166 of 166 TTM inputs after the rebuild.

## 2a. Fix A: 3-month values checked against the year to date (Nov 22)

A year-end breakdown of the remaining mismatches found that about 95% of
the unexplained flow cases had a reported 3-month value contradicting the
same company's year-to-date (YTD) figures: a Q4 "3-month" fact equal to
the full year (AZZ's FY2024 10-K), a value with the opposite sign
(U-Haul, quarter ending Dec 2025), or another difference.

Each 3-month value is now compared with its YTD difference (within 0.5%
or $10,000). The two clear filing errors are replaced by the YTD
difference; any other difference keeps the reported value, because most
are revisions of an earlier quarter carried in a later YTD (see
`docs/methodology.md`). Every disagreement is logged with its reason and
action in `data/logs/ttm_overrides.csv`:

| Reason | Action | Single quarters |
| --- | --- | --- |
| Q4 "3-month" value equals the full year | replaced by the YTD difference | 218 |
| Opposite sign of the YTD difference | replaced by the YTD difference | 425 |
| Other difference from the YTD difference | kept as reported | 30,327 |

A first version replaced all 30,970. That raised the Q4 agreement with
annual to about 99% for most flows, but mostly by construction: the
quarters then add up to the 10-K's 12-month value, and revisions of
earlier quarters moved into later ones. It was narrowed the same day.

Effect of the narrowed fix, all 18 line items used in the scores:

| Measure | Before fix A | After fix A |
| --- | --- | --- |
| Year-end mismatches (value differs or TTM blank) | 63,640 | 63,161 |
| of which unexplained | 3,263 | 3,060 |
| Q4 m_flag equal to annual | 99.46% | 99.48% |
| Q4 M-Score within 0.01 of annual | 84.41% | 84.57% |

The remaining unexplained flow cases are mostly kept "other
difference" quarters; they cannot be told apart from revisions
automatically and are listed in the override log for review.

## 2b. Fix B: the earliest filing wins between two quarter-end dates (Nov 22)

3,244 company-quarters have facts on two dates. When both were near the
company's report date, the old tie-break kept the date with more facts,
then the later date. For Onto Innovation FY2018, HireQuest FY2018 and
URS FY2012 that was Dec 31, taken from a later successor's 10-K or a
10-K/A, instead of the company's own year end (Dec 29, Dec 28, Dec 28)
from that year's 10-K. Now the date first filed wins (the is_original
rule). All three now equal the annual table (for example Onto total
assets $375.6M, was $418.0M). Every dropped date is logged in
`data/logs/ttm_dropped_quarter_end_dates.csv` with both dates, when
each was first filed, the facts dropped and the reason:

| Reason the other date lost | Dates |
| --- | --- |
| Not near a report date | 228 |
| First filed later | 2,785 |
| Same first filing, fewer facts | 351 |
| Same filing and facts, earlier date | 19 |

| Measure | Before fix B | After fix B |
| --- | --- | --- |
| Year-end mismatches | 63,161 | 63,238 |
| of which unexplained | 3,060 | 3,020 |
| of which missing or misaligned quarter | 38,324 | 38,469 |
| Unexplained balance-sheet mismatches (10 items) | 68 | 42 |

Total mismatches rose by 77 because a few more TTMs are blank: where
the earliest-filed date is kept, a quarter's flows reported only on the
later date are no longer used. That follows the original-values rule;
the cost is small (about 0.2% of the missing-or-misaligned count).

## 3. Q4 scores vs annual scores (`quarterly_crosscheck_scores.csv`)

39,702 company-years have both a Q4 quarterly row and an annual row
(after the consistent-tag rule and fixes A and B; before both, M-Score 81.48%
and m_flag 99.40%).

| Measure | Pairs | Agreement |
| --- | --- | --- |
| m_flag | 14,194 | 99.48% equal |
| z_zone | 32,217 | 99.81% equal |
| f_band | 12,151 | 98.66% equal |
| flags_raised | 34,004 | 97.70% equal |
| f_score | 12,151 | 96.35% equal |
| z_score | 32,217 | 95.24% within 0.01 |
| accruals_ratio | 34,241 | 98.38% within 0.01 |
| cash_conversion | 21,513 | 96.40% within 0.01 |
| m_score | 14,194 | 84.59% within 0.01 |

The M-Score agrees least because it has the most flow inputs (eight
indexes from up to eleven line items, for two years), so any input gap
from section 2 moves it. The verdicts agree in 97.7% to 99.8% of
company-years.

## 4. Coverage (`quarterly_coverage.csv`, % of scored rows)

| Basis | Rows | M-Score | Z'' | F-Score | Accruals | Option C rows |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | 42,152 | 32.4 | 78.7 | 25.9 | 81.3 | 24,047 |
| Q2 | 41,844 | 32.4 | 79.0 | 26.7 | 83.9 | 24,553 |
| Q3 | 41,075 | 32.3 | 79.1 | 26.7 | 84.3 | 24,150 |
| Q4 | 40,013 | 36.6 | 81.5 | 31.0 | 86.5 | 0 |
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
