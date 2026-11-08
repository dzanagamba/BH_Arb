# Session brief

**Updated:** 2026-11-08
**Goal:** keep `ROADMAP.md` current without weakening the trust model.
**Current task:** none; SR0-1, SR0-2, SR1-1, SR1-2, SR1-3, SR1-4, SR2-1 …
SR2-6, SR3-1, SR3-2, SR3-3, SR3-4, SR4-1, SR4-2, SR4-3, SR4-3b … SR4-3f,
SR4-3h, SR4-3i, SR4-3j, SR4-4, SR4-5, SR4-6, SR4-7, SR4-7a, SR4-8, SR4-8a,
SR4-9, SR4-10, SR4-11, SR4-12, SR4-13, SR5-1, SR5-2, SR6-1, SR6-2, SR6-3,
SR7-1 and SR7-2 are done.
**SR4-3g is blocked on a live EVLBet payload** (the SR6-3 capture was an empty
feed). Every other `Not started` row is `Gate: operator`; the roadmap is the
single task list in `ROADMAP.md`, N2-4 stays deferred and P1-6 stays waived
until the operator says otherwise.
**Last task commit:** `8a1cb90` — "adapter protocol, in-page fetch and HAR replay
for browser books" (SR6-2, SR4-8a, SR4-8), pushed to `origin/main` on
2026-11-08. The working tree is clean; the commit before it, `e549267`, carries
SR1-4, the gate decisions, SR4-9 … SR4-13, SR5-1, SR5-2 and SR6-1.

## Project state

SR4-8 (2026-11-08, working tree): the browser books' transport is now a
committed, scrubbed fixture set. `tests/fixtures/har/<book>.har.gz` +
`<book>.meta.json` (1.72 MB total) hold the page document and that book's API
calls, with every cookie/authorization header removed and the cookie jar
emptied; `mozzartbet` keeps 30 per-event offers (its full offer is one request
per event) and the rest abort into its list-odds fallback. Replay:
`browser_pool(har_path=...)` → `route_from_har(not_found="abort")` with the
sidecar's `scan_time`, so nothing can reach the network. Measured replays:
admiralbet 93 matches/739 markets, wwin 450/2,643, mozzartbet 207/941. Refresh
with `python scripts/capture_har.py --books all` (it re-replays and records the
verified counts). Tests: `tests/test_har_fixtures.py` (8, normal suite),
`tests/test_har_seams.py` (4), opt-in `tests/test_browser_har_replay.py` (3).
Docs: `docs/HAR_REPLAY.md`; optional CI job `.github/workflows/browser.yml`
(`workflow_dispatch`).

SR4-8a (2026-11-08, working tree, operator choice **A**): the browser books'
API calls are now issued by the page itself. `scrapers/base.py`'s
`measured_api_get/post` run `fetch` in the loaded document with the same
arguments and the same response surface (`PageResponse`: `status`, `headers`,
`body()`, `json()`, `content`), `credentials: "include"`, request/byte
accounting unchanged, and a Python-side 30 s cap that reports the shared
`timeout` kind. No adapter calls `page.request`; rate limit and retry are
untouched. Live A/B on the same offer: admiralbet 3 req/4.71 MB/13.2 s/121
matches → `page.request` 3/4.71 MB/10.3 s/121; mozzartbet 234/72.27 MB/25.5 s/215
→ 233/71.95 MB/37.0 s/215; wwin 46/2.03 MB/13.2 s/459 → 46/2.03 MB/12.1 s/459,
all `ok` (Cloudflare passed, cross-origin admiralbet included). Evidence:
`docs/evidence/2026-11-08-sr4-8a-inpage-fetch.md`. Tests:
`tests/test_page_fetch.py` (10) plus opt-in `tests/test_page_fetch_browser.py`,
which proves with real Chromium that `context.route` sees the in-page API call.
**This unblocks SR4-8** (HAR capture + replay per browser book).

