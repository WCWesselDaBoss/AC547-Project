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

**facts_long** (`facts_long_drops.csv`): 2,433,288 rows kept, 1,196,485 of
them originally reported values. Dropped facts: 9,200,448 not from a 10-K
or 10-K/A; 545,501 not an annual period; 297,340 a second tag for a period
the company's preferred tag already covers; 222,892 outside FY2011-FY2025;
32,322 in units other than USD or shares; 164 with the wrong unit or
period type for the line item.

**financials_annual** (`financials_annual_log.csv`): 74,868 company-years.
FY2012-FY2025: 39,853 pass the $100M size floor, 28,550 fail (kept as
possible prior years), 475 cannot be tested. 1,800 10-K years with no
facts and 167 duplicate fiscal-year labels were dropped; 3,626
comparative-only years were added.

**prices** (`prices_coverage.csv`): of 5,493 scored companies, 2,705 have
an SEC common-stock ticker and 2,606 have full price history. 2,414 of the
2,422 scored companies that stopped filing by FY2023 have no prices
(survivorship bias; see `docs/methodology.md`). Six tickers were removed
for invalid adjusted prices and seven returned no data.

## Verification

`verification/phase1_tieout.csv` lists revenue, net income, total assets
and CFO for Apple, Walmart and Coca-Cola (FY2024) as stored by the
pipeline, with the XBRL tag and filing link, for comparison with each
10-K by hand. **All 12 values matched the 10-Ks** (checked by hand on
November 11, 2026). The three companies cover September (Apple), January
(Walmart, labeled FY2024 under the Compustat convention) and December
(Coca-Cola) fiscal year ends.
