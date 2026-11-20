# Curiosity: do flagged companies' stocks fall more after a warning filing?

**Not part of the class project's test register** (`docs/backtest.md`).
When a company files a warning sign with the SEC (a late-filing notice
or an auditor change), do the stocks of companies our checks had
flagged fall more afterward than those of clean companies? Public data
only: the SEC submissions bulk file and the project's price table. This
is an analysis for a class project, not investment advice.

Definitions fixed before any result was computed; exploratory.

## Data

- **Filings:** `data/raw/submissions.zip` (SEC bulk file), every filing
  listed for the companies in the universe (the `companies` table, not
  excluded), including each company's older filings in the overflow
  files. The submissions data lists each 8-K's item numbers, so no 8-K
  document is downloaded.
- **Scores:** `scores`, with each score's 10-K filing date from
  `financials_annual`.
- **Prices:** the project's `prices` table (Yahoo adjusted closes) and
  SPY for the market; trading days are SPY's.
- **Step 1 check (counts only):** 10,032 NT 10-K and 8,103 original
  8-Ks with Item 4.01 filed 2014-2025; before the eligibility and repeat
  rules, 185 NT 10-K and 336 Item 4.01 events had a usable score with all
  three scores and a price on the entry day.

## Definitions

- **Events, analyzed separately:**
  - (A) NT 10-K filings (notices that the annual report will be late);
    the form "NT 10-K" only, not amendments (NT 10-K/A).
  - (B) original 8-Ks (form "8-K", not 8-K/A) whose listed items include
    4.01 (changes in the registrant's certifying accountant). Item 4.01
    covers resignations, dismissals and routine changes alike; they
    cannot be separated without reading each filing, which this
    analysis does not do.
  - Filing dates from 2014-01-01 to 2025-12-31.
- **Repeats.** For each company and event type, an event within 63
  market trading days after a kept event of the same type is dropped;
  only the first of a run is kept.
- **Flag status at the event.** The company's latest score whose 10-K
  was filed strictly before the event's filing date and no more than 15
  months before it, with an M-Score, a Z'' and an F-Score all present.
  Clean = 0 flags (`flags_raised`), Flagged = 1 or more. Events without
  such a score are excluded and counted.
- **Event days.** Day 0 is the filing date if it is a market trading
  day, otherwise the last trading day before it. Day +1, the entry day,
  is the first market trading day after the filing date (a filing can
  come after the market closes, so the filing day itself is not
  tradeable; a Friday filing enters on Monday). Days are counted in
  market trading days.
- **Entry.** The adjusted close on day +1.
- **Filing-day move (descriptive).** The close on day 0 against the close
  on day -1, minus SPY's move on the same day, reported only for events
  filed on a trading day. It shows how much of the reaction happens
  before anyone could act on the filing.
- **Eligibility.** A current ticker; a price on each of the 20 trading
  days before day 0 (days -20 to -1); and an adjusted close of at least
  $5 on day +1. The results are also reported without the $5 rule, as a
  descriptive check.
- **Outcome (registered window).** The market-adjusted return from day
  +1 to day +63: the stock's buy-and-hold return from the close on day +1
  to the close on day +63, minus SPY's return over the same days. An
  event whose stock has no price on day +63 (its prices stop, or the
  window runs past the end of the price data) is excluded from that
  window and counted by group.
- **Descriptive windows.** The same measure from day +1 to day +21, +126
  and +252, each with its own count of complete windows.
- **Registered questions, for each event type (4 in all):**
  - (a) Is the Flagged group's average market-adjusted return (days +1
    to +63) different from zero?
  - (b) Is the Flagged average different from the Clean average?
  - Both are estimated by ordinary least squares with standard errors
    clustered by company (statsmodels): (a) the outcome on a constant,
    over Flagged events; (b) the outcome on a constant and a Flagged
    indicator (0 or 1), over all events. Because 4 questions are tested,
    a question passes only if |t| >= 3.0 (two-sided, as "different"
    asks).
- **Descriptive:**
  - results by flag count (0, 1, 2 and 3);
  - the number of events per group per year;
  - a chart of the average cumulative market-adjusted return from day
    -5 to day +252 for Flagged and Clean, one panel per event type
    (`docs/curiosity/events_car.png`). The curve is measured from the
    close on day -6 (so the days before and the filing-day move show),
    with day +1 marked; on each day it averages the events with a price
    that day.

## Limitations, stated in advance

- **Survivorship.** Current tickers only. Late filers and companies
  whose auditor leaves are especially likely to delist later, so the
  worst outcomes are probably missing.
- **Few usable events.** Most events belong to companies without a
  usable score (step 1: about 2% of NT 10-K events and 4% of Item 4.01
  events remain before the eligibility and repeat rules), so the groups
  are small and the |t| >= 3.0 bar needs a large effect.
- **Events cluster in time** (for example, 2020).
- **Item 4.01 mixes** routine and alarming auditor changes.
- **Market reaction, not a trade.** This shows whether the market
  reacts after the event, not whether a short sale or put would profit
  after borrowing costs and option prices.
- **Correlation, not cause.** Not investment advice.

## Outputs

These results, whatever they show; `docs/curiosity/events_car.png`;
details in `data/logs/curiosity_events.csv`. Code:
`src/curiosity/events.py`. Tests: `tests/test_curiosity.py` (event date
to entry day, a Friday filing entering Monday; the 63-day repeat rule;
market adjustment on a hand-checked example).