SR6-2 (2026-11-08, working tree): `scrapers/protocol.py` defines `BookAdapter`,
the one adapter `Protocol` (no-arg construction, async `scrape()` with `live`,
`scan_time`, `sports_wanted`), and `AdapterClass = type[BookAdapter]`. The five
adapters that lacked `sports_wanted` (mozzartbet, betole, evlbet,
premier_kladionica, wwin) take it and ignore it, replacing the `TypeError`
signature fallback for them; the fetched offer is unchanged.
`scrapers.registry.__getitem__` is typed `AdapterClass`, a new
`adapter(book) -> AdapterClass | None` is used at the two scan call sites, and
mypy now checks `scraper.scrape(...)` instead of `Any`. New
`tests/test_adapter_protocol.py` (5 tests) pins the contract at runtime and
proves with mypy that all ten declared classes type-check while three broken
adapters (missing entry point, sync entry point, wrong return) do not; the
declaration AST guard counts a concrete class, not a `Protocol`. Suite: 2,242
passed, 8 skipped, 1 xfailed in 100.8 s; mypy 265 files clean.

SR6-1 (2026-11-08, working tree): one `AdapterDeclaration` per book in
`config/bookmakers.py` (name, adapter module/class strings, transport, enabled,
UI fields, per-feed timeouts). `settings.BOOKMAKERS`, the lazy
`scrapers.registry.SCRAPERS`, `PLAYWRIGHT_BOOKIES` (3 browser books) and the 20
transport policies derive from it. `server/api.py` imports no adapter module;
`import server.api` loads 0 book modules; `scrapers.__all__` is derived too.
`tests/test_adapter_declarations.py` (9) fails on an undeclared adapter module
or a declaration without a module, checks the derived lists/exports/policies and
the market-registry book set, and proves laziness.

SR4-13 (2026-11-08, working tree): Premier's delta response is five positional
tables (execRes 5 cols, dogVar 14, dogTipK odds 9, dogLiveScore 43, scalars),
and the strict schema was treating every section as odds — so the 5-column
execRes row dropped the book in both modes. A section is now odds only when a
row has the dogTipK shape, and every row of a recognised section is still
validated strictly. Trimmed live capture in `tests/fixtures/wire/`, evidence in
`docs/evidence/2026-11-08-premier-delta-sections.md`; 5 new tests. Live probes:
prematch 700 matches/5,761 market rows, live 151/868, both error-free.

SR4-12 (2026-11-08, working tree): the structural fingerprint now keeps only
the paths common to every item of a list, so an optional per-item key
(`items[].matchComment`, `events[].aPrevSc`) no longer alerts. Common-path
types are unioned and `null` is ignored when a real type exists; per-item-only
paths are stored as `optional`; a previously optional path promoted to common
is adopted silently, while a common path removed/renamed or a common type change
still drifts. `FINGERPRINT_VERSION = 2` migrates older baselines once without
an alert. New `optional_paths()`; `tests/test_structural_drift.py` is 19 tests
(12 SR4-4 + 7 SR4-12).

SR5-2 (2026-11-08, working tree): `/api/health.book_health.{prematch,live}` now
has one state per configured book — `healthy`, `degraded`, `open`, `blocked`,
`drifted` or `disabled` — with a one-line reason, reduced in
`server/book_health.py` from the SR2-1 last kind, the SR2-6 breaker and the
runtime toggle. It is diagnostic; pricing still reads feed integrity and the
certainty gate. `tests/test_book_health.py` has one test per state plus the
priorities and the endpoint. The measured scan-cost baseline is
`docs/evidence/2026-11-08-scan-cost-baseline.md`: prematch 144.8 s elapsed, 682
requests, 392.77 MiB, 201.06 book-seconds, 1.32 browser-seconds, 6,610
matches/45,192 markets; live 33.7 s, 70 requests, 74.74 MiB, 66.52 book-seconds,
1.45 browser-seconds, 653 matches/3,548 markets. That scan exposed **SR4-13**
(Premier delta sync rows with 5 columns drift the strict schema, both modes),
which is now fixed and probed (see above).

SR5-1 (2026-11-08, working tree): `/api/metrics` now carries every per-book
reliability family. Added a cumulative histogram type (0.05–120 s) and
`bh_scraper_attempts_total`, `bh_scraper_retries_total`,
`bh_scraper_attempt_seconds`, `bh_http_status_total` from `retry_call`;
`bh_book_last_success_timestamp_seconds` on `ok`; `bh_schema_drift_total` in
the wire schemas; `bh_browser_recycles_total{reason}` in the SR3-3 pool. Every
family is documented in `docs/METRICS.md` (linked from the README), and
`tests/test_reliability_metrics.py` scrapes the text output.

