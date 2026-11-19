# Feedback log

Every confusion point found in user testing, and what was done about it
(CLAUDE.md section 7). Sessions follow `docs/user_test_script.md`.

**Privacy.** Testers are recorded only as Tester A, B, C with a general
role. Never write a name, email or other identifying detail here.

**Rules.** Record what the tester did or said, not what we think they
meant. Every finding gets a severity (scale in the test script) and
either a fix with its commit, or a reason it was not fixed. Do not edit a
finding after the fact except to add its fix.

## Sessions

| Tester | Date | Role | Data | App commit | Tasks: success / assisted / failed |
| --- | --- | --- | --- | --- | --- |
| | | | sample | | |

## Findings from user tests

| ID | Tester | Task | What happened (observed or said) | Severity | Fix | Commit | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

## Post-test answers

Record each tester's answers to the five questions in the test script.

### Tester A

1. Confidence explaining a verdict (1 to 5), and why:
2. Most confusing word, label or screen:
3. Anything that sounded like a prediction or advice:
4. Did the trace panel change trust in the numbers:
5. One change that would help most:

## Internal review before user testing (not user feedback)

Problems the build team found on November 19, 2026 by capturing and
reviewing screenshots of every page (Phase 3 step 7). Listed so the log
is complete, and kept separate because no tester was involved.

| ID | Page | What was wrong | Severity | Fix | Commit |
| --- | --- | --- | --- | --- | --- |
| R1 | All | `python -m streamlit run app/app.py` crashed on import, because the project root sat behind `app/` on the import path | 3 | Project root always moved to the front of the path in `app/app.py` | ebe9bb3 |
| R2 | Case studies | A note with two dollar amounts ("$408 million ... $9 million") rendered as a garbled math formula | 3 | Text from `case_studies.csv` is escaped (`labels.escape_markdown`) | ebe9bb3 |
| R3 | Sidebar | Said "50 real companies" when the sample had 53; the number was typed into the code | 2 | Count computed from the loaded scores table | ebe9bb3 |
| R4 | Screener | The three verdict columns were cut off at laptop width | 2 | Verdict columns moved before Industry and Size | ebe9bb3 |
| R5 | Trace panel | The EDGAR link column was off the right edge of the table | 2 | Link moved next to the status column | ebe9bb3 |
| R6 | Company detail | Verdict headline wrapped onto two lines | 1 | Unscored checks moved to a note under the headline | ebe9bb3 |
| R7 | Company detail | Every driver sentence was bold, making the section hard to scan | 1 | Only the rank number is bold | ebe9bb3 |
| R8 | Company detail | Empty-chart message lowercased the model name ("piotroski f-score") | 1 | Message leads with the full label | ebe9bb3 |
| R9 | Case studies | Headline counted a distress warning as "showed warning signs", overstating what the radar caught | 3 | Headline based only on the earnings manipulation check | 888e4a0 |
