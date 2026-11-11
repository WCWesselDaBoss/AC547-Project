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
fixed rule, not at random: Apple and any CIKs in
`config.SAMPLE_EXTRA_CIKS` (case studies) first; then 30 companies with
full price history, 10 that stopped filing and have no prices, and 5 with
a ticker but partial prices, each group taken in turn across SIC
divisions and ordered by most size-floor years, then CIK. Prices include
SPY. Peer percentile ranks computed on 50 companies are illustrative only;
real rankings need the full tables.
