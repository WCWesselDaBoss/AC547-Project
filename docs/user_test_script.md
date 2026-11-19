# User test script

A 25-minute session with one tester who has never seen the Earnings
Quality Radar. The goal is to find where an analyst who did not build the
tool gets confused, not to test the tester. Log every confusion point in
`docs/feedback_log.md` (CLAUDE.md section 7: user feedback log).

## Who to recruit

Someone who reads financial statements but has not taken AC 547 or seen
the app: for example a MAcc or MBA student, or an analyst. A common
usability rule of thumb (Nielsen, 2000, "Why You Only Need to Test with
5 Users") is that a handful of testers finds most problems, so two or
three sessions are worthwhile even with little time.

**Privacy.** Do not write a tester's name, email or other identifying
details anywhere in the repo. Refer to testers only as Tester A, Tester B,
and so on, and record only a general role (for example "MAcc student").
Ask before recording the screen; never record faces or voices.

## Before each session (5 minutes)

1. Pull the latest `main`, run `pytest`, and note the commit:
   `git log --oneline -1` (goes in the log).
2. Start the app on the committed sample, so every tester sees the same
   data and the answer keys below hold:

   ```
   $env:EQR_DATA_SOURCE = "sample"
   streamlit run app/app.py
   ```

3. Open the app in a **new private browser window** for each tester, so
   no filters or choices from the last session carry over.
4. Leave the app on the Screener page, sidebar open.
5. Have this script, a timer and `docs/feedback_log.md` open on another
   screen.

## What to say at the start (read aloud)

> "Thanks for helping. This is a tool for an equity analyst who wants to
> know whether a company's reported earnings can be trusted. I'm testing
> the tool, not you: if something is confusing, that's the tool's fault,
> and it's exactly what I need to find. Please think out loud as you go:
> say what you're looking at, what you expect, and what surprises you.
> I'll mostly stay quiet, because in real use nobody would be there to
> explain. There are nine short tasks; stop me any time."

## How to run the tasks

- Read each task exactly as written. Do not point at the screen or name
  a button.
- If the tester is stuck for **60 seconds**, say "What would you look
  for?" If still stuck after **2 minutes**, mark the task "failed", show
  the answer, and move on.
- Write down what they say, especially words they misread or questions
  they ask. Note the time to the first useful action.
- Score each task: **Success** (no help), **Assisted** (needed the 60 s
  prompt) or **Failed**.

## Tasks

Answer keys are from the committed sample as of commit `515fedf`
(November 19, 2026). If the sample is rebuilt, recheck them.

### 1. First impression (Screener, 30 seconds)

> "Without clicking anything: what do you think this tool is for, and
> what would you do first?"

**Success:** describes it as flagging warning signs in reported earnings
(not as predicting the stock price or proving fraud).
**Watch for:** reading the scores as buy/sell advice; not noticing the
"Sample data" note in the sidebar.

### 2. Find the riskiest large companies

> "Show only large companies for fiscal year 2024. Which one has the
> most warning signs?"

**Answer:** 19 large companies in FY2024. Three tie with 1 concern
(EQT Corp, American Electric Power, American Airlines); EQT Corp is
listed first because its M-Score (2.33) is the highest.
**Success:** sets Fiscal year and Size, reads the Concerns column, and
notices or asks about the tie.
**Watch for:** sorting by another column by mistake; reading "1 of 3" as
a score out of 3 rather than a count of checks.

### 3. Change the manipulation cutoff

> "Some analysts use a cutoff of -2.22 instead of -1.78 for the
> manipulation check. Switch to -2.22. Does that warn about more
> companies or fewer?"

**Answer:** more. In FY2024 the manipulation warnings go from 2 to 3 of
42 companies (clear the Size filter first, or the count differs).
**Success:** moves the slider to -2.22 and explains that a lower cutoff
warns about more companies.
**Watch for:** confusion about which direction is "stricter"; whether
they find the slider's help text.

### 4. The five-second verdict

> "Open Under Armour's fiscal 2015. In one sentence, what does the tool
> say about its earnings?"

**Answer:** 1 of 3 checks raised concerns: the earnings manipulation
check warned (M-Score -0.90, above the -1.78 cutoff); distress risk is
in the safe zone; financial strength could not be scored.
**Success:** gets there (search box or screener row) and gives a correct
one-sentence summary within about 10 seconds of the page loading.
**Watch for:** reading "No score" as good or bad; missing the cards.

### 5. Why

> "What is the main reason for that warning?"

**Answer:** reason 1 (AQI): a larger share of assets is now in
hard-to-value items, which can mean spending is being recorded as an
asset instead of an expense. (Reasons 2 and 3 are TATA and SGI.)
**Success:** reads the first "Why" sentence and can restate it.
**Watch for:** whether the sentence makes sense without the index name;
whether they think the reason proves wrongdoing.

### 6. Compared with peers

> "How does Under Armour compare with similar companies that year, and
> how much would you trust that comparison?"

**Answer:** the sentences rank it against only 2 companies in its
industry (SIC 23), and a caution says the ranking rests on very few
companies; on the sample, rankings are illustrative.
**Success:** gives the comparison and notices the caution.
**Watch for:** taking "more than 100% of its peers" at face value without
noticing there are only 2.

### 7. Trace a number to the 10-K

> "Find the exact revenue figure the manipulation score used for fiscal
> 2015, and show me where it comes from in the SEC filing."

**Answer:** $3,825,691,000, tag `SalesRevenueNet`, from the 10-K filed
2016-02-22 (accession 0001336917-16-000064). The "Open on EDGAR" link
opens the filing (needs internet; offline, the accession number is
enough).
**Success:** uses "Trace to the 10-K" (or the trace tab) and finds the
Revenue row for FY2015 without help.
**Watch for:** whether the trace button is noticed at all; confusion
between the FY2015 and FY2014 rows; what they make of "Calculated from
other reported facts".

### 8. A case study

> "Did the tool warn about Kraft Heinz before its accounting problem
> became public?"

**Answer:** no, a miss. Only FY2017 could be scored before the February
21, 2019 disclosure, and its M-Score (-1.82) was just below the -1.78
cutoff.
**Success:** finds Case studies, picks Kraft Heinz, reads the headline
and says it was a miss.
**Watch for:** whether "before the event" and the shaded years are
understood; whether distress warnings are mistaken for a catch.

### 9. Limits

> "Where would you check what this tool cannot tell you?"

**Success:** finds the About and limitations page and names one
limitation in their own words.

## After the tasks (5 minutes)

Ask each question, write down the answer word for word where you can:

1. "On a scale of 1 to 5, how confident would you be explaining a
   company's verdict to your manager? Why?"
2. "Which word, label or screen was the most confusing?"
3. "Did anything on the screen sound like a prediction or advice? Where?"
4. "Did the trace panel change how much you trust the numbers? How?"
5. "What one change would make this more useful to you?"

## Severity scale for the log

| Severity | Meaning |
| --- | --- |
| 3, major | Tester reached a wrong conclusion, or failed a task |
| 2, minor | Tester was slowed down or needed the 60-second prompt |
| 1, cosmetic | Tester noticed or commented, but it did not slow them |

Fix every severity 3 before the presentation, and severity 2 where time
allows. After each fix, run `pytest`, re-capture the screenshots
(`python docs/screenshots/capture_screenshots.py`), commit, and record
the commit in the log.
