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

The ticker is the first one SEC lists; companies with none are left blank
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
