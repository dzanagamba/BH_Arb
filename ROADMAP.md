# BH_Arb roadmap

The single task list. It holds only **open work**, the rules every task keeps and
a short execution log. Everything closed before 2026-11-11 — every `SR0`…`SR7`
and `M1`…`M7-1` task section with its outcome, the `P*`/`N*` ID glossary, the
"already fixed" list and the full execution log — is kept verbatim in
[`docs/archive/ROADMAP_2026-11-11.md`](docs/archive/ROADMAP_2026-11-11.md).
Look an old ID up there; do not re-open a closed row from it.

## How to use this file

1. Read `docs/SESSION_BRIEF.md`, then this file.
2. Resume a row marked `In progress`. Otherwise take the first `Not started` row
   in the table whose `Depends` are `Done` and whose `Gate` is `—` (or has a
   written operator decision under it).
3. Set it `In progress` **before** coding. One row per session unless the
   operator asks for more.
4. Do only that row's steps. Re-check every `path:line` first; lines drift.
5. Add the named tests, then verify (see `AGENTS.md` → Verify).
6. Tick the acceptance boxes, set `Done`, add an execution-log row with the
   commands and the **measured** output, update `docs/SESSION_BRIEF.md`.
7. Commit only when the operator asks. If blocked, write the blocker under the
   row and stop.

Work the operator asks for that has no row gets a row first (`In progress`).
New IDs continue the existing groups: scraper/feed work is `SR*`, maintenance
and product work is `M*`.

## Definition of done

- Acceptance criteria met and ticked.
- Named tests added; full suite, Ruff, MyPy and the three `--check` scripts pass
  (clean ledger mode locally; also `BH_ARB_TEST_RUNTIME_LEDGER=populated` when
  the change touches the ledger, `config/generated/` or the isolation guard).
- Operator-facing docs updated, including `docs/ACCEPTANCE.md` for any number
  that changes the readiness story; `MARKET_MAPPING.md` regenerated, never
  hand-edited.
- An execution-log row with commands and pasted measurements.
- `docs/SESSION_BRIEF.md` updated.
- No trust rule weakened to make a number look better.

## Rules every task keeps

- The ten trust invariants in `AGENTS.md` are never weakened.
- A scraper failure fails closed: a book that cannot be read is missing from the
  scan, never filled with stale or guessed prices.
- Reliability changes never increase traffic.
- No stealth, TLS impersonation, captcha solving or proxy rotation beyond the
  scoped `launch_browser()` exception recorded in `AGENTS.md`.
- Keep `scrapers/__init__.py` and `engine/__init__.py` lazy.
- New dependencies are pinned in the manifests **and** the regenerated locks
  (`scripts/lock_requirements.py`).
- No bets, no logins; AI may rank candidates but never approve them.
- No new book or market without a capture or a dated absence proof.
- No faster live polling without a push / sub-10 s feed.
- No task lowers the certainty gate.

## Current state (2026-11-11)

One FastAPI process (`main.py` → `server.app:app`) serves the PWA in
`frontend/` and the `/api` routes in `server/api.py`; every `/api` route except
`/api/health` sits behind one key guard. `server.scheduler.scan_loop` runs the
prematch and live feeds when `AUTO_SCAN_*_MINUTES` > 0 (default 0 = on demand).

Ten adapters are declared once in `config/bookmakers.py` and loaded lazily by
`scrapers/registry.py`: seven HTTP (mdshop, betole, evlbet, maxbet, mbet,
sportplus, premier_kladionica) and three browser books (mozzartbet, admiralbet,
wwin) that share one pooled Chromium per scan and call their APIs with an
in-page `fetch`. EVLBet is disabled. Every request goes through the per-book
transport policy, retry budget, rate limiter, deadline and circuit breaker;
every response is validated by a strict wire schema (except EVLBet, SR4-3g) and
fingerprinted for structural drift.

