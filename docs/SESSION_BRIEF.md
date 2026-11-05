# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — first eligible task is **N0-1** (hermetic tests).
**Last commit:** `499caf7` — next roadmap added; no N-task started.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The current
system passes **1,476 tests** on a clean runtime state, with Ruff, MyPy and the
generated market doc clean. The main residual risks are listed as G1–G15 in
`PROJECT_ROADMAP_V2.md`.

Known local trap: a populated gitignored
`config/generated/mapping_evidence.json` can change one e2e expectation. That is
why N0-1 comes first. Redirect runtime state in tests; do not delete the
operator's ledger.

## Next action

Start N0-1: mark it `In progress`, add the shared test isolation fixture, and
prove the suite passes with both a clean and a populated generated ledger.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
