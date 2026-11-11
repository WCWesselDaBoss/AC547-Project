# CLAUDE.md: Earnings Quality Radar shared spec

This file is the shared rulebook for every Claude Code session in this repo. Section numbers (2 to 7) match the team's master build spec, and the phase prompts refer to them. If anything here changes, update this file, commit it, and tell the team before changing code.

## 2. Project brief and universe rules

We are building a Streamlit dashboard that helps an equity analyst decide whether a company's reported earnings can be trusted before recommending the stock. The tool scores every company on earnings manipulation risk, distress risk, and financial strength. It ranks each company against peers, and it traces every number back to the SEC filing it came from.

**Course requirements this build must satisfy (AC 547, Track B):** it runs end to end on real public data; interactive controls recompute results; outputs are verified against hand calculations and the original filings; every displayed figure is traceable to source data and code; all data processing and calculation logic is in Python; and the demo runs offline from cached data.

**Which companies are included:**

- **Filers:** companies that file Form 10-K (and 10-K/A) with US GAAP XBRL data, including companies that were later delisted. Foreign filers (20-F, 40-F) are excluded by this rule.
- **Excluded industries:** SIC codes 6000 to 6799. This removes banks, insurers, REITs, and blank-check shell companies (SIC 6770) in one rule. Companies with no SIC code are also excluded, because they cannot be placed in an industry or peer group; they are logged with exclusion_reason "missing_sic" and counted.
- **Size floor:** revenue of at least $100M **or** total assets of at least $100M, tested **separately in each fiscal year** (nominal dollars). A company that shrank later still counts for the years it qualified.
- **Years:** fiscal years 2012 through the latest complete fiscal year (expected FY2025). Earlier years are excluded because smaller filers phased into detailed XBRL tagging around 2011.
- **Complete data:** a company-year gets a score only if every input for that score exists for both the current and prior year. Missing inputs produce no score, never an estimate. The pipeline reports how many company-years were dropped and why.

## 3. Tech stack and repo structure

**Stack:** Python 3.11+, pandas, pyarrow (Parquet files), requests, Streamlit, Plotly, pytest, yfinance (prices only), and black for formatting. Pin exact versions in `requirements.txt`.

All calculations live in `src/`. The Streamlit app in `app/` only loads finished tables, filters them, and draws them. It never computes a score itself, so every number can be tested outside the dashboard.

```text
earnings-quality-radar/
  CLAUDE.md               # this shared spec
  README.md               # setup, data refresh, how to run, verification summary
  requirements.txt
  config.py               # paths, year range, size floor, thresholds, SEC User-Agent
  run_pipeline.py         # one command rebuilds every processed table from raw data
  data/
    raw/                  # SEC + price downloads (gitignored, too large)
    processed/            # Parquet tables from section 4 (gitignored if > 50 MB)
    sample/               # small committed sample so the app runs from a fresh clone
    case_studies.csv      # hand-curated, committed
  src/
    pipeline/             # Phase 1: download, tag mapping, facts, financials, prices
    scores/               # Phase 2: beneish, altman, piotroski, accruals, peers, returns
  app/                    # Phase 3: Streamlit app, pages, trace component
  tests/                  # pytest tests + small fixture files, all phases
  verification/           # Excel tie-outs and notes (Phase 2)
  docs/
    data_dictionary.md    # every column in every table
    methodology.md        # formulas, design choices, limitations
    feedback_log.md       # user test notes and fixes (Phase 3)
```

## 4. Data contracts

Phases hand off only through these Parquet tables in `data/processed/`. Column names and types are frozen once agreed; any change goes into this section first. `cik` is a whole number (int64) in every table; it is zero-padded to 10 digits only when building SEC URLs. `sic` is a nullable whole number (pandas Int64). Phases 2 and 3 start immediately by building small fake versions of these tables in `tests/fixtures/` with the exact same columns.

