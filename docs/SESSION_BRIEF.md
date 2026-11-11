# Session brief

**Updated:** 2026-11-11
**Goal:** keep the scanner correct and current without weakening the trust
model; work `ROADMAP.md` top to bottom.
**Current row:** none in progress. SR9-4 is Done (labelling shipped; the
operator declined a hide or deprioritise option).
**Last commit:** `225f55e` "feat: show which legs reach the match on each card
(SR9-4)" on `main` (2026-11-11, not pushed). `git log -1` has the hash.

## Project state

- Everything before 2026-11-11 is closed; the old roadmap and brief are in
  `docs/archive/*_2026-11-11.md`. `ROADMAP.md` now lists open rows only.
- **Live scan 2026-11-11** (`docs/evidence/2026-11-11-test-scan.md`):
  prematch 6,921 matches / 1,359 verified groups / 20 surebets in 139.0 s, all
  nine enabled books `ok`; live 183 / 27 / 1 in 29.1 s, Mozzartbet and Betole
  `empty`. EVLBet disabled.
- **Destinations now:** `ticket_filled` 6 of 18 cells (MDShop, Admiralbet,
  MaxBet prematch+live), `match_page` 6 (Mozzartbet prematch, Betole prematch,
  MBet both, WWIN prematch+live), generic 6 (SportPlus 2, Premier 2,
  Mozzartbet live, Betole live). Evidence:
  `docs/evidence/2026-11-11-sr9-2.md`.
- **Verification baseline (2026-11-11, this session):** `pytest` 2,437 passed,
  12 skipped in 105.82 s, 0 failed. Ruff clean, mypy 295 files clean, market
  doc / refresh_fixtures / audit_admissibility `--check` exit 0.
- Branch coverage floor `fail_under = 87.05` (measured 88.05 %, M6-1); CI's 3.11
  leg enforces it and runs both ledger modes.
- **Production-readiness checklist** (`ROADMAP.md`): met — prematch book
  coverage, cold replay (0 false merges), certified e2e, no trust-changing
  path, auth, green suite. Not met — leg links (SR9, 6 of 18 still generic),
  live Mozzartbet/Betole (SR8-1), mapping coverage (SR8-3), 26 price-check
  outliers / 5,622 (M8-1), and the multi-day / 24 h evidence that N2-4 and
  P1-6 (operator) would provide.

## Next action

**SR8-1** (live Mozzartbet and Betole parse to zero matches), which also
unblocks the Mozzartbet live destination id. Then SR8-4, SR8-2, M8-1.

## Blockers and standing decisions

- SR9-4: the operator chose to keep every surebet listed — no hide and no
  deprioritise option exists; revisit only on a new operator instruction.
- SR4-3g blocked on a live EVLBet payload.
- N2-4 deferred, P1-6 waived — do not start without an operator instruction.
- SR8-3 gated: operator decides how mapping coverage is measured.
- Until SR8-4 lands, never run `scripts/record_scan.py` bare against the real
  cache; restore state first (see `AGENTS.md` → Running a real scan).
