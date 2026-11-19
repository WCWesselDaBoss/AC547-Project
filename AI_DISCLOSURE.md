# AI Disclosure Log — Earnings Quality Radar (AC 547)

This document discloses my use of AI assistance (Claude, Anthropic) on this project. Each dated section below summarizes, at a high level, what I used AI for during that day's work. Entries are categorical summaries, not verbatim prompts or transcripts.

## 2026-11-19

- Planned the Phase 3 (dashboard and case studies) build as a sequence of reviewable steps, following the shared spec in CLAUDE.md.
- Generated Phase 3 step 1 code for my review before committing: a script that builds small made-up test tables for the dashboard (company list, XBRL facts including one restated value, and scores produced by the team's existing Phase 2 functions), and a config setting to switch the app between test, sample and full data.
- Generated pytest tests that check the test tables against the real sample tables' columns and types and check the data-source setting; ran the full test suite (all passing).
