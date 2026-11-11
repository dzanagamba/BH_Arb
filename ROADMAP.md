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

**Leg links** (`engine/destinations.py`, `config/bookmaker_destinations.json`,
`docs/DESTINATIONS.md`): re-proven 2026-11-11 (SR9-1) — 4 of 18 book × mode
cells open a filled ticket, 7 the match page, 7 a labelled fallback.

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
| — | Every surebet leg opens the match or a filled ticket (operator priority) | **Not met**: 2026-11-11 re-check — ticket 4 cells, match page 7 (MaxBet ×2 and WWIN prematch new, MBet live fixed), generic 7 (Mozzartbet live demoted). See `docs/evidence/2026-11-11-destinations.md` | SR9-1 … SR9-4 |
| — | The committed suite is green | **Met** after M6-2 (2026-11-11) | — |

Two items cannot move without the operator: criterion 2/8 depend on the
deferred N2-4 and waived P1-6. Ask before treating the product as
production-ready while either stands.

## Task table

Closed rows are not listed; see the archive. Order within `Not started` is the
recommended order. **SR9 is the operator's number-one priority (2026-11-11):**
work it before every other row.

| ID | Title | Status | Depends | Gate |
|----|-------|--------|---------|------|
| SR9-1 | Re-prove every leg destination on today's sites | Done | — | — |
| SR9-2 | Match-level link or filled ticket for the generic cells | Not started | SR9-1 | — |
| SR9-3 | On-demand browser check of a served surebet's leg links | Not started | SR9-1 | — |
| SR9-4 | Show which legs reach the match; decide whether to hide the rest | Not started | SR9-1 | operator (hide option only) |
| M7-2 | Live test scan and roadmap/brief/AGENTS rewrite | Done | — | — |
| M6-2 | Coverage-floor test still pins the old floor (main is red) | Done | — | — |
| SR8-1 | Live Mozzartbet and Betole parse to zero matches | Not started | — | — |
| SR8-4 | `record_scan.py` restores state before scanning | Not started | — | — |
| SR8-2 | Structural-drift alarm noise and stale baselines | Not started | — | — |
| M8-1 | Refresh the production-readiness assessment | Not started | SR8-1 | — |
| SR8-3 | Mapping-coverage floor vs the full-offer long tail | Not started | — | operator |
| SR4-3g | Strict wire schema: EVLBet | Blocked on a live EVLBet payload | SR4-3 | — |
| N2-4 | Seven-day local opportunity baseline and drift gates | Deferred | — | operator |
| P1-6 | 24-hour soak and resource budget | Waived | — | operator |

## Open task sections

### SR9 — Bookmaker destinations (operator priority 1, 2026-11-11)

Operator: "when the program finds surebets … the links to the bookmakers'
matches [must] actually link to the match in question, or if the bookmaker's site
doesn't work that way, [the link must] create a ticket with the match in
question."

Where it stands (`config/bookmaker_destinations.json`, `engine/destinations.py`,
`docs/DESTINATIONS.md`, all proofs dated 2026-11-03). The ladder is
`ticket_filled` > `match_page` > `search` > `competition`, and a rung is used only
with a confirmed proof. Of the 18 book × mode cells:

| Best rung | Cells |
|---|---|
| `ticket_filled` | MDShop prematch/live, Admiralbet prematch/live (NSoft `ticketItems`; stake not prefilled) |
| `match_page` | Mozzartbet prematch/live, MBet prematch/live, Betole prematch |
| competition / copy only | **SportPlus** prematch/live (prematch has a console prefill script), **Premier Kladionica** prematch/live, **WWIN** prematch/live, **MaxBet** prematch/live, **Betole** live |

Contradiction to settle in SR9-1: `config/bookmaker_deeplinks.json` treats
MaxBet's `/match/<id>` route as `route_pattern_verified` (2026-11-03: "the app
requests `/sportsbook/rest/v2/matches/<id>`"), while the destination record from
the same day says `/match/<id>` "rendered blank" in the operator's browser. The
gate's link half and the dashboard's destination must not disagree about the
same URL.

