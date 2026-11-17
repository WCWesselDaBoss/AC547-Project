# Methodology

## Phase 1: data pipeline

### Fiscal year assignment

A fact's fiscal year comes from its `period_end` date, never from SEC's
`fy` field (which describes the filing, not the period). We use the
Compustat convention: a fiscal year ending in January through May is
labeled with the prior calendar year (for example, a year ending
January 31, 2026 is FY2025). Reasons: the Beneish (1999) and Piotroski
(2000) models were estimated on Compustat data, and the rule groups
January-year-end retailers with calendar-year peers covering mostly the
same months. Implemented in `config.fiscal_year_from_period_end`.

### Company universe and exclusions

The universe is every CIK in SEC's companyfacts bulk file (companies with
XBRL data). Each is matched to its submissions record for name, SIC code,
tickers and filing history. A company is excluded, but kept in the table
with a reason, if:

- its SIC code is 6000-6799 inclusive (banks, insurers, REITs, blank-check
  shells);
- its SIC code is blank, because the industry cannot be confirmed and no
  peer group can be assigned;
- it never filed a 10-K or 10-K/A. The check reads SEC's overflow filing
  files as well as the ~1,000 most recent filings, so long-lived companies
  are not wrongly excluded. This rule also removes foreign (20-F, 40-F)
  filers.

The ticker is the first common-stock ticker SEC lists (SEC does not always
list it first: Hertz lists its warrant HTZWW before HTZ); warrants, units,
rights and preferreds are skipped, and a company with only those gets no
ticker. Companies with none are left blank
rather than matched by name, so no company is given another's prices.
Whether a company has US GAAP facts is tested when facts_long is built
(step 5), not here, to avoid reading 19.5 GB of facts twice.

Companies whose companyfacts file contains no facts (62 files are just
"{}", 2,402 have a name but an empty facts section) are excluded as
`no_xbrl_facts`; only 12 of these 2,464 were not already excluded by
another rule.

Counts from the November 11, 2026 download (`data/logs/companies_exclusions.csv`):
20,571 companies in the companyfacts file; 9,912 excluded (5,631 no 10-K,
4,630 financial SIC, 3,017 missing SIC, 2,464 no XBRL facts; a company can
have more than one reason); 10,659 included before the size floor.

Of the 3,017 missing-SIC companies, 213 filed a 10-K and 184 meet the
$100M floor in at least one year (627 company-years). A keyword screen of
their names (Capital, Credit, Fund, Trust, Insurance, Account, etc.)
flags 201 of 213 as financial; most appear to be business development
companies, funds and insurance separate accounts that the financial-SIC
rule would exclude anyway. The screen is approximate, not a formal
classification.

### Tag mapping (src/pipeline/tag_map.py)

Each standard line item maps to an ordered list of us-gaap tags. A tag
was added only with evidence from the coverage report
(`python -m src.pipeline.tag_coverage`, logs in `data/logs/`): in
company-years where the candidate and an existing mapped tag are both
reported, how often the values agree within 0.5%. The denominator is
every fiscal year in which an included company filed an original 10-K
(67,122 company-years, FY2012-FY2025; 38,675 meet the size floor).

Tags added after the first report (each last in its list):

| Line item | Tag added | Agreement | Company-years filled |
| --- | --- | --- | --- |
| total_assets | LiabilitiesAndStockholdersEquity | 99.9% | 256 |
| revenue | RevenueFromContractWithCustomerIncludingAssessedTax | 65.8% (gap is sales/excise tax) | 2,301 |
| cfo | NetCashProvidedByUsedInOperatingActivitiesContinuingOperations | 68.3% (gap is discontinued operations) | 5,965 |
| receivables | AccountsReceivableNet | 65.2% (unclassified balance sheets) | 2,072 |

Tags rejected because they measure a different concept:
GeneralAndAdministrativeExpense for SG&A (29% agreement; excludes
selling), CostsAndExpenses for cost of revenue (0.6%), ProfitLoss for net
income (61.5%; includes noncontrolling interests),
CommonStockSharesIssued for shares outstanding (80.5%; includes treasury
shares), LongTermDebt and LongTermDebtAndCapitalLeaseObligations for
noncurrent long-term debt (27% and 61%).

