# Earnings Quality Radar

A Streamlit dashboard that helps an equity analyst decide whether a
company's reported earnings can be trusted. It scores companies on
earnings manipulation risk (Beneish M-Score), distress risk (Altman Z''),
and financial strength (Piotroski F-Score), ranks them against peers, and
traces every number to the SEC filing it came from. AC 547, Track B.

The shared build spec is `CLAUDE.md`; formulas and design choices are in
`docs/methodology.md`; every column is described in
`docs/data_dictionary.md`.

> Status: all three phases are built: the data pipeline and prices
> (Phase 1), the scores (Phase 2), and the dashboard and case studies
> (Phase 3). Screenshots of every page are in `docs/screenshots/`.

**Contents:** [Setup](#setup) ·
[Running the dashboard](#running-the-dashboard) ·
[Rebuilding the data](#rebuilding-the-data) ·
[Phase 1 data](#phase-1-data-what-was-kept-and-dropped) ·
[Phase 2 scores](#phase-2-scores-coverage-and-blanks) ·
[Verification](#verification) ·
[Phase 3 dashboard](#phase-3-dashboard) ·
[Case studies](#case-studies) · [Limitations](#limitations) ·
[Keeping the data current](#keeping-the-data-current)

## Setup

Python 3.12 or later (the pinned numpy 2.5.3 requires it).

```
pip install -r requirements.txt
pytest
```

A fresh clone already contains `data/sample/` (53 real companies,
including every case-study company), so the app runs without downloading
anything.

## Running the dashboard

```
streamlit run app/app.py
```

(`python -m streamlit run app/app.py` also works.) The app opens at
http://localhost:8501. It only reads local Parquet files: it never
computes a score (all calculations are in `src/`), makes no internet
calls (usage statistics are off and it serves only to this computer, see
`.streamlit/config.toml`), and so runs the demo without Wi-Fi. Only the
"Open on EDGAR" links leave the app, and they need a connection.

**Which data it shows** is set by `EQR_DATA_SOURCE` (PowerShell:
`$env:EQR_DATA_SOURCE = "sample"`); the sidebar always says which one is
on screen.

| Value | Folder | Use |
| --- | --- | --- |
| `auto` (default) | `data/processed/` if every table is there, otherwise `data/sample/` | Normal use; a fresh clone gets the sample |
| `full` | `data/processed/` | Real rankings; errors (never silently switches) if a table is missing |
| `sample` | `data/sample/` | Demo from a fresh clone; peer ranks are illustrative |
| `fixture` | `tests/fixtures/app/` | Five made-up, hand-checkable companies for development |

**Deep links** open a page on a chosen company or case, handy for demo
bookmarks: `http://localhost:8501/company?cik=1336917&year=2015` (Under
Armour FY2015) or `http://localhost:8501/case-studies?case=2`.

**Before a live demo:** run `pytest`, start the app once to warm its
cache, and keep `docs/screenshots/` open as a backup.

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
| `python -m src.scores.drivers` | Rebuild `score_drivers.parquet` (add `--sample` for `data/sample/`) |
| `python -m src.scores.returns` | Rebuild `returns.parquet` and print the flagged vs. not-flagged comparison |
| `python -m src.scores.backtest` | Run the backtests (stretch goal: 2021-2025 and 2014-2025, with a comparison group and a value tilt); writes `backtest_results.parquet` and `data/logs/backtest_*.csv`; the first run also reads public floats from `data/raw/companyfacts.zip` (about 4 minutes, then cached); see `docs/backtest.md` |
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

**Verdicts (`f_band`, `flags_raised`).** F-Score bands: 2,881 weak,
7,936 middle, 2,609 strong (26,434 without an F-Score). Warnings per
company-year: 21,550 with 0, 11,778 with 1, 1,753 with 2, 243 with all
3, and 4,536 with no check available (null). Only 9,587 company-years
have all three checks; 16,886 have just one, so their 0 means "no
warning from the one check we have", not an all-clear. The models are
never combined into one weighted score.

**M-Score drivers (`score_drivers`, `data/logs/score_drivers_log.csv`).**
43,672 driver rows for 16,455 of the 16,619 company-years with an
M-Score; 164 have no component pushing the score up. Among the 1,708
flagged years the top driver is most often AQI (517), DSRI (433) or SGI
(416). Across all years SGI leads (6,565), because any sales growth
counts toward the score.

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
checks are in `verification/tieout_notes.md`. `pytest` runs 357 tests
(November 19, 2026), each with an expected answer worked by hand from
`tests/fixtures/`; 127 of them cover the dashboard (see
[Phase 3 dashboard](#phase-3-dashboard)).

**Click-to-trace check (Phase 3, November 19, 2026).** Every input of
every score was traced for all 691 company-years of the 53-company
sample, the same lookup the dashboard's trace panel runs. All 31,613
reported values matched the original 10-K fact the score used
(0 unmatched). The remaining rows were 4,186 inputs not reported (shown
as missing, never filled), 632 values Phase 1 calculated (each traced
through its 977 reported parts) and 192 years with no 10-K in the data
(such as the year before a company's first 10-K). The dashboard tests
also run every page headlessly on the fixture data and every case study
on the sample.

**Full-data run (Phase 3, November 19, 2026).** With the full tables
built locally (`python run_pipeline.py --scores-only`: 39,853 scored
company-years for 5,493 companies on this laptop's Phase 1 tables), every
page ran without errors. Cold-start load times: screener 2 s, a company
page with the trace tab about 4 s (one company's filings are read from
the 630 MB `facts_long` on demand, then cached). Peer groups are real
here: Under Armour FY2015 is ranked against 7 similar-sized companies,
not the sample's 2. The seven case-study results are identical on sample
and full data. Screenshots: `docs/screenshots/full/`.


## Phase 3 dashboard

Four pages, written for an analyst who never took this course. Every
page reads finished tables and only filters and draws them.

| Page | What it answers | Screenshot |
| --- | --- | --- |
| Screener | Which companies in a year show the most warning signs? Filters for fiscal year, industry, size, the M-Score cutoff (slider, default -1.78), Z'' zone and F-Score range; riskiest first; notes on who is excluded and why scores are blank | `01_screener.png` |
| Company detail | In five seconds: a one-line verdict and three traffic-light cards. Then why (the stored `score_drivers` sentences), how it compares with peers (one sentence per percentile), and the detail (trends, peer ranks, every component) | `02_company_verdict.png` |
| Click-to-trace | For any score or part of one: the formula, the stored result, the Python function that computed it, and every input with its XBRL tag, period, filing date, accession number and EDGAR link. Opened from the button under each card or the "Trace to SEC filing" tab | `03_trace_popup.png`, `04_trace_tab.png` |
| Case studies | Did the radar warn before a known accounting problem became public? Hits, misses and companies it could not score are all shown | `05`-`07_case_*.png` |
| About and limitations | Data sources, universe rules, citations, coverage computed from the data on screen, and limitations | `08_about.png` |

Design choices worth knowing:

- **Plain English with an icon and a word for every verdict**
  (🔴 Warning, 🟡 Grey zone, 🟢 Safe zone, ⚪ No score), never color
  alone. The wording never says a company "will fail" or is a "bad
  investment"; concerns are "warning signs worth investigating".
- **The slider re-applies Phase 2's own rule.** Moving the M-Score cutoff
  recomputes the flag and the concern count with `beneish.m_flag` and
  `verdicts.flags_raised`; a test confirms that at -1.78 they equal the
  stored `m_flag` and `flags_raised`. The company page uses the same
  cutoff, so the two pages never disagree.
- **Size bands** on the screener are total assets that year: under $1B,
  $1B to $10B, $10B and over (`config.APP_SIZE_BANDS`). They are a team
  display convention, used because the peer groups' size terciles exist
  only where an industry has enough companies.
- **The trace uses Phase 2's own input lists** (`beneish.INDEX_INPUTS`,
  `altman.RATIO_INPUTS`, `piotroski.SIGNAL_INPUTS`), so it can never list
  different inputs from the ones the score used. Values calculated by
  Phase 1 are labeled as such, with their reported parts and the
  function that calculated them; later restatements are shown, not used.

User testing: `docs/user_test_script.md` (nine tasks with answer keys
for a first-time tester) and `docs/feedback_log.md` (every confusion
point, its severity, the fix and its commit).

Code: `app/app.py` (shell), `app/views/` (one file per page), and pure,
tested logic in `app/screening.py`, `app/company_view.py`,
`app/trace.py`, `app/case_view.py` and `app/about_view.py`.

## Case studies

`data/case_studies.csv` lists seven companies with a documented
accounting or disclosure problem. Each `event_date` is the **first public
disclosure** of the problem in a company filing (an investigation, a
filing delay tied to an accounting review, or a non-reliance notice),
not the later SEC action, because the question is what an analyst could
have seen before the problem was known. A fiscal year counts as "before
the event" only if its 10-K was filed before that date, and cases use
the published -1.78 cutoff, never the slider. Every source and note was
checked against the filing on sec.gov.

Result on the sample, for the earnings manipulation check (distress and
strength are shown for context but not counted, because they measure
financial health, not manipulation):

| Company | First disclosure | Result | Why |
| --- | --- | --- | --- |
| Under Armour | 2019-11-04 | Warned | M-Score above -1.78 in FY2015 (the first year of the pull-forwards the SEC described) and FY2013 |
| Super Micro Computer | 2017-10-26 | Warned | FY2015 |
| Kraft Heinz | 2019-02-21 | Miss | Only FY2017 could be scored before the event: -1.82, just under the cutoff |
| General Electric | 2018-01-16 | Could not score | No current assets or current liabilities tagged (unclassified balance sheet) |
| MiMedx | 2018-02-20 | Could not score | Revenue not found under a mapped tag in FY2014-FY2015, so FY2014-FY2016 lack a year t or t-1 revenue |
| Synchronoss | 2017-05-15 | Could not score | No cost of revenue |
| Hertz Corp | 2014-06-06 | Could not score | The subsidiary's 10-K data lacks most inputs: cost of revenue, depreciation, current assets and liabilities, net income |

Two warned, one miss, four could not be scored. Seven hand-picked cases
cannot measure accuracy; they show how the radar behaves, including that
missing XBRL inputs keep it from scoring several well-known cases. To add
a case, add a row (see `docs/data_dictionary.md`), verify its source,
then run `python run_pipeline.py --sample-only` and commit `data/sample/`.

## Limitations

The About page lists these with coverage figures computed from the data
on screen; full detail is in `docs/methodology.md`.

- **The checks flag warning signs; they do not predict returns or prove
  fraud.** A company with no warnings can still have problems (see the
  case studies).
- **Coverage.** Scores are blank whenever an input is missing (M-Score
  42%, F-Score 34% of size-floor company-years on full data). Missing
  SG&A and long-term debt are set to neutral instead, as section 5 of
  `CLAUDE.md` specifies.
- **Differences from the papers.** Coefficients come from 1980s-90s
  samples and are not re-estimated, so scores rank companies rather than
  give probabilities. TATA uses the cash-flow form. Z'' uses operating
  income for EBIT and book equity, so large buybacks can lower it for
  strong companies. The -2.22 alternative cutoff is not in Beneish
  (1999), and the Z'' zone cutoffs are not yet confirmed in a primary
  source.
- **Calculated inputs.** Income from continuing operations and total
  liabilities are sometimes calculated from other reported facts; the
  trace panel labels every such value.
- **Peers.** Percentile ranks compare a company only with the companies
  in the data loaded; on the sample they are illustrative.
- **Disclosure-only problems** that do not change reported numbers are
  largely invisible to these models.
- **Returns** (stretch goal) are biased upward by survivorship and show
  correlation, not cause; the dashboard does not display them.
- **Backtest** (stretch goal, `docs/backtest.md`): a long-short test of
  0-flag vs 3-flag companies, 2021-2026. It uses today's tickers, so
  companies that later delisted are left out (look-ahead bias), and it
  rests on 7 to 11 shorts a year. Over 2014-2025 no long-only version
  reliably beat SPY or an equal-weighted group of all scored companies.
  Not investment advice.

## Keeping the data current

SEC's bulk files are rebuilt nightly, so a rerun always picks up every
10-K filed so far. 10-Ks are due 60, 75 or 90 days after the fiscal year
ends, depending on filer size, so most December year-end companies have
filed by early April.

1. **After each 10-K season** (late April for December year-ends), set
   `SEC_USER_AGENT` and run `python run_pipeline.py`. It downloads the
   latest files and rebuilds every table, the scores and the sample.
2. Run `pytest`, then compare the new counts in `data/logs/` with this
   README and update them.
3. **When a new fiscal year is complete**, raise `LAST_FISCAL_YEAR` in
   `config.py` and section 2 of `CLAUDE.md` together, as a team
   decision. It is fixed on purpose so the universe does not move between
   runs.
4. Rerun `python docs/screenshots/capture_screenshots.py` (and add
   `--source full` for the full-data set) so the backup slides match the
   live app.
5. Restart the app: it reads the new tables on start.