Boundaries for every SR9 row (trust invariant 9 and the scraper rules): a
"ticket" means **prefilling the book's own slip on the operator's side** — a URL
parameter, a public share/booking code the site itself issues without login, or
a client-side prefill the operator triggers. Never log in, never submit or place
a ticket, never store credentials, never call an endpoint that needs an account.
Destinations never set `deep_link_verified` and never change a group's status;
if SR9-1 shows the gate's declaration is wrong, record it and ask the operator
before changing `config/bookmaker_deeplinks.json`.

### SR9-1 Re-prove every leg destination on today's sites

Status: Done (2026-11-11)

Why: every proof is eight days old and one contradicts the gate (MaxBet). A
link the operator clicks must open the fixture today, not on 2026-11-03.

Steps:
1. Take fresh legs from a real scan (state restored; `docs/evidence/2026-11-11-test-scan.md`
   shows how) — at least two fixtures per book and mode where the book has legs.
2. Open each confirmed route in a real browser (OpenChamber browser panel or the
   Playwright pool, headed where a headless page differs) and record: fixture
   heading seen, selection on the slip seen (ticket rungs), screenshot path.
3. Update each route's `proof` in `config/bookmaker_destinations.json`
   (`checked_at`, `result`, sample, notes); demote a route that no longer works.
4. Settle the MaxBet contradiction with a dated observation in both records'
   notes; if the gate declaration is wrong, stop and ask the operator.
5. Update the tables in `docs/DESTINATIONS.md`.

Acceptance:
- [x] All 18 cells re-checked on 2026-11-11 with a sample fixture, except Betole
      live (no live legs exist to link; SR8-1). Evidence:
      `docs/evidence/2026-11-11-destinations.md`.
- [x] The MaxBet route has one consistent verdict in both records (operator
      decision 2026-11-11).
- [x] `tests/test_destinations.py` passes
      against the updated record; no route is used above its proof.

**SR9-1 outcome so far (2026-11-11).** Links that worked before still work for
Mozzartbet prematch, MDShop and Admiralbet (both modes, slip filled), MBet
prematch and Betole prematch. Three links the dashboard was serving were broken
and are fixed or demoted in `config/bookmaker_destinations.json`:
- MBet live `single-live?id=` is a 404 → now `https://mbet.ba/live?id={event_id}`
  (confirmed in the panel and headless).
- Mozzartbet live used the prematch id, which opens nothing → demoted to the live
  competition page until the adapter carries the live id (SR9-2).
- SportPlus live `/live` is a 404 → `/live/betting`; Premier live `/ponuda/` has
  no live list → `/live`.
MaxBet moves from a home-page fallback to a **confirmed match page**
(`/ba/sportsbook/match/{event_id}`, both modes), and `?outcome=<id>` fills its
slip — SR9-2 wires that up. Tests: `tests/test_destinations.py` gained five
(MaxBet both modes, MBet live, Mozzartbet live demotion, SportPlus live) and its
date check now accepts any re-check from 2026-11-03 on.

**Operator decisions (2026-11-11, recorded):**
1. WWIN prematch link "opens the match" and Betole match link "opens the match"
   in the operator's normal browser. WWIN prematch promoted to a confirmed match
   page; Betole's proof now names the operator check. WWIN live is not yet
   clicked and stays failed.
2. MaxBet gate template: "Change it". `config/bookmaker_deeplinks.json` now
   declares `https://www.maxbet.ba/ba/sportsbook/match/{event_id}` (both modes,
   fallback `https://www.maxbet.ba/ba`); identity and `route_pattern_verified`
   unchanged. `tests/test_maxbet.py` follows the new `Match.url`.

### SR9-2 Match-level link or filled ticket for the nine generic cells

