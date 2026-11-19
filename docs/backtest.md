# Backtest: does the flag count predict stock returns?

**This is an analysis for a class project (AC 547), not investment
advice.** It tests whether the Earnings Quality Radar's warning count
lined up with later stock returns over 2021 to 2026. It does not show
that the flags cause returns, and its biases (below) are large enough
that the results should not be used to trade.

Reproduce: `python -m src.scores.backtest` (about a minute; reads
`data/processed/` and runs both windows in `config.BACKTEST_WINDOWS`,
2021-2025 as specified and 2014-2025). Code: `src/scores/backtest.py`; tests with a
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

## 12 years and a fairer comparison (2014-2025)

Added 2026-11-19. Five periods cannot separate skill from luck, and SPY
is a large-company index while every portfolio here weights companies
equally, so beating or trailing SPY partly measures company size. Two
changes address this:

- **Window `2014_2025`:** the same rules on every June 30 from 2014 to
  2025, 12 periods. 2013 is left out because FY2012 has no F-Score (it
  needs a FY2010 row, which the pipeline does not keep), so a June 2013
  portfolio could hold no best-score or 3-flag companies.
- **Comparison group (`universe`, `equal_weight`):** every company whose
  latest score is usable on the trade date and that passes the same
  price checks, whatever its flags, equal-weighted and rebuilt each June
  30 (1,177 to 1,992 companies a year). A selection that beats this
  group picked better stocks than the pool it came from.

`data/logs/backtest_comparison.csv` compares each portfolio's yearly
returns with the group and with SPY. The t-statistic is the mean yearly
difference divided by its standard error; with 12 years it needs to be
about 2.2 or more before a difference is unlikely to be chance (about
2.8 with 5 years).

| Portfolio, 2014-06-30 to 2026-11-10, 20 bps | Per year | Worst drop | $100,000 becomes | Mean yearly edge over the group | Years ahead of the group | t |
| --- | --- | --- | --- | --- | --- | --- |
| SPY | 13.3% | -33.7% | $469,770 | | | |
| Best scores, long only, held | 11.6% | -38.3% | $388,382 | +2.1 pts | 8 of 12 | 1.0 |
| All three scores, long only | 11.3% | -38.2% | $374,881 | +1.9 pts | 8 of 12 | 1.8 |
| Best scores, long only, sold on a flag | 11.0% | -35.8% | $362,308 | +1.3 pts | 8 of 12 | 0.5 |
| 0 flags, long only | 9.3% | -40.0% | $299,249 | 0.0 pts | 8 of 12 | 0.0 |
| **Comparison group** | 9.0% | -40.4% | $291,789 | | | |
| Long-short strategy, as specified | 6.3% | -66.7% | $214,062 | -3.4 pts | 6 of 12 | -0.3 |
| Short leg alone (every variant) | wiped out in 2020-21 | -100% | $0 | | | |

What this shows:

- **Most of the gap to SPY is the stock pool, not the checks.** The
  comparison group trailed SPY by 3.2 points a year and beat it in 4 of
  12 years.
- **The checks may add about 2 points a year over comparable stocks,**
  but the evidence is weak: requiring all three scores, or the best
  readings, beat the group in 8 of 12 years, with t-statistics of 1.0
  to 1.8. "0 flags" alone (which counts a missing score as no warning)
  added nothing. In 2021-2025 alone the best-scores long leg beat the
  group in all 5 years (t = 2.4), but over 12 years the edge is much
  smaller, so the short window flattered it.
- **No long-only version beat SPY.** The best-scores long leg trailed
  it by 1.1 points a year (6 of 12 years ahead).
- **Selling on a flag cost return over 12 years** (about 0.6 points a
  year for best scores), while making the worst drop slightly smaller.
- **Shorting failed.** In 2020-21, 9 of the 12 shorts rose (Senseonics
  +885%), so the short-only portfolio lost everything and the long-short
  strategy fell 67% from its peak. Accounts that reach zero are closed
  at zero, not carried negative (see Method).
- **The bias is worse in early years.** Among companies with a usable
  score, 56% had no current ticker in 2014 against 13% in 2025, so early
  years cover mostly survivors, in both the selections and the
  comparison group (`data/logs/backtest_universe_status.csv`).

## Test register

Every additional test on the same years raises the chance that a
"winning" version is luck. This register lists every test run, in
order, and whether it was chosen before or after seeing earlier results.
New tests are written here and committed **before** they are run, and
every registered test is reported, whatever it shows.

| # | Test | Chosen | Status |
| --- | --- | --- | --- |
| 1 | Long-short, 0 flags vs 3 flags, 2021-2025, as specified | Before any result | Reported above |
| 2 | Long leg requiring all three scores | Before any result (planned with test 1) | Reported above |
| 3 | Long only, best scores | After seeing test 1 | Reported above; exploratory |
| 4 | Selling a long on a flag | After seeing test 1 | Reported above; exploratory |
| 5 | Formation from 2013 (scratch run) | After seeing tests 1-4 | Dropped: FY2012 has no F-Score, so 2013 could not be tested; replaced by 2014 |
| 6 | 2014-2025 window and the equal-weighted comparison group | After seeing tests 1-4 | Reported above |
| 7 | Value tilt, tests V1 to V3 below | Registered 2026-11-19, before any value-portfolio return was computed | Run 2026-11-19; no registered test passed (results below) |
| 8 | Best-score value stocks (V3) against the whole value group (V1) | After seeing test 7 | Exploratory: t = 2.20, at the pass mark, but not registered |

