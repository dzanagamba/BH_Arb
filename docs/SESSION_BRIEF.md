# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4, N1-1 through N1-4, N2-1 and N2-2
are Done**. First eligible task is **N2-3** (candidate remediation and
strict-miss trends; no dependencies).
**Last task commit:** `cced941` — N2-2 realistic paper fills.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,561 passed, 2 skipped, 1 warning** in both ledger modes: with no generated
ledger and with a deliberately populated one. Ruff, MyPy (199 source files),
Node syntax check and the generated market doc are clean.

N2-2 replaces the “every leg fills” assumption with deterministic paper fills:
a leg is `filled`, `partial` (capped at the advisory book limit), `rejected`
(price moved beyond tolerance) or `missing` (no price/disappeared). Each mark
records per-leg planned/filled stake, reason and worst-case profit. The summary
keeps `execution_adjusted` (complete fill records only, with its own
denominator) separate from the explicitly labelled optimistic
`simulated_open` block; an unfilled position is never called profitable.
Settlement uses the filled stake when a mark exists. No cash, account, bet
placement or acceptance is simulated. `docs/PAPER_MODE.md` documents the model.

Earlier work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, a CSP with no inline styles, automatic closing-line capture,
bounded retention/maintenance, coverage/mapping alerts, per-book scan cost
accounting, release hardening (SBOM, Docker smoke workflow, grouped
Dependabot), and the Paper dashboard/CSV/retention view. The first live
scan-cost baseline is still pending (no live scan was run); its evidence slot is
ready.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N2-3**: rank candidate remediation from evidence already in the ledger
and raw spellings, label suggestions as proposals only; group repeated strict
misses by book pair, league and spelling pattern with a trend series; add a
dashboard “top recurring blockers” panel with evidence and the exact gate
reason; add a CLI report under `scripts/` for the top N closeable pairs; ensure
no default path can approve or apply a suggestion automatically.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