Status: Done (2026-11-11)

Why: for SportPlus, Premier Kladionica, WWIN, MaxBet (both modes) and Betole
live, a surebet leg today opens a generic or competition page, so the operator
must search for the fixture by hand while the price moves.

Steps, per book (one book per sub-commit, cheapest first):
1. Investigate, in the browser and the site's own JS/network traffic, the routes
   that would identify the fixture: a hash/SPA route with the event id, a
   `ticketItems`-like query, a share/booking-code URL the site issues without
   login, or a client-side slip format (as SportPlus `localStorage["cn-prematch.ticket"]`).
2. Prefer `ticket_filled` (the leg's exact selection on the slip), then
   `match_page`. Record each attempt, including failures, in the JSON record.
3. Add the route to `engine/destinations.py` with the identifiers the adapter
   already parses; if the adapter does not carry the needed id, add it to the
   parsed `Match` (no extra request per event unless measured and justified).
4. SportPlus: turn the console prefill into a one-click path if the site
   allows one without login (for example a bookmarklet the operator drags once);
   otherwise keep the honest label.
5. Betole live stays copy-only until it prices live legs (score guard; see
   `docs/DESTINATIONS.md` "Honest limits") — record it and move on.

Leads from SR9-1 (2026-11-11), cheapest first:
- **MaxBet ticket:** keep each outcome's unique `id` (not `outcomeId`) in
  `Market.outcome_ids` in `scrapers/maxbet.py`, then add a `ticket_filled` route
  `https://www.maxbet.ba/ba/sportsbook/match/{event_id}?outcome={outcome_id}`
  (proven in both browsers). Check the list endpoint carries `outcomes[].id`.
- **Mozzartbet live:** parse the live-feed id (equal to the SportPlus/Betradar
  id, e.g. `74723528`) for live rows and restore the live match route with it;
  likely the same change as SR8-1.
- **WWIN live:** `#/match/{event_id}` opens in headless Chromium; promote it after
  an operator click (prematch is already confirmed).
- **SportPlus, Premier:** no per-event or slip URL found yet; investigate the
  SPA routes and slip storage.

Acceptance:
- [x] Each of the nine cells is either upgraded to `ticket_filled`/`match_page`
      with a dated browser proof, or carries a dated proof that the site offers
      neither without login (listing what was tried).
- [x] A unit test per new route builds the URL from a fixture `Match` and
      `SurebetStake` and asserts the exact selection identifiers.
- [x] No new route requires a login, an account endpoint or a ticket submit.

**SR9-2 progress (2026-11-11).** Evidence: `docs/evidence/2026-11-11-sr9-2.md`
and its screenshots. MaxBet is done in both modes: the live list response carries
`odds[].outcomes[].id` (13,180/13,180 rows on the 2026-11-11 probe), the adapter
keeps it in `Market.outcome_ids`, and `?outcome=<row id>` put the leg on the slip
for a prematch fixture (`1027619`, 1 @ 1.55) and an in-play one (`1032215`, 1 @
1.21). A missing row id falls back to the confirmed match page with the reason
`ticket parameters missing`; no extra request. The dated maxbet fixtures were
re-captured so the row id is in the frozen shape (their "unpriced control" total
moved 4.5 → 6.5 because the registry prices 4.5/5.5 now), and the parser
snapshots were regenerated for the new capture. SportPlus (both modes) and
Premier Kladionica (both modes) carry a dated "no URL exists" proof: no router or
per-event route in the served app, no anchors on the offer pages, a row click
leaves the URL unchanged, and Premier's `?who=`/`#/who=` forms are ignored. The
SportPlus script stays a manual copy action: a `javascript:` bookmarklet clicked
in the dashboard runs in the dashboard's origin, not SportPlus's. Betole live is
recorded as copy-only (no live leg is priced). WWIN live is promoted: the
operator opened `#/match/4732588` (Z.Podbrezova – Z.Moravce, a live id from that
day's scan) in a normal browser and it opened the fixture, so the route is a
confirmed match page (the panel still shows WWIN as an empty shell). All nine
cells are now covered. Best rungs of the 18: ticket 6, match page 6, generic 6
(was 4 / 7 / 7 before this pass). Mozzartbet live stays on `/sr/uzivo`: it is not
one of the nine cells and needs the live-feed id from SR8-1 first.

### SR9-3 On-demand browser check of a served surebet's leg links

Status: Done (2026-11-11)

Why: a one-time sample proves a pattern, not today's leg. Before the operator
acts on a surebet, each leg's link should be checked to open that fixture (and,
for ticket rungs, that selection).

Steps: reuse the `server/deeplink_verifier.py` browser path (isolated context, no
cookies kept) to open each leg's destination for **one** surebet on request
(slip "Check links" button → a scoped `/api` route), look for the fixture's team
names (book spelling) and, for ticket rungs, the selection on the slip; return
per-leg `opens_fixture` / `ticket_has_selection` / `failed` with a timestamp.
Operator-triggered only: it never runs per scan, so it adds no scheduled
traffic. It is advisory and never sets `deep_link_verified`.

Acceptance:
- [x] The slip shows a per-leg link check result with its time.
- [x] Offline tests drive the check against HAR/fixture pages for a pass, a
      generic page (fail) and an empty slip (fail).
- [x] The route requires the `scan` scope and is rate-limited per surebet.

**SR9-3 outcome (2026-11-11).** `server/leg_link_check.py` is the check;
`POST /api/surebets/{id}/check-links` (`scan` scope) serves it from the slip's
**Check links** button. Per leg with a `ticket_filled`/`match_page` destination
it opens the URL in its own fresh browser context (one context per leg, so a
filled slip cannot leak into the next leg's check) and judges the rendered
accessibility text: both team names (book spelling from `listings`) for
`opens_fixture`, and for a ticket the text after the page's own slip wording
(Tiket/Listić/Selekcije) must repeat both teams and the pick; a line market also
needs its side and line. An empty slip is caught by the book's own phrase ("Vaš
tiket je prazan") and by the slip-area rule — the FIRST marker, because both
MaxBet and NSoft render a ticket-status widget after the slip. Captured page
texts are in `tests/fixtures/link_check/`: MaxBet filled (`1027619`, 1 @ 1.55
slip), MaxBet empty slip (same fixture, fresh context), MDShop filled
(Manchester City – Fulham), MaxBet home. A leg with only a search/competition
rung is skipped without a browser; the per-surebet window
(`SUREBET_LINK_CHECK_MIN_INTERVAL_SECONDS`, 30 s) refuses a double-click with
429 + Retry-After, a `read`-only key gets 403, and the check shares the deep-link
checker's lock and browser semaphore. The slip panel shows one row per leg,
failed rows marked, the count ("N of M legs open the match") and a live
`data-ago` timestamp, in EN and BS. Tests: `tests/test_surebet_link_check.py`
(27: judge against the four captures, targets, page/route seam, scope, window,
404/409/skip, no gate write) and `tests/test_frontend_link_check.py` (14,
node-driven against the shipped `renderLinkCheckPanel`/`linkStatusLabel`).

### SR9-4 Show which legs reach the match; decide whether to hide the rest — Gate: operator (hide option only)

Status: Not started

Why: the operator must see at a glance whether a surebet can be placed from
links alone.

Steps: on each surebet card show "N/M legs open the match or a filled ticket"
and mark the legs that do not; give the generic legs the copyable book spelling
first. The labelling part is ungated. **Operator decision needed** before adding
an option that hides or deprioritises surebets whose legs cannot reach the match
— it changes what is listed (not the certainty gate) and must not be on by
default without that decision.

Acceptance:
- [ ] Card count and per-leg marking in EN and BS, covered by frontend tests.
- [ ] Hide/deprioritise option implemented only after a recorded decision.

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

Status: Done (2026-11-11)

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
- [x] `pytest tests/test_ci_hardening.py` passes; the full suite has 0 failures.
- [x] Lowering the floor below 80 in a scratch copy makes the test fail
      (`fail_under = 79` → the test failed; file restored).

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
| 2026-11-11 | SR9 | Rows added | Operator: links on a surebet must open the exact match, or create a ticket with it where the site has no match page; make it priority one. Added SR9-1 … SR9-4 above every other row. Measured state from `config/bookmaker_destinations.json`: `ticket_filled` 4 cells (mdshop, admiralbet), `match_page` 5 (mozzartbet, mbet, betole prematch), competition/copy only 9 (sportplus, premier_kladionica, wwin, maxbet, betole live); all proofs `checked_at` 2026-11-03. Recorded the MaxBet contradiction between `bookmaker_deeplinks.json` (`route_pattern_verified`) and the destination record (`/match/<id>` rendered blank). No code changed. |
| 2026-11-11 | SR9-1 | In progress | Re-checked all destinations on that day's fixtures in the OpenChamber panel and headless Chromium (no login, nothing submitted); evidence `docs/evidence/2026-11-11-destinations.md` + screenshots. Fixed in `config/bookmaker_destinations.json`: MBet live → `/live?id=` (old route 404), SportPlus live → `/live/betting` (old 404), Premier live → `/live`, Mozzartbet live match page demoted (prematch id opens nothing); promoted MaxBet match page `www.maxbet.ba/ba/sportsbook/match/{id}` (panel + headless, both modes) and found its `?outcome=` slip prefill. Before → after best rungs: ticket 4 → 4, match page 5 → 6, generic 9 → 8. Full run: `2 failed, 2375 passed, 12 skipped in 107.78s` — M6-2 (pre-existing) and `test_e2e_certified.py` pinning `proof_checked_at == "2026-11-03"`, relaxed to a dated proof ≥ 2026-11-03; rerun of `tests/test_e2e_certified.py tests/test_destinations.py` all passed. Ruff clean, mypy 291 files clean, market doc / refresh_fixtures / audit_admissibility `--check` exit 0. Waiting on the operator: WWIN/Betole click check and the MaxBet gate template. |
| 2026-11-11 | SR9-1 | Done | Operator: WWIN prematch and Betole match links open the match in a normal browser; change the MaxBet gate template. Promoted WWIN prematch (`#/top-bets/match/{event_id}`); Betole proof names the operator check; `config/bookmaker_deeplinks.json` MaxBet template/template_live → `https://www.maxbet.ba/ba/sportsbook/match/{event_id}`, fallback `https://www.maxbet.ba/ba`. Best rungs now: ticket 4, match page 7, generic 7 (was 4 / 5 / 9). Tests: `tests/test_maxbet.py` new `Match.url`; `tests/test_destinations.py` + WWIN prematch test. Full run: `1 failed, 2377 passed, 12 skipped in 125.01s` (the one failure is the pre-existing M6-2 test); ruff `All checks passed!`; mypy `no issues found in 291 source files`; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-11 | M6-2 + docs | Done | Operator: update the README, roadmap and every file that should follow. M6-2: `tests/test_ci_hardening.py` reads `fail_under` via `tomllib` (80 ≤ floor ≤ 88.05, `branch = true`); with `fail_under = 79` the test failed, file restored. README: MaxBet's new declared URL, a **Leg links** dashboard bullet (4 / 7 / 7 of 18), the `record_scan.py` state caveat, lock-file `pip_audit` commands, the 87.05 % branch floor, a Project status section. `docs/PRODUCTION_READINESS.md` status note pointing at the checklist (M8-1 still refreshes it); `docs/ACCEPTANCE.md` coverage line marked superseded; `AGENTS.md` destinations building block. Full run: `2378 passed, 12 skipped in 136.38s` (0 failed); ruff `All checks passed!`; mypy `no issues found in 291 source files`; market doc in sync; refresh_fixtures and audit_admissibility `--check` exit 0. |
| 2026-11-11 | SR9-2 | Done | MaxBet ticket filled in both modes. `scrapers/maxbet.py` keeps each open outcome's own `id` (not `outcomeId`) in `Market.outcome_ids`; `engine/destinations.py` gained `{outcome_id}`; `config/bookmaker_destinations.json` ships `…/sportsbook/match/{event_id}?outcome={outcome_id}` prematch + live with dated proofs. Measured in plain headless Chromium: prematch `1027619` CD Universitario – Herrera FC, slip 1 @ 1.55; live `1032215` CD Ibiza Islas Pitiusas – UD Arenal (HT), slip 1 @ 1.21; the live list response carries `outcomes[].id` on 13,180/13,180 rows. MaxBet fixtures re-captured (`--capture --books maxbet --write`, 2026-10-26 → 2026-11-11); the "unpriced control" total moved 4.5 → 6.5 because the registry prices 4.5/5.5, and the two maxbet parser snapshots were regenerated for the new capture; `contracts.json` now records `[].outcomes[].id:int`. SportPlus and Premier Kladionica (four cells) got dated "no per-event URL" proofs: no router/route in the served app, no anchors on the offer pages, a row click leaves the URL, Premier's `?who=`/`#/who=` forms are ignored. Betole live stays copy-only (no live leg priced). Tests: `tests/test_maxbet.py` +3 (4 cases incl. the two-mode capture check), `tests/test_destinations.py` +3 (ticket URL, missing-id fallback, live ticket), `tests/test_fixture_metadata.py` `pop(key, None)` for freshly captured fixtures. Full run: `2385 passed, 12 skipped in 117.30s` (0 failed); ruff `All checks passed!`; mypy `no issues found in 291 source files`; market doc / refresh_fixtures / audit_admissibility `--check` exit 0. Operator then opened the WWIN live route for `4732588` (Z.Podbrezova – Z.Moravce) in a normal browser and reported it opens the fixture; WWIN live promoted to a confirmed match page with a second test (`test_wwin_live_match_page_is_confirmed_by_the_operator` replaces the old fallback test). All nine cells covered; best rungs 6 ticket / 6 match page / 6 generic (was 4 / 7 / 7). Mozzartbet live stays on `/sr/uzivo` (needs SR8-1's live-feed id). |
| 2026-11-11 | SR9-3 | Done | `server/leg_link_check.py` + `POST /api/surebets/{id}/check-links` (`scan` scope) behind the slip's **Check links** button. Per leg with a ticket or match destination: a fresh browser context, then the rendered accessibility text (`aria_snapshot`, which also sees MaxBet's closed shadow DOM), both book-spelled team names for `opens_fixture`, and for a ticket the slip area after the FIRST slip marker must repeat the teams and the pick (side + line for totals); an empty slip fails on the book's own phrase. A surebet with only search/competition rungs is skipped without a browser. Per-surebet window 30 s (`SUREBET_LINK_CHECK_MIN_INTERVAL_SECONDS`, 429 + Retry-After), a `read`-only key gets 403, a scan in progress 409, and the check shares `_deep_link_check_lock` + `_browser_sem` with the deep-link checker; it never writes `deep_link_verified`. Captured page texts in `tests/fixtures/link_check/` (MaxBet filled `1027619` and empty slip, MDShop filled, MaxBet home). Tests: `tests/test_surebet_link_check.py` 27, `tests/test_frontend_link_check.py` 14 (node-driven against the shipped renderer). Full run: `2425 passed, 12 skipped in 105.07s` (0 failed); ruff `All checks passed!`; mypy `no issues found in 294 source files`; market doc / refresh_fixtures / audit_admissibility `--check` exit 0. |