| Table | Built by | Used by | One row per | Columns |
| --- | --- | --- | --- | --- |
| `companies` | Phase 1 | 2, 3 | company | cik, name, sic, sic_description, ticker (nullable), is_excluded, exclusion_reason |
| `facts_long` | Phase 1 | 2, 3 | company, line item, period, filing | cik, line_item, xbrl_tag, value, unit, period_start, period_end, fiscal_year, form, accession, filed_date, filing_url, is_original |
| `financials_annual` | Phase 1 | 2 | company, fiscal year | cik, fiscal_year, period_end, filed_date, accession, passes_size_floor, derived_items, then one column per standard line item (as originally reported): revenue, cost_of_revenue, sga, depreciation, operating_income, income_continuing_ops, net_income, cfo, receivables, current_assets, ppe_net, total_assets, current_liabilities, long_term_debt, total_liabilities, retained_earnings, stockholders_equity, shares_outstanding; then the component columns used by derivations: income_discontinued_ops, liabilities_and_equity, equity_including_nci, temporary_equity_total, temporary_equity_parent, redeemable_nci |
| `prices` | Phase 1 | 2 | ticker, trading day | ticker, date, adj_close |
| `scores` | Phase 2 | 3 | company, fiscal year | cik, fiscal_year, m_score, m_flag, the 8 M-Score indexes, z_score, z_zone, f_score, the 9 F-Score signals, accruals_ratio, cash_conversion, peer_group, percentile ranks per score, missing_inputs |
| `returns` (stretch) | Phase 2 | 3 | company, fiscal year | cik, fiscal_year, filed_date, ticker, ret_12m, mkt_ret_12m, excess_ret_12m, has_full_price_history |
| `case_studies.csv` | Phase 3 | 3 | case | cik, name, event_type, event_date, source_url, note |

**Column types (agreed; fixtures must use the same types):**

- **General rules.** Money is `float64` in whole US dollars (not thousands). Missing values are always NaN/NA, never 0. Text is pandas `string`. Dates are `datetime64[ns]` with no time part. Returns and ratios are decimals (0.12 = 12%). Percentile ranks run 0 to 100. Flags that can be undetermined (no score) are nullable `boolean`.
- **companies:** name, sic_description, ticker, exclusion_reason `string` (ticker and exclusion_reason nullable); is_excluded `bool`.
- **facts_long:** line_item, xbrl_tag, unit (`USD` or `shares`), form, filing_url `string`; accession `string` with dashes (e.g. `0000320193-26-000026`); value `float64`; period_start `datetime64[ns]` (NaT for balance sheet instants); period_end, filed_date `datetime64[ns]`; fiscal_year `int64`; is_original `bool`.
- **financials_annual:** fiscal_year `int64`; period_end, filed_date `datetime64[ns]`; accession `string`; passes_size_floor `bool`; derived_items `string` ("; "-separated names of line items calculated from other reported facts rather than read from their own tag, null when every value was reported; see `src/pipeline/derived_items.py` and `docs/methodology.md`); each line-item and component column `float64` (NaN when missing; shares_outstanding is in shares).
- **prices:** ticker `string`; date `datetime64[ns]`; adj_close `float64`.
- **scores:** m_score, the 8 indexes, z_score, accruals_ratio, cash_conversion `float64` (NaN when not computable); m_flag nullable `boolean`; z_zone `string` (`safe`, `grey`, `distress`, or null); f_score nullable `Int64` (0 to 9); the 9 F-Score signals nullable `boolean`; peer_group `string`; missing_inputs `string` ("; "-separated, null when complete); percentile ranks `float64` (0 to 100).
- **returns:** filed_date `datetime64[ns]`; ticker `string`; ret_12m, mkt_ret_12m, excess_ret_12m `float64` (decimals); has_full_price_history `bool`.
- **case_studies.csv:** cik integer; name, event_type, source_url, note text; event_date `YYYY-MM-DD`.

**Rules for `facts_long` (these are where XBRL data goes wrong):**

