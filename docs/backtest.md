# Backtest: does the flag count predict stock returns?

**This is an analysis for a class project (AC 547), not investment
advice.** It tests whether the Earnings Quality Radar's warning count
lined up with later stock returns over 2021 to 2026. It does not show
that the flags cause returns, and its biases (below) are large enough
that the results should not be used to trade.

Reproduce: `python -m src.scores.backtest` (about 20 seconds; reads
`data/processed/`). Code: `src/scores/backtest.py`; tests with a
hand-checked example: `tests/test_backtest.py`; settings:
`config.py` ("Long-short backtest"). Results:
`data/processed/backtest_results.parquet` (columns in
`docs/data_dictionary.md`) and `data/logs/backtest_*.csv`. Figures below
come from the run on 2026-11-19 with prices through 2026-11-10.

## Method

| Choice | Rule | Why |
| --- | --- | --- |
| Formation dates | June 30 of 2021 to 2025; trades on the last trading day on or before June 30 (2024-06-28 in 2024) | By June 30 nearly all December fiscal-year 10-Ks are public |
| Information used | Each company's latest score whose 10-K `filed_date` (from `financials_annual`) is strictly before the trade date, and at most 15 months old | Nothing filed on or after the trade date is used; an old score from a company that stopped filing is not used |
| Long leg | `flags_raised` = 0 | As specified |
| Short leg | `flags_raised` = 3 (M-Score above -1.78, Z'' distress zone and F-Score weak band) | As specified |
| Long leg variant | `all_three_scores`: 0 flags **and** an M-Score, a Z'' and an F-Score all exist | `flags_raised` counts a missing score as "no warning", so a company with only a safe Z'' has 0 flags. A 3 always needs all three scores, so the variant holds both legs to the same evidence standard |
| Long leg variant | `best_scores`: every check at its best: M-Score not flagged, Z'' safe (above 2.60) and F-Score strong (7 to 9) | 0 flags still allows a grey-zone Z'' and a middle F-Score; this asks for the best reading of all three. Added 2026-11-19 at the team's request |
| Sell on a flag (long only) | `long_only_sell_on_flag`: a long is sold at the close of the first trading day after a newer 10-K, filed during the holding year, raises any warning (`flags_raised` >= 1); the money waits in cash until the next June 30 | The first day an investor could act on the filing. A 10-K that is merely less than best (say an F-Score falling from 7 to 6) raises no flag, so the stock is held. Its exit trading cost is charged on the period's last day (same amount, slightly different timing in the daily path) |
| Eligibility | A current SEC ticker; a price on each of the last 20 trading days; adjusted close of at least $5 | Penny stocks are hard to short |
| Sizing | $100,000: $50,000 long and $50,000 short, equal-weighted within each leg | Dollar neutral |
| Holding | Buy and hold until the next formation date, then sell everything and rebuild the portfolio (50/50 again); the final period runs to the last SPY price (2026-11-10, about 16 months) | As specified |
| Prices | Adjusted close (dividends and splits included) | As specified |
| Delisting | A stock whose prices stop is exited at its last real price; the money then earns nothing | No price is ever invented |
| Costs | 0 or 20 bps on every dollar traded (entry and exit, even for a stock held in both periods, which overstates costs slightly); 1% a year on the short leg's starting value, pro-rated by days, at **both** cost levels | A short seller always pays to borrow |
| Benchmark | $100,000 in SPY bought 2021-06-30 and held to 2026-11-10, no costs | As specified |
| Each leg alone | $100,000 fully long, or fully short, in the same stocks | Comparable with SPY's $100,000 |
| Empty leg | A leg with no eligible stocks holds cash: no trading cost and no borrowing fee | Cash is neither traded nor borrowed |
| Wiped out | If the account's value reaches 0 or below (shorts owing more than everything it holds), it is closed: the value stays at 0 and later periods hold nothing | A broker would close the account; a negative balance is never compounded. No portfolio in the 2021-2025 run was wiped out |

## Results

### Ending value of $100,000 (2021-06-30 to 2026-11-10)

| Portfolio | 0 bps | 20 bps + borrow | Total return (20 bps) | Annualized (20 bps) | Max drawdown (20 bps) |
| --- | --- | --- | --- | --- | --- |
| Strategy, as specified | $207,881 | $204,459 | +104.5% | 14.3% | -32.8% |
| Strategy, all three scores | $212,299 | $208,814 | +108.8% | 14.7% | -31.0% |
| Long leg alone, as specified | $129,635 | $127,112 | +27.1% | 4.6% | -27.8% |
| Long leg alone, all three scores | $135,167 | $132,547 | +32.5% | 5.4% | -28.6% |
| Strategy, best scores | $227,726 | $224,014 | +124.0% | 16.2% | -30.3% |
| Long only, best scores, held | $155,944 | $152,962 | +53.0% | 8.2% | -29.2% |
| Long only, best scores, sold on a flag | $157,025 | $154,027 | +54.0% | 8.4% | -26.9% |
| Short leg alone | $276,788 | $272,621 | +172.6% | 20.6% | -89.7% |
| SPY | $187,909 | (no costs) | +87.9% | 12.5% | -24.5% |

