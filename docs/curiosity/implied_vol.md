# Curiosity, part 2: did put prices on flagged stocks underestimate crashes?

**Not part of the class project's test register** (`docs/backtest.md`).
Part 1 (`vol_matched.md`) found that flagged stocks fell 30% or 50% more
often than their own trailing volatility predicts. The options market
prices crash risk through implied volatility, so the question here is
whether put prices already reflected that extra risk. This is an
analysis for a class project, not investment advice.

**Licensed data.** The OptionMetrics data from WRDS stays in
`data/raw/wrds/` (gitignored) and is never committed. At most 5 raw rows
are ever printed to the screen; only summary results are written to
docs, and the details file holds derived values per observation, not raw
WRDS rows.

Definitions fixed before any result was computed.

## Data

Each file is read by its exact name, never with a wildcard.

- **Volatility surface:** `data/raw/wrds/vsurf_puts_730d.csv.gz`,
  OptionMetrics standardized options (`optionm.vsurfd`), 730-day puts at
  delta -50 and -25, 2013-07-22 to 2024-06-28 (checked in step 1: only
  those days, deltas and put flags; 3,595,528 rows, 820 secids).
- **Name history:** `data/raw/wrds/secnmd_names.csv.gz`, OptionMetrics
  security names (`optionm.secnmd`) for the 820 secids in the surface
  file, used to confirm matches (4,146 rows; every secid present; no
  missing issuer names).
- **Security prices (pending approval; see analyses 3 to 5):**
  OptionMetrics daily security prices (`optionm.secprd`: close and the
  cumulative adjustment factor `cfadj`) for the same secids, 2013-07-01
  to 2026-07-31.

## Definitions

- **Observations.** The 4,783 observations of part 1
  (`src/curiosity/vol_matched.py`): the same start dates, reference
  prices, trailing volatilities, drops and 24-month follow-up, reused
  from that module, not recomputed.
- **Usable surface row.** Implied volatility present, and strike and
  premium both above zero. A strike or premium of -99.99 (OptionMetrics'
  missing-value code) or 0 counts as missing. Applied to each delta
  separately.
- **Issue type.** The OptionMetrics `issue_type` code "F" means ADR/ADS
  (IvyDB US Reference Manual v5.0, Security file, Issue Type: 0 common
  stock, A market index, 7 mutual or investment trust fund, F ADR/ADS,
  % exchange-traded fund, S structured product, U unit, blank
  unspecified). Step 1 found 4 secids with "F". Matched observations
  that carry it are kept and counted, because our companies all file
  10-Ks and an ADR match is unusual.
- **Matching.** Both ticker fields are current tickers (the surface
  file's ticker is "the security's current ticker symbol" in the
  manual; ours are current SEC tickers). For each observation:
  1. Candidates: the secids whose surface-file ticker equals the
     company's ticker.
  2. For each candidate, the name-history row in effect on the
     observation's start date (the latest row with an effective date on
     or before the start).
  3. Name similarity between that name and the SEC company name: both
     names upper-cased, punctuation removed, and the words THE, INC,
     INCORPORATED, CORP, CORPORATION, CO, COMPANY, LTD, LIMITED, PLC,
     LLC, LP, HOLDINGS, HOLDING, GROUP, CLASS, CL, A, B and NEW dropped;
     similarity = Python's `difflib.SequenceMatcher` ratio of what is
     left. A match is accepted if the ratio is at least 0.85, or one
     cleaned name contains the other.
  4. Tickers with two secids: use the candidate whose name-history
     dates cover the start date and whose name passes the check. If
     both or neither pass, the observation is rejected and counted.
  5. Every company whose best candidate falls below the threshold is
     written, with both names and the ratio, to
     `data/raw/wrds/name_review.csv` (gitignored, because it contains
     licensed names), and at most 5 are printed. A pair is used only if
     approved by hand in that file before any result is computed;
     otherwise it is rejected and counted, never forced.