- Decide a fact's fiscal year from its `period_end` date, never from the SEC `fy` field. The `fy` field describes the filing, not the period, so a 2024 10-K's comparative 2023 numbers also carry `fy` 2024.
- Annual flow items (revenue, net income, cash flow) must cover roughly a full year (period length 350 to 380 days). Balance sheet items are instant values at `period_end`.
- The same period's value appears in several filings (as a comparative, or restated). Mark the value from the **earliest** filing as `is_original = True`. Scores use original values, because that is what investors saw at the time. Later values are kept for the restatement stretch feature.
- `filing_url` links to the filing on EDGAR, built from the CIK and accession number. This is what click-to-trace opens.
- When a company reports two mapped tags for the same line item and period, `facts_long` keeps only the company's preferred tag (the one it reports in the most years), so each company, line item and period has exactly one original value. FY2011 facts are kept only so FY2012 has a prior year.

**Rules for `financials_annual`:**

- Company-years come from each company's original 10-K filings, so a year with missing data appears with NaN values rather than disappearing. Rows run FY2011 to FY2025; FY2011 rows exist only as prior-year values and are never scored.
- Rows that fail the size floor are kept with `passes_size_floor = False`, because they can still be the prior year for a passing year. Phase 2 scores only rows that pass.
- A comparative-only year (for example, the year before a company's first 10-K, known only from that 10-K's comparative columns) is included so the first 10-K year can be scored. Its `accession` and `filed_date` are the later 10-K that first reported it, so `filed_date` is not that year's own filing date.
- Share counts are restated in later filings after stock splits. For F-Score signal 7, compare the current year's shares with the prior-year figure reported in the same 10-K (available in `facts_long`), not with the prior year's original value, or a split will look like a share issuance.

## 5. Score formulas

All coefficients and cutoffs below come from the original papers as commonly reproduced. Phase 2 must check each one against the source paper before final use and cite it in `docs/methodology.md`. Subscript t is the current fiscal year; t-1 is the prior year.

### Beneish M-Score (Beneish, 1999, 8-variable model)

```
M = -4.84 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI
```

| Index | Meaning | Formula |
| --- | --- | --- |
| DSRI | Receivables growing faster than sales | (Receivables_t / Sales_t) / (Receivables_t-1 / Sales_t-1) |
| GMI | Gross margin shrinking | GrossMargin_t-1 / GrossMargin_t, where GrossMargin = (Sales - COGS) / Sales |
| AQI | More costs being capitalized | [1 - (CurrentAssets_t + NetPPE_t) / TotalAssets_t] / [same for t-1] |
| SGI | Sales growth | Sales_t / Sales_t-1 |
| DEPI | Depreciation slowing | [Dep_t-1 / (Dep_t-1 + NetPPE_t-1)] / [Dep_t / (Dep_t + NetPPE_t)] |
| SGAI | Overhead growing faster than sales | (SGA_t / Sales_t) / (SGA_t-1 / Sales_t-1) |
| TATA | Profits not backed by cash | (IncomeContinuingOps_t - CFO_t) / TotalAssets_t |
| LVGI | Leverage increasing | [(CurrentLiab_t + LongTermDebt_t) / TotalAssets_t] / [same for t-1] |

Default flag cutoff: M greater than -1.78 (the 8-variable cutoff). Many practitioners use -2.22, so the dashboard exposes the cutoff as a slider. If SGA is missing, SGAI is set to 1 (neutral) and the row is flagged in `missing_inputs`; document this choice.

### Altman Z'' (Altman's model for non-manufacturers)

We use Z'' for every company because the universe mixes industries, and Z'' uses book equity, so it does not depend on price data. The original Z-Score (built for public manufacturers) is a stretch goal.

```
Z'' = 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4
```

X1 = working capital / total assets; X2 = retained earnings / total assets; X3 = EBIT / total assets (operating income as the EBIT proxy); X4 = book equity / total liabilities. Zones: above 2.60 safe, 1.10 to 2.60 grey, below 1.10 distress.

