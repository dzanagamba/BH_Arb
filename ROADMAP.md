# BH_Arb roadmap

This is the single task list for all future work on BH_Arb. It replaces
`PROJECT_ROADMAP.md`, `PROJECT_ROADMAP_V2.md` and `TODO.md`, which were deleted
on 2026-11-07 when this file was created. The old files remain in git history at
`2e06756ecd56b013df6e99b58258e8d2cfaa0e25` (BASE), for example
`git show 2e06756ecd56b013df6e99b58258e8d2cfaa0e25:PROJECT_ROADMAP_V2.md`.

The task IDs in the History section (`P*` and `N*`) are historical labels kept
for the many docs and test docstrings that still cite them. New work uses the
`SR*` and `M*` IDs in this file.

## How to use this file

1. Open `docs/SESSION_BRIEF.md`, then this file.
2. Resume a task marked `In progress`. Otherwise take the first `Not started`
   task whose `Depends` are all `Done` and whose `Gate` (if any) is cleared.
3. Set it `In progress` before coding. One task per session.
4. Do only that task's steps. Re-check every `path:line` first; the briefs in
   `research/` were written on 2026-11-07 and lines drift.
5. Add the named tests, then run:
   ```bash
   python -m pytest
   python -m ruff check .
   python -m mypy .
   python scripts/generate_market_mapping_doc.py --check
   python scripts/check_test_isolation.py
   python scripts/refresh_fixtures.py --check
   python scripts/audit_admissibility.py --check
   ```
   (`.venv/bin/python` if `python` is missing.)
6. Tick the acceptance boxes, set `Done`, add a line to the execution log at the
   bottom, update `docs/SESSION_BRIEF.md`.
7. Do not commit unless the operator asks. If blocked, write the blocker under
   the task and stop.

A task marked **Gate: operator** needs a written operator decision recorded under
the task before any code changes. A task marked `Gate: operator` on the `M*`
rows additionally means it must not start without explicit operator approval,
because those items were deliberately deferred from the old maintenance backlog.

## Definition of done

For every task:

- Acceptance criteria are met and checked off.
- New/updated tests pass; the full offline suite, Ruff, MyPy and the generated
  market-doc check pass.
- The suite is verified both with a clean runtime state and with a populated
  generated ledger.
- User-facing or operator-facing docs are updated, including
  `docs/ACCEPTANCE.md` for any number that changes the project's readiness story.
- The execution log below has a dated entry with commands, measured results and
  files changed; the measured output is pasted in, never merely claimed.
- `docs/SESSION_BRIEF.md` is updated with the task status, next action, last
  commit and any blocker, so the next session can resume from it.
- `MARKET_MAPPING.md` is regenerated with
  `python scripts/generate_market_mapping_doc.py`; never hand-edit the generated
  table.
- No trust rule is weakened to make a number look better.

## Rules every task keeps

- The ten trust invariants in `AGENTS.md` are never weakened; follow them there
  rather than restating them here.
- A scraper failure must fail closed: a book that cannot be read is missing from
  the scan, never filled with stale or guessed prices.
- Reliability changes must not make the scanner hit a site harder. Retries,
  limiters and breakers only ever reduce or space out traffic.
- No stealth, fingerprint spoofing, TLS impersonation (`curl_cffi`), captcha
  solving or proxy rotation. See "Rejected" below.
- Keep `scrapers/__init__.py` and `engine/__init__.py` lazy.
- New dependencies are pinned in the same place the existing ones are, and each
  is named in the task that adds it.
- Do not place bets or log in to a bookmaker; the product is advisory. AI may
  rank candidates but never approve them.
- Do not add a book or market without a capture or dated absence proof.
- Do not raise live polling without a push/sub-10 s feed.
- No task may lower the certainty gate (invariant 10 in `AGENTS.md`); a missed
  match is cheaper than a false merge.

## Current state

Ten adapters under `scrapers/`, duck-typed classes with `async scrape()` and a
function library in `scrapers/base.py`, registered by hand in `SCRAPERS`
(`server/api.py:1020`) and `PLAYWRIGHT_BOOKIES` (`server/api.py:253`). Seven are
plain httpx (mdshop, betole, evlbet, maxbet, mbet, sportplus,
premier_kladionica); three are Playwright hybrids that read network JSON
(mozzartbet, admiralbet, wwin). One process, `asyncio.gather` per scan,
`Semaphore(3)` for browsers, no scan-level timeout. A fresh `AsyncClient` and a
fresh Chromium per scrape. One hand-rolled retry (`fetch_with_retry`,
`scrapers/base.py:148-177`: 3 attempts, 5xx/network only, no jitter, no 429/403
handling) that mozzartbet, admiralbet and premier_kladionica do not use; wwin has
its own. Anti-breakage: pydantic models, dated fixture contracts
(`engine/parser_contracts.py`), feed-integrity quarantine, coverage deltas,
stale/outlier guards. Observability: stdlib JSON logs, an in-house Prometheus
registry at `/api/metrics`, `/api/health`. Fixtures are trimmed live JSON captured
by hand (`scripts/capture_market_fixtures.py`); tests stub at the parser boundary,
there are no transport-level tests and Playwright scrapers are not exercised in CI.

Test counts, coverage, lint and MyPy baselines live in `docs/SESSION_BRIEF.md`;
do not copy stale numbers here.

## Task table

| ID | Title | Status | Depends | Gate |
|----|-------|--------|---------|------|
| SR0-1 | Decide on browser fingerprint masking | Not started | — | operator |
| SR0-2 | Decide TLS verification default | Not started | — | operator |
| SR1-1 | Remove the date bomb in the contract test | Done | — | — |
| SR1-2 | Run the isolation check in CI | Done | — | — |
| SR1-3 | Stop `settle()` swallowing navigation errors | Done | — | — |
| SR2-1 | Scrape error taxonomy | Done | — | — |
| SR2-2 | Per-book transport policy and shared client | Done | SR2-1 | — |
| SR2-3 | Retry policy rewrite (jitter, budget, 429, 403) | Done | SR2-1, SR2-2 | — |
| SR2-4 | Outgoing per-book rate limiter | Done | SR2-2 | — |
| SR2-5 | Adapter and scan deadlines | Done | SR2-1 | — |
| SR2-6 | Per-book circuit breaker | Done | SR2-1, SR2-3 | — |
| SR3-1 | Upgrade Playwright | Not started | SR0-1 | — |
| SR3-2 | Leak-free resource blocking | Not started | SR3-1 | — |
| SR3-3 | Shared browser lifecycle | Not started | SR3-2, SR2-5 | — |
| SR3-4 | Response capture and failure forensics | Not started | SR3-3 | — |
| SR4-1 | Transport-level tests with respx | Not started | SR2-3 | — |
| SR4-2 | Fixture metadata and age policy | Not started | — | — |
| SR4-3 | Strict wire schemas, one book first | Not started | SR2-1 | — |
| SR4-4 | Structural fingerprint and drift alarm | Not started | SR4-3 | — |
| SR4-5 | Cardinality floors against a baseline | Not started | SR2-1 | — |
| SR4-6 | Snapshot tests of normalised parser output | Not started | SR4-2 | — |
| SR4-7 | Property-based mutation tests for parsers | Not started | SR4-6 | — |
| SR4-8 | HAR fixtures for browser books | Not started | SR3-4, SR4-2 | — |
| SR4-9 | Scheduled live canary | Not started | SR4-4, SR4-5 | operator |
| SR5-1 | Per-book reliability metrics | Not started | SR2-6 | — |
| SR5-2 | Per-book health state and live cost baseline | Not started | SR5-1 | — |
| SR6-1 | Single adapter declaration | Not started | SR2-2 | — |
| SR6-2 | Adapter `Protocol` and mypy enforcement | Not started | SR6-1 | — |
| SR6-3 | Decide EVLBet's future | Not started | — | operator |
| SR7-1 | Full per-match market offers (Mozzartbet, Betole) | Done | — | operator |
| SR7-2 | Raise the Mozzartbet request rate | Done | SR7-1 | operator |
| M1-1 | Redesign named-key authentication | Not started | — | operator |
| M1-2 | Decide `accepted_odds: 0` with a stake | Not started | — | operator |
| M1-3 | Auth-failure rate limit and PBKDF2 cache | Not started | — | operator |
| M2-1 | Move scan CPU/I/O off the event loop | Not started | — | operator |
| M2-2 | Stop rewriting the cache on verify-links | Not started | — | operator |
| M2-3 | Serve a cached `/api/health` summary | Not started | — | operator |
| M2-4 | Decide the candidate queue cap | Not started | — | operator |
| M2-5 | Review compact cache/ledger representations | Not started | — | operator |
| M3-1 | Decompose `server/api.py` | Not started | — | operator |
| M3-2 | Move the deep-link store to `engine/` | Not started | — | operator |
| M3-3 | One link-settled predicate | Not started | — | operator |
| M3-4 | Unify datetime and SQLite helpers | Not started | — | operator |
| M3-5 | Route registry lookups through `registered_spec()` | Not started | — | operator |
| M3-6 | Move `pairing_audit` and verifier into `server/` | Not started | — | operator |
| M4-1 | Add a resolved constraints/lock file | Not started | — | operator |
| M4-2 | Docker Chromium check and image CVE scan | Not started | — | operator |
| M4-3 | Pin Actions by SHA and base image by digest | Not started | — | operator |
| M4-4 | Plan the remaining dependency upgrades | Not started | — | operator |
| M5-1 | Remove legacy URL maps | Not started | — | operator |
| M5-2 | Decide the `link_sweeps` table | Not started | — | operator |
| M5-3 | Decide approve/reject functions | Not started | — | operator |
| M5-4 | Decide `raw_market_resolver.resolve_offers` | Not started | — | operator |
| M5-5 | Finish the PWA | Not started | — | operator |
| M5-6 | Zero-matches diagnostic and no-surebet state | Not started | — | operator |
| M5-7 | Fix the feed-mode tab ARIA contract | Not started | — | operator |
| M6-1 | Branch coverage floor in CI | Not started | — | operator |
| M7-1 | Dashboard UI polish pass | Done | — | — |

