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

**Re-check of long-term debt tags (2026-11-17; no tag added).** Phase 2
found that 12,237 of the 19,027 size-floor years missing
`long_term_debt` report another debt-like tag in the same 10-K (for
example, Analog Devices tags its $7,551.1mm of non-current debt only as
`UnsecuredLongTermDebt`). Each candidate was tested the same way as above
(earliest-filed value at the 10-K's balance-sheet date; agreement within
0.5% with `LongTermDebtNoncurrent` where both are reported; November 11
download):

| Candidate | Both reported | Agree (0.5%) | Within 5% | Would fill (size-floor years) | Why it differs |
| --- | --- | --- | --- | --- | --- |
| UnsecuredLongTermDebt | 206 | 23.3% | 30.1% | 123 | unsecured debt only |
| LongTermNotesPayable | 948 | 49.7% | 54.0% | 906 | notes only |
| SeniorLongTermNotes | 288 | 19.4% | 27.1% | 379 | senior notes only |
| LongTermDebtAndCapitalLeaseObligations | 2,599 | 60.6% | 77.1% | 5,085 | includes finance leases |
| LongTermDebt | 16,548 | 27.1% | 55.3% | 4,480 | includes the current portion (75.2% agreement with non-current + current) |
| SecuredLongTermDebt | 386 | 33.2% | 42.2% | 428 | secured debt only |
| ConvertibleLongTermNotesPayable | 379 | 18.2% | 20.3% | 600 | convertible notes only |
| OtherLongTermDebtNoncurrent | 714 | 26.1% | 30.1% | 521 | "other" debt only |

**Decision: no tag added.** None measures non-current long-term debt
with high agreement: most are one component of a company's debt, so for
a company that also reports other debt they understate it. For some
filers (ADI among them) the component *is* all of the debt, but the
data cannot tell those filers apart from the rest, so mapping the tag
would put a partial debt figure into LVGI and F-Score signal 5 for many
companies. The neutral-value rule in section 5 (LVGI = 1, flagged) stays
the documented treatment; ADI FY2017 long-term debt remains a known
tie-out difference. A possible later improvement, not done here, is a
calculated total: the sum of debt components reported in the same 10-K,
accepted only where it ties to a reported total. It would need its own
evidence and a team decision.

**Re-check of shares outstanding tags (2026-11-17; no tag added).**
`shares_outstanding` is missing in about 30% of scored years. The
balance-sheet share counts reported alongside `CommonStockSharesOutstanding`:

| Candidate | Both reported | Agree (0.5%) | Would fill (size-floor years) | Why it differs |
| --- | --- | --- | --- | --- |
| CommonStockSharesIssued | 48,818 | 80.5% | 5,225 | includes treasury shares |
| SharesOutstanding | 860 | 52.9% | 175 | equity-statement total, often several classes |
| Preferred, temporary-equity and partnership-unit counts | | 0-33% | | different securities |

**Decision: no tag added.** Shares issued equal shares outstanding only
when a company holds no treasury stock, so the issued count would
overstate outstanding shares for the other ~20% and could flip F-Score
signal 7. The cover-page count (`dei:EntityCommonStockSharesOutstanding`)
was not considered: it is dated weeks after the balance sheet, so it is a
different measurement. A possible later improvement, not done here, is to
use shares issued only where the same 10-K reports zero treasury shares;
that would need its own agreement test.

**Revenue tags that disagree within one filing (guard added
2026-11-17).** Every mapped revenue tag is meant to be total revenue, but
some 10-Ks report the same year under two of them with very different
values; the smaller is usually a segment or a figure entered in the wrong
scale. Example: Apogee Enterprises' (CIK 6845) FY2014 10-K reports
`Revenues` $72.7mm and `SalesRevenueNet` $933.9mm. Apogee reports
`Revenues` in more years, so the preferred-tag rule picked $72.7mm and
its FY2014 M-Score was a false flag (+3.92).

Evidence (original filings, full data): 7,475 original revenue values
come from a filing that also reports another mapped revenue tag; 2,785
of those disagree by more than 1%. Judged against the company's own
original revenue in the neighbouring years, the larger value is closer
in 67% of those cases, but in **87% (554 of 635) where one value is more
than 3x the other**. Most of the remaining 13% are companies that make
the same scale error every year (for example `Revenues` 8,739 next to
`SalesRevenueNet` 8,738,739), so the neighbouring years share the error
and the larger value is in fact right.