- **Fallback.** For each delta, the usable surface row on the start
  date; if there is none, the usable row on the closest earlier market
  trading day within 5 trading days (SPY's calendar); never a later
  day. Otherwise the observation has "no option data" for that delta,
  counted by group. The day used is the "option date".
- **Tradeability.** For Clean, Flagged, 2 flags and 3 flags: how many
  observations matched, how many have delta -50 data, and how many have
  delta -25 data.

## Analyses

1. **Implied-volatility benchmark.** Part 1's method 3 with implied
   volatility (delta -50, 730 days) in place of trailing volatility:
   P = 2 x N(ln(1 - d) / (sigma x sqrt(2))), actual against average
   predicted share reaching 30% and 50% drops within 24 months, by group
   (Clean, Flagged, 0 to 3 flags).
2. **Cox regression.** Part 1's method 2 with the log of implied
   volatility in place of the log of trailing volatility: Flagged and
   log implied volatility, Efron ties, standard errors clustered by
   company (statsmodels `PHReg`). The key result: whether Flagged's
   hazard ratio stays above 1 once the options market's own volatility is
   held equal. For comparison, part 1's trailing-volatility model is
   rerun on the same matched observations, so a change in the hazard
   ratio cannot come only from the smaller sample.
3. **Put held to expiry (exact, no model).** Buy the 730-day put at
   `impl_strike` for `impl_premium` on the option date; expiry is the
   last market trading day on or before the option date plus 730 days.
   Payoff = max(strike - stock price at expiry, 0). Return per dollar of
   premium = (payoff - premium) / premium. Reported for Clean, Flagged
   and 0 to 3 flags (mean, median and share with a positive return), at
   delta -50 and delta -25.
   - **Prices (pending approval).** Strike and premium are in dollars
     as of the option date, but Yahoo adjusted closes are rescaled for
     every later split and dividend, so the two cannot be compared
     directly. The stock price at expiry is therefore taken from
     OptionMetrics `secprd`, converted to option-date share units with
     the adjustment factor: price at expiry x cfadj at expiry / cfadj on
     the option date. This corrects for splits, as option contracts do,
     and not for dividends, as option payoffs do not. If prices stop
     before expiry, the put is valued at its intrinsic value on the last
     price day, and the observation is counted.
   - If `secprd` is not used, analyses 3 to 5 are not run, and only
     analyses 1 and 2 are reported.
4. **Put with an exit rule (approximate).** Sell when the stock first
   closes 30% or more below the reference price (the option-date close
   from `secprd`, in the same split-adjusted units), or at expiry. At an
   early exit, value the put two ways:
   - intrinsic value, max(strike - price, 0): a lower bound, because a
     put with time left is worth at least its exercise value;
   - Black-Scholes, using the option date's implied volatility, the
     remaining time to expiry, and an interest rate and dividend yield
     of zero: an estimate, because the real implied volatility at the
     exit (usually higher after a crash), interest rates and dividends
     all differ.
5. **Costs.** Analyses 3 and 4 repeated with the purchase price raised
   5% and 10% above `impl_premium`, to stand in for paying the ask
   rather than the mid price.

## Limitations, stated in advance

- Standardized options are interpolated from listed options and may not
  correspond to any contract that traded; `impl_premium` is a mid price.
- Survivorship: current tickers only.
- Companies without listed options are excluded, and they are likely
  the riskiest.
- Years already studied in tests 1 to 12 and part 1.
- Interest rates and dividends are simplified (zero in the Black-Scholes
  estimate; dividends ignored in the hold-to-expiry payoff, as in a real
  put).
- Correlation, not cause. Not investment advice.

## Outputs

These results, whatever they show; charts in `docs/curiosity/`; details
in `data/logs/curiosity_implied_vol.csv` (derived values per
observation, no raw WRDS rows). Code: `src/curiosity/implied_vol.py`.
Tests: `tests/test_curiosity.py` (put payoff at expiry on a hand-checked
example, the exit rule on a fake price path, and the fallback rule: a
missing start date filled from 2 days earlier, never from a later day).