---

## Task sections

### SR0 — Operator decisions

### SR0-1 Decide on browser fingerprint masking — Gate: operator

Status: Not started

Why: `launch_browser()` (`scrapers/base.py:20-65`) launches Chromium with
`--disable-blink-features=AutomationControlled` (`:32`) and an init script that
hides `navigator.webdriver` and fakes `navigator.plugins`, `navigator.languages`
and `window.chrome` (`:50-55`). That is fingerprint masking, which trust
invariant 9 ("never evades account limits") and this file's rules exclude.
Briefs `research/01_shared_infra.md` §3 and
`research/05_browser_automation_research.md` conclusion 4. The three browser
books reportedly need the browser to pass Cloudflare/Turnstile
(`research/03_fixtures_and_pain_points.md` §B), so removing it may take them
offline.

Options to put to the operator:
- A. Remove the flag and the init script. Locale, timezone, UA header and
  resource blocking stay (they are not masking). Any book that then gets a
  challenge is reported `blocked` and drops out of the scan (fail closed).
- B. Keep it as a written, scoped exception in `AGENTS.md`.

Recommendation: A.

Acceptance:
- [ ] Decision and date recorded here.
- [ ] If A: flag and init script removed; a test asserts `launch_browser()` adds
      no init script that redefines `navigator.*`; each browser book was run once
      live and its result (ok / blocked) recorded here.
- [ ] If B: exception text added to `AGENTS.md`, quoted here.

### SR0-2 Decide TLS verification default — Gate: operator

Status: Not started

Why: `VERIFY_SSL` defaults to `"false"` (`config/settings.py:364`) and is passed
to every httpx client (`research/01_shared_infra.md` §2,
`research/04_http_reliability_research.md` line ~49). Prices read over an
unverified connection can be tampered with in transit.

Recommendation: default `true`; a per-book override exists only for a named book
with a recorded reason.

Acceptance:
- [ ] Decision recorded.
- [ ] Default changed (if approved); per-book override, if any, lives in the
      transport policy from SR2-2 or in settings with a comment naming the reason.
- [ ] Test asserts the default.

---

### SR1 — Quick fixes

### SR1-1 Remove the date bomb in the contract test

Status: Done

Why: the parser-contract test reads `date.today()`, so the suite turns red on
2027-02-17 with no code change (`research/03_fixtures_and_pain_points.md` §A,
line ~212). Do this before that date. (Was the corresponding item in the old
maintenance backlog.)

Steps: inject the reference date into `engine/parser_contracts.py` checks (a
parameter or a clock seam), have the unit test pass a fixed date, keep the
production check on the real date.

Acceptance:
- [x] Test passes with the system clock set to 2027-03-01 (use a frozen date in
      a test, not a real clock change).
- [x] Production behaviour unchanged: an expired contract still reports stale.

### SR1-2 Run the isolation check in CI

Status: Done

Why: `AGENTS.md` says CI runs `scripts/check_test_isolation.py`; the workflow does
not (`research/03_fixtures_and_pain_points.md` §A, `docs/CI.md:43`). Confirmed
against `.github/workflows/*` (`research/07_roadmap_migration_inventory.md` §5):
CI does not run `check_test_isolation.py`, while `refresh_fixtures.py --check`
and `audit_admissibility.py --check` do run. The SQLite `-shm`/`-wal` guard also
gives a false positive (`research/03_fixtures_and_pain_points.md` §B). (Was the
corresponding items in the old maintenance backlog.)

Steps: confirm against `.github/workflows/*`; add the step, or, if the double
suite run already covers it, make `AGENTS.md` and `docs/CI.md` say so. Fix the
`-shm`/`-wal` false positive.

Acceptance:
- [x] Workflow and docs agree.
- [x] Test covering the `-shm`/`-wal` case.

### SR1-3 Stop `settle()` swallowing navigation errors

Status: Done

Why: `scrapers/base.py:106-115` hides navigation failures, so a challenge page or
timeout looks like an empty feed (`research/03_fixtures_and_pain_points.md` §B).

Steps: let `settle()` return or raise a classified outcome (until SR2-1 lands, a
small local enum is fine; SR2-1 absorbs it).

Acceptance:
- [x] Unit test with a fake page whose navigation raises: the outcome is a
      failure, not an empty success.

---

### SR2 — HTTP reliability core

### SR2-1 Scrape error taxonomy

Status: Done

Why: `blocked` vs `parse_error` is decided by text heuristics
(`research/03_fixtures_and_pain_points.md` §B); retry, breaker, health and alerts
all need one shared classification.

Steps: add `scrapers/errors.py` (or similar) with outcome kinds — `ok`, `empty`,
`blocked` (403, challenge page), `rate_limited` (429), `timeout`, `transport`,
`upstream_5xx`, `parse_error`, `schema_drift` — and a classifier for httpx and
Playwright exceptions/responses. Use it at the point where `run_scan` records a
book's result. Keep the existing health fields working.

Acceptance:
- [x] Table-driven test mapping status codes and exceptions to kinds.
- [x] Health and metrics report the kind per book.
- [x] No text-matching classification left in the scan path.

### SR2-2 Per-book transport policy and shared client

Status: Done

Why: every scrape builds a fresh `AsyncClient` with per-module timeouts of 20–120 s
and no explicit limits (`research/01_shared_infra.md` §2;
`research/04_http_reliability_research.md` recommendation 1).

Steps: a frozen dataclass `TransportPolicy` per book (connect/read/total timeout,
max connections, requests per second, retry budget, verify). One `AsyncClient`
per book per scan with explicit `httpx.Limits` and `httpx.Timeout`, closed when
the scan ends. Move the module-level timeouts into the policies without changing
their values.

Acceptance:
- [x] Every HTTP adapter gets its client from the shared factory.
- [x] Test: two requests from one book in one scan share a client; clients are
      closed after the scan.
- [x] Timeout values unchanged (diff recorded in the execution log).

### SR2-3 Retry policy rewrite

Status: Done

Why: `fetch_with_retry` (`scrapers/base.py:148-177`) has no jitter, retries
nothing on 429, has no total time budget, and is skipped by mozzartbet,
admiralbet and premier_kladionica (`premier_kladionica.py:437-459`); wwin has a
private copy (`research/01_shared_infra.md` §4,
`research/02_adapters.md` table, `research/04_http_reliability_research.md`).

Steps: adopt `stamina` (new dependency;
`research/04_http_reliability_research.md` §3) or keep it hand-rolled if the
operator prefers no new dependency — record which. Policy: full jitter, attempt
cap and total-time budget from SR2-2; 429 waits for `Retry-After` (capped) and
counts against the budget; 403/challenge is never retried and is reported
`blocked`; 5xx/timeout/transport retried. Every attempt is recorded by
`record_request`. Route premier's JSON-RPC POST, wwin and the `page.request` calls
in the browser books through it where safe (POST retry only if the call is
read-only, which it is for odds feeds — confirm and note).

Acceptance:
- [x] wwin's private retry removed.
- [x] Tests (respx or fake transport): 429 with `Retry-After` waits then succeeds;
      403 is one attempt and `blocked`; budget exhaustion stops early; attempts
      counted.
- [x] No adapter makes more requests per scan than before in the success path.

### SR2-4 Outgoing per-book rate limiter

Status: Done

Why: only wwin's `Semaphore(6)` and `fetch_pages(batch=4)` limit outgoing traffic
(`research/01_shared_infra.md` §5).

Steps: `aiolimiter.AsyncLimiter` (new dependency) per book from the policy,
acquired once per attempt, including retries. Defaults chosen so current scan
duration does not grow by more than the operator accepts; record the before/after
scan time.

Decision (2026-11-07): hand-rolled `scrapers/ratelimit.BookRateLimiter` instead
of adding `aiolimiter`. The acceptance criterion needs a clock/sleep seam the
dependency hides, and the reservation model (one slot per attempt, no burst)
satisfies "N attempts take at least N/R seconds" literally; a leaky bucket with
an initial burst of R does not. It also keeps every attempt accounted in the
project's own retry/policy path, as SR2-3 did. One limiter per
(book, event loop), so a scan shares it per book and politeness does not reset at
a scan boundary; the rate is `SCRAPER_REQUESTS_PER_SECOND` (default 5/s, 0
disables) and it is applied in `retry_call`, so httpx adapters and the browser
books' `page.request` calls both take a slot.

Acceptance:
- [x] Test: N requests at limit R take at least N/R seconds (use a fake clock).
- [x] Measured scan duration before/after in the execution log.

### SR2-5 Adapter and scan deadlines

Status: Done

Why: there is no whole-scan timeout; one hung book delays the scan
(`research/01_shared_infra.md` risks).

Steps: `asyncio.timeout()` around each adapter (from policy) and around the
whole `run_scan`. A book that hits its deadline is `timeout` and missing from the
scan; the others still price. Browser resources are closed on cancellation.

