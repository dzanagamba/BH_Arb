# Session brief

**Updated:** 2026-11-08
**Goal:** keep `ROADMAP.md` current without weakening the trust model.
**Current task:** none; SR1-1, SR1-2, SR1-3, SR2-1, SR2-2, SR2-3, SR2-4, SR2-5,
SR2-6, SR4-1, SR4-2, SR4-3, SR4-3b, SR4-3c, SR4-3d, SR4-3e, SR4-3f, SR7-1 and
SR7-2 are done. SR4-1, SR4-2, SR4-3, SR4-3b, SR4-3c, SR4-3d, SR4-3e and SR4-3f
are in the working tree (not yet committed). The roadmap is the single task list
in `ROADMAP.md`; N2-4 stays deferred and P1-6 stays waived until the operator
says otherwise.
**Last task commit:** `d963625` — full per-match offers for Mozzartbet and
Betole, and the per-book request rate (SR7-1, SR7-2).

## Project state

SR4-3f (2026-11-08, working tree): SportPlus's fixtures freeze one match's
`markets[]` array, so `SportplusMarket` (`id`/`name`/`odds`, required but
nullable so a renamed key is drift and `odds: null` still parses) and
`SportplusOdd` (`alias`/`value`) model the block, and
`SportplusPrematchPage`/`SportplusLivePage` the `{"matches": [...]}` and
`{"sports": [...]}` envelopes (the live `date` key is declared but unread).
`scrape()` validates the prematch body after the optional double-serialised
decode and the live body before parsing; non-JSON or drifted data raises
`ScrapeError(SCHEMA_DRIFT)` and drops the book with zero legs. Unknown keys count
at `root`/`market`/`odd` in `bh_wire_unknown_keys_total{book="sportplus",...}`.
The match shell stays unmodelled (no dated capture), so a renamed team field
still drops that match silently (the gap SR4-4/SR5-1 close). New
`tests/test_wire_schemas_sportplus.py` (19 tests) drives the real `scrape()`
through respx in both modes, including the double-serialised body. No live scan
was run.

SR4-3e (2026-11-08, working tree): MBet (Alea, plain HTTP) has the NSoft
`{"events": [...]}` envelope but a different odds shape: each event's `odds` is
a map whose keys are oddtype keys (data, not an allow-list) and whose values are
either a typed entry or a bare number. `MbetOdd` requires `value`,
`market_key`, `oddtype_key`, `market_status` and `oddtype_status` (nullable but
present in every captured entry), so a renamed price/status field is drift
instead of an odd the parser reads as suspended. `MbetResponse` requires
`events`. `fetch_page` validates the envelope and every event's odds map right
after `response.json()`; a non-JSON page or drifted entry raises
`ScrapeError(SCHEMA_DRIFT)`, propagated by `fetch_pages`, so the book drops with
zero legs. String prices are drift; integers, bare numbers and `null` entries
are kept (the parser already handles those forms). Unknown keys count at
`root`/`odd` in `bh_wire_unknown_keys_total{book="mbet",...}`. The event shell
(sport id, competitors, kickoff, tournament) stays unmodelled — no dated capture
— so a renamed team field still drops that event silently (the gap SR4-4/SR5-1
close). New `tests/test_wire_schemas_mbet.py` (16 tests) drives the real
`scrape()` through respx in both modes. No live scan was run.

SR4-3d (2026-11-08, working tree): Betole's "price row" is a
`{pick_code: price}` map, so it got its own models. `BetoleDeskPage` shapes the
`{"esMatches": [...]}` desk envelope (`esMatches` required, so a renamed key
cannot read as an empty page) and `BetoleOfferRow` the batched full offer
(`id` + `odds` required). Map keys are pick codes (data, not an allow-list), so
every code is accepted and the unmapped `284` control stays in the capture;
values are strict numbers (a string/boolean price is drift, an integer is
accepted, a `null` pick is kept as "no price"). `validate_betole_desk` runs in
the pagination loop and `validate_betole_offers` in `_fetch_full_offers`, both
right after `response.json()`; a non-JSON body or a drifted row raises
`ScrapeError(SCHEMA_DRIFT)` and is not swallowed by the "failed batch keeps desk
odds" fallback, so the book drops with zero legs. Unknown keys count at
`root`/`row` in `bh_wire_unknown_keys_total{book="betole",...}`. The desk event
shell (teams, kickoff, live flags) stays unmodelled — no dated capture — so a
renamed team field still drops that event silently (the gap SR4-4/SR5-1 close).
New `tests/test_wire_schemas_betole.py` (16 tests) drives the real `scrape()`
through respx. No live scan was run.

