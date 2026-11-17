# Earnings Quality Radar

A Streamlit dashboard that helps an equity analyst decide whether a
company's reported earnings can be trusted. It scores companies on
earnings manipulation risk (Beneish M-Score), distress risk (Altman Z''),
and financial strength (Piotroski F-Score), ranks them against peers, and
traces every number to the SEC filing it came from. AC 547, Track B.

The shared build spec is `CLAUDE.md`; formulas and design choices are in
`docs/methodology.md`; every column is described in
`docs/data_dictionary.md`.

> Status: Phase 1 (data pipeline and prices) is complete. Phases 2
> (scores) and 3 (dashboard) will add their sections below.

## Setup

Python 3.12 or later (the pinned numpy 2.5.3 requires it).

```
pip install -r requirements.txt
pytest
```

A fresh clone already contains `data/sample/` (50 companies), so the app
can run without downloading anything.

## Rebuilding the data

SEC asks every requester to identify themselves. Set a User-Agent with
your team name and school email first (PowerShell):

```
$env:SEC_USER_AGENT = "EarningsQualityRadar AC547 your-school-email"
```

Then:

| Command | What it does |
| --- | --- |
| `python run_pipeline.py` | Download SEC bulk files (~3 GB) and prices, then rebuild every table and the sample |
| `python run_pipeline.py --skip-download` | Rebuild from files already in `data/raw/` (works offline, about 7 minutes) |
| `python run_pipeline.py --sample-only` | Rebuild only `data/sample/`, e.g. after changing `data/case_studies.csv` (needs `data/processed/`) |
| `python -m src.pipeline.tag_coverage` | Re-run the tag coverage report that justified the tag map |
| `python -m src.pipeline.tieout` | Rebuild the hand-verification sheet in `verification/` |
| `python run_pipeline.py --scores-only` | Rebuild only the scores and returns tables (full and sample) from existing Phase 1 tables |
| `python -m src.scores.build_scores` | Rebuild `scores.parquet` (add `--sample` for `data/sample/`) |
| `python -m src.scores.returns` | Rebuild `returns.parquet` and print the flagged vs. not-flagged comparison |
| `python -m src.scores.tieout` | Rebuild `verification/tieout.xlsx` (Excel recomputes every score) |

Sources: SEC `companyfacts.zip` and `submissions.zip` (rebuilt nightly
by SEC) and Yahoo Finance daily adjusted closes via yfinance. Download
dates, sizes and SHA-256 hashes are recorded in
`data/raw/download_manifest.json` and `data/raw/prices/manifest.json`.

## Phase 1 data: what was kept and dropped

Counts from the November 11, 2026 download. Logs are in `data/logs/`.

**Companies** (`companies_exclusions.csv`): 20,571 companies in SEC's
XBRL file; 9,912 excluded and kept with a reason; 10,659 included before
the size floor. A company can have more than one reason:

| Reason | Companies |
| --- | --- |
| Never filed a 10-K or 10-K/A (includes foreign filers) | 5,631 |
| Financial SIC 6000-6799 (banks, insurers, REITs, shells) | 4,630 |
| Missing SIC code | 3,017 |
| No XBRL facts in SEC's file | 2,464 |

