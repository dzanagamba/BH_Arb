# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N2-3, N2-5 and N2-6 are Done**. N2-4 remains deferred
by the operator and must not be started until they un-defer it. First eligible
task is **N3-1** (property-based pricing/identity tests and load budgets;
depends on N0-1, which is Done).
**Last task commit:** N2-6 — parser fixtures and drift detection (see
`git log -1`).

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,613 passed, 4 skipped, 1 warning** in both ledger modes. The four skips are
the two opt-in runtime-state checks plus the two Chromium tests unless
`BH_ARB_TEST_BROWSER=1`. Ruff, MyPy (208 source files), Node syntax checks and
the generated market doc are clean.

N2-6 makes feed drift visible before a live scan loses a market. Every frozen
market fixture now has a dated contract in
`tests/fixtures/markets/contracts.json`: required top-level keys, source-id set,
label set, nested shape, event count and fingerprints. `--check` fails with an
exact id/label/shape diff, an enabled book without a contract, or a capture
older than the 120-day policy. A network failure is reported as `capture_failed`
and is never treated as a feed change. `/api/health.parser_contracts` exposes
coverage, missing modes and stale captures. Coverage is 17 fixtures across all
enabled books; Betole has a prematch contract (its prematch desk has no double
chance or 1.5/3.5 totals, and the registry declares no live rows), so the live
Betole mode is an explicit visible gap, not an implicit one.

N2-6 never edits the registry, a parser or a trust rule. A changed market id is
a prompt for a human re-capture and the existing admissibility evidence. CI runs
`python scripts/refresh_fixtures.py --check`.

Earlier work remains in place: hermetic tests, frozen-price quarantine, CSP with
no inline styles, automatic CLV capture, retention/maintenance, coverage alerts,
per-book scan cost, release hardening, paper ledger/fills, candidate remediation,
and the complete BS/EN UI with machine-checked accessibility. The first live
scan-cost and seven-day opportunity baselines remain unmeasured; N2-4 owns the
latter and is deferred.

## Next action

Start **N3-1**: add Hypothesis (dev-only) and generators for valid odds sets,
stakes, rounding modes, team spellings and kickoff boundaries; assert implied
sum/profit identity, stake-split worst case, non-negative rounding loss,
one-leg-per-book/source, and no cross-sport/settlement pairing; add bounded
performance budgets marked slow/CI-only; keep minimized failures as normal
regression tests; document how to run the property suite locally.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