SR4-3c (2026-11-08, working tree): Admiralbet serves the same NSoft
`getwebevents` envelope as MDShop, so it **reuses** the `NSoft*` models instead
of defining a second shape; reuse was gated on a fixture-backed test. `scrape()`
calls `validate_response(data, book="admiralbet")` right after `response.json()`
and wraps the adapter's historical bare-list form as `{"events": [...]}` so both
shapes get the same schema. A non-JSON body or a drifted row is
`ScrapeError(SCHEMA_DRIFT)`, re-raised by the existing `except ScrapeError:
raise`, so the book drops out with zero legs. Unknown keys are counted in
`bh_wire_unknown_keys_total{book="admiralbet",...}` at the shared NSoft levels
(`root`/`event`/`bet`/`outcome`). The event shell is validated only through the
fields MDShop's capture proved; Admiralbet's extra fallback keys
(`home`/`guest`, `dateFrom`/`kickoff`, `leagueName`) stay unmodelled and are
counted as unknown event keys if present (the gap SR4-4/SR5-1 close). New
`tests/test_wire_schemas_admiralbet.py` (18 tests) drives the real `scrape()`
through a fake browser. No live scan was run.

SR4-3b (2026-11-08, working tree): Mozzartbet validates its raw JSON in the two
places the adapter reads it. `scrapers/wire_schemas.py` models the odds row
(`MozzartGame`/`MozzartSubgame`/`MozzartOdd`), the per-event offer
(`MozzartOffer`, `{"match": {"odds": [...]}}`) and the list envelope
(`MozzartMatchesPage`, `items` + `totalPages`), all `strict=True,
extra="allow"`. `_complete_offer` validates after `response.json()`;
`validate_mozzart_page` checks the pagination envelope and each item's fallback
odds. A renamed `value`, a string price or a non-JSON body raises
`ScrapeError(SCHEMA_DRIFT)`; `_build_matches` re-raises it, so the book drops
out (fail closed) instead of pricing the other events. A per-event
`{"error": ...}` payload (validated with `match = None`) and a request failure
keep that event's list odds. Unknown keys are counted in
`bh_wire_unknown_keys_total{book="mozzartbet",level=root|match|odd|game|subgame}`.
The list item shell (teams, kickoff, competition) has no dated capture yet and
stays unmodelled; `docs/WIRE_SCHEMAS.md` records the gap. New
`tests/test_wire_schemas_mozzartbet.py` (19 tests). No live scan was run.

SR4-3 (2026-11-08, working tree): MDShop validates its raw `getwebevents`
payload before the parser runs. `scrapers/wire_schemas.py` models the NSoft
envelope, event, market block and price row with `strict=True, extra="allow"`;
`fetch_and_parse` calls `validate_response` right after `response.json()`.
Renamed price fields, string/boolean prices and non-JSON bodies raise
`ScrapeError(SCHEMA_DRIFT)`, which the adapter re-raises, so the book drops out
instead of returning zero legs as an empty feed. Unknown keys are kept, counted
in `bh_wire_unknown_keys_total{book,level,field}` and logged, never fatal.
`validate_bets` proves each dated fixture; `tests/test_wire_schemas.py` has 13
tests including the real `scrape()` drift path. The pattern and the remaining
`SR4-3g` … `SR4-3j` follow-up rows (one per book) are in
`docs/WIRE_SCHEMAS.md`.

SR4-2 (2026-11-08, working tree): every fixture in
`tests/fixtures/markets/` now carries a metadata header (`recorded_at` with its
source, `endpoint`/`http_method`, `http_status`, `capture_tool_version`, book,
mode, reviewed `captured_at`, `source`, `payload_kind`, `provenance`). The 17
existing captures were backfilled from their last commit and marked
`git_commit`/`metadata_backfilled`; `captured_at` and the 120-day policy are
unchanged. `refresh_fixtures.py --check` now fails on a missing header or a
credential-shaped key, and `--backfill-metadata` is the reproducible operator
command. New `tests/test_fixture_metadata.py` (25 tests).

