# Data dictionary

Every column in every processed table (CLAUDE.md section 4).

## companies

One row per company with an XBRL companyfacts file. Built by
`src/pipeline/companies.py`. Excluded companies are kept and labeled.

| Column | Type | Meaning | Source |
| --- | --- | --- | --- |
| cik | int64 | SEC Central Index Key, unpadded | companyfacts.zip file name |
| name | string | Current EDGAR conformed name | submissions `name` |
| sic | Int64 (nullable) | Standard Industrial Classification code | submissions `sic` |
| sic_description | string (nullable) | SEC's label for the SIC code | submissions `sicDescription` |
| ticker | string (nullable) | First common-stock ticker SEC lists (warrants, units, rights and preferreds skipped); null if none (often delisted) | `companies.pick_ticker` on submissions `tickers` |
| is_excluded | bool | True if any exclusion rule applies | `companies.exclusion_reasons` |
| exclusion_reason | string (nullable) | All reasons, joined with "; " | `companies.exclusion_reasons` |

Exclusion reason values: `financial_sic_6000_6799`, `missing_sic`,
`no_10k_filings`, `no_xbrl_facts` (companyfacts file is empty), `no_submissions_record`.

## facts_long

One row per company, line item, period and filing. Built by
`src/pipeline/facts.py` for included companies, FY2011-FY2025 (FY2011
only supplies prior-year values for FY2012).

| Column | Type | Meaning | Source |
| --- | --- | --- | --- |
| cik | int64 | Company | companyfacts file name |
| line_item | string | Standard line item or derivation component | `tag_map.ALL_ITEMS` |
| xbrl_tag | string | us-gaap tag the value was reported under | companyfacts |
| value | float64 | Reported value in whole dollars (or shares) | companyfacts `val` |
| unit | string | `USD`, or `shares` for shares_outstanding | companyfacts unit |
| period_start | datetime64[ns] | Start of a flow period; NaT for balance sheet instants | companyfacts `start` |
| period_end | datetime64[ns] | End of the period or the balance sheet date | companyfacts `end` |
| fiscal_year | int64 | From period_end, Compustat convention (Jan-May ends -> prior year) | `config.fiscal_year_from_period_end` |
| form | string | `10-K` or `10-K/A` | companyfacts `form` |
| accession | string | SEC accession number, with dashes | companyfacts `accn` |
| filed_date | datetime64[ns] | Date the filing was filed | companyfacts `filed` |
| filing_url | string | EDGAR filing index page | `facts.edgar_filing_url` |
| is_original | bool | True for the earliest filing of this company, line item and period | `facts.mark_is_original` |

## financials_annual

One row per company and fiscal year, FY2011-FY2025 (FY2011 rows exist only
as prior-year values for FY2012). Built by `src/pipeline/financials.py`.
Values are the ORIGINALLY reported ones (`is_original` in facts_long);
trace any value through facts_long by cik, line_item and fiscal_year.

| Column | Type | Meaning |
| --- | --- | --- |
| cik | int64 | Company |
| fiscal_year | int64 | Compustat convention, from period_end |
| period_end | datetime64[ns] | Fiscal year end (the 10-K's report date) |
| filed_date | datetime64[ns] | Filing date of the 10-K for this year; for a comparative-only year, of the 10-K that first reported it |
| accession | string | That 10-K's accession number |
| passes_size_floor | bool | Revenue or total assets of at least $100M this year |
| derived_items | string (nullable) | Line items calculated from other reported facts ("; "-separated) |
| revenue ... shares_outstanding | float64 | The 18 standard line items (see `tag_map.LINE_ITEMS`); NaN when missing |
| income_discontinued_ops ... redeemable_nci | float64 | The 6 derivation components (see `tag_map.COMPONENT_ITEMS`) |

## prices

One row per ticker and trading day. Built by `src/pipeline/prices.py`
from Yahoo Finance via yfinance, for every scored company with an SEC
ticker plus SPY (market benchmark).

| Column | Type | Meaning |
| --- | --- | --- |
| ticker | string | The company's ticker from the companies table, or SPY |
| date | datetime64[ns] | Trading day |
| adj_close | float64 | Yahoo's close adjusted for splits and dividends, as of the download date in `data/raw/prices/manifest.json` |