SR4-8 (2026-11-08, blocked): HAR replay does not work for the browser adapters
as written. Playwright routing/HAR sees only **page-initiated** requests; the
adapters fetch JSON through `page.request`, which bypasses both (measured: a
route never fired for `page.request`, a real capture held only analytics
traffic). No HAR was committed and the temporary tooling was reverted. **SR4-8a
asks the operator to choose**: A, move the API calls to in-page fetch (full HAR
replay, live transport change, needs a measured scan), or B, a
boundary-recorded HAR shim (no live change, weaker claim). SR4-8 stays blocked
until that is recorded.

SR3-4 (2026-11-08, working tree): a failed browser scrape now leaves a
**Playwright trace and a screenshot** under `cache/forensics/<book>/<scan_id>/`
(no cookies or storage state), pruned by age (7 days) then size (200 MB),
newest kept. `FORENSICS_ENABLED` (default true) controls the overhead; tracing
starts with the context and is discarded on success. `run_scan` appends the
paths to the book's failure note and the capture logs them with the book.
`page.expect_response` was checked and not needed (the only response listener is
supplementary). Tests: 5 unit + 1 opt-in real-browser forced failure.

SR3-3 (2026-11-08, working tree): a scan now shares **one Chromium**.
`scrapers/browser_pool.py` launches it lazily, gives every book a fresh context,
and recycles it after 200 contexts or 600 s (`BROWSER_MAX_PAGES` /
`BROWSER_MAX_AGE_SECONDS`); a disconnected browser is replaced at the next
book, a hung one at the age cap. `run_scan` and `probe_feeds` own the pool;
adapters use `browser_session()`; standalone scrapes still get a private
one-shot browser, and the deep-link verifier keeps its own isolated context.
Measured on the 3-book probe: **3 launches → 1**, wall 74.2 s → 66.8 s; peak
Chromium RSS 838 → 945 MB in these samples, so the win is launch count, not
memory. New `tests/test_browser_pool.py` (8 tests, fake launcher).

SR3-2 (2026-11-08, working tree): the cited route leak is **not applicable**.
playwright-python#3121 was closed as completed on 2026-07-02; the retained
completed tasks were a CPython 3.14 asyncio bug fixed by python/cpython#152585,
and this project runs 3.11/3.12. `context.route("**/*")` stays (no CDP
workaround). New opt-in `tests/test_browser_route_leak.py` loads six image-heavy
pages through the real launcher and pins the completed-task count; measured
growth 0 (baseline 1, after 1). Run with `BH_ARB_TEST_BROWSER=1`.

SR4-11 (2026-11-08, working tree): **wwin is reading again.** The failing body
was not HTML: days 8–9 of the 15-day prematch walk answer HTTP 200 with a
**0-byte body** for every bet group, and the adapter classified that as schema
drift. `_json_body()` now treats an empty/whitespace body as "no rows for that
slice", an HTML page as `blocked`, and any other non-JSON body as drift. New
tests cover all three. Measured with `probe_feeds`: 0 matches before, **1,014
matches / 5,445 markets** after.

SR4-10 (2026-11-08, working tree): **mozzartbet is reading again.** The live
offer omits `value` on a suspended pick (105 of 518 rows in the captured one),
which the strict model treated as drift. `MozzartOdd.value` is now optional;
`game`/`subgame` stay required and a string price is still drift, and a list
page with odds rows but no numeric `value` anywhere is drift (a renamed price
field). The parser still emits no leg without a price. Measured with
`probe_feeds`: 0 matches before, **603 matches / 4,698 markets** after. Evidence:
`docs/evidence/2026-11-08-mozzartbet-missing-value.md`.

