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
- **Security prices (approved and downloaded 2026-11-19, for analyses 3
  to 5):** `data/raw/wrds/secprd_prices.csv.gz`, OptionMetrics daily
  security prices (`optionm.secprd`: secid, date, close, volume and the
  cumulative adjustment factor `cfadj`) for the same 820 secids. Checked
  before use: 2,175,245 rows, every secid present, no missing values, no
  duplicate secid-date rows; it runs from 2013-07-01 to **2025-08-29**
  (the last date in the file, not the 2026-07-31 requested); 10 secids'
  prices end before that date; 2,134 rows have a negative close and 1 a
  zero close (see below).

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
   - **Prices.** Strike and premium are in dollars as of the option
     date, but Yahoo adjusted closes are rescaled for every later split
     and dividend, so the two cannot be compared directly. The stock
     price at expiry is therefore taken from OptionMetrics `secprd`,
     converted to option-date share units with the adjustment factor:
     price at expiry x cfadj at expiry / cfadj on the option date. This
     corrects for splits, as option contracts do, and not for dividends,
     as option payoffs do not.

   **Price rules for analyses 3 to 5 (added 2026-11-19, after the
   security prices were checked and before any analysis 3 to 5 result
   was computed):**
   - **Negative and zero closes.** A negative close is the average of
     the closing bid and ask on a day without a trade (IvyDB US
     Reference Manual v5.0, Security_Price file, Close Price), so its
     absolute value is used as that day's price. A zero close counts as
     no price that day.
   - **Split adjustment.** `cfadj` is the cumulative split factor
     (dividends are in a separate factor not used here); the manual's
     conversion, close x cfadj that day / cfadj on another day, gives
     the price in that other day's share units, which is the formula
     above.
   - **Price on a day.** The close on that day; if the security has no
     price row that day, the latest earlier row within 5 trading days.
   - **Not yet expired in the data.** The price file ends on
     2025-08-29. A put whose expiry (the last market trading day on or
     before the option date plus 730 days) falls after that date is "not
     yet expired in the data": it is counted by group and left out of
     analyses 3 to 5. It is never valued at the last available price.
   - **Prices that stop for the security.** If a security's own prices
     stop before its expiry while the file continues past that expiry
     (for example a delisting), the put is valued at its intrinsic value
     on the security's last price day and counted separately. This was
     the original rule for prices that stop; it now applies only to a
     security's own prices stopping, not to the end of the file.
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

## Results (run 2026-11-19)

Run with `python -m src.curiosity.implied_vol --results` (matching
alone: without `--results`). Everything above this section was committed
before any result was computed. Only summary results are shown here; no
raw OptionMetrics rows.

**Short answer: the options market already priced most of it.** Once
each stock's implied volatility is held equal, the flags no longer add a
statistically clear signal about 30% or 50% drops. With trailing
volatility on the same observations they still do (part 1's result).

### Matching and the name review

- 4,513 of the 4,783 observations were matched to an OptionMetrics
  security. Not matched: 261 whose ticker is not in the WRDS data, 5
  ambiguous (two secids of one ticker both passed the name check), 3
  whose name did not match, and 1 with no name history on the start
  date.
- **The hand review was delegated to Claude by the user** (2026-11-19).
  Of the 131 pairs below the name threshold, 128 were approved and 3
  rejected, using two pieces of evidence recorded in the gitignored
  review file: one of the company's former SEC names matches the WRDS
  name (77 pairs), or the security's own name history later carries
  today's SEC name (125 pairs; OptionMetrics security IDs are never
  recycled, so this is a renamed security, not a reused ticker). Every
  approval rested on a similarity of at least 0.85 or a shared name of
  at least 6 letters; a random sample of 5 was checked by eye. The 3
  rejected pairs had neither kind of evidence and are different
  companies using the same ticker. Each decision and its basis is noted
  in the review file.
- 23 matched observations are on a security that OptionMetrics codes as
  an ADR/ADS (issue type F). They were kept, as the definitions say.

### Tradeability

| Group | Observations | Matched | With delta -50 data | With delta -25 data |
| --- | --- | --- | --- | --- |
| Clean | 3,094 | 2,916 | 2,839 | 2,839 |
| Flagged | 1,689 | 1,597 | 1,478 | 1,480 |
| 2 flags | 420 | 394 | 350 | 351 |
| 3 flags | 80 | 77 | 66 | 66 |

