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
python -m src.scores.yearend_causes     # year-end mismatch causes
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
no Excel errors** (re-checked after fixes A, B and C). Recalculated in Microsoft Excel 16.0 (through its
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
or $10,000). Every disagreement is logged with its reason and action in
`data/logs/ttm_overrides.csv` (counts after fixes B and C):

| Reason | Action | Single quarters |
| --- | --- | --- |
| Q4 "3-month" value equals the full year | replaced by the YTD difference | 218 |
| Opposite sign of the YTD difference | replaced by the YTD difference | 425 |
| Other difference from the YTD difference | kept as reported | 30,172 |

Why only two kinds are replaced. The reported 3-month value is the
original figure: what the company filed for that quarter, when it filed
it, which is what the scores use everywhere (CLAUDE.md section 4). The
year-to-date difference is not a clean measure of the quarter, because
each YTD is re-reported in the next filing, and when an earlier quarter
is revised (a restatement, or a business reclassified as discontinued),
the later YTD carries the revision, so subtracting the earlier YTD puts
the revision of an earlier quarter into the current one. In 86.7% of the
kept disagreements (26,154 of 30,172), the 3-month value and the later
YTD come from the same filing, the pattern of such a revision. A Q4
"3-month" value equal to the full-year total and a value with the
opposite sign of its YTD difference are different: no revision produces
them, they are tagging errors, so only they are replaced.

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

**"Unexplained", split (after fixes A, B and C).** A year-end mismatch
was counted as unexplained when none of the automatic causes applied
(missing or misaligned quarter, 52/53-week alignment, derived value, tag
mixing, or a period later re-reported with a different value). That
count includes cases fix A explains in its own log:

| Unexplained year-end mismatches (all 18 items) | Count |
| --- | --- |
| (a) Revisions of earlier quarters kept as reported under fix A: a quarter of that fiscal year has a 3-month value that differs from its YTD difference and was kept | 2,824 |
| (b) Truly unexplained: no cause found | 197 (155 flows, 42 balance-sheet items) |
| Total | 3,021 |

Group (a) is attributed to revisions by the same-filing pattern above;
each case is listed in `data/logs/ttm_overrides.csv` with both values
and the filings, but individual cases have not been checked against the
filings. The breakdown is reproduced by `python -m
src.scores.yearend_causes` (counts by line item, cause and split in
`verification/quarterly_yearend_causes.csv`).

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

After fix C (which removed quarters in fiscal-year changes), 3,179
company-quarters have a second date: 2,740 dropped dates were first
filed later, 348 had fewer facts in the same first filing, 211 were not
near a report date and 19 were earlier dates (the counts above are at
the time of fix B).

Total mismatches rose by 77 because a few more TTMs are blank: where
the earliest-filed date is kept, a quarter's flows reported only on the
later date are no longer used. That follows the original-values rule;
the cost is small (about 0.2% of the missing-or-misaligned count).

## 2c. Fix C: fiscal year ends from each company's own 10-Ks (Nov 22)

Quarters are numbered from the previous fiscal year end, so a missing
or wrong year end shifted a whole year's labels: Southwestern Energy's
calendar-2017 quarters were labeled FY2018 (no FY2017 row in
`financials_annual`), Archer-Daniels-Midland's July 2012 to June 2013
quarters FY2013 (a change from June to December year ends), and
Cal-Maine's June 2013 to May 2014 quarters FY2014 (two 52/53-week year
ends, June 1, 2013 and May 31, 2014, share label 2013).

Now (`quarterly.place_quarter`, `ten_k_year_ends`):

- Year ends are `financials_annual`'s plus each company's own 10-K year
  ends, taken as the latest period end of each 10-K's 12-month facts.
  SEC's submissions "reportDate" was tried first and rejected: for some
  10-Ks it is the filing date (Southwestern's FY2017 10-K shows
  2018-03-01), which created false two-month fiscal years.
- A "year" whose ends are not 350 to 380 days apart is a change of
  fiscal year end; its quarters are dropped (`quarter_in_a_fiscal_year_
  change`), never rounded into a quarter number.
- A year whose label equals the previous year's is dropped
  (`fiscal_year_label_used_twice`), because the annual table kept only
  the earlier year under that label.

| Check | Before fix C | After fix C |
| --- | --- | --- |
| Q4 rows whose label is not the period-end rule | 100 | 5 |
| Same label as annual but year ends more than 7 days apart | 351 | 8 |
| financials_ttm rows | 309,546 | 307,827 |
| Scored company-quarters | 165,084 | 164,786 |
| Year-end mismatches | 63,238 | 63,005 |
| of which unexplained | 3,020 | 3,021 |

Southwestern now has FY2016, FY2017 and FY2018 Q4 rows at Dec 31 of
each year; Cal-Maine's FY2014 Q4 is May 30, 2015, as in the annual
table. Archer-Daniels-Midland has no FY2013 row: its June 2012 and
December 2013 year ends are 549 days apart (the July to December 2012
transition 10-KT has no 12-month facts), so all quarters in between,
including calendar 2013, are dropped and counted rather than guessed.
Facts dropped as `quarter_in_a_fiscal_year_change`: 102,614;
`fiscal_year_label_used_twice`: 2,118 (`data/logs/facts_quarterly_drops.csv`).

## 3. Q4 scores vs annual scores (`quarterly_crosscheck_scores.csv`)

39,702 company-years have both a Q4 quarterly row and an annual row
(after the consistent-tag rule and fixes A, B and C; before both, M-Score 81.48%
and m_flag 99.40%).

| Measure | Pairs | Agreement |
| --- | --- | --- |
| m_flag | 14,186 | 99.51% equal |
| z_zone | 32,179 | 99.85% equal |
| f_band | 12,126 | 98.67% equal |
| flags_raised | 33,962 | 97.73% equal |
| f_score | 12,126 | 96.40% equal |
| z_score | 32,179 | 95.44% within 0.01 |
| accruals_ratio | 34,165 | 98.45% within 0.01 |
| cash_conversion | 21,518 | 96.47% within 0.01 |
| m_score | 14,186 | 84.80% within 0.01 |

The M-Score agrees least because it has the most flow inputs (eight
indexes from up to eleven line items, for two years), so any input gap
from section 2 moves it. The verdicts agree in 97.7% to 99.8% of
company-years.

## 4. Coverage (`quarterly_coverage.csv`, % of scored rows)

| Basis | Rows | M-Score | Z'' | F-Score | Accruals | Option C rows |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | 42,063 | 32.5 | 78.9 | 26.0 | 81.5 | 24,044 |
| Q2 | 41,760 | 32.5 | 79.2 | 26.8 | 84.1 | 24,559 |
| Q3 | 40,997 | 32.5 | 79.3 | 26.8 | 84.5 | 24,175 |
| Q4 | 39,966 | 36.7 | 81.6 | 31.1 | 86.5 | 0 |
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