SR3-1 (2026-11-08, working tree): Playwright is pinned at **1.64.1** (PyPI
latest) with Chrome Headless Shell 156.0.8078.4 (v1248); the two opt-in browser
tests pass with `BH_ARB_TEST_BROWSER=1` (10 passed). README notes that a pin
change needs the matching `playwright install chromium`. The live run of the
three browser books found admiralbet healthy (780 matches) while mozzartbet and
wwin dropped: both were feed-shape problems, not the upgrade (they failed
identically on Playwright 1.61.0), and both are fixed — SR4-10 (missing `value`)
and SR4-11 (0-byte day windows). The repeated list-page fingerprint alerts were
fixed by SR4-12 (common paths only). The 00:48 scan that day had all three
healthy.

SR4-9 (2026-11-08, working tree): new `scripts/live_canary.py` runs every book
once a day from the operator host, sequentially, through the real adapter and
shared transport policy, and writes `cache/live_canary/YYYY-MM-DD.json`. It
compares with the newest other report: an adapter/missing-scraper error, a book
with at least 10 matches losing more than half, and a market family with at
least 5 markets losing more than half are reasons; a new family is news. Exit is
0 with alarms (a timer must not page), `--strict` returns 1. It never touches a
fixture and is not in CI. New `docs/LIVE_CANARY.md` documents the schema,
thresholds and the 06:17 cron line; the operator installs the timer. New
`tests/test_live_canary.py` (12 tests). No live probe was run.

SR0-1 / SR0-2 / SR6-3 (2026-11-08, working tree): the operator gate decisions
are recorded. **SR0-1 = B**: the browser masking stays as a scoped, written
exception in `AGENTS.md` ("Scraper rules"), limited to `launch_browser()`; TLS
impersonation, proxy rotation, captcha solving, extra stealth and account-limit
evasion stay forbidden. **SR0-2 = keep the default**: `VERIFY_SSL` stays
`false`; `tests/test_transport.py` now asserts `policy.verify is VERIFY_SSL` so a
silent flip fails. **SR6-3 = capture and keep**: the capture attempt answered
HTTP 200 with `[]` for `SportIds=388` and `1`, so there is no EVLBet fixture;
the adapter stays disabled and kept, and `SR4-3g` is blocked on a live payload,
not on a decision. No live scan.

SR1-4 (2026-11-08, working tree): the per-task verification loop now runs the
full suite **once**, in the clean runtime state, plus targeted test files while
coding. `pytest --cov` and `scripts/check_test_isolation.py` are out of the
routine loop: CI's 3.11 leg runs the empty and populated ledger modes and the
coverage floor. The one local exception is a change to the ledger,
`config/generated/` or the isolation guard, which also runs
`BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest`. No test, marker or
trust rule was removed. Measured 2026-11-08: plain suite 90 s, `--cov` 240 s,
isolation 180 s, so the loop drops from ~8.5 min to ~100 s. `AGENTS.md`,
`ROADMAP.md` and `docs/CI.md` say the same. No live scan.

SR4-7a (2026-11-08, working tree): `parse_nsoft_bets` now keeps the first
offered price per normalized outcome label and ignores a later duplicate row
(and its outcome id), so a duplicated NSoft `betOutcome` can no longer become
two legs for one book. The market acceptance logic is unchanged. The strict
xfail was removed; the regression test duplicates the first outcome of the real
MDShop prematch capture with a different price and asserts one label with the
first price, and the mutation property enforces label uniqueness again for
every parser. No live scan.

SR4-7 (2026-11-08, working tree): `hypothesis==6.150.0` was already a dev pin.
New `tests/test_properties_parsers.py` mutates all 17 fixtures that declare
`expected_markets` (nine parser dispatch paths) with 1-3 bounded operations
(drop key, null, scalar type swap, shuffle/duplicate/drop/truncate array, add
unknown key). A mutation the book's wire schema rejects is skipped because
production never passes it to a parser; accepted mutations must return a list
without an unhandled exception, emit only finite positive prices, never repeat
a label for one `(market_type, settlement, period)`, and never emit a
sport/settlement identity outside the clean capture's set. The clean capture
and two filter tests prove the property is not vacuous; the run is ~2 s.
It found one production-reachable defect — `parse_nsoft_bets` appends the same
normalized outcome twice — recorded as **SR4-7a** with a strict xfail, not fixed
in SR4-7. No live scan.

