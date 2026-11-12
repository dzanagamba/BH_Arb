# Session brief

**Updated:** 2026-11-12
**Goal:** keep the scanner correct and current without weakening the trust
model; work `ROADMAP.md` top to bottom.
**Current row:** none in progress. SR8-5, M8-2 and M8-3 are Done (2026-11-12).
SR8-1 stays In progress because Mozzartbet live is websocket-only and waits on
the operator's transport decision.
**Last commit:** M8-2/M8-3 on `main` (2026-11-12). `git log -1` has the hash.

## Project state

- Everything before 2026-11-11 is closed; the old roadmap and brief are in
  `docs/archive/*_2026-11-11.md`. `ROADMAP.md` lists open rows only.
- **Orientation (M8-2):** a shared Betradar id no longer lets a fuzzy name
  comparison flip home and away. Ledger/allowlist proof decides first; otherwise
  the comparison must clear 60 points and a 20-point margin, else the pair
  splits. Replay of the stored scan: groups 1,292 → 1,293, comparisons 5,971 →
  5,976, outliers **18 → 12**, strict misses unchanged at 21 (0.33 %).
- **Scan reporting (M8-3):** `ScanStatus.notes` carries protective actions (the
  price-guard drop, an odds-age spread), so the dashboard no longer calls them
  bookmaker failures. Measured: `errors = []`, `notes = ['6 surebet(s) dropped:
  a leg was a price outlier']`.
- **SportPlus (SR8-5):** a blank 2xx body is a `transport` failure retried inside
  the existing budget, not `schema_drift`; the book is back at 730–737 matches.
- **Latest scans (2026-11-12, new code):** prematch 6,367 listings / 1,297
  verified groups / 19 surebets, 9/9 books; `price_check` 12 outliers, all price
  disagreements on `betole`/`maxbet`, none from orientation.
- **2026-11-11 baselines** (`docs/evidence/2026-11-11-m8-1-scans.md`): prematch
  6,459 matches / 1,283 verified groups / 21 outliers / 20 surebets; live 243 /
  19 / 0, Mozzartbet the only missing book. Pairing 0.28 % and 0.0 % strict
  miss; mapping 7.7 % prematch, 2.6 % live.
- **Production-readiness assessment** (`docs/PRODUCTION_READINESS.md`, M8-1,
  dated 2026-11-11) matches the ROADMAP checklist; leg links 6 ticket / 6 match
  page / 6 generic cells.
- **Verification baseline (2026-11-12):** `pytest` 2,465 passed, 12 skipped in
  120.51 s, 0 failed. Ruff clean, mypy 298 files clean, market doc /
  refresh_fixtures / audit_admissibility `--check` exit 0.
- Branch coverage floor `fail_under = 87.05` (measured 88.05 %, M6-1); CI's 3.11
  leg enforces it and runs both ledger modes.
- **Checklist not met:** live Mozzartbet (SR8-1), mapping breadth (SR8-3,
  operator-gated), the price-outlier bar (criterion 4: 12 / 5,966 = 0.20 %
  prematch today), criteria 2/8 (N2-4 deferred, P1-6 waived). Six generic leg
  cells.

## Next action

No ungated row is left. The next step is the operator's call on: the Mozzartbet
live transport (SR8-1), the criterion-4 price bar (M8-1 proposal; prematch is now
0.20 % over 5,966 comparisons), criteria 2 and 8 (N2-4 deferred, P1-6 waived),
and how SR8-3 measures mapping coverage.

## Blockers and standing decisions

- Mozzartbet live is available only over `wss://.../socket.io`; the HTTP list the
  adapter reads has no in-play events. Needs the operator's scope decision.
- SR9-4: every surebet stays listed — no hide or deprioritise option exists;
  revisit only on a new operator instruction.
- SR4-3g blocked on a live EVLBet payload. N2-4 deferred, P1-6 waived, SR8-3
  operator-gated — none of them starts without an operator instruction.
- `scripts/record_scan.py` restores state itself (SR8-4) and takes several modes
  in one invocation, with `--out` as a directory.
