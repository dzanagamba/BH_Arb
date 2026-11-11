# BH_Arb — agent instructions

BH_Arb is an advisory arbitrage scanner for the Bosnian bookmaker market. It
scrapes odds from ten configured books, decides which listings are the same
match, prices only the groups a certainty gate can defend, and shows them on a
PWA dashboard. It never logs in or places a bet.

## Map

| Where | What |
|---|---|
| `main.py` | Starts uvicorn on `server.app:app` (`HOST`/`PORT` from `config/settings.py`). |
| `server/app.py` | FastAPI app, lifespan (`_restore_state()`, scheduled scan loops), middleware, the `/api` key guard, static PWA. |
| `server/api.py` | `run_scan(mode)` and every `/api` route (large; grep, do not read top to bottom). Helpers split out: `candidate_scoring`, `json_store`, `sqlite_store`, `timeutil`, `book_health`, `bets`, `paper`, `alerts`, `scan_cost`, `observability`, `deeplink_verifier`, `pairing_audit`. |
| `scrapers/` | One adapter per book plus shared transport (`base`, `transport`, `retry`, `ratelimit`, `breaker`, `browser_pool`, `wire_schemas`, `har_fixtures`, `forensics`). |
| `engine/` | Pure domain logic: names/teams/leagues, `matcher`, `certainty` (the gate), `deeplinks`, `market_registry`, `market_consensus`, `arbitrage`, stale/skin/feed-integrity guards, mapping learner and evidence ledger. |
| `models/schemas.py` | Shared Pydantic types: `Match`, `Market`, `MatchGroup`, `Surebet`, … |
| `config/` | `settings.py` (env), `bookmakers.py` (the one adapter declaration), curated JSON; `config/generated/` is runtime-learned operator state. |
| `frontend/` | Vanilla-JS PWA (`index.html`, `js/app.js`, `i18n.js`, `sw.js`); talks only to `/api`. |
| `scripts/` | Operator and CI tools (audits, fixture/HAR capture, `record_scan.py`, generated docs). |
| `tests/` | Offline suite; fixtures under `tests/fixtures/`. |
| `docs/`, `research/` | Operator docs, dated evidence (`docs/evidence/`), research briefs (`research/00_README.md`). |

Scan flow: `scan_loop` / `POST /api/scan` → `run_scan` → each enabled adapter's
`scrape()` → mapping learn → `MatchMatcher.group_matches` (gate per pair) →
skin / stale / feed-integrity guards → `ArbitrageEngine.find_surebets` on
`verified` groups → `FeedState` → dashboard. Dependencies run one way:
`scrapers` → `engine`; `server` uses both; no `engine`, `server` or `scrapers`
module imports `scripts` (pinned for `server` by `tests/test_layering.py`).

## Read first

1. `docs/SESSION_BRIEF.md` — current state and next action.
2. `ROADMAP.md` — open rows, the production-readiness checklist, rules,
   acceptance criteria, recent log.
3. The `research/` brief or `docs/evidence/` file a row cites.
4. History only when needed: `docs/archive/ROADMAP_2026-11-11.md` (every closed
   `SR*`/`M*` section, the `P*`/`N*` glossary, the old execution log),
   `docs/archive/SESSION_BRIEF_2026-11-11.md`, `docs/HANDOFF.md`.

N2-4 stays deferred and P1-6 waived; do not start or un-waive either without an
explicit operator instruction.

## Task loop

1. Resume an `In progress` row. Otherwise pick the first `Not started` row whose
   dependencies are `Done`.
2. Skip `Gate: operator` rows until a written decision is recorded under them.
3. Set the row `In progress` **before** coding.
4. Implement only that row, following its Why, Steps and Acceptance.
5. Add or update the tests it names.
6. Verify (below), plus any row-specific measurement or replay command.
7. Tick the acceptance boxes, set `Done`, add an execution-log row with the
   commands and pasted measured output, update `docs/SESSION_BRIEF.md`.
8. Review the diff. Commit and push with a conventional message only when the
   operator explicitly asks; otherwise leave the working tree for review.
9. If blocked, record the blocker in the row and stop. Do not start a second row.