A scan (`server/api.py::run_scan`) scrapes, learns mappings, groups listings
through `engine.matcher.MatchMatcher` + `engine.certainty.CertaintyGate`, runs
skin / stale-price / feed-integrity guards, and prices only `verified` groups in
`engine.arbitrage.ArbitrageEngine`. Heavy stages run in `asyncio.to_thread`.

**Last measured live scan** (2026-11-11, `docs/evidence/2026-11-11-test-scan.md`):
prematch 6,921 matches / 1,359 verified groups / 20 surebets in 139.0 s, all
nine enabled books `ok`; live 183 / 27 / 1 in 29.1 s, with Mozzartbet and Betole
`empty`. Suite size, coverage and lint baselines live in `docs/SESSION_BRIEF.md`.

## Production-readiness checklist

The bar is the "What would make it production-ready" list in
`docs/PRODUCTION_READINESS.md` (assessment dated 2026-11-03; refreshing it is
M8-1). Status measured on 2026-11-11 unless noted; every open line points to the
row or operator decision that closes it.

| # | Criterion | Status 2026-11-11 | Owner |
|---|-----------|-------------------|-------|
| 1 | A real prematch scan returns matches for every configured football book | **Met** for prematch (9/9 enabled). Live misses Mozzartbet and Betole | SR8-1 |
| 2 | `pairing_audit.py --check` under 2 % strict miss rate across several days, zero duplicate-book groups | One scan: **0.4 %** (28 / 6,921), 0 duplicate-book groups, exit 0. "Several days" not measured | operator: N2-4 is deferred |
| 3 | Every published market row mapped or with a dated absence proof | **Not met**: 45,678 / 454,293 prematch rows mapped | SR8-3 (operator) |
| 4 | `price_check.py` 0 outliers over a meaningful comparison count | **Not met**: 26 outliers / 5,622 comparisons (0.46 %, threshold 0.10, scattered over 8 books; whether any reached a served surebet is not measured) | M8-1 decides whether the bar is 0 or a rate |
| 5 | Cold-start replay reaches a fixed point, 0 false merges, 0 unresolved | **Met**: `replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` exit 0, `fixed_point: true`, `false_merges: 0`, `pairs_unresolved: 0` | — |
| 6 | The certified end-to-end test removes a surebet when a claim is spoiled | **Met** (`tests/test_e2e_certified.py` in the suite) | — |
| 7 | No endpoint, config file or UI action can change trust | **Met** (M5-3 removed the last approval path) | — |
| 8 | A 24 h soak shows no memory/browser growth and no stale-book blindness | **Not met**: P1-6 waived; 10-cycle plateau only | operator: the waiver and this criterion conflict |
| 9 | Security hardening applied; not exposed without a key | **Met** in code (M1-1, M1-3); deployment must set `API_KEY` | `docs/DEPLOYMENT.md` |
| — | The committed suite is green | **Not met**: 1 failing test at HEAD | M6-2 |

Two items cannot move without the operator: criterion 2/8 depend on the
deferred N2-4 and waived P1-6. Ask before treating the product as
production-ready while either stands.

## Task table

Closed rows are not listed; see the archive. Order within `Not started` is the
recommended order (by impact).

| ID | Title | Status | Depends | Gate |
|----|-------|--------|---------|------|
| M7-2 | Live test scan and roadmap/brief/AGENTS rewrite | Done | — | — |
| M6-2 | Coverage-floor test still pins the old floor (main is red) | Not started | — | — |
| SR8-1 | Live Mozzartbet and Betole parse to zero matches | Not started | — | — |
| SR8-4 | `record_scan.py` restores state before scanning | Not started | — | — |
| SR8-2 | Structural-drift alarm noise and stale baselines | Not started | — | — |
| M8-1 | Refresh the production-readiness assessment | Not started | M6-2, SR8-1 | — |
| SR8-3 | Mapping-coverage floor vs the full-offer long tail | Not started | — | operator |
| SR4-3g | Strict wire schema: EVLBet | Blocked on a live EVLBet payload | SR4-3 | — |
| N2-4 | Seven-day local opportunity baseline and drift gates | Deferred | — | operator |
| P1-6 | 24-hour soak and resource budget | Waived | — | operator |