### Piotroski F-Score (Piotroski, 2000)

Nine pass/fail signals, one point each (0 to 9):

1. ROA > 0 (net income / beginning-of-year total assets)
2. CFO > 0
3. ROA higher than last year
4. CFO / beginning total assets > ROA (cash beats accruals)
5. Long-term debt / average total assets lower than last year
6. Current ratio higher than last year
7. No new shares issued (shares outstanding not higher than last year)
8. Gross margin higher than last year
9. Asset turnover (sales / beginning total assets) higher than last year

### Accruals and cash conversion

- **Accruals ratio** = (net income - CFO) / average total assets. Higher means less of the profit is backed by cash.
- **Cash conversion** = CFO / net income. Shown as blank when net income is zero or negative, since the ratio is meaningless there.

## 6. Rules every phase follows

- **Traceability.** Every number the dashboard shows must trace to a row in `facts_long` (XBRL tag, accession number, filing URL) and to the named Python function that computed it. No hard-coded numbers anywhere in the code except the published coefficients in `config.py`.
- **No silent fixes.** Never fill, guess, or drop data to make a result look better. Every row removed or left unscored is counted and logged with a reason, and those counts appear in the README.
- **Tests.** Every calculation function gets a pytest test with a small hand-checkable example. `pytest` must pass before every push.
- **Offline.** The app reads only local files. Nothing in `app/` calls the internet, so the live demo works without Wi-Fi.
- **SEC access.** Every request to SEC sends a `User-Agent` header with the team's name and a school email, and stays under 10 requests per second. Prefer SEC's bulk download files over thousands of single-company calls. Verify current URLs and rules on SEC's developer pages before coding.
- **Code style.** Follow the course's style rules: PEP 8; 4-space indentation, never tabs; snake_case for variables and functions, PascalCase for classes; lines under 79 characters where practical; f-strings for string formatting; and descriptive variable names (`revenue_df`, not `df1`). Format with black set to `line-length = 79` in `pyproject.toml` so the formatter matches the 79-character rule. Write a short docstring for every function. Add comments that explain *why* a choice was made, not just what the line does; the professor grades the narration.
- **Reproducible.** `python run_pipeline.py` rebuilds every processed table from raw data. A fresh clone with `data/sample/` must run the app with no extra steps.
- **Commits.** Each member commits their own work from their own account, in small commits with clear messages, at least every work session. Claude Code works on the current member's phase only and does not build other phases' modules.

## 7. Must-haves, stretch goals and milestones

**Must-haves (the grade depends on these):** the full data pipeline; M-Score, Z''-Score, F-Score, accruals and cash conversion; peer groups and percentile ranks; a screener with filters; a company drill-down; click-to-trace; case-study mode; Excel tie-outs and automated tests; an offline demo; the README; and the user feedback log.

**Stretch goals (only after every must-have works):** the 12-month return test (go/no-go on December 1); a restatement detector that compares originally reported values to later restated values; the original Altman Z for manufacturers; and CSV export from the screener.

**Milestones:**

- [ ] Nov 11: proposal memo submitted
- [ ] Nov 13: repo live, `CLAUDE.md` committed, data contracts frozen, fixture tables built
- [ ] Nov 20: Phase 1 delivers `companies` and `facts_long` on real data
- [ ] Nov 24: Phase 1 delivers `financials_annual` and `prices` (before Thanksgiving)
- [ ] Nov 30: scores on real data; dashboard running on real tables
- [ ] Dec 1: return test go/no-go; case studies verified
- [ ] Dec 2: user feedback session done, fixes made
- [ ] Dec 4: repo due (code, data instructions, tests, README)
- [ ] Dec 5 to 6: slides done; full rehearsal on the presentation laptop with cached data and a backup recording
- [ ] Dec 7 or 9: presentation