**Rule (`facts.apply_revenue_guard`).** Within one filing, if two mapped
revenue tags for the same period differ by more than
`config.REVENUE_TAG_CONFLICT_RATIO` (3x), the larger is used; smaller
gaps keep the company's preferred tag, because some are legitimate (gross
vs net of sales taxes). Revenue only; other line items were not tested.
Each override is counted in `facts_long_drops.csv` as
`adjusted:revenue_tags_disagree_used_largest` (454 filings). Effect on
the size-floor years: revenue changed in 107 company-years at 43
companies (for example Apogee FY2014 $933.9mm, Crown Holdings FY2013
$8,656mm, The Andersons FY2015 $4,198mm, Kratos FY2013 $950.6mm); 7 more
company-years now pass the size floor (39,860); M flags fell from 1,719
to 1,708 (12 removed, including Apogee FY2014, and 1 added).

**Correction.** An earlier note here (2026-11-17) said a screen for
revenue below 20% of both neighbouring years found 49 mis-tagged
size-floor years. That was wrong: most of those 49 are genuine, such as
biotech milestone revenue and Cedar Fair's 2020 park closures. Only
about 8 were tag conflicts, and the guard above handles them. Revenue is
never removed for being unusually low.

### facts_long (src/pipeline/facts.py)

- Only us-gaap facts for mapped tags, from 10-K and 10-K/A filings, in USD
  (shares for shares_outstanding).
- Flow items must span 350-380 days (counting both end dates), which keeps
  52/53-week years and drops quarterly and year-to-date values that 10-Ks
  also contain. Balance sheet items are instants.
- Fiscal year comes from period_end (see Fiscal year assignment), never
  from SEC's `fy` field. FY2011 is kept so FY2012 has a prior year.
- **One row per filing.** When one filing reports the same line item and
  period under two mapped tags, the company's preferred tag is kept for
  that filing (the tag it reports in the most years; see Tag mapping).
  The choice is made within each filing, never across filings.
- **Original = earliest filing under any mapped tag.** For each company,
  line item and period, the earliest filing that reported it is
  `is_original`, whatever tag it used; ties on filing date put a 10-K
  before a 10-K/A, then the lower accession number. Every later filing
  stays in the table with `is_original = False` (restatement feature).
