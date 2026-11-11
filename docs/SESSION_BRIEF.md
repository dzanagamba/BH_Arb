# Session brief

**Updated:** 2026-11-11
**Goal:** keep the scanner correct and current without weakening the trust
model; work `ROADMAP.md` top to bottom.
**Current row:** none in progress. M7-2 (live test scan + doc rewrite) is Done.
**Last commit:** `afbb3c1` "docs: live test scan, production-readiness
checklist and roadmap rewrite (M7-2)", pushed to `origin/main` on 2026-11-11.

## Project state

- Everything before 2026-11-11 is closed; the old roadmap and brief are in
  `docs/archive/*_2026-11-11.md`. `ROADMAP.md` now lists open rows only.
- **Live scan 2026-11-11** (`docs/evidence/2026-11-11-test-scan.md`):
  prematch 6,921 matches / 1,359 verified groups / 20 surebets in 139.0 s, all
  nine enabled books `ok`; live 183 / 27 / 1 in 29.1 s, Mozzartbet and Betole
  `empty`. EVLBet disabled.
- **Verification baseline (2026-11-11, clean ledger mode):** `pytest` 1 failed, 2,371 passed,
  12 skipped in 108.5 s; the failure is pre-existing at HEAD (M6-2). Ruff clean,
  mypy 291 files clean, market doc / refresh_fixtures / audit_admissibility
  `--check` exit 0.
- Branch coverage floor `fail_under = 87.05` (measured 88.05 %, M6-1); CI's 3.11
  leg enforces it and runs both ledger modes.

- **Production-readiness checklist** (`ROADMAP.md`): met — prematch book
  coverage, cold replay (0 false merges), certified e2e, no trust-changing
  path, auth. Not met — live Mozzartbet/Betole (SR8-1), mapping coverage
  (SR8-3), 26 price-check outliers / 5,622 (M8-1), green suite (M6-2), and the
  multi-day / 24 h evidence that N2-4 and P1-6 (operator) would provide.

## Next action

**Operator priority 1 (2026-11-11): SR9 — every surebet leg must open the
exact match or a filled ticket.** Start with SR9-1 (re-prove all 18 book × mode
destinations on today's sites and settle the MaxBet gate/destination
contradiction), then SR9-2 (upgrade SportPlus, Premier, WWIN, MaxBet, Betole
live), SR9-3, SR9-4. Never log in or submit a ticket. After SR9:

Take **M6-2**: `main` is red because `tests/test_ci_hardening.py:25`
still expects `fail_under = 80` after M6-1 set 87.05 (one-line class of fix).
Then **SR8-1** (live Mozzartbet and Betole parse to zero matches) — two of nine
books are missing from every live scan. Then SR8-4 (make `record_scan.py`
restore state; small), then SR8-2 (drift-alarm noise). Then M8-1 (refresh
`docs/PRODUCTION_READINESS.md` from measurements). SR8-3 needs an operator
choice between options A/B/C. Ask the operator about N2-4/P1-6: they block
readiness criteria 2 and 8.

## Blockers and standing decisions

- SR4-3g blocked on a live EVLBet payload.
- N2-4 deferred, P1-6 waived — do not start without an operator instruction.
- SR8-3 gated: operator decides how mapping coverage is measured.
- Until SR8-4 lands, never run `scripts/record_scan.py` bare against the real
  cache; restore state first (see `AGENTS.md` → Running a real scan).
