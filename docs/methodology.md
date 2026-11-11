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
