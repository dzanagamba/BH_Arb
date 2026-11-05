# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4 are Done**. First eligible task is
**N1-1** (retention and maintenance automation).
**Last task commit:** `pending` — N0-4 automatic closing-line capture.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite now
runs **1,511 passed, 2 skipped** in both ledger modes: with no generated ledger
and with a deliberately populated one. A throwaway copy with no
`config/generated/` and no `cache/` also passes in both modes. Ruff, MyPy and the
generated market doc are clean.

N0-4 captures a closing line for every open logged bet from each scan's verified
groups. Matching is exact on event, bookmaker, market, line, settlement and
outcome; a missing or mismatched price leaves CLV null with a reason, the record
freezes at kickoff, a manual entry is labelled `manual` and never overwritten,
and a settled bet is never touched. `GET /api/bets/summary` reports
`closing_capture`, `closing_sources` and `last_capture`; the dashboard shows the
coverage numerator/denominator.

Earlier N0 work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, and a CSP with no inline styles.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N1-1**: mark it `In progress`, define retention windows in
`config/settings.py`, add `scripts/maintenance.py` with `--dry-run`, `--vacuum`
and `--backup DIR`, schedule the bounded prune/vacuum off the scan critical
path, expose store sizes and last maintenance time in `/api/health`, and add a
restore drill plus a retention test for every store. Never delete settled bets
by default.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