**Company-consistent tag choice.** The scores compare year t with t-1, so
a company switching tags between years (for example, depreciation and
amortization one year, depreciation only the next) can move a ratio with
no change in the business. Each company uses the mapped tag it reports in
the most years (ties keep the map order); other tags fill only years where
that tag is missing (`tag_map.company_tag_order`). Year-to-year tag
switches fell from 2,072 to 574 for depreciation, 2,792 to 2,186 for
revenue (most remaining revenue switches are the 2018 ASC 606 change,
which kept the concept), and 1,575 to 1,319 for cost of revenue.

**Derived line items (src/pipeline/derived_items.py).** Used only when the
item's own tag is missing; every use is named in the `derived_items`
column.

- *Income from continuing operations* = net income - income from
  discontinued operations (missing discontinued line treated as none,
  since it must be presented separately when it exists). Tagged value
  coverage was only 16%. Where both can be compared, the calculation
  matches the tagged value in 79% of company-years with discontinued
  operations and 70% without: moderate agreement, recorded here as a
  limitation of the TATA input. Coverage rises to 92.6%.
- *Total liabilities* = total liabilities and equity - equity including
  noncontrolling interests (parent equity if not reported) - temporary
  equity. Matches the tagged value in 95.6% of 50,146 company-years; when
  it misses, the miss is often large (median 33% of total assets), which
  is why derived values are labeled. Coverage rises from 76.6% to 96.1%.

**Not fixed: long-term debt (35.6% of all company-years, 52.4% above the
size floor).** Many companies with no debt do not tag it. Treating a
missing tag as zero would be an estimate, which section 2 of CLAUDE.md
forbids, and deriving it as total debt minus the current portion fills
only 1,181 company-years at 75% agreement. Phase 2 and the team should
decide whether LVGI and F-Score signal 5 need a rule like the SGA rule.

**Depreciation tag order.** Depreciation, depletion and amortization is
listed first. Beneish (1999) used Compustat data, whose depreciation item
is understood to include amortization; this should be verified against
the paper when Phase 2 cites it.

### facts_long (src/pipeline/facts.py)

- Only us-gaap facts for mapped tags, from 10-K and 10-K/A filings, in USD
  (shares for shares_outstanding).
- Flow items must span 350-380 days (counting both end dates), which keeps
  52/53-week years and drops quarterly and year-to-date values that 10-Ks
  also contain. Balance sheet items are instants.
- Fiscal year comes from period_end (see Fiscal year assignment), never
  from SEC's `fy` field. FY2011 is kept so FY2012 has a prior year.
- When a company reports two mapped tags for the same line item and
  period, only its preferred tag is kept (the tag it reports in the most
  years; see Tag mapping), so each company, line item and period has a
  single original value.
- Every filing that reported the chosen value is kept. The earliest filing
  is `is_original`; ties on filing date put a 10-K before a 10-K/A, then
  the lower accession number.
- `filing_url` is the EDGAR filing index page built from the CIK and the
  accession number.
- Every removed fact is counted by reason in
  `data/logs/facts_long_drops.csv`.

### financials_annual (src/pipeline/financials.py)

- **Company-years** come from each company's original 10-K filings in
  submissions (recent and overflow files), not from the facts, so a year
  with missing data shows up as missing rather than disappearing. The
  10-K's report date is the fiscal year end. If a change of year end gives
  two 10-Ks the same fiscal-year label, the earlier is kept (167 cases,
  logged).
- **Comparative-only years.** A company's first 10-K also reports the
  prior year. No 10-K exists for that prior year, but its values are
  original 10-K data and are needed to score the first 10-K year. Such a
  year is added when an original total-assets balance is dated within 7
  days of one year before or after an existing 10-K's year end; its
  accession and filed_date are the 10-K that first reported it (3,626
  company-years, mostly the year before a first 10-K).
- **Matching values to years.** Each original fact is attached to the
  year whose fiscal year end is nearest its period end, within 7 days.
  Facts with no year (43,546) are mostly balances dated at quarter ends or
  other dates inside a year (median 92 days from year end), which are not
  fiscal-year-end values.