SR4-6 (2026-11-08, working tree): the dev-only `syrupy==5.0.0` pin is in
`requirements-dev.txt`. `tests/test_parser_snapshots.py` runs every fixture that
declares `expected_markets` (17 captures) through the real parser entry point
`tests/test_market_fixtures.py::_run_parser` dispatches to and snapshots only the
normalised `market_type`/`settlement`/`period` and `label`/`value` rows — source
ids, context, outcome ids and timestamps are excluded, and raw payloads are not
snapshotted. Snapshots live in `tests/__snapshots__/test_parser_snapshots.ambr`
and run in the normal suite; a coverage guard keeps the case set equal to the
fixtures declaring `expected_markets`. `--snapshot-update` stays a human action
(documented in `docs/CI.md`, never run by CI). No live scan.

SR4-5 (2026-11-08, working tree): `engine/coverage_budget.py` gained
`cardinality_snapshot` (events and market rows per `book|sport`),
`evaluate_cardinality` (rolling-median `event_drop`/`market_thin` flags,
peer-gated), `push_cardinality_history` and `cardinality_book_reasons`. The
floor is relative and absolute (below 50 % with ≥5 events missing, or
markets-per-event below 50 % with ≥2 rows missing; baselines under 10 events
are not judged), and a drop is only flagged when a peer book still publishes
that sport *and* is itself near its baseline — a shared calendar dip is not a
feed failure. `compute_feed_integrity` maps a flag to the critical reason
`cardinality_drop`, so the book enters the existing quarantine/recovery state
machine and the unchanged `priceable_groups` path; there is no second gate.
`server/api.py` computes/persists the report and bounded history in
`cache/coverage_budget.json`, publishes `bh_cardinality_flags`(/_total), logs
the flag count and exposes `cardinality_floor` in `/api/health`. New
`tests/test_cardinality_floor.py` (9 tests). No live scan.

SR4-4 (2026-11-08, working tree): `engine/structural_drift.py` fingerprints a
raw payload by its sorted key paths and JSON types (values ignored, array
indices collapsed, numeric id map keys collapsed to `<id>`) and stores the first
informative baseline per `(book, endpoint)` in
`config/generated/wire_fingerprints.json`. A later change increments
`bh_wire_structure_drift_total{book,endpoint}` and logs the added/removed paths;
the last good baseline is kept, empty pages do not establish one, and an I/O
failure only logs. Alert-only — it never rejects a payload or touches pricing.
It is wired at every adapter's raw-JSON boundary (MDShop/Admiralbet per
sport+mode, Mozzartbet matches/offer, Betole desk/offers, MBet events,
SportPlus prematch/live, Premier full/delta sync, WWin prematch/live/headerBets,
MaxBet per sport, EVLBet flat offer). `tests/conftest.py` redirects the baseline
into the per-test runtime tree. New `tests/test_structural_drift.py` (12 tests),
including the real MDShop scrape being silent on a price change and alerting on
an unmodelled key, and `/api/metrics` rendering the counter. No live scan.

SR4-3j (2026-11-08, working tree): MaxBet's matches response is a bare
`[event, ...]` list and its fixtures freeze one match's `odds[]` array, so
`wire_schemas.py` gained `MaxbetSpecifiers` (`total`/`hcp`), `MaxbetOutcome`
(`outcome`, `outcomeId`, `status`, `oddValue` and `marketAvailableForBetting`
required but nullable) and `MaxbetMarket` (`id`, `name`, `specifiers` optional
because line-less markets omit it, `outcomes`), plus
`validate_maxbet_odds`/`validate_maxbet_events`. `fetch_and_parse` validates the
list and every event's `odds` immediately after `response.json()`. A non-JSON
body, a non-list response, a non-object event or a drifted market/outcome row is
`ScrapeError(SCHEMA_DRIFT)` and drops the book with zero legs. Unknown keys
count at `market`/`specifiers`/`outcome` in
`bh_wire_unknown_keys_total{book="maxbet",...}`. The event shell (teams,
kickoff, league, status, external ids) has no dated capture and stays unmodelled
(a renamed team field still drops that event silently; SR4-4/SR5-1 close it),
and a renamed specifier on a totals market degrades to "no line" rather than
drift. New `tests/test_wire_schemas_maxbet.py` (22 tests) drives the real
`scrape()` in both modes through respx. No live scan was run.