About 92% of Clean and 88% of Flagged observations have delta -50 option
data (83% for 3 flags). The analyses below use the 4,317 observations
with delta -50 data (790 companies). Those without it are excluded and,
as the limitations note, may be among the riskiest.

![Actual vs predicted drops](implied_vol_benchmark.png)

### Analysis 1: implied-volatility benchmark

Actual share that dropped within 24 months against the average chance
predicted by the zero-drift formula, from implied volatility and, on the
same observations, from trailing volatility:

| Group | Observations | 30% drop: actual | Predicted (implied) | Actual / predicted (implied) | Actual / predicted (trailing) | 50% drop: actual | Predicted (implied) | Actual / predicted (implied) | Actual / predicted (trailing) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Clean | 2,839 | 42.7% | 45.3% | 0.94 | 0.95 | 17.9% | 17.3% | 1.03 | 0.99 |
| Flagged | 1,478 | 59.1% | 58.7% | 1.01 | 1.01 | 34.9% | 32.2% | 1.08 | 1.07 |
| 1 flag | 1,062 | 55.0% | 55.6% | 0.99 | 0.99 | 29.4% | 28.3% | 1.04 | 1.01 |
| 2 flags | 350 | 69.4% | 66.2% | 1.05 | 1.06 | 48.9% | 41.6% | 1.17 | 1.19 |
| 3 flags | 66 | 69.7% | 69.6% | 1.00 | 1.03 | 50.0% | 45.8% | 1.09 | 1.16 |

- Implied volatility predicts the groups' drop rates about as well as
  trailing volatility, and both come close: Flagged stocks dropped 30%
  almost exactly as often as predicted (1.01).
- The clearest excess is for 50% drops with 2 flags: 48.9% actual
  against 41.6% predicted from implied volatility (1.17), on 350
  observations. The 3-flag group (66 observations) is too small to read
  much into.

### Analysis 2: Cox regression, implied vs trailing volatility

Same 4,317 observations, Flagged and the log of volatility as inputs,
Efron ties, standard errors clustered by company (790):

| Drop | Volatility held equal | Hazard ratio for Flagged | 95% interval | p-value |
| --- | --- | --- | --- | --- |
| 30% | Implied (options market) | 1.08 | 0.97 to 1.20 | 0.15 |
| 30% | Trailing (price history) | 1.18 | 1.07 to 1.31 | 0.0013 |
| 50% | Implied (options market) | 1.09 | 0.94 to 1.27 | 0.26 |
| 50% | Trailing (price history) | 1.22 | 1.06 to 1.41 | 0.0057 |

- **The key result:** with the options market's own volatility held
  equal, Flagged's hazard ratio falls to about 1.08 to 1.09 and its
  interval includes 1, so the flags no longer show a clear extra risk.
  With trailing volatility on the same observations, the extra risk
  remains (1.18 to 1.22), so the change comes from switching to implied
  volatility, not from the smaller sample.
- In plain English: put prices on flagged stocks were already high
  enough to reflect most of their extra crash risk. Implied volatility
  also predicts drops more strongly than trailing volatility does
  (hazard ratios per unit of log volatility of 4.0 and 7.6, against 3.1
  and 5.8).
- Absence of a clear signal is not proof of none: the point estimates
  are still above 1, and the 50% drop with 2 flags stands out in
  analysis 1.

### Analyses 3 to 5: not run

The put-payoff analyses need OptionMetrics security prices
(`optionm.secprd`), because strike and premium are in dollars of the
option date while Yahoo adjusted closes are rescaled for later splits
and dividends. That file was not downloaded, so, as the definitions say,
analyses 3 to 5 are not run. The tested put arithmetic is ready in
`src/curiosity/implied_vol.py` if the prices are added later.

### What this means

- Part 1 found that the flags signal crash risk beyond a stock's past
  volatility. Part 2 suggests the options market already knew: once
  implied volatility is held equal, little extra risk remains. This is
  consistent with the flags summarizing public information that option
  traders also use.
- For the project, this supports presenting the flags as a transparent,
  explainable risk screen, not as a source of trading profits.

### Limitations

Those stated in advance (interpolated standardized options and mid
prices; current tickers only; companies without listed options
excluded; years already studied; simplified rates and dividends;
correlation, not cause), plus: the name review was made by Claude on the
user's instruction rather than by a person, using the recorded evidence
above. Not investment advice.