- **Size floor.** `passes_size_floor` is true when revenue or total assets
  is at least $100M in that year (nominal). Rows that fail are kept, since
  they can still serve as a prior year; a year with neither value cannot
  pass. FY2012-FY2025: 39,853 pass, 28,550 fail, 475 untestable.
- Counts are in `data/logs/financials_annual_log.csv`.

### prices (src/pipeline/prices.py)

- **Which companies.** Scored companies are those with at least one
  size-floor year from FY2012 on. Only tickers in SEC's own data are used;
  companies without one stay unmatched rather than being matched by name,
  because a wrong match would attach another company's prices.
- **Download.** yfinance, `auto_adjust=False`, keeping only `Adj Close`
  from 2012-01-01 to the download date, in unthreaded batches of 50 with a
  pause between batches (threaded mode locked yfinance's SQLite cache on
  Windows). A ticker that returns no data is retried once alone; tickers
  still failing are listed in the manifest. Each ticker is cached in
  `data/raw/prices/`, so reruns skip finished tickers.
- **Adjusted prices change over time.** Yahoo recalculates adjusted closes
  after each split or dividend, so the manifest records the download
  date; reproducing results exactly requires the same cached files.
- **Full price history** means a company's prices start within 7 days of
  its first passing year's 10-K filing date and end within 7 days of 12
  months after its last passing year's filing (capped at the latest
  trading day). Counts are in `data/logs/prices_coverage.csv`, and each
  company's status is in `data/logs/prices_by_company.csv`.
- **Survivorship bias (limitation).** SEC and Yahoo both drop tickers
  once a company stops trading, so companies that were acquired, delisted
  or went bankrupt mostly have no prices. These are exactly the outcomes
  that earnings manipulation tends to precede, so any return test on this
  data understates what happened to the worst companies.
- **Invalid adjusted prices.** A ticker whose adjusted close is ever zero
  or negative is removed entirely, because a wrong adjustment factor
  mis-scales the whole series, not just those days. Six tickers were
  removed in the November 2026 download (CBIO, CODQL, DEC, LIANY, NFE,
  VATE; listed in the manifest).
- **Results (November 11, 2026 download).** Of 5,493 scored companies,
  2,705 have an SEC common-stock ticker, 2,692 have prices and 2,606 have
  full price history. Seven tickers returned no data from Yahoo
  ("possibly delisted"). Of the 2,422 scored companies that stopped filing
  10-Ks by FY2023, 2,414 have no prices.

### Committed sample (src/pipeline/sample.py)

`data/sample/` holds the four Phase 1 tables cut to 50 companies, so a
fresh clone runs the app with no downloads. Companies are chosen by a
fixed rule, not at random: Apple, every CIK in `data/case_studies.csv`
(owned by Phase 3) and any in `config.SAMPLE_EXTRA_CIKS` first; then 30 companies with
full price history, 10 that stopped filing and have no prices, and 5 with
a ticker but partial prices, each group taken in turn across SIC
divisions and ordered by most size-floor years, then CIK. Prices include
SPY. Peer percentile ranks computed on 50 companies are illustrative only;
real rankings need the full tables.

## Phase 2: score engine

### Coefficient sources (to verify against the original papers)

Every coefficient and cutoff the code uses is in `config.py` and listed
below. "Confidence" says how sure we are of the citation, not the number.
The numbers match CLAUDE.md section 5 and widely reproduced versions of
each model, but **each must be checked against the original paper
before it is cited in the report**. Mark the "Checked" column when done.