SR4-3i (2026-11-08, working tree): WWIN's fixtures freeze the `bets[]` array the
parser reads, so `wire_schemas.py` gained `WwinOdd` (`t` and `va` required, `isv`
optional because the documented live row is `{va, t}`), `WwinBet` (`idBt`,
`spec`, `odds`), `WwinEventsPage` (raw `p`/`events`), `WwinHeaderBetsPage`
(`{"bets": [{"<eventId>": bet}]}`) and
`validate_wwin_bets`/`validate_wwin_events`/`validate_wwin_header_bets`.
`scrapers/wwin.py` validates the prematch page (`p` or the historical `events`)
and every event's `bets`, the live `events` page and the live `headerBets` rows
immediately after `response.json()`. A non-JSON body, a missing page key, a
non-object event/header item or a drifted bet row is
`ScrapeError(SCHEMA_DRIFT)` and drops the book with zero legs. Unknown keys
count at `root` for the envelopes and `bet`/`odd` for the rows in
`bh_wire_unknown_keys_total{book="wwin",...}`. The event shell (teams, kickoff,
competition) has no dated capture and stays unmodelled (a renamed team field
still drops that event silently; SR4-4/SR5-1 close it). New
`tests/test_wire_schemas_wwin.py` (25 tests) drives the real `scrape()` in both
modes through a fake browser. No live scan was run.

SR4-3h (2026-11-08): Premier Kladionica's PrSync is positional, so
`wire_schemas.py` gained `PremierOddRow` (price at column 5), `PremierSetTip`
(name at 2), `PremierSetTipVar` (line at 9) and `PremierSetTipTip` (code at 4),
mapped from positional lists through `model_validator(mode="before")`, plus
`validate_premier_odds`/`validate_premier_lookup`/`validate_premier_sync`.
`_sync_call` validates the `[sections]` envelope (at least ten slots) and, for a
full sync, sections 7/8/9; a delta sync's every non-empty section is typed as
odds rows. A non-JSON body, wrong envelope, short row/table or string price is
`ScrapeError(SCHEMA_DRIFT)` and drops the book with zero legs. Because rows are
positional there are no field names to count, so unknown **section slots** past
the documented fifteen are counted at `level="section"`. The event/sports/
competition-group/execRes sections have no dated capture and stay unmodelled (a
renamed team column still drops that event silently; SR4-4/SR5-1 close it). New
`tests/test_wire_schemas_premier.py` (19 tests) drives the real `scrape()` in
both modes. No live scan was run.

SR4-3g (2026-11-08, blocked): EVLBet is disabled, its recorded flat offer is
empty and it has no market capture, so the strict-schema acceptance cannot be
met. SR6-3 (operator) must choose: capture a fixture and keep the adapter, or
remove it. No code was changed; the row is marked `Blocked on SR6-3`.

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
tests including the real `scrape()` drift path. The pattern and the finished
`SR4-3b` … `SR4-3j` follow-up rows are in `docs/WIRE_SCHEMAS.md`.

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
**2,166 passed, 6 skipped, 1 xfailed, 1 warning** in both ledger modes (17
snapshots passed), with **90.53%** coverage (floor 80%; 13,142 statements). The
six skips are the two
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
scan-cost baseline is now measured (`docs/evidence/2026-11-08-scan-cost-baseline.md`);
the seven-day opportunity baseline remains unmeasured and N2-4 owns it.

## Next action

**No `Not started` row is ungated any more.** SR4-8 closed the last one. What is
left needs the operator: **SR4-3g** (blocked on a live EVLBet payload — do not
start it), the **M1-1 … M6-1** rows (all `Gate: operator`, deliberately deferred
from the old backlog; each needs explicit approval before any work), and the
deferred N2-4 / waived P1-6 (leave both alone). Do not invent a task or reopen a
done one. The working tree is clean at `8a1cb90`; a HAR refresh is an operator
action, not a task: `python scripts/capture_har.py --books all`.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
