# Multi-sport expansion — worklog (2026-11-04)

This file is the durable progress record for the multi-sport / multi-market
expansion. It is updated as work lands so a compacted session can resume from it.

## Baseline (before any change)

- Python: 3.11.18 in `.venv` (created with `uv`; system `python` is absent).
- Test suite: **1,207 collected** (the brief says 1,177; the checkout's actual
  count is recorded here). `pytest -q` passed.
- `ruff check .` passed; `mypy .` passed (123 source files).
- Football replay baseline (`scripts/replay_mappings.py
  tests/fixtures/replay/2026-11-03 --no-learn`):
  - matches_total=3, books=[mbet, sportplus, wwin]
  - pairs_total=3, pairs_verified=1, false_merges=0
  - groups_verified=1, surebets_count=3
  - market_rows_total=18, mapped=18, unmapped=0
  Saved at `/tmp/opencode/replay_before.json` (not committed).

## Measurement rule

A sport is **admissible** only when at least three of the nine enabled books
(`mozzartbet, mdshop, admiralbet, betole, mbet, sportplus, premier_kladionica,
wwin, maxbet`) publish at least three comparable full-match market families
(moneyline, handicap, total), with the same settlement, during the measured
window. The raw probe is `scripts/measure_sports.py`; its report is written to
`docs/evidence/`.

## Chosen implementation (evidence-driven)

- **Basketball**: moneyline (incl. OT), handicap (regulation), total (regulation).
- **Tennis**: match winner, game handicap, total games (all full match).
- Books implemented for these sports: sportplus, mbet, mdshop, admiralbet,
  maxbet (six bookmakers incl. the two NSoft books, four independent price
  sources).
- Ice hockey was measured but left out: only two books offer three
  regular-time comparable markets (see discovery report); mixing regular-time
  and incl-OT totals would be a settlement mismatch. Blocking evidence per book
  is in the discovery report.
- premier_kladionica, mozzartbet, wwin, betole: non-football parsing not
  implemented in this pass; exact blockers in the discovery report.

## Invariants

1. Football behaviour, cache serialisation semantics and replay metrics must not
   change. New fields default to `football` and existing market ids stay.
2. Only groups the certainty gate marks `verified` may be priced.
3. A sport mismatch is a hard reject (`sport_mismatch`) and matcher candidates
   are bucketed by sport, so cross-sport merges are impossible twice over.
4. No generated file is hand-edited; no human mapping approval is required.

## Progress log

- [x] Baseline captured.
- [x] Sport schema + hard identity key.
- [x] Per-book sport normalisation + sport-aware gate/matcher.
- [x] Prematch parsers for basketball/tennis (sportplus, mbet, nsoft, maxbet).
- [x] Live parsers for the same books.
- [x] Arbitrage market semantics (moneyline/handicap/total).
- [x] Football extra markets with admission evidence.
- [x] API/cache per-sport reporting.
- [x] Dashboard "Other sports" tab with sport filter, in Upcoming and Live.
- [x] Tests, docs, real scans, replay comparison. See `docs/MULTISPORT_EVIDENCE.md` and `docs/evidence/`.

## Follow-up pass: line and name verification (2026-11-04, later)

- [x] `over_under_0_5` / `4_5` / `5_5` now parse on every book that publishes
      them: maxbet, NSoft (MDShop + Admiralbet), WWIN, Premier, MBet (4.5/5.5),
      Mozzartbet (4.5/5.5). SportPlus publishes only 1.5/2.5/3.5; Betole's desk
      exposes only 2.5.
- [x] Measured admission rerun: 961 / 3,827 / 2,452 rows, 4–5 independent price
      sources each, 0 outliers (`docs/evidence/2026-11-04-football-lines.json`).
- [x] Browser/vision checks on MaxBet (0.5/4.5/5.5 labels and prices) and
      Mozzartbet (goal-range 4.5/5.5, no 0.5); MDShop list and Betole desk
      checked against their own payloads.
- [x] Non-football identity fixes: compound surnames and doubles, Ž/Wom/WTA/ITF
      W markers, group-wide anchor selection, same-provider-id clock/category
      precedence, tennis-only missing-gender bridge, group-level kickoff/league
      fallback, clean basketball club/sport/gender tokens.
- [x] Matching audit: 0 missed provider pairs, 0 missed exact-name pairs inside
      the 15-minute window, 0 false merges for basketball and tennis
      (`docs/evidence/2026-11-04-team-matching-audit.json`).
- [x] Stale-price correction: a dropped stale set no longer counts as a price
      source, distinct `price_source` values are counted, and a non-football
      book whose side of a line is >20% from the peer median cannot support an
      edge. The 13.08% NBA handicap artefact is gone.
- [x] Removed a dead duplicate `elif exact_teams` branch in the certainty gate.
- [x] Added `scripts/record_scan.py` and `scripts/audit_nonfootball_matching.py`
      so the scan and matching numbers are reproducible.
- [x] Football replay unchanged: 3 matches, 1 verified pair, 0 false merges,
      1 group, 3 surebets, 18/18 mapped rows.

## Final state (2026-11-04)

- Test suite: **1,253 passed** (baseline 1,207; the brief's 1,177 differs from
  the checkout).
- `ruff check .`, `mypy .`, `scripts/generate_market_mapping_doc.py --check` and
  `scripts/generate_market_registry.py --check` all clean.
- Football replay before/after identical (see `docs/evidence/2026-11-04-replay.json`).
- Real prematch (`scripts/record_scan.py`): 9,629 matches, 1,657 verified
  groups, 7 football surebets, 1 basketball, 0 tennis; the only non-football
  surebet is 0.36%.
- Real live: 182 matches, 23 verified groups, 1 football surebet, 0 other-sport.
- Matching audit: 0 provider misses, 0 exact-name misses in window, 0 false
  merges (`docs/evidence/2026-11-04-team-matching-audit.json`).
- Dashboard was verified in a browser earlier; the new changes do not touch it.
- Changes remain uncommitted; nothing was committed, pushed, or bet.