## Open task sections

### M7-2 Live test scan and roadmap/brief/AGENTS rewrite

Status: Done

Why: operator asked (2026-11-11) to verify the codebase with a real prematch and
live scan, then rewrite `docs/SESSION_BRIEF.md`, this file and `AGENTS.md` so
work can continue from them.

Acceptance:
- [x] One prematch and one live scan through `run_scan`, restored state kept,
      results in `docs/evidence/2026-11-11-test-scan.md`.
- [x] Every finding from the scan is a row (SR8-1 … SR8-4).
- [x] The old roadmap and brief are archived verbatim under `docs/archive/`;
      this file holds open work only; the brief is short.
- [x] `AGENTS.md` matches the current code and keeps every trust invariant and
      scraper rule unchanged.
- [x] Full verification run; its one failure is pre-existing at HEAD and is
      recorded as M6-2 (docs-only change, no test touched).

### M6-2 Coverage-floor test still pins the old floor (main is red)

Status: Not started

Why: M6-1 (`22519bd`) set `fail_under = 87.05` in `pyproject.toml`, but
`tests/test_ci_hardening.py::test_coverage_is_scoped_and_has_a_measured_floor`
still asserts the literal `"fail_under = 80"` (line 25). The 2026-11-11 full
run: `1 failed, 2371 passed, 12 skipped in 108.50s` — the one failure is this
test, so the committed `main` does not pass its own suite.

Steps: make the test read the floor from `[tool.coverage.report]` (via
`tomllib`) and assert it is a number at or above the previous 80 and no higher
than the measured 88.05 recorded in the comment, instead of a string literal;
keep the `branch = true` and source-scope assertions.

Acceptance:
- [ ] `pytest tests/test_ci_hardening.py` passes; the full suite has 0 failures.
- [ ] Lowering the floor below 80 in a scratch copy makes the test fail.

Tests: `tests/test_ci_hardening.py`.

### SR8-1 Live Mozzartbet and Betole parse to zero matches

Status: Not started

Why: in the 2026-11-11 live scan Mozzartbet (6 requests, 0.74 MB) and Betole
(5 requests, 2.1 MB) answered but yielded 0 matches (`kind: empty`), and both
were `empty` in live in the 2026-11-08 baseline as well. Twice in a row, with
bytes on the wire, at times other books had 20–46 live matches, is unlikely to
be "no live events". Two of nine books are missing from every live scan, so
live surebets are under-counted.

Steps:
1. Capture one live response per book (Mozzartbet through the browser pool,
   Betole through its HTTP policy) with the existing capture tooling; record
   event counts in the raw body.
2. If the body has live events, find where the adapter drops them (endpoint,
   filter, sport id, date window, schema) and fix it; if it truly has none,
   record a dated absence proof and say so.
3. Do not widen schemas blindly: a renamed field stays `schema_drift`.

Acceptance:
- [ ] A dated capture per book in `docs/evidence/`.
- [ ] Either each book parses its live events (measured match count, before →
      after on the same probe) or a dated proof shows the feed was empty.
- [ ] A fixture-based test per fixed adapter pins the live parse.

Tests: `tests/test_wire_schemas_mozzartbet.py`, `tests/test_wire_schemas_betole.py`
or the adapter's live test file; snapshot tests if the output changes.

### SR8-4 `record_scan.py` restores state before scanning

Status: Not started

Why: `scripts/record_scan.py` calls `api.run_scan(mode)` from a fresh process,
so the module globals are empty and the scan rewrites `cache/scan_cost.json`
(and the other diagnostic stores) from nothing, wiping restored per-book
history. The 2026-11-11 test scan had to call `server.app._restore_state()` in
an external driver to avoid it.