Decision (2026-11-07): the scan deadline wraps the scraping phase (every adapter
task), not the local matching, pricing and persistence work after it. Wrapping
all of `run_scan` would cancel the pricing pass and discard the books that had
already returned, which contradicts "the others still price"; the post-scrape
work is local CPU plus one bounded AI call, so it is not where the hang is. The
scrape phase is also where the browser-slot queue lives, which no per-book
deadline can bound. Books are built by `asyncio.create_task` inside the
transport pool so each inherits the shared-client context; a book that finishes
is remembered immediately, and the book list is rebuilt from those after the
gather, so a cancelled gather never loses a completed book. Budgets:
`TransportPolicy.adapter_deadline` (`SCRAPER_BOOK_TIMEOUT_SECONDS`, 240 s = 2.4×
the slowest recorded book) and `SCRAPER_SCAN_TIMEOUT_SECONDS` (600 s). A
scan-deadline cancellation is recorded as `timeout` but not charged to the
book's scheduled-scan backoff: our own deadline is not the book failing.

Acceptance:
- [x] Test: a fake scraper that sleeps forever is cut off; the rest of the scan
      completes and prices.
- [x] Test: cancellation closes the fake browser/context.

### SR2-6 Per-book circuit breaker

Status: Done

Why: the scheduled backoff after 3 failures (`server/api.py:1740-1764`, cap 60
min) is the only breaker, and it does not distinguish error kinds
(`research/01_shared_infra.md` §5).

Steps: a small in-house async breaker (closed → open → half-open, one probe),
keyed per book, fed by SR2-1 kinds. `blocked` and `rate_limited` open it faster
and longer than `timeout`; `parse_error` does not open it (it is not the site
refusing us). Fold the existing scheduled backoff into it rather than running
both. State survives restarts only if the current backoff already does.

Decision (2026-11-07): `scrapers/breaker.py` owns a `BookCircuitBreaker` in a
process-wide registry keyed by `(mode, book)` — a book's prematch and live
endpoints are different feeds, and a blocked prematch says nothing about live.
States are `closed`/`open`/`half_open`; an elapsed cooldown lets exactly one
probe through, and its outcome closes or re-opens with a doubled cooldown.
`blocked` and `rate_limited` open on the first occurrence with twice the
cooldown of a soft failure; `empty`, `timeout`, `transport` and `upstream_5xx`
open after `BOOK_BACKOFF_AFTER_FAILURES` consecutive ones; `parse_error`,
`schema_drift` and `skipped` are neutral (they cannot open it and cannot reset
it, and a neutral probe releases the slot). Any `ok` closes it and resets the
escalation. The base cooldown is the mode's scan interval (5 minutes when that
feed's schedule is off, so a manual-scan-only install still has a positive
cooldown), doubled on every consecutive open, capped by
`BOOK_BACKOFF_MAX_MINUTES`. `_book_failures`, `_book_skip_until`,
`_BOOK_BACKOFF_LOCK` and `_book_is_backed_off` are gone; manual scans still
ignore the open state (the operator asked), while every scan records its kind
into the breaker. Health reports `scheduler.breakers.<mode>/<book>` and metrics
report `bh_book_breaker_state{mode,book,state}`, `bh_book_breaker_failures` and
`bh_book_breaker_cooldown_seconds`. In-process only, exactly like the backoff it
replaces, so a restart starts every book closed. `allow()` and `record()` are
non-blocking (a thread lock, no awaits): the scan only needs the decision, so
there is nothing for an async API to wait on.

Acceptance:
- [x] Unit tests for each transition with a fake clock.
- [x] Breaker state per book in `/api/health` and `/api/metrics`.
- [x] Old backoff code path removed or delegating.

---

### SR3 — Browser books

### SR3-1 Upgrade Playwright

Status: Not started — Depends: SR0-1

Why: pinned 1.61.0; `research/05_browser_automation_research.md` reports 1.64.1
(2026-10-22). Confirm the latest on PyPI first. (Was the Playwright 1.64 item in
the old maintenance backlog.)

Acceptance:
- [ ] Pin updated, `playwright install chromium` documented if the procedure
      changes.
- [ ] Browser tests pass with `BH_ARB_TEST_BROWSER=1`; each browser book run once
      live, result recorded.

### SR3-2 Leak-free resource blocking

Status: Not started

Why: `context.route("**/*", ...)` (`scrapers/base.py:58-63`) intercepts every
request; `research/05_browser_automation_research.md` cites
playwright-python#3121, a task leak per intercepted request. Verify the issue is
still open for the pinned version.

Steps: if still relevant, block image/media/font with CDP
`Network.setBlockedURLs` (Chromium-only, acceptable) or narrow the route pattern
to resource URLs.

Acceptance:
- [ ] Test or measurement showing task count does not grow across N page loads.

### SR3-3 Shared browser lifecycle

Status: Not started

Why: every scrape starts its own Playwright and Chromium; wwin starts two
(`wwin.py:257`, `:371`) (`research/01_shared_infra.md` §3).

Steps: one browser per scan (or per process with recycling after N pages / M
minutes / RSS threshold), a fresh context per book, a watchdog that restarts a
browser that stops responding. Respect `BROWSER_CONCURRENCY`. The deep-link
browser check keeps its own isolated context so its result cannot be influenced
by scraper state.

Acceptance:
- [ ] wwin uses one browser for prematch and live.
- [ ] Test with a fake browser: recycle after N pages; a crashed browser is
      replaced and the book reports `transport`, not `ok`.
- [ ] Scan duration and peak RSS before/after recorded.

### SR3-4 Response capture and failure forensics

Status: Not started

Why: browser books capture JSON through `page.on("response")` listeners and
`page.request` (`research/02_adapters.md`); failures leave no artefact.

Steps: use `page.expect_response(predicate, timeout=...)` where a listener waits
for one response; on failure save a Playwright trace and a screenshot under
`cache/forensics/<book>/<scan_id>/` with a size and age cap; never store cookies
or storage state in the artefact.

Acceptance:
- [ ] Forced failure in a browser test writes a trace; retention cap tested.
- [ ] Artefact paths appear in the scan log line for that book.

---

### SR4 — Anti-breakage and tests

### SR4-1 Transport-level tests with respx

Status: Not started

Why: no test drives an HTTP adapter's `scrape()` through a fake transport except
one MDShop test with `fetch_with_retry` monkeypatched
(`research/03_fixtures_and_pain_points.md` §A).

Steps: add `respx` (dev dependency). For each HTTP adapter, one test that serves
its fixture through respx and runs `scrape()` end to end, plus 429/403/5xx/timeout
cases using SR2-1 kinds. Block real network in the test session (respx
`assert_all_mocked` or a socket guard).

Acceptance:
- [ ] Seven HTTP adapters covered (EVLBet per SR6-3 outcome).
- [ ] A test that tries a real request fails loudly.

### SR4-2 Fixture metadata and age policy

Status: Not started

Why: fixtures are trimmed JSON with a 120-day policy enforced by
`scripts/refresh_fixtures.py --check`
(`research/03_fixtures_and_pain_points.md` §A); no replay tool expires fixtures by
itself (`research/06_parser_contract_testing_research.md`).

Steps: a sidecar or header per fixture with `recorded_at`, book, endpoint shape,
HTTP status, capture tool version; scrub cookies/tokens; `--check` reports
missing metadata. Do not change the 120-day policy without the operator.

Acceptance:
- [ ] All existing fixtures carry metadata (backfill `recorded_at` from git if
      unknown, marked as such).
- [ ] `--check` fails on a fixture without metadata (test).

### SR4-3 Strict wire schemas, one book first

Status: Not started

Why: no adapter validates the raw payload against a schema; correctness rests on
pydantic models of the parsed result (`research/02_adapters.md`;
`research/06_parser_contract_testing_research.md` recommendation 1).

Steps: for one book (pick the simplest HTTP book), model the raw response with
pydantic `strict=True`, `extra="allow"`, plus an allow-list of known keys; prices
are never coerced from strings silently. A payload that fails is `schema_drift`
and the book drops out (fail closed). Unknown keys are counted and logged, not
fatal. Record the pattern so the other books can follow in later sessions (one
book per session after this).

Acceptance:
- [ ] Fixture passes; mutated fixture (renamed price field) yields
      `schema_drift`, zero legs.
- [ ] Unknown-key count visible in metrics.
- [ ] Follow-up rows "SR4-3b … SR4-3j" added to the table, one per remaining book.

### SR4-4 Structural fingerprint and drift alarm

Status: Not started

Why: `research/06_parser_contract_testing_research.md` §6. Shape changes are
visible before parsing fails.

Steps: compute a stable fingerprint (sorted key paths and value types, arrays
collapsed) of each raw response per endpoint; store the last good one per book;
alert (log + metric) when it changes. Alert only; do not change pricing.

Acceptance:
- [ ] Test: same shape different values → same fingerprint; renamed key →
      different.
- [ ] Drift counter in `/api/metrics`.

### SR4-5 Cardinality floors against a baseline

Status: Not started

Why: an emptied or half-emptied feed (EVLBet empty feed,
`research/03_fixtures_and_pain_points.md` §B) can pass parsing. Coverage-budget
deltas exist (`research/01_shared_infra.md` §7); extend, do not duplicate.

Steps: per book and sport, rolling baseline of events and markets per event;
below a floor (absolute and relative) the book is `empty` or quarantined via the
existing feed-integrity quarantine.

Acceptance:
- [ ] Test: a feed at 10 % of baseline is quarantined; a normal dip is not.
- [ ] Reuses the existing quarantine and coverage code paths (named in the log).