**facts_long** (`facts_long_drops.csv`): 2,456,096 rows kept, 1,196,485 of
them originally reported values (one per company, line item and period,
always from the earliest filing that reported it). Dropped facts:
9,200,448 not from a 10-K or 10-K/A; 545,501 not an annual period;
274,532 a second mapped tag for the same period in the same filing (the
company's preferred tag is kept); 222,892 outside FY2011-FY2025; 32,322 in
units other than USD or shares; 164 with the wrong unit or period type
for the line item. In 454 filings two mapped revenue tags disagreed by
more than 3x and the larger was used (`adjusted:` in the log; see
`docs/methodology.md`).

**financials_annual** (`financials_annual_log.csv`): 74,868 company-years.
FY2012-FY2025: 39,860 pass the $100M size floor, 28,543 fail (kept as
possible prior years), 475 cannot be tested. 1,800 10-K years with no
facts and 167 duplicate fiscal-year labels were dropped; 3,626
comparative-only years were added.

**prices** (`prices_coverage.csv`): of 5,495 scored companies, 2,706 have
an SEC common-stock ticker and 2,606 have full price history. 2,415 of the
2,423 scored companies that stopped filing by FY2023 have no prices
(survivorship bias; see `docs/methodology.md`). Six tickers were removed
for invalid adjusted prices and eight returned no data.

## Phase 2 scores: coverage and blanks

Counts after the Phase 1 `is_original` fix and revenue guard (rebuilt
2026-11-17 with
`python run_pipeline.py --skip-download`; `data/logs/scores_log.csv`).
All 39,860 size-floor company-years (FY2012-FY2025, 5,495 companies) are
in `scores.parquet`. Every other `financials_annual` row is counted:
5,991 are FY2011 prior-year rows and 29,020 fail the size floor (kept
only as possible prior years).

A score is blank when any input is missing; nothing is estimated. Each
blank has its reason in `missing_inputs`.

| Score | Computed | Share | Main reasons for blanks |
| --- | --- | --- | --- |
| M-Score | 16,619 | 42% | No cost of revenue (13,612 years), receivables missing (9,137) |
| Z''-Score | 33,304 | 84% | Equity, operating income or total liabilities missing |
| F-Score | 13,426 | 34% | No same-filing prior share count (12,484) or no cost of revenue; 6,498 lack a t-2 year |
| Accruals ratio | 35,452 | 89% | Missing prior-year total assets |
| Cash conversion | 22,616 | 57% | Blank by design when net income <= 0 (14,277) |

**Neutral values (CLAUDE.md section 5).** LVGI is set to 1 in 8,259 of the
16,619 M-Scores (50%) because long-term debt is missing, and SGAI in 6,345
(38%) because SG&A is missing. A Phase 2 check found that 12,237 of the
19,027 size-floor years missing `long_term_debt` report other debt tags
in the same 10-K. Phase 1 tested each candidate against
`LongTermDebtNoncurrent`: none agrees closely enough to map (best 61%,
and most are one component of debt, such as unsecured or senior notes),
so the neutral-value rule stays. Evidence is in `docs/methodology.md`.

**Flags and zones.** 1,708 of 16,619 M-Scores (10.3%) exceed -1.78.
Z'' zones: 15,677 safe, 6,203 grey, 11,424 distress.

**Returns (stretch goal, `data/logs/returns_by_flag.csv`).** 22,749 of
39,860 scored years have a ticker and a full 12-month price window.
With prices through 2026-11-16, flagged companies had a mean excess
return over SPY of +10.1% but a median of -12.1% (1,007 years); unflagged
companies +2.0% mean and -6.3% median (9,091 years). The groups disagree on direction depending on mean or
median. Results are biased upward because delisted companies mostly lack
prices, and they show correlation, not cause (see `docs/methodology.md`).

**Peer groups.** 37,846 company-years are ranked within an industry-size
group; the median `peer_group_size` over those rows is 48 companies
(`peer_group_level == "industry_size"`; 46 if fallback rows are
included). 2,014 fall back to the whole 2-digit
industry because their group had fewer than 5 companies.

## Verification

`verification/phase1_tieout.csv` lists revenue, net income, total assets
and CFO for Apple, Walmart and Coca-Cola (FY2024) as stored by the
pipeline, with the XBRL tag and filing link, for comparison with each
10-K by hand. **All 12 values matched the 10-Ks** (checked by hand on
November 11, 2026). The three companies cover September (Apple), January
(Walmart, labeled FY2024 under the Compustat convention) and December
(Coca-Cola) fiscal year ends.

`verification/tieout.xlsx` recomputes all 28 score outputs with Excel
formulas for Apple FY2024 and FY2020 (stock split), AMD FY2018 and
Analog Devices FY2017. **All 112 Excel results match the Python
output** (recalculated in Excel on 2026-11-17: 0 differences on every
company sheet). All 76 inputs were also read from the 10-K statements
(`verification/tenk_values.csv`): 74 tie. The 2 differences are
documented choices: Analog Devices' long-term debt, tagged only as
`UnsecuredLongTermDebt`, which no mapped tag captures, and AMD's
depreciation, where the company-consistent tag is depreciation only.
A third difference, ASC 606 restated values marked as "original", was a
Phase 1 bug fixed on 2026-11-17 (1,572 company-years changed, 972 by
more than 1%; see `docs/methodology.md`). Findings and remaining hand
checks are in `verification/tieout_notes.md`. `pytest` runs 216 tests,
each with an expected answer worked by hand from `tests/fixtures/`.