Tests 3, 4 and 6 were chosen after seeing results, so they are
exploratory: they suggest ideas but cannot confirm them.

### Test 7: value tilt (registered before running)

Background: Piotroski (2000) applied the F-Score to high book-to-market
("value") companies and reported its strongest results there. Our
portfolios ignore price, so this tests whether the checks add more
within value stocks. Verify the paper's details against the original
before citing them.

- **Value measure.** Book-to-market = `stockholders_equity` from the
  10-K behind the company's latest score (the `financials_annual` row)
  divided by that same 10-K's cover-page public float
  (`dei:EntityPublicFloat`: the market value of shares held by
  non-insiders on the last day of the second fiscal quarter). The float
  is read from `data/raw/companyfacts.zip` and matched by accession
  number, so it is known when the 10-K is filed and traces to the
  filing. Adjusted prices are not used, because they are scaled for
  later splits and dividends and would use future information.
  Companies with book equity of zero or less, or no public float in
  that 10-K, get no value rank and are counted.
- **Value group.** On each formation date, the fifth (quintile) of the
  comparison group with the highest book-to-market, among companies
  that have one.
- **Portfolios** (long only, equal-weighted, held to the next June 30,
  20 bps, same eligibility rules):
  - V1 `value`: every company in the value group (the control);
  - V2 `value_strong_f`: value group and F-Score strong (7 to 9; the
    team's band, not Piotroski's 8 to 9, to avoid tuning a cutoff);
  - V3 `value_best`: value group and best scores (M-Score not flagged,
    Z'' safe, F-Score strong).
- **Questions and pass mark.** (a) Does V2 beat V1? This is Piotroski's
  question: does a strong F-Score pick better value stocks? (b) Do V2
  and V3 beat the comparison group and SPY? Evidence window: 2014-2025
  (12 years); 2021-2025 is reported but not used as evidence. A result
  counts as evidence only if the yearly-difference t-statistic is at
  least 2.2.
- **No tuning afterwards.** The quintile, the F band, the value measure
  and the window are fixed here. Any change after seeing results must be
  added to this register as a new, exploratory test.

### Test 7 results

Data check, made before any value-portfolio return was computed: 98.5%
of scored company-years from FY2013 on have a public float. About 4% of
floats are dated outside the usual window (about 6 months before fiscal
year-end; some look like tagging errors in the date, such as AMD's FY2025
10-K, which dates its float 2024-06-28). They are used as reported,
because each comes from the 10-K itself, so none uses later information.
In the 2014-2025 comparison group, 16,530 company-years were ranked;
2,117 had book equity of zero or less, 318 a zero float and 258 no float
(`data/logs/backtest_value_ranks.csv`). The value group held 210 to 339
companies a year.

| 2014-06-30 to 2026-11-10, 20 bps | Stocks a year | Per year | Worst drop | $100,000 becomes |
| --- | --- | --- | --- | --- |
| SPY | | 13.3% | -33.7% | $469,770 |
| V3 value and best scores | 3 to 15 | 13.5% | -42.5% | $477,674 |
| V2 value and strong F-Score | 8 to 37 | 8.9% | -49.1% | $288,617 |
| V1 value group | 210 to 339 | 7.1% | -53.9% | $233,572 |
| Comparison group | 1,177 to 1,992 | 9.0% | -40.4% | $291,789 |

| Registered question (2014-2025, yearly differences) | Mean | Median | Years ahead | t | Passes (t >= 2.2)? |
| --- | --- | --- | --- | --- | --- |
| (a) V2 beats V1 | +5.2 pts | -0.6 pts | 6 of 12 | 0.73 | No |
| (b) V2 beats the comparison group | +4.2 pts | | 5 of 12 | 0.46 | No |
| (b) V2 beats SPY | +1.0 pts | | 2 of 12 | 0.09 | No |
| (b) V3 beats the comparison group | +5.8 pts | | 9 of 12 | 1.44 | No |
| (b) V3 beats SPY | +2.6 pts | | 5 of 12 | 0.39 | No |

What this shows:

- **No registered test passed.** A strong F-Score did not reliably pick
  better value stocks here, so this backtest does not reproduce
  Piotroski's (2000) main result. Our sample differs from his (recent
  years, current tickers only, the team's 7-to-9 band, public float
  instead of full market value), so this is not evidence against the
  paper.
- **One year drives the averages.** In 2020-21 the value portfolios rose
  91% (V1), 169% (V2) and 110% (V3). Without that year, V2 trailed the
  comparison group by 4.6 points a year (t = -1.95) and V3 led it by 2.5
  (t = 0.99). This is why the mean differences are large while the
  medians and years-ahead counts are not.
- **V3 matched SPY's return with much more risk.** It ended slightly
  ahead of SPY ($477,674 against $469,770) with a deeper worst drop
  (-42.5% against -33.7%), beat SPY in only 5 of 12 years, and held
  just 3 to 15 stocks a year, so a few companies decided each year.
- **Exploratory only (test 8):** V3 beat the whole value group in 9 of
  12 years (t = 2.20, mean +6.8 points). This comparison was not
  registered, and test 7 ran five comparisons, so one reaching the pass
  mark by chance is not surprising. Treat it as an idea for a new test
  on new data, not a finding.

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