### SR4-6 Snapshot tests of normalised parser output

Status: Not started

Why: `research/06_parser_contract_testing_research.md` recommendation 2.

Steps: add `syrupy` (dev). For each fixture, snapshot the normalised output
(events, markets, settlement, prices), with IDs/timestamps blanked by a matcher.
Do not snapshot raw payloads. A snapshot update requires a reason in the commit.

Acceptance:
- [ ] Snapshots for every fixture that has `expected_markets`.
- [ ] Snapshot tests run in the normal `pytest` run.

### SR4-7 Property-based mutation tests for parsers

Status: Not started

Why: `research/06_parser_contract_testing_research.md` recommendation 4.

Steps: add `hypothesis` (dev) if not present. Mutate fixtures (drop keys, null
values, swap types, shuffle arrays, duplicate markets). Properties: the parser
never raises an unhandled exception; never emits a leg with a missing or
non-positive price; never emits two legs for one book in a group; never changes
sport or settlement.

Acceptance:
- [ ] Property tests for every parser, bounded run time in CI.
- [ ] Any bug found is fixed in a separate task row, not silently in this one.

### SR4-8 HAR fixtures for browser books

Status: Not started

Why: browser books are captured by hand and never replayed
(`research/03_fixtures_and_pain_points.md` §A;
`research/05_browser_automation_research.md` §1 `record_har_path` /
`route_from_har`).

Steps: capture tool writes a scrubbed HAR (no cookies, no auth headers) per
browser book; a test replays it with `route_from_har` and runs the real
`scrape()`. Runs only with `BH_ARB_TEST_BROWSER=1`; add an optional CI job with
Chromium (was the browser-enabled CI Chromium job in the old maintenance
backlog, folded here).

Acceptance:
- [ ] One HAR replay test per browser book.
- [ ] Scrubbing test: no `cookie`/`authorization` headers in any committed HAR.

### SR4-9 Scheduled live canary — Gate: operator

Status: Not started

Why: `research/06_parser_contract_testing_research.md` §6; offline fixtures
cannot see a site change.

Steps: an opt-in scheduled job that runs each book once (rate-limited, no login,
same transport policy), compares fingerprint and counts with the baseline, and
reports. It never refreshes fixtures automatically. The operator decides where it
runs (CI from a datacentre IP may be blocked differently from the operator host)
and how often.

Acceptance:
- [ ] Decision recorded (where, how often).
- [ ] Report format documented; a failing canary does not fail the main CI.

---

### SR5 — Observability

### SR5-1 Per-book reliability metrics

Status: Not started

Why: `research/01_shared_infra.md` §8 — in-house registry exists; keep it
(`research/04_http_reliability_research.md` recommendation 4).

Metrics: attempts, retries, outcome kind counter, status code counter, latency
histogram, breaker state gauge, last success timestamp, schema drift counter,
unknown-key counter, browser recycle counter.

Acceptance:
- [ ] All metrics in `/api/metrics` with a test scraping the text output.
- [ ] Metric names documented in `docs/`.

### SR5-2 Per-book health state and live cost baseline

Status: Not started

Why: `/api/health` is rich but has no per-book state machine; the first live cost
baseline is unmeasured (`research/03_fixtures_and_pain_points.md` §B).

Steps: per-book state (`healthy`, `degraded`, `open`, `blocked`, `drifted`,
`disabled`) derived from SR2-1/SR2-6/SR4-4. Measure and record a live cost
baseline (requests, bytes, seconds, browser seconds per scan).

Acceptance:
- [ ] Health test per state.
- [ ] Baseline numbers recorded in `docs/SESSION_BRIEF.md` or a doc it links.

---

### SR6 — Structure

### SR6-1 Single adapter declaration

Status: Not started

Why: `SCRAPERS` (`server/api.py:1020`), `PLAYWRIGHT_BOOKIES`
(`server/api.py:253`) and the market registry are synchronised by hand
(`research/01_shared_infra.md` risks).

Steps: one declaration per book (name, import path, transport, policy,
enabled flag) that the other lists are derived from; imports stay lazy. A test
fails when a module under `scrapers/` has no declaration or a declaration has no
module.

Acceptance:
- [ ] The three lists are derived, not hand-written.
- [ ] Consistency test.

### SR6-2 Adapter `Protocol` and mypy enforcement

Status: Not started

Steps: a `typing.Protocol` for adapters; the declaration from SR6-1 is typed
against it so mypy catches a missing or mistyped `scrape()`.

Acceptance:
- [ ] mypy fails on a deliberately broken adapter in a test fixture module (or a
      `reveal_type`/`assert_type` check).

### SR6-3 Decide EVLBet's future — Gate: operator

Status: Not started

Why: EVLBet is disabled, returns an empty feed and has no fixture
(`research/02_adapters.md`, `research/03_fixtures_and_pain_points.md`).

Options: capture a fixture and keep it, or remove the adapter and its config.

Acceptance:
- [ ] Decision recorded and carried out.

---

### SR7 — Market coverage

### SR7-1 Full per-match market offers (Mozzartbet, Betole) — Gate: operator

Status: Not started

Why: both books are flagged `degraded — missing markets`, and the operator
asked (2026-11-08) whether they should carry more markets. The 2026-11-08 live
probe in `docs/evidence/2026-11-08-market-coverage-probe.md` measured it: their
list endpoints (Betole's `/restapi/offer/ba/sport/S/desk`, Mozzartbet's
`POST /betting/matches`) carry only four complete supported families each
(1X2, double chance, BTTS, over/under 2.5; Betole adds the experimental
first-half 1X2). The extra codes Betole serves are combination/special/advance
markets decoded from its own `ttg_lang` catalog, not families this project
prices; Mozzartbet's feed carries no other supported family. Both report
`totalOddsCount`/`oddsCount` in the hundreds against the ~14/30 they list: the
full offer exists only on the per-match page.

Consequence: more markets means one request per event — 652 + 820 events in the
2026-11-07 scan — taking a scan from 124 requests to roughly 1,470 (+12.9x) and
adding ~130 s per book at the current 5 requests/second ceiling, which exceeds
the 240 s per-adapter deadline. That is why this is gated.

Options to put to the operator:
- A. Targeted fetch: request the full offer only for events that sit in a
  verified cross-book group and lack a family at least two peers publish, capped
  per scan (a new setting), with the cap and result reported in health. Bounded
  traffic; still adds markets where they can change pricing.
- B. Full fetch: every event of both books, which needs the adapter deadline,
  the scan deadline and the schedule re-tuned together.
- C. No change: keep the list-level offer; the degraded badges stay and document
  the coverage gap rather than a fault.

Recommended: A, after capturing one full-offer response per book as a fixture.
Whatever is chosen, `SR4-3`'s wire-schema pattern and a captured fixture are
required before a market is added, and the affected registry rows must state the
settlement.

**Decision (2026-11-08, operator): B — full fetch.** Every event of both books
gets its full offer, accepting ~1,470 requests per scan (+12.9x over the 124 of
2026-11-07) and the per-book wall time that follows. Budget: the per-adapter
deadline stays 240 s; at the 5 requests/second ceiling a full Betole walk
(~820 events) is ~165 s and a full Mozzartbet walk (~652) is ~130 s on top of
the list pass, so both must fit under it or the scan must report `timeout`
rather than overrun. Where the full-offer endpoint or its mapping turns out to
carry none of the families this project prices, that book keeps its list offer
and the reason is recorded here.

Status: Done

**Outcome (2026-11-08).** Betole's full offer is a **batched** request:
`GET /restapi/offer/ba/matches/by-ids?matchIdsToken=…&annex=0` returns the whole
offer for 40 events at once (763 picks per event against 30 on the desk), so 809
prematch matches cost 21 requests on top of the desk listing. Mozzartbet has no
bulk variant (the list flags `loadAllTemplateGames`/`loadExtendedOffer` change
nothing, measured), so it needs one `POST /betting/match/{id}` per event: 678
requests in the measured scan, 159.9 s, under the 240 s adapter deadline. Both
parsers now emit, from the full offer: the 1.5/2.5/3.5/4.5/5.5 totals (Betole
4.5/5.5 were added to the registry), Betole's double chance, and the
experimental first-half 1X2 for both books. Mozzartbet's unsupported games
(HT/FT, team totals, exact score, per-half goals, …) are declared in
`_excluded` instead of flooding the unmapped diagnostic.

Measured, 2026-11-08 01:05–01:09, same machine and market:

| metric | before (2026-11-07 22:18) | after |
|---|---|---|
| requests / scan | 124 | 777 |
| response bytes | 234.7 MB | 433.0 MB |
| scan wall | 105 s | 237 s |
| mozzartbet adapter | 57 s | 159.9 s |
| betole markets | 3,275 (4.0/event) | 6,628 (8.2/event) |
| mozzartbet markets | 2,598 (4.1/event) | 4,976 (7.9/event) |
| mozzartbet missing rate | 0.558 (degraded) | 0.170 (healthy) |
| betole missing rate | 0.028 | 0.028 (healthy) |

Fixtures re-captured on 2026-11-08 (desk → full offer for Betole, list → match
offer for Mozzartbet), contracts refreshed, `MARKET_MAPPING.md` regenerated, and
a new admissibility baseline (`docs/evidence/2026-11-08-admissibility-baseline.json`)
recorded because Betole gained two measured families. Handicap/Asian handicap
remain out: the full offer carries them (Betole 201-203/421-426, Mozzartbet on
some matches) but the line value is not in the payload, so mapping them needs a
separate capture.