| Constant (`config.py`) | Value | Source | Confidence | Checked |
| --- | --- | --- | --- | --- |
| `BENEISH_INTERCEPT` | -4.84 | Beneish, M. D. (1999). The detection of earnings manipulation. *Financial Analysts Journal*, 55(5), 24-36. Unweighted probit, 8 variables. | High | [ ] |
| `BENEISH_COEFFICIENTS` dsri 0.920, gmi 0.528, aqi 0.404, sgi 0.892, depi 0.115, sgai -0.172, tata 4.679, lvgi -0.327 | see left | Beneish (1999), same table as the intercept | High | [ ] |
| `BENEISH_FLAG_CUTOFF` | -1.78 | Beneish (1999); secondary sources tie -1.78 to a 20:1 relative cost of missing a manipulator vs. a false alarm | Medium: confirm the cost ratio in the paper | [ ] |
| `BENEISH_ALTERNATE_CUTOFF` | -2.22 | Widely used by practitioners; **origin not confirmed**. It may come from a later paper or the 5-variable model. Present it only as a "commonly used" alternative unless the source is found. | Low | [ ] |
| `ALTMAN_Z2_COEFFICIENTS` x1 6.56, x2 3.26, x3 6.72, x4 1.05 | see left | **Confirmed in Altman (2000), p. 27** (see below). Altman's Z'' model for non-manufacturers. First appeared in Altman, E. I. (1983), *Corporate Financial Distress* (Wiley); restated in Altman (2000), "Predicting Financial Distress of Companies: Revisiting the Z-Score and ZETA Models" (NYU Stern working paper). Secondary sources cite 1983, 1993, 2000 and 2002 editions, so confirm which edition you cite. | Medium | [ ] |
| `ALTMAN_Z2_SAFE_ABOVE`, `ALTMAN_Z2_DISTRESS_BELOW` | 2.60, 1.10 | Same as the Z'' coefficients | Medium | [ ] |
| (no constant) | none | The "+3.25" emerging-market variant (Altman, Hartzell & Peck, 1995) is a different model and is **not** used | High | [x] Altman (2000), p. 27 |
| Piotroski signal definitions (no numeric coefficients) | 9 binary signals | Piotroski, J. D. (2000). Value investing: The use of historical financial statement information to separate winners from losers. *Journal of Accounting Research*, 38 (Supplement), 1-41. | High (one source lists the issue as 38(3); check the JSTOR record) | [ ] |
| `F_SCORE_TIE_TOLERANCE` | 1e-9 | Our choice, not from a paper; only stops floating-point rounding from deciding a signal | n/a | n/a |

**Verification attempt (2026-11-17).** Primary texts were sought online;
results:

- **Altman Z'' coefficients: confirmed** in Altman (2000), "Predicting
  Financial Distress of Companies: Revisiting the Z-Score and ZETA
  Models", NYU Stern working paper, p. 27: "Z" = 6.56 (X1)+ 3.26 (X2) +
  6.72 (X3) + 1.05 (X4)"; "The book value of equity was used for X 4";
  and the +3.25 constant belongs only to the emerging-market version
  ("In the emerging market model, we added a constant term of +3.25").
  The paper credits the application to Altman, Hartzell and Peck (1995)
  and cites Altman (1983), *Corporate Financial Distress*.
- **Altman Z'' zones 2.60 / 1.10: NOT found** in Altman (2000), which gives
  zones only for the Z' model (1.23 / 2.90). The Z'' zones must be traced
  to another source (possibly a later Altman book) before citing.
- **Beneish coefficients: corroborated by a secondary source only.**
  Svabova, Kramarova, Chutka and Strakova (2020), *Oeconomia Copernicana*
  11(3), 485-508, reproduce the model with eight coefficients identical
  to ours, but print TATA as **4.697**, not 4.679. Probably a transposed
  digit, but **check the original's table**; TATA has the largest
  coefficient.
- **Beneish cutoffs: conflicting secondary sources.** Svabova et al.
  (2020) attribute -2.22 to Beneish (1999); Omeir, Vasiliauskaite and
  Soleimanizadeh (2023), *Journal of Governance and Regulation* 12(3),
  attribute -1.78 to Beneish (1999). Settle from the original.
- **Beneish (1999) and Piotroski (2000) full texts could not be read**
  (paywalled or blocked). Get them through the UA library: Beneish via
  DOI 10.2469/faj.v55.n5.2296; Piotroski via JSTOR 2672906.

### Known differences from the papers (state these in results)

These are deliberate simplifications or data constraints. Check each
against the paper when verifying the coefficients:

1. **TATA uses the cash-flow form.** We compute (income from continuing
   operations - CFO) / total assets, as CLAUDE.md section 5 specifies. As
   we understand it, Beneish (1999) computed total accruals from balance
   sheet changes (change in current assets excluding cash, less change in
   current liabilities excluding current debt and taxes payable, less
   depreciation); the cash-flow form is used in later work such as
   Beneish, Lee and Nichols (2013). **Verify** this in the paper. The
   coefficients were estimated on the balance-sheet form.