SR4-1 (2026-11-08, working tree): `tests/test_transport_adapters.py` (37 tests)
now drives every HTTP adapter's real `scrape()` through `respx` with the
captured fixture payload inside the envelope the adapter requests, and checks
the market families the capture declares. 403/429/503/timeout responses through
all seven adapters must surface the SR2-1 `ScrapeError` kind. EVLBet has no
market capture (SR6-3), so its recorded empty flat offer is pinned as empty.
`tests/conftest.py` blocks real sockets for the whole session; `docs/CI.md`
documents the layer. Dev pin: `respx==0.22.0`.

SR7-1 (2026-11-08, commit `d963625`): both books now parse their full offer.
Betole uses the batched `matches/by-ids` endpoint (22 requests for 809 matches);
Mozzartbet needs one `POST /betting/match/{id}` per event (678 requests,
159.9 s). Betole gained double chance and the 1.5/3.5/4.5/5.5 totals, Mozzartbet
the first-half 1X2 and the 1.5/3.5/4.5 totals. Measured: requests/scan 124 → 777,
scan wall 105 s → 237 s, markets per event betole 4.0 → 8.2 and Mozzartbet
4.1 → 7.9, and both books are now `healthy` (Mozzartbet missing rate 0.558 →
0.170). Fixtures were re-captured on 2026-11-08 and the admissibility baseline
re-recorded as `docs/evidence/2026-11-08-admissibility-baseline.json`. Handicap
and Asian handicap stay unmapped: the offer carries the picks but not the line
value.

SR7-2 (2026-11-08, commit `d963625`): `SCRAPER_BOOK_RATES` overrides the outgoing
ceiling per book (`mozzartbet=60` by default; every other book keeps 5/s).
Betole's full-offer batches run 8-in-flight. Measured: scan wall 237 s → 121-124 s,
Mozzartbet 159.9 s → ~41 s, Betole 31.3 s → 13.3 s, requests unchanged. The
limiter is no longer binding — the browser's per-host connection pool caps
Mozzartbet at ~16.5 req/s — and the remaining ~80 s is local matching/pricing
(M2-1, operator-gated).


SR2-6 (2026-11-07, commit `a13229a`): the scheduled-scan backoff is now a real
per-book circuit breaker in `scrapers/breaker.py`, keyed by `(mode, book)`,
closed → open → half-open with one probe and an injected clock. `blocked`/`429`
open it on the first occurrence with twice a soft failure's cooldown, `empty`/
`timeout`/`transport`/`5xx` open it after `BOOK_BACKOFF_AFTER_FAILURES`, and a
parser error or schema drift never opens it. Cooldowns double per open up to
`BOOK_BACKOFF_MAX_MINUTES`. State, failures and the remaining cooldown are in
`/api/health` under `scheduler.breakers` and in `/api/metrics` as
`bh_book_breaker_state{failures,cooldown_seconds}`. Manual scans still ignore an
open breaker.

SR2-5 (2026-11-07, commit `a13229a`): a scan can no longer hang on one book. Each
adapter runs under `TransportPolicy.adapter_deadline`
(`SCRAPER_BOOK_TIMEOUT_SECONDS`, default 240 s, 2.4× the slowest recorded book),
and the whole scrape phase runs under `SCRAPER_SCAN_TIMEOUT_SECONDS` (600 s).
A book that overruns is `timeout` and missing from the scan; its browser is
closed and its browser slot released, and the books that already returned still
price. The scan deadline deliberately covers the scrape phase only, not the
local matching/pricing work after it (recorded under the task).

SR2-4 (2026-11-07, commit `a13229a`): `scrapers/ratelimit.py` adds one outgoing
limiter per bookmaker, acquired once per attempt inside `retry_call` (retries
included and the first attempt included). It is hand-rolled rather than adding
`aiolimiter`, because the timing test needs a clock/sleep seam and a
burst-free reservation model; two tests pin that and the queueing. The rate is
`SCRAPER_REQUESTS_PER_SECOND` (default 5/s, 0 disables), carried on every
`TransportPolicy` including the three browser books, so their `page.request`
calls are limited too. Against the recorded 2026-11-06 prematch scan (187
requests, busiest book 101 in 57 s) no book's modelled floor exceeds its
recorded wall time, so the measured scans do not get slower.