Acceptance (decision):
- [x] Decision recorded here with the traffic budget.
- [x] If A or B: fixture captured for both books, parser mappings added with
      settlement, `MARKET_MAPPING.md` regenerated, and the measured request
      count/scan time before/after in the execution log.
- [ ] If C: this row is closed with the dated probe cited. (not taken)

---

### SR7-2 Raise the Mozzartbet request rate — Gate: operator

Status: Done

**Outcome (2026-11-08).** `SCRAPER_BOOK_RATES` (default `mozzartbet=60`) is a
per-book override of `SCRAPER_REQUESTS_PER_SECOND`; every other book stays at
5/s. Betole's full-offer batches also run 8-in-flight now. Measured on two live
prematch scans the same evening:

| metric | before | after |
|---|---|---|
| scan wall | 237 s | 124 s / 121 s |
| mozzartbet wall | 159.9 s | 43.8 s / 40.8 s |
| betole wall | 31.3 s | 13.3 s |
| requests | 777 | 777 / 779 |

The limiter is no longer the binding constraint: 675 Mozzartbet requests in
40.8 s is ~16.5 requests/second, well under the 60/s ceiling, because
`page.request` shares the browser's per-host connection pool. The remaining
~80 s of the scan is local matching/pricing, which is M2-1 (operator-gated);
pushing Mozzartbet further would mean leaving the browser transport, which the
Cloudflare session (and the no-TLS-impersonation rule) makes a separate
decision.

Why: after SR7-1 a scan spent 159.9 s on Mozzartbet's 678 requests because the
5 requests/second per-book ceiling is a hard floor (678/5 ≈ 136 s). The operator
asked (2026-11-08) to increase it to 60 requests/second. Same requests, shorter
burst; the only change is how fast the book is hit.

Steps: a per-book rate override on `TransportPolicy` (`SCRAPER_BOOK_RATES`,
default `mozzartbet=60`), leaving every other book at
`SCRAPER_REQUESTS_PER_SECOND` (5/s). Measure one prematch scan; if the book
starts answering 429/403 the breaker will open it and the rate is too high.

Acceptance:
- [x] Per-book override applies (test) and other books keep 5/s.
- [x] One live scan measured before/after, with the per-book kind and wall time
      pasted into the execution log.

---

### M1 — Security and authentication (from the old maintenance backlog)

### M1-1 Redesign named-key authentication

Status: Not started

Gate: operator

Why / what: Redesign named-key authentication as one coherent change: a middleware
resolves the env `API_KEY` or a named key for every `/api` route except
`/api/health`, routes carry explicit read/write scopes, and the dashboard sends
the key on every fetch and download. Then remove the strict xfail in
`tests/test_auth_keys.py`.

The strict xfail at `tests/test_auth_keys.py:131` must stay until this is fixed;
do not delete it without fixing the gap, and do not turn it into a skip.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.
- [ ] The strict xfail is removed by fixing the gap, not deleted or skipped.

### M1-2 Decide `accepted_odds: 0` with a stake

Status: Not started

Gate: operator

Why / what: Decide whether `accepted_odds: 0` with a non-zero accepted stake
should be rejected (422) instead of treated as "not placed". The current settle
path treats either zero as not placed, so bankroll stays correct.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M1-3 Auth-failure rate limit and PBKDF2 cache

Status: Not started

Gate: operator

Why / what: Add an authentication-failure rate limit and avoid one PBKDF2
verification per request; invalidate any verification cache immediately on
revocation.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

---

### M2 — Performance and availability (from the old maintenance backlog)

### M2-1 Move scan CPU/I/O off the event loop

Status: Not started

Gate: operator

Why / what: Move the scan's CPU/I/O stages off the event loop
(`asyncio.to_thread`): learning, `group_matches`, stale/skin/feed-integrity,
candidate CPU work and JSON/SQLite writes. A real scan blocked `/api/status` for
about 100 s.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M2-2 Stop rewriting the cache on verify-links

Status: Not started

Gate: operator

Why / what: Stop rewriting the ~55 MB scan cache on every `/api/verify-links`
call; persist failed-check results without a full cache write.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M2-3 Serve a cached `/api/health` summary

Status: Not started

Gate: operator

Why / what: Serve a cached `/api/health` summary instead of recomputing freshness
and the candidate queue on every poll.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M2-4 Decide the candidate queue cap

Status: Not started

Gate: operator

Why / what: Decide whether to cap the candidate review queue (14k+ rows) and how
to report the denominator. Do not trim silently.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M2-5 Review compact cache/ledger representations

Status: Not started

Gate: operator

Why / what: Evaluate the compact cache/ledger representations against every
consumer; never delete runtime evidence to meet a budget.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

---

### M3 — Architecture (from the old maintenance backlog)

### M3-1 Decompose `server/api.py`

Status: Not started

Gate: operator

Why / what: Decompose `server/api.py` in stages: pure candidate scoring, a
`FeedState` object for `_state_for`, then the JSON-store layer. Leave scan and
deep-link semantics untouched.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M3-2 Move the deep-link store to `engine/`

Status: Not started

Gate: operator

Why / what: Move the deep-link declaration store out of `scrapers/common.py` into
`engine/`, and remove the `engine` ↔ `scrapers` package cycle.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M3-3 One link-settled predicate

Status: Not started

Gate: operator

Why / what: Share one link-settled predicate between `CertaintyGate` and cache
restore, with a parity test over every link case.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M3-4 Unify datetime and SQLite helpers

Status: Not started

Gate: operator

Why / what: Unify the repeated datetime and SQLite connection helpers; decide one
`synchronous` policy for the shared database file.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M3-5 Route registry lookups through `registered_spec()`

Status: Not started

Gate: operator

Why / what: Route the remaining direct `MARKET_REGISTRY` lookups through
`registered_spec()` (or an accessor) and make the registry test seam patch the
object, not only the module global.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M3-6 Move `pairing_audit` and verifier into `server/`

Status: Not started

Gate: operator

Why / what: Move `scripts/pairing_audit.audit` and the reusable deep-link verifier
into `server/` so coverage measures them.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

---

### M4 — Supply chain and CI (from the old maintenance backlog)

### M4-1 Add a resolved constraints/lock file

Status: Not started

Gate: operator

Why / what: Add a resolved constraints/lock file and install Docker/CI/SBOM from
it.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M4-2 Docker Chromium check and image CVE scan

Status: Not started

Gate: operator

Why / what: Add a Docker Chromium launch check and an OS/image CVE scan.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M4-3 Pin Actions by SHA and base image by digest

Status: Not started

Gate: operator

Why / what: Pin GitHub Actions to commit SHAs and the base image to a digest;
keep Dependabot able to update both.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M4-4 Plan the remaining dependency upgrades

Status: Not started

Gate: operator

Why / what: Plan the separate upgrades for FastAPI/Starlette, MyPy 2.x and
Ruff 0.17; evaluate the `httpx2` TestClient migration. (The Playwright 1.64
upgrade from the same old TODO item is tracked by SR3-1.)

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

---

### M5 — Product and configuration decisions (from the old maintenance backlog)

### M5-1 Remove legacy URL maps

Status: Not started

Gate: operator

Why / what: Remove or deprecate `Surebet.match_urls`, `Surebet.bet_urls`,
`Match.bet_url` and `MATCH_URL_TEMPLATES` after a documented compatibility
window. `SurebetStake.destination` is the supported path.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M5-2 Decide the `link_sweeps` table

Status: Not started

Gate: operator

Why / what: Decide the `link_sweeps` SQLite table: wire `append_link_sweep()`
into `POST /api/link-sweeps`, or remove the table/method/retention entry and
correct `docs/STORAGE.md`.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M5-3 Decide approve/reject functions

Status: Not started

Gate: operator

Why / what: Decide the unreachable candidate approve/reject functions: restore
them behind `HUMAN_MAPPING_ENABLED` with a review, or delete them and the stale
documentation.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M5-4 Decide `raw_market_resolver.resolve_offers`

Status: Not started

Gate: operator

Why / what: Decide `engine/raw_market_resolver.resolve_offers`: wire it into
`scripts/discover_markets.py` or retire it.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M5-5 Finish the PWA

Status: Not started

Gate: operator

Why / what: Finish the PWA: add 192/512 icons; decide whether the
browser-notification button sends a notification or is removed.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M5-6 Zero-matches diagnostic and no-surebet state

Status: Not started

Gate: operator

Why / what: Add the "scan completed with zero matches" diagnostic and a
run-mode-aware no-surebet state; extend the truth table and companions
deliberately.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

### M5-7 Fix the feed-mode tab ARIA contract

Status: Not started

Gate: operator

Why / what: Fix the feed-mode tab ARIA contract (`aria-controls`/roving tabindex
or a `group` with `aria-pressed`) and reconsider the whole-slip live region.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

---

### M6 — Tests and process (from the old maintenance backlog)

### M6-1 Branch coverage floor in CI

Status: Not started

Gate: operator

Why / what: Enable branch coverage with a measured floor and add it to CI.

Acceptance:
- [ ] Operator approval recorded here.
- [ ] Acceptance criteria written here before coding.

---

### M7 — Operator requests

### M7-1 Dashboard UI polish pass

Status: Done