Steps: call `_restore_state()` (or a public wrapper of it) before the first scan
in `record_scan.py`; accept several modes in one invocation (`prematch live`)
so a test scan is one command.

Acceptance:
- [ ] After a stubbed scan through the script, pre-existing scan-cost history
      entries survive.
- [ ] `python scripts/record_scan.py prematch live --out <dir>` writes one
      report per mode.

Tests: new `tests/test_record_scan.py` with stubbed adapters (no traffic).

### SR8-2 Structural-drift alarm noise and stale baselines

Status: Not started

Why: the 2026-11-11 scan logged 173 identical `[mozzartbet] structural drift at
offer` warnings (fully suspended offers missing `value`, which SR4-10 accepts),
drift on empty `mbet`/`maxbet` list pages and `wwin` events without `bets`, and
a real `admiralbet` casing change (`sBV*` → `sbv*`) that the parser already
handles. An alarm that fires on every scan hides the one that matters.

Steps:
1. Classify each alarm as benign shape (empty page, all-suspended offer, item
   without optional block) or real change.
2. Benign: do not fingerprint an empty list / item-less page, and emit at most
   one drift warning per book, endpoint and signature per scan.
3. Real (admiralbet casing): re-record the baseline deliberately and say so in
   the log; keep the wire schema accepting both spellings only where the parser
   reads both.
4. Never stop alarming on a removed or renamed required price path.

Acceptance:
- [ ] A rerun scan logs at most one drift line per book/endpoint/signature.
- [ ] Empty pages produce no drift; a removed price path still does (tests).
- [ ] The admiralbet baseline matches the current casing.

Tests: `tests/test_structural_drift.py` (extend).

### M8-1 Refresh the production-readiness assessment

Status: Not started

Why: `docs/PRODUCTION_READINESS.md` is dated 2026-11-03 and predates most of the
SR/M work (it still cites an 80 % coverage floor, an approval path and a
hand-written registry). It is the document that says whether the product is
ready, so it must match measured reality, and its criterion 4 ("0 outliers")
needs a defined comparison count or rate.

Steps: after M6-2 and SR8-1, run one prematch and one live scan (state restored),
`pairing_audit.py --check`, `price_check.py` (both modes), the cold replay and
`mapping` coverage; rewrite the verdict table and the blocker list from those
numbers; update the checklist above. Propose (do not apply) a definition for
criterion 4 and flag criteria 2 and 8 for the operator.

Acceptance:
- [ ] Every number in the refreshed doc is measured and dated, with its command.
- [ ] The checklist in this file matches the doc.
- [ ] `docs/ACCEPTANCE.md` links the refreshed assessment.

### SR8-3 Mapping-coverage floor vs the full-offer long tail — Gate: operator

Status: Not started — needs an operator decision

Why: mapping coverage measured 45,678 / 454,293 rows (≈10 %) prematch and
718 / 89,919 live against `MAPPING_COVERAGE_FLOOR` 0.95. Since SR7-1 fetched full
per-match offers, most rows are markets the registry deliberately does not price
(for example `betole:10`…`betole:18`, 940 rows each), so the warning and its
alert fire every scan.

Options for the operator: (A) measure coverage only over market families the
registry prices (denominator change, floor unchanged); (B) keep the denominator
and set a per-mode floor from a measured baseline; (C) leave it as is. No option
changes what is priced or the certainty gate.

Acceptance (after a decision): the chosen metric is documented in
`docs/METRICS.md`/`docs/ALERTING.md`, measured before → after on a real scan,
and a synthetic regression in a priced family still fires.

### SR4-3g Strict wire schema: EVLBet

Status: Blocked on a live EVLBet payload. The SR6-3 capture was an empty feed;
EVLBet is disabled. Do not start it until a payload with events exists. Full
section in the archive.

### Deferred and waived (N2-4, P1-6)

