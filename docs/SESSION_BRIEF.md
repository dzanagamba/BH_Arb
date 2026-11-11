# Session brief

**Updated:** 2026-11-11
**Goal:** keep the scanner correct and current without weakening the trust
model; work `ROADMAP.md` top to bottom.
**Current row:** none in progress. SR9-1 and M6-2 are Done.
**Last commit:** "docs: refresh README, roadmap and docs; read the coverage floor
(M6-2)" on `origin/main` (2026-11-11), after `5a4b8fe` (SR9-1). `git log -1`
has the hash.

## Project state

- Everything before 2026-11-11 is closed; the old roadmap and brief are in
  `docs/archive/*_2026-11-11.md`. `ROADMAP.md` now lists open rows only.
- **Live scan 2026-11-11** (`docs/evidence/2026-11-11-test-scan.md`):
  prematch 6,921 matches / 1,359 verified groups / 20 surebets in 139.0 s, all
  nine enabled books `ok`; live 183 / 27 / 1 in 29.1 s, Mozzartbet and Betole
  `empty`. EVLBet disabled.
- **Verification baseline (2026-11-11, clean ledger mode):** `pytest` 2,378 passed,
  12 skipped in 136 s, 0 failed (M6-2 fixed). Ruff clean, mypy 291 files clean,
  market doc / refresh_fixtures / audit_admissibility `--check` exit 0.
- Branch coverage floor `fail_under = 87.05` (measured 88.05 %, M6-1); CI's 3.11
  leg enforces it and runs both ledger modes.
- **Production-readiness checklist** (`ROADMAP.md`): met — prematch book
  coverage, cold replay (0 false merges), certified e2e, no trust-changing
  path, auth, green suite. Not met — leg links (SR9, 7 of 18 still fallback),
  live Mozzartbet/Betole (SR8-1), mapping coverage (SR8-3), 26 price-check
  outliers / 5,622 (M8-1), and the multi-day / 24 h evidence that N2-4 and
  P1-6 (operator) would provide.

## Next action

**Operator priority 1 (2026-11-11): SR9 — every surebet leg must open the exact
match or a filled ticket.** SR9-1 is done (`docs/evidence/2026-11-11-destinations.md`:
ticket 4, match page 7, fallback 7 of 18). Next is **SR9-2**: the MaxBet filled
ticket first (`?outcome=<id>` is proven; the adapter must keep each outcome's
`id`), then the Mozzartbet live id, then SportPlus, Premier and WWIN live (needs
an operator click); then SR9-3 and SR9-4. Never log in or submit a ticket.

After SR9: SR8-1 (live Mozzartbet and Betole parse to zero matches), SR8-4
(`record_scan.py` restores state), SR8-2 (drift-alarm noise), M8-1 (refresh
`docs/PRODUCTION_READINESS.md`). SR8-3 needs an operator choice (A/B/C), and
N2-4/P1-6 block readiness criteria 2 and 8 — ask the operator.

## Blockers and standing decisions

- SR4-3g blocked on a live EVLBet payload.
- N2-4 deferred, P1-6 waived — do not start without an operator instruction.
- SR8-3 gated: operator decides how mapping coverage is measured.
- Until SR8-4 lands, never run `scripts/record_scan.py` bare against the real
  cache; restore state first (see `AGENTS.md` → Running a real scan).