Why / what: Operator asked (2026-11-07) to look at the dashboard and improve
it. A browser pass with seeded demo surebets (no scraper traffic) found:
team and league names with non-ASCII letters were mis-capitalised
(`FK ŽEljezničAr`, `AtléTico`) because `\b\w` is ASCII-only; the re-check
banner printed its `<span data-ago>` markup as text; the row re-check badge
showed a bare `?`; before the first scan a red "odds are not current" alarm
with a third Scan button sat above an empty list; some book tags were
low-contrast; the slip totals cramped on phones. Presentation only: no trust
rule, freshness state or gate changes.

Acceptance:
- [x] Names with diacritics keep their case (`Željezničar`, `Atlético`).
- [x] The re-check banner renders its live age, not escaped markup.
- [x] The row badge for an unconfirmed re-check reads as a word in EN and BS.
- [x] Before any scan and with nothing listed, the freshness banner is a calm
      notice without the "not current" sentence or a duplicate Scan button;
      with rows on screen it is unchanged.
- [x] Tests cover the first three; full verification suite passes.

---

## Deferred and waived

Neither task below may be started without an explicit operator instruction.

### N2-4 — Seven-day local opportunity baseline and drift gates

**Status:** Deferred — operator deferred this task on 2026-11-05 ("skip N2-4
for now"); it is not blocked, just intentionally out of order. Do not start it
until the operator un-defers it.
**Priority:** P2
**Effort:** M
**Depends on:** none

**Objective:** replace the public-reference placeholder with a local baseline and
make a material regression visible.

**Steps:**

1. Run the scanner for at least seven days (or import an existing recorded
   history) and generate `scripts/opportunity_baseline.py --days 7`.
2. Publish crossing rate, floor-crossing rate, actionable rate, median/best
   margin and p50/p90 lifetime with denominators.
3. Define per-mode drift bands and a `--check` failure for a material drop.
4. Add the baseline date, sample count and limitations to
   `docs/evidence/`.
5. Wire the report into CI as an optional data check, never a live-feed CI job.

**Acceptance criteria:**

- [ ] The baseline has at least seven days and both modes where available.
- [ ] Every rate prints its numerator/denominator.
- [ ] A synthetic drop fails `--check`; a stable replay passes.
- [ ] The report states what the baseline cannot prove.

**Tests:**

- New: `tests/test_opportunity_baseline.py` (extend if present).
- Existing: `tests/test_opportunity_metrics.py`, `tests/test_scan_quality.py`,
  `tests/test_replay.py`.

**Notes / risks:** Do not tune filters until the baseline exists; a low number is
a finding, not a threshold to lower.

### P1-6 — 24-hour soak and resource budget

**Status:** Waived and excluded from roadmap completion — the operator skipped
the 24-hour run on 2026-11-04. The harness, budget guard and two-cycle smoke
evidence remain in `docs/SOAK.md`. The roadmap is finished without this task by
operator decision; the unchecked acceptance boxes below are retained so the
waiver is not mistaken for a passed 24-hour run.
**Priority:** P1
**Effort:** M
**Depends on:** P0-1, P1-2

**Objective:** prove the service survives a day of scheduled scans without unbounded memory, leaked browsers, or stale-book blindness.

**Expected outcome:** a 24 h `scripts/soak.py --minutes 1440 --check` run with a plateau, zero surviving browsers, and a written report in `docs/`.

**Steps:**

1. Run the soak with scheduled prematch scans and, if enabled, live scans.
2. Record the RSS series, browser count, per-book errors, group/surebet counts, and cache size.
3. Add a soft alert when RSS exceeds a configured budget or the cache exceeds a size budget.
4. Fix any leak found; do not mask it by restarting the process.
5. Publish the report and link it from `docs/ACCEPTANCE.md`.

**Acceptance criteria:**

- [ ] 24 h run completes with no browser process surviving a scan.
- [ ] Memory plateaus below the documented budget.
- [ ] No book is silently absent for the whole run without an alert/error entry.
- [ ] The report is reproducible from the command and environment recorded in it.

**Tests:** `scripts/soak.py` unit tests plus the manual run.

**Notes / risks:** A short run is a smoke test, not acceptance. The project already has a 6- and 10-cycle plateau; the gap is duration. See `docs/SOAK.md`.

---

## Rejected (do not reopen without the operator)

| Option | Reason | Brief |
|--------|--------|-------|
| Adopt Scrapy, Crawlee or Crawl4AI | The project has its own adapters and trust gates; borrow patterns only (autothrottle, session/pool hooks, stats, context recycling) | `research/04_http_reliability_research.md`, `research/05_browser_automation_research.md` |
| `curl_cffi`, playwright-stealth, camoufox, nodriver, undetected-chromedriver, captcha solvers, proxy rotation | Evasion; trust invariant 9 | `research/04_http_reliability_research.md`, `research/05_browser_automation_research.md` |
| `hishel` HTTP caching for prices | Prices must be fresh; caching hides staleness | `research/04_http_reliability_research.md` |
| `backoff` | Archived | `research/04_http_reliability_research.md` |
| `aiobreaker` / `pybreaker` | Abandoned / sync-only; in-house breaker is ~50 lines | `research/04_http_reliability_research.md` |
| prometheus-client, structlog, OpenTelemetry | In-house registry and JSON logs already cover the need | `research/04_http_reliability_research.md` |
| Pact, Schemathesis | Need a cooperating provider or a published spec | `research/06_parser_contract_testing_research.md` |
| pandera, Great Expectations | Dataframe/batch tools; wrong shape | `research/06_parser_contract_testing_research.md` |
| Browserless | SSPL licence, remote browser not needed | `research/05_browser_automation_research.md` |
| Selenium, pydoll | No gain over Playwright | `research/05_browser_automation_research.md` |

---

## History

### Already fixed — do not reopen

These were open in `docs/HANDOFF.md` and are now implemented; keep them out of the TODO:

- `MatchGroup.evidence` is persisted and served (but see F1/F6 for payload cost).
- `group_matches` is order-insensitive and has a fall-through path.
- `build_targets` has `settled` + `offset` and converges.
- Prematch expiry uses the latest kickoff plus a two-minute buffer.
- `premier_kladionica` live BTTS and the NSoft live window have regression tests.
- `orientation_unresolved` is emitted, tested, and documented in the README.
- The approve/reject HTTP routes are gone; Diagnostics is read-only.

### ID glossary

`P*` and `N*` are historical labels. They are defined here only so the docs and
test docstrings that cite them stay resolvable. Per-task execution logs and
"Files changed" lists are in git history at BASE
(`git show 2e06756ecd56b013df6e99b58258e8d2cfaa0e25:PROJECT_ROADMAP_V2.md`).

| ID | Title | Final status |
|----|-------|--------------|
| P0-1 | Bound the cached evidence payload | Done |
| P0-2 | Dashboard XSS + inline-handler + CSP hardening | Done |
| P0-3 | Gate-vocabulary truth audit and probe strengthening | Done |
| P0-4 | Runtime freshness and stale-state policy | Done |
| P0-5 | Reloadable deep-link declarations | Done |
| P0-6 | Opportunity-rate and arb-lifetime telemetry | Done |
| P0-7 | Feed-integrity scorecard and stale-book quarantine | Done |
| P1-1 | Paginated, filtered group-evidence API | Done |
| P1-2 | Structured logs, request IDs, metrics endpoint | Done |
| P1-3 | Reproducible deployment (Docker/systemd) | Done |
| P1-4 | CI hardening: coverage, dependency and security scans | Done |
| P1-5 | Alerting with dedupe and retry | Done |
| P1-6 | 24-hour soak and resource budget | Waived (excluded) |
| P1-7 | Raw-price invariant and rounding audit | Done |
| P2-1 | Convergent deep-link sweep automation and UI | Done |
| P2-2 | Dated re-verification of no-event declarations | Done |
| P2-3 | Publish `source_id` from every parser; complete registry coverage | Done |
| P2-4 | Multi-day replay corpus and precision/recall evaluation | Done |
| P2-5 | Sports expansion with measured admissibility | Done |
| P2-6 | Candidate-queue quality and coverage metrics | Done |
| P2-7 | Identical-feed ("skin") detection | Done |
| P2-8 | Event-identity edge cases: doubleheaders and rematches | Done |
| P2-9 | Silent-drop coverage budget | Done |
| P2-10 | Measured push-feed discovery and per-book WebSocket adapter | Done |
| P3-1 | Persistent storage v2 (SQLite) and migration | Done |
| P3-2 | Bet log, bankroll, and CLV analytics | Done |
| P3-3 | Advisory execution workflow and limits | Done |
| P3-4 | Alerts, PWA, accessibility, and Bosnian UI | Done |
| P3-5 | Authentication and key management hardening | Done |
| P3-6 | Book risk profiles and advisory pacing | Done |
| P3-7 | Record-only / paper-trading mode | Done |
| N0-1 | Hermetic tests independent of runtime state | Done |
| N0-2 | Source-updated timestamps and frozen-price quarantine | Done |
| N0-3 | CSP without inline styles | Done |
| N0-4 | Automatic closing-line capture for logged bets | Done |
| N1-1 | Retention and maintenance automation | Done |
| N1-2 | Coverage/mapping alerts and SLOs | Done |
| N1-3 | Per-book scan cost accounting | Done |
| N1-4 | Release hardening: Docker smoke, SBOM, dependency updates | Done |
| N2-1 | Paper ledger dashboard, CSV and retention view | Done |
| N2-2 | Realistic paper fills: rejection, partial acceptance, caps | Done |
| N2-3 | Candidate remediation and strict-miss trends | Done |
| N2-4 | Seven-day local opportunity baseline and drift gates | Deferred |
| N2-5 | Complete Bosnian localization and automated a11y checks | Done |
| N2-6 | Parser fixture refresh and drift detection | Done |
| N3-1 | Property-based pricing/identity tests and load budgets | Done |
| N3-2 | Scheduled market/sport admissibility re-audit | Done |

### Quick reference

```bash
python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check
```

Useful starting points:

| Concern | File |
|---|---|
| Test isolation | `tests/conftest.py`, `tests/test_e2e_certified.py` |
| Freshness / feed integrity | `engine/feed_integrity.py`, `server/api.py` |
| CSP and headers | `server/app.py` |
| Bet log / CLV | `server/bets.py`, `docs/BET_LOG.md` |
| Paper mode | `server/paper.py`, `docs/PAPER_MODE.md` |
| Retention / backup | `server/storage.py`, `docs/STORAGE.md` |
| Coverage / alerts | `engine/coverage_budget.py`, `server/alerts.py` |
| Metrics | `server/observability.py`, `server/api.py` |
| Parsers / fixtures | `scrapers/`, `tests/fixtures/markets/`, `scripts/capture_market_fixtures.py` |
| Scraper research briefs | `research/` (index in `research/00_README.md`) |

## Execution log

| Date | Task | Result | Notes |
|------|------|--------|-------|
| 2026-11-07 | — | Roadmap created | Created from `SCRAPER_TODO.md` + `TODO.md`; `PROJECT_ROADMAP.md`, `PROJECT_ROADMAP_V2.md` and `TODO.md` deleted. Old files in git history at BASE `2e06756ecd56b013df6e99b58258e8d2cfaa0e25`. |
| 2026-11-07 | M7-1 | Done | Browser pass on a seeded demo (scrapers cleared, no bookmaker traffic). Fixed Unicode name capitalisation (`capitalizeWords`), escaped `<span data-ago>` in the re-check banner (`trWithMarkup`), `?` row badge → `unconfirmed`/`nepotvrđeno`, quiet pre-scan freshness banner (only `never_scanned` with zero rows), book-tag contrast, 2-column slip totals on phones; asset version v=7→v=8, SW cache v4. New `tests/test_frontend_polish.py`. `pytest`: 1738 passed, 6 skipped, 1 xfailed (clean and `BH_ARB_TEST_RUNTIME_LEDGER=populated`); ruff clean; mypy 219 files clean; market doc in sync; isolation check OK; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-07 | SR1-1 | Done | The `today` seam already existed end-to-end (`stale_contracts`, `refresh_fixtures.build_report`, `contract_health`); `tests/test_parser_contracts.py` now passes `today=REFERENCE_DATE` (2026-11-07) so the fixture/contract equality check no longer reads the wall clock. New regression tests freeze `parser_contracts.date` at 2027-03-01: the equality check stays green, while the real-clock path reports a 132-day-old contract as stale. `pytest`: 1740 passed, 6 skipped, 1 xfailed (clean and `BH_ARB_TEST_RUNTIME_LEDGER=populated`); `pytest tests/test_parser_contracts.py -k "shipped or wall_clock or expired"`: 4 passed; ruff clean; mypy 219 files clean; market doc in sync; isolation check OK (both ledgers); `refresh_fixtures.py --check` exit 0 (17 contracts, no diff/stale/missing); `audit_admissibility.py --check` status ok. |
| 2026-11-07 | SR1-2 | Done | CI already runs the suite in the two modes `check_test_isolation.py` orchestrates, so no redundant third/fourth run was added; `AGENTS.md` and `docs/CI.md` now say that explicitly. The runtime-state guard moved to `scripts/check_test_isolation.py:runtime_state_snapshot()` and ignores SQLite `-shm`/`-wal` sidecars (connection-scoped; a concurrent scanner can create or remove them) while still comparing the database file and every other runtime file. New `tests/test_runtime_isolation.py::test_sqlite_sidecars_do_not_count_as_runtime_state_writes`. `pytest`: 1741 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1741 passed, 6 skipped, 1 xfailed; ruff clean; mypy 219 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-07 | SR1-3 | Done | `scrapers/base.py` now returns a local `SettleOutcome` (`SETTLED`/`TIMEOUT`/`FAILED`) from `settle()` and logs a warning for the two failure kinds; callers may proceed only knowing the page is unproven, and SR2-1 will absorb the enum into the shared scrape taxonomy. New `tests/test_scraper_base.py` covers a settled page, a Playwright timeout and any other navigation error. `pytest`: 1744 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1744 passed, 6 skipped, 1 xfailed; ruff clean; mypy 220 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-07 | SR2-1 | Done | New `scrapers/errors.py` owns `ScrapeKind` (`ok`, `empty`, `blocked`, `rate_limited`, `timeout`, `transport`, `upstream_5xx`, `parse_error`, `schema_drift`, plus `skipped` for a book not attempted) and structural `classify_response`/`classify_exception`/`classify_scrape`; the old text-marker classifier is gone. `run_scan` records the kind on every book (`finish_book(kind=...)`), health exposes `scan_cost.<mode>.books.<book>.kind` and `totals.kinds`, and `bh_book_kinds_total` carries the kind per book while `bh_book_results_total` keeps its historical outcome label. SR1-3's local `SettleOutcome` was absorbed: `settle()` now returns `ScrapeKind`. New `tests/test_scrape_errors.py` tables statuses and exception types, including old marker strings that must no longer classify as blocked. `pytest`: 1793 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1793 passed, 6 skipped, 1 xfailed; ruff clean; mypy 222 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-07 | SR2-2 | Done | New `scrapers/transport.py` owns frozen `TransportPolicy` per (book, mode) with `httpx.Timeout` + explicit `httpx.Limits(10, keepalive=5)`, `retry_budget=3`, `requests_per_second=None` (reserved for SR2-4) and `verify` from `VERIFY_SSL`. `TransportPool` holds one `AsyncClient` per (book, mode) per scan; `run_scan` opens it around the scraper gather and closes every client afterwards. All seven httpx adapters use `transport_client()`; standalone calls still get a private closed client. Timeout diff (unchanged): betole 30→30, evlbet 20→20, maxbet 60→60, mbet 30→30, mdshop 30→30, premier_kladionica 60→60, sportplus 120 prematch/60 live→120/60; connect/read/write/pool all keep the old value. New `tests/test_transport.py` pins the policies, shared client, close lifecycle and standalone fallback; `tests/test_metrics.py` proves a scan shares and closes the client. `pytest`: 1813 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1813 passed, 6 skipped, 1 xfailed; ruff clean; mypy 224 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-07 | SR2-3 | Done | Kept the policy hand-rolled rather than adding `stamina`: the project already owns per-attempt cost accounting, the per-book policy and the kind taxonomy, so a dependency would have to be threaded through all three. New `scrapers/retry.py` implements full-jitter backoff, the SR2-2 attempt cap and total-time budget, `Retry-After` (numeric or HTTP-date, capped at 60 s), 403/challenge as one attempt and `blocked`, and per-attempt `record_request`. `fetch_with_retry` moved there and gained read-only POST support; wwin's private retry loop is gone, and its Playwright calls, mozzartbet's pagination POST and admiralbet's events GET now use `retry_call`; premier's JSON-RPC POST retries through `fetch_with_retry`. The success path is still one request per call. New `tests/test_retry.py` (httpx `MockTransport`) covers 429 + `Retry-After`, 403 and challenge one-attempt blocking, the attempt cap, total-budget stop, the retry-after cap, transport retries, attempt counts and the one-request success path. `pytest`: 1825 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1825 passed, 6 skipped, 1 xfailed; ruff clean; mypy 226 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-07 | SR2-4 | Done | Kept it hand-rolled (`scrapers/ratelimit.BookRateLimiter`) rather than adding `aiolimiter` (recorded under the task): the acceptance test needs a clock/sleep seam, and a reservation model (one slot per attempt, no burst) satisfies "N attempts take at least N/R s" where a leaky bucket's initial burst of R does not. One limiter per (book, event loop), so a scan shares it per book and politeness does not reset at a scan boundary. `retry_call` acquires one slot per attempt, the first included, so retries are spaced too; `TransportPolicy` gained `bookmaker` and `requests_per_second` (`SCRAPER_REQUESTS_PER_SECOND`, default 5/s, 0 disables), and the three browser books got explicit policies with their previous httpx defaults (30/30/30) so only the rate applies to their `page.request` calls. No dependency was added; `aiolimiter` was installed only to inspect it and removed again. New `tests/test_ratelimit.py` (fake clock: 5 attempts at 4/s span 1.25 s; 6 concurrent at 10/s span >= 0.6 s; per-book/per-loop registry; disabled rates; one slot per attempt including retries; 403 takes one slot), `tests/test_transport.py` updated. **Measured no slow-down:** `cache/scan_cost.json` prematch 2026-11-06 (187 requests, wall 256.197 s) gives floor = requests/5 s per book, e.g. mozzartbet 101 req → 20.2 s floor vs 57.12 s recorded wall, wwin 46 → 9.2 vs 34.20, mbet 16 → 3.2 vs 33.15, premier 10 → 2.0 vs 17.23, admiralbet 5 → 1.0 vs 72.64, mdshop/maxbet 3 → 0.6 vs 9.46/10.85, betole 2 → 0.4 vs 2.56, sportplus 1 → 0.2 vs 18.99; delta 0.00 s for every book in that scan and in the 2026-11-05 live scan. Limiter benchmark: 10 attempts take 0.000 s unlimited, 2.006 s at 5/s, 0.504 s at 20/s. No live scan was run (no bookmaker traffic in this session); the before/after is the recorded ledger against the modelled floor. `pytest`: 1834 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1834 passed, 6 skipped, 1 xfailed; ruff clean; mypy 228 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed; `pytest --cov`: 86.19% (11,935 statements, floor 80%). |
| 2026-11-07 | SR2-5 | Done | Per-adapter deadline from `TransportPolicy.adapter_deadline` (`SCRAPER_BOOK_TIMEOUT_SECONDS`, default 240 s) via `asyncio.timeout` around the scrape call, and one scraping-phase deadline (`SCRAPER_SCAN_TIMEOUT_SECONDS`, default 600 s) around the gather. The scan deadline deliberately wraps the scrape phase, not all of `run_scan` (recorded under the task): aborting the pricing pass would discard the books that already returned. Each book stores its matches in `book_matches` as it finishes and the list is rebuilt from that after the gather, so a cancelled gather keeps completed books; stragglers are cancelled and awaited (browser closed, semaphore released) before the transport pool closes its clients. Books are now `asyncio.create_task` inside `transport_pool()`: creating them before the pool lost the shared-client context (caught by `test_a_scan_shares_one_transport_client_and_closes_it`). A scan-deadline cancellation is `timeout` in cost/health but is not charged to the scheduled-scan backoff. New `tests/test_scan_deadlines.py`: a hung book is cut at the adapter deadline while the other book prices and is served; a hung book is cancelled at the scan deadline while the finished book is still served and the scan is not marked failed; a fake browser book's `finally` close runs and the `BROWSER_CONCURRENCY` slot is returned. Defaults are 2.4× the slowest recorded book (admiralbet 72.6 s prematch, betole 100.7 s live). `pytest`: 1837 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1837 passed, 6 skipped, 1 xfailed; ruff clean; mypy 229 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed; `pytest --cov`: 86.23% (11,974 statements, floor 80%). |
| 2026-11-07 | SR2-6 | Done | New `scrapers/breaker.py`: one `BookCircuitBreaker` per `(mode, book)` in a process-wide registry, states `closed`/`open`/`half_open` with exactly one probe, injected clock. `blocked` and `rate_limited` open on the first occurrence with twice a soft failure's cooldown; `empty`/`timeout`/`transport`/`upstream_5xx` open after `BOOK_BACKOFF_AFTER_FAILURES` consecutive ones; `parse_error`/`schema_drift`/`skipped` are neutral and cannot open or reset it (a neutral probe releases the slot); any `ok` closes it and resets the escalation. Base cooldown is the mode's scan interval (5 min when that feed's schedule is off, so the live breaker cannot get a zero cooldown), doubled per consecutive open and capped by `BOOK_BACKOFF_MAX_MINUTES`. The old dict/lock/`_book_is_backed_off` are removed; `_record_book_result` now takes the `ScrapeKind`, manual scans still ignore an open breaker, scheduled scans skip the book with note `circuit breaker open`. Health serves `scheduler.breakers.<mode>/<book>` with state, consecutive failures, opens, cooldown remaining and last kind; metrics publish `bh_book_breaker_state{mode,book,state}` (1/0 per state), `bh_book_breaker_failures` and `bh_book_breaker_cooldown_seconds`. Alerts still fire at the same threshold, fed by consecutive failures. New `tests/test_breaker.py` (every transition with a fake clock: soft threshold, hard opening immediately with a longer cooldown, neutral kinds, one probe, dead probe doubles, success resets, cap, snapshot shape, registry, health, metrics); `tests/test_scheduler.py` rewritten against the breaker; `tests/test_scan_deadlines.py` proves a scheduled scan skips an open book while a manual scan still runs it; alert tests stub `_breaker_snapshots`. `pytest`: 1853 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1853 passed, 6 skipped, 1 xfailed; ruff clean; mypy 231 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed; `pytest --cov`: 86.40% (12,072 statements, floor 80%). |
| 2026-11-08 | SR7-1 | Done | Operator chose **B (full fetch)**. Betole now calls the batched full-offer endpoint (`GET /restapi/offer/ba/matches/by-ids?matchIdsToken=<40 ids>&annex=0`) after the desk listing; the annex code comes from the site's `parametersData.json` (`BOOK_ANNEX_CODE=0`). Desk events are filtered (mode/live, blocked, teams) before batching, so 809 matches cost 22 requests. Parser gains double chance (7/8/9) and totals 1.5/2.5/3.5/4.5/5.5 (242/21, 24/22, 25/219, 27/453, 223/266); the registry gains `over_under_4_5`/`over_under_5_5` for betole; the 22 combination/special picks stay in `_excluded`. Mozzartbet has no bulk variant (tested `loadAllTemplateGames`/`loadExtendedOffer`/`packGroupsInMatch`: the list payload is unchanged), so it fetches `POST /betting/match/{id}` per unique event with 8 in flight, the shared 5/s limiter, and the list odds as the fallback per event; the GET form returns `{"error":"Not found. Sorry."}` (caught in the first live run: 642 wasted GETs, fixed to POST). Parser gains game 4 first-half 1X2 (experimental, like Betole's) and the 1.5/3.5/4.5 complete totals; unsupported game ids (5,7,8,9,16,19,20,26,128,129,131,132,139,140,142,143,153,154,179,297) are declared in `_excluded`. Fixtures re-captured from the live endpoints and contracts rewritten (`refresh_fixtures --write`): betole full-offer odds map, mozzartbet match-offer rows; `UNCOVERED_ROWS` entries for the now-covered rows removed. New admissibility baseline `docs/evidence/2026-11-08-admissibility-baseline.json` (betole's two new families were `new_family_without_evidence` warnings on the 2026-11-05 baseline; `DEFAULT_BASELINE` and the docs now point at the 2026-11-08 file). **Measured before → after (same machine, 2026-11-07 22:18 → 2026-11-08 01:05):** requests/scan 124 → 777 (+5.9x), bytes 234.7 MB → 433.0 MB, scan wall 105 s → 237 s, mozzartbet adapter 57 s → 159.9 s (under the 240 s deadline), betole 22 requests / 31.3 s, mozzart 678 requests / 159.9 s; markets betole 3,275 → 6,628 (4.0 → 8.2 per event), mozzartbet 2,598 → 4,976 (4.1 → 7.9); feed integrity mozzartbet 0.558 missing (degraded) → 0.170 (healthy), betole 0.028 (healthy); 26 surebets on the final scan. Handicap/Asian handicap stay unmapped: the offer carries the picks but not the line value (recorded under the task). New `tests/test_full_offer_markets.py` (9 tests: family sets, incomplete legs, batching, failed batch fallback, desk prefilter, first-half 1X2, offer-failure fallback). `pytest`: 1861 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes green; `pytest --cov`: 86.23% (12,149 statements, floor 80%); ruff clean; mypy 232 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR7-2 | Done | Operator asked to raise the rate to 60 requests/second. Added `SCRAPER_BOOK_RATES` (parsed `"book=rate,..."` pairs, default `mozzartbet=60`) as a per-book override of `SCRAPER_REQUESTS_PER_SECOND`; `TransportPolicy.requests_per_second` takes the override, every other book stays at 5/s. Betole's full-offer batches now run 8-in-flight; Mozzartbet keeps 32 in flight. **Measured on two live prematch scans:** scan wall 237 s → 124 s and 121 s; mozzartbet 159.9 s → 43.8 s / 40.8 s; betole 31.3 s → 13.3 s; requests unchanged at 777/779; kinds stayed `ok`, no 429/blocked (one Betole batch 503'd and the retry succeeded). The limiter is no longer binding: 675 Mozzartbet requests in 40.8 s ≈ 16.5 req/s, because `page.request` shares the browser's per-host connection pool; the remaining ~80 s is local matching/pricing (M2-1, operator-gated). `SCRAPER_BOOK_RATES` documented in README and `.env.example`; `tests/test_ratelimit.py` pins mozzartbet 60/s, mbet 5/s. `pytest`: 1861 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes green; `pytest --cov`: 86.23% (12,166 statements, floor 80%); ruff clean; mypy 232 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR7-1 | Investigation | Operator asked why Mozzartbet and Betole carry so few markets. Live probes (read-only): Betole `GET /restapi/offer/ba/sport/S/desk` returned 1,415 events with 30 distinct pick codes; the 10 mapped codes are 1X2, BTTS, O/U 2.5 and the experimental first-half 1X2, and the other 20 (present on 1,106 events) are exactly `_excluded.betole`. Decoding them through Betole's own catalog (`GET /restapi/offer/ba/ttg_lang`, 1,204 bets / 6,426 picks) shows they are combination/special/advance markets (team wins match-or-first-half, wins both halves, goals per half mixes, qualification, two-goals-in-a-row) — no supported family. Mozzartbet `POST /betting/matches` returned 15 events with 14 odds and 5 groups each: 1X2, DC, BTTS (`gg`/`ng`/`gg3+`), totals with only the 2.5 line complete, and per-half goals; `totalOddsCount` is 518 against the 14 listed, so the full offer is only on the match page. Neither parser drops a supported family; more markets require one request per event (652 + 820 in the 2026-11-07 scan), i.e. ~1,470 requests (+12.9x) and ~130 s per book at the 5/s ceiling, over the 240 s adapter deadline. Recorded as gated **SR7-1** with evidence in `docs/evidence/2026-11-08-market-coverage-probe.md`; no code, book or market was changed. `pytest`/ruff/mypy unchanged from the previous entry (no source changes). |