Use `.venv/bin/python` if `python` is not on `PATH`.

## Verify

```bash
python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/refresh_fixtures.py --check
python scripts/audit_admissibility.py --check
```

## Test cadence

The suite is ~2,400 tests in roughly 2 minutes (measured figure in
`docs/SESSION_BRIEF.md`). While coding, run only the test files the change
touches; run the full suite **once**, when the row's code is finished, in the
clean runtime state. Do not run `pytest --cov` or
`scripts/check_test_isolation.py` in the routine loop: CI's 3.11 leg runs the
suite in both ledger modes (`BH_ARB_TEST_RUNTIME_LEDGER` empty and `populated`)
and enforces the branch-coverage floor (`fail_under` in `pyproject.toml`). The
one local exception is a change to the ledger, `config/generated/` or the
isolation guard, which also runs
`BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest`. See `docs/CI.md`.

## Running a real scan

A real scan hits the bookmakers, so run one only when a row or the operator asks.
Run it through the app (dashboard or `POST /api/scan`) or through a script that
calls `server.app._restore_state()` **before** `server.api.run_scan(mode)`.
`scripts/record_scan.py` does not restore state yet (SR8-4): run bare, it
rewrites `cache/scan_cost.json` and the other diagnostic stores from empty
globals and wipes the restored history. The 2026-11-11 driver and its results
are in `docs/evidence/2026-11-11-test-scan.md`. To look at a populated dashboard
without traffic, seed `api.cached_surebets`/`cached_matches` with
`api.SCRAPERS.clear()` instead of scanning.

## Maintenance work and ad-hoc requests

- Work the operator asks for that has no row gets a row first (`In progress`)
  and an execution-log entry.
- Never un-gate a `Gate: operator` row without a written operator approval.
- Keep changes in small, file-disjoint bundles; update `docs/SESSION_BRIEF.md`
  and `ROADMAP.md`; do not commit unless asked.
- A deferred finding stays in `ROADMAP.md`; do not silently start it later
  without operator approval.
- Edit `ROADMAP.md` between headings (`### ID` to the next `### `), never by
  slicing on `---`, and compare `grep '^### ' ROADMAP.md` before and after a
  scripted edit so no row is lost.

## Measurement discipline

- The suite must pass in both clean and populated-ledger modes before a push; CI
  verifies both.
- Run the command that proves a claim and paste the measured output into the
  execution log; never report a number you did not measure.
- `MARKET_MAPPING.md` is generated. Regenerate it with
  `python scripts/generate_market_mapping_doc.py`; never hand-edit it.

## Shared building blocks

- `engine/name_keys.raw_team_key()` is the only raw team-name key. The certainty
  gate, evidence ledger and review diagnostics delegate to it; do not copy a
  second NFKD/punctuation fold.
- `engine.market_consensus` owns complete-market, devig and outlier math.
  Operator scripts import it; do not reintroduce local market tables.
- `engine.market_registry.registered_spec()` is the shared per-book resolver.
  It keeps the `has_source_id` seam used by test fakes. Other registry reads go
  through the module accessors `registry()`, `has_source_id()`, `specs_for()`,
  `lookup_type()` and `ids_for()`; never import `MARKET_REGISTRY` into another
  module, or the test seam that replaces the module global will miss it.
- `engine.deeplinks` owns the deep-link declaration store the certainty gate
  reads (`config/bookmaker_deeplinks.json`, its cache and provenance, the
  `supports_event_id: false` predicate and `build_event_url`).
  `engine.deeplinks.settle_link()` is the one link-settled predicate: the gate,
  the cache restore and the dashboard counter all call it.
  `engine.ah_labels` owns the Asian-handicap label helpers; `scrapers.common`
  re-exports them for the adapters. Never import `scrapers` from `engine`.
- `config/bookmakers.py` `DECLARATIONS` is the one per-book declaration (module,
  class, transport, enabled, timeouts). `scrapers/protocol.BookAdapter` is the one
  adapter contract: no-arg construction and an async
  `scrape(live=, scan_time=, sports_wanted=)`, even when an adapter ignores a
  keyword. Read the class through `SCRAPERS.adapter(book)` so mypy checks it;
  `SCRAPERS.get()` is `Any`.
