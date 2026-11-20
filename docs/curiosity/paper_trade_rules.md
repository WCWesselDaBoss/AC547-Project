# Paper-trading rules: the late-filing rule

**Rules version 1, frozen before any trade was logged. Changes create a
new version; earlier versions and their trades stay in the log
unchanged.**

**Hypothetical research log, not investment advice.** Curiosity work,
not part of the class project. No brokerage is ever connected, no real
order is ever placed, and nothing here is built to do either. Public
data only (SEC EDGAR and Yahoo Finance prices). Any real trading would
first need to be checked against my employer's independence policy.

Background: in `docs/curiosity/events.md`, flagged companies' stocks
trailed SPY by 7.7% over the three months after a late-filing notice,
but on only 144 past events the result did not pass its bar (t =
-1.76). This log tests the same idea on filings that have not happened
yet, so the rule cannot have been tuned to them.

## Rules (version 1)

- **Start.** Only NT 10-K filings with a filing date on or after the
  date of the git commit that adds this file. No earlier filing is ever
  backfilled.
- **Events.** Original NT 10-K filings (form "NT 10-K", not "NT 10-K/A")
  by companies that file 10-Ks, whose SIC code is outside 6000-6799, and
  that have a current ticker in SEC's company ticker file on the day the
  event is logged.
- **Flag status, point in time.** For that one company, fetch its XBRL
  company facts from SEC and keep only facts from 10-K and 10-K/A
  filings made strictly before the NT 10-K's filing date, using each
  fact's original (earliest-filed) value, as the project pipeline does.
  Build the company's annual financials with the project's own pipeline
  functions and compute the latest fiscal year's scores with the
  project's own score functions. Usable only if that latest 10-K was
  filed no more than 15 months before the NT 10-K, the M-Score, Z'' and
  F-Score are all present, and that year passes the size floor (revenue
  or total assets of at least $100 million). Flagged = 1 or more flags;
  Clean = 0. Events without a usable score are logged with the reason.
- **Entry day.** The first market trading day after the filing date (a
  filing can come after the close; a Friday filing enters on Monday).
  Trading days are SPY's.
- **Eligibility.** A price on each of the 20 trading days before the
  filing date, and an adjusted close of at least $5 on the entry day.
  Ineligible events are logged with the reason and never traded.
- **Repeats.** If the same company has a paper trade whose entry day is
  within the 63 trading days before this event's entry day (open or
  already closed), the new event is logged but not traded.
- **Hypothetical trade.** For every eligible Flagged event: short
  $10,000 of the stock and buy $10,000 of SPY, both at the adjusted
  close on the entry day. Eligible Clean events get the same
  hypothetical trade, logged as the comparison group; the rule itself
  trades only Flagged events.
- **Exit.** Both legs at the adjusted close on trading day 63, where the
  entry day is day 1 (so the trade spans 62 trading-day returns, the
  same window as `events.md`).
- **Result.** SPY's return minus the stock's return over the trade
  (positive means the trade made money), and in dollars, $10,000 times
  that. The market-adjusted stock return is the negative of the result.
- **Costs, reported alongside.** The same result minus a borrowing fee
  of 10% a year for 63 of 252 trading days, which is 2.5% of the short
  side, because late filers are often expensive to short. Real
  borrowing availability and cost cannot be seen from public data; every
  trade is marked "borrowing availability unknown".
- **A stock that stops trading.** If the stock has no price for 5
  trading days in a row while a trade is open (delisted or halted), the
  trade is closed at the last available price and marked "closed at
  last price"; no price is ever invented.
- **Evaluation, decided now.** The rule is not judged until at least 60
  Flagged trades have closed and 24 months have passed since this
  file's commit, whichever comes later. Then it is tested once:
  - Is the Flagged average market-adjusted stock return below zero?
  - Is it below the Clean average?
  - Both by ordinary least squares with standard errors clustered by
    company. The rule passes only if the Flagged-minus-Clean difference
    in market-adjusted stock return has t <= -2.2 (equivalently, t >=
    2.2 on the trade result), with the Flagged average below zero.
  - Before then, summaries are for watching only and never justify
    changing the rules. A new version may change the rules for future
    events only.

## The logs

- `data/papertrade/events_log.csv` (every event) and
  `data/papertrade/trades_log.csv` (every hypothetical trade), each row
  marked with the rules version.
- Append-only: a run may fill in an entry or exit price on an existing
  row, but never changes a filing date, flag status or rules version
  once logged. A mistake is fixed by adding a correction row that points
  to the original row; nothing is edited or deleted. The tracker checks
  this on every run and stops with an error if any earlier field
  changed.
- The logs hold public data only and are meant to be committed after
  each run, so the git history also shows that no earlier row was
  changed.

## Instructions: how to run weekly (not part of the rules)

This section explains how to run the tracker; it changes none of the
rules above, which were frozen in commit `7722c0a` (2026-11-20).

1. **Once: set your SEC User-Agent.** SEC asks every automated request
   to identify itself; the tracker refuses to run without it. In
   PowerShell (this saves it for your user account, so scheduled runs
   see it too; open a new window afterwards):

   ```powershell
   setx SEC_USER_AGENT "Your Name AC547 your.email@school.edu"
   ```

2. **Each week: run it** from the project folder, on the branch that
   holds the tracker (`curiosity-events`, or `main` once merged):

   ```powershell
   cd C:\Projects\AC547-Project
   py -m src.curiosity.papertrade
   ```

   A run reads SEC's daily filing indexes since the last run (it
   catches up on any missed weeks), logs new events, fills entry and
   exit prices that are due, checks that no earlier logged field was
   changed (it stops with an error if one was), and rewrites
   `docs/curiosity/paper_trade_status.md`. It takes a few minutes and
   needs an internet connection.

3. **After each run: review and commit the logs**, so the git history
   also shows that no earlier row was changed:

   ```powershell
   git add data/papertrade docs/curiosity/paper_trade_status.md
   git commit -m "Paper trading: weekly run"
   ```

   The price cache (`data/papertrade/prices/`) is gitignored; the logs
   keep every price used.

4. **If a row was logged wrong,** add a correction row; never edit the
   CSV files by hand (the next run would stop on the changed row):

   ```powershell
   py -m src.curiosity.papertrade --correct T000003 --field ticker --value ABCD --reason "ticker changed before the event"
   ```

**Scheduling it (optional; set up only if you decide to).** Windows
Task Scheduler can run step 2 weekly; nothing here creates the task.
Run step 2 by hand once first: it creates `data\papertrade\`, where the
scheduled run writes its output (`run.log`, which is gitignored).

- In Task Scheduler: Create Basic Task, name it (for example
  "Paper trade tracker"), trigger Weekly (for example Saturday 9:00),
  action "Start a program":
  - Program: `cmd.exe`
  - Arguments: `/c py -m src.curiosity.papertrade >> data\papertrade\run.log 2>&1`
  - Start in: `C:\Projects\AC547-Project`
- In the task's properties, tick "Run task as soon as possible after a
  scheduled start is missed", so a week the computer was off is caught
  up next time (the tracker also catches up on missed days itself).
- The same task from a command prompt, if you prefer (not run here):

  ```
  schtasks /Create /SC WEEKLY /D SAT /ST 09:00 /TN "Paper trade tracker" /TR "cmd /c cd /d C:\Projects\AC547-Project && py -m src.curiosity.papertrade >> data\papertrade\run.log 2>&1"
  ```

- A scheduled run does not commit anything; review
  `data\papertrade\run.log` and commit the logs yourself (step 3). The
  task only reads public data and writes local files: it places no
  orders and connects to no brokerage.
