# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N3-2 is Done**. Every roadmap task is Done except
N2-4, which the operator deferred on 2026-11-05 and must stay deferred until
they explicitly un-defer it. There is no other eligible task in this roadmap.
**Last task commit:** N3-2 — dated sport/market admissibility re-audit (see
`git log -1`).

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,645 passed, 6 skipped, 1 warning** in both ledger modes, with **84.02%**
coverage (floor 80%). The six skips are the two opt-in runtime-state checks, the
two Chromium tests unless `BH_ARB_TEST_BROWSER=1`, and the two load budgets
unless `BH_ARB_TEST_SLOW=1`. Ruff, MyPy (214 source files), Node syntax checks
and the generated market doc are clean.

N3-2 adds `engine/admissibility.py` and `scripts/audit_admissibility.py`. The
offline report has a stable schema and records, per book and sport, the measured
market families with their settlements; for every enabled football market it
records the dated evidence row, the per-book registry declarations and, for
0.5/4.5/5.5, the measured price sources. The dated baseline is
`docs/evidence/2026-11-05-admissibility-baseline.json`.

`python scripts/audit_admissibility.py --check` fails when an admitted sport or
market disappears, a previously measured family or price source disappears, a
qualifying book drops below three families, a settlement changes, an enabled
entry loses its evidence, or the fixed three-book/three-family rule is changed.
A new family, book, price source, sport or market is only a warning and never
changes an admitted flag; code remains the admission decision. CI runs the
check on every push; the live bookmaker probe stays a reviewed operator action
documented in `docs/ADMISSIBILITY_AUDIT.md`. `/api/health.admissibility_audit`
exposes the bounded status.

Earlier work remains in place: hermetic tests, frozen-price quarantine, CSP with
no inline styles, automatic CLV capture, retention/maintenance, coverage alerts,
per-book scan cost, release hardening, paper ledger/fills, candidate remediation,
the complete BS/EN UI with machine-checked accessibility, dated parser contracts
and the property-based pricing/identity suites and load budgets. The first live
scan-cost and seven-day opportunity baselines remain unmeasured; N2-4 owns the
latter and is deferred.

## Next action

None in this roadmap. Resume only if the operator explicitly un-defers **N2-4**
(seven-day local opportunity baseline and drift gates), or supplies a new
roadmap. Do not invent a task or reopen a done one.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