2. **Depreciation** includes depletion and amortization where companies
   tag them together (Phase 1 limitation).
3. **Z'' EBIT** is operating income, which excludes non-operating items.
4. **Piotroski ROA** uses net income. Piotroski used net income before
   extraordinary items. Extraordinary items were removed from US GAAP in
   2015 (ASU 2015-01), so the difference matters only for early years.
5. **Piotroski EQ_OFFER** (signal 7) asks whether the firm issued common
   equity. We test whether shares outstanding rose, which also catches
   option and RSU vesting but misses issuance offset by buybacks.
6. **Coefficients are from the 1980s-90s samples** and were never
   re-estimated on our data. Scores rank companies; they are not
   calibrated probabilities.

### Missing inputs, zero denominators and ties

- **Prior year.** Each score matches year t with exactly fiscal year t-1
  (and t-2 for the F-Score), never an older year
  (`src/scores/common.with_prior_years`).
- **Zero denominators** give NaN, never infinity or 0
  (`common.safe_divide`). Infinity would sort to the top or bottom of
  every percentile rank. The row's `missing_inputs` says
  `<index>_zero_denominator`.
- **Neutral values** (section 5): SGAI = 1 when SGA is missing, LVGI = 1
  when long-term debt is missing, but only if that item is the index's
  only missing input. Noted as `sgai_set_to_1` / `lvgi_set_to_1`.
- **F-Score.** NA if any signal is NA, except signal 5 when only
  long-term debt is missing (0 points, noted `f_leverage_down_no_point`).
  Ties earn no point.
- **Signal 7** uses the prior-year share count reported in year t's own
  10-K, matched on the prior balance-sheet date. In the 50-company sample
  this exists for 359 of 370 scored years with shares (97%). It avoids
  stock-split errors (Apple's 2014 7-for-1 split) and at least one
  scaling error in an original filing (CIK 45012 FY2011 shows 921
  shares). If the filing gives two values for that date, signal 7 is NA
  (`shares_t-1_same_filing_ambiguous`).
- **Cash conversion** is blank when net income is zero or negative
  (`net_income_not_positive`), because dividing by a loss flips the sign.

### 12-month return test (stretch goal, src/scores/returns.py)

For each scored company-year with a ticker, the return window starts on
the first trading day after the 10-K's `filed_date`, so the filing was
public before the hypothetical purchase. It ends on the last trading day
on or before start + 12 months.

- `ret_12m` is the buy-and-hold return on adjusted close, which includes
  dividends and splits.
- `excess_ret_12m` subtracts SPY's return over the same dates.
- A return is computed only when the stock has a price within 7 days of
  both dates (`has_full_price_history`). A stock delisted mid-window gets
  no return, because a partial-window return would be an estimate.

The summary compares companies flagged by the M-Score (-1.78) with those
not flagged: count, mean and median excess return. Company-years with no
M-Score are in neither group.

**Limitations. State these with any result.**

- **Survivorship bias.** Most companies that stopped filing have no
  Yahoo prices. Phase 1 found 2,414 of 2,422 such scored companies with
  no prices. Failed companies, likely including real manipulators, drop
  out, so the results are **biased upward** and describe mainly
  survivors.
- **Correlation, not cause.** A return gap between the groups does not
  show that the flag causes or predicts returns. The groups differ in
  size, industry and timing, and nothing here controls for that.
- **Overlapping windows.** Most 10-Ks are filed in February and March,
  so windows overlap in calendar time and observations are not
  independent. Counts, means and medians are descriptive; no
  significance test is reported.
- **Tickers.** Tickers are current SEC tickers. A reused ticker could
  attach another company's prices to an old filing.

On the 50-company sample (illustrative only): 665 scored years, 553
with a ticker, and 472 with a full 12-month window. Of those, 19 flagged
company-years had a mean excess return of -2.0% (median +2.2%), and 255
unflagged ones had a mean of +2.6% (median -2.9%). With 19 flagged
observations, this says nothing yet. The full-universe run decides the
December 1 go/no-go.
