# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4 and N1-1 are Done**. First eligible
task is **N1-2** (coverage/mapping alerts and SLOs).
**Last task commit:** `8096d9b` — N1-1 retention and maintenance automation.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,519 passed, 2 skipped, 1 warning** in both ledger modes: with no generated
ledger and with a deliberately populated one. Ruff, MyPy (192 source files) and
the generated market doc are clean.

N1-1 bounds every runtime store: scans and link sweeps (90 days), paper
opportunities/positions (180 days plus a newest-row cap), mapping evidence (the
existing claim prune rule) and generated logs (30 days). Bets are never deleted;
settled rows older than 365 days are copied to a dated archive only.
`scripts/maintenance.py` supports `--dry-run`, `--vacuum` and `--backup DIR`;
the lifespan runs the bounded job daily off the scan path. `/api/health.retention`
reports each store's bytes/rows, budgets, warnings and the last maintenance time.
A process-wide guard makes a new scan refuse to start while maintenance runs.

Earlier N0 work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, a CSP with no inline styles, and automatic closing-line
capture for logged bets.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N1-2**: add settings for the coverage-budget flag count,
mapping-coverage floor and consecutive-scan threshold; add `coverage_drop`,
`mapping_coverage_low` and repeated `zero_result_reason` alert kinds; include the
peer-evidence and baseline-scan count in the body; add counters and a dashboard
trend; write the SLO definitions in `docs/COVERAGE_BUDGET.md` and
`docs/ALERTING.md`. Coverage stays a warning, never a trust rule.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
