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
| f_band | string | weak (F-Score 0-3), middle (4-6), strong (7-9); NA when there is no F-Score. Team display convention, edges in `config.py` | `verdicts.f_band` |
| f_roa_positive | boolean | 1. NI_t / TA_t-1 > 0 | `piotroski.f_roa_positive` |
| f_cfo_positive | boolean | 2. CFO_t > 0 | `piotroski.f_cfo_positive` |
| f_roa_improved | boolean | 3. ROA_t > ROA_t-1 (ROA_t-1 = NI_t-1 / TA_t-2) | `piotroski.f_roa_improved` |
| f_cfo_exceeds_roa | boolean | 4. CFO_t / TA_t-1 > ROA_t | `piotroski.f_cfo_exceeds_roa` |
| f_leverage_down | boolean | 5. LTD / average TA lower than last year | `piotroski.f_leverage_down` |
| f_current_ratio_up | boolean | 6. CA/CL higher than last year | `piotroski.f_current_ratio_up` |
| f_no_new_shares | boolean | 7. Shares_t not above the t-1 count reported in year t's own 10-K | `piotroski.f_no_new_shares` |
| f_gross_margin_up | boolean | 8. Gross margin higher than last year | `piotroski.f_gross_margin_up` |
| f_asset_turnover_up | boolean | 9. Sales / beginning TA higher than last year | `piotroski.f_asset_turnover_up` |
| flags_raised | Int64 | Warnings among the three checks, 0-3: m_flag True, z_zone distress, f_band weak. A check without a score counts as no warning; NA only when none of the three has a score | `verdicts.flags_raised` |
| accruals_ratio | float64 | (NI - CFO)_t / average of TA_t and TA_t-1 | `accruals.accruals_ratio` |
| cash_conversion | float64 | CFO_t / NI_t; NaN when NI <= 0 | `accruals.cash_conversion` |
| peer_group | string | "SIC nn small/mid/large", or "SIC nn" after fallback | `peers.assign_peer_groups` |
| peer_group_level | string | industry_size, or industry (group < 5 or no total assets) | `peers.assign_peer_groups` |
| peer_group_size | int64 | Companies in the peer group used, that year | `peers.assign_peer_groups` |
| m_score_pctile, z_score_pctile, f_score_pctile, accruals_ratio_pctile, cash_conversion_pctile | float64 | 0-100: share of other peers with a lower value (ties count half), same year; NaN if the score is blank or fewer than 2 peers have it | `peers.add_percentile_ranks` |
| missing_inputs | string | "; "-separated reasons any value is blank or neutral (e.g. `cost_of_revenue_t-1`, `no_row_t-2`, `dsri_zero_denominator`, `sgai_set_to_1`, `shares_t-1_same_filing`); null when complete. See docs/methodology.md, Phase 2 | `common.combine_notes` |

## score_drivers

Zero to three rows per company-year with an M-Score: the M-Score
components pushing that score toward the warning zone, largest first.
Built by `src/scores/drivers.py` from `scores`. Ranking rule: CLAUDE.md
section 4 and docs/methodology.md, "M-Score drivers".

| Column | Type | Meaning | Computed by |
| --- | --- | --- | --- |
| cik | int64 | SEC Central Index Key | scores |
| fiscal_year | int64 | Fiscal year t | scores |
| driver_rank | int64 | 1 = largest contribution, up to 3 | `drivers.build_score_drivers` |
| component | string | DSRI, GMI, AQI, SGI, DEPI, SGAI, TATA or LVGI | `drivers.build_score_drivers` |
| component_value | float64 | The index value in `scores` (e.g. dsri) | scores |
| contribution | float64 | coefficient x (index - 1), or coefficient x TATA for TATA; always > 0. The 8 contributions (kept or not) add up to m_score - (-2.48) | `drivers.contributions` |
| explanation | string | Approved plain-English sentence for the component | `explanations.explain` |

## returns (stretch goal)

One row per scored company-year whose company has a ticker. Built by
`src/scores/returns.py` from `scores`, `financials_annual` (filed_date),
`companies` (ticker) and `prices`. Method and limitations:
docs/methodology.md, "12-month return test". Results are biased upward
(delisted companies mostly have no prices) and show correlation, not
cause.