- Browser books call their JSON APIs through `scrapers.base.measured_api_get/post`
  (an in-page `fetch`, SR4-8a). Never use `page.request`: it bypasses
  `context.route` and HAR, which the replay depends on.
- `scrapers/har_fixtures.py` owns the committed HAR rules and
  `scripts/capture_har.py` regenerates them; never hand-edit a `.har.gz`. A
  replay must run with `route_from_har(not_found="abort")`. See
  `docs/HAR_REPLAY.md`.
- `server/csv_export.csv_cell()` neutralises formula-leading cells in every CSV
  export. Use it rather than a local copy.
- `server/json_store.atomic_write_json()` / `read_json()` are the JSON-store
  layer for `cache/` and `config/generated/` files.
- `server/sqlite_store.connect()` / `connect_readonly()` are the only SQLite
  connection paths for `cache/bh_arb.sqlite3` (WAL + `synchronous=NORMAL`).
  `server/timeutil` is the server clock: `utcnow()`, `naive_utc()`, `iso_now()`
  and `iso_seconds()`; do not hand-write another naive-UTC `now`.
- Keep `engine/__init__.py` and `scrapers/__init__.py` lazy. Import submodules
  directly (`from engine.matcher import MatchMatcher`).
- Dependencies are pinned in `requirements*.txt` and resolved in
  `requirements*.lock` (`scripts/lock_requirements.py`); Docker and CI install
  the locks.

## Authentication

`api_key_guard` in `server/app.py` resolves the env key or a named key for every
`/api` route except `/api/health` (M1-1), so a new route cannot rely on a
per-route dependency alone. Do not weaken that back to per-route-only auth. With
no bootstrap key and no stored key record the API is open by documented design
(local-only, loopback bind). See `docs/AUTH.md`.

## Trust invariants — never weaken

1. Only `verified` groups reach pricing.
2. `verified` means zero outstanding reasons, including the link half.
3. Only a browser check can set `deep_link_verified`; no human or AI action can.
4. A missing declaration fails safe.
5. A false merge is worse than a split; no fuzzy score alone confirms identity.
6. `sport` is a hard identity gate; no cross-sport pricing.
7. Settlement is part of market identity; regulation vs overtime never pair.
8. One leg per bookmaker and one leg per price source.
9. The scanner never logs in, places a bet, moves money, or evades account limits.
10. Never lower the certainty gate to increase the number of surebets.

## Scraper rules

- A scraper failure must fail closed: a book that cannot be read is missing from
  the scan, never filled with stale or guessed prices.
- Reliability changes must never increase traffic. Retries, limiters and
  breakers only ever reduce or space out traffic.
- No stealth, fingerprint masking, TLS impersonation (`curl_cffi`), captcha
  solving or proxy rotation, except the scoped browser exception below. Do not
  spread the pattern.
- **Browser fingerprint masking is a scoped exception** (SR0-1, operator decision
  2026-11-08). `launch_browser()` keeps
  `--disable-blink-features=AutomationControlled` and the init script that hides
  `navigator.webdriver` and supplies `navigator.plugins`, `navigator.languages`
  and `window.chrome`, because the browser books need it to pass
  Cloudflare/Turnstile. It stays limited to those markers inside
  `launch_browser()`: no TLS impersonation, proxy rotation, captcha solving,
  extra stealth or account-limit evasion. A book that is still challenged is
  reported `blocked` and drops out; revisit SR0-1 if the browser books drop out.

## Session handoff

Keep `docs/SESSION_BRIEF.md` under ~60 lines: goal, row status, project state
with the last measured baselines, next action, last commit, blockers. Update it
at the end of every row. It replaces its own content each time; history goes in
the `ROADMAP.md` execution log, not in the brief.

## Do not

- Do not delete `config/generated/mapping_evidence.json` or other operator
  runtime state to make a test pass; redirect tests instead.
- Do not change trust rules, accepted evidence semantics, or price-source
  identity as part of an unrelated row.
- Do not start from `cache/` contents; they are runtime state, not fixtures.
- Do not edit the archive files under `docs/archive/`; they are a record.
