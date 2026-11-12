# Session brief

**Updated:** 2026-11-12
**Goal:** keep the scanner correct and current without weakening the trust
model; work `ROADMAP.md` top to bottom.
**Current row:** none in progress. SR8-5 (2026-11-12) is Done. SR8-1 stays In
progress because Mozzartbet live is websocket-only and waits on the operator's
transport decision.
**Last commit:** SR8-5 on `main` (2026-11-12). `git log -1` has the hash.

## Project state

- Everything before 2026-11-11 is closed; the old roadmap and brief are in
  `docs/archive/*_2026-11-11.md`. `ROADMAP.md` lists open rows only.
- **Latest scans (2026-11-12, new code):** three prematch runs, all nine books
  present in the last one — 6,327 matches / 1,266 groups / 22 surebets.
  SportPlus is fixed (737 matches per run; it had dropped out of the operator's
  00:26 scan on a blank `HTTP 200` body) and the feed-integrity guard restored it
  to `healthy` after three clean scans. Evidence:
  `docs/evidence/2026-11-12-sr8-5-sportplus-blank-body.md`.
- **2026-11-11 baselines** (`docs/evidence/2026-11-11-m8-1-scans.md`): prematch
  6,459 matches / 1,283 verified groups / 5,795 comparisons / 21 outliers /
  20 surebets (8 dropped by the price guard); live 243 / 19 / 0, Mozzartbet the
  only missing book. Pairing 0.28 % and 0.0 % strict miss, zero duplicate-book
  groups; mapping 7.7 % prematch, 2.6 % live.
- **Production-readiness assessment** (`docs/PRODUCTION_READINESS.md`, M8-1,
  dated 2026-11-11) matches the ROADMAP checklist, including leg links at
  6 ticket / 6 match page / 6 generic cells.
- **Structural drift:** 225 → 23 lines per prematch scan with 0 repeated
  signatures (SR8-2). SportPlus now fingerprints
  `matches[].leagueDescription:string->null` once per scan — a nullable field the
  parser never reads, recorded as an observation, not a price path.
- **Verification baseline (2026-11-12):** `pytest` 2,458 passed, 12 skipped in
  120.30 s, 0 failed. Ruff clean, mypy 297 files clean, market doc /
  refresh_fixtures / audit_admissibility `--check` exit 0.
- Branch coverage floor `fail_under = 87.05` (measured 88.05 %, M6-1); CI's 3.11
  leg enforces it and runs both ledger modes.
- **Checklist not met:** live Mozzartbet (SR8-1), mapping breadth (SR8-3,
  operator-gated), the price-outlier bar (criterion 4, proposal with the
  operator), criteria 2/8 (N2-4 deferred, P1-6 waived). Six generic leg cells.

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