The "0 bps" column still includes the 1% borrowing fee. Over the five
periods the strategy (as specified, 20 bps) paid $2,456 in trading costs
and $3,515 in borrowing fees. The short leg is the same in every
variant. Long-only portfolios pay no borrowing fee.

Max drawdown is the largest fall from a previous high in the daily
value. Long legs and SPY bottomed in the 2022 bear market (late
September to mid-October 2022). The strategy and the short leg bottomed on 2026-06-30, when two
2025 shorts had surged: FuelCell (FCEL) traded at 6.4 times its entry
price and Applied Digital (APLD) at 3.7 times. The eight shorts then
owed about 1.9 times the short leg's equity, so the short-only portfolio
fell to about $28,000 before those stocks dropped back. A broker would
have demanded more collateral or closed the positions well before that,
which this backtest does not model (see Limitations).

### Return by year (20 bps + borrow)

Each period runs from one formation date to the next; 2025 runs to
2026-11-10.

| Portfolio | 2021-22 | 2022-23 | 2023-24 | 2024-25 | 2025-26 |
| --- | --- | --- | --- | --- | --- |
| Strategy, as specified | +15.9% | -3.1% | +26.7% | +19.7% | +20.1% |
| Strategy, all three scores | +16.3% | -0.9% | +27.8% | +19.3% | +18.7% |
| Long leg alone, as specified | -20.9% | +14.6% | +6.8% | +3.3% | +27.2% |
| Long leg alone, all three scores | -20.0% | +19.1% | +9.1% | +2.5% | +24.4% |
| Short leg alone | +52.7% | -20.8% | +46.6% | +36.1% | +13.1% |
| SPY | -10.6% | +19.4% | +24.5% | +14.9% | +23.0% |

### Stocks in each leg and hit rates

A long "hits" if its return beat SPY's over the same period; a short
hits if its return was below SPY's. A tie is not a hit. For a delisted
stock the return runs to its exit price.

| Formation | Longs, as specified | Longs, all three scores | Shorts | Longs beating SPY (as specified / all three) | Shorts lagging SPY |
| --- | --- | --- | --- | --- | --- |
| 2021 | 1,074 | 289 | 7 | 36.0% / 34.3% | 7 of 7 |
| 2022 | 1,190 | 307 | 10 | 41.2% / 47.2% | 6 of 10 |
| 2023 | 1,141 | 302 | 10 | 27.3% / 27.8% | 9 of 10 |
| 2024 | 1,149 | 331 | 11 | 33.0% / 32.0% | 9 of 11 |
| 2025 | 1,155 | 320 | 8 | 45.0% / 46.6% | 6 of 8 |
| All | 5,709 | 1,549 | 46 | 36.6% / 37.6% | 37 of 46 (80.4%) |

### What the numbers say

- The strategy beat SPY (14.3% vs 12.5% a year after costs), but
  **almost all of the gain came from the short leg**. The long leg alone
  trailed SPY by about 8 points a year, and most 0-flag stocks
  underperformed SPY in every year. Equal-weighted portfolios of many
  smaller companies lagged a large-company index over this period, so
  this comparison mixes the flags with a size effect.
- The 3-flag stocks did badly: the median short lost between about 10%
  and 66% in each period, and 80% lagged SPY. But the short leg's returns
  rest on 7 to 11 stocks a year and swing widely: in 2022-23
  TransMedics (+167%), Blue Bird (+144%) and Norwegian Cruise Line
  (+96%) rose sharply and the short leg lost 21%.
- The stricter long leg (all three scores) did slightly better than the
  one as specified in total, but only in three of the five years, so the
  difference is small and not consistent.

## Long only: best indicators, sold on a flag

No shorting: $100,000 goes into the companies whose three checks are all
at their best (`best_scores`), equal-weighted, and is rebuilt each June
30. The second row also sells a stock as soon as a newer 10-K raises a
warning. 20 bps, no borrowing fee.

| Formation | Stocks bought | Sold after a flag | Held for the year | Sold on a flag | SPY |
| --- | --- | --- | --- | --- | --- |
| 2021 | 45 | 6 | -18.0% | -15.9% | -10.6% |
| 2022 | 90 | 17 | +25.6% | +24.9% | +19.4% |
| 2023 | 61 | 4 | +12.0% | +10.0% | +24.5% |
| 2024 | 88 | 9 | +5.4% | +5.0% | +14.9% |
| 2025 | 78 | 4 | +25.8% | +27.0% | +23.0% |

Best-indicator candidates over the five years: 362 traded; not traded,
147 with a stale score, 53 with no ticker, 5 with a gap in the last 20
trading days, 10 under $5 and 1 with no prices
(`data/logs/backtest_candidates.csv`).

- **Choosing the best indicators helped.** The best-scores long leg
  returned 8.2% a year against 4.6% for the 0-flag long leg, and beat
  SPY in two of five years (2022 and 2025). It still trailed SPY
  (12.5%) by about 4 points a year. 39.0% of its picks beat SPY.
