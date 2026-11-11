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
| ticker | string (nullable) | First ticker SEC lists; null if none (often delisted) | submissions `tickers[0]` |
| is_excluded | bool | True if any exclusion rule applies | `companies.exclusion_reasons` |
| exclusion_reason | string (nullable) | All reasons, joined with "; " | `companies.exclusion_reasons` |

Exclusion reason values: `financial_sic_6000_6799`, `sic_missing`,
`no_10k_filings`, `no_submissions_record`.
