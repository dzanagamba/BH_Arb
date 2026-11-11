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
   python scripts/refresh_fixtures.py --check
   python scripts/audit_admissibility.py --check
   ```
   (`.venv/bin/python` if `python` is missing.) While coding, run only the test
   files the change touches; the full suite runs **once**, at task completion.
   Do not run `pytest --cov` or `scripts/check_test_isolation.py` in the routine
   loop: CI's 3.11 leg runs the suite in both ledger modes and enforces the
   coverage floor (SR1-4).
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
  generated ledger. The clean mode runs locally once per task; CI's 3.11 leg
  runs the populated mode and the coverage floor. Run the populated mode locally
  only when the change touches the ledger, `config/generated/` or the isolation
  guard (SR1-4).
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
| SR0-1 | Decide on browser fingerprint masking | Done | — | operator |
| SR0-2 | Decide TLS verification default | Done | — | operator |
| SR1-1 | Remove the date bomb in the contract test | Done | — | — |
| SR1-2 | Run the isolation check in CI | Done | — | — |
| SR1-3 | Stop `settle()` swallowing navigation errors | Done | — | — |
| SR1-4 | Run the test suite once per task | Done | SR1-2 | — |
| SR2-1 | Scrape error taxonomy | Done | — | — |
| SR2-2 | Per-book transport policy and shared client | Done | SR2-1 | — |
| SR2-3 | Retry policy rewrite (jitter, budget, 429, 403) | Done | SR2-1, SR2-2 | — |
| SR2-4 | Outgoing per-book rate limiter | Done | SR2-2 | — |
| SR2-5 | Adapter and scan deadlines | Done | SR2-1 | — |
| SR2-6 | Per-book circuit breaker | Done | SR2-1, SR2-3 | — |
| SR3-1 | Upgrade Playwright | Done | SR0-1 | — |
| SR3-2 | Leak-free resource blocking | Done | SR3-1 | — |
| SR3-3 | Shared browser lifecycle | Done | SR3-2, SR2-5 | — |
| SR3-4 | Response capture and failure forensics | Done | SR3-3 | — |
| SR4-1 | Transport-level tests with respx | Done | SR2-3 | — |
| SR4-2 | Fixture metadata and age policy | Done | — | — |
| SR4-3 | Strict wire schemas, one book first | Done | SR2-1 | — |
| SR4-3b | Strict wire schema: Mozzartbet | Done | SR4-3 | — |
| SR4-3c | Strict wire schema: Admiralbet | Done | SR4-3 | — |
| SR4-3d | Strict wire schema: Betole | Done | SR4-3 | — |
| SR4-3e | Strict wire schema: MBet | Done | SR4-3 | — |
| SR4-3f | Strict wire schema: SportPlus | Done | SR4-3 | — |
| SR4-3g | Strict wire schema: EVLBet | Blocked on a live EVLBet payload | SR4-3 | — |
| SR4-3h | Strict wire schema: Premier Kladionica | Done | SR4-3 | — |
| SR4-3i | Strict wire schema: WWin | Done | SR4-3 | — |
| SR4-3j | Strict wire schema: MaxBet | Done | SR4-3 | — |
| SR4-4 | Structural fingerprint and drift alarm | Done | SR4-3 | — |
| SR4-5 | Cardinality floors against a baseline | Done | SR2-1 | — |
| SR4-6 | Snapshot tests of normalised parser output | Done | SR4-2 | — |
| SR4-7 | Property-based mutation tests for parsers | Done | SR4-6 | — |
| SR4-7a | Drop a duplicated NSoft outcome label | Done | SR4-7 | — |
| SR4-8 | HAR fixtures for browser books | Done | SR3-4, SR4-2, SR4-8a | — |
| SR4-8a | Choose the browser replay transport | Done | SR3-4 | operator |
| SR4-9 | Scheduled live canary | Done | SR4-4, SR4-5 | operator |
| SR4-10 | Mozzartbet offer rows may omit `value` | Done | SR4-3b | — |
| SR4-11 | WWin non-JSON body classified as schema drift | Done | SR4-3i | — |
| SR4-12 | Fingerprint over heterogeneous list pages | Done | SR4-4 | — |
| SR4-13 | Premier delta rows shorter than the strict schema | Done | SR4-3h | — |
| SR5-1 | Per-book reliability metrics | Done | SR2-6 | — |
| SR5-2 | Per-book health state and live cost baseline | Done | SR5-1 | — |
| SR6-1 | Single adapter declaration | Done | SR2-2 | — |
| SR6-2 | Adapter `Protocol` and mypy enforcement | Done | SR6-1 | — |
| SR6-3 | Decide EVLBet's future | Done | — | operator |
| SR7-1 | Full per-match market offers (Mozzartbet, Betole) | Done | — | operator |
| SR7-2 | Raise the Mozzartbet request rate | Done | SR7-1 | operator |
| M1-1 | Redesign named-key authentication | Done | — | operator |
| M1-2 | Decide `accepted_odds: 0` with a stake | Done | — | operator |
| M1-3 | Auth-failure rate limit and PBKDF2 cache | Done | — | operator |
| M2-1 | Move scan CPU/I/O off the event loop | Done | — | operator |
| M2-2 | Stop rewriting the cache on verify-links | Done | — | operator |
| M2-3 | Serve a cached `/api/health` summary | Done | — | operator |
| M2-4 | Decide the candidate queue cap | Done | — | operator |
| M2-5 | Review compact cache/ledger representations | Done | — | operator |
| M3-1 | Decompose `server/api.py` | Done | — | operator |
| M3-2 | Move the deep-link store to `engine/` | Done | — | operator |
| M3-3 | One link-settled predicate | Done | — | operator |
| M3-4 | Unify datetime and SQLite helpers | Done | — | operator |
| M3-5 | Route registry lookups through `registered_spec()` | Done | — | operator |
| M3-6 | Move `pairing_audit` and verifier into `server/` | Done | — | operator |
| M4-1 | Add a resolved constraints/lock file | Done | — | operator |
| M4-2 | Docker Chromium check and image CVE scan | Done | — | operator |
| M4-3 | Pin Actions by SHA and base image by digest | Done | — | operator |
| M4-4 | Plan the remaining dependency upgrades | Done | — | operator |
| M4-5 | Apply the planned dependency upgrades | Done | M4-4 | operator |
| M5-1 | Remove legacy URL maps | Done | — | operator |
| M5-2 | Decide the `link_sweeps` table | Done | — | operator |
| M5-3 | Decide approve/reject functions | In progress | — | operator |
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

**Decision (2026-11-08, operator): B — keep it, as a written and scoped
exception.** The exception is now in `AGENTS.md` ("Scraper rules") and quoted
here:

> **Browser fingerprint masking is a scoped exception** (SR0-1, operator decision
> 2026-11-08). `launch_browser()` keeps
> `--disable-blink-features=AutomationControlled` and the init script that hides
> `navigator.webdriver` and supplies `navigator.plugins`, `navigator.languages`
> and `window.chrome`, because the browser books need it to pass
> Cloudflare/Turnstile. It stays limited to those markers inside
> `launch_browser()`: no TLS impersonation, proxy rotation, captcha solving,
> extra stealth or account-limit evasion. A book that is still challenged is
> reported `blocked` and drops out; revisit SR0-1 if the browser books drop out.

Status: Done

Acceptance:
- [x] Decision and date recorded here.
- [ ] If A: flag and init script removed; a test asserts `launch_browser()` adds
      no init script that redefines `navigator.*`; each browser book was run once
      live and its result (ok / blocked) recorded here.
- [x] If B: exception text added to `AGENTS.md`, quoted here.

### SR0-2 Decide TLS verification default — Gate: operator

Why: `VERIFY_SSL` defaults to `"false"` (`config/settings.py:364`) and is passed
to every httpx client (`research/01_shared_infra.md` §2,
`research/04_http_reliability_research.md` line ~49). Prices read over an
unverified connection can be tampered with in transit.

Recommendation: default `true`; a per-book override exists only for a named book
with a recorded reason.

**Decision (2026-11-08, operator): keep the current default — `VERIFY_SSL`
stays `false`.** Direct httpx calls and the shared transport policy keep
`verify=VERIFY_SSL`, so certificates are not validated unless the operator sets
`VERIFY_SSL=true` in the environment. No per-book override is added. The
decision is pinned by
`tests/test_transport.py::test_the_policy_has_explicit_limits_and_a_rate`, which
asserts `policy.verify is VERIFY_SSL`, so a silent flip of the default fails the
suite. Recorded consequence: prices read over an unverified connection can be
tampered with in transit.

Status: Done

Acceptance:
- [x] Decision recorded.
- [x] Default changed (if approved); per-book override, if any, lives in the
      transport policy from SR2-2 or in settings with a comment naming the reason.
      (Not approved; the default is unchanged and no override was added.)
- [x] Test asserts the default.

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

### SR1-4 Run the test suite once per task

Status: Done

Why: the per-task loop named four full suite runs — plain `pytest`,
`pytest --cov`, and `check_test_isolation.py`'s empty and populated modes — and
the measured cost on this machine is 90 s + 240 s + 180 s ≈ 8.5 min per task.
CI's 3.11 leg already runs the empty and populated modes and the coverage gate
(`.github/workflows/ci.yml:77-101`, `docs/CI.md`), so the local repeats add no
evidence. Measured 2026-11-08: 2,166 tests in 89.8 s, `--cov` 243 s, isolation
180 s; 145 test files, 1,461 plain test functions and 712 parametrized cases.

Steps: in `AGENTS.md` and `ROADMAP.md`, make the per-task verification one full
suite run in the clean runtime state, with targeted test files while coding.
Drop `--cov` and `scripts/check_test_isolation.py` from the routine loop and
name CI as the owner of the populated-ledger mode and the coverage floor. Keep
one local exception: a change to the ledger, `config/generated/` or the
isolation guard runs the populated mode too. `docs/CI.md` records the same rule.
No test, marker or trust rule is removed.

**SR1-4 Outcome (2026-11-08).** `AGENTS.md` now has a short "Test cadence"
section; its task loop and the `ROADMAP.md` "How to use" block list **one** full
suite run at task completion (clean state) plus targeted files while coding, and
no `--cov`/isolation run in the routine loop. The `Definition of done` and
`Measurement discipline` bullets now say CI's 3.11 leg owns the populated-ledger
mode and the coverage floor, with one local exception: a change to the ledger,
`config/generated/` or the isolation guard also runs
`BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest`. `docs/CI.md` says the
same and records the measured cost. No test, marker or trust invariant was
removed, and the full suite still passes unchanged (2,166 passed, 6 skipped,
1 xfailed). Measured on this machine: plain suite 90 s, `--cov` 240 s, isolation
180 s; the per-task loop drops from ~8.5 min to ~100 s.

Acceptance:
- [x] `AGENTS.md`, `ROADMAP.md` and `docs/CI.md` name one suite run per task,
      targeted runs while coding, and CI for the second ledger mode and the
      coverage floor.
- [x] No test or trust rule is removed; the ledger/generated-state exception is
      written down.

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

Status: Done — Depends: SR0-1

Why: pinned 1.61.0; `research/05_browser_automation_research.md` reports 1.64.1
(2026-10-22). Confirm the latest on PyPI first. (Was the Playwright 1.64 item in
the old maintenance backlog.)

**SR3-1 Outcome (2026-11-08).** PyPI reports 1.64.1 as latest; the pin in
`requirements.txt` moved from 1.61.0 to 1.64.1 and the Chromium bundle was
reinstalled (`python -m playwright install chromium`, Chrome Headless Shell
156.0.8078.4, v1248). The install procedure is unchanged (README and the
Dockerfile already run `playwright install chromium`); README now notes that a
pin change needs the matching `playwright install chromium`, because the bundle
is versioned and a stale one fails with "Executable doesn't exist".
`BH_ARB_TEST_BROWSER=1 pytest tests/test_accessibility_axe.py`: **10 passed**
(the two opt-in Chromium tests included). Each browser book was run once live
(`scripts/probe_feeds.py --books admiralbet,mozzartbet,wwin`):

| book | result |
|---|---|
| admiralbet | ok — 780 matches, 9 families, 27.8 s |
| mozzartbet | `ScrapeError: offer schema drift at match.odds.14.value: Field required`, 0 matches (SR4-10) |
| wwin | `ScrapeError: prematch response is not JSON`, 0 matches (SR4-11) |

The two failures are **not** caused by the upgrade: the same probe was re-run
after downgrading the venv to 1.61.0 with its own Chromium, and both books
failed identically; the 00:48 scan that day had both healthy (wwin 877 matches,
mozzartbet 614). The failures are recorded as SR4-10 and SR4-11; the upgrade was
then reinstalled and the browser tests re-run green. The mozzartbet list-page
fingerprint also re-alerted on optional per-row keys — recorded as SR4-12. The
live probe created the runtime structural-drift baseline
`config/generated/wire_fingerprints.json`; it is now gitignored with the other
runtime state instead of showing as an untracked file.

Acceptance:
- [x] Pin updated, `playwright install chromium` documented if the procedure
      changes.
- [x] Browser tests pass with `BH_ARB_TEST_BROWSER=1`; each browser book run once
      live, result recorded.

### SR3-2 Leak-free resource blocking

Status: Done

Why: `context.route("**/*", ...)` (`scrapers/base.py:58-63`) intercepts every
request; `research/05_browser_automation_research.md` cites
playwright-python#3121, a task leak per intercepted request. Verify the issue is
still open for the pinned version.

Steps: if still relevant, block image/media/font with CDP
`Network.setBlockedURLs` (Chromium-only, acceptable) or narrow the route pattern
to resource URLs.

Acceptance:
- [x] Test or measurement showing task count does not grow across N page loads.

**SR3-2 Outcome (2026-11-08).** Verified against the tracker: playwright-python
#3121 ("context.route retains completed Tasks until Connection close") was
**closed as completed on 2026-07-02**; its cause was a CPython 3.14 asyncio task
retention fixed by python/cpython#152585, not a Playwright route defect in the
pinned client. This project runs Python 3.11 and 3.12 (CI matrix; the Docker
base is `python:3.11-slim`), where the leak never applied, so the route stays
and no CDP workaround is needed. New opt-in
`tests/test_browser_route_leak.py` pins the invariant through the real
`launch_browser()` route: six image-heavy pages (40 blocked requests each) are
loaded in one context and the completed `asyncio.Task` count is compared with
the baseline. Measured: **baseline 1, after 1, growth 0** (threshold 50; a leak
would add hundreds). Run with `BH_ARB_TEST_BROWSER=1`; `docs/CI.md` lists it
with the accessibility checks. If the support matrix ever adds 3.14, the CPython
fix is required and this test catches a regression.

### SR3-3 Shared browser lifecycle

Status: Done

Why: every scrape starts its own Playwright and Chromium; wwin starts two
(`wwin.py:257`, `:371`) (`research/01_shared_infra.md` §3).

Steps: one browser per scan (or per process with recycling after N pages / M
minutes / RSS threshold), a fresh context per book, a watchdog that restarts a
browser that stops responding. Respect `BROWSER_CONCURRENCY`. The deep-link
browser check keeps its own isolated context so its result cannot be influenced
by scraper state.

Acceptance:
- [x] wwin uses one browser for prematch and live.
- [x] Test with a fake browser: recycle after N pages; a crashed browser is
      replaced and the book reports `transport`, not `ok`.
- [x] Scan duration and peak RSS before/after recorded.

**SR3-3 Outcome (2026-11-08).** New `scrapers/browser_pool.py` owns one
Chromium per scan: `BrowserPool` launches lazily through the existing
`launch_browser()`, hands every book a fresh context from `new_context()`, and
recycles the browser after `BROWSER_MAX_PAGES` (200) contexts or
`BROWSER_MAX_AGE_SECONDS` (600). A browser that reports disconnected is replaced
at the next acquisition; a hung browser that still reports connected is replaced
at the age cap. `run_scan` opens `browser_pool()` around the scraping gather, so
one scan uses one browser; `scripts/probe_feeds.py` does the same so a multi-book
probe is comparable. Every adapter (`admiralbet`, `mozzartbet`, and both wwin
paths) now takes its context from `browser_session()`; a standalone `scrape()`
still gets a private one-shot pool, which keeps the capture scripts and the
existing fake-browser tests working. The deep-link verifier still calls
`launch_browser()` directly, so its context stays isolated from scraper state.
`BROWSER_CONCURRENCY` still bounds how many browser books run at once; the pool
is per scan, not per process.

Measured with the same three-book probe before → after:

| metric | before (one browser per scrape) | after (one browser per scan) |
|---|---|---|
| Chromium launches | 3 | **1** |
| wall | 74.2 s | 66.8 s |
| peak Chromium-tree RSS | 838.2 MB | 945.3 MB |

The RSS sample is not lower (a long-lived browser serves all three books; a
second sampled run measured 945 MB with the same 6 processes, while the books
themselves were slower that run), so the structural win is one launch and one
browser per scan rather than a memory reduction. `tests/test_browser_pool.py`
(8 tests, fake launcher) pins: one launch for many contexts, a fresh context per
book with the init script and route, recycle on the page budget, recycle on the
age budget, replacement of a disconnected browser, browser + Playwright closed,
the scan pool visible to a scrape, `PlaywrightError` classified `transport`, and
a context-close failure tolerated. All existing fake-browser suites pass with
`scrapers.base.launch_browser` patched.

### SR3-4 Response capture and failure forensics

Status: Done

Why: browser books capture JSON through `page.on("response")` listeners and
`page.request` (`research/02_adapters.md`); failures leave no artefact.

Steps: use `page.expect_response(predicate, timeout=...)` where a listener waits
for one response; on failure save a Playwright trace and a screenshot under
`cache/forensics/<book>/<scan_id>/` with a size and age cap; never store cookies
or storage state in the artefact.

Acceptance:
- [x] Forced failure in a browser test writes a trace; retention cap tested.
- [x] Artefact paths appear in the scan log line for that book.

**SR3-4 Outcome (2026-11-08).** New `scrapers/forensics.py`: a browser session
starts Playwright tracing when its context is created, discards the trace on
success, and on a failure writes `trace.zip` plus `screenshot.png` under
`cache/forensics/<book>/<scan_id>-<timestamp>/`. A capture never writes
`storage_state`, cookies or storage data, and it never raises — the real error
is re-raised unchanged. `browser_session()` wires it in, so every browser book
is covered without touching an adapter; a `CancelledError` (scan/adapter
deadline) is not captured, because the scan already records `timeout` and a
capture would race the cleanup. After each capture the directory is pruned by
age (`FORENSICS_MAX_AGE_DAYS`, 7) and then by total size (`FORENSICS_MAX_MB`,
200), never removing the newest file. `FORENSICS_ENABLED` (default true) turns
the overhead off. The capture logs `[<book>] forensics: screenshot=…, trace=…`
and `run_scan` appends `| forensics: …` to that book's failure note (scan cost
and health), so the artefact paths sit on the per-book line as well.

`page.expect_response` was checked and is not needed: no adapter waits on a
single-response listener. Mozzartbet's `page.on("response")` is a supplementary
capture of the list payload; its primary path is the paginated `page.request`
walk, so an `expect_response` rewrite would change the flow without fixing a
failure.

Tests: `tests/test_forensics.py` (5) covers a capture writing both files and
registering the paths, the disabled path writing nothing, age pruning, the size
budget (oldest first, newest kept), and the log fragment. The opt-in
`tests/test_forensics_browser.py` forces a real failure through
`browser_session("mbet")` and asserts a non-empty `trace.zip` and
`screenshot.png` exist under the book directory and that the warning line names
the book and the trace path. Measured: the browser test passes with
`BH_ARB_TEST_BROWSER=1`; `pytest`: 2199 passed, 8 skipped, 1 xfailed (17
snapshots passed); ruff clean; mypy 257 source files clean; market doc in sync;
refresh_fixtures and audit_admissibility `--check` passed.

---

### SR4 — Anti-breakage and tests

### SR4-1 Transport-level tests with respx

Status: Done

Why: no test drives an HTTP adapter's `scrape()` through a fake transport except
one MDShop test with `fetch_with_retry` monkeypatched
(`research/03_fixtures_and_pain_points.md` §A).

Steps: add `respx` (dev dependency). For each HTTP adapter, one test that serves
its fixture through respx and runs `scrape()` end to end, plus 429/403/5xx/timeout
cases using SR2-1 kinds. Block real network in the test session (respx
`assert_all_mocked` or a socket guard).

Acceptance:
- [x] Seven HTTP adapters covered (EVLBet per SR6-3 outcome).
- [x] A test that tries a real request fails loudly.

**Outcome (2026-11-08).** New `tests/test_transport_adapters.py` (37 tests)
re-inserts each captured payload into the response envelope the adapter
requests, serves it through `respx==0.22.0` (dev pin) and runs the real
`scrape()`. Six books are checked against their prematch capture — mdshop, mbet,
maxbet, sportplus, betole and premier_kladionica — with the contract that the
market families the capture declares are exactly the families returned. The
seven-adapters box is met for EVLBet at the transport boundary: no market
capture exists (SR6-3 is still open), so the test pins its recorded empty
flat-offer response as empty rather than an error. The error matrix drives 403,
429 (with `Retry-After`), 503 and a connect timeout through every adapter and
asserts the SR2-1 `ScrapeError` kinds `blocked`, `rate_limited`,
`upstream_5xx` and `timeout`, so a refused feed cannot look like an empty one.
`tests/conftest.py` gained a session-scoped socket guard (connect, connect_ex,
create_connection, getaddrinfo) so any test that escapes respx fails loudly;
two tests prove the guard and the unmocked-request failure. `docs/CI.md`
documents the layer. `pytest`: 1898 passed, 6 skipped, 1 xfailed in both ledger
modes (`check_test_isolation.py`); `pytest --cov`: 87.97% (12,166 statements,
floor 80%); ruff clean; mypy 233 source files clean; market doc in sync;
refresh_fixtures and audit_admissibility `--check` passed.

### SR4-2 Fixture metadata and age policy

Status: Done

Why: fixtures are trimmed JSON with a 120-day policy enforced by
`scripts/refresh_fixtures.py --check`
(`research/03_fixtures_and_pain_points.md` §A); no replay tool expires fixtures by
itself (`research/06_parser_contract_testing_research.md`).

Steps: a sidecar or header per fixture with `recorded_at`, book, endpoint shape,
HTTP status, capture tool version; scrub cookies/tokens; `--check` reports
missing metadata. Do not change the 120-day policy without the operator.

Acceptance:
- [x] All existing fixtures carry metadata (backfill `recorded_at` from git if
      unknown, marked as such).
- [x] `--check` fails on a fixture without metadata (test).

**Outcome (2026-11-08).** Every capture now carries the SR4-2 header: `book`
(`bookmaker`), `mode`, the reviewed `captured_at`, `recorded_at` plus
`recorded_at_source`/`recorded_at_commit`, `endpoint`/`http_method`,
`http_status`, `capture_tool_version` and the existing `source`, `payload_kind`
and `provenance`. The 17 existing fixtures were backfilled with
`refresh_fixtures.py --backfill-metadata --write`: `recorded_at` is the
fixture's last commit time (`git log -1 --format=%cI%n%h`) and is marked
`recorded_at_source: "git_commit"` with its short sha and
`metadata_backfilled: true`. Backfilled captures carry
`capture_tool_version: "pre-metadata"`; new captures write version `2` from
`CAPTURE_TOOL_VERSION`. `captured_at` was not rewritten, and the 120-day age
policy still reads it (`stale_contracts` untouched): `recorded_at` is
provenance only. `engine/parser_contracts.py` gained `metadata_issues`,
`metadata_report`, `scrub_secrets`, `backfill_metadata` and
`http_method_for`; `refresh_fixtures.build_report` reports a `metadata` block
and includes it in `ok`, so CI's `--check` fails on a missing header or a
credential-shaped key. The capture tool scrubs cookies, authorization headers,
bearer/access/refresh tokens, CSRF and session ids before writing; exact key
matching keeps Betole's `matchIdsToken` event-id list from being mistaken for
a credential. Contracts were regenerated for the new required top-level keys.
Docs: `docs/PARSER_CONTRACTS.md` (metadata table, backfill command) and
`docs/CI.md`. New `tests/test_fixture_metadata.py` (25 tests: shipped headers,
missing-field name, isolated `--check` failure at `main(["--check"]) == 1`,
git/capture-date backfill, scrub, token false-positive, age-policy pin).
`pytest`: 1923 passed, 6 skipped, 1 xfailed in both ledger modes
(`check_test_isolation.py`); `pytest --cov`: 87.95% (12,255 statements, floor
80%); ruff clean; mypy 234 source files clean; market doc in sync;
refresh_fixtures and audit_admissibility `--check` passed.

### SR4-3 Strict wire schemas, one book first

Status: Done

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
- [x] Fixture passes; mutated fixture (renamed price field) yields
      `schema_drift`, zero legs.
- [x] Unknown-key count visible in metrics.
- [x] Follow-up rows "SR4-3b … SR4-3j" added to the table, one per remaining book.

**Outcome (2026-11-08).** MDShop (the simplest direct-HTTP feed) now validates
its raw `getwebevents` response before any parser runs. New
`scrapers/wire_schemas.py` models the envelope, event, market block and price
row with `ConfigDict(strict=True, extra="allow")`; `validate_response` is
called in `scrapers/mdshop.py::fetch_and_parse` immediately after
`response.json()`. `strict=True` rejects a string price, a boolean price and a
renamed price field (`odd` → `price`); `extra="allow"` keeps an added key.
`validate_bets` validates the captured `bets` array directly, which is what the
dated fixtures freeze. A failure raises `ScrapeError(ScrapeKind.SCHEMA_DRIFT)`,
which MDShop's existing `except ScrapeError: raise` propagates, so the book
drops out instead of returning zero legs as an empty feed; a non-JSON body is
the same kind. Unknown keys outside the allow-list are counted in
`bh_wire_unknown_keys_total{book,level,field}` (`level` is `root`, `event`,
`bet` or `outcome`), logged once per payload, and never fatal. The pattern and
the follow-up mapping are in `docs/WIRE_SCHEMAS.md`; `docs/CI.md` links it.
New `tests/test_wire_schemas.py` (13 tests): both fixtures pass with no unknown
keys, the event shell passes, renamed/string prices raise `schema_drift`
through `validate_bets` and through the real `scrape()` (both modes, zero
legs), integer prices stay numeric, unknown bet/outcome/event keys are kept,
counted in the rendered metric and logged, an unknown key still scrapes, and a
non-JSON body is `schema_drift`.
`pytest`: 1936 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both
ledger modes 1936 passed, 6 skipped, 1 xfailed; coverage 88.02% (12,365
statements, floor 80%); ruff clean; mypy 236 source files clean; market doc,
refresh-fixtures and audit-admissibility checks pass.

### SR4-3b … SR4-3j Strict wire schemas, remaining books

Status: SR4-3b … SR4-3f and SR4-3h … SR4-3j Done (2026-11-08); SR4-3g is
Blocked on a live EVLBet payload (SR6-3 capture was empty). One row per
remaining book, one book per session, picked in table order (Mozzartbet first).

Why: SR4-3 proved the pattern on MDShop (direct HTTP, NSoft envelope); every
other adapter still trusts the raw payload and validates only the parsed result.

Steps: follow `docs/WIRE_SCHEMAS.md` for one book. Model its raw envelope and
leaf price rows with `strict=True, extra="allow"`, add the allow-list of
consumed keys, validate immediately after the transport read, raise
`ScrapeError(SCHEMA_DRIFT)` on failure (fail closed), count unknown keys in
`bh_wire_unknown_keys_total` and log them. Admiralbet serves the same NSoft
shape as MDShop but still needs its own fixture-backed test before it may reuse
the models. Browser books validate the captured JSON response inside the
Playwright flow, not the DOM.

Acceptance:
- [ ] That book's dated fixture passes the strict schema with no unknown keys.
- [ ] A renamed price field and a string price yield `schema_drift` and zero
      legs through the real adapter.
- [ ] Unknown-key counts appear in `bh_wire_unknown_keys_total` for that book.

**SR4-3b Outcome (2026-11-08).** Mozzartbet now validates its raw wire payload
in both paths: `validate_mozzart_offer` in `_complete_offer` (the per-event
`{"match": {"odds": [...]}}` response, immediately after `response.json()`) and
`validate_mozzart_page` in the pagination loop (`items` + `totalPages`, plus
every item's `odds` array, which is the per-event fallback). The models are
`MozzartGame` / `MozzartSubgame` / `MozzartOdd` plus `MozzartMatch`,
`MozzartOffer` and `MozzartMatchesPage`, all `strict=True, extra="allow"`.
`value` is required but nullable (the captures carry `null` for suspended
picks), so a renamed price field or a string price is `SCHEMA_DRIFT` instead of
a row the parser skips as `value == 0`. `_build_matches` re-raises a
`ScrapeError` from a per-event task, so the book drops out (fail closed) rather
than keeping the other events' legs. A per-event `{"error": ...}` payload
validates with `match = None` and keeps that event's list odds; a request or
non-JSON failure still keeps the list odds too. Unknown keys are counted at
`root`/`match`/`odd`/`game`/`subgame`. The list **item** shell (teams, kickoff,
competition) has no dated capture yet, so it is deliberately unmodelled and
documented as a gap (SR4-4/SR5-1 own structural drift). New
`tests/test_wire_schemas_mozzartbet.py` (19 tests): both fixtures pass,
`null`/integer prices are accepted, renamed and string prices raise through
`validate_mozzart_odds` and through the real `_complete_offer`/`_build_matches`
(both modes, zero legs), an unknown key is kept/counted/logged, the offer
envelope, a non-JSON offer body, the page envelope and a drifted page odds array
are covered, and the item shell stays unmodelled. `docs/WIRE_SCHEMAS.md`
records the book and levels.

Acceptance (SR4-3b):
- [x] Both dated fixtures (prematch and live) pass the strict odds schema with
      no unknown keys.
- [x] A renamed price field and a string price yield `schema_drift` through the
      real adapter, with zero legs returned.
- [x] Unknown-key counts appear in `bh_wire_unknown_keys_total` for
      `book="mozzartbet"`.

**SR4-3c Outcome (2026-11-08).** Admiralbet serves the same NSoft
`getwebevents` envelope as MDShop, so it **reuses** `NSoftResponse` /
`NSoftEvent` / `NSoftBet` / `NSoftOutcome` rather than defining a second shape.
Reuse was allowed only after its own dated captures proved it:
`tests/test_wire_schemas_admiralbet.py` checks both the prematch and live `bets`
arrays against `validate_bets(..., book="admiralbet")` with no unknown keys and
runs the real `scrape()` against them. `validate_response` now runs in
`scrape()` immediately after `response.json()`, before any event is parsed; the
adapter's historical bare-list form (the payload being the events array itself)
is wrapped as `{"events": [...]}` first, so both shapes get the same schema. A
non-JSON body or a drifted row raises `ScrapeError(SCHEMA_DRIFT)`, which the
existing `except ScrapeError: raise` propagates, so the book drops out with zero
legs. Unknown keys are counted in
`bh_wire_unknown_keys_total{book="admiralbet",...}` at the shared NSoft levels
(`root`/`event`/`bet`/`outcome`) and logged once per payload. The event shell is
validated only through the fields MDShop's capture proved: Admiralbet's extra
fallback keys (`home`/`guest`, `dateFrom`/`kickoff`, `leagueName`) have no dated
capture, stay unmodelled and are counted as unknown event keys if the live shell
carries them — recorded as the gap SR4-4/SR5-1 close. `docs/WIRE_SCHEMAS.md`
gained the Admiralbet section. New `tests/test_wire_schemas_admiralbet.py` (18
tests): both fixtures pass, integer prices are accepted, renamed/string prices
raise through `validate_bets` and through the real `scrape()` (both modes, zero
legs), the envelope and event shell pass, unknown keys are kept/counted/logged,
the real scrape emits exactly each capture's declared families, the bare-list
form is validated, and a non-JSON body is `schema_drift`.

Acceptance (SR4-3c):
- [x] Both dated fixtures (prematch and live) pass the shared strict NSoft
      schema with no unknown keys.
- [x] A renamed price field and a string price yield `schema_drift` through the
      real adapter, with zero legs returned.
- [x] Unknown-key counts appear in `bh_wire_unknown_keys_total` for
      `book="admiralbet"`.

**SR4-3d Outcome (2026-11-08).** Betole's "price row" is a `{pick_code: price}`
map, not an object with a price field, so the NSoft/Mozzart models do not fit.
`scrapers/wire_schemas.py` gained `BetoleDeskPage` (`{"esMatches": [event, ...]}`,
`esMatches` required) and `BetoleOfferRow` (`id`, `odds` required) plus
`validate_betole_offer_map`, `validate_betole_desk` and `validate_betole_offers`.
The map's **keys are data, not an allow-list**: every pick code is accepted, the
unmapped `284` control stays in the capture, and `record_unmapped` keeps
tracking codes the parser cannot price. Its **values** are the pricing surface:
`strict=True` rejects a string or boolean price, accepts an integer, and keeps
a `null` pick because the parser already reads it as "no price". The adapter
validates the desk page and each event's odds map immediately after
`response.json()` (the desk odds are the per-event fallback) and the batched
full-offer rows in `_fetch_full_offers`; a non-JSON body or a drifted row raises
`ScrapeError(SCHEMA_DRIFT)`, it is re-raised rather than swallowed by the
"failed batch keeps desk odds" fallback, and the book drops out with zero legs.
Unknown keys are counted at `root` (desk envelope) and `row` (offer rows) in
`bh_wire_unknown_keys_total{book="betole",...}` and logged once per payload. The
desk *event* shell (teams, kickoff, live flags) has no dated capture and stays
unmodelled — its keys are neither rejected nor counted, so a renamed team field
still drops that event silently (the gap SR4-4/SR5-1 close). `docs/WIRE_SCHEMAS.md`
gained the Betole section and levels. New `tests/test_wire_schemas_betole.py`
(16 tests): the capture's map passes, integer and null picks are accepted,
string prices, a renamed `esMatches`, an offer row without `odds` and non-JSON
desk/offer bodies raise (through the schema and through the real `scrape()` with
zero legs), unknown root/row keys are kept/counted/logged, and the real scrape
emits exactly the capture's expected plus experimental families.

Acceptance (SR4-3d):
- [x] The dated fixture's odds map passes the strict schema with no unknown
      keys.
- [x] A renamed price envelope key and a string price yield `schema_drift`
      through the real adapter, with zero legs returned.
- [x] Unknown-key counts appear in `bh_wire_unknown_keys_total` for
      `book="betole"`.

**SR4-3e Outcome (2026-11-08).** MBet (Alea platform, plain HTTP) has the NSoft
`{"events": [...]}` envelope but a different odds shape: each event's `odds` is
a map whose keys are oddtype keys (`ofb:fs:1`, `lfb:tg:over|2.5`, ...) and whose
values are either an entry object or a bare number. `scrapers/wire_schemas.py`
gained `MbetOdd` (`value`, `market_key`, `oddtype_key`, `market_status`,
`oddtype_status` — all required but nullable, since the capture writes all five
for every key) and `MbetResponse` (`events` required) plus
`validate_mbet_odds` and `validate_mbet_response`. `scrapers/mbet.py` validates
the page envelope and every event's odds map in `fetch_page()` immediately
after `response.json()`; a non-JSON page or a drifted entry raises
`ScrapeError(SCHEMA_DRIFT)`, which `fetch_pages` propagates, so the book drops
out with zero legs instead of reading as an empty or fully suspended feed.
Oddtype keys are data, not an allow-list: every key is accepted and
`record_unmapped` keeps tracking families the parser cannot price. Values are
strict: a string price is drift, an integer is accepted, and a bare number or a
`null` entry is kept because the parser already supports that form. Unknown keys
are counted at `root` and `odd` in
`bh_wire_unknown_keys_total{book="mbet",...}` and logged once per payload. The
event shell (sport id, competitors, kickoff, tournament) has no dated capture
and stays unmodelled — its keys are neither rejected nor counted, so a renamed
team field still drops that event silently (the gap SR4-4/SR5-1 close).
`docs/WIRE_SCHEMAS.md` gained the MBet section and levels. New
`tests/test_wire_schemas_mbet.py` (16 tests): both fixtures pass, integer/bare
number/null entries are accepted, renamed and string prices plus a renamed
`events` key raise (through the schema and the real `scrape()` in both modes,
zero legs), non-JSON pages are drift, unknown root/odd keys are
kept/counted/logged, and the real scrape emits exactly each capture's declared
families.

Acceptance (SR4-3e):
- [x] Both dated fixtures (prematch and live) pass the strict schema with no
      unknown keys.
- [x] A renamed price field and a string price yield `schema_drift` through the
      real adapter, with zero legs returned.
- [x] Unknown-key counts appear in `bh_wire_unknown_keys_total` for
      `book="mbet"`.

**SR4-3f Outcome (2026-11-08).** SportPlus's dated fixtures freeze one match's
`markets[]` array, so `scrapers/wire_schemas.py` gained `SportplusMarket`
(`id`, `name`, `odds` required but nullable) and `SportplusOdd` (`alias`,
`value` required but nullable), plus `SportplusPrematchPage` (`{"matches":
[...]}`), `SportplusLivePage` (`{"sports": [...]}`, with a declared-but-unread
`date` key kept out of the telemetry) and `validate_sportplus_markets` /
`validate_sportplus_prematch` / `validate_sportplus_live`. `scrapers/sportplus.py`
validates the prematch response after the optional double-serialised decode
(`resp.json()` returning a JSON *string*) and the live response before any
match is parsed; a non-JSON body or a drifted block/price raises
`ScrapeError(SCHEMA_DRIFT)`, re-raised by the existing `except ScrapeError:
raise`, so the book drops out with zero legs. Both envelope keys (`matches`,
`sports`) are required, so a renamed one cannot read as an empty offer. A
renamed `value`/`alias` is drift, a string price is drift, an integer price is
accepted and a block with a null `odds` list is kept (the parser already treats
it as empty). Unknown keys are counted at `root`/`market`/`odd` in
`bh_wire_unknown_keys_total{book="sportplus",...}` and logged once per payload.
The match shell (sport name, competitors, kickoff, league) has no dated capture
and stays unmodelled — its keys are neither rejected nor counted, so a renamed
team field still drops that match silently (the gap SR4-4/SR5-1 close).
`docs/WIRE_SCHEMAS.md` gained the SportPlus section and levels. New
`tests/test_wire_schemas_sportplus.py` (19 tests): both fixtures pass with no
unknown keys, the prematch/live envelopes pass, renamed and string prices raise
through the schema and the real `scrape()` in both modes with zero legs, integer
prices and a null odds block are accepted, the double-serialised prematch body
still scrapes, renamed `matches`/`sports` keys and non-JSON bodies are drift,
and unknown root/market/odd keys are kept/counted/logged.

Acceptance (SR4-3f):
- [x] Both dated fixtures (prematch and live) pass the strict schema with no
      unknown keys.
- [x] A renamed price field and a string price yield `schema_drift` through the
      real adapter, with zero legs returned.
- [x] Unknown-key counts appear in `bh_wire_unknown_keys_total` for
      `book="sportplus"`.

**SR4-3g Blocked on no live payload (2026-11-08).** EVLBet is disabled, its
recorded flat-offer response is an empty list and it has no market capture
(`tests/test_market_fixtures.py::BOOKS_WITHOUT_FIXTURES`). SR6-3's operator
decision was "capture a fixture and keep the adapter"; the 2026-11-08 capture
attempt answered HTTP 200 with `[]`, so no fixture exists. The strict-schema
acceptance cannot be met: there is no odds row to model, no renamed price field
to reject and no price to type. SR4-1 pinned the recorded empty response at the
transport boundary only. Work resumes here when a capture carries markets; the
row is no longer waiting on a decision.

**SR4-3h Outcome (2026-11-08).** Premier Kladionica's PrSync is positional: the
response is `[sections]`, each section a list of rows, and a column's meaning is
its index. The dated fixtures freeze the dogTipK odds rows (`bets`) and the
setTip/setTipVar/setTipTip definition rows (`lookup`), so
`scrapers/wire_schemas.py` gained `PremierOddRow` (`dog_id`, `grupa_tip_id`,
`set_tip_id`, `var_id`, `tip_id`, `koef` (the price, column 5), `na_pon`,
`dobitni`, `koef1`), `PremierSetTip` (name at column 2), `PremierSetTipVar`
(line at column 9) and `PremierSetTipTip` (outcome code at column 4), each
mapping its positional list through a `model_validator(mode="before")` so the
strict field types apply by position. `scrapers/premier_kladionica.py::_sync_call`
now takes the sync `kind`: a full sync validates the envelope (a `[sections]`
list with at least ten slots, each slot a list) plus sections 7/8/9, and a
delta sync validates every non-empty section as odds rows. A non-JSON body, a
non-`[sections]` envelope, a short row/tabled row or a string price raises
`ScrapeError(SCHEMA_DRIFT)`, so the book drops out with zero legs. Positional
data has no field names, so the unknown-key counter reports **unknown section
slots** (past the fifteen the parser documents) at level `section` instead. The
event, sports, competition-group and execRes sections have no dated capture and
stay unmodelled — a renamed team column still drops that event silently (the
gap SR4-4/SR5-1 close). `docs/WIRE_SCHEMAS.md` gained the Premier section and
levels. New `tests/test_wire_schemas_premier.py` (19 tests): both fixtures'
odds and lookup rows pass, both envelopes pass, string/truncated prices,
non-string line/code columns and short rows raise (schema and real `scrape()`
in both modes, zero legs), an integer price is accepted, an unknown section
slot is counted/logged, short and non-`[sections]` envelopes and non-JSON
bodies are drift, and the real scrape emits each capture's declared families.

Acceptance (SR4-3h):
- [x] Both dated fixtures (prematch and live) pass the strict schema with their
      modelled columns.
- [x] A renamed (truncated) price column and a string price yield
      `schema_drift` through the real adapter, with zero legs returned.
- [x] Unknown-section counts appear in `bh_wire_unknown_keys_total` for
      `book="premier_kladionica"` (positional data has no field names).

**SR4-3i Outcome (2026-11-08).** WWIN is a Playwright hybrid whose dated
fixtures freeze the `bets[]` array the parser reads (`idBt`, `spec`, `odds[]`
with `t`/`va`/`isv`). `scrapers/wire_schemas.py` gained `WwinOdd` (`va`
required, `isv` optional — the documented live `headerBets` row is `{va, t}`),
`WwinBet` (`idBt`, `spec`, `odds`), `WwinEventsPage` (`p`/`events` kept raw),
`WwinHeaderBetsPage` (`{"bets": [{"<eventId>": bet}]}`) and
`validate_wwin_bets`/`validate_wwin_events`/`validate_wwin_header_bets`.
`scrapers/wwin.py` validates the prematch page (`p` or the historical
`events`) and every event's `bets`, the live `events` page, and the live
`headerBets` rows immediately after `response.json()`. A non-JSON body, a
missing page key, a non-object event/header item, or a drifted bet row raises
`ScrapeError(SCHEMA_DRIFT)`, so the book drops out with zero legs instead of
reading a renamed envelope as an empty page. Unknown keys are counted at `root`
for the envelopes and at `bet`/`odd` for the rows
(`bh_wire_unknown_keys_total{book="wwin",...}`), and still scraped. The event
shell (teams, kickoff, competition) has no dated capture and stays unmodelled —
its keys are neither rejected nor counted, so a renamed team field still drops
that event silently (the gap SR4-4/SR5-1 close). `docs/WIRE_SCHEMAS.md` gained
the WWIN section and levels. New `tests/test_wire_schemas_wwin.py` (25 tests):
both fixtures' bet rows and all three envelopes pass, string/renamed prices, a
missing `spec`, a string `idBt`, a missing/renamed page key and non-object
events/header items and non-JSON bodies raise (schema and real `scrape()` in
both modes, zero legs), an integer price is accepted, unknown root/bet/odd keys
are kept/counted/logged, and the real scrape emits each capture's declared
families.

Acceptance (SR4-3i):
- [x] Both dated fixtures (prematch and live) pass the strict schema with no
      unknown keys.
- [x] A renamed price field and a string price yield `schema_drift` through the
      real adapter, with zero legs returned.
- [x] Unknown-key counts appear in `bh_wire_unknown_keys_total` for
      `book="wwin"`.

**SR4-3j Outcome (2026-11-08).** MaxBet (Singular sportsbook) is plain HTTP and
its matches response is a bare `[event, ...]` list; the dated fixtures freeze
one match's `odds[]` array. `scrapers/wire_schemas.py` gained `MaxbetSpecifiers`
(`total`/`hcp`), `MaxbetOutcome` (`outcome`, `outcomeId`, `status`, `oddValue`
required but nullable, `marketAvailableForBetting` required but nullable) and
`MaxbetMarket` (`id`, `name`, `specifiers` optional because line-less markets
omit it, `outcomes`), plus `validate_maxbet_odds`/`validate_maxbet_events`.
`scrapers/maxbet.py::fetch_and_parse` validates the list and every event's
`odds` immediately after `response.json()`. A non-JSON body, a non-list
response, a non-object event or a drifted market/outcome row raises
`ScrapeError(SCHEMA_DRIFT)`, so the book drops out with zero legs instead of
reading a renamed response as an empty list. Unknown keys are counted at
`market`, `specifiers` and `outcome` in
`bh_wire_unknown_keys_total{book="maxbet",...}` and still scraped. The event
shell (teams, kickoff, league, status, external ids) has no dated capture and
stays unmodelled — its keys are neither rejected nor counted, so a renamed team
field still drops that event silently (the gap SR4-4/SR5-1 close); a renamed
specifier on a totals market degrades to "no line" rather than drift.
`docs/WIRE_SCHEMAS.md` gained the MaxBet section and levels. New
`tests/test_wire_schemas_maxbet.py` (22 tests): both fixtures and the bare-list
envelope pass, a renamed/string price, a missing outcome id, a string
status/market id, a non-list response, non-object events and non-JSON bodies
raise (schema and real `scrape()` in both modes, zero legs), a null price is
accepted, an integer price is accepted, unknown market/specifier/outcome keys
are kept/counted/logged, and the real scrape emits each capture's declared
families.

Acceptance (SR4-3j):
- [x] Both dated fixtures (prematch and live) pass the strict schema with no
      unknown keys.
- [x] A renamed price field and a string price yield `schema_drift` through the
      real adapter, with zero legs returned.
- [x] Unknown-key counts appear in `bh_wire_unknown_keys_total` for
      `book="maxbet"`.

### SR4-4 Structural fingerprint and drift alarm

Status: Done

Why: `research/06_parser_contract_testing_research.md` §6. Shape changes are
visible before parsing fails.

Steps: compute a stable fingerprint (sorted key paths and value types, arrays
collapsed) of each raw response per endpoint; store the last good one per book;
alert (log + metric) when it changes. Alert only; do not change pricing.

**SR4-4 Outcome (2026-11-08).** New `engine/structural_drift.py` computes a
structural signature from sorted key paths plus JSON types: array indices are
collapsed (`events[].bets[].odds[].va:number`), numeric map keys are collapsed
to `<id>` (so ``headerBets``' per-event ids never look like renames), and the
signature is SHA-256-truncated. Values are ignored, so the same shape with new
prices has the same fingerprint. `observe(book, endpoint, payload)` stores the
first informative baseline per `(book, endpoint)` in
`config/generated/wire_fingerprints.json`; later responses either match or
increment `bh_wire_structure_drift_total{book,endpoint}` and log the added/
removed paths. The last good baseline is deliberately kept on drift, so the
alarm repeats until an operator reviews the change; empty pages never establish
a baseline. The check is alert-only and cannot raise into a scrape (I/O errors
are logged and skipped). It is wired at every adapter's raw-JSON boundary with
an endpoint label (MDShop/Admiralbet `mode:events:sportId`, Mozzartbet
`matches`/`offer`, Betole `desk`/`offers`, MBet `events`, SportPlus
`prematch`/`live`, Premier `sync:full`/`sync:delta`, WWin
`prematch-events`/`live-events`/`live-header-bets`, MaxBet `matches:<sport>`,
EVLBet `flat-offer`); a per-event Mozzartbet error payload is not observed.
`tests/conftest.py` redirects the baseline file into the per-test runtime tree,
and `scripts/check_test_isolation.py` still passes in both ledger modes. New
`tests/test_structural_drift.py` (12 tests): values do not change the
fingerprint, a renamed key/type change/removed level do, numeric map keys
collapse, the first informative response records a baseline, a value change
matches silently, a rename increments the counter and logs the diff while the
last good baseline is kept, empty pages do not establish one, an unreadable
store recovers, the real MDShop scrape ignores a price change and alerts on an
unmodelled key, and `/api/metrics` renders the counter.

Acceptance:
- [x] Test: same shape different values → same fingerprint; renamed key →
      different.
- [x] Drift counter in `/api/metrics`.

### SR4-5 Cardinality floors against a baseline

Status: Done

Why: an emptied or half-emptied feed (EVLBet empty feed,
`research/03_fixtures_and_pain_points.md` §B) can pass parsing. Coverage-budget
deltas exist (`research/01_shared_infra.md` §7); extend, do not duplicate.

Steps: per book and sport, rolling baseline of events and markets per event;
below a floor (absolute and relative) the book is `empty` or quarantined via the
existing feed-integrity quarantine.

**SR4-5 Outcome (2026-11-08).** `engine/coverage_budget.py` gained
`cardinality_snapshot` (events and market rows per `book|sport`),
`evaluate_cardinality` (rolling-median baselines, `event_drop` and
`market_thin` flags, peer-gated), `push_cardinality_history` (bounded to 20
scans) and `cardinality_book_reasons` (one `cardinality_drop` reason per
flagged book). The floors are relative **and** absolute: a drop below 50 % of
the median with at least 5 missing events, or markets-per-event below 50 % of
the median with at least 2 missing rows; a baseline thinner than 10 events is
not judged. A drop is only flagged when a peer book still publishes that sport
*and is itself near its own baseline*, so a shared calendar dip is not a feed
failure. `engine/feed_integrity.compute_feed_integrity` takes
`cardinality_flags`, adds the critical reason `cardinality_drop` and records
`cardinality_flags` in the scorecard/history, so the book enters the existing
quarantine state machine and recovery streak and is removed from pricing by the
unchanged `quarantined_books`/`priceable_groups` path — no second gate.
`server/api.py` computes the report per scan, persists the last report and the
bounded history in `cache/coverage_budget.json` (loaded per mode), publishes
`bh_cardinality_flags`/`bh_cardinality_flags_total`, logs the flag count and
exposes `cardinality_floor` in `/api/health`. `tests/conftest.py` resets and
redirects the new state per test. New `tests/test_cardinality_floor.py`
(9 tests): the snapshot, a 10 % feed flagged and quarantined with
`cardinality_drop`, a 75 % dip healthy, a peer-wide dip not flagged, a
markets-per-event drop flagged, a short baseline not judged, the bounded
history, the coverage-budget file round-trip and the `/api/health` block.

Acceptance:
- [x] Test: a feed at 10 % of baseline is quarantined; a normal dip is not.
- [x] Reuses the existing quarantine and coverage code paths (named in the log).

### SR4-6 Snapshot tests of normalised parser output

Status: Done

Why: `research/06_parser_contract_testing_research.md` recommendation 2.

Steps: add `syrupy` (dev). For each fixture, snapshot the normalised output
(events, markets, settlement, prices), with IDs/timestamps blanked by a matcher.
Do not snapshot raw payloads. A snapshot update requires a reason in the commit.

**SR4-6 Outcome (2026-11-08).** Added the dev-only pin `syrupy==5.0.0`. New
`tests/test_parser_snapshots.py` runs every fixture that declares
`expected_markets` (17 captures) through the real parser entry point that
`tests/test_market_fixtures.py::_run_parser` dispatches to, and snapshots the
**normalised** output only: `market_type`, `settlement`, `period` and each
`label`/`value` price row. Source ids, source context, outcome ids and update
timestamps are deliberately left out, so book-specific identity data and the
scan clock cannot churn the snapshot. Raw payloads are not snapshotted; SR4-2/
SR4-3 already pin the raw shape and `tests/fixtures/markets/contracts.json` pins
the ids/labels. Snapshots live in
`tests/__snapshots__/test_parser_snapshots.ambr` and run in the normal `pytest`
run (17 snapshots + one coverage guard). `pytest --snapshot-update` stays a
human action: `docs/CI.md` records that a commit updating a snapshot must say
why the normalised output changed and that CI never updates one. A second test
asserts the snapshot case set equals the set of fixtures declaring
`expected_markets`, so a new capture cannot silently skip the snapshot layer.

Acceptance:
- [x] Snapshots for every fixture that has `expected_markets`.
- [x] Snapshot tests run in the normal `pytest` run.

### SR4-7 Property-based mutation tests for parsers

Status: Done

Why: `research/06_parser_contract_testing_research.md` recommendation 4.

Steps: add `hypothesis` (dev) if not present. Mutate fixtures (drop keys, null
values, swap types, shuffle arrays, duplicate markets). Properties: the parser
never raises an unhandled exception; never emits a leg with a missing or
non-positive price; never emits two legs for one book in a group; never changes
sport or settlement.

**SR4-7 Outcome (2026-11-08).** `hypothesis==6.150.0` was already a dev pin. New
`tests/test_properties_parsers.py` runs all 17 fixtures that declare
`expected_markets` (the nine parser dispatch paths; EVLBet has no capture,
SR6-3). Each Hypothesis example keeps the payload container and applies 1-3
bounded mutations inside it: drop a key, null a value, swap a scalar type,
shuffle/duplicate/drop/truncate an array, add an unknown key. A mutation the
book's wire schema (SR4-3) rejects is skipped, because in production the raw
payload never reaches a parser in that shape; this keeps the property about the
parser rather than a second schema implementation. Accepted mutations must
return a list without an unhandled exception, every emitted price must be
finite and positive, no label may repeat for one
`(market_type, settlement, period)`, and no emitted identity may fall outside
the clean capture's sport/settlement set (mutations may drop markets, never
cross sport or settlement). The clean capture is checked against the same
invariants, plus two filter tests (an unknown key is accepted, a short Premier
row is rejected), so the property is not vacuous. Runtime is ~2 s for 17×40
examples. The mutation run found one production-reachable defect (a duplicated
NSoft `betOutcome` becomes two legs for one book); it is recorded as `SR4-7a`
and pinned by a strict xfail, not fixed in this row. The schema-guarded
robustness gaps it also exposed (short Premier rows, a non-object MaxBet
`specifiers`) cannot reach a parser in production and need no code change.

Acceptance:
- [x] Property tests for every parser, bounded run time in CI.
- [x] Any bug found is fixed in a separate task row, not silently in this one.

### SR4-7a Drop a duplicated NSoft outcome label

Status: Done

Why: SR4-7's mutation run showed that `parse_nsoft_bets` appends one
`OddsValue` per raw `betOutcomes` row without deduplicating by normalized
label. A payload with the same outcome twice (the schema accepts it: the
`betOutcomes` list has no uniqueness rule) yields a market whose odds list
carries label `1` twice. That is two legs for one book in a group, against
trust invariant 8. `tests/test_properties_parsers.py` pins the defect with a
strict xfail (`test_nsoft_duplicate_outcome_is_not_emitted_twice`), which turns
red when the fix lands and forces the marker's removal.

Steps: in `scrapers/common.py::parse_nsoft_bets`, keep the first (or the latest
offered) price per normalized label instead of appending a duplicate; keep the
existing `actual`/`min_legs` acceptance logic. Add a fixture-free regression
test and remove the strict xfail; update the SR4-7 docstring's known-defect
paragraph.

**SR4-7a Outcome (2026-11-08).** `parse_nsoft_bets` now tracks the normalized
labels it has already emitted and keeps the **first offered** price per label;
a later duplicate row is ignored, including its outcome id. The existing
`actual`/`min_legs`/`issubset` acceptance logic is unchanged, so a market still
needs its full label set. In `tests/test_properties_parsers.py` the strict
xfail was removed, the regression test now duplicates the first outcome of the
real MDShop prematch capture (with a different price) and asserts one label with
the first price, and the mutation property enforces label uniqueness again for
every parser. A duplicated outcome can no longer become two legs for one book.

Acceptance:
- [x] A duplicated normalized label yields one `OddsValue`, and the strict
      xfail is removed.
- [x] `python -m pytest` and `python scripts/check_test_isolation.py` stay green.

### SR4-8 HAR fixtures for browser books

Status: Done

Why: browser books are captured by hand and never replayed
(`research/03_fixtures_and_pain_points.md` §A;
`research/05_browser_automation_research.md` §1 `record_har_path` /
`route_from_har`). SR4-8a chose route A (in-page fetch), so the API calls are
now page-initiated and a HAR can record and replay them.

Steps: capture tool writes a scrubbed HAR (no cookies, no auth headers) per
browser book; a test replays it with `route_from_har` and runs the real
`scrape()`. Runs only with `BH_ARB_TEST_BROWSER=1`; add an optional CI job with
Chromium (was the browser-enabled CI Chromium job in the old maintenance
backlog, folded here).

Acceptance:
- [x] One HAR replay test per browser book.
- [x] Scrubbing test: no `cookie`/`authorization` headers in any committed HAR.

**SR4-8 Outcome (2026-11-08).** New `scrapers/har_fixtures.py` owns the fixture
rules: `REPLAY_PREFIXES` (each book's API), `MAX_REPLAY_OFFERS` (30 for
`mozzartbet`, whose full offer is one request per event), `trim()` (keeps the
page document plus that book's API calls, drops analytics/JS/images/fonts),
`scrub()` (drops `cookie`/`set-cookie`/`authorization`/`proxy-authorization`
headers and empties the HAR cookie jar; odds payloads stay) and the gzip
`loads`/`dumps` helpers. New `scripts/capture_har.py` records a live HAR through
the real adapter and browser pool (`browser_pool(record_har_path=...)`, a new
seam), trims and scrubs it, writes `tests/fixtures/har/<book>.har.gz` plus a
`<book>.meta.json` sidecar, then **replays the new file offline through the same
adapter** and records the measured `matches`/`markets` in the sidecar; a capture
that replays zero matches fails instead of writing a fixture. The committed set
is 1.72 MB gzipped: admiralbet 492 KB (93 matches / 739 markets from 38
entries), wwin 341 KB (450 / 2,643 from 56), mozzartbet 892 KB (207 / 941 from
54 — 30 offers kept, the rest abort into the adapter's documented list-odds
fallback). Raw captures are 9–88 MB, which is why the files are gzipped and the
per-event offers bounded. The replay runs with
`browser_pool(har_path=...)` (second new seam) as
`route_from_har(not_found="abort")`, so a missing entry aborts and nothing can
reach the network; the sidecar's `scan_time` is passed to `scrape()` because the
adapters build their request URLs from it. New `tests/test_har_fixtures.py` (8
tests, normal suite): every book's file is present, holds only its document and
API calls, carries no secret header and an empty cookie jar, has a consistent
sidecar, is already trimmed (idempotent) and is under the size budget; the
synthetic cases pin `scrub`, `trim` and the offer bound, so a new capture cannot
ship credentials. New opt-in `tests/test_browser_har_replay.py` (3 tests) runs
the real `scrape()` from each file and asserts the sidecar counts. New
`docs/HAR_REPLAY.md` (format, scrubbing, refresh command, what a replay does not
prove); `docs/CI.md`, `README.md` and `AGENTS.md` point at it. New
`.github/workflows/browser.yml` runs the Chromium checks (this file, the
page-fetch route check, accessibility, the route-leak check) on
`workflow_dispatch` only, so the push CI stays fast. No bookmaker traffic is
generated by a replay.

**SR4-8 investigation (2026-11-08, before SR4-8a).** Measured before writing fixtures:
Playwright's `context.route` / `record_har_*` / `route_from_har` only see
**page-initiated** requests. The browser adapters fetched their JSON through
`page.request.get/post` (`measured_api_get`/`measured_api_post`), which is an
`APIRequestContext` and bypasses both routing and HAR recording. The probe:
a route on `**/probe` never fired for `page.request.get`, which went to DNS,
while `page.evaluate("fetch(...)")` did fire it. A real capture confirmed it
from the other side: a full admiralbet scrape recorded a HAR whose only entries
were analytics/widgets (`log.cookieyes.com`, Sentry, a chat widget) — the NSoft
event responses the adapter actually parsed were absent. So a HAR could not
serve a real `scrape()` and a captured HAR would be dead weight; the attempt was
discarded (no HAR, capture tool or partial test committed). `SR4-8a` owned the
transport decision; it chose route A on 2026-11-08 and the adapters now fetch
from inside the page, so this row resumes with the capture tool and one replay
test per browser book.

### SR4-8a Choose the browser replay transport

Status: Done

Gate: operator

**Decision (2026-11-08, operator): A — in-page fetch transport.** The three
browser adapters issue their JSON calls with `fetch` inside the loaded document
instead of `page.request`, so `context.route`/`route_from_har` see every API
call and SR4-8 works as written. The live request shape changes (`sec-fetch-*`,
CORS, headers), so the measurement below was taken before the change is
treated as trusted, exactly as the option text required.

Why: the three browser adapters fetch JSON over `page.request`, which HAR
record/replay cannot see. Two ways to make a browser scrape replayable, with
different risk:

- **A. In-page fetch transport.** Replace `measured_api_get/post` with
  `page.evaluate(fetch(...))` (credentials included), keeping the same rate
  limit, retry and byte accounting. Then `context.route` and `route_from_har`
  cover every API call and SR4-8 works as written. It changes the live request
  shape (`sec-fetch-*`, CORS, headers) and must be measured on a live scan
  before it is trusted.
- **B. Boundary-recorded HAR shim.** Keep `page.request`. A capture tool wraps
  `measured_api_get/post` and records each request/response into a HAR-like
  file (scrubbed), then records only the page document with Playwright's HAR.
  The replay test serves the document with `route_from_har` and the API calls
  from the same file through a test shim. No live transport change; the test
  exercises the adapter and parser on recorded bodies but not the real
  transport.

Steps: record the choice here. For A: a measurement plan (requests/bytes/wall,
Cloudflare pass, per-book kinds on one live scan) before merging. For B: the
capture/replay format and the honest limit (API bodies recorded at the adapter
boundary).

**SR4-8a Outcome (2026-11-08).** `scrapers/base.py` now runs the adapters' API
calls as an in-page `fetch` (`_page_fetch`): the same `headers`/`params`/`data`
arguments, the same returned surface (`status`/`status_code`, `headers`,
`body()`, `json()`, `content`), `credentials: "include"` so the browser's
cookies and Cloudflare clearance go with it, every request and body size still
counted, and a Python-side 30 s cap (`PAGE_FETCH_TIMEOUT_SECONDS`, the old
`APIRequestContext` default) so an overrun is the shared `timeout` kind rather
than a text-matched JS error. A dict/list body is JSON-serialised with
`application/json` and a string body is sent unchanged, mirroring Playwright's
`data` rules, so the two POST endpoints keep their request shape. No adapter
calls `page.request` any more, pinned by
`tests/test_page_fetch.py::test_no_adapter_calls_page_request`.

Measurement (form in `docs/evidence/2026-11-08-sr4-8a-inpage-fetch.md`): one
live prematch pass per browser book with the per-book cost collector, plus an
A/B control minutes later with `measured_api_*` patched back to `page.request`
in-process. In-page → control: admiralbet 3 req / 4.71 MB / 13.2 s / 121
matches, kind `ok` → 3 req / 4.71 MB / 10.3 s / 121 matches, `ok`; mozzartbet
234 / 72.27 MB / 25.5 s (19.2 s earlier) / 215 → 233 / 71.95 MB / 37.0 s / 215;
wwin 46 / 2.03 MB / 13.2 s / 459 → 46 / 2.03 MB / 12.1 s / 459. **Cloudflare
passed on all three, including cross-origin admiralbet; zero `blocked`/
`transport`, three `ok`.** Requests match within one event, bytes within 0.5 %
and the parsed output is identical modulo that event, so the in-page path reads
the same feed at the same cost. `tests/test_page_fetch.py` (10 tests) pins the
request shape, body round-trip (empty body, non-ASCII), byte accounting, the
Python timeout, a page error as `transport`, a 403 as one `blocked` attempt and
a 503 retry; `tests/test_page_fetch_browser.py` (opt-in,
`BH_ARB_TEST_BROWSER=1`) proves with real Chromium that `context.route` sees the
document and the in-page API call, POST body included. `docs/CI.md` lists the
new opt-in check, `docs/SCAN_COST.md` names the in-page fetch in the `requests`
definition. No login, no bet, rate limit and retry policy in force.

Acceptance:
- [x] Choice recorded with the reason.
- [x] SR4-8 resumed with the agreed scope, or closed if the boundary shim is
      judged not worth its maintenance. (Resumed: capture tool + one replay test
      per browser book.)

### SR4-9 Scheduled live canary — Gate: operator

Status: Done

Why: `research/06_parser_contract_testing_research.md` §6; offline fixtures
cannot see a site change.

**Decision (2026-11-08, operator): operator host, daily.** The canary runs from
this machine (real network, not a CI datacentre IP) once a day, keeps its report
under the runtime state directory, and never fails the main CI. The
implementation lands under this row; nothing runs until it is built and the
timer is installed.

Steps: an opt-in scheduled job that runs each book once (rate-limited, no login,
same transport policy), compares fingerprint and counts with the baseline, and
reports. It never refreshes fixtures automatically. The operator decides where it
runs (CI from a datacentre IP may be blocked differently from the operator host)
and how often.

Acceptance:
- [x] Decision recorded (where, how often).
- [x] Report format documented; a failing canary does not fail the main CI.

**SR4-9 Outcome (2026-11-08).** New `scripts/live_canary.py` probes every
configured book once through its real adapter (so the shared transport policy,
rate limit and deadline apply), sequentially, and writes one dated report to
`cache/live_canary/YYYY-MM-DD.json`. It compares with the newest other report:
an adapter error or missing scraper, a book with at least 10 matches that loses
more than half, and a market family with at least 5 markets that loses more than
half are reasons; a new family is listed as news, not an alarm. The default exit
code is 0 even with alarms so a timer does not page on a feed gap; `--strict`
returns 1. It never writes a fixture or contract and is not wired into CI.
New `docs/LIVE_CANARY.md` documents the schema, the thresholds, the boundaries
and the cron line for the operator host (daily, 06:17). New
`tests/test_live_canary.py` (12 tests) covers the first run, a halved book and
family, an erroring book, a missing scraper, a new family, the threshold table,
that no fixture mtime changes, and `--strict`. No live probe was run in this
session; the timer is installed by the operator, not by the repo.

---

### SR4-10 Mozzartbet offer rows may omit `value`

Status: Done

Why: the 2026-11-08 live probe (SR3-1) logged
`mozzartbet offer schema drift at match.odds.<n>.value: Field required` for many
matches, so the whole book dropped with zero legs. `MozzartOdd` requires all
three fields on purpose and documents that `value` may be `null`; the live feed
now leaves the key out entirely for some picks (suspended rows), while the
`oddValue` price is still there. The 00:48 scan that day was healthy (614
matches), and the same failure reproduces on Playwright 1.61.0, so it is a feed
change, not the browser upgrade.

Steps: capture one live `POST /betting/match/{id}` response that reproduces the
omission and compare it with the dated fixture. Then either model a missing
`value` explicitly as null (and count it) while keeping `value` present-but-null
required as before, or treat it as a real feed change and refresh the contract.
Do not drop the strictness before checking what a renamed price field would do.

Acceptance:
- [x] A dated capture reproduces the omission.
- [x] The parser emits no leg without a price.
- [x] A renamed price field still fails as schema drift; tests cover both.

**SR4-10 Outcome (2026-11-08).** A live offer captured that day carries 518
rows: 413 with a numeric `value`, 105 with no `value` key at all, 0 with
`value: null`. The unpriced rows have the same key set minus `value` and the
same `specialOddValue: "-1"` as priced rows; there is no second price field.
They are suspended picks, and they occur in supported families too, not only in
the excluded combinations. Captured in
`docs/evidence/2026-11-08-mozzartbet-missing-value.md`. `MozzartOdd.value` is
now optional (`float | None = None`) while `game`/`subgame` stay required and a
string or boolean price is still `schema_drift`; `validate_mozzart_page()` adds
one page-level guard — a list page that carries odds rows and no numeric
`value` anywhere is `schema_drift`, which is what a renamed price field looks
like, while a single suspended row or a fully suspended offer is accepted. The
parser already skipped a missing price (`value` falsy → 0.0 → below the 1.01
floor), so no leg is emitted without one and a short market still fails
`min_legs`. Tests: a row without `value` validates as unpriced; a mixed page
passes; a page with no priced row is drift; a renamed `value` on the list page
is drift; an offer with the 1X2 rows unpriced yields no 1X2 leg but still
parses the other families; a string price still drops the book. Measured
before → after, same probe: **0 matches → 603 matches / 4,698 markets**, 28.8 s
(1x2 603, double_chance 597, btts 590, over_under_1_5 579, over_under_2_5 603,
over_under_3_5 591, over_under_4_5 553, first_half_1x2 582).

### SR4-11 WWin non-JSON body classified as schema drift

Status: Done

Why: the 2026-11-08 live probe (SR3-1) got
`wwin prematch response is not JSON: Expecting value: line 1 column 1 (char 0)`
and the book dropped with zero legs, minutes after its events page had parsed
(the structural-drift log shows `prematch-events`). The adapter classified any
JSON decode failure as `SCHEMA_DRIFT`.

**Corrected by the capture (2026-11-08).** The body was not HTML. Replaying the
exact batch (15 day windows × 3 bet groups, sequential) shows **days 8 and 9
answer HTTP 200 with a 0-byte body** for every bet group, while the other days
answer JSON (2 KB–1.0 MB, 699 events on day 0). A 0-byte body is the feed saying
"no rows for this window", not drift; the blanket classification dropped the
whole book over it. An HTML body remains possible in principle (challenge) and
is `blocked`.

Steps: decode the body once in `_json_body(resp, label)`: empty/whitespace →
`None` ("no rows"); HTML (content-type `text/html` or a `<` prefix) →
`ScrapeError(BLOCKED)`; any other non-JSON → `ScrapeError(SCHEMA_DRIFT)`. The
prematch slice returns an empty event list, live stops with no matches, and a
live `headerBets` slice is skipped. All three response sites use the helper.

Acceptance:
- [x] An HTML/challenge body is `blocked`; a malformed JSON body stays
      `schema_drift`.
- [x] A 0-byte or whitespace body is "no rows for that slice" and does not drop
      the book.
- [x] No book is filled with stale or guessed prices.

**SR4-11 Outcome (2026-11-08).** `scrapers/wwin.py` gained `_json_body`, used by
the prematch day loop, the live events page and the live `headerBets` page.
Measured replay: 45 requests, days 0–7 and 10–14 return JSON, days 8–9 return
HTTP 200 / 0 bytes for all three groups — an out-of-horizon window, not a
challenge. Empty ⇒ no rows for that slice; HTML ⇒ `blocked`; other non-JSON ⇒
`schema_drift`. New tests in `tests/test_wire_schemas_wwin.py`: an empty body and
a whitespace body are no rows (prematch and live), an HTML page is `blocked`,
and a malformed body is drift. Measured before → after, same probe: **0 matches
→ 1,014 matches / 5,445 markets**, 12.5 s (1x2 1,014; double_chance 996; btts
879; over_under_2_5 817; over_under_3_5 575; over_under_1_5 336; over_under_4_5
198; over_under_5_5 11; over_under_0_5 9; first_half_1x2 610).

### SR4-12 Fingerprint over heterogeneous list pages

Status: Done

Why: during the SR3-1 live probe, mozzartbet's list page alerted six times and
wwin's three times for per-item optional keys (`items[].matchComment`,
`events[].aPrevSc`) that only some rows carry. The fingerprint is the union of
every item's paths, so one optional key on one match changes the digest, and
SR4-4 deliberately keeps the old baseline on drift, which means every later run
re-alerts. The alarm is correct about the *shape* but too sensitive to a normal
heterogeneous list.

Steps: fingerprint a page by the paths common to all items (plus an explicit
per-item-shape rule), or compare per-item shape multisets and alert only when a
key disappears from items that used to carry it. Keep it alert-only and keep the
last good baseline on drift.

Acceptance:
- [x] A key on only some items does not alert.
- [x] A removed or renamed price key still alerts.
- [x] The existing SR4-4 tests still pass.

**SR4-12 Outcome (2026-11-08).** The signature now keeps only the paths
**common to every item of a list**; per-item-only paths are recorded as
`optional` in the baseline and never make a digest differ. Types are unioned
across the items that carry a common path, and `null` is ignored when a real
type is also present, so a nullable field does not flip the digest on a page
with no null row. Drift means a common path disappeared, an unknown path
appeared, or a common path's type set changed. A previously optional path that
becomes common is adopted silently (so its later removal still alerts), and a
required path demoted to optional is a removal. `FINGERPRINT_VERSION = 2` makes
`observe` re-record an older baseline once without an alert, so the upgrade is
not a page-wide false alarm. `structural_paths()` returns the required
`path:type` set and new `optional_paths()` exposes the rest. New tests (7, in
`tests/test_structural_drift.py`): optional key move, required price removal,
price rename, type change, nullable field, optional-to-common promotion followed
by removal, and the v1 upgrade path; the 12 SR4-4 tests still pass. `docs/CI.md`
documents the heterogeneous-list rule. Measured: `pytest` 2223 passed, 8
skipped, 1 xfailed (17 snapshots); ruff clean; mypy 260 source files clean;
market doc in sync; refresh_fixtures and audit_admissibility `--check` passed.

---

### SR4-13 Premier delta rows shorter than the strict schema

Status: Done

Deps: SR4-3h.

Why: the 2026-11-08 SR5-2 baseline found `premier_kladionica` dropping out of
both scans with `schema_drift`: a delta sync odds row arrived as
`[0, '', 1794138522410, 4, 1308500813]` (5 columns) where
`validate_premier_sync`'s strict adapter expects at least 9. The earlier
prematch probes passed, so the row variant is new or intermittent in the delta
section — most likely a delete/tombstone row, but that is a guess until the
payload is captured. Until then Premier contributes nothing to either feed.

Steps: capture the live full and delta sync payloads (dated evidence under
`docs/evidence/`), identify the short-row variant and its meaning, model it in
`validate_premier_sync` without loosening the strict check for real odds rows,
and add a fixture-backed parser test plus a replay of the captured shape.
Never accept an arbitrary short row merely to stop the drift.

Acceptance:
- [x] The captured delta shape validates and still produces no fabricated odds.
- [x] A malformed real odds row (missing price/selection columns) still drifts.
- [x] A probe of `premier_kladionica` in both modes returns matches
      instead of `schema_drift`, with the measured counts recorded.

**SR4-13 Outcome (2026-11-08).** Root cause: the delta response is five
positional tables, not one — execRes (5 columns), dogVar (14), dogTipK odds (9),
dogLiveScore (43) and a scalar section — and `validate_premier_sync` was
validating every non-empty section as odds, so the 5-column execRes row
`[0, "", 1794138522410, 4, 1308500813]` drifted the whole book. Empty sections
are omitted, so the index cannot identify the table; a section is now an odds
table only when at least one row has the dogTipK shape (ints at 0/2/3/4, numeric
price at 5, numeric result at 7), and every row of a recognised section still
goes through the same strict adapter, so a truncated row or string price still
drifts. The other tables stay unmodelled, as they were on a full sync; if every
row of an odds section lost the shape, the parser reads none (fail closed) and
SR4-4's page fingerprint still alarms. The live delta was captured in
`tests/fixtures/wire/premier_kladionica_delta.json` (trimmed, verbatim) and
documented in `docs/evidence/2026-11-08-premier-delta-sections.md`. Five new
tests in `tests/test_wire_schemas_premier.py`: the real envelope validates, the
exact execRes row is not odds, a truncated row in a recognised section drifts, a
mistyped price drifts, and an auxiliary section alone is left unmodelled. Live
probes: prematch **700 matches / 5,761 market rows** in 7.4 s, live **151
matches / 868 market rows** in 5.2 s, both with `error: ""`. Measured: `pytest`
2228 passed, 8 skipped, 1 xfailed (17 snapshots); ruff clean; mypy 260 source
files clean; market doc in sync; refresh_fixtures and audit_admissibility
`--check` passed.

---

### SR5 — Observability

### SR5-1 Per-book reliability metrics

Status: Done

Why: `research/01_shared_infra.md` §8 — in-house registry exists; keep it
(`research/04_http_reliability_research.md` recommendation 4).

Metrics: attempts, retries, outcome kind counter, status code counter, latency
histogram, breaker state gauge, last success timestamp, schema drift counter,
unknown-key counter, browser recycle counter.

Acceptance:
- [x] All metrics in `/api/metrics` with a test scraping the text output.
- [x] Metric names documented in `docs/`.

**SR5-1 Outcome (2026-11-08).** The registry gained a cumulative histogram type
(`MetricsRegistry.observe`, `HISTOGRAM_BUCKETS` 0.05 … 120 s, rendered as
`_bucket{le=…}`/`_sum`/`_count`) and every metric in the list now exists:

- attempts/retries/latency/status — `retry_call` records
  `bh_scraper_attempts_total{book}`, `bh_scraper_retries_total{book}`,
  `bh_scraper_attempt_seconds{book}` (histogram) and
  `bh_http_status_total{book,status}` for every attempt, including the failed
  ones; the rate-limit slot and existing accounting are unchanged.
- last success — `bh_book_last_success_timestamp_seconds{mode,book}` is set on
  an `ok` result in `run_scan` and published as 0 for every book/mode at startup.
- schema drift — `bh_schema_drift_total{book}` increments in
  `wire_schemas._drift()`.
- browser recycles — `bh_browser_recycles_total{reason}` in the SR3-3 pool, with
  `pages`, `age` or `crash`.
- already present and kept: `bh_book_kinds_total` (outcome kind),
  `bh_book_breaker_state`/`_failures`/`_cooldown_seconds`, and
  `bh_wire_unknown_keys_total`.

New `docs/METRICS.md` documents every family with its type, labels and meaning,
the histogram semantics and the startup-zero rule; the README monitoring
section links it. New `tests/test_reliability_metrics.py` (6 tests) renders the
histogram buckets, exercises the retry path and asserts the counters, the schema
drift counter and a pool recycle, and scrapes `/api/metrics` text for every new
family; `tests/test_metrics.py` also asserts the last-success gauge after a real
scan. Measured: `pytest` 2204 passed, 8 skipped, 1 xfailed (17 snapshots passed);
ruff clean; mypy 258 source files clean; market doc in sync; refresh_fixtures and
audit_admissibility `--check` passed. Total 2237 passed. No bookmaker traffic.

### SR5-2 Per-book health state and live cost baseline

Status: Done

Why: `/api/health` is rich but has no per-book state machine; the first live cost
baseline is unmeasured (`research/03_fixtures_and_pain_points.md` §B).

Steps: per-book state (`healthy`, `degraded`, `open`, `blocked`, `drifted`,
`disabled`) derived from SR2-1/SR2-6/SR4-4. Measure and record a live cost
baseline (requests, bytes, seconds, browser seconds per scan).

Acceptance:
- [x] Health test per state.
- [x] Baseline numbers recorded in `docs/SESSION_BRIEF.md` or a doc it links.

**SR5-2 Outcome (2026-11-08).** New `server/book_health.py` is the one place
that reduces the existing evidence to a per-book state: `healthy`, `degraded`,
`open`, `blocked`, `drifted` or `disabled`, each with a one-line reason. Inputs
are the SR2-1 kind from the last N1-3 scan-cost record (with the legacy
`outcome` fallback), the SR2-6 breaker snapshot and the runtime enable map;
priority is disabled → blocked → drifted → open → degraded → healthy, so a
blocked site is not hidden by the breaker it tripped, and an open breaker still
shows when the cause was timeouts/transport. A book with no record is
`degraded` ("no scan recorded yet"). `GET /api/health` now serves
`book_health.{prematch,live}` for every configured book; it is diagnostic only
(pricing keeps reading feed integrity and the certainty gate). New
`tests/test_book_health.py` (12 tests): one per state plus the priorities, the
outcome fallback, the builder and the endpoint for all states on the prematch
feed and the unproven live feed.

The live cost baseline is measured and recorded in
`docs/evidence/2026-11-08-scan-cost-baseline.md` (linked from
`docs/SCAN_COST.md`, `docs/SESSION_BRIEF.md`), one scan per feed: prematch
144.8 s elapsed, 682 requests, 392.77 MiB, 201.06 book-seconds, 1.32
browser-seconds, 6,610 matches / 45,192 market rows (0.030 s, 62 KB per match);
live 33.7 s, 70 requests, 74.74 MiB, 66.52 book-seconds, 1.45 browser-seconds,
653 matches / 3,548 market rows (0.102 s, 120 KB per match), with explicit
`n/a` reasons. The scans also exposed a separate feed defect —
`premier_kladionica` delta sync drifting on 5-column rows in both modes —
recorded as **SR4-13** and not fixed here. Measured: `pytest` 2216 passed,
8 skipped, 1 xfailed (17 snapshots); ruff clean; mypy 260 source files clean;
market doc in sync; refresh_fixtures and audit_admissibility `--check` passed.

---

### SR6 — Structure

### SR6-1 Single adapter declaration

Status: Done

Why: `SCRAPERS` (`server/api.py:1020`), `PLAYWRIGHT_BOOKIES`
(`server/api.py:253`) and the market registry are synchronised by hand
(`research/01_shared_infra.md` risks).

Steps: one declaration per book (name, import path, transport, policy,
enabled flag) that the other lists are derived from; imports stay lazy. A test
fails when a module under `scrapers/` has no declaration or a declaration has no
module.

Acceptance:
- [x] The three lists are derived, not hand-written.
- [x] Consistency test.

**SR6-1 Outcome (2026-11-08).** New `config/bookmakers.py` holds one
`AdapterDeclaration` per book: name, adapter module and class (strings), the
transport (`http`/`browser`), the default enabled flag, the UI URLs/colour and
the per-feed HTTP timeouts. Four hand-kept lists now derive from it:
`settings.BOOKMAKERS` (same dict shape as before), the new lazy
`scrapers.registry.SCRAPERS`, `PLAYWRIGHT_BOOKIES` (the three browser books) and
`scrapers.transport`'s policy table (20 books×modes, same timeout values).
`SCRAPERS` is a `MutableMapping` that imports an adapter on first read and still
supports `monkeypatch.setitem` for the tests; `server/api.py` no longer imports
any adapter module, so `import server.api` loads **0** book modules (measured).
`scrapers.__all__` is derived from the same declaration too (adding the two
classes the old hand list had missed). The market registry stays curated JSON,
but its book set is checked against the declaration. New
`tests/test_adapter_declarations.py` (9 tests): AST scan fails
when a `scrapers/*.py` module defines `async def scrape` without a declaration,
and when a declaration has no module/class; the three lists, timeout policies
and market-registry books must match; an unknown key raises `KeyError`; a read
caches the class; and a subprocess proves the lazy import. Measured: `pytest`
2237 passed, 8 skipped, 1 xfailed (17 snapshots); ruff clean; mypy 263 source
files clean; market doc in sync; refresh_fixtures and audit_admissibility
`--check` passed. No bookmaker traffic.

### SR6-2 Adapter `Protocol` and mypy enforcement

Status: Done

Steps: a `typing.Protocol` for adapters; the declaration from SR6-1 is typed
against it so mypy catches a missing or mistyped `scrape()`.

**SR6-2 Outcome (2026-11-08).** New `scrapers/protocol.py` owns
`BookAdapter` (a `runtime_checkable` `Protocol`) and `AdapterClass =
type[BookAdapter]`: no-argument construction and an async `scrape()` with the
three keywords `run_scan` passes (`live`, `scan_time`, `sports_wanted`). Five
adapters lacked `sports_wanted` (mozzartbet, betole, evlbet, premier_kladionica,
wwin) and their calls used to go through a `TypeError` fallback in
`server/api.py`; they now accept the keyword and ignore it, so the previous
behaviour (fetch every listed sport) is unchanged and the scan no longer has to
guess a signature. `scrapers.registry` types `__getitem__` as `AdapterClass`
and gained `adapter(book) -> AdapterClass | None`, which the two scan call sites
in `server/api.py` now use, so mypy checks `scraper.scrape(...)` against the
protocol instead of `Any`; the `TypeError` fallback stays only for
monkeypatched test fakes. New `tests/test_adapter_protocol.py` (5 tests): every
declared class matches the protocol at runtime (construction, coroutine,
keyword defaults, `get_type_hints`), the registry's annotations are the protocol
types, the protocol imports without loading an adapter module, and two mypy
subprocess checks build a module from the real declaration (all ten classes
type-check) and reject three deliberately broken adapters (missing entry point,
sync entry point, wrong return). `tests/test_adapter_declarations.py`'s AST
guard now counts a concrete class with an async `scrape`, so the `Protocol` is
not mistaken for an undeclared adapter. No live scan, no bookmaker traffic.

Acceptance:
- [x] mypy fails on a deliberately broken adapter in a test fixture module (or a
      `reveal_type`/`assert_type` check).

### SR6-3 Decide EVLBet's future — Gate: operator

Status: Done

Why: EVLBet is disabled, returns an empty feed and has no fixture
(`research/02_adapters.md`, `research/03_fixtures_and_pain_points.md`).

**Decision (2026-11-08, operator): capture a fixture and keep the adapter.**
The adapter, its deeplink and its registry row stay. The next step is a dated
capture attempt against the live endpoint (`scripts/capture_market_fixtures.py
--books evlbet`); if the feed still carries no 1/X/2 offer, the capture is
recorded as an empty-feed proof and the adapter stays disabled, which unblocks
`SR4-3g` only if markets exist. No fixture is invented and the book is not
enabled until a capture carries markets.

Options: capture a fixture and keep it, or remove the adapter and its config.

**SR6-3 Outcome (2026-11-08).** The capture was carried out and returned a
**dated empty-feed proof**, not a fixture: the flat offer endpoint answered
HTTP 200 with a 2-byte body `[]` for `SportIds=388` and `SportIds=1`, with and
without `Limit`/`Offset`
(`https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat`).
The adapter, deeplink and registry row stay as decided, still disabled; no
fixture is invented and the book is not enabled. Because no payload exists,
`SR4-3g` (strict wire schema) cannot be built from a capture and stays blocked
on a real EVLBet offer; it unblocks when a capture carries markets.

Acceptance:
- [x] Decision recorded and carried out (capture attempted, negative result
      recorded; the adapter is kept and stays disabled).

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

Status: Done

Gate: operator

**Decision (2026-11-08, operator): "start whichever you think is more
important" — this row is the pick.** Measured why: 16 of the 34 `/api` routes
had no auth dependency at all (`/results`, `/status`, `/config`, `/groups`,
`/debug/*`, `/bets`, `/paper/*`, `/link-sweeps`), so with the bootstrap
`API_KEY` set they served odds, config, bet history and CSV exports to anyone,
and a store holding only revoked named keys left them open — the strict xfail at
`tests/test_auth_keys.py`. The named-key path was also unusable next to a
bootstrap key: the middleware checked exactly `API_KEY`, so a valid named key
got 401 before `api_key_store.verify` ran.

Why / what: Redesign named-key authentication as one coherent change: a middleware
resolves the env `API_KEY` or a named key for every `/api` route except
`/api/health`, routes carry explicit read/write scopes, and the dashboard sends
the key on every fetch and download. Then remove the strict xfail in
`tests/test_auth_keys.py`.

The strict xfail at `tests/test_auth_keys.py:131` must stay until this is fixed;
do not delete it without fixing the gap, and do not turn it into a skip.

**M1-1 Outcome (2026-11-08).** `server/auth.py` gained
`resolve_api_key(presented, env_key=, store=) -> ResolvedKey | None`, the single
resolver the middleware and the route dependencies share; the env key is compared
with `hmac.compare_digest`, then the hashed store is tried, so a valid named key
now works beside a bootstrap `API_KEY` (before, the middleware compared only
`API_KEY` and answered 401 first). `server/app.py::api_key_guard` now resolves
either key for **every** `/api` route except `/api/health`, sets
`request.state.api_key_id`/`api_key_scopes`, returns 401 for no valid key and
403 for a `GET`/`HEAD` whose key lacks `read`/`admin`; with no bootstrap key and
no stored record the documented local-only mode stays open with every scope.
`server/api._require_api_key` reuses the middleware's result and only resolves on
its own when a route is exercised without the middleware. Seven write routes that
accepted any valid key (`/verify`, `/recalculate`, `/link-sweeps`, `/bets`,
`/bets/{id}/settle`, `/bets/{id}/closing`, `/paper/positions/{id}/settle`) now
require `scan`; `/verify-links` and `/scan` already did, and config
toggles/shutdown/key management/audit stay `admin`.
**The strict xfail is gone because the gap is fixed**: with a store holding only
revoked keys, `/api/results` answers 401 (suite xfailed count 1 → 0).
`tests/conftest.py` now gives every test a private `ApiKeyStore` under its runtime
tree, so the operator's `config/generated/api_keys.json` can no longer decide the
suite. `tests/test_api_key.py`, `tests/test_metrics.py`,
`tests/test_request_id.py` and `tests/test_security_headers.py` patch
`api.API_KEY` (the single owner) instead of the removed `server.app` binding.
New `tests/test_api_auth.py` (9 tests): every `/api` route enumerated from the
OpenAPI schema except health is 401 without a key (32 paths), health stays
public, a named key works beside a bootstrap key, a read key cannot write, a scan
key cannot read, local-only stays open, a revoked-only store closes the read
routes, and a near-miss bootstrap key is rejected. `docs/AUTH.md` documents the
enforcement and the updated scope matrix, `README.md` gained the scope table,
and `AGENTS.md` records that the tripwire is fixed rather than removed.

Acceptance (written before coding, 2026-11-08):
- [x] One `api_key_guard` middleware resolves the env `API_KEY` **or** a named
      key for every `/api/*` route except `/api/health`; no valid key is 401;
      `/api/health` stays public.
- [x] A valid named key is accepted while a bootstrap `API_KEY` is also
      configured (today it is rejected by the middleware).
- [x] The env key is compared with `hmac.compare_digest`.
- [x] Explicit scopes: every GET/HEAD request needs `read` or `admin`; the write
      routes that accepted any key (`/verify`, `/recalculate`, `/verify-links`,
      `/link-sweeps`, `/bets`, `/bets/{id}/settle`, `/bets/{id}/closing`,
      `/paper/positions/{id}/settle`) now require `scan`; config toggles,
      shutdown and key management stay `admin`.
- [x] With no bootstrap key and no stored key record (local-only, loopback) the
      API stays open exactly as documented, and the dependency and the
      middleware share one resolver so they cannot disagree.
- [x] The strict xfail is removed by fixing the gap, not deleted or skipped.
- [x] `tests/conftest.py` gives every test a private key store, so the
      operator's `config/generated/api_keys.json` can never decide the suite.
- [x] Tests: every `/api` route except health is 401 without a key; a named key
      works beside a bootstrap key; a read key cannot write; a scan key cannot
      read results; a revoked-only store closes the read routes; health stays
      public; local-only stays open. The dashboard's `apiFetch`/
      `downloadProtected` already send the key on every fetch and download
      (pinned by `tests/test_frontend_review.py`).
- [x] `README.md` documents the middleware, the scope matrix and the local-only
      mode.

### M1-2 Decide `accepted_odds: 0` with a stake

Status: Done

Gate: operator

**Decision (2026-11-08, operator: continue after M2-4; the pick announced after
M2-4 was this row): reject it with 422.** Measured from the code: the payload
validator documents `accepted_odds: 0` as the explicit "this leg was not placed"
sentinel "matching a zero accepted stake"; `BetStore.settle` treats *either*
zero as not placed, so bankroll, staked and profit stay correct; CLV already
skips a falsy accepted odds, so the pair cannot fake a -100 % CLV either. The
dashboard cannot produce the pair — "Mark placed" refuses odds below 1.01 and
sends both accepted fields from the same `placed` flag — so it can only arrive
from a hand-written client, where today a positive stake at a price that cannot
exist is silently neutralised: money the operator says the book accepted
disappears from P/L with no warning.

So: `accepted_stake > 0` with `accepted_odds == 0` is an impossible claim and is
refused at create with 422. The sentinel stays: both zero means not placed,
`null` still falls back to the planned value, and a row already stored with the
pair still settles as not placed (history is never rewritten).

Why / what: Decide whether `accepted_odds: 0` with a non-zero accepted stake
should be rejected (422) instead of treated as "not placed". The current settle
path treats either zero as not placed, so bankroll stays correct.

**M1-2 Outcome (2026-11-08).** `server/api.py::BetLegPayload` gained a
`model_validator(mode="after")` `_a_stake_needs_a_price`: a positive
`accepted_stake` with `accepted_odds == 0` is refused with 422, the detail names
both fields and says to record 0 for both when the leg was not placed, and no
row is written. The sentinel is unchanged: both zero still means "not placed",
`accepted_odds: null` still falls back to the planned price, and a zero stake
with a real price stays accepted (the price is known, no money is at stake).
`BetStore.settle` is untouched, so an already-stored inconsistent row still
settles as not placed — verified: the stored-row case yields `staked 0.0`,
`payout 0.0`, `profit 0.0` (nothing rejected, nothing rewritten). Four new tests
in `tests/test_bet_log.py`: the 422 and the empty store, the null-price fallback
still accepted, the zero-stake mirror still accepted and settling flat, and the
stored-row leniency. `docs/BET_LOG.md` documents the pair rule next to the P/L
formulas. `pytest`: 2310 passed, 12 skipped (17 snapshots) in 117.63 s; ruff
clean; mypy 275 source files clean; market doc in sync; refresh_fixtures and
audit_admissibility `--check` exit 0. No live scan, no bookmaker traffic.

Acceptance (written before coding, 2026-11-08):
- [x] `POST /api/bets` answers 422 for a leg with `accepted_stake > 0` and
      `accepted_odds == 0`, the message names both fields and says to use 0 for
      both when the leg was not placed, and no row is written.
- [x] The sentinel and the fallbacks still work: both zero is accepted as "not
      placed"; `accepted_odds: null` with a stake keeps the planned-odds
      fallback; `accepted_stake: 0` with a real odds is still accepted.
- [x] `BetStore.settle` still treats an already-stored inconsistent row as not
      placed, so existing data is neither rejected nor rewritten.
- [x] Tests pin each case through the API and through the store.
- [x] `docs/BET_LOG.md` documents the rule next to the P/L formulas.


### M1-3 Auth-failure rate limit and PBKDF2 cache

Status: Done

Gate: operator

**Decision (2026-11-08, operator: continue after the delegated M1-1 pick).**
M1-1 made `api_key_guard` resolve a key for every `/api` request, and a
successful named-key verification now costs one 200k-iteration PBKDF2 hash under
the store lock — measured **84.8 ms per request** on this host with one key and
with five. The dashboard polls a few routes every 30 s, so that is a quarter of a
second of blocking CPU per poll on the event loop, and it is paid again on every
request while the store is also rewritten for `last_used_at`. Nothing throttles
repeated wrong-key attempts, so an exposed deployment can be made to spend that
same PBKDF2 per request by anyone who can reach the port.

Why / what: Add an authentication-failure rate limit and avoid one PBKDF2
verification per request; invalidate any verification cache immediately on
revocation.

**M1-3 Outcome (2026-11-08).** `config/settings.py` gained
`AUTH_FAILURE_RATE_LIMIT` (default 10, `0` disables) and `AUTH_CACHE_SECONDS`
(default 60, `0` disables). `server/auth.py::ApiKeyStore.verify` now keeps a
bounded, in-memory cache of successful verifications keyed by `sha256(token)`
(the token is never held), with the key id and scope snapshot; a hit runs no
PBKDF2 and writes no file. `invalidate()` clears the cache on `create()` and
`revoke()`, so a revoked key answers 401 on its very next request inside the
TTL, a new key works at once, and a failure is never cached. Every hit also
compares the store file's mtime+size, so a hand edit or a second process is
noticed without a re-hash (the TTL only bounds a store that never changes).
`last_used_at` is persisted at most once per key per TTL instead of on every
request; with the cache disabled the old write-per-request remains. A
process-wide `FailureLimiter` (`auth.auth_failures`, counter per client address
in the shared `RATE_LIMIT_WINDOW_SECONDS`) is consulted by `api_key_guard`
**before** resolving, so `AUTH_FAILURE_RATE_LIMIT` failures then `429` with
`Retry-After` spend no PBKDF2; a success clears that address's counter and
`/api/health` is never throttled.
**Measured** on this host with 10 stored keys, 25 requests to `/api/results` per
mode: **83.47 → 3.33 ms per request** (25.1x, −80.1 ms) with
`AUTH_CACHE_SECONDS` 0 → 60; the PBKDF2 alone measured 84.75 ms per verify
before the change. New `tests/test_auth_limits.py` (14 tests) covers the cache
(hit spends no `_hash`, TTL expiry, `0` disables, revoke immediate, out-of-band
revoke seen, wrong token not cached, no store write on a hit) and the limiter
(N failures then 429 + `Retry-After`, success resets, `0` disables,
per-address isolation, sliding window, no PBKDF2 while blocked, public health).
`tests/conftest.py` resets the process-wide budget per test; the route-coverage
test resets it per request so the sweep still proves 401 rather than 429.
`README.md`, `.env.example` and `docs/AUTH.md` document both knobs.

Acceptance (written before coding, 2026-11-08):
- [x] `AUTH_FAILURE_RATE_LIMIT` (default 10 per the shared
      `RATE_LIMIT_WINDOW_SECONDS`, `0` disables): after that many failed attempts
      from one client address, further `/api` requests except `/api/health` get
      `429` with `Retry-After` **before** any PBKDF2 runs; a successful key clears
      that client's counter; health stays public.
- [x] `AUTH_CACHE_SECONDS` (default 60, `0` disables): a successful verification
      is cached in memory under `sha256(token)` — never the token itself — with
      the key's scope snapshot, so a hit spends no PBKDF2 and writes no file.
- [x] Revocation invalidates immediately: revoking a key drops every cached
      verification, so the revoked key answers 401 on its next request even
      inside the TTL. Creating a key is usable at once. A failed verification is
      never cached.
- [x] An out-of-band store edit (a hand-edit or a second process) is noticed
      inside the TTL through the store file's mtime+size stamp — one `stat`, not
      a re-hash — so the TTL is a bound, not a blind window.
- [x] `last_used_at` is persisted at most once per key per cache TTL instead of
      on every request.
- [x] Tests (`tests/test_auth_limits.py`): cache hit runs no `_hash`, TTL expiry,
      `0` disables the cache, revoke is immediate, out-of-band revoke is seen,
      a wrong token is not cached, writes are coalesced; limiter: N failures then
      429 + `Retry-After`, a success resets, `0` disables, per-client isolation,
      a blocked client spends no PBKDF2, health public.
- [x] `README.md`, `.env.example` and `docs/AUTH.md` document both knobs.


### M2 — Performance and availability (from the old maintenance backlog)

### M2-1 Move scan CPU/I/O off the event loop

Status: Done

Gate: operator

**Decision (2026-11-08, operator: continue after M1-3).** The scan's whole
analysis half runs on the event loop: from the end of the scrape phase through
`group_matches`, the stale/skin/feed-integrity checks, the candidate build, the
pricing pass and the JSON/SQLite writes, there is not one `await` that yields to
anything else, so a real scan blocked `/api/status` (and every dashboard poll)
for about 100 s. The scrape phase is already concurrent and non-blocking; this
row fixes the other half without touching the pipeline's logic or ordering.

Why / what: Move the scan's CPU/I/O stages off the event loop
(`asyncio.to_thread`): learning, `group_matches`, stale/skin/feed-integrity,
candidate CPU work and JSON/SQLite writes. A real scan blocked `/api/status` for
about 100 s.

**M2-1 Outcome (2026-11-08).** The scan's whole analysis half now runs in
worker threads. Added sync helpers called through `asyncio.to_thread`, in the
same order as before: `_finish_scan_cost` (report + history + save), 
`_evaluate_feed_diagnostics` (coverage, cardinality and mapping, each of which
walks every market), `learn_scan_mappings`, `MatchMatcher()` construction,
`group_matches`, `measure_price_agreement`, `apply_measured_twins`,
`get_match_report`, `evaluate_stale_prices`, `compute_feed_integrity`, the
candidate CPU build (split out of `_collect_candidates` as `_build_candidates`;
the AI ranking stays async on the loop), `find_surebets`,
`filter_price_outliers`, `capture_closing`, the paper `record_opportunities` /
`open_positions_from_scan` writes, `_summarize_pricing` (`summarize_scan` +
lifetimes), `_serialise_scan_caches` (the per-model `model_dump` of the served
payloads) and `_persist_scan_state` (`_save_cache`, opportunity metrics, feed
integrity, stale-price state, history, candidate trend, pairing summary). No
logic, input, output or ordering changed; `tests/test_e2e_certified.py`,
`test_metrics.py`, `test_record_only.py`, `test_scan_candidates.py`,
`test_auto_clv.py` and `test_health_cache.py` pass unchanged. A cancelled scan
can leave one worker finishing because a thread is not interruptible; every
stage it can orphan re-reads shared state at call time and writes idempotent
diagnostics, which `_persist_scan_state`'s docstring states.
**Measured** by `test_the_scan_analysis_runs_off_the_event_loop` (new): the same
3-match scan with `group_matches` stubbed to block 0.5 s held the event loop for
a **695.5 ms** heartbeat gap with `asyncio.to_thread` neutralised, and **15.4 ms**
with the offload — the other inline stages cost the remaining ~195 ms even on
this tiny scan. The test wraps nine heavy stages and asserts every one ran on a
non-main thread, so a future edit that drops an offload fails it. `pytest`:
2295 passed, 12 skipped (17 snapshots) in 115.41 s; ruff clean; mypy 275 source
files clean; market doc in sync; refresh_fixtures and audit_admissibility
`--check` exit 0. No live scan, no bookmaker traffic.

Acceptance (written before coding, 2026-11-08):
- [x] Every heavy post-scrape stage runs in a worker thread
      (`asyncio.to_thread`), sequentially in the same order as today:
      `MatchMatcher()` construction and `group_matches`, `learn_scan_mappings`,
      `measure_price_agreement` / `apply_measured_twins`,
      `get_match_report`, `evaluate_stale_prices`, `compute_feed_integrity`,
      the candidate CPU build (`_build_candidates`), `find_surebets`,
      `filter_price_outliers`, the closing-line capture and the paper/record
      writes, `summarize_scan` + lifetimes, the `model_dump` serialisation of
      the served caches, and `_save_cache` + the other JSON writes.
- [x] No stage's logic, inputs, outputs or ordering change: same groups, same
      surebets, same cache payload, same errors and alerts.
- [x] A blocking stage no longer blocks the loop: with `group_matches` stubbed
      to sleep, a heartbeat coroutine keeps its cadence (max gap well under the
      sleep) and every heavy stage is observed on a non-main thread.
- [x] A cancelled scan may let an in-flight worker finish; every stage it can
      orphan re-reads shared state at call time and writes idempotent
      diagnostics, so it cannot publish stale prices or resurrect a revoked
      result. Recorded in the outcome and in the code comment.
- [x] Existing scan tests (`tests/test_e2e_certified.py`,
      `tests/test_metrics.py`, `tests/test_record_only.py`,
      `tests/test_scan_candidates.py`, `tests/test_auto_clv.py`,
      `tests/test_health_cache.py`) pass unchanged, plus a new offload test.
- [x] The scan's analysis half yields between stages, proven with a measured
      `/api/status` latency during a stubbed scan written into the outcome.


### M2-2 Stop rewriting the cache on verify-links

Status: Done

Gate: operator

**Decision (2026-11-08, operator: continue after M2-1).** Every
`/api/verify-links` call ends in `_save_cache(mode)`, which serialises and
atomically rewrites the whole scan cache — 27 MB prematch / 3.6 MB live on the
operator's host, ~55 MB across a sweep — to persist at most a handful of
`deep_link_verified` flags. The verdict itself is already persisted in two small
stores (`deep_link_verifications.json`, `deep_link_decisions.json`), so the big
write buys only the cached copy of the flag, and it runs once per checked event.
The catch that makes it non-trivial: the cache file trusts its own flags on
restart, and `_apply_deep_link_verifications` only ever SETS one, so a failed
check (which removes the proof) would be resurrected by the next start unless the
load path re-derives the flag from the store.

Why / what: Stop rewriting the ~55 MB scan cache on every `/api/verify-links`
call; persist failed-check results without a full cache write.

**M2-2 Outcome (2026-11-08).** `verify_links` no longer calls `_save_cache`.
A completed check still applies `apply_report` and
`_apply_deep_link_verifications` to the in-memory `cached_matches`, so the
running server serves the new flags immediately; the verdict is durable in the
two small stores `_record_deep_link_outcomes` and `_record_deep_link_decisions`
already wrote. New `_clear_stale_deep_link_flags(matches, mode)` runs in
`_load_cache` before `_apply_deep_link_verifications`: a fresh proof is
re-applied, and a cached `deep_link_verified=True` that no fresh record backs is
cleared, so a restart cannot resurrect a link a completed check found dead. A
book the gate settles by declaration (verified route pattern, or no event route)
is unaffected. The one existing test that pinned the old asymmetry — the match
list keeping a stale `True` while the restored report dropped the group — now
asserts the flag is re-derived too (`mdshop` False, `mozzartbet` True); that is
strictly stronger, and the report filter still decides from the store.
**Measured** on this host with the operator's real cache files: `_save_cache`
cost **71.4 ms** on today's prematch cache (1.2 MB, 384 matches), **201.2 ms**
on the live cache (3.7 MB, 942 matches) and **1230.3 ms** on a 6,610-match
prematch cache (21.6 MB, the SR5-2 baseline shape and the size the row cites).
A check now performs **no cache write**; the two store writes for one outcome
measure **0.325 ms**. New tests: a completed check writes no cache yet persists
the proof and updates memory; a failed check removes the proof, records the
decision and clears the flag without a write; a restart with an emptied store
clears the cached flag. `pytest`: 2298 passed, 12 skipped (17 snapshots) in
116.27 s; ruff clean; mypy 275 source files clean; market doc in sync;
refresh_fixtures and audit_admissibility `--check` exit 0. No live scan, no
bookmaker traffic.

Acceptance (written before coding, 2026-11-08):
- [x] `/api/verify-links` no longer calls `_save_cache`; its completed verdicts
      are still persisted through `_record_deep_link_outcomes` (a proof is
      written or removed) and `_record_deep_link_decisions` (the event is
      decided), both small atomic writes.
- [x] The in-memory `cached_matches` still reflects the check immediately:
      `apply_report` clears a failed link and sets a proven one, so the running
      process serves the new state without waiting for a scan.
- [x] `_load_cache` re-derives the flag from the store instead of trusting the
      cached `deep_link_verified=True`: a fresh proof is re-applied, and a
      True that no fresh record backs is cleared. A book settled by its own
      declaration (verified route pattern, or no event route) keeps verifying,
      because the gate decides those without this flag.
- [x] A completed check that ran while a scan started still leaves the in-memory
      matches alone (`applied: false`) and still records the proof/decision.
- [x] Tests: a normal check writes no cache and persists the verdict; a failed
      check removes the proof and is not resurrected on restart; a fresh proof
      still survives a restart; the concurrent-scan test keeps its meaning.
- [x] Measured before → after on the operator's real cache files, and the
      numbers recorded in the outcome.


### M2-3 Serve a cached `/api/health` summary

Status: Done

Gate: operator

**Decision (2026-11-08, operator): cache the health summary.** Picked from the
gated queue as the next row.

Why / what: Serve a cached `/api/health` summary instead of recomputing freshness
and the candidate queue on every poll.

**M2-3 Outcome (2026-11-08).** `server/api.py::health()` is split in two:
`_health_summary()` builds the 31 measured blocks (parser contracts,
admissibility audit, retention, cache sizes, freshness, stale prices, feed
integrity, cardinality, mapping coverage/trends, scan cost, pairing, candidate
blockers/remediation/trends, the cached counters and the `unverified_links`
walk) and caches them for `HEALTH_CACHE_SECONDS` (new setting, env
`HEALTH_CACHE_SECONDS`, default 2.0 s, `0` disables); the endpoint adds the 18
live fields per request (scanning state, the cached surebet/match counters,
`book_health`, the breaker snapshots, `memory`, `alerts`, `ai_available`,
per-bookie errors and the deep-link declaration source/audit). The payload gains
`health_cache: {ttl_seconds, generated_at, age_seconds}`; no shipped key was
renamed or removed (pinned by `tests/test_health_cache.py`). `run_scan` drops
the cache when it starts and in its `finally`, so progress and a completed scan
are visible on the next poll, and `tests/conftest.py` drops it per test so one
test's scan data cannot answer another's diagnostics.
**Measured** with `health()` called directly in the same process: empty state
2.241 ms → 0.337 ms with the cache (85 % less); 6,600 prematch + 2,000 live
cached matches 20.32 ms → 0.33 ms (98 % less), the walk over the cached matches
being the dominant cost. Through `TestClient`, `/api/health` went from 5.74 ms
to 3.80 ms (the client's own overhead dominates there). Roughly 1.7 ms of the
empty-state cost was the three file-backed blocks (`admissibility_health`
0.98 ms, `retention_health` 0.46 ms, `contract_health` 0.22 ms). Health stays a
diagnostic: the certainty gate, feed integrity and pricing never read it.
New `tests/test_health_cache.py` (6 tests: hit does not rebuild, TTL expiry
rebuilds, `0` disables, live fields stay fresh, shipped key set unchanged, a
scan drops it). Two existing helpers that emulate a completed scan now drop the
cache before reading (`tests/test_frontend_empty_state.py`), and the one test
that changed the declaration map mid-test does the same
(`tests/test_candidates_api.py`), with the reason recorded there. `README.md`
and `.env.example` document the setting.

**M1-3 Outcome (2026-11-08).** `config/settings.py` gained
`AUTH_FAILURE_RATE_LIMIT` (default 10, `0` disables) and `AUTH_CACHE_SECONDS`
(default 60, `0` disables). `server/auth.py::ApiKeyStore.verify` now keeps a
bounded, in-memory cache of successful verifications keyed by `sha256(token)`
(the token is never held), with the key id and scope snapshot; a hit runs no
PBKDF2 and writes no file. `invalidate()` clears the cache on `create()` and
`revoke()`, so a revoked key answers 401 on its very next request inside the
TTL, a new key works at once, and a failure is never cached. Every hit also
compares the store file's mtime+size, so a hand edit or a second process is
noticed without a re-hash (the TTL only bounds a store that never changes).
`last_used_at` is persisted at most once per key per TTL instead of on every
request; with the cache disabled the old write-per-request remains. A
process-wide `FailureLimiter` (`auth.auth_failures`, counter per client address
in the shared `RATE_LIMIT_WINDOW_SECONDS`) is consulted by `api_key_guard`
**before** resolving, so `AUTH_FAILURE_RATE_LIMIT` failures then `429` with
`Retry-After` spend no PBKDF2; a success clears that address's counter and
`/api/health` is never throttled.
**Measured** on this host with 10 stored keys, 25 requests to `/api/results` per
mode: **83.47 → 3.33 ms per request** (25.1x, −80.1 ms) with
`AUTH_CACHE_SECONDS` 0 → 60; the PBKDF2 alone measured 84.75 ms per verify
before the change. New `tests/test_auth_limits.py` (14 tests) covers the cache
(hit spends no `_hash`, TTL expiry, `0` disables, revoke immediate, out-of-band
revoke seen, wrong token not cached, no store write on a hit) and the limiter
(N failures then 429 + `Retry-After`, success resets, `0` disables,
per-address isolation, sliding window, no PBKDF2 while blocked, public health).
`tests/conftest.py` resets the process-wide budget per test; the route-coverage
test resets it per request so the sweep still proves 401 rather than 429.
`README.md`, `.env.example` and `docs/AUTH.md` document both knobs.

Acceptance (written before coding, 2026-11-08):
- [x] Operator approval recorded here.
- [x] The expensive summary blocks are cached for `HEALTH_CACHE_SECONDS`
      (default 2.0 s, `0` disables): parser contracts, admissibility audit,
      retention, cache sizes, freshness, stale prices, unverified links,
      candidate blockers/remediation and the trends, mapping coverage, closing
      capture, skin detection, cardinality, feed integrity, pairing, scan cost
      and the cached counters that walk the scan data. Measured baseline:
      `admissibility_health` 0.98 ms + `retention_health` 0.46 ms +
      `contract_health` 0.22 ms of a 2.17 ms call, and the gate-facing
      `unverified_links` walk alone costs ~16 ms at 6,600 cached matches.
- [x] The live fields stay per request: `scanning`, the cached
      surebet/match counters, `book_health`, the breaker snapshots, `memory`,
      `alerts`, `ai_available`, per-bookie errors and the deep-link declaration
      fields (a test edits that file and re-reads health).
- [x] A scan start and a scan finish reset the cache, so progress and a
      completed scan are visible on the next poll.
- [x] The payload gains `health_cache: {ttl_seconds, generated_at,
      age_seconds}`; no existing key is renamed or removed, so `/api/health`
      stays a diagnostic and no pricing path reads it.
- [x] Measured before/after (`health()` called directly, same process state)
      pasted in the execution log.
- [x] Tests: a cache hit does not call the builders again, the TTL expiry
      rebuilds, `HEALTH_CACHE_SECONDS=0` always rebuilds, a live field changes
      between two cached calls, the key set is unchanged, a scan resets it, and
      the suite clears the cache between tests. `unverified_links` stays in the
      cached summary (its walk is the expensive part), so
      `tests/test_candidates_api.py` drops the cache explicitly before it reads
      the second count.

### M2-4 Decide the candidate queue cap

Status: Done

Gate: operator

**Decision (2026-11-08, operator: "Continue with M2-4, the candidate queue
cap"): cap the queue and report the denominator.** Measured from the operator's
own scan history (`cache/bh_arb.sqlite3`, 25 recorded scans): the prematch queue
reached **14,249** pairs (11,657 matches, 1,800 groups), median 5,855; the live
queue peaked at 766. Only **473** (3.3 % of the peak) were actionable, and the
queue is already ordered so the actionable ones come first. Cost of keeping all
of them, measured at 14,249 on this host: `/api/candidates` **8.9 ms** per poll
(it is sync on the event loop), health's candidate blocks **1.7 + 20.5 ms** per
summary rebuild, and **~19.8 MB** of candidate JSON (more as pydantic objects),
held until the next scan.

So: keep the queue capped at `CANDIDATE_QUEUE_MAX` (default **2,000**, `0`
disables) in the existing priority order — closeable, alias-actionable, fewest
human blockers, tightest kickoff, closest names, id — and never trim silently:
the found/retained/dropped numbers are reported everywhere the queue is
described.

Why / what: Decide whether to cap the candidate review queue (14k+ rows) and how
to report the denominator. Do not trim silently.

**M2-4 Outcome (2026-11-08).** `server/api.py` gained
`CANDIDATE_QUEUE_MAX` (env of the same name, default 2000, `0` disables) and
`CANDIDATE_TRIM_FACTOR` (4). `_build_candidates` counts every pair it finds,
bounds its transient list with `_pair_priority` (the same total order the final
cut uses, so the answer cannot change) and keeps the top N; it returns the
retained queue, the ordered pairs and the found/retained/dropped/cap plus
found-side actionable/closeable counts. `_collect_candidates` takes an optional
`stats` out-parameter, so its many test callers keep the plain queue. `run_scan`
stores the numbers in `candidate_totals[mode]`. `/api/candidates` now reports
`found`, `retained`, `dropped`, `cap`, `actionable_found`, `closeable_found`
beside the retained `total`/`actionable_total`/`closeable_total`; health serves
`candidate_queue.{prematch,live}`; the history row keeps `candidate_queue` as
the found count (so old and new rows stay comparable) and adds
`candidate_retained`; the blocker trend point carries `retained`/`dropped`/`cap`;
`bh_candidate_queue_size` is the retained queue and the new `bh_candidates_found`
gauge is the denominator (startup baseline included). The review tab states the
cap when it bites (`renderCandidates` takes `capInfo`), with the Bosnian string
in `frontend/js/i18n.js`.
**Measured** at the recorded peak of 14,249 found pairs: the same queue served
**7.8 → 2.8 ms** per `/api/candidates` poll and health's candidate blocks
**22.7 → 2.7 ms** (1.7 + 21.0 → 0.2 + 2.5), with the retained queue's JSON
footprint **~19.8 MB → ~2.8 MB**. New tests: the cap keeps the actionable pair
over a league-blocked one at cap 1, `0` disables, a mid-walk trim yields the same
retained ids, `/api/candidates` reports the denominator, health serves it, a
history row keeps the found count and names the retained one, the trend point
carries the cap, and the frontend note is pinned. `README.md` and
`.env.example` document the knob; `docs/METRICS.md` and
`docs/CANDIDATE_REMEDIATION.md` document the gauge and the cap. `pytest`: 2306
passed, 12 skipped (17 snapshots) in 118.23 s; ruff clean; mypy 275 source files
clean; market doc in sync; refresh_fixtures and audit_admissibility `--check`
exit 0. No live scan, no bookmaker traffic.

Acceptance (written before coding, 2026-11-08):
- [x] `CANDIDATE_QUEUE_MAX` (env, default 2000, `0` disables) keeps the top N by
      the existing priority order. The transient pair list is bounded during the
      walk too (trimmed to 4×N with the same total order), so the answer is
      unchanged and the peak does not grow to five figures.
- [x] `/api/candidates` reports `found` (the denominator), `retained`,
      `dropped` and `cap`; `total` stays the retained queue the page is drawn
      from; `actionable_found`/`closeable_found` report the found set alongside
      the retained `actionable_total`/`closeable_total`.
- [x] Health serves `candidate_queue.{prematch,live}` with
      found/retained/dropped/cap/actionable_found/closeable_found;
      `pending_candidates` stays the retained count.
- [x] History keeps `candidate_queue` as the found count (comparable with older
      rows) and `candidate_actionable` as the found-side actionable count; the
      blocker trend point gains `retained`, `dropped` and `cap`.
- [x] Metrics: `bh_candidate_queue_size` is the retained queue, new
      `bh_candidates_found` is the denominator; `docs/METRICS.md` updated.
- [x] The dashboard states the cap when it bites, localized, so a reviewer is
      never shown a trimmed queue as if it were complete.
- [x] Tests: cap applied in priority order, `0` disables, mid-walk trimming
      yields the same top N, and found/retained/dropped reach the endpoint,
      health, history and the trend; the frontend note is pinned.
- [x] Measured before → after poll/health cost at the peak queue size, in the
      outcome.


### M2-5 Review compact cache/ledger representations

Status: Done

Gate: operator

**Decision (2026-11-08, operator: continue after M1-2): keep every piece of
evidence, make the representation match the consumer.** Measured on the
operator's machine: `config/generated/mapping_evidence.json` is **93,981,475
bytes** (16,649 claims) and is written with `indent=2`, which puts it **over the
67.1 MB `MAPPING_LEDGER_BUDGET_BYTES`** for no benefit — every reader loads it
through `MappingLedger.load()` or `json.load`, and no consumer, script or test
reads the raw text or depends on line breaks. The cache files (`last_scan.json`,
`last_live_scan.json`), the diagnostics stores (`coverage_budget.json`,
`feed_integrity.json`, `scan_cost.json`, `stale_price_state.json`,
`opportunity_metrics.json`) and the SQLite rows are already compact; only the
ledger and the small human-inspectable decision/link-sweep files use indentation.
The ledger is a machine trust record, not hand-edited config, so it should be
compact like the scan cache (P0-1).

So: write the ledger with compact separators, keeping its schema, claim set,
evidence records, statuses, TTLs and prune rule byte-for-byte equivalent. Do not
delete claims or evidence and do not raise the budget to hide the size. Record
the per-representation consumer audit in `docs/STORAGE.md` so the next change
knows which reader owns what.

Why / what: Evaluate the compact cache/ledger representations against every
consumer; never delete runtime evidence to meet a budget.

**M2-5 Outcome (2026-11-08).** `engine/mapping_evidence.py::MappingLedger.save`
now writes compact JSON (`separators=(",", ":")`, `sort_keys=True`) instead of
`indent=2`; the schema, claim set, evidence records, statuses, TTLs and prune
rule are unchanged. This is a representation change, not retention: no claim or
evidence record is removed, `prune()` remains the only thing that drops evidence
and still runs only from the maintenance job. The audit of every persisted
representation and its consumers is in `docs/STORAGE.md`; the ledger was the
only indented runtime file, and every reader goes through `MappingLedger.load()`
or `json.load` (gate, learner, replay, league resolver's `detail["teams"]`,
candidate remediation/mapping coverage evidence types, the market-registry
script's last-evidence detail, maintenance prune and health bytes). Two tests in
`tests/test_mapping_evidence.py`: the file has no newline and is smaller than
its indented equivalent, and a nine-record claim survives save/load intact
(above the prune cap, proving save does not prune). **Measured on the operator's
real ledger (16,649 claims): 93,981,475 -> 50,054,456 bytes (-46.7 %), now under
`MAPPING_LEDGER_BUDGET_BYTES` (67.1 MB) without raising the budget or pruning;
load 1.83 -> 1.73 s, save 4.45 -> 4.01 s (best of runs, on a copy).**
`pytest`: 2312 passed, 12 skipped (17 snapshots) in 116.23 s; ruff clean; mypy
275 source files clean; market doc in sync; refresh_fixtures and
audit_admissibility `--check` exit 0. No live scan, no runtime state rewritten.

Acceptance (written before coding, 2026-11-08):
- [x] `MappingLedger.save()` writes compact JSON (no indentation), with the same
      schema, claim keys, evidence records and ordering as before.
- [x] A round trip through the compact file preserves every claim and every
      evidence record exactly; no evidence is deleted or capped by this change.
- [x] The operator's real ledger is measured before → after, and the compact
      file is under `MAPPING_LEDGER_BUDGET_BYTES` (67.1 MB) without pruning,
      raising the budget, or dropping a single claim.
- [x] Save/load time is measured before → after on the real ledger.
- [x] Every persisted representation and its consumers is audited in
      `docs/STORAGE.md`; the ledger is the only remaining indented runtime file,
      and each consumer reads through `json`/`MappingLedger`, never formatting.
- [x] Tests pin the compact form, the full evidence round trip, and that the
      prune/TTL behaviour is unchanged. The maintenance health bytes view still
      reports the ledger.
- [x] No prune rule, TTL, evidence cap or trust input changes.


---

### M3 — Architecture (from the old maintenance backlog)

### M3-1 Decompose `server/api.py`

Status: Done

Gate: operator

**Decision (2026-11-08, operator: continue after M2-5): take the three named
stages in order, each a behaviour-preserving extraction, and stop when the turn's
stage is green rather than half-migrating two at once.** `server/api.py` was
5,903 lines: routes, scan orchestration, caches, JSON stores and the pure pair
scoring all in one module. The stages are (1) pure candidate scoring, (2) a
`FeedState` object for `_state_for`, (3) the JSON-store layer. Scan and
deep-link semantics never change; each stage leaves the suite green.

Why / what: Decompose `server/api.py` in stages: pure candidate scoring, a
`FeedState` object for `_state_for`, then the JSON-store layer. Leave scan and
deep-link semantics untouched.

Acceptance (written before coding, 2026-11-08):
- [x] Stage 1: the pure scoring half (`TeamTokens`, `FoundPair`, kickoff/match
      keys, similarity, pair id, priority) lives in `server/candidate_scoring.py`
      with one definition. `server.api` imports it, no private copy remains, the
      module never imports `server.api`, and the queue tests/`audit_league_pairs`
      read the new module.
- [x] Stage 2: `_state_for` returns a `FeedState` NamedTuple
      (`status`, `surebets`, `matches`, `report`, `per_bookie`), route call sites
      read named fields instead of five anonymous values, and the pre-existing
      tuple unpacking in scripts/tests keeps working.
- [x] Stage 3: the JSON-store layer is extracted without touching scan or
      deep-link semantics.
- [x] Behaviour is unchanged: scores, ids, ordering, scan results and deep-link
      verdicts are the same before and after; the suite is green.

**Outcome (2026-11-08, all three stages).** `server/api.py` fell from **5,903
to 5,714 lines** across three behaviour-preserving extractions:

1. `server/candidate_scoring.py` (198 lines) owns the scoring helpers; api
   imports the one definition (no duplicate) and the module never imports
   `server.api`.
2. `FeedState` names the five values `_state_for` returned; route call sites
   read `state.report` / `state.matches` / `state.status`, and the NamedTuple
   keeps the old tuple unpacking in `scripts/record_scan.py` and the tests
   working. `server.mapping_coverage` accepts a `Sequence` so the typed match
   list stays assignable.
3. `server/json_store.py` (70 lines) owns the JSON-store layer:
   `atomic_write_json` (whole-document replacement through a temp file) and
   `read_json` (missing or malformed reads as `None`). Every JSON reader and
   writer in api uses it — toggles, allowlist, suppressed decisions, both
   deep-link stores, history export, the diagnostics stores, the scan cache and
   link sweeps — and `json`/`tempfile` are no longer imported by api. Validation,
   locks, TTL filtering and merge rules stay with each store's owner; no scan or
   deep-link behaviour changed.

`tests/test_candidate_scoring.py` pins the module boundary,
`tests/test_json_store.py` pins whole-file replacement (a failed write keeps the
old document and no temp file), the forgiving read and the compact form;
`tests/test_ci_hardening.py` and `tests/test_cache_serialization.py` follow the
moved call sites. Full suite **2,320 passed, 12 skipped** (17 snapshots) in
117.95 s (see the execution log).


### M3-2 Move the deep-link store to `engine/`

Status: Done

Gate: operator

**Decision (2026-11-09, operator: continue after M3-1): move the whole
declaration store, not a facade.** The store is a config reader with a cached
map, mtime-based reload, provenance and fail-safe parsing; it belongs beside the
gate that trusts it. Certainty currently imports it from `scrapers.common`,
which also imports `engine.market_registry` lazily, so `engine` and `scrapers`
depend on each other. Moving only certainty's import would leave `engine.matcher`
and `engine.arbitrage` importing `scrapers.common` for the pure Asian-handicap
label helpers, so the package cycle would remain. Those helpers are pricing
vocabulary, not scraper I/O, so they move to `engine/` too; `scrapers.common`
re-exports them for the adapters and tests that already import them there.

So: `engine/deeplinks.py` owns the declaration store, predicates, audit,
effective map and `build_event_url`; `engine/ah_labels.py` owns `ah_line_fmt`,
`ah_label`, `parse_ah_label` and `flip_ah_label`. `engine` imports no module
under `scrapers`; the reverse direction stays. Declaration semantics
(path resolution, fail-safe parse, mtime reload, synthetic-cache seam, TTLs) do
not change.

Why / what: Move the deep-link declaration store out of `scrapers/common.py` into
`engine/`, and remove the `engine` ↔ `scrapers` package cycle.

**Outcome (2026-11-09).** `engine/deeplinks.py` (317 lines) now owns the whole
declaration store: the path, cached map, mtime/size reload, provenance, the
`supports_event_id` / `declares_no_event_id` / `declares_route_pattern_verified`
predicates, `declaration_verified_at`, `declaration_audit`,
`effective_deeplink_declarations`, `deeplink_declaration_source` and
`build_event_url`, with the same fail-safe parse and injected-cache seam.
`engine/ah_labels.py` (49 lines) owns the four AH label helpers and
`scrapers.common` re-exports them for the adapters, so `scrapers/mbet.py` and
`sportplus.py` did not change. `scrapers/common.py` fell from **986 to 657
lines**. Certainty, the matcher and the arbitrage engine import from `engine`
only; a subprocess test proves importing `engine.certainty`, `engine.matcher`
and `engine.arbitrage` loads no `scrapers` module, and an AST test sees even a
function-level import. `server/api.py`, both deep-link scripts, the four
adapters and every test (including `conftest`'s cache-reset fixture) read the new
modules; no test patches a dead `scrapers.common` cache. `AGENTS.md` records the
new building blocks and the one-way dependency. Full suite **2,323 passed, 12
skipped** (17 snapshots) in 149.41 s. No declaration value, template, TTL or
trust rule changed.

Acceptance (written before coding, 2026-11-09):
- [x] `engine/deeplinks.py` owns the declaration file path, cache, reload and
      provenance, `supports_event_id` / `declares_no_event_id` /
      `declares_route_pattern_verified`, `declaration_verified_at`,
      `declaration_audit`, `effective_deeplink_declarations`,
      `deeplink_declaration_source` and `build_event_url`, with the same
      behaviour (fail-safe malformed file, mtime reload, injected-cache seam).
- [x] `engine/ah_labels.py` owns the four AH label helpers; `scrapers.common`
      re-exports them unchanged for adapters/tests.
- [x] No module under `engine/` imports any module under `scrapers/`, and a
      test pins that; importing `engine.certainty`, `engine.matcher` and
      `engine.arbitrage` loads no `scrapers` module.
- [x] `server/api.py`, both deep-link scripts and every test read the new
      modules; no test patches a dead `scrapers.common` cache.
- [x] The declaration/config tests and full suite pass with identical verdicts;
      no config file, declaration value or trust rule changes.


### M3-3 One link-settled predicate

Status: Done

Gate: operator

**Decision (2026-11-09, operator: continue after M3-2).** The gate and the
cache restore answer the same question — is this leg's per-event link settled?
— with two hand-written copies of the four cases. They can drift, and a drift
either restores a `verified` group whose link is not proven or refuses one the
gate would accept. `engine.deeplinks.settle_link()` becomes the one answer.

The predicate takes the case-1 proof as an explicit input, because the two
callers get it from different places and must not be papered over: during a scan
the gate reads the match's `deep_link_verified` flag (set from the store by
`_apply_deep_link_verifications`), while a cache restore reads the store itself
(by design — a cached flag is a snapshot that outlives its proof). Everything
else — the route-pattern proof, the declares-no-event-route case, and the two
open cases — is shared verbatim.

`_unverified_link_count` is the third copy of the same test; it moves too, so a
future edit to settlement cannot leave the dashboard counter behind.

Why / what: Share one link-settled predicate between `CertaintyGate` and cache
restore, with a parity test over every link case.

**Outcome (2026-11-09).** `engine.deeplinks.settle_link()` is now the one
link-settled predicate, returning `LinkSettlement(settled, reason)` and taking
the per-caller proof as an argument. `CertaintyGate._link_evidence` passes the
match's `deep_link_verified` flag; `_restorable_match_groups` passes a fresh store
record keyed `bookmaker|event_id` (never the cached flag); `_unverified_link_count`
passes the flag and keeps its existing scope (rows carrying an event id).
`engine/certainty.py` lost 99 hand-written branch lines and `server/api.py` no
longer imports the individual declaration predicates. `tests/test_link_settlement.py`
(31 tests) runs ten cases — proof, route pattern, declares-no-route (with and
without an id), declared-but-unproven (with and without a capture), silence with
an id, a URL and nothing, and a stale store proof — through the predicate, the
gate, the restore and the counter, and asserts all four agree; a named test pins
that a stale store proof cannot restore a `verified` group. Full suite **2,354
passed, 12 skipped** (17 snapshots) in 115.83 s; ruff and mypy (282 files) clean;
market doc, fixtures and admissibility checks green. No trust rule, declaration,
TTL or cache format changed.

Acceptance (written before coding, 2026-11-09):
- [x] `engine.deeplinks.settle_link()` returns `(settled, reason)` for the four
      gate cases, taking the per-caller proof as an argument.
- [x] `CertaintyGate._link_evidence` builds its `MatchEvidence` from the
      predicate with the same confidence and reason it used before.
- [x] `_restorable_match_groups` and `_unverified_link_count` call the predicate
      instead of repeating its cases.
- [x] A parity test covers every case (cached flag, fresh store proof, route
      pattern, declares-no-route, declared-unproven, silence with an id/url,
      silence with nothing) and asserts the gate's settled verdict, the restored
      row's fate and the counter agree.
- [x] No trust rule, declaration, TTL or cache format changes; the full suite
      passes with identical verdicts.


### M3-4 Unify datetime and SQLite helpers

Status: Done

Gate: operator

**Decision (2026-11-09, operator: continue after M3-3).** Two shared modules,
both under `server/` because they describe runtime state, not engine logic:

* `server/sqlite_store.py` owns the connection policy for the one shared
  `cache/bh_arb.sqlite3`. `Storage`, `BetStore`, `PaperStore` and the
  maintenance runner all spelled the connection out; all set WAL, but only
  `Storage` set `synchronous=NORMAL`, so the same file ran under two durability
  policies depending on which store opened it. The policy is **WAL +
  `synchronous=NORMAL`**, which `docs/STORAGE.md` already documents: durable
  across an application crash, not a power-loss guarantee, and appropriate for
  one scanner process whose data is reproducible from feeds. Read-only opens
  stay pragma-free so a dry run cannot change the file.
* `server/timeutil.py` owns the clock and the written timestamp shape: naive UTC
  from `utcnow()`, normalization from `naive_utc()`, second-precision strings
  from `iso_now()` / `iso_seconds()`. The duplicated `_now`, `_now_iso`, `_iso`
  and `_naive_utc` helpers and 41 inline `datetime.now(UTC).replace(...)`
  expressions in `server/` move onto it.

`engine/` keeps its own clock expressions: it is the pure package and must not
import `server`. This task is about the server runtime stores and their one
shared database, not about relocating the engine's timestamps.

Why / what: Unify the repeated datetime and SQLite connection helpers; decide one
`synchronous` policy for the shared database file.

**Outcome (2026-11-09).** `server/sqlite_store.py` (44 lines) is the one
connection path for `cache/bh_arb.sqlite3`: `connect()` sets WAL +
`synchronous=NORMAL`, `connect_readonly()` opens `mode=ro` without pragmas and
never creates the file. `Storage`, `BetStore`, `PaperStore` and maintenance
delegate to it, so the shared file no longer runs under FULL for two stores and
NORMAL for one. `server/timeutil.py` (40 lines) owns `utcnow()`, `naive_utc()`,
`iso_now()` and `iso_seconds()`; the `_now`/`_now_iso`/`_iso`/`_naive_utc`
copies are gone and **zero** `datetime.now(UTC).replace(tzinfo=None)` expressions
remain under `server/` outside the helper. Stored shapes are unchanged (naive
UTC, same precisions). `tests/test_storage_policy.py` (7 tests) pins WAL +
NORMAL for all three stores, proves a read-only open neither creates the file
nor writes, checks the clock/normalization helpers, and round-trips a bet and a
meta row through the shared file. `docs/STORAGE.md` and `AGENTS.md` name the
shared helpers. Full suite **2,361 passed, 12 skipped** (17 snapshots) in
113.89 s; ruff and mypy (285 files) clean; market doc, fixtures and admissibility
checks green.

Acceptance (written before coding, 2026-11-09):
- [x] `server/sqlite_store.connect()` is the only read-write connection path for
      the shared database and sets WAL + `synchronous=NORMAL`;
      `connect_readonly()` never creates or mutates the file.
- [x] `Storage`, `BetStore`, `PaperStore` and maintenance open the database
      through it, and a test pins the pragmas for every store.
- [x] `server/timeutil` provides `utcnow`, `naive_utc`, `iso_now` and
      `iso_seconds`; the `_now`/`_now_iso`/`_iso`/`_naive_utc` copies are gone
      and no server module hand-writes naive-UTC `now`.
- [x] Stored timestamp shapes and precisions are unchanged; a bet and a paper
      row still parse as naive UTC.
- [x] `docs/STORAGE.md` and `AGENTS.md` name the shared helpers; the full suite,
      ruff, mypy and the generated/fixture/admissibility checks pass.


### M3-5 Route registry lookups through `registered_spec()`

Status: Done

Gate: operator

**Decision (2026-11-09, operator: continue after M3-4).** The registry had two
problems, and both come from importing the singleton by name:

* `scrapers/wwin.py`, `scrapers/maxbet.py`, `scrapers/mbet.py`,
  `scrapers/evlbet.py`, `scrapers/mozzartbet.py`,
  `engine/admissibility.py` and `scripts/capture_market_fixtures.py` did
  `from engine.market_registry import MARKET_REGISTRY` and then called methods on
  their own binding. That binding is captured at import time, so the test seam
  that replaces `engine.market_registry.MARKET_REGISTRY` never reached those
  modules; the fake sat unused while the parser queried the real registry.
* The lookups that only need a spec repeated the unmapped-recording logic or
  skipped it, so a parser could be silent about an unknown ID.

So `engine/market_registry.py` gains module-level accessors — `registry()`,
`has_source_id()`, `specs_for()`, `lookup_type()` and `ids_for()` — that read the
singleton at call time; `registered_spec()` keeps its unmapped-recording
behaviour and now resolves through `registry()` too. Every caller moves onto
them; no module outside `engine/market_registry.py` names `MARKET_REGISTRY`.
`mbet`, `mozzartbet` and the fixture capture use `lookup_type()` rather than
`registered_spec()` where they previously did a raw lookup without recording an
unmapped ID, so diagnostics do not gain new entries from this refactor.

The test seam stays "replace the module global"; the difference is that the
global is now the object every lookup resolves, not one of several import-time
copies. A test replaces it after the adapter modules are imported and asserts
that nsoft, mbet, mozzartbet, wwin, maxbet and admissibility all follow it.

Why / what: Route the remaining direct `MARKET_REGISTRY` lookups through
`registered_spec()` (or an accessor) and make the registry test seam patch the
object, not only the module global.

**Outcome (2026-11-09).** `engine/market_registry.py` now exposes
`registry()`, `has_source_id()`, `specs_for()`, `lookup_type()` and `ids_for()`,
all resolving `MARKET_REGISTRY` at call time; `registered_spec()` uses the same
resolution and keeps the `has_source_id` fallback. Every direct singleton import
moved: `engine/admissibility.py`, `scrapers/{wwin,maxbet,mbet,evlbet,mozzartbet}.py`,
`scrapers/common._nsoft_registry` and `scripts/capture_market_fixtures.py`.
**Zero** modules outside `engine/market_registry.py` name `MARKET_REGISTRY` any
more. `mbet`, `mozzartbet` and the capture script use the raw `lookup_type()`
accessor where they previously looked up without recording unmapped IDs, so
diagnostics did not gain entries. Two tests were added to
`tests/test_market_registry.py`: one checks every accessor follows a replaced
global, and one replaces the registry *after* the adapters are imported and
proves `common.parse_nsoft_bets`, `mbet`, `mozzartbet`, `wwin`, `maxbet` and
admissibility all see the fake — the seam that used to miss import-time copies.
Full suite **2,363 passed, 12 skipped** (17 snapshots) in 112.94 s; ruff and
mypy (285 files) clean; market doc, fixture and admissibility checks green. No
registry row, mapping or parser verdict changed.

Acceptance (written before coding, 2026-11-09):
- [x] `engine.market_registry` exposes `registry()`, `has_source_id()`,
      `specs_for()`, `lookup_type()` and `ids_for()`, each resolving
      `MARKET_REGISTRY` at call time.
- [x] `registered_spec()` uses the same resolution and keeps its
      `has_source_id` fallback for fakes that lack it.
- [x] No module outside `engine/market_registry.py` imports or calls
      `MARKET_REGISTRY`.
- [x] A test replaces `MARKET_REGISTRY` after the adapter modules load and
      proves nsoft/common, mbet, mozzartbet, wwin, maxbet and admissibility all
      use the replacement.
- [x] No registry row, market mapping, unmapped-recording behaviour or parser
      verdict changes; the full suite and generated-doc check pass.


### M3-6 Move `pairing_audit` and verifier into `server/`

Status: Done

Gate: operator

**Decision (2026-11-09, operator: continue after M3-5).** Coverage's `source`
is `engine`, `server`, `scrapers`, `config` and `models`, so the pairing audit
and the deep-link verifier were exercised by tests but invisible to the coverage
floor. Worse, the running application imported them *from* `scripts`:
`server/api.py` called `scripts.pairing_audit.audit` and lazily imported
`scripts.verify_deeplinks` for `/api/verify-links`. The reusable logic moves,
the command lines stay:

* `server/pairing_audit.py` owns the measurement helpers and `audit()`;
  `scripts/pairing_audit.py` keeps `main()` and re-exports `audit` and
  `DEFAULT_MAX_MISS_RATE` for existing importers.
* `server/deeplink_verifier.py` owns the criterion, dataclasses, evidence
  parsing, `build_targets`, `apply_report`, `check_target` and
  `verify_bookmaker`; `scripts/verify_deeplinks.py` keeps `_load_cached_matches`
  and `main()` and re-exports the names tests and callers already import.
* `server/api.py` imports from the `server` modules, so the app no longer
  depends on `scripts`.

Behaviour, prompts, criterion text, CLI flags and report shapes do not change.
The one test that read the verifier source to keep the README's cursor claim
honest now reads `server/deeplink_verifier.py`.

Why / what: Move `scripts/pairing_audit.audit` and the reusable deep-link
verifier into `server/` so coverage measures them.

**Outcome (2026-11-09).** `server/pairing_audit.py` (234 lines) now owns the
strict-miss measurement and `audit()`; `scripts/pairing_audit.py` is a 48-line
CLI wrapper that re-exports `audit` and `DEFAULT_MAX_MISS_RATE`.
`server/deeplink_verifier.py` (585 lines) owns the criterion, dataclasses,
evidence parsers, target builder, `check_target` and `verify_bookmaker`;
`scripts/verify_deeplinks.py` is a 109-line wrapper that keeps
`_load_cached_matches`/`main` and re-exports the public names. `server/api.py`
imports both from `server`, so the app no longer depends on an unmeasured
directory. `tests/test_layering.py` now pins that no `server` module imports
`scripts`, that the implementations live under `server`, and that the wrappers
keep their public names; the README-claims test that read the verifier source
reads the new module. CLI flags, report shapes, criterion text and verdicts are
unchanged: `python scripts/pairing_audit.py --check` exits 0 on the shipped
cache. Full suite **2,366 passed, 12 skipped** (17 snapshots) in 113.32 s; ruff
and mypy (287 files) clean; market doc, fixtures and admissibility checks green.

Acceptance (written before coding, 2026-11-09):
- [x] `server/pairing_audit.py` owns `audit()` and the measurement helpers;
      `scripts/pairing_audit.py` is a CLI wrapper that re-exports them.
- [x] `server/deeplink_verifier.py` owns the reusable verifier;
      `scripts/verify_deeplinks.py` keeps only the CLI loader/report/storage and
      re-exports the public names.
- [x] `server/api.py` imports both from `server`, and no `server` module imports
      `scripts` (pinned by a test).
- [x] CLI flags, printed report shapes, criterion text and verdicts are
      unchanged; the existing tests pass through the wrappers.
- [x] The full suite, coverage source list, ruff, mypy and the doc/fixture checks
      pass.


---

### M4 — Supply chain and CI (from the old maintenance backlog)

### M4-1 Add a resolved constraints/lock file

Status: Done

Gate: operator

**Decision (2026-11-09, operator: continue with the next three).** Two lock
files, generated by one script, installed by everything that builds or tests:

* `requirements.lock` — the runtime resolution of `requirements.txt` (27
  packages today, transitives included, `pip`/`setuptools`/`wheel` excluded).
* `requirements-dev.lock` — the same environment after `requirements-dev.txt`,
  so CI's tools and the runtime pins cannot disagree.

`scripts/lock_requirements.py` resolves both in one clean temporary venv and
writes sorted exact pins with a generated-file header; `--check` re-resolves and
diffs for a human. CI does not run `--check` because it needs network and can
move when a transitive releases; instead `tests/test_dependency_lock.py` proves
offline that every direct manifest pin is carried at the same version, that the
dev lock contains the runtime set unchanged, that locks are sorted and fully
pinned, and that Docker/CI/SBOM install the lock. A Dependabot manifest PR
therefore fails until the lock is regenerated.

The Docker image, every CI install step, the SBOM resolution and the release
workflow switch to the locks. `pip-audit` now audits the resolved locks, so
transitive advisories are in scope. `requirements.txt`/`requirements-dev.txt`
stay as the human-edited manifests.

Why / what: Add a resolved constraints/lock file and install Docker/CI/SBOM from
it.

**Outcome (2026-11-09).** `requirements.lock` (27 runtime packages) and
`requirements-dev.lock` (85 packages) are the resolved sets, sorted exact pins
with `pip`/`setuptools`/`wheel` excluded. `scripts/lock_requirements.py` resolves
both in one clean temp venv, regenerates them and supports `--check`;
`--check` reported "dependency locks are in sync". The Dockerfile installs
`requirements.lock`; every CI install, the release workflow and the Docker smoke
trigger use the locks; `pip-audit` audits both locks (transitives included); the
SBOM installs `requirements.lock` in its clean venv. `tests/test_dependency_lock.py`
(6 tests) proves manifest/lock agreement, the dev superset with unchanged
runtime pins, sorted exact pins, the resolved transitives, and that Docker/CI/
SBOM install the locks. README, `docs/CI.md` and `docs/RELEASE.md` describe
regeneration and the CI-safe check. Full suite **2,372 passed, 12 skipped** (17
snapshots) in 105.03 s; ruff and mypy (289 files) clean; market doc, fixtures and
admissibility checks green.

Acceptance (written before coding, 2026-11-09):
- [x] Operator approval recorded here.
- [x] Acceptance criteria written here before coding.
- [x] `requirements.lock` and `requirements-dev.lock` contain the resolved sets
      as sorted exact pins, with no bootstrapper packages.
- [x] `scripts/lock_requirements.py` regenerates both; `--check` reports drift.
- [x] `tests/test_dependency_lock.py` proves manifest/lock agreement, the dev
      superset, exact/sorted pins, resolved transitives and lock installation in
      Docker/CI/SBOM.
- [x] Dockerfile, `ci.yml`, `release.yml`, `browser.yml`, `docker.yml` paths,
      `pip-audit` and the SBOM use the locks; README/release/CI docs match.
- [x] Full suite, ruff, mypy and the doc/fixture checks pass.


### M4-2 Docker Chromium check and image CVE scan

Status: Done

Gate: operator

**Decision (2026-11-09, operator: next three).** The Docker smoke proved the
server starts but never proved the browser layer works, and nothing scanned the
image for OS or library CVEs. A Playwright bump or a missing system library could
pass every build and fail the first browser-book scan. So:

* `scripts/docker_smoke.py` launches the bundled Chromium headless inside the
  running container with the same `--no-sandbox`/`--disable-dev-shm-usage` flags
  `launch_browser()` uses, and fails unless the page title round-trips.
* `docker.yml` scans the loaded image with Trivy (`os,library`),
  `HIGH,CRITICAL`, `ignore-unfixed: true`, `exit-code: 1`. A fixable HIGH or
  CRITICAL CVE fails the Docker job; an unfixed one is reported but does not
  block, because the base image has no remedy to apply.
* `release.yml` runs the same scan against `bh-arb:release`, so a release cannot
  ship an image the Docker job would refuse.

Trivy is pinned by commit SHA now (M4-3 covers the rest), and the Dependabot
`docker` ecosystem keeps the base image moving.

Why / what: Add a Docker Chromium launch check and an OS/image CVE scan.

**Outcome (2026-11-09).** `scripts/docker_smoke.py` now launches the image's
bundled Chromium headless as the non-root runtime user (same `--no-sandbox` and
`--disable-dev-shm-usage` flags the scanners use) and fails unless a page title
round-trips. `docker.yml` scans the loaded `bh-arb:ci` image with Trivy
(`aquasecurity/trivy-action` pinned by SHA): `vuln-type: os,library`,
`severity: HIGH,CRITICAL`, `ignore-unfixed: true`, `exit-code: "1"`;
`release.yml` runs the same scan against `bh-arb:release`. Two tests in
`tests/test_deployment_assets.py` pin the probe and the scan policy.
`docs/CI.md` documents both. Full suite **2,374 passed, 12 skipped** (17
snapshots) in 113.54 s; ruff and mypy (289 files) clean; market doc, fixtures and
admissibility checks green. The image build/scan itself runs in the path-
triggered Docker workflow, not locally.

Acceptance (written before coding, 2026-11-09):
- [x] Operator approval recorded here.
- [x] Acceptance criteria written here before coding.
- [x] `scripts/docker_smoke.py` launches Chromium and fails when it cannot.
- [x] `docker.yml` and `release.yml` scan the built image for fixable HIGH and
      CRITICAL OS/library CVEs and fail the job.
- [x] `tests/test_deployment_assets.py` pins the probe and the scan policy, and
      the smoke test's docstring/pass line name the new check.
- [x] Docker/CI docs describe both; the full suite and checks pass.


### M4-3 Pin Actions by SHA and base image by digest

Status: Done

Gate: operator

**Decision (2026-11-09, operator: next three).** A moving `@v4` tag and a bare
`python:3.11-slim` tag are both mutable supply-chain inputs. Every `uses:` now
names a 40-character commit SHA with the release in a comment, and the base image
is `python:3.11-slim@sha256:<digest>`. The version comment is not decoration:
Dependabot's `github-actions` ecosystem reads it and rewrites the SHA and comment
together; the existing `docker` ecosystem advances the digest. No moving tag is
left to restore.

`tests/test_workflow_pins.py` runs offline: every `uses:` must match
`owner/repo@<sha>  # vX.Y.Z`, every `FROM` must carry a 64-hex `@sha256:` digest,
and Dependabot must keep the `github-actions` and `docker` ecosystems. A future
unpinned action or base image fails CI.

Why / what: Pin GitHub Actions to commit SHAs and the base image to a digest;
keep Dependabot able to update both.

**Outcome (2026-11-09).** All six action references (checkout v4.4.0,
setup-python v5.6.0, setup-node v4.4.0, upload-artifact v4.6.2,
setup-buildx-action v3.12.0, build-push-action v6.19.2) and Trivy (v0.36.0) are
pinned to 40-character commit SHAs with version comments; the Dockerfile is
`python:3.11-slim@sha256:07d48240…b535`. `tests/test_workflow_pins.py` (3 tests)
fails on a moving tag, a bare `FROM`, or a Dependabot config missing the
`github-actions`/`docker` ecosystems. `dependabot.yml`, `docs/CI.md` and
`docs/RELEASE.md` state that the existing ecosystems rewrite the SHA + version
comment and advance the digest, so no moving tag needs restoring. Full suite
**2,377 passed, 12 skipped** (17 snapshots) in 113.10 s; ruff and mypy (290
files) clean; market doc, fixtures and admissibility checks green.

Acceptance (written before coding, 2026-11-09):
- [x] Operator approval recorded here.
- [x] Acceptance criteria written here before coding.
- [x] Every `uses:` in `.github/workflows/` is a commit SHA with a version
      comment; no moving tag remains.
- [x] The Dockerfile `FROM` is tag + `@sha256:` digest.
- [x] Dependabot keeps the `github-actions` and `docker` ecosystems and the
      config states how the SHA/comment and digest are updated.
- [x] `tests/test_workflow_pins.py` pins both rules offline.
- [x] Docs describe the update path; the full suite and checks pass.


### M4-4 Plan the remaining dependency upgrades

Status: Done

Gate: operator

**Decision (2026-11-09, operator: finish every planned objective, skip the
ones that need input).** The row is a plan, not the upgrade itself, so it is
finished here: `docs/DEPENDENCY_UPGRADES.md` records four separate changes, each
with its own steps, acceptance and rollback. The upgrades stay separate commits
so a failure cannot hide behind another pin move.

**Measured dry run (throwaway venv, `/tmp/opencode/m44-venv`).**
`requirements-dev.lock`, then `fastapi==0.162.2`, `starlette==1.10.0`,
`mypy==2.4.1`, `ruff==0.17.4` and `httpx2==2.16.0`:

* full suite green — 2,389 tests collected, exit 0, 17 snapshots, 1 m 50 s, no
  test or fixture change;
* mypy 2.4.1 — one error, `scripts/refresh_fixtures.py:212`, an inferred
  `dict[str, bool | dict]` receiving integer report fields;
* ruff 0.17.4 — three `UP042` findings for `MarketType`, `Sport` and
  `ScrapeKind` inheriting `str, Enum`; no other rule fired;
* `httpx2` — the current `fastapi.testclient` import raises
  `StarletteDeprecationWarning: Using 'httpx' with 'starlette.testclient' is
  deprecated; install 'httpx2' instead`; with `httpx2` installed Starlette
  resolves it and the warning is gone.

Plan: U4 `httpx2` (dev-only), U1 FastAPI 0.162.2 (Starlette already 1.10.0),
U2 MyPy 2.4.1 (one annotation), U3 Ruff 0.17.4 (`StrEnum`, with JSON/label
assertions because it changes direct `str(member)` text). Pydantic and Uvicorn
newer releases are left to their Dependabot groups, not this row.

Why / what: Plan the separate upgrades for FastAPI/Starlette, MyPy 2.x and
Ruff 0.17; evaluate the `httpx2` TestClient migration. (The Playwright 1.64
upgrade from the same old TODO item is tracked by SR3-1.)

Acceptance (2026-11-09, recorded before any dependency pin moves):
- [x] Operator approval recorded here (the "finish every planned objective"
      instruction; no dependency pin was moved by this row).
- [x] `docs/DEPENDENCY_UPGRADES.md` names each upgrade with its current and
      target version.
- [x] Each upgrade has steps, measurable acceptance criteria and a rollback.
- [x] The dry run records the suite, mypy and ruff results and the `httpx2`
      deprecation evidence.
- [x] The plan keeps `httpx` runtime, adds `httpx2` dev-only, and leaves the
      trust rules, data formats and `requirements.lock` untouched.
- [x] Full suite, ruff, mypy and the doc/fixture checks pass with no code change.


### M4-5 Apply the planned dependency upgrades

Status: Done

Gate: operator

**Decision (2026-11-11, operator: continue).** `docs/DEPENDENCY_UPGRADES.md`
defines four separate moves; this row executes them, one commit each, in the
planned order: dev-only `httpx2`, FastAPI 0.162.2, MyPy 2.4.1, Ruff 0.17.4.
No trust rule, data format, cache key, metric label or price source changes.

Why / what: execute the M4-4 plan so the measured dry run becomes the installed
dependency set.

**Outcome (2026-11-11).** All four moves were applied as separate commits.
`httpx2==2.16.0` is dev-only (runtime lock still carries `httpx==0.28.1`), and
`starlette.testclient` resolves it with the deprecation warning gone. FastAPI is
0.162.2 with Starlette still 1.10.0 and no application or test edit. MyPy is
2.4.1 after annotating the `refresh_fixtures.py` report dict. Ruff is 0.17.4,
with `MarketType`, `Sport` and `ScrapeKind` as `StrEnum`; no rule was ignored.
`tests/test_dependency_lock.py` gained 2 tests (httpx2 stays out of the runtime
lock; TestClient resolves it) and `tests/test_enum_values.py` has 3 tests pinning
the enum value strings through str(), f-strings, Pydantic and JSON. Full suite
**2,382 passed, 12 skipped** (17 snapshots) in 108.71 s with no warning line;
ruff clean; mypy 291 files clean; market doc, fixtures, admissibility and the lock
check green.

Acceptance:
- [x] `requirements-dev.txt` adds `httpx2==2.16.0`, the dev lock carries it, the
      runtime lock does not, `TestClient` resolves it, and the deprecation
      warning is gone.
- [x] `requirements.txt` pins `fastapi==0.162.2`, Starlette stays `1.10.0`, and
      the suite is green with no application or test edit.
- [x] MyPy 2.4.1 is pinned; `scripts/refresh_fixtures.py` annotates its report
      dict; mypy is clean on every file with no new ignore or loosened setting.
- [x] Ruff 0.17.4 is pinned; `MarketType`, `Sport` and `ScrapeKind` are
      `StrEnum`; API JSON, metric labels and canary text are asserted unchanged;
      ruff is clean under the same rule selection.
- [x] Each upgrade is its own commit; the full suite and the doc/fixture checks
      pass once at the end of the row.

---

### M5 — Product and configuration decisions (from the old maintenance backlog)

### M5-1 Remove legacy URL maps

Status: Done

Gate: operator

**Decision (2026-11-11, operator: continue with M5): remove.** The compatibility
window is over: no frontend or server reader uses `Surebet.match_urls` or
`Surebet.bet_urls` (`tests/test_destinations.py` already asserts the dashboard
never reads `sb.bet_urls`), `Match.bet_url` is never populated by an adapter, and
`SurebetStake.destination` is the supported per-leg destination path. Keeping
three parallel URL shapes invites a future consumer to trust the unverified one.

Removing `Surebet.match_urls`/`bet_urls`, `Match.bet_url`, `MATCH_URL_TEMPLATES`
and the two `_collect_*` helpers shrinks every results payload and leaves
`Match.url` (the scraped event page, still used by adapters and tests) alone.

Why / what: Remove or deprecate `Surebet.match_urls`, `Surebet.bet_urls`,
`Match.bet_url` and `MATCH_URL_TEMPLATES` after a documented compatibility
window. `SurebetStake.destination` is the supported path.

**Outcome (2026-11-11).** Removed `Surebet.match_urls`, `Surebet.bet_urls`,
`Match.bet_url`, `MATCH_URL_TEMPLATES` and the two `_collect_*` helpers. Served
results and caches no longer carry the three fields; `Match.url` (the scraped
event page) stays. `SurebetStake.destination` is the only destination path, and
`test_destinations` still proves the dashboard never reads `sb.bet_urls`.
`tests/test_urls.py` now covers only the two parser-built match URLs.

Acceptance (2026-11-11):
- [x] The four legacy symbols and the two collectors are gone; no result,
      cache or API payload carries `match_urls`/`bet_urls`/`bet_url`.
- [x] `SurebetStake.destination` is the only served destination path and the
      dashboard still reads it.
- [x] Tests citing the removed collectors are removed or rewritten; the full
      suite and checks pass.

### M5-2 Decide the `link_sweeps` table

Status: Done

Gate: operator

**Decision (2026-11-11, operator: continue with M5): remove.** The sweep report
has one live store, `cache/link_sweeps.json`, which `POST /api/link-sweeps`
writes and `GET /api/link-sweeps` reads; it is capped at 200 reports. The SQLite
`link_sweeps` table has no writer in the app — only `Storage.append_link_sweep()`
and its tests — so wiring it would create a second history with a second
retention rule. Remove the table from the schema, the method, the retention
entry and the maintenance inventory, and keep the JSON store.

Why / what: Decide the `link_sweeps` SQLite table: wire `append_link_sweep()`
into `POST /api/link-sweeps`, or remove the table/method/retention entry and
correct `docs/STORAGE.md`.

**Outcome (2026-11-11).** Removed the SQLite `link_sweeps` table from the
schema, `Storage.append_link_sweep()`/`prune_link_sweeps()`, the `counts()` key,
the maintenance inventory/prune step, the `link_sweeps_days` window and
`RETENTION_LINK_SWEEPS_DAYS`. `cache/link_sweeps.json` (capped at 200) stays the
one sweep history for `GET /api/link-sweeps`; `docs/STORAGE.md` records the
removal. Maintenance and migration tests were updated.

Acceptance (2026-11-11):
- [x] `Storage.initialize()` no longer creates `link_sweeps`; the append/prune
      methods and the `counts()` key are gone.
- [x] `server/maintenance.py` no longer inventories or prunes the table and the
      retention report drops `link_sweeps_days`; `RETENTION_LINK_SWEEPS_DAYS` is
      removed from settings.
- [x] Maintenance and migration tests are updated; the JSON sweep store and its
      API tests are unchanged.
- [x] `docs/STORAGE.md` and the full suite/checks agree.

### M5-3 Decide approve/reject functions

Status: In progress

Gate: operator

**Decision (2026-11-11, operator: continue with M5): delete.** The two functions
had no route (`POST /api/candidates/{id}/approve|reject` is asserted absent), the
dashboard has no approve/reject control, and the project already records the
evidence ledger as the only trust source with Diagnostics read-only. Restoring
them behind `HUMAN_MAPPING_ENABLED` would reopen a retired human path that grants
team aliases; deleting removes the flag, the in-memory decision log, the runtime
allowlist writer and the stale documentation instead.

The suppression reader stays: it honours candidate decisions an older build wrote
to `cache/suppressed_candidates.json`, so those pairs are not re-queued. Only the
writer to that store remains (`_suppress_candidate`, now used by imported/legacy
data and tests), with no HTTP or human entry point.

Why / what: Decide the unreachable candidate approve/reject functions: restore
them behind `HUMAN_MAPPING_ENABLED` with a review, or delete them and the stale
documentation.

Acceptance (2026-11-11):
- [ ] `approve_candidate`, `reject_candidate`, `_approve`, `_approval_blockers`,
      `_resolve_candidate`, `HUMAN_MAPPING_ENABLED`, `candidate_reviews`,
      `CANDIDATE_REVIEW_HISTORY_MAX` and the runtime allowlist writer are gone.
- [ ] The candidates payload drops `human_mapping_enabled`; the suppression
      reader still loads and honours old decisions.
- [ ] Tests for the removed path are deleted; suppression tests drive
      `_suppress_candidate` directly; the 404 route-absence tests stay.
- [ ] `docs/CANDIDATE_REMEDIATION.md` matches; the full suite and checks pass.

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
| 2026-11-08 | SR4-1 | Done | New `tests/test_transport_adapters.py` (37 tests) with `respx==0.22.0` (dev-only pin in `requirements-dev.txt`). Each case re-inserts the captured payload into the response envelope the adapter actually requests and runs the real `scrape()`: mdshop, mbet, maxbet, sportplus, betole and premier_kladionica are asserted against their fixture's declared market families, so a changed URL, query key or envelope now fails. EVLBet is covered at the transport boundary with its recorded empty flat-offer response (no market capture exists; SR6-3 still open), pinning empty as `[]` rather than an error. The error matrix runs 403, 429 `Retry-After: 0`, 503 and a connect timeout through all seven adapters and asserts `ScrapeError.kind` is `blocked`, `rate_limited`, `upstream_5xx` and `timeout` (SR2-1), with zero jitter and no rate slot via a patched policy so the matrix stays fast. `tests/conftest.py` gained a session-scoped socket guard (connect/connect_ex/create_connection/getaddrinfo) and two tests prove it plus respx's `AllMockedAssertionError`; `docs/CI.md` documents the layer. `pytest`: 1898 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1898 passed, 6 skipped, 1 xfailed; `pytest --cov`: 87.97% (12,166 statements, floor 80%); ruff clean; mypy 233 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-2 | Done | Every market fixture now carries a metadata header: `bookmaker`, `mode`, reviewed `captured_at`, `recorded_at` with `recorded_at_source`/`recorded_at_commit`, `endpoint`/`http_method`, `http_status`, `capture_tool_version`, plus the existing `source`, `payload_kind` and `provenance`. The 17 existing captures were backfilled by `refresh_fixtures.py --backfill-metadata --write` from each fixture's last commit (`git log -1 --format=%cI%n%h`), marked `recorded_at_source: "git_commit"`, `metadata_backfilled: true` and `capture_tool_version: "pre-metadata"`; `captured_at` is unchanged, so the 120-day policy and `stale_contracts` keep their exact meaning (`recorded_at` is provenance only). `engine/parser_contracts.py` gained `metadata_issues`, `metadata_report`, `scrub_secrets`, `backfill_metadata`, `http_method_for` and the extended `REQUIRED_TOP_LEVEL_KEYS`; `refresh_fixtures.build_report` reports a `metadata` block and folds it into `ok`, so CI `--check` fails on a missing field or a credential-shaped key. The capture tool writes `CAPTURE_TOOL_VERSION = "2"`, `recorded_at` from the capture clock, derives GET/POST and scrubs cookies, authorization, bearer/access/refresh tokens, CSRF and session ids; exact key matching keeps Betole's `matchIdsToken` event-id list unflagged. Contracts regenerated for the new keys. Docs: `docs/PARSER_CONTRACTS.md`, `docs/CI.md`; new `tests/test_fixture_metadata.py` (25 tests, including an isolated `main(["--check"]) == 1` for a stripped header). `pytest`: 1923 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1923 passed, 6 skipped, 1 xfailed; `pytest --cov`: 87.95% (12,255 statements, floor 80%); ruff clean; mypy 234 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3 | Done | MDShop (simplest direct-HTTP feed) now validates its raw `getwebevents` payload before any parser runs. New `scrapers/wire_schemas.py` models the NSoft envelope, event, market block and price row with `ConfigDict(strict=True, extra="allow")`; `validate_response` runs in `scrapers/mdshop.py::fetch_and_parse` immediately after `response.json()`, and `validate_bets` validates the `bets` array the dated fixtures freeze. `strict=True` rejects a string price, a boolean price and a renamed price field (`odd` → `price`); `extra="allow"` keeps an added key. A failure raises `ScrapeError(ScrapeKind.SCHEMA_DRIFT)`, propagated by MDShop's existing `except ScrapeError: raise`, so the book drops out instead of contributing zero legs as an empty feed; a non-JSON body is the same kind. Unknown keys outside the allow-list are counted in `bh_wire_unknown_keys_total{book,level,field}` (`root`/`event`/`bet`/`outcome`), logged once per payload and never fatal. The pattern is in `docs/WIRE_SCHEMAS.md`; `docs/CI.md` links it. Follow-up rows `SR4-3b`…`SR4-3j` added, one per remaining book, starting with Mozzartbet. New `tests/test_wire_schemas.py` (13 tests): both fixtures pass with no unknown keys, the captured event shell passes, renamed and string prices raise `schema_drift` through `validate_bets` and through the real `scrape()` (both modes, zero legs), integer prices stay numeric, unknown bet/outcome/event keys are kept, counted in the rendered metric and logged, an unknown key still scrapes, and a non-JSON body is `schema_drift`. `pytest`: 1936 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1936 passed, 6 skipped, 1 xfailed; `pytest --cov`: 88.02% (12,365 statements, floor 80%); ruff clean; mypy 236 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3b | Done | Mozzartbet (Playwright hybrid) now validates its raw JSON in both adapter paths. `scrapers/wire_schemas.py` gained `MozzartGame`/`MozzartSubgame`/`MozzartOdd`, `MozzartMatch`/`MozzartOffer` (the per-event `{"match": {"odds": [...]}}` response) and `MozzartMatchesPage` (`items` + `totalPages`), all `strict=True, extra="allow"`; the three entry points are `validate_mozzart_odds`/`validate_mozzart_offer`/`validate_mozzart_page`. `value`, `game` and `subgame` are required but nullable because every captured row carries them (`null` marks a suspended pick), so a renamed price field or a string price is `SCHEMA_DRIFT`, not a row the parser skips as `value == 0`. `scrapers/mozzartbet.py::_complete_offer` validates the offer immediately after `response.json()` and turns a non-JSON body into `SCHEMA_DRIFT`; a request failure or a per-event `{"error": ...}` payload (validated with `match = None`) still keeps that event's list odds. The pagination loop validates the list envelope and every item's `odds` array (the fallback offer); a non-JSON page is `SCHEMA_DRIFT`. `_build_matches` re-raises a `ScrapeError` returned by a per-event task, so a drifted row drops the whole book instead of pricing the other events. Unknown keys are counted at `root`/`match`/`odd`/`game`/`subgame` in `bh_wire_unknown_keys_total` and logged once per payload. The list **item** shell (teams, kickoff, competition) has no dated capture yet, so it stays unmodelled and undocumented keys there are neither rejected nor counted — recorded as the gap SR4-4/SR5-1 will close. `docs/WIRE_SCHEMAS.md` gained the Mozzartbet section and its levels. New `tests/test_wire_schemas_mozzartbet.py` (19 tests). No live scan was run and no bookmaker traffic was generated. `pytest`: 1955 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1955 passed, 6 skipped, 1 xfailed; `pytest --cov`: 88.26% (12,463 statements, floor 80%); ruff clean; mypy 237 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3c | Done | Admiralbet serves the same NSoft `getwebevents` envelope as MDShop, so it **reuses** `NSoftResponse`/`NSoftEvent`/`NSoftBet`/`NSoftOutcome` instead of adding a second shape; reuse was gated on a fixture-backed test. `scrapers/admiralbet.py::fetch_and_parse` now calls `validate_response(data, book="admiralbet")` immediately after `response.json()`, before any event is parsed. The adapter's historical bare-list form (the payload being the events array itself) is wrapped as `{"events": [...]}` first so the same schema applies to both shapes; a non-JSON body is `SCHEMA_DRIFT` too. A drift raises `ScrapeError(SCHEMA_DRIFT)`, which the existing `except ScrapeError: raise` propagates, so the book drops out with zero legs instead of an empty scan. Unknown keys are counted in `bh_wire_unknown_keys_total{book="admiralbet",...}` at the shared NSoft levels (`root`/`event`/`bet`/`outcome`) and logged once per payload. The event shell is validated only through the fields MDShop's capture proved; Admiralbet's extra fallback keys (`home`/`guest`, `dateFrom`/`kickoff`, `leagueName`) have no dated capture and stay unmodelled, counted as unknown event keys if present (the gap SR4-4/SR5-1 close). New `tests/test_wire_schemas_admiralbet.py` (18 tests) drives the real `scrape()` through a fake browser: both dated fixtures pass with no unknown keys, the real scrape emits exactly each capture's declared families, integer prices stay numeric, renamed/string prices raise in `validate_bets` and through `scrape()` (both modes, zero legs), unknown keys are kept/counted/logged, the bare-list form is validated, and a non-JSON body is `schema_drift`. `docs/WIRE_SCHEMAS.md` gained the Admiralbet section. No live scan was run and no bookmaker traffic was generated. `pytest`: 1973 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1973 passed, 6 skipped, 1 xfailed; `pytest --cov`: 88.77% (12,471 statements, floor 80%); ruff clean; mypy 238 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3d | Done | Betole's "price row" is a `{pick_code: price}` map, so the NSoft/Mozzart shapes do not fit. `scrapers/wire_schemas.py` gained `BetoleDeskPage` (the `{"esMatches": [...]}` desk envelope, `esMatches` required so a renamed key cannot read as an empty page), `BetoleOfferRow` (`id` + `odds` required) and `validate_betole_offer_map`/`validate_betole_desk`/`validate_betole_offers`. Map keys are pick codes, i.e. data rather than an allow-list — every code is accepted and the unmapped `284` control stays in the capture (`record_unmapped` keeps tracking codes the parser cannot price). Values are the pricing surface: `strict=True` rejects a string or boolean price, accepts an integer, keeps a `null` pick (the parser already reads it as "no price"). `scrapers/betole.py` validates the desk page and each event's odds map right after `response.json()` (desk odds are the per-event fallback), and the batched full-offer rows in `_fetch_full_offers`; a non-JSON body or a drifted row raises `ScrapeError(SCHEMA_DRIFT)`, which the "failed batch keeps desk odds" fallback now re-raises instead of swallowing, so the book drops out with zero legs. Unknown keys are counted at `root`/`row` in `bh_wire_unknown_keys_total{book="betole",...}` and logged once per payload. The desk event shell (teams, kickoff, live flags) has no dated capture and stays unmodelled, so a renamed team field still drops that event silently (the gap SR4-4/SR5-1 close). `docs/WIRE_SCHEMAS.md` gained the Betole section and levels. New `tests/test_wire_schemas_betole.py` (16 tests): the capture passes, integer/null picks accepted, string prices, renamed `esMatches`, a row without `odds` and non-JSON desk/offer bodies raise (through the schema and the real `scrape()`, zero legs), unknown root/row keys kept/counted/logged, and the real scrape emits the capture's expected plus experimental families. No live scan was run and no bookmaker traffic was generated. `pytest`: 1989 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 1989 passed, 6 skipped, 1 xfailed; `pytest --cov`: 88.83% (12,517 statements, floor 80%); ruff clean; mypy 239 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3e | Done | MBet (Alea platform, plain HTTP) has the NSoft `{"events": [...]}` envelope but a different odds shape: each event's `odds` is a map whose keys are oddtype keys and whose values are either a typed entry or a bare number. `scrapers/wire_schemas.py` gained `MbetOdd` (`value`, `market_key`, `oddtype_key`, `market_status`, `oddtype_status`, all required but nullable because the capture writes all five for every key) and `MbetResponse` (`events` required), plus `validate_mbet_odds`/`validate_mbet_response`. `scrapers/mbet.py::fetch_page` validates the page envelope and every event's odds map immediately after `response.json()`; a non-JSON page or a drifted entry raises `ScrapeError(SCHEMA_DRIFT)`, which `fetch_pages` propagates, so the book drops with zero legs instead of reading as empty or fully suspended. Oddtype keys are data, not an allow-list (every key accepted; `record_unmapped` still tracks unpriceable families); values are strict — string price is drift, integer accepted, bare number and `null` entry kept because the parser supports that form. Unknown keys count at `root`/`odd` in `bh_wire_unknown_keys_total{book="mbet",...}` and are logged once per payload. The event shell (sport id, competitors, kickoff, tournament) has no dated capture and stays unmodelled, so a renamed team field still drops that event silently (the gap SR4-4/SR5-1 close). `docs/WIRE_SCHEMAS.md` gained the MBet section and levels. New `tests/test_wire_schemas_mbet.py` (16 tests): both fixtures pass, integer/bare-number/null entries accepted, renamed and string prices plus a renamed `events` key raise (schema and real `scrape()`, both modes, zero legs), non-JSON pages are drift, unknown root/odd keys kept/counted/logged, and the real scrape emits each capture's declared families. No live scan was run and no bookmaker traffic was generated. `pytest`: 2005 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 2005 passed, 6 skipped, 1 xfailed; `pytest --cov`: 88.88% (12,568 statements, floor 80%); ruff clean; mypy 240 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3f | Done | SportPlus's dated fixtures freeze one match's `markets[]` array, so `scrapers/wire_schemas.py` gained `SportplusMarket` (`id`/`name`/`odds` required but nullable) and `SportplusOdd` (`alias`/`value` required but nullable), plus `SportplusPrematchPage` (`{"matches": [...]}`), `SportplusLivePage` (`{"sports": [...]}`, with a declared-but-unread `date` key kept out of the telemetry) and `validate_sportplus_markets`/`validate_sportplus_prematch`/`validate_sportplus_live`. `scrapers/sportplus.py` validates the prematch body after the optional double-serialised decode (`resp.json()` returning a JSON string) and the live body before any match is parsed; a non-JSON body or drifted block/price raises `ScrapeError(SCHEMA_DRIFT)`, re-raised by the existing `except ScrapeError: raise`, so the book drops with zero legs. `matches`/`sports` are required so a renamed envelope key cannot read as an empty offer; a renamed `value`/`alias` or a string price is drift, an integer price is accepted, and a block with `odds: null` is kept (the parser already treats it as empty). Unknown keys count at `root`/`market`/`odd` in `bh_wire_unknown_keys_total{book="sportplus",...}` and are logged once per payload. The match shell (sport name, competitors, kickoff, league) has no dated capture and stays unmodelled, so a renamed team field still drops that match silently (the gap SR4-4/SR5-1 close). `docs/WIRE_SCHEMAS.md` gained the SportPlus section and levels. New `tests/test_wire_schemas_sportplus.py` (19 tests): both fixtures pass, both envelopes pass, renamed/string prices raise through the schema and the real `scrape()` in both modes with zero legs, integer prices and a null odds block are accepted, the double-serialised prematch body still scrapes, renamed `matches`/`sports` and non-JSON bodies are drift, and unknown root/market/odd keys are kept/counted/logged. No live scan was run and no bookmaker traffic was generated. `pytest`: 2024 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 2024 passed, 6 skipped, 1 xfailed; `pytest --cov`: 89.18% (12,666 statements, floor 80%); ruff clean; mypy 241 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3g | Blocked | EVLBet is disabled, its recorded flat-offer response is an empty list and it has no market capture (`tests/test_market_fixtures.py::BOOKS_WITHOUT_FIXTURES`). The strict-schema acceptance cannot be met: there is no odds row to model, no renamed price field to reject, and no price to type. SR4-1 already pinned the recorded empty response at the transport boundary. SR6-3 (`Gate: operator`) owns the choice — capture a fixture and keep the adapter, or remove it and its config. No code was changed; the row is marked `Blocked on SR6-3` and work resumes only after that written decision. |
| 2026-11-08 | SR4-3h | Done | Premier Kladionica's PrSync is positional: the response is `[sections]`, each section a list of rows, and a column's meaning is its index. `scrapers/wire_schemas.py` gained `PremierOddRow` (price at column 5), `PremierSetTip` (name at column 2), `PremierSetTipVar` (line at column 9) and `PremierSetTipTip` (outcome code at column 4), each mapping its positional list through `model_validator(mode="before")` so the strict field types apply by position, plus `validate_premier_odds`/`validate_premier_lookup`/`validate_premier_sync`. `scrapers/premier_kladionica.py::_sync_call` gained the sync `kind`: a full sync validates the `[sections]` envelope (at least ten slots, each a list) and sections 7/8/9; a delta sync validates every non-empty section as odds rows. A non-JSON body, a wrong envelope, a short row/table or a string price raises `ScrapeError(SCHEMA_DRIFT)` and drops the book with zero legs. Positional data has no field names, so the counter reports unknown **section slots** past the documented fifteen at `level="section"`. The event/sports/competition-group/execRes sections have no dated capture and stay unmodelled, so a renamed team column still drops that event silently (the gap SR4-4/SR5-1 close). `docs/WIRE_SCHEMAS.md` gained the Premier section and levels. New `tests/test_wire_schemas_premier.py` (19 tests): both fixtures' odds/lookup rows and envelopes pass, string/truncated prices, non-string line/code columns and short rows raise (schema and real `scrape()` in both modes, zero legs), an integer price is accepted, an unknown section slot is counted/logged, short and non-`[sections]` envelopes and non-JSON bodies are drift, and the real scrape emits each capture's declared families. `pytest`: 2043 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 2043 passed, 6 skipped, 1 xfailed; `pytest --cov`: 89.26% (12,767 statements, floor 80%); ruff clean; mypy 242 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3i | Done | WWIN is a Playwright hybrid whose dated fixtures freeze the `bets[]` array (`idBt`, `spec`, `odds[]` with `t`/`va`/`isv`). `scrapers/wire_schemas.py` gained `WwinOdd` (`va` required, `isv` optional because the documented live `headerBets` row is `{va, t}`), `WwinBet`, `WwinEventsPage` (raw `p`/`events`), `WwinHeaderBetsPage` and `validate_wwin_bets`/`validate_wwin_events`/`validate_wwin_header_bets`. `scrapers/wwin.py` validates the prematch page (`p` or the historical `events`) and every event's `bets`, the live `events` page and the live `headerBets` rows immediately after `response.json()`. A non-JSON body, a missing page key, a non-object event/header item or a drifted bet row raises `ScrapeError(SCHEMA_DRIFT)` and drops the book with zero legs. Unknown keys are counted at `root` for envelopes and at `bet`/`odd` for rows and still scraped; the event shell (teams, kickoff, competition) has no dated capture and stays unmodelled (a renamed team field still drops that event silently; SR4-4/SR5-1 close it). `docs/WIRE_SCHEMAS.md` gained the WWIN section and levels. New `tests/test_wire_schemas_wwin.py` (25 tests): both fixtures and all three envelopes pass, string/renamed prices, a missing `spec`, a string `idBt`, missing/renamed page keys, non-object events/header items and non-JSON bodies raise (schema and real `scrape()` in both modes, zero legs), an integer price is accepted, unknown root/bet/odd keys are kept/counted/logged, and the real scrape emits each capture's declared families. `pytest`: 2068 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 2068 passed, 6 skipped, 1 xfailed; `pytest --cov`: 90.20% (12,851 statements, floor 80%); ruff clean; mypy 243 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-3j | Done | MaxBet (Singular sportsbook) is plain HTTP and its matches response is a bare `[event, ...]` list; the dated fixtures freeze one match's `odds[]` array. `scrapers/wire_schemas.py` gained `MaxbetSpecifiers` (`total`/`hcp`), `MaxbetOutcome` (`outcome`, `outcomeId`, `status` and `oddValue`/`marketAvailableForBetting` required but nullable) and `MaxbetMarket` (`id`, `name`, `specifiers` optional because line-less markets omit it, `outcomes`), plus `validate_maxbet_odds`/`validate_maxbet_events`. `scrapers/maxbet.py::fetch_and_parse` validates the list and every event's `odds` immediately after `response.json()`. A non-JSON body, a non-list response, a non-object event or a drifted market/outcome row raises `ScrapeError(SCHEMA_DRIFT)` and drops the book with zero legs. Unknown keys are counted at `market`/`specifiers`/`outcome` and still scraped; the event shell (teams, kickoff, league, status, external ids) has no dated capture and stays unmodelled (a renamed team field still drops that event silently; SR4-4/SR5-1 close it), and a renamed specifier on a totals market degrades to "no line" rather than drift. `docs/WIRE_SCHEMAS.md` gained the MaxBet section and levels. New `tests/test_wire_schemas_maxbet.py` (22 tests): both fixtures and the bare-list envelope pass, renamed/string prices, a missing outcome id, string status/market ids, non-list responses, non-object events and non-JSON bodies raise (schema and real `scrape()` in both modes, zero legs), a null price and an integer price are accepted, unknown market/specifier/outcome keys are kept/counted/logged, and the real scrape emits each capture's declared families. `pytest`: 2090 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 2090 passed, 6 skipped, 1 xfailed; `pytest --cov`: 90.27% (12,913 statements, floor 80%); ruff clean; mypy 244 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-4 | Done | New `engine/structural_drift.py` computes a structural signature from sorted key paths plus JSON types: array indices are collapsed, numeric map keys (e.g. `headerBets` per-event ids) collapse to `<id>`, values are ignored and the signature is SHA-256-truncated. `observe(book, endpoint, payload)` stores the first informative baseline per `(book, endpoint)` in `config/generated/wire_fingerprints.json`; a later response either matches or increments `bh_wire_structure_drift_total{book,endpoint}` and logs the added/removed paths. The last good baseline is kept on drift so the alarm repeats until an operator reviews the change; empty pages never establish one; I/O errors are logged and skipped so the alert can never raise into a scrape. It is wired at every adapter's raw-JSON boundary with an endpoint label (MDShop/Admiralbet `mode:events:sportId`, Mozzartbet `matches`/`offer` (success only), Betole `desk`/`offers`, MBet `events`, SportPlus `prematch`/`live`, Premier `sync:full`/`sync:delta`, WWin `prematch-events`/`live-events`/`live-header-bets`, MaxBet `matches:<sport>`, EVLBet `flat-offer`). `tests/conftest.py` redirects the baseline into the per-test runtime tree. New `tests/test_structural_drift.py` (12 tests): values do not change the fingerprint, a renamed key/type change/removed level do, numeric map keys collapse, the first informative response records a baseline, a value change matches silently, a rename increments the counter and logs the diff while the last good baseline is kept, empty pages do not establish one, an unreadable store recovers, the real MDShop scrape ignores a price change and alerts on an unmodelled key, and `/api/metrics` renders the counter. `pytest`: 2102 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 2102 passed, 6 skipped, 1 xfailed; `pytest --cov`: 90.34% (13,052 statements, floor 80%); ruff clean; mypy 246 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-5 | Done | `engine/coverage_budget.py` gained `cardinality_snapshot` (events and market rows per `book|sport`), `evaluate_cardinality` (rolling-median baselines, `event_drop` and `market_thin` flags, peer-gated), `push_cardinality_history` (20 scans) and `cardinality_book_reasons`. The floors are relative and absolute: below 50 % of the median with at least 5 missing events, or markets-per-event below 50 % with at least 2 missing rows; a baseline below 10 events is not judged. A drop is only flagged when a peer book still publishes that sport and is itself near its own baseline, so a shared calendar dip is not a feed failure. `compute_feed_integrity` takes `cardinality_flags`, adds the critical reason `cardinality_drop` and records `cardinality_flags` in the scorecard/history, so the book enters the existing quarantine state machine and recovery streak and is removed from pricing by the unchanged `quarantined_books`/`priceable_groups` path — no second gate. `server/api.py` computes the report per scan, persists the last report and bounded history in `cache/coverage_budget.json`, publishes `bh_cardinality_flags`/`bh_cardinality_flags_total`, logs the flag count and exposes `cardinality_floor` in `/api/health`. `tests/conftest.py` resets and redirects the new state. New `tests/test_cardinality_floor.py` (9 tests): the snapshot, a 10 % feed flagged and quarantined with `cardinality_drop`, a 75 % dip healthy, a peer-wide dip not flagged, a markets-per-event drop flagged, a short baseline not judged, the bounded history, the coverage-budget file round-trip and the `/api/health` block. `pytest`: 2111 passed, 6 skipped, 1 xfailed; `check_test_isolation.py`: both ledger modes 2111 passed, 6 skipped, 1 xfailed; `pytest --cov`: 90.40% (13,140 statements, floor 80%); ruff clean; mypy 247 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-6 | Done | Added the dev-only pin `syrupy==5.0.0`. New `tests/test_parser_snapshots.py` runs every fixture that declares `expected_markets` (17 captures) through the real parser entry point that `tests/test_market_fixtures.py::_run_parser` dispatches to, and snapshots the normalised output only: `market_type`, `settlement`, `period` and each `label`/`value` price row. Source ids, source context, outcome ids and update timestamps are deliberately left out so book identity data and the scan clock cannot churn the snapshot; raw payloads are not snapshotted (SR4-2/SR4-3 pin the raw shape and `contracts.json` pins ids/labels). Snapshots live in `tests/__snapshots__/test_parser_snapshots.ambr` and run in the normal `pytest` run (17 snapshots + one coverage guard). `pytest --snapshot-update` stays a human action: `docs/CI.md` records that a commit updating a snapshot must say why the normalised output changed and that CI never updates one. The guard asserts the snapshot case set equals the fixtures declaring `expected_markets` so a new capture cannot silently skip the layer. `pytest`: 2129 passed, 6 skipped, 1 xfailed (17 snapshots passed); `check_test_isolation.py`: both ledger modes 2129 passed, 6 skipped, 1 xfailed; `pytest --cov`: 90.40% (13,140 statements, floor 80%); ruff clean; mypy 248 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-7 | Done | New `tests/test_properties_parsers.py` runs all 17 fixtures that declare `expected_markets` (nine parser dispatch paths; EVLBet has no capture (SR6-3)) under Hypothesis with 40 examples each. Each example keeps the payload container and applies 1-3 bounded mutations inside it: drop a key, null a value, swap a scalar type, shuffle/duplicate/drop/truncate an array, add an unknown key. A mutation the book's wire schema (SR4-3) rejects is skipped, because production never passes that shape to a parser. Accepted mutations must return a list without an unhandled exception, every emitted price must be finite and positive, no label may repeat for one `(market_type, settlement, period)`, and no emitted identity may fall outside the clean capture's sport/settlement set. The clean capture is checked against the same invariants, plus two filter tests, so the property is not vacuous. Runtime ~2 s. The run found one production-reachable defect: `parse_nsoft_bets` appends one OddsValue per raw `betOutcomes` row without deduplicating by normalized label, so a duplicated outcome (accepted by the schema) gives two legs for one book. Recorded as `SR4-7a` and pinned with a strict xfail in the same file; not fixed in this row. The schema-guarded gaps it also exposed (short Premier rows, a non-object MaxBet `specifiers`) cannot reach a parser in production and need no code change. `pytest`: 2165 passed, 6 skipped, 2 xfailed (17 snapshots passed); `check_test_isolation.py`: both ledger modes pass; `pytest --cov`: 90.53% (13,140 statements, floor 80%); ruff clean; mypy 249 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR4-7a | Done | `scrapers/common.py::parse_nsoft_bets` now tracks the normalized labels it has already emitted and keeps the first offered price per label; a later duplicate raw `betOutcomes` row (and its outcome id) is ignored. The existing `actual`/`min_legs`/`issubset` acceptance logic is unchanged, so a market still needs its full label set. In `tests/test_properties_parsers.py` the strict xfail was removed, the regression test now duplicates the first outcome of the real MDShop prematch capture with a different price and asserts one label with the first price, and the mutation property enforces label uniqueness again for every parser. A duplicated outcome can no longer become two legs for one book. `pytest`: 2166 passed, 6 skipped, 1 xfailed (17 snapshots passed); `check_test_isolation.py`: both ledger modes 2166 passed, 6 skipped, 1 xfailed; `pytest --cov`: 90.53% (13,142 statements, floor 80%); ruff clean; mypy 249 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR1-4 | Done | The routine per-task loop now runs the full suite **once** (clean runtime state) instead of four times; targeted test files are run while coding. `AGENTS.md` gained a "Test cadence" section and its step 6 lost `scripts/check_test_isolation.py`; the `ROADMAP.md` "How to use" block, `Definition of done` and `Measurement discipline` say the same, and `docs/CI.md` records that CI's 3.11 leg owns the populated-ledger mode and the coverage floor. The one local exception is a change to the ledger, `config/generated/` or the isolation guard, which also runs `BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest`. No test, marker or trust invariant was removed. Measured before → after on this machine: plain suite 91.8 s, `--cov` 243 s, isolation 180 s (≈8.5 min) → one suite run plus ruff/mypy/checks ≈100 s; 145 test files, 1,461 plain test functions and 712 parametrized cases. `pytest`: 2166 passed, 6 skipped, 1 xfailed (17 snapshots passed); targeted `tests/test_readme_claims.py tests/test_ci_hardening.py tests/test_runtime_isolation.py`: 52 passed, 1 skipped; ruff clean; mypy 249 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR0-1 | Done | Operator decision: **B — keep the browser masking as a written, scoped exception**. `AGENTS.md` "Scraper rules" now forbids stealth/TLS impersonation/proxy rotation/captcha solving "except the scoped browser exception below" and adds the exception: `launch_browser()` keeps `--disable-blink-features=AutomationControlled` and the `navigator.*`/`window.chrome` init script because the browser books need it for Cloudflare/Turnstile; it stays limited to those markers inside `launch_browser()`, no TLS impersonation, proxy rotation, captcha solving, extra stealth or account-limit evasion, and a challenged book still reports `blocked` and drops out. The exception is quoted in the SR0-1 row. No code changed. `pytest`: 2166 passed, 6 skipped, 1 xfailed; ruff clean; mypy 249 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR0-2 | Done | Operator decision: **keep the current default — `VERIFY_SSL` stays `false`**. No code change; no per-book override. The decision is pinned by `tests/test_transport.py::test_the_policy_has_explicit_limits_and_a_rate`, which now asserts `policy.verify is VERIFY_SSL` (it previously only checked `isinstance(..., bool)`), so a silent flip of the default fails the suite. Recorded consequence in the row: prices read over an unverified connection can be tampered with in transit. `pytest`: 2166 passed, 6 skipped, 1 xfailed; ruff clean; mypy 249 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR6-3 | Done | Operator decision: **capture a fixture and keep the adapter**. The capture was carried out: `scripts/capture_market_fixtures.py --books evlbet` reported `SKIPPED evlbet/prematch: the flat offer feed answered 200 with an empty list`; direct probes of `matches/flat` with `SportIds=388` (with and without `Limit`/`Offset`) and `SportIds=1` all returned **HTTP 200, 2 bytes, `[]`**. No fixture exists, so none was written and the book stays disabled; the adapter, deeplink and registry row are kept as decided. `SR4-3g` is now **Blocked on a live EVLBet payload** rather than on this decision. No code changed. `pytest`: 2166 passed, 6 skipped, 1 xfailed; ruff clean; mypy 249 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Three capture/probe requests were sent to EVLBet. |
| 2026-11-08 | SR4-9 | Done | Operator decision: **operator host, daily**; the canary is not part of CI. New `scripts/live_canary.py` probes every configured book once, sequentially, through its real adapter (shared transport policy, rate limit, deadline; no login) and writes one dated report to `cache/live_canary/YYYY-MM-DD.json`. It compares with the newest other report: adapter error / missing scraper, a book with at least 10 matches losing more than half, and a market family with at least 5 markets losing more than half are reasons; a new family is `new_market_types`, not an alarm. Exit is 0 with alarms so a timer does not page; `--strict` returns 1. It never writes a fixture or contract. New `docs/LIVE_CANARY.md` documents the schema, thresholds, boundaries and the 06:17 cron line; the operator installs the timer, the repo does not. New `tests/test_live_canary.py` (12 tests): first run, halved book and family, erroring book, missing scraper, new family, the threshold table, fixture mtimes unchanged, and `--strict`. No live probe in this session. `pytest`: 2178 passed, 6 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 251 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. |
| 2026-11-08 | SR3-1 | Done | PyPI latest confirmed 1.64.1; `requirements.txt` pin moved 1.61.0 → 1.64.1 and the matching Chromium bundle was installed (`playwright install chromium`, Chrome Headless Shell 156.0.8078.4, v1248). The procedure is unchanged (README and Dockerfile already call it); README gained a line that a pin change needs the matching `playwright install chromium` because a stale bundle fails with "Executable doesn't exist". `BH_ARB_TEST_BROWSER=1 pytest tests/test_accessibility_axe.py`: 10 passed. Live, one run per browser book (`scripts/probe_feeds.py --books admiralbet,mozzartbet,wwin --timeout 300`): **admiralbet ok** (780 matches, 9 families, 1x2/btts/double_chance/over_under_0_5…5_5, 27.8 s); **mozzartbet** `ScrapeError: offer schema drift at match.odds.14.value: Field required` (0 matches, 25.1 s); **wwin** `ScrapeError: prematch response is not JSON` (0 matches, 8.1 s). Attribution control: downgraded the venv to 1.61.0 with its own Chromium and re-ran both failing books — identical failures (mozzartbet 24.8 s, wwin 7.7 s), so the upgrade is not the cause; the 00:48 scan that day had both healthy (wwin 877 matches, mozzartbet 614). Findings opened as **SR4-10** (Mozzartbet omits `value`, model requires the key) and **SR4-11** (WWin non-JSON classified `schema_drift`, a challenge should be `blocked`); the repeated list-page fingerprint alerts are **SR4-12**. Then reinstalled 1.64.1 and re-ran the browser tests green. `pytest`: 2178 passed, 6 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 251 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Traffic: three book probes plus the 1.61 control pair (five book runs total), no scan. |
| 2026-11-08 | SR4-10 | Done | Live capture: one offer has 518 odds rows — 413 with a numeric `value`, **105 with no `value` key at all**, 0 null — and the unpriced rows are otherwise identical (same keys minus `value`, same `specialOddValue: "-1"`, no second price field), i.e. suspended picks; they appear in supported families too. Evidence: `docs/evidence/2026-11-08-mozzartbet-missing-value.md`. `MozzartOdd.value` is now `float | None = None`; `game`/`subgame` stay required and a string/bool price is still `schema_drift`. `validate_mozzart_page()` gained one page-level guard: a page that carries odds rows and no numeric `value` anywhere is drift (a renamed price field); one suspended row or a fully suspended offer is accepted. The parser already skipped a missing price, so no leg is emitted without one. New/updated tests in `tests/test_wire_schemas_mozzartbet.py`: unpriced row accepted, mixed page accepted, page with no priced row is drift, renamed `value` on the list page is drift, an offer with the 1X2 rows unpriced yields no 1X2 leg but parses the other families, string price still drops the book. **Measured before → after (same probe): 0 matches / 0 markets → 603 matches / 4,698 markets, 28.8 s** (1x2 603, double_chance 597, btts 590, ou1.5 579, ou2.5 603, ou3.5 591, ou4.5 553, first_half_1x2 582). `pytest`: 2180 passed, 6 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 251 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Traffic: one list page + three offers for the capture, one full book probe after the fix. |
| 2026-11-08 | SR4-11 | Done | The capture corrected the hypothesis: replaying the exact prematch batch (15 day windows × 3 bet groups, 45 requests, sequential) shows **days 8-9 answer HTTP 200 with a 0-byte body** for every group, while days 0-7 and 10-14 answer JSON (2 KB-1.0 MB; 699 events on day 0). A 0-byte body is "no rows for this out-of-horizon window", not drift, and the blanket `schema_drift` dropped the whole book over it; an HTML challenge page remains possible and is `blocked`. New `scrapers/wwin.py::_json_body(resp, label)` decodes the body once: empty/whitespace → `None` (prematch slice returns no events, live stops with no matches, `headerBets` is skipped), `text/html` or a `<` prefix → `ScrapeError(BLOCKED)`, anything else non-JSON → `ScrapeError(SCHEMA_DRIFT)`; all three response sites use it. Tests: empty body and whitespace body are no rows (prematch and live), HTML page is `blocked`, malformed body is drift. **Measured before → after (same probe): 0 matches / 0 markets → 1,014 matches / 5,445 markets, 12.5 s** (1x2 1,014; double_chance 996; btts 879; over_under_2_5 817; over_under_3_5 575; over_under_1_5 336; over_under_4_5 198; over_under_5_5 11; over_under_0_5 9; first_half_1x2 610). `pytest`: 2186 passed, 6 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 251 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Traffic: one single-request probe, one 45-request replay, one 45-request sequential replay, one full book probe. |
| 2026-11-08 | SR3-2 | Done | Verified the cited tracker: playwright-python#3121 was **closed as completed on 2026-07-02**; the retained completed `asyncio.Task` objects came from a **CPython 3.14** asyncio bug fixed by python/cpython#152585, not from the pinned Playwright client. This project runs Python 3.11 and 3.12 (CI matrix; Docker base `python:3.11-slim`), where the leak never applied, so `context.route("**/*")` stays and no CDP `Network.setBlockedURLs` workaround is needed. New opt-in `tests/test_browser_route_leak.py` pins the invariant through the real `launch_browser()` route: six image-heavy pages (40 blocked requests each) in one context, completed-task count compared with the baseline. **Measured: baseline 1, after 1, growth 0** (threshold 50; a leak would add hundreds). The test is skipped without `BH_ARB_TEST_BROWSER=1` and `docs/CI.md` now lists it with the accessibility checks. `pytest`: 2186 passed, 7 skipped, 1 xfailed (17 snapshots passed); `BH_ARB_TEST_BROWSER=1 pytest tests/test_browser_route_leak.py`: 1 passed; ruff clean; mypy 252 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Total 2237 passed. No bookmaker traffic. |
| 2026-11-08 | SR3-3 | Done | New `scrapers/browser_pool.py` (`BrowserPool`, `browser_pool()`, `current_browser_pool()`): one Chromium per scan, launched lazily through the existing `launch_browser()`, a fresh context per book from the new `base.new_context()`, recycling after `BROWSER_MAX_PAGES=200` contexts or `BROWSER_MAX_AGE_SECONDS=600`. A disconnected browser is replaced at the next acquisition; a hung one at the age cap. `run_scan` wraps the scrape gather in `browser_pool()` and `scripts/probe_feeds.py` does the same. All three adapters (admiralbet, mozzartbet, and both wwin paths) take a context from `base.browser_session()`, so a standalone `scrape()` still gets a private one-shot pool and the capture scripts are unchanged. The deep-link verifier still calls `launch_browser()` directly (isolated context). `BROWSER_CONCURRENCY` still bounds concurrent browser books. **Measured with the same three-book probe before → after: launches 3 → 1, wall 74.2 s → 66.8 s, peak Chromium-tree RSS 838.2 MB → 945.3 MB** (a second sampled after-run measured 114.6 s / 945.3 MB while the books themselves were slower; the structural win is one launch and one browser, not memory). New `tests/test_browser_pool.py` (8 tests, fake launcher): one launch for many contexts, fresh context with init script/route, recycle on page budget, recycle on age budget, disconnected browser replaced, browser+Playwright closed, scan pool visible, `PlaywrightError` → `transport`, close failure tolerated. Fake-browser suites now patch `scrapers.base.launch_browser`. `pytest`: 2194 passed, 7 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 254 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Traffic: three 3-book probes (before + two after runs), no full scan. |
| 2026-11-08 | SR3-4 | Done | New `scrapers/forensics.py` and a `browser_session()` hook: tracing starts with the context, is discarded on success, and on failure writes `trace.zip` + `screenshot.png` under `cache/forensics/<book>/<scan_id>-<timestamp>/`; no `storage_state`/cookies are ever written and a capture never replaces the real error. `CancelledError` is skipped (the scan already records `timeout`). Retention: age (`FORENSICS_MAX_AGE_DAYS=7`) then total size (`FORENSICS_MAX_MB=200`), newest file kept; `FORENSICS_ENABLED` (default true) disables the overhead. The capture logs `[<book>] forensics: screenshot=…, trace=…` and `run_scan` appends `| forensics: …` to the book's failure note. `page.expect_response` was checked and is not needed: the only response listener (mozzartbet) is supplementary to the paginated `page.request` walk, so no flow change. Tests: `tests/test_forensics.py` (5: capture, disabled, age prune, size prune keeping the newest, log fragment); opt-in `tests/test_forensics_browser.py` forces a real failure through `browser_session("mbet")` and asserts a non-empty trace and screenshot under the book and the warning line naming the trace. **Measured:** `BH_ARB_TEST_BROWSER=1 pytest tests/test_forensics_browser.py`: 1 passed; `pytest`: 2199 passed, 8 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 257 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Total 2237 passed. No bookmaker traffic. |
| 2026-11-08 | SR4-8 | Blocked | Measured that Playwright HAR cannot replay these adapters: `context.route` / `record_har_*` / `route_from_har` only see page-initiated requests, while all three browser adapters fetch JSON through `page.request` (`APIRequestContext`), which bypasses routing and HAR recording. Probe: a route on `**/probe` never fired for `page.request.get` (the request went to DNS) but `page.evaluate("fetch(...)")` did fire it. A real admiralbet capture confirmed it: the HAR contained only analytics/widgets (cookieyes, Sentry, chat widget), none of the NSoft event responses the adapter parsed. The capture was discarded (no HAR, tool or partial test committed; the temporary `new_context(**overrides)`/`browser_pool(launch=)` seams were reverted). New gated row **SR4-8a** offers A (in-page fetch transport, then full HAR replay; changes live request shape, needs a measured scan) or B (boundary-recorded HAR shim, no live change, weaker claim); the operator must choose before SR4-8 resumes. `pytest`: 2199 passed, 8 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 257 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Traffic: one admiralbet capture run (640 matches) before the approach was abandoned. |
| 2026-11-08 | SR5-1 | Done | Added a cumulative histogram to `server/observability.py` (`observe`, buckets 0.05–120 s, `_bucket`/`_sum`/`_count`) and filled the missing per-book metrics: `retry_call` records `bh_scraper_attempts_total{book}`, `bh_scraper_retries_total{book}`, `bh_scraper_attempt_seconds{book}` and `bh_http_status_total{book,status}` for every attempt (including failures); `run_scan` sets `bh_book_last_success_timestamp_seconds{mode,book}` on `ok` and the startup baseline publishes it as 0 for every book/mode; `wire_schemas._drift()` increments `bh_schema_drift_total{book}`; the SR3-3 pool increments `bh_browser_recycles_total{reason=pages|age|crash}`. Existing `bh_book_kinds_total`, breaker gauges and `bh_wire_unknown_keys_total` are documented with the rest. New `docs/METRICS.md` lists every family, type, labels and meaning (README links it). New `tests/test_reliability_metrics.py` (6) covers cumulative buckets, retry attempts/retries/status/latency, schema drift, a pool recycle, and scrapes `/api/metrics` for every new family; `tests/test_metrics.py` asserts the last-success gauge after a real scan. `pytest`: 2204 passed, 8 skipped, 1 xfailed (17 snapshots passed); ruff clean; mypy 258 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` passed. Total 2237 passed. No bookmaker traffic. |
| 2026-11-08 | SR5-2 | Done | New `server/book_health.py` reduces the existing evidence to one state per book and feed (`healthy`, `degraded`, `open`, `blocked`, `drifted`, `disabled`) with a one-line reason, from the SR2-1 last kind (N1-3 scan-cost record, legacy `outcome` fallback), the SR2-6 breaker snapshot and the runtime toggle; priority disabled → blocked → drifted → open → degraded → healthy, and no record is `degraded` ("no scan recorded yet"). `GET /api/health` now serves `book_health.{prematch,live}` for every configured book; it is diagnostic only. New `tests/test_book_health.py` (12). Baseline, one scan per feed: prematch 144.8 s elapsed, 682 requests, 392.77 MiB, 201.06 book-seconds, 1.32 browser-seconds, 6,610 matches/45,192 market rows; live 33.7 s, 70 requests, 74.74 MiB, 66.52 book-seconds, 1.45 browser-seconds, 653 matches/3,548 market rows. Recorded in `docs/evidence/2026-11-08-scan-cost-baseline.md`; `premier_kladionica` delta drifted on 5-column rows in both modes, recorded as SR4-13. `pytest`: 2216 passed, 8 skipped, 1 xfailed (17 snapshots); ruff clean; mypy 260 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-08 | SR4-12 | Done | Structural signature now keeps only paths common to every list item, unions the types a common path shows across items, and ignores `null` when a real type is present; per-item-only paths are stored as `optional` and never alert, a previously optional path promoted to common is adopted silently, and a required path removed/renamed or a common type change still drifts. `FINGERPRINT_VERSION = 2` re-records older baselines once without an alert. New `optional_paths()`; `structural_paths()` is the required set. 7 new tests (19 in the file, the 12 SR4-4 tests still pass) cover optional-key move, required price removal, rename, type change, nullable field, promotion-then-removal and the v1 upgrade. `pytest`: 2223 passed, 8 skipped, 1 xfailed (17 snapshots); ruff clean; mypy 260 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No bookmaker traffic. |
| 2026-11-08 | SR4-13 | Done | The live delta response is five positional tables (execRes 5 cols, dogVar 14, dogTipK odds 9, dogLiveScore 43, scalars); `validate_premier_sync` was validating every non-empty section as odds, so execRes `[0,"",ts,4,ver]` drifted the book in both modes. Empty sections are omitted, so a section is now an odds table only when one row has the dogTipK shape (ints 0/2/3/4, numeric price 5, numeric result 7); all rows of a recognised section still go through the strict adapter, so truncated rows and string prices still drift. Other sections stay unmodelled; an all-malformed odds section fails closed (no legs) and SR4-4 still alarms. Trimmed live capture at `tests/fixtures/wire/premier_kladionica_delta.json`, evidence at `docs/evidence/2026-11-08-premier-delta-sections.md`; 5 new tests (24 in the premier file). Live probes: prematch 700 matches/5,761 market rows in 7.4 s, live 151/868 in 5.2 s, both `error: ""`. `pytest`: 2228 passed, 8 skipped, 1 xfailed (17 snapshots); ruff clean; mypy 260 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-08 | SR6-1 | Done | New `config/bookmakers.py` `AdapterDeclaration`/`DECLARATIONS` is the single per-book source (name, adapter module/class as strings, transport, enabled, UI URLs/colour, per-feed timeouts). Derived: `settings.BOOKMAKERS`, lazy `scrapers.registry.SCRAPERS` (`MutableMapping`, imports on first read, supports test overrides), `PLAYWRIGHT_BOOKIES` (admiralbet/mozzartbet/wwin) and the 20 transport policies with unchanged values. `server/api.py` imports no adapter module; `import server.api` loads 0 book modules. Market registry stays curated but its book set is checked. `scrapers.__all__` is derived as well. New `tests/test_adapter_declarations.py` (9): AST check for undeclared/absent adapters, derived lists and package exports, policies, registry coverage, unknown key, cached read, subprocess laziness. `pytest`: 2237 passed, 8 skipped, 1 xfailed (17 snapshots); ruff clean; mypy 263 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No bookmaker traffic. |
| 2026-11-08 | SR6-2 | Done | New `scrapers/protocol.py`: `BookAdapter` (runtime-checkable `Protocol`) and `AdapterClass = type[BookAdapter]` — no-argument construction plus an async `scrape()` with `live`, `scan_time` and `sports_wanted`. The five adapters that lacked `sports_wanted` (mozzartbet, betole, evlbet, premier_kladionica, wwin) accept it and ignore it; before, `server/api.py` reached them through a `TypeError` fallback, so the fetched offer is unchanged. `scrapers.registry.__getitem__` is typed `AdapterClass` and a new `adapter(book) -> AdapterClass | None` is used at the two scan call sites in `server/api.py`, so mypy now checks `scraper.scrape(...)` against the protocol instead of `Any`; the `TypeError` fallback stays for monkeypatched test fakes. `tests/test_adapter_declarations.py`'s AST guard now requires a concrete class with an async `scrape`, so the Protocol is not counted as an undeclared adapter. New `tests/test_adapter_protocol.py` (5 tests): every declared class matches the protocol at runtime (no-arg construction, coroutine, keyword defaults, `get_type_hints`), the registry annotations are the protocol types, the contract imports without loading an adapter module, mypy accepts a generated module typing all ten declared classes as `type[BookAdapter]`, and mypy rejects three broken adapters (missing entry point, sync entry point, wrong return type) with each file named in its output. `pytest`: 2242 passed, 8 skipped, 1 xfailed (17 snapshots passed) in 100.81 s; ruff clean; mypy 265 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan, no bookmaker traffic. |
| 2026-11-08 | SR4-8a | Done | Operator chose **A (in-page fetch)**. `scrapers/base.py` now issues the browser books' API calls with `fetch` inside the loaded document (`_page_fetch`): same `headers`/`params`/`data` arguments, same returned surface (`status`/`status_code`, `headers`, `body()`, `json()`, `content`), `credentials: "include"` for the browser's cookies and Cloudflare clearance, request and body bytes still counted, and a Python-side 30 s cap (`PAGE_FETCH_TIMEOUT_SECONDS`, the old `APIRequestContext` default) so an overrun is the shared `timeout` kind, not a text-matched JS error. Dict/list bodies are JSON-serialised with `application/json`, string bodies are sent unchanged (Playwright's `data` rules), so both POST endpoints keep their shape. New `PageResponse` keeps the adapters unchanged; no adapter calls `page.request` any more. **Measured (2026-11-08, prematch, live, in-page → `page.request` control minutes later on the same offer):** admiralbet 3 req / 4.71 MB / 13.2 s / 121 matches → 3 / 4.71 MB / 10.3 s / 121; mozzartbet 234 / 72.27 MB / 25.5 s (19.2 s on an earlier pass) / 215 → 233 / 71.95 MB / 37.0 s / 215; wwin 46 / 2.03 MB / 13.2 s / 459 → 46 / 2.03 MB / 12.1 s / 459. Cloudflare passed on all three including cross-origin admiralbet: zero `blocked`/`transport`, three `ok`; requests within one event, bytes within 0.5 %, parsed output identical modulo that event. Evidence and boundaries in `docs/evidence/2026-11-08-sr4-8a-inpage-fetch.md`. New `tests/test_page_fetch.py` (10 tests: request shape, JSON/string bodies, empty-body and non-ASCII round-trip, byte accounting, Python timeout, page error as `transport`, 403 one `blocked` attempt, 503 retry, challenge header, no `page.request` in `scrapers/`) and opt-in `tests/test_page_fetch_browser.py` (real Chromium: `context.route` sees the document and the in-page API call with its POST body). `docs/CI.md` lists the opt-in check; `docs/SCAN_COST.md` names the in-page fetch in the `requests` definition. `pytest`: 2252 passed, 9 skipped, 1 xfailed (17 snapshots) in 108.71 s; ruff clean; mypy 267 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. Traffic: three live prematch passes over the three books (two on the new transport, one control), ~848 API requests plus 9 navigations; no login, no bet. |
| 2026-11-08 | SR4-8 | Done | The browser books' transport is committed and replayed. New `scrapers/har_fixtures.py` owns the rules: `REPLAY_PREFIXES` (each book's API), `MAX_REPLAY_OFFERS` (30 for mozzartbet), `trim()` (keeps the page document — `_resourceType: document` — plus the book's API calls; drops analytics/JS/images/fonts), `scrub()` (drops `cookie`/`set-cookie`/`authorization`/`proxy-authorization` headers from both sides and empties the HAR cookie jar; odds payloads stay), and gzip `loads`/`dumps`. New `scripts/capture_har.py` records a live HAR through the real adapter and pool (`browser_pool(record_har_path=...)`), trims and scrubs it, writes `tests/fixtures/har/<book>.har.gz` + `<book>.meta.json`, then replays the new file offline through the same adapter and records the measured counts in the sidecar (a zero-match replay fails the capture). Committed set 1.72 MB gzipped: admiralbet 492 KB (93 matches / 739 markets, 38 entries), wwin 341 KB (450 / 2,643, 56 entries), mozzartbet 892 KB (207 / 941, 54 entries — 30 offers kept, the rest abort into the adapter's list-odds fallback). Raw captures were 31.8 / 8.8 / 88.0 MB, hence gzip and the offer bound. Replay uses `browser_pool(har_path=...)` → `route_from_har(not_found="abort")`, so a missing entry aborts and nothing leaves the browser; the sidecar's `scan_time` is passed to `scrape()` because admiralbet and wwin build their date windows from it. New `tests/test_har_fixtures.py` (8, normal suite) proves every file is present, holds only its document plus API calls, carries no secret header, has an empty cookie jar, has a consistent sidecar, is idempotently trimmed and is under the size budget; `tests/test_har_seams.py` (4) proves a scan records nothing and routes nothing while the capture/replay seams pass their path. New opt-in `tests/test_browser_har_replay.py` (3) runs each book's real `scrape()` from its file and asserts the sidecar counts (measured: 3 passed). New `docs/HAR_REPLAY.md`; `docs/CI.md`, `README.md` and `AGENTS.md` point at it. New `.github/workflows/browser.yml` runs the Chromium checks (page-fetch route, HAR replay, accessibility, route leak) on `workflow_dispatch` only. `pytest`: 2264 passed, 12 skipped, 1 xfailed (17 snapshots) in 117.69 s; `BH_ARB_TEST_BROWSER=1` on the two new files: 4 passed; ruff clean; mypy 272 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. Traffic: six live prematch passes over the three browser books (three sizing probes plus one capture pass per book) with the shared transport policy; the replays run offline; no login, no bet. |
| 2026-11-08 | M2-3 | Done | `/api/health` is split into a cached summary and live fields. `_health_summary()` builds and caches 31 blocks for `HEALTH_CACHE_SECONDS` (new setting, env of the same name, default 2.0 s, `0` disables): parser contracts, admissibility audit, retention, cache sizes, freshness, stale prices, feed integrity, cardinality, mapping coverage/trends, scan cost, pairing, candidate blockers/remediation/trends, the cached counters and the `unverified_links` walk. The endpoint adds the 18 live fields per request (scanning state, surebet/match counters, `book_health`, breaker snapshots, memory, alerts, `ai_available`, per-bookie errors, deep-link declaration source/audit). The payload gains `health_cache{ttl_seconds,generated_at,age_seconds}` and keeps every shipped key (pinned by a key-set test). `run_scan` resets the cache at start and in its `finally`; `tests/conftest.py` resets it per test. **Measured** (`health()` direct, same process): empty 2.241 → 0.337 ms (85 % less); 6,600 prematch + 2,000 live cached matches 20.32 → 0.33 ms (98 % less); through `TestClient` 5.74 → 3.80 ms. The three file-backed blocks were 1.7 ms of the empty-state call (`admissibility_health` 0.98, `retention_health` 0.46, `contract_health` 0.22). New `tests/test_health_cache.py` (6 tests). Two scan-emulating helpers drop the cache before reading (`tests/test_frontend_empty_state.py`) and the declaration-map test does too (`tests/test_candidates_api.py`). `README.md` and `.env.example` document the setting; health stays diagnostic, no gate or pricing path reads it. `pytest`: 2270 passed, 12 skipped, 1 xfailed (17 snapshots) in 120.60 s; ruff clean; mypy 273 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan. |
| 2026-11-08 | M1-1 | Done | Operator delegated the pick; chose this because 16 of 34 `/api` routes had no auth dependency (`/results`, `/status`, `/config`, `/groups`, `/debug/*`, `/bets`, `/paper/*`, `/link-sweeps`), so with `API_KEY` set they served odds, config, bet history and CSV to anyone, and a valid named key was rejected whenever a bootstrap key was also configured. `server/auth.py` gained `resolve_api_key` (env key first via `hmac.compare_digest`, then the hashed store) shared by `server/app.py::api_key_guard` and `server/api._require_api_key`; the middleware resolves the key for every `/api` route except `/api/health`, returns 401 when no key resolves and 403 for a `GET`/`HEAD` without `read`/`admin`, and keeps the documented local-only open mode when nothing is configured. Seven write routes that accepted any key (`/verify`, `/recalculate`, `/link-sweeps`, `/bets`, `/bets/{id}/settle`, `/bets/{id}/closing`, `/paper/positions/{id}/settle`) now require `scan`. **The strict xfail is removed by fixing the gap** (suite xfailed 1 → 0); `tests/conftest.py` gives each test a private key store so the operator's `config/generated/api_keys.json` cannot decide the suite. New `tests/test_api_auth.py` (9 tests): every `/api` path except health from the OpenAPI schema is 401 without a key (32 paths), health public, named key beside bootstrap key, read-cannot-write, scan-cannot-read, local-only open, revoked-only store closes reads, near-miss env key rejected. Three test modules now patch `api.API_KEY` (single owner) instead of the removed `server.app` binding. `docs/AUTH.md` and `README.md` document the middleware and the scope matrix; `AGENTS.md` records that the tripwire is fixed. `pytest`: 2280 passed, 12 skipped, 0 xfailed (17 snapshots) in 108.03 s; ruff clean; mypy 274 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan, no bookmaker traffic. |
| 2026-11-08 | M1-3 | Done | Follow-up to M1-1, which made the middleware resolve a key on every `/api` request: a successful named-key verify measured **84.75 ms** (PBKDF2, 200k iterations) per request on this host, paid again on every 30 s dashboard poll and on every wrong-key attempt, with a full store rewrite for `last_used_at` each time. `ApiKeyStore.verify` now caches successes for `AUTH_CACHE_SECONDS` (default 60, 0 disables) under `sha256(token)` with the scope snapshot; a hit spends no PBKDF2 and writes no file. `create()`/`revoke()` clear the cache, so revocation is immediate; cache hits compare the store file's mtime+size, so an out-of-band edit is seen at once (the TTL only bounds an unchanging store); failures are never cached; `last_used_at` is persisted at most once per key per TTL. A process-wide `FailureLimiter` (`auth.auth_failures`) throttles failed attempts per client address at `AUTH_FAILURE_RATE_LIMIT` (default 10, 0 disables) inside the shared `RATE_LIMIT_WINDOW_SECONDS`, checked **before** resolving so a blocked client spends no PBKDF2; a success clears the counter and `/api/health` stays public. **Measured** with 10 stored keys, 25 requests to `/api/results` per mode: **83.47 → 3.33 ms per request (25.1x, −80.1 ms)** for cache off → on. New `tests/test_auth_limits.py` (14 tests); `tests/conftest.py` resets the shared budget per test and the route-coverage sweep resets it per request so it still asserts 401, not 429. `README.md`, `.env.example`, `docs/AUTH.md` updated. `pytest`: 2294 passed, 12 skipped (17 snapshots) in 141.15 s; ruff clean; mypy 275 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan, no bookmaker traffic. |
| 2026-11-08 | M2-1 | Done | The scan's analysis half ran on the event loop with no yielding `await` — grouping, stale/skin/feed-integrity, the candidate walk, the pricing pass and the 27 MB cache write — so a real scan blocked `/api/status` for about 100 s. Every heavy stage is now a sync helper called through `asyncio.to_thread`, in the same order: `_finish_scan_cost`, `_evaluate_feed_diagnostics`, `learn_scan_mappings`, `MatchMatcher()` + `group_matches`, `measure_price_agreement`/`apply_measured_twins`, `get_match_report`, `evaluate_stale_prices`, `compute_feed_integrity`, `_build_candidates` (the candidate walk split from the async AI ranking), `find_surebets`, `filter_price_outliers`, `capture_closing`, the paper writes, `_summarize_pricing`, `_serialise_scan_caches` and `_persist_scan_state` (cache + sibling JSON writes). Logic, inputs, outputs and ordering are unchanged; the scan tests in `test_e2e_certified`, `test_metrics`, `test_record_only`, `test_scan_candidates`, `test_auto_clv` and `test_health_cache` pass unchanged. New `test_the_scan_analysis_runs_off_the_event_loop` calibrates itself: with `to_thread` neutralised the same 3-match scan (group_matches stubbed to 0.5 s) held the loop for a **695.5 ms** heartbeat gap; offloaded it was **15.4 ms**, and all nine wrapped heavy stages ran off the main thread. A cancelled scan may let one worker finish (threads are not interruptible); every orphanable stage re-reads shared state at call time and writes idempotent diagnostics. `pytest`: 2295 passed, 12 skipped (17 snapshots) in 115.41 s; ruff clean; mypy 275 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan. |
| 2026-11-08 | M2-2 | Done | Each `/api/verify-links` call ended in `_save_cache(mode)`, rewriting the whole scan cache to persist at most a handful of `deep_link_verified` flags, once per checked event. The write is gone: `apply_report` + `_apply_deep_link_verifications` still update the in-memory cache, and the verdict stays durable in `deep_link_verifications.json` (proof written or removed) and `deep_link_decisions.json` (the event is decided). Because the cache file can now predate a failed check, `_load_cache` re-derives the flag: new `_clear_stale_deep_link_flags` clears a cached True that no fresh store record backs, then `_apply_deep_link_verifications` re-applies the fresh ones; a book the gate settles by declaration is unaffected. The one test pinning the old asymmetry (match list kept a stale True while the report was filtered) now asserts the flag is re-derived as well. **Measured** on the operator's real files: `_save_cache` 71.4 ms at 1.2 MB/384 matches (today's prematch), 201.2 ms at 3.7 MB/942 matches (live), 1230.3 ms at 21.6 MB/6,610 matches (the SR5-2 baseline shape, the row's size); a check now does zero cache writes and its two store writes take 0.325 ms. New tests: normal check writes no cache but persists the proof and updates memory; failed check removes the proof, records the decision, clears the flag; restart with an emptied store clears the cached flag. `pytest`: 2298 passed, 12 skipped (17 snapshots) in 116.27 s; ruff clean; mypy 275 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan. |
| 2026-11-08 | M2-4 | Done | Operator: "Continue with M2-4, the candidate queue cap." The operator's scan history (`cache/bh_arb.sqlite3`, 25 scans) shows a prematch queue peaking at **14,249** pairs (11,657 matches), median 5,855, of which at most **473** were actionable; live peaked at 766. Keeping all of them cost 8.9 ms per `/api/candidates` poll, ~22.7 ms per health summary rebuild and ~19.8 MB of candidate JSON. New `CANDIDATE_QUEUE_MAX` (env, default 2000, 0 disables) keeps the top N in the existing priority order (closeable, alias-actionable, fewest blockers, tightest kickoff, closest names, id), with `_pair_priority` shared by a mid-walk trim at 4×N so the transient list stays bounded and the retained set is identical. Nothing is silent: `/api/candidates` gains `found`/`retained`/`dropped`/`cap` and found-side `actionable_found`/`closeable_found`; health gains `candidate_queue.{prematch,live}`; history keeps `candidate_queue` = found (comparable with old rows) plus `candidate_retained`; the blocker trend point gains `retained`/`dropped`/`cap`; `bh_candidate_queue_size` is retained and new `bh_candidates_found` is the denominator; the Review tab shows the cap note (Bosnian string added). **Measured at the 14,249 peak: `/api/candidates` 7.8 → 2.8 ms, health candidate blocks 22.7 → 2.7 ms, retained JSON ~19.8 → ~2.8 MB.** New tests: cap keeps the actionable pair, 0 disables, trim is exact, endpoint/health/history/trend denominator, frontend note. `README.md`, `.env.example`, `docs/METRICS.md`, `docs/CANDIDATE_REMEDIATION.md` updated. `pytest`: 2306 passed, 12 skipped (17 snapshots) in 118.23 s; ruff clean; mypy 275 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan. |
| 2026-11-08 | M1-2 | Done | Operator: continue. Decision: **reject with 422**. `accepted_odds: 0` is the explicit "not placed" sentinel, but it is a sentinel on both fields: `BetStore.settle` already treats either zero as not placed (bankroll, staked and profit stay correct) and CLV skips a falsy accepted odds, so the old behaviour was safe for money but silent — a positive stake at a price that cannot exist was neutralised and the operator's claimed stake vanished from P/L with no warning. The dashboard cannot produce it ("Mark placed" refuses odds < 1.01 and sends both accepted fields from the same `placed` flag), so only a hand-written client could. New `BetLegPayload` model validator `_a_stake_needs_a_price` refuses `accepted_stake > 0` with `accepted_odds == 0` with a 422 that names both fields, and writes no row. The sentinel stays: both zero = not placed, `accepted_odds: null` still falls back to the planned price, a zero stake with a real price is still accepted. `BetStore.settle` unchanged, so an already-stored inconsistent row still settles as not placed (verified: staked 0.0, payout 0.0, profit 0.0). Four new tests in `tests/test_bet_log.py`; `docs/BET_LOG.md` documents the pair rule. `pytest`: 2310 passed, 12 skipped (17 snapshots) in 117.63 s; ruff clean; mypy 275 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan. |
| 2026-11-08 | M2-5 | Done | Operator: continue. Decision: **keep every piece of evidence; compact the representation that has no human reader.** The operator's `config/generated/mapping_evidence.json` was 93,981,475 bytes / 16,649 claims written with `indent=2` — over the 67.1 MB `MAPPING_LEDGER_BUDGET_BYTES` — while every consumer loads it through `MappingLedger.load()` or `json.load`: the gate, learner, replay, league resolver (`detail["teams"]`), candidate remediation and mapping coverage (evidence types), `scripts/generate_market_registry.py` (last evidence detail), maintenance prune and `/api/health.retention` bytes. The scan caches and every diagnostics file were already compact; only the ledger (and the two small human-inspectable decision/link-sweep files) were indented. `MappingLedger.save()` now writes `separators=(",", ":")` with `sort_keys=True`; schema, claims, evidence, statuses, TTLs and the prune rule are unchanged, and `prune()` remains the only evidence-dropping step (maintenance only). Audit recorded in `docs/STORAGE.md`. Two tests: compact file (no newline, smaller than indented), and a nine-record claim round-trips intact above the prune cap. **Measured on a copy of the real ledger: 93,981,475 -> 50,054,456 bytes (-46.7 %), under budget without pruning; load 1.83 -> 1.73 s, save 4.45 -> 4.01 s.** `pytest`: 2312 passed, 12 skipped (17 snapshots) in 116.23 s; ruff clean; mypy 275 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan, no runtime state rewritten. |
| 2026-11-08 | M3-1 (stages 1–2) | In progress | Operator: continue. Stage 1: the pure candidate scoring moved to **`server/candidate_scoring.py`** (198 lines) — `TeamTokens`, `FoundPair`, kickoff keys/bucketing, `match_event_ref`/`match_side_key`, `bigrams`, `shares_any_signal`, `team_similarity`, `token_run_shared`, `canonical_pair_key`, `candidate_id`, `pair_priority` — with one definition; `server/api.py` imports it (5,903 → 5,782 lines), no private copy remains, and the module imports no `server.api`. `tests/test_scan_candidates.py` and `scripts/audit_league_pairs.py` read the new module; `tests/test_candidate_scoring.py` pins the import rule and object identity. Stage 2: `_state_for` now returns a **`FeedState`** NamedTuple (`status`, `surebets`, `matches`, `report`, `per_bookie`); api route call sites read named fields, while the existing tuple unpacking in `scripts/record_scan.py` and tests keeps working; `server.mapping_coverage` takes a `Sequence` so the typed list stays assignable. `tests/test_ci_hardening.py` follows the `usedforsecurity=False` call site to the new module. Stage 3 (JSON-store layer) remains. `pytest`: 2314 passed, 12 skipped (17 snapshots) in 112.49 s; ruff clean; mypy 277 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan; scores, ids, ordering and deep-link verdicts unchanged. |
| 2026-11-08 | M3-1 (stage 3) | Done | Operator: continue. New **`server/json_store.py`** (70 lines) owns the JSON-store layer: `atomic_write_json` (temp file + `os.replace`, the writer moved out of api) and `read_json` (missing/unreadable/malformed → `None`). Every JSON reader and writer in `server/api.py` now uses it: market/bookmaker toggles, allowlist, suppressed decisions and premises, both deep-link stores, the history export, opportunity metrics, feed integrity, stale price state, coverage budget, scan cost, the scan cache loaders and link sweeps. Shape validation, locks, TTL filtering and merge rules stay with each store's owner, so scan and deep-link semantics are unchanged. `server/api.py` **5,782 → 5,714 lines** (5,903 → 5,714 across M3-1) and no longer imports `json` or `tempfile`. New `tests/test_json_store.py`: compact output, readable default, whole replacement with no temp file, a failed write keeping the previous document, and the forgiving read; `tests/test_cache_serialization.py` and `tests/test_candidates_api.py` follow the moved writer. `pytest`: 2320 passed, 12 skipped (17 snapshots) in 117.95 s; ruff clean; mypy 279 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan. |
| 2026-11-09 | M3-2 | Done | Operator: continue with M3-2. The declaration store moved from `scrapers/common.py` to **`engine/deeplinks.py`** (317 lines): path, cache, mtime/size reload, provenance, `supports_event_id`/`declares_no_event_id`/`declares_route_pattern_verified`, `declaration_verified_at`, `declaration_audit`, `effective_deeplink_declarations`, `deeplink_declaration_source` and `build_event_url`; semantics (fail-safe parse, synthetic-cache seam, TTLs) unchanged. The other engine→scrapers edges were the AH label helpers, so **`engine/ah_labels.py`** (49 lines) now owns them and `scrapers.common` re-exports them for `mbet`/`sportplus` and the tests. `scrapers/common.py`: **986 → 657 lines**. Certainty, matcher and arbitrage import from engine only; `tests/test_layering.py` proves by subprocess that importing those three loads no `scrapers` module and by AST that no engine source imports scrapers even inside a function, and that `scrapers.common` no longer exposes the store. `server/api.py`, `scripts/verify_deeplinks.py`, `scripts/audit_deeplinks.py`, `mdshop`/`maxbet`/`admiralbet`, tests and `conftest`'s cache-reset fixture all read the new modules. `AGENTS.md` documents the one-way dependency. `pytest`: 2323 passed, 12 skipped (17 snapshots) in 149.41 s; ruff clean; mypy 281 source files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No live scan; no declaration value or trust rule changed. |
| 2026-11-09 | M3-3 | Done | Operator: continue with M3-3. `engine.deeplinks.settle_link()` now answers "is this leg's per-event link settled?" once for all three callers, returning `LinkSettlement(settled, reason)`. The gate passes the match's `deep_link_verified` flag; the cache restore passes a fresh store record keyed `bookmaker|event_id` (never the cached flag, which outlives its proof); `_unverified_link_count` passes the flag and keeps its event-id scope. Removed the duplicated four-case branches from `engine/certainty.py::_link_evidence` and `server/api.py::_restorable_match_groups`/`_unverified_link_count`. New `tests/test_link_settlement.py` runs ten cases (proof, route pattern, declares-no-route ±id, declared-unproven ±capture, silence with id/url/nothing, stale store proof) through the predicate, gate, restore and counter and asserts agreement, plus a stale-proof restore rejection. `pytest`: 2354 passed, 12 skipped (17 snapshots) in 115.83 s; ruff clean; mypy 282 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No trust rule, declaration, TTL or cache format changed. |
| 2026-11-09 | M3-4 | Done | Operator: continue with M3-4. Added **`server/sqlite_store.py`** as the one connection path for the shared `cache/bh_arb.sqlite3`: `connect()` sets WAL + `synchronous=NORMAL`, `connect_readonly()` sets no pragmas and cannot create the file. `Storage`, `BetStore`, `PaperStore` and `_readonly_connection` in maintenance now delegate, ending the split where only `Storage` set NORMAL and the other two ran FULL. Added **`server/timeutil.py`** with `utcnow()`, `naive_utc()`, `iso_now()` and `iso_seconds()`; removed the `_now`/`_now_iso`/`_iso`/`_naive_utc` copies and all 41 inline `datetime.now(UTC).replace(tzinfo=None)` expressions under `server/` (0 remain outside the helper). Stored timestamp shapes and precisions unchanged. New `tests/test_storage_policy.py` (7 tests) pins WAL+NORMAL on all three stores, the read-only no-create/no-write rule, the clock helpers and a shared-file round trip. `docs/STORAGE.md` and `AGENTS.md` document the helpers. `pytest`: 2361 passed, 12 skipped (17 snapshots) in 113.89 s; ruff clean; mypy 285 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No schema, cache format or retention rule changed. |
| 2026-11-09 | M3-5 | Done | Operator: continue with M3-5. Added call-time registry accessors to `engine/market_registry.py`: `registry()`, `has_source_id()`, `specs_for()`, `lookup_type()`, `ids_for()`; `registered_spec()` resolves through them and keeps its `has_source_id` fallback. Removed every direct `from engine.market_registry import MARKET_REGISTRY` and method call from `engine/admissibility.py`, `scrapers/{wwin,maxbet,mbet,evlbet,mozzartbet}.py`, `scrapers/common._nsoft_registry` and `scripts/capture_market_fixtures.py`; 0 modules outside the registry now name the singleton. Raw lookups (mbet live, mozzartbet hardcoded ids, fixture capture) use `lookup_type()` so unmapped diagnostics do not change. Two tests in `tests/test_market_registry.py` prove every accessor follows a replaced global and that a registry replaced AFTER the adapters import is seen by common/nsoft, mbet, mozzartbet, wwin, maxbet and admissibility. `pytest`: 2363 passed, 12 skipped (17 snapshots) in 112.94 s; ruff clean; mypy 285 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No registry row, mapping or parser verdict changed. |
| 2026-11-09 | M3-6 | Done | Operator: continue with M3-6. Moved the reusable code out of `scripts/` so coverage measures it: **`server/pairing_audit.py`** (234 lines, `audit` + miss helpers) and **`server/deeplink_verifier.py`** (585 lines, criterion, dataclasses, evidence, `build_targets`, `apply_report`, `check_target`, `verify_bookmaker`). `scripts/pairing_audit.py` (48 lines) and `scripts/verify_deeplinks.py` (109 lines) keep their `main`/loader and re-export the public names, so existing importers and CLI flags are unchanged. `server/api.py` now imports both from `server`, removing the app→scripts dependency. `tests/test_layering.py` pins: no `server` module imports `scripts`, both implementations are under `server`, and both wrappers keep their names; the README cursor-claim test now reads `server/deeplink_verifier.py`. `python scripts/pairing_audit.py --check` exits 0; `pytest`: 2366 passed, 12 skipped (17 snapshots) in 113.32 s; ruff clean; mypy 287 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. No criterion, report shape, flag or verdict changed. |
| 2026-11-09 | M4-1 | Done | Added **`requirements.lock`** (27 runtime packages) and **`requirements-dev.lock`** (85), generated by **`scripts/lock_requirements.py`** (one clean temp venv; `--check` reported in sync). Lock files are sorted exact pins, excluding pip/setuptools/wheel. Dockerfile, all CI install steps, the release workflow, the Docker-smoke path filter and the SBOM venv now install the locks; `pip-audit` audits the resolved locks instead of the manifests. New `tests/test_dependency_lock.py` (6 tests) proves direct manifest pins match the lock, the dev lock is a superset with unchanged runtime pins, locks are sorted/exact, resolved transitives are present, and Docker/CI/SBOM install the lock; `test_deployment_assets`, `test_ci_hardening` and README/RELEASE/CI docs were updated. `pytest`: 2372 passed, 12 skipped (17 snapshots) in 105.03 s; ruff clean; mypy 289 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-09 | M4-2 | Done | `scripts/docker_smoke.py` now launches the image's bundled Chromium headless with the scanners' `--no-sandbox`/`--disable-dev-shm-usage` flags and fails unless a page title round-trips; its docstring and PASS line name the check. `docker.yml` scans `bh-arb:ci` with Trivy (`aquasecurity/trivy-action` pinned by SHA) for HIGH/CRITICAL `os,library` CVEs with `ignore-unfixed: true` and `exit-code: 1`; `release.yml` scans `bh-arb:release` the same way. Two `tests/test_deployment_assets.py` tests pin the probe and scan policy; `docs/CI.md` documents both. `pytest`: 2374 passed, 12 skipped (17 snapshots) in 113.54 s; ruff clean; mypy 289 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-09 | M4-3 | Done | Pinned every workflow action to a commit SHA with a `# vX.Y.Z` comment: checkout v4.4.0, setup-python v5.6.0, setup-node v4.4.0, upload-artifact v4.6.2, setup-buildx-action v3.12.0, build-push-action v6.19.2 and Trivy v0.36.0. The Dockerfile base is `python:3.11-slim@sha256:07d48240…b535`. New `tests/test_workflow_pins.py` (3 tests) fails on a moving tag, a bare `FROM`, or a Dependabot config lacking the `github-actions`/`docker` ecosystems; `dependabot.yml`, `docs/CI.md` and `docs/RELEASE.md` document that those ecosystems rewrite the SHA + comment and advance the digest. No workflow behaviour or Docker build content changed. `pytest`: 2377 passed, 12 skipped (17 snapshots) in 113.10 s; ruff clean; mypy 290 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-09 | M4-4 | Done | Wrote **`docs/DEPENDENCY_UPGRADES.md`**, a plan-only row: no pin moved. Measured a throwaway venv (`/tmp/opencode/m44-venv`) with `fastapi==0.162.2`, `starlette==1.10.0`, `mypy==2.4.1`, `ruff==0.17.4` and `httpx2==2.16.0`: full suite green (2,389 collected, exit 0, 17 snapshots, 1 m 50 s, no test change); mypy 2.4.1 reports one `refresh_fixtures.py:212` assignment error; ruff 0.17.4 reports three `UP042` `str, Enum` findings (`MarketType`, `Sport`, `ScrapeKind`); `httpx2` removes the live `StarletteDeprecationWarning` and Starlette resolves it for `TestClient`. The plan splits U4 `httpx2` (dev-only), U1 FastAPI, U2 MyPy (one annotation), U3 Ruff (`StrEnum` with JSON/label assertions), each with steps, acceptance and rollback; `httpx` stays runtime, pydantic/uvicorn stay out of scope. Working tree verification: `pytest` 2,377 passed, 12 skipped (17 snapshots) in 113.82 s; ruff clean; mypy 290 files clean; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-11 | M4-5 | Done | Applied the four M4-4 upgrades as separate commits: **U4** `httpx2==2.16.0` dev-only (runtime lock keeps `httpx==0.28.1`; `starlette.testclient` resolves httpx2, deprecation warning gone; 2 new lock tests), **U1** FastAPI 0.162.2 with Starlette 1.10.0 and no app/test edit, **U2** mypy 2.4.1 with one `dict[str, Any]` annotation in `scripts/refresh_fixtures.py`, **U3** ruff 0.17.4 with `MarketType`/`Sport`/`ScrapeKind` as `StrEnum` (3 new value-string tests in `tests/test_enum_values.py`, no rule ignored). `docs/DEPENDENCY_UPGRADES.md` records the applied set. `pytest`: 2,382 passed, 12 skipped (17 snapshots) in 108.71 s, no warning line; ruff clean; mypy 291 files clean; market doc in sync; refresh_fixtures, audit_admissibility and lock `--check` exit 0. |
| 2026-11-11 | M5-1 | Done | Removed the legacy URL maps: `Surebet.match_urls`, `Surebet.bet_urls`, `Match.bet_url`, `MATCH_URL_TEMPLATES` and `_collect_match_urls`/`_collect_bet_urls`. `SurebetStake.destination` stays the only served destination path; `Match.url` stays. `tests/test_urls.py` keeps only the two parser URL tests. `pytest`: 2,378 passed, 12 skipped (17 snapshots) in 106.61 s; ruff and mypy clean. |
| 2026-11-11 | M5-2 | Done | Removed the unused SQLite `link_sweeps` store: table creation, `Storage.append_link_sweep()`/`prune_link_sweeps()`, the `counts()` key, the maintenance inventory/prune step and window, and `RETENTION_LINK_SWEEPS_DAYS`. `cache/link_sweeps.json` (cap 200) stays the one sweep history; `docs/STORAGE.md` and the maintenance/migration tests were updated. `pytest`: 2,378 passed, 12 skipped (17 snapshots) in 108.48 s; ruff and mypy clean. |
| 2026-11-11 | M5-3 | Done | Deleted the unreachable human approval path: `approve_candidate`, `reject_candidate`, `_approve`, `_approval_blockers`, `_resolve_candidate`, `HUMAN_MAPPING_ENABLED`, `candidate_reviews`, `CANDIDATE_REVIEW_HISTORY_MAX`, the `human_mapping_enabled` payload key and the runtime allowlist writer (`_load_allowlist`/`_save_allowlist`/`ALLOWLIST_FILE`). The suppression reader still honours old decisions; tests now drive `_suppress_candidate` directly, and the 404 route-absence tests stay. `docs/CANDIDATE_REMEDIATION.md` updated. `pytest`: 2,368 passed, 12 skipped (17 snapshots) in 104.83 s; ruff and mypy clean. |