| Column | Type | Meaning | Computed by |
| --- | --- | --- | --- |
| cik | int64 | SEC Central Index Key | scores |
| fiscal_year | int64 | Fiscal year of the 10-K | scores |
| filed_date | datetime64[ns] | 10-K filing date; the window starts the next trading day | financials_annual |
| ticker | string | Current SEC ticker | companies |
| ret_12m | float64 | Buy-and-hold return on adjusted close, start to start + 12 months; NaN without a full window | `returns.compute_returns` |
| mkt_ret_12m | float64 | SPY return over the same dates | `returns.compute_returns` |
| excess_ret_12m | float64 | ret_12m - mkt_ret_12m | `returns.compute_returns` |
| has_full_price_history | bool | Stock has a price within 7 days of both window dates | `returns.compute_returns` |

## backtest_results (stretch goal)

`data/processed/backtest_results.parquet`: one row per long-leg variant,
portfolio, cost level and holding period, plus SPY. Built by
`src/scores/backtest.py` (`python -m src.scores.backtest`) from `scores`,
`financials_annual` (filed_date), `companies` (ticker) and `prices`. It
is an analysis output, not a hand-off table between phases. Method,
results and limitations: docs/backtest.md. Not investment advice.

| Column | Type | Meaning | Computed by |
| --- | --- | --- | --- |
| variant | string | Long leg: `as_specified` (flags_raised = 0), `all_three_scores` (also requires M, Z'' and F scores), or `spy` | `backtest.run_backtest` |
| portfolio | string | `strategy` (50% long, 50% short), `long_only`, `short_only`, or `spy` | `backtest.run_backtest` |
| cost_bps | int64 | Trading cost per dollar traded, in basis points (0 or 20); the 1% a year borrowing fee applies at both | `config.BACKTEST_COST_BPS` |
| formation_date | datetime64[ns] | June 30 the portfolio was formed for | `config.BACKTEST_FORMATION_DATES` |
| start | datetime64[ns] | Trade date: last trading day on or before formation_date | `backtest.holding_periods` |
| end | datetime64[ns] | Next period's start, or the last SPY price date | `backtest.holding_periods` |
| start_value | float64 | Equity at start, in dollars ($100,000 in the first period) | `backtest.run_portfolio` |
| end_value | float64 | Equity at end after costs, in dollars | `backtest.simulate_period` |
| period_return | float64 | end_value / start_value - 1 | `backtest.run_portfolio` |
| spy_return | float64 | SPY's return over the same dates | `backtest.period_benchmark_returns` |
| n_long | int64 | Stocks held long (0 for short_only and spy) | `backtest.run_portfolio` |
| n_short | int64 | Stocks held short (0 for long_only and spy) | `backtest.run_portfolio` |
| trading_cost | float64 | Entry plus exit trading cost, in dollars | `backtest.simulate_period` |
| borrow_cost | float64 | Borrowing fee on the short leg, in dollars | `backtest.simulate_period` |

Logs in `data/logs/` (gitignored): `backtest_summary.csv` (ending value,
total and annualized return, max drawdown per portfolio),
`backtest_hit_rates.csv`, `backtest_coverage_status.csv` (candidates by
year, leg and drop reason), `backtest_coverage_delisted.csv`,
`backtest_positions.csv` (every pick with entry, exit and return vs
SPY), `backtest_candidates.csv` and `backtest_daily.csv` (daily values).

## case_studies.csv (data/case_studies.csv)

One row per case study. Hand-curated and committed by Phase 3; every
CIK in it is automatically included in `data/sample/`
(`src/pipeline/sample.py`). Read by `app/case_view.py`, which checks the
columns and types. Every row's source and note must be verified by a
team member against the filing on sec.gov before it is committed.

| Column | Type | Meaning | Source |
| --- | --- | --- | --- |
| cik | integer | SEC Central Index Key; must match a scored company | EDGAR |
| name | text | Company name as SEC lists it | EDGAR |
| event_type | text | What became public, e.g. "First public disclosure: SEC subpoena on procurement accounting" | the filing at source_url |
| event_date | YYYY-MM-DD | Date of the FIRST public disclosure of the problem in a company filing (an investigation, a filing delay tied to an accounting review, or a non-reliance notice); not the later SEC action. A fiscal year counts as "before the event" only if its 10-K was filed before this date | the filing at source_url |
| source_url | text | sec.gov link to the 8-K, press release exhibit or SEC order that documents the event | EDGAR |
| note | text | What the source says, plus the later SEC action (release number, date, link, period of misconduct, penalty); only facts stated in the cited sources | SEC releases and filings |