- **Why the order matters (fixed 2026-11-17).** The first version chose
  the preferred tag across all filings *before* finding the earliest
  filing. When a company switched tags, usually at the ASC 606 adoption,
  its first 10-K's fact was discarded and a later, often restated, value
  became "original". Example: Analog Devices FY2017 revenue was
  $5,246.4mm (restated in the FY2019 10-K) instead of the $5,107.5mm in
  the FY2017 10-K. Phase 2 found it in the 10-K tie-out (see Phase 2,
  "Phase 1 data issue found by the 10-K tie-out").
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
  pass. FY2012-FY2025: 39,860 pass, 28,543 fail, 475 untestable
  (after the 2026-11-17 revenue guard; 39,853 and 28,550 before).
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
- **Results (November 11, 2026 download; rebuilt 2026-11-17).** Of
  5,495 scored companies, 2,706 have an SEC common-stock ticker, 2,692
  have prices and 2,606 have
  full price history. Seven tickers returned no data from Yahoo
  ("possibly delisted"; 8 after the rebuild, because one newly scored
  company's ticker was never downloaded in an offline run). Of the 2,423
  scored companies that stopped filing 10-Ks by FY2023, 2,415 have no
  prices.

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

### Coefficient sources

Every coefficient and cutoff the code uses is in `config.py` and listed
below. "Confidence" says how sure we are of the citation, not the number.
The numbers match CLAUDE.md section 5 and widely reproduced versions of
each model, but **each must be checked against the original paper
before it is cited in the report**. Mark the "Checked" column when done.

| Constant (`config.py`) | Value | Source | Confidence | Checked |
| --- | --- | --- | --- | --- |
| `BENEISH_INTERCEPT` | -4.84 | Beneish, M. D. (1999). The detection of earnings manipulation. *Financial Analysts Journal*, 55(5), 24-36. Unweighted probit, 8 variables. | High | [x] Beneish (June 1999 working-paper version, `beneish1999.pdf`), Table 3 Panel A, "Unweighted Probit" row: -4.840 (PDF p. 24) |
| `BENEISH_COEFFICIENTS` dsri 0.920, gmi 0.528, aqi 0.404, sgi 0.892, depi 0.115, sgai -0.172, tata 4.679, lvgi -0.327 | see left | Beneish (1999), same table as the intercept | High | [x] Same row: ".920 .528 .404 .892 .115 -.172 4.679 -.327" (PDF p. 24). TATA is **4.679**; the 4.697 in Svabova et al. (2020) is their typo |
| `BENEISH_FLAG_CUTOFF` | -1.78 | Beneish (1999): the cutoff that minimizes expected misclassification cost at relative error costs of 20:1 or 30:1 | High | [x] PDF p. 17: "at relative error costs of 20:1 or 30:1, the model classifies firms as manipulators when the estimated probabilities exceed .0376 (a score greater than -1.78)"; same cutoff in the holdout sample |
| `BENEISH_ALTERNATE_CUTOFF` | -2.22 | Widely used by practitioners; **not in Beneish (1999)** (no -2.22 anywhere in the paper; its other cutoffs are -1.49 at 10:1 and -1.78 at 20:1/30:1). Origin still unconfirmed. Present it only as a "commonly used" alternative. | Low | [x] Checked absent from Beneish (1999); source still open |
| `ALTMAN_Z2_COEFFICIENTS` x1 6.56, x2 3.26, x3 6.72, x4 1.05 | see left | Altman, E. I. (2000). Predicting financial distress of companies: Revisiting the Z-Score and ZETA models. NYU Stern working paper. Model first applied in Altman, Hartzell and Peck (1995). | High | [x] Altman (2000), p. 27: "Z" = 6.56 (X1)+ 3.26 (X2) + 6.72 (X3) + 1.05 (X4)"; X4 uses book value of equity |
| `ALTMAN_Z2_SAFE_ABOVE`, `ALTMAN_Z2_DISTRESS_BELOW` | 2.60, 1.10 | Widely reported for Z'' and attributed to Altman, Hartzell and Peck (1995); **not in Altman (2000)**, which gives zones only for Z' (1.23 / 2.90) | Medium | [ ] Open: no primary text read |
| (no constant) | none | The "+3.25" emerging-market variant (Altman, Hartzell & Peck, 1995) is a different model and is **not** used | High | [x] Altman (2000), p. 27 |
| Piotroski signal definitions (no numeric coefficients) | 9 binary signals | Piotroski, J. D. (2000). Value investing: The use of historical financial statement information to separate winners from losers. *Journal of Accounting Research*, 38 (Supplement), 1-41. | High | [x] Piotroski (2000), pp. 7-9 (signal definitions) and p. 14 (Table 1 notes), from `value_investing_the_use_of_historical_financial_statement_information.pdf`; the journal header reads "Vol. 38 Supplement 2000", which settles the 38(3) question |
| `F_SCORE_TIE_TOLERANCE` | 1e-9 | Our choice, not from a paper; only stops floating-point rounding from deciding a signal. Consistent with Piotroski's rule that a signal is one only if the change is positive, "zero otherwise" | n/a | n/a |

**Verification (2026-11-17), from the two papers added to the repo root.**
`beneish1999.pdf` is Beneish's June 1999 working-paper version of the
FAJ article (author's manuscript, 27 pages), so page numbers are the
PDF's, not the journal's; the coefficients and cutoffs should be
identical to the published version, but cite the FAJ article after a
quick check of its Table 3 if the library copy is available.

- **Beneish coefficients: confirmed**, including TATA = 4.679 (Table 3,
  Panel A, unweighted probit; estimation sample of 50 manipulators and
  1,708 non-manipulators).
- **-1.78: confirmed** as the cutoff for relative error costs of 20:1 or
  30:1, which Beneish calls the relevant range for investors (PDF pp.
  16-17). At 10:1 the cutoff is -1.49.
- **-2.22: not from Beneish (1999).** Kept only as the slider's
  alternative; origin open.
- **Altman Z'' coefficients and no constant: confirmed** in Altman (2000),
  p. 27 (read 2026-11-17 from a public copy of the working paper).
- **Z'' zones 2.60 / 1.10: still open.** Not in Altman (2000) or either
  added paper. Needs Altman, Hartzell and Peck (1995) or a later Altman
  text.
- **Piotroski signals: confirmed** as implemented, apart from known
  differences 4, 5 and 7 below.

### Known differences from the papers (state these in results)

These are deliberate simplifications or data constraints. Check each
against the paper when verifying the coefficients:

1. **TATA uses the cash-flow form.** We compute (income from continuing
   operations - CFO) / total assets, as CLAUDE.md section 5 specifies.
   **Confirmed difference:** Beneish (1999, PDF p. 12) defines total
   accruals as "the change in working capital accounts other than cash
   less depreciation", a balance-sheet form, and the coefficients were
   estimated on it. The cash-flow form is used in later work (for
   example Beneish, Lee and Nichols, 2013).
2. **Depreciation** includes depletion and amortization where companies
   tag them together (Phase 1 limitation).
3. **Z'' EBIT** is operating income, which excludes non-operating items.
4. **Piotroski ROA** uses net income. Piotroski used net income before
   extraordinary items (confirmed, p. 7). Extraordinary items were removed from US GAAP in
   2015 (ASU 2015-01), so the difference matters only for early years.
5. **Piotroski EQ_OFFER** (signal 7) asks whether the firm issued common
   equity "in the year preceding portfolio formation" (p. 9). We test whether shares outstanding rose, which also catches
   option and RSU vesting but misses issuance offset by buybacks.
6. **Beneish's own data treatment differs from ours** (PDF p. 12). He
   set AQI to 1 when its denominator was zero (we leave it blank and
   note `aqi_zero_denominator`), set SGAI to 1 when SG&A was missing (the
   same as our rule), set DEPI to 1 when amortization of intangibles was
   missing, and winsorized every variable at the 1st and 99th
   percentiles (we do not). The DEPI note implies his depreciation
   measure involved amortization of intangibles (Compustat #65), most
   likely to remove it, i.e. depreciation excluding intangibles
   amortization. That is an inference; Phase 1 maps depreciation,
   depletion and amortization first, so our DEPI may include
   amortization that Beneish excluded.
7. **Piotroski's leverage includes current maturities.** Table 1 notes
   (p. 14): "total long-term debt (including the portion of long-term
   debt classified as current) scaled by average total assets". Our
   `long_term_debt` is non-current only. Also, the main text (p. 9)
   scales asset turnover by beginning-of-year assets while the Table 1
   notes say average assets; we follow the main text and CLAUDE.md.
8. **Coefficients are from the 1980s-90s samples** and were never
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

### Verdicts and M-Score drivers (src/scores/verdicts.py, drivers.py)

**Verdicts.** `f_band` labels the F-Score weak (0-3), middle (4-6) or
strong (7-9). These bands are a team display convention: Piotroski
(2000) compared the highest and lowest scores, not three bands.
`flags_raised` counts warnings across the three models (M-Score above
-1.78, Z'' distress zone, F-Score weak). A model without a score counts
as no warning, because "unknown" cannot raise a flag; the count is null
only when none of the three models has a score. The trade-off: a 0 can
mean "not checked" for a model with missing inputs, so the dashboard
must show which checks exist (`missing_inputs`). On the full data, only
9,587 of 39,860 company-years have all three checks. The models are
deliberately not combined into one weighted score: no published method
supports a weighting.

**Drivers.** The M-Score can be rewritten as
`M = -2.48 + sum over the 8 components of contribution`, where -2.48 is
the intercept plus the seven ratio coefficients (a company with every
ratio unchanged from last year and profit equal to cash), and each
contribution is coefficient x (index - 1), or 4.679 x TATA. So the
contributions show exactly what moves a company's M away from "nothing
changed". `score_drivers` keeps the up to three largest positive ones
(pushing toward the warning zone), each with a fixed, team-approved
sentence (`src/scores/explanations.py`). Checked on the full data: the
baseline plus the contributions reproduces every M-Score to within
1e-10.

Points to state when presenting drivers:

- **SGI is a driver whenever sales grew,** which is why it is the most
  common top driver overall (6,565 of 16,455 years). Among flagged
  years, AQI, DSRI and SGI lead.
- **SGAI and LVGI drive the score when they fall,** because their
  fitted coefficients are negative. In Beneish's Table 3 neither is
  statistically significant (t = -0.71 and -1.22), and DEPI is not
  either (t = 0.70); their sentences call SGAI and LVGI weak patterns.
- **Neutral values never become drivers.** An SGAI or LVGI set to 1
  contributes exactly 0.
- **Rounding guard.** Contributions at or below 1e-9
  (`config.DRIVER_MIN_CONTRIBUTION`) are ignored, so an index equal to
  1 up to floating-point rounding is not reported. On the current data
  no contribution falls in that range; the guard is a precaution.
- **Ties** in contribution are broken by the fixed component order
  (DSRI, GMI, AQI, SGI, DEPI, SGAI, TATA, LVGI).

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
  Yahoo prices. Phase 1 found 2,415 of 2,423 such scored companies with
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

**Full-universe result (rebuilt 2026-11-17 after the Phase 1
`is_original` fix and revenue guard).**

- **Coverage:** of 39,860 scored company-years, 25,607 have a ticker and
  22,749 have a full 12-month price window (prices through
  2026-11-16, `data/logs/returns_coverage.csv`).
- **Compared:** 10,098 company-years with both an M-Score and a full
  window.

| Group | Count | Mean excess return | Median excess return |
| --- | --- | --- | --- |
| Flagged (M > -1.78) | 1,007 | +10.1% | -12.1% |
| Not flagged | 9,091 | +2.0% | -6.3% |

The mean and median disagree. The *typical* flagged company (median)
trailed SPY by 5.8 points more than the typical unflagged one. The mean
is pulled up by a few very large winners, which is common in small,
fast-growing companies (the M-Score rewards sales growth). This is
descriptive only, with no significance test, biased upward by missing
delisted companies, and correlation, not cause. It is an input to the
December 1 go/no-go, not a finding.

### Full-universe check of the neutral-value rules (2026-11-17)

On the 39,860 scored company-years (counts updated after the Phase 1
`is_original` fix and revenue guard on 2026-11-17):

- **LVGI is neutral (1) in 8,259 of 16,619 M-Scores (50%)** because
  `long_term_debt` is missing; SGAI is neutral in 6,345 (38%).
- **Most missing debt is a tagging gap, not absence of debt.** 12,237 of
  the 19,027 size-floor years missing `long_term_debt` report other
  debt-like instant tags in the same 10-K. The most common are
  `LongTermDebtAndCapitalLeaseObligations` (5,204 years; Phase 1 rejected
  it at 61% agreement because it includes lease obligations) and
  `LongTermDebt` (4,545; includes the current portion). Analog Devices,
  for example, reports $7.55bn of `UnsecuredLongTermDebt` at FY2017
  year-end, which no mapped tag captures. **Phase 1 result:** each
  candidate was tested against `LongTermDebtNoncurrent`; none agrees
  closely enough to map (see Phase 1, "Re-check of long-term debt
  tags"), so the neutral-value rule stays.
- **Effect on flags.** 1,044 of the 1,708 flagged company-years (61%) use
  a neutral LVGI. LVGI's coefficient is -0.327, so a true LVGI of 1.2
  would lower M by 0.065: only 71 of those flags are that close to
  -1.78 (157 within 0.16, i.e. a true LVGI of 1.5). Most flags therefore
  do not depend on the rule. A true LVGI below 1 would raise M instead,
  so the rule can also hide flags. Example: Analog Devices FY2021 has a
  neutral LVGI; its true LVGI from the unmapped `UnsecuredLongTermDebt`
  tag is 0.569 (the stock-financed Maxim deal grew assets faster than
  debt), which raises M from -1.741 to -1.600. The flag holds.

### Phase 1 data issue found by the 10-K tie-out (2026-11-17)

Hand-reading all 76 tie-out inputs from the 10-Ks
(`verification/tenk_values.csv`) found 73 matches and 3 differences
(after the fix below: 74 matches, differences 1 and 2 remain):

1. **ADI FY2017 long-term debt**: $7,551.1mm in the 10-K, missing in our
   data (the unmapped-tag gap described above).
2. **AMD FY2018 depreciation**: our $94mm is depreciation only
   (`Depreciation`, AMD's most-reported tag); the cash flow statement
   prints depreciation and amortization of $170mm, which AMD also tags
   (`DepreciationDepletionAndAmortization`). This is the documented
   company-consistent tag rule working as designed: DEPI compares a
   company with itself, so each company uses one definition, but the
   definition can differ between companies.
3. **ADI FY2017 revenue: a Phase 1 bug.** The FY2017 10-K reports
   $5,107.5mm (tag `SalesRevenueNet`). Our value, $5,246.4mm, is the
   ASC 606 restatement first reported in the FY2019 10-K under
   `RevenueFromContractWithCustomerExcludingAssessedTax`. Phase 1 keeps
   only the company's preferred tag for a period *before* marking the
   earliest filing as original, so when a company switched tags, the
   later (often restated) value became `is_original`. That breaks the
   section 4 rule that scores use what investors saw at the time.

**Extent (full data, size-floor years FY2012-FY2025).** 7,668 original
values came from a later filing although the year's own 10-K reported
the item under another mapped tag. 1,582 of them differ by more than 1%,
in 1,256 company-years (3.2% of scored years) at 852 companies. Most are
revenue (451), CFO (400), cost of revenue (191), depreciation (190) and
net income (147), clustered in FY2016-FY2017 (ASC 606 full retrospective
adoptions). These touch 557 M-Scores and 74 flags. Year t+1 scores that
use these as t-1 values are also affected.

**Fix (Phase 1, `src/pipeline/facts.py`):** mark `is_original` on the
earliest filing's value for each company, line item and period across
all mapped tags, then apply the preferred-tag rule only among facts from
that same filing. Not changed here, because CLAUDE.md section 6 keeps
each phase's code with its owner. Table columns and types do not change,
so Phase 3 is unaffected apart from these values updating after the fix.

**Fixed in Phase 1 on 2026-11-17** (`src/pipeline/facts.py`,
`choose_tag_per_filing` then `mark_is_original`). ADI FY2017 revenue is
now $5,107.5mm from the FY2017 10-K, and its tie-out row reads OK.
Measured as a before/after comparison of `financials_annual` on the
size-floor years FY2012-FY2025: **1,572 company-years changed, 972 by
more than 1%, at 644 companies** (revenue 543, CFO 521, cost of revenue
426, depreciation 219, receivables 13, continuing-operations income 5,
total assets 2). That is fewer than the estimate above; in particular no
net income value changed, because `net_income` has a single mapped tag,
so a switch between mapped tags cannot occur for it. The estimate's
method was not committed, so the gap could not be traced exactly; a
likely cause is counting tags mapped to other line items. Effect on
scores: 1,317 M-Scores changed value; flags went from 1,721 to 1,719
(25 newly flagged, 30 no longer flagged, 11 became computable or
blank); 179 F-Scores changed; no Z'' zone changed. The revenue guard
added the same day (Phase 1, Tag mapping) then moved flags to 1,708.
ADI FY2017 stays
flagged (M -1.348 to -1.355) and AMD FY2018 stays flagged (-0.641 to
-0.623; its FY2016-17 inputs were ASC 606 restatements).

## Quarterly (TTM) upgrade

Quarterly scores use TTM data from unaudited 10-Q filings, apply the
annual formulas and cutoffs unchanged, and have NOT been backtested;
tests 1 to 12 apply to annual scores only. The full quarterly method is
documented in step 6; the notes below record decisions as they are made.

### Single quarters must agree with the year to date (fix A, 2026-11-22)

A single quarter can come from a reported 3-month value or from the
difference of two year-to-date (YTD) values (6 months minus 3, 9 minus
6, 12 minus 9). The step 5 cross-check found 3-month values that
contradict the same company's YTD figures: a Q4 "3-month" fact equal to
the full-year total (AZZ's FY2024 10-K), a 3-month value with the
opposite sign (U-Haul, quarter ending Dec 2025), and other differences.
About 95% of the unexplained year-end mismatches had one of these.

Rule (`src/pipeline/ttm.py`, `quarters_from_facts`): where a quarter has
both, the two are compared (agreement = within 0.5% or $10,000, the
cross-check tolerance; values reported in thousands can differ by a few
thousand dollars through rounding). Two disagreements are clear filing
errors, and the YTD difference replaces the reported value: a Q4
"3-month" value equal to the full-year total, and a value with the
opposite sign of the YTD difference. Any other disagreement keeps the
reported 3-month value. Most of those are revisions, not errors: a later
10-Q's YTD includes a corrected earlier quarter (in 86% of them the
3-month value and the YTD come from the same filing), so replacing the
3-month value would move that correction into the current quarter. That
would break the original-values rule (what investors saw for the
quarter). Every disagreement, replaced or kept, is counted by action and
reason in `data/logs/financials_ttm_log.csv` and listed with both values
and the filings in `data/logs/ttm_overrides.csv`. A first version
(2026-11-22) replaced all 30,970 disagreements; it was narrowed the same
day for this reason.

What this means for verification: tying quarters to the YTD figures
makes the year-end cross-check (Q4 TTM against `financials_annual`)
partly automatic for the replaced cases. When Q2 to Q4 all come from
YTD differences, the four quarters add up to the 12-month value by
construction, so agreement there no longer shows that the quarters are
right, only that the 12-month value matches the annual table. The
cross-check therefore remains a check of the data, not of this rule.
The independent check is the Excel tie-out
(`verification/tieout_quarterly.xlsx`): its TTM sheets rebuild every
input from the source filings with Excel formulas, and each source row
links to the filing on EDGAR, so a reader can confirm each quarter
against the 10-Q or 10-K itself.