SR1-1, SR1-2, SR1-3, SR2-1, SR2-2 and SR2-3 (2026-11-07, commit `30b6632`): the
parser-contract equality check now uses a pinned reference date, so it no
longer turns red when a capture crosses the 120-day policy (the real-date
`refresh_fixtures.py --check` alarm is unchanged). The runtime-state guard
ignores SQLite `-shm`/`-wal` sidecars while still comparing the database file
and every other runtime file. CI already runs the suite in the two ledger modes
`check_test_isolation.py` orchestrates, so `AGENTS.md` and `docs/CI.md` now say
that rather than promising a separate step. `scrapers/errors.py` owns one
structural `ScrapeKind`; `run_scan` records it per book, health exposes it, and
`bh_book_kinds_total` reports it while the historical outcome metric is
unchanged. `settle()` returns that shared kind instead of swallowing failures.
`scrapers/transport.py` owns the per-book timeout/limit policy and one HTTP
client per book per scan, closed when the scraper gather returns.
`scrapers/retry.py` now applies full jitter, the attempt cap and total-time
budget, `Retry-After` and one-attempt 403/challenge blocking, with every attempt
counted; wwin's private retry loop is gone.

M7-1 (2026-11-07, commit `9cd37d0`): presentation-only dashboard fixes — Unicode
name capitalisation, the re-check banner's escaped age markup, a worded
`unconfirmed` row badge, a quiet pre-scan freshness notice (full warning as
soon as a row is listed), book-tag contrast and phone slip totals. Assets are
now `?v=8`.

On 2026-11-07 the old roadmaps and the maintenance backlog were folded into
`ROADMAP.md` and deleted; the research briefs moved to `research/`. The
`P*`/`N*` IDs are now historical labels with a glossary in the `ROADMAP.md`
History section. P1-6 is waived and excluded. The suite runs
**2,024 passed, 6 skipped, 1 xfailed, 1 warning** in both ledger modes, with
**89.18%** coverage (floor 80%; 12,666 statements). The six skips are the two
opt-in runtime-state checks, the two Chromium tests unless
`BH_ARB_TEST_BROWSER=1`, and the two load budgets unless `BH_ARB_TEST_SLOW=1`.
Ruff, MyPy (236 source files), Node syntax checks and the generated market doc
are clean. The xfail documents the deferred named-key auth gap (see below).

### 2026-11-06 maintenance pass (`2e06756`)

A six-audit cleanup pass landed in `2e06756`.
It removed dead symbols and duplicate price/registry helpers, unified the team
key, fixed the stale-price cap, mapping coverage with cached dict rows,
non-finite bet inputs, `days` bounds, CSV formula escaping, per-book cache
restore and the verify rate limit; repaired the service worker, feed-mode
races, Bosnian wiring, mobile slip trap, settings-drawer focus and download
auth headers; and made the SBOM describe the resolved runtime, with workflow
permissions and Dependabot coverage. The full suite, Ruff, MyPy, the market doc
check, the isolation check and an end-to-end browser pass (service worker,
offline shell, all tabs, BS/EN, exports, a real 155 s scan producing 4 visible
surebets, and a live odds re-check) are green.

Deferred: auth middleware/scope redesign (the xfail), event-loop offload of scan
stages, `server/api.py` decomposition, constraints lock, Docker Chromium/CVE
checks, dependency bumps, legacy URL-map removal, `link_sweeps` storage decision,
approve/reject route decision, and branch-coverage gating. The full backlog is
in `ROADMAP.md` (the `M*` rows, each gated on operator approval).

N3-2 adds `engine/admissibility.py` and `scripts/audit_admissibility.py`. The
offline report has a stable schema and records, per book and sport, the measured
market families with their settlements; for every enabled football market it
records the dated evidence row, the per-book registry declarations and, for
0.5/4.5/5.5, the measured price sources. The dated baseline is
`docs/evidence/2026-11-08-admissibility-baseline.json`.

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

Start **SR4-3g** (strict wire schema for EVLBet), the next follow-up row after
SR4-3f, subject to SR6-3: EVLBet is disabled, returns an empty flat offer and
has no market capture, so a payload schema cannot be proved. Record that against
the row; if SR6-3 has no written operator decision, take the next row after it
(SR4-3h Premier Kladionica) instead and leave SR4-3g blocked on SR6-3. SR4-5 is
also ungated, but the SR4-3 follow-ups are earlier rows. The SR3 rows are still
blocked on SR3-1 (gate SR0-1). The operator gates waiting for a decision are
SR0-1, SR0-2, SR4-9 and SR6-3. N2-4 stays deferred and P1-6 stays waived. Do not
invent a task or reopen a done one. SR4-1, SR4-2, SR4-3, SR4-3b, SR4-3c, SR4-3d,
SR4-3e and SR4-3f are in the working tree; commit them if the operator asks.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