N2-4 (seven-day opportunity baseline) is **deferred** and P1-6 (24-hour soak)
is **waived** by operator decision (2026-11-05 and 2026-11-04). Do not start or
un-waive either without an explicit instruction. Note that both block
production-readiness criteria 2 and 8 above. Their full sections, steps and
unticked acceptance boxes are in the archive; the soak harness is documented in
`docs/SOAK.md`.

## Rejected (do not reopen without the operator)

| Option | Reason | Brief |
|--------|--------|-------|
| Adopt Scrapy, Crawlee or Crawl4AI | Own adapters and trust gates; borrow patterns only | `research/04_http_reliability_research.md`, `research/05_browser_automation_research.md` |
| `curl_cffi`, playwright-stealth, camoufox, nodriver, undetected-chromedriver, captcha solvers, proxy rotation | Evasion; trust invariant 9 | `research/04_http_reliability_research.md`, `research/05_browser_automation_research.md` |
| `hishel` HTTP caching for prices | Prices must be fresh | `research/04_http_reliability_research.md` |
| `backoff` | Archived | `research/04_http_reliability_research.md` |
| `aiobreaker` / `pybreaker` | Abandoned / sync-only | `research/04_http_reliability_research.md` |
| prometheus-client, structlog, OpenTelemetry | In-house registry and JSON logs cover it | `research/04_http_reliability_research.md` |
| Pact, Schemathesis | Need a cooperating provider or a spec | `research/06_parser_contract_testing_research.md` |
| pandera, Great Expectations | Wrong shape | `research/06_parser_contract_testing_research.md` |
| Browserless | SSPL, remote browser not needed | `research/05_browser_automation_research.md` |
| Selenium, pydoll | No gain over Playwright | `research/05_browser_automation_research.md` |

## Execution log

Entries before 2026-11-11 are in the archive.

| Date | Task | Result | Notes |
|------|------|--------|-------|
| 2026-11-11 | M7-2 | Done | Operator: run a test scan for live and prematch, then rewrite the brief, roadmap and AGENTS. Driver `/tmp/bhscan/scan_both.py` (`_restore_state()` then `record_scan.run(mode)` for each mode). **Measured: prematch 6,921 matches / 1,359 groups (all verified) / 20 surebets, 139.0 s, nine books `ok`, error `5 surebet(s) dropped: a leg was a price outlier`; live 183 / 27 / 1, 29.1 s, `Mozzartbet: returned no matches`, `Betole: returned no matches`.** Mapping coverage 45,678/454,293 prematch, 718/89,919 live (floor 0.95); 173 mozzartbet offer drift lines; scan-cost history 1 → 3 entries (baseline kept); `git status` clean after the scan. Findings → SR8-1 … SR8-4; the full run exposed a pre-existing M6-1 test failure → M6-2; evidence `docs/evidence/2026-11-11-test-scan.md`. Old `ROADMAP.md` and `docs/SESSION_BRIEF.md` copied verbatim to `docs/archive/*_2026-11-11.md`; this file, the brief and `AGENTS.md` rewritten. Verification: `pytest` **1 failed, 2371 passed, 12 skipped in 108.50 s** (the failure is `test_ci_hardening.py::test_coverage_is_scoped_and_has_a_measured_floor`, pre-existing at HEAD, → M6-2); ruff `All checks passed!`; mypy `no issues found in 291 source files`; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-11 | M7-2 review | Done | Operator: check the changes help reach production readiness. Added the production-readiness checklist (criteria from `docs/PRODUCTION_READINESS.md`) with offline measurements: `replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` exit 0 (`fixed_point: true`, `false_merges: 0`, `pairs_unresolved: 0`); `pairing_audit.py --cache cache/last_scan.json --check` exit 0 (`strict_miss_rate: 0.004`, 28 misses, 0 duplicate-book groups, 1,359 groups); `price_check.py` `outliers: 26` over `market comparisons: 5622`. New row M8-1 (refresh the readiness doc); deferred/waived section renamed so existing references resolve. |