- **Selling on a flag changed little.** It added 0.1 points a year and
  reduced the worst drop from -29.2% to -26.9%. 40 of 362 positions
  were sold early. The typical sold stock did better sold than held
  (median +1.6% against -10.0% to the rebalance), but a few sold stocks
  rallied afterward, so on average holding would have earned slightly
  more (+6.8% against +5.8%). In the 0-flag long leg (759 of 5,709
  sold) selling helped on both measures; in the all-three-scores leg
  (270 of 1,549) it helped the median but not the mean.
- **One sale checked by hand.** AMD was bought on 2022-06-30 on its
  FY2021 10-K (all three checks at their best). Its FY2022 10-K, filed
  2023-02-27, raised an M-Score flag (likely reflecting the Xilinx
  acquisition, which changes many of the M-Score's year-over-year
  ratios). It was sold on 2023-02-28 at $78.58 against a $76.47 entry,
  +2.76%.
- The best-scores strategy (best longs, 3-flag shorts) earned 16.2% a
  year, the highest of the long-short versions, but its edge over SPY
  still comes mainly from the short leg and its biases.

## Data coverage

Candidates on each formation date and why they were not traded. Counts
are companies with 0 flags (long) or 3 flags (short) in their latest
score.

| Formation | Leg | Traded | Stale score (> 15 months) | No ticker | No prices at all | Gap in last 20 days | Under $5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2021 | long | 1,074 | 677 | 325 | 5 | 10 | 16 |
| 2021 | short | 7 | 20 | 5 | 0 | 0 | 2 |
| 2022 | long | 1,190 | 735 | 360 | 5 | 9 | 95 |
| 2022 | short | 10 | 19 | 12 | 0 | 0 | 3 |
| 2023 | long | 1,141 | 813 | 267 | 6 | 8 | 81 |
| 2023 | short | 10 | 22 | 11 | 0 | 0 | 8 |
| 2024 | long | 1,149 | 877 | 202 | 6 | 8 | 76 |
| 2024 | short | 11 | 32 | 3 | 0 | 1 | 8 |
| 2025 | long | 1,155 | 948 | 132 | 3 | 8 | 110 |
| 2025 | short | 8 | 38 | 3 | 0 | 0 | 9 |

- Dropped for missing prices (no ticker, no prices, or a gap in the
  last 20 days), across the five years: **1,354 long candidates** and
  **35 short candidates**, against 5,709 longs and 46 shorts traded.
- A stale score means the company's latest 10-K is more than 15 months
  old at formation; most such companies have likely stopped filing
  (acquired, delisted or deregistered). This was not checked company by
  company.
- **Delisted mid-period: 0** in every year and leg. This is not good
  news; it is a sign of the first limitation below.

## Limitations

1. **Survivorship and look-ahead bias (the largest problem).**
   - Tickers are today's SEC tickers, and prices were downloaded only
     for them. A company that delisted after a formation date usually
     has no ticker today, so it was left out of that year's portfolio
     even though an investor at the time could have traded it. The
     selection therefore uses information from the future, which is why
     no pick delisted mid-period.
   - The bias is largest for the short leg. In 2022 and 2023, more
     3-flag companies were dropped for having no ticker (12 and 11) than
     were shorted (10 each).
   - The direction of the bias is unknown. Left-out longs that later
     failed would have lowered the long leg. Left-out shorts that
     collapsed would have raised the short leg. Shorts that were
     acquired at a premium would have lowered it.
2. **Short-selling frictions are not modeled.**
   - Hard-to-borrow stocks: distressed small companies often cost far
     more than 1% a year to borrow, or cannot be borrowed at all.
   - Recalls: a lender can recall shares and force a short to close.
   - Margin calls: the 2026 FCEL and APLD surge would have forced
     buy-backs at the worst prices, so the simulated short leg could not
     actually have been held through it.
   - Collateral: short-sale proceeds and freed cash earn no interest
     here, while in practice they earn a rebate.
3. **Small sample.**
   - There are five annual periods, the last one only partly a year, and
     7 to 11 shorts a year, 46 short positions in all. One or two stocks
     can decide a year's result.
   - There is no test of statistical significance, and five overlapping
     market years cannot support one.
4. **Correlation, not cause.**
   - The 3-flag companies are financially weaker by construction (Z''
     distress zone, weak F-Score) and are likely smaller and more
     volatile than the 0-flag companies (not measured here), and the 2021-2026 market (the 2022 drop and the
     later rally led by large companies) treated those groups
     differently for reasons that may have nothing to do with earnings
     quality.
   - A difference in returns does not show that the flags predict
     returns in other periods.
5. **Smaller points.**
   - The $5 test uses adjusted closes, which sit below the price
     actually traded for older dates, so slightly more stocks are
     excluded than with raw prices.
   - Trading costs are charged on the whole portfolio at each rebalance,
     including stocks held in both periods, which overstates costs.
   - SPY pays no costs.
   - The price data contain occasional one-day spikes, mostly in thinly
     traded tickers; none affects a stock picked here.
   - Scores come from original (not restated) 10-K values, as the
     dashboard does.
