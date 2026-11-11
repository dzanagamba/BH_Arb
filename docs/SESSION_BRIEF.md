# Session brief

**Updated:** 2026-11-11
**Goal:** keep the scanner correct and current without weakening the trust
model; work `ROADMAP.md` top to bottom.
**Current row:** none in progress. M8-1, SR8-2 and SR8-4 are Done. SR8-1 stays
In progress because Mozzartbet live is websocket-only and waits on the
operator's transport decision; Betole live is fixed (0 → 76 matches, 75 in
today's live scan).
**Last commit:** `PENDING` on `main` (2026-11-11). `git log -1` has the hash.

## Project state

- Everything before 2026-11-11 is closed; the old roadmap and brief are in
  `docs/archive/*_2026-11-11.md`. `ROADMAP.md` now lists open rows only.
- **Today's scans (post SR8-4/SR8-1/SR8-2, M8-1 evidence):** prematch 6,459
  matches / 1,283 verified groups / 20 surebets (8 dropped by the price guard);
  live 243 / 19 / 0, with Mozzartbet the only missing book. Pairing 0.28 % and
  0.0 % strict miss, zero duplicate-book groups; mapping 7.7 % prematch and
  2.6 % live. Reports: `docs/evidence/2026-11-11-m8-1-scans.md`.
- **Production-readiness assessment refreshed** (`docs/PRODUCTION_READINESS.md`,
  M8-1, dated 2026-11-11). The ROADMAP checklist matches it, including the leg
  links corrected to 6 ticket / 6 match page / 6 generic cells.
- **Structural drift:** 225 → 23 lines per prematch scan, 0 repeated
  signatures; Admiralbet's six baselines re-recorded with the current
  `sbv`/`tot` casing (SR8-2).
- **Verification baseline (2026-11-11, this session):** `pytest` 2,453 passed,
  12 skipped in 104.54 s, 0 failed. Ruff clean, mypy 296 files clean, market
  doc / refresh_fixtures / audit_admissibility `--check` exit 0.
- Branch coverage floor `fail_under = 87.05` (measured 88.05 %, M6-1); CI's 3.11
  leg enforces it and runs both ledger modes.
- **Checklist not met:** live Mozzartbet (SR8-1), mapping breadth (SR8-3,
  operator-gated), the price-outlier bar (criterion 4, proposal with the
  operator), and criteria 2/8 (N2-4 deferred, P1-6 waived). Six generic leg
  cells remain.

## Next action

No ungated row is left. The next step is the operator's call on: the Mozzartbet
live transport (SR8-1), the criterion-4 price bar (M8-1 proposal), criteria 2
and 8 (N2-4 deferred, P1-6 waived), and how SR8-3 measures mapping coverage.

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
