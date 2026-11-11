# Session brief

**Updated:** 2026-11-11
**Goal:** keep the scanner correct and current without weakening the trust
model; work `ROADMAP.md` top to bottom.
**Current row:** none in progress. SR8-2 and SR8-4 are Done. SR8-1 stays In
progress because Mozzartbet live is websocket-only and waits on the operator's
transport decision; Betole live is fixed (0 → 76 matches, also 75 in today's
live scan).
**Last commit:** `c7d4933` "fix: quiet the structural-drift alarm and refresh the
NSoft casing (SR8-2)" on `main` (2026-11-11). `git log -1` has the hash.

## Project state

- Everything before 2026-11-11 is closed; the old roadmap and brief are in
  `docs/archive/*_2026-11-11.md`. `ROADMAP.md` now lists open rows only.
- **Today's scans (after SR8-4/SR8-1/SR8-2):** prematch 6,459 matches / 1,283
  groups / 20 surebets; live 243 / 19 / 0. Betole live reports 75 matches (was
  `empty`); Mozzartbet live still 0 (`returned no matches`, SR8-1 blocker).
  Reports in `/tmp/opencode/sr8-2/`; the dated SR8-1 evidence is
  `docs/evidence/2026-11-11-sr8-1-live.md`.
- **Structural drift:** 225 → 23 lines per prematch scan, 0 repeated
  signatures; Admiralbet's six baselines re-recorded with the feed's current
  `sbv`/`tot` casing (SR8-2).
- **Destinations now:** `ticket_filled` 6 of 18 cells (MDShop, Admiralbet,
  MaxBet prematch+live), `match_page` 6 (Mozzartbet prematch, Betole prematch,
  MBet both, WWIN prematch+live), generic 6 (SportPlus 2, Premier 2,
  Mozzartbet live, Betole live). Evidence:
  `docs/evidence/2026-11-11-sr9-2.md`.
- **Verification baseline (2026-11-11, this session):** `pytest` 2,453 passed,
  12 skipped in 104.54 s, 0 failed. Ruff clean, mypy 296 files clean, market
  doc / refresh_fixtures / audit_admissibility `--check` exit 0.
- Branch coverage floor `fail_under = 87.05` (measured 88.05 %, M6-1); CI's 3.11
  leg enforces it and runs both ledger modes.
- **Production-readiness checklist** (`ROADMAP.md`): met — prematch book
  coverage, cold replay (0 false merges), certified e2e, no trust-changing
  path, auth, green suite. Not met — leg links (SR9, 6 of 18 still generic),
  live Mozzartbet (SR8-1; Betole live was fixed), mapping coverage (SR8-3), 26
  price-check outliers / 5,622 (M8-1), and the multi-day / 24 h evidence that
  N2-4 and P1-6 (operator) would provide.

## Next action

No ungated row is ready: M8-1 depends on SR8-1, SR8-3 is gated, SR4-3g needs a
live EVLBet payload, N2-4/P1-6 are deferred/waived. The next step needs the
operator's Mozzartbet live decision (build the Socket.IO collector, defer it to
its own row, or accept the limitation). Once SR8-1 closes, M8-1 refreshes the
production-readiness assessment.

## Blockers and standing decisions

- Mozzartbet live is available only over `wss://.../socket.io`; the HTTP list the
  adapter reads has no in-play events. Needs the operator's scope decision.
- SR9-4: the operator chose to keep every surebet listed — no hide and no
  deprioritise option exists; revisit only on a new operator instruction.
- SR4-3g blocked on a live EVLBet payload.
- N2-4 deferred, P1-6 waived — do not start without an operator instruction.
- SR8-3 gated: operator decides how mapping coverage is measured.
- `scripts/record_scan.py` restores state itself (SR8-4) and takes several modes
  in one invocation, with `--out` as a directory.
