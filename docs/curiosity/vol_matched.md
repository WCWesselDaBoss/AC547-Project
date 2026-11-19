# Curiosity: do the flags predict large drops beyond volatility?

**Not part of the class project's test register** (`docs/backtest.md`).
A side question: tests 10 to 12 found that flagged stocks fall 30% or
50% more often, but flagged companies are also more volatile, and
volatile stocks touch any lower price more often. Do the flags add
information beyond a stock's own volatility? This is an analysis for a
class project, not investment advice.

Definitions fixed before any result was computed.

## Definitions

- **Observations.** Exactly test 11's eligible observations: scored
  company-years with an M-Score, a Z'' and an F-Score, original 10-K
  filed through 2024-06-30, the same eligibility checks, the same start
  day (first market trading day on or after the filing date) and
  reference price (the stock's adjusted close that day), and the same
  24-month follow-up and censoring. The code reuses test 11's functions
  (`src/scores/time_to_drop.py`) rather than rewriting them.
- **Trailing volatility.** The annualized standard deviation of daily
  log returns of adjusted close over the 252 market trading days ending
  the day before the start: daily standard deviation (sample, n - 1) x
  the square root of 252. A daily log return is ln(close that day /
  close the previous market trading day) and counts only when the stock
  has a price on both days. At least 200 valid daily returns are
  required; otherwise the observation is excluded and counted.
- **Volatility buckets.** Quintiles (five equal-sized groups) of trailing
  volatility across all observations pooled. The cutoffs and the number
  of Clean and Flagged observations in each bucket are reported. A
  bucket with fewer than 30 Clean or fewer than 30 Flagged observations
  is marked "too few to compare" and left out of the volatility-adjusted
  gap (method 1).
- **Drops.** 30% and 50%, defined exactly as in tests 11 and 12: the
  first close after the start at or below 70% or 50% of the reference
  price within the 24-month follow-up.
- **Groups.** Clean (`flags_raised` = 0) and Flagged (1 or more); also
  0, 1, 2 and 3 flags as a descriptive breakdown.

## Three ways to answer the question

1. **Within-bucket comparison.** For each bucket and drop size: the
   24-month share that dropped (Kaplan-Meier, as in tests 11 and 12) for
   Clean and Flagged, the gap (Flagged minus Clean, in points) and the
   ratio (Flagged / Clean). Then a volatility-adjusted gap: the average
   of the within-bucket gaps, weighted by each bucket's total
   observations, over the buckets that are not "too few to compare".
2. **Regression.** A Cox proportional hazards model of time to each
   drop, with Flagged (0 or 1) and the natural log of trailing
   volatility as inputs, ties handled by the Efron method, and standard
   errors clustered by company (one company appears in several years).
   Reported: the hazard ratio for Flagged with its 95% confidence
   interval and p-value. In plain English: a hazard ratio of 1.5 means
   flagged stocks reached the drop at 1.5 times the rate of clean stocks
   with the same volatility. Library: statsmodels 0.15.0 (`PHReg`, with
   company as the clustering groups), added to `requirements.txt` with
   `wrapt` pinned to the stable 2.5.2 (otherwise pip picks a
   pre-release). `lifelines` is not used because it cannot be installed
   with the project's pandas 3 (test 11, change 11a).
3. **Volatility-only benchmark.** For each observation, the chance of
   touching the drop within 24 months that a simple model predicts from
   volatility alone: P = 2 x N(ln(1 - d) / (sigma x sqrt(2))), where d
   is the drop size, sigma the trailing volatility, 2 the years and N
   the standard normal cumulative distribution. For each group (Clean,
   Flagged, and 0 to 3 flags), the actual share that dropped (drops /
   observations; censoring only at the end of follow-up, as found in
   test 11) is compared with the average predicted P. If Flagged stocks
   drop more often than their own volatility predicts and Clean stocks
   do not, the flags carry information beyond volatility. This model
   assumes no drift (no expected rise or fall in the log price) and
   normally distributed returns, so it ignores trends and the fat tails
   of real returns: it is a rough yardstick, not a price.

## Robustness check

Reported alongside method 1, not in place of it: method 1 repeated with
daily log returns clipped at the 1st and 99th percentiles of all daily
returns in all observations' volatility windows (pooled) before
volatility is computed, because one-day price glitches can inflate
volatility. The buckets are re-formed from the clipped volatilities.

## Limitations, stated in advance

- **Survivorship.** Current tickers only, so companies that crashed and
  delisted are mostly missing.
- **Years already studied** in tests 1 to 12; this question was chosen
  after seeing their results.
- **Historical volatility is not implied volatility.** Options are
  priced on implied volatility, which usually includes an extra charge
  for crash protection, so even a positive result does not show that
  buying puts on flagged stocks would profit.
- **Correlation, not cause.** Not investment advice.

## Outputs

These results, whatever they show; a chart of the 24-month drop share by
volatility bucket, Clean and Flagged side by side, for each drop size
(`docs/curiosity/vol_buckets.png`); details in
`data/logs/curiosity_vol_matched.csv`. Code: `src/curiosity/vol_matched.py`.
Tests: `tests/test_curiosity.py`.
