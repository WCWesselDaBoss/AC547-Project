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

## scores

One row per scored company-year: FY2012 to FY2025, passes the size
floor, company not excluded. Built by `src/scores/build_scores.py` from
`financials_annual` (all values as originally reported) and, for F-Score
signal 7, `facts_long`. t = this fiscal year, t-1 = the year before.
Every value traces to the named function; inputs trace to
`financials_annual` and from there to `facts_long`.

| Column | Type | Meaning | Computed by |
| --- | --- | --- | --- |
| cik | int64 | SEC Central Index Key | financials_annual |
| fiscal_year | int64 | Fiscal year t | financials_annual |
| m_score | float64 | Beneish M-Score: -4.84 + weighted sum of the 8 indexes; NaN if any index is NaN | `beneish.m_score` |
| m_flag | boolean | m_score > -1.78 (`config.BENEISH_FLAG_CUTOFF`); NA when no score | `beneish.m_flag` |
| dsri | float64 | (Receivables/Sales)_t / (Receivables/Sales)_t-1 | `beneish.dsri` |
| gmi | float64 | Gross margin t-1 / gross margin t | `beneish.gmi` |
| aqi | float64 | [1 - (CA + PPE)/TA]_t / same at t-1 | `beneish.aqi` |
| sgi | float64 | Sales_t / Sales_t-1 | `beneish.sgi` |
| depi | float64 | [Dep/(Dep + PPE)]_t-1 / same at t | `beneish.depi` |
| sgai | float64 | (SGA/Sales)_t / (SGA/Sales)_t-1; 1 if SGA missing (noted) | `beneish.sgai`, `beneish.compute_beneish` |
| tata | float64 | (Income from continuing ops - CFO)_t / TA_t | `beneish.tata` |
| lvgi | float64 | [(CL + LTD)/TA]_t / same at t-1; 1 if LTD missing (noted) | `beneish.lvgi`, `beneish.compute_beneish` |
| z_score | float64 | Altman Z'' = 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4 | `altman.z_score` |
| z_zone | string | safe (> 2.60), grey (1.10 to 2.60), distress (< 1.10), NA if no score | `altman.z_zone` |
| z_x1 | float64 | (Current assets - current liabilities) / TA | `altman.z_x1` |
| z_x2 | float64 | Retained earnings / TA | `altman.z_x2` |
| z_x3 | float64 | Operating income / TA (EBIT proxy) | `altman.z_x3` |
| z_x4 | float64 | Stockholders' equity / total liabilities | `altman.z_x4` |
| f_score | Int64 | Number of True signals, 0-9; NA if any signal is NA (except signal 5 with missing LTD) | `piotroski.f_score` |
| f_roa_positive | boolean | 1. NI_t / TA_t-1 > 0 | `piotroski.f_roa_positive` |
| f_cfo_positive | boolean | 2. CFO_t > 0 | `piotroski.f_cfo_positive` |
| f_roa_improved | boolean | 3. ROA_t > ROA_t-1 (ROA_t-1 = NI_t-1 / TA_t-2) | `piotroski.f_roa_improved` |
| f_cfo_exceeds_roa | boolean | 4. CFO_t / TA_t-1 > ROA_t | `piotroski.f_cfo_exceeds_roa` |
| f_leverage_down | boolean | 5. LTD / average TA lower than last year | `piotroski.f_leverage_down` |
| f_current_ratio_up | boolean | 6. CA/CL higher than last year | `piotroski.f_current_ratio_up` |
| f_no_new_shares | boolean | 7. Shares_t not above the t-1 count reported in year t's own 10-K | `piotroski.f_no_new_shares` |
| f_gross_margin_up | boolean | 8. Gross margin higher than last year | `piotroski.f_gross_margin_up` |
| f_asset_turnover_up | boolean | 9. Sales / beginning TA higher than last year | `piotroski.f_asset_turnover_up` |
| accruals_ratio | float64 | (NI - CFO)_t / average of TA_t and TA_t-1 | `accruals.accruals_ratio` |
| cash_conversion | float64 | CFO_t / NI_t; NaN when NI <= 0 | `accruals.cash_conversion` |
| peer_group | string | "SIC nn small/mid/large", or "SIC nn" after fallback | `peers.assign_peer_groups` |
| peer_group_level | string | industry_size, or industry (group < 5 or no total assets) | `peers.assign_peer_groups` |
| peer_group_size | int64 | Companies in the peer group used, that year | `peers.assign_peer_groups` |
| m_score_pctile, z_score_pctile, f_score_pctile, accruals_ratio_pctile, cash_conversion_pctile | float64 | 0-100: share of other peers with a lower value (ties count half), same year; NaN if the score is blank or fewer than 2 peers have it | `peers.add_percentile_ranks` |
| missing_inputs | string | "; "-separated reasons any value is blank or neutral (e.g. `cost_of_revenue_t-1`, `no_row_t-2`, `dsri_zero_denominator`, `sgai_set_to_1`, `shares_t-1_same_filing`); null when complete. See docs/methodology.md, Phase 2 | `common.combine_notes` |
