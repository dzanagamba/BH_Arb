# BH_Arb — Project Audit & Development Roadmap

**Last updated:** 2026-11-04
**Repository:** `dzanagamba/BH_Arb` (`main`)
**Status of this document:** audit complete; P0-1 through P0-7 and P1-1 through P1-5 and P1-7 done; P1-6 waived by operator; P2/P3 implementation continuing
**Purpose:** a durable, session-by-session plan so work can resume without re-reading the whole repository.

> **How to use this document**
>
> 1. Read the audit snapshot and the task table first.
> 2. Pick the first task whose dependencies are `Done` and whose status is `Not started`.
> 3. Change its status to `In progress` **before** coding.
> 4. Do only that task. Verify it, then update the task checkboxes, status, and the execution log at the bottom.
> 5. If a task is blocked, write the blocker in its Notes and stop; do not silently work around trust or safety rules.
>
> **Definition of done for every task**
>
> - Acceptance criteria are met and checked off.
> - New/updated tests pass; the full offline suite, Ruff, MyPy, and the generated-market-doc check pass.
> - User-facing or operator-facing docs are updated (README, `docs/`, or this file).
> - The execution log has a dated entry with commands and measured results.
> - No trust rule is weakened to make a number look better.

---

## 1. Audit snapshot

### 1.1 What the project is

BH_Arb is a **research-grade arbitrage scanner for the Bosnian bookmaker market**. It:

- scrapes ten configured books (nine enabled; EVLBet is disabled because its football feed returns nothing),
- normalizes team, league, market, and sport identity,
- groups listings that describe the same real-world event,
- prices only groups that pass the deterministic **certainty gate**,
- re-checks a selected surebet against fresh odds,
- presents the result in a static dashboard and a FastAPI API,
- and explicitly **never logs in, moves money, or places a bet**.

The central safety property is: *a surebet is shown only when the same-event claim is proven.* A false merge is treated as worse than a missed match.

### 1.2 Architecture

```text
main.py / uvicorn
  └─ server/app.py            FastAPI app, middleware, lifespan, static dashboard
       ├─ server/api.py       routes, scan orchestration, caches, candidates, verify
       ├─ server/scheduler.py unattended scan loop
       └─ server/mapping_coverage.py

scrapers/*.py                 one adapter per book
  └─ scrapers/base.py         Playwright launcher, HTTP retry, page batching
  └─ scrapers/common.py       shared parsing, NSoft helpers, deep-link declarations

engine/
  ├─ normalizer.py            canonical team/league/country/market names
  ├─ name_identity.py         conservative name identity rules
  ├─ sports.py                sport-specific cleaning and identity
  ├─ team_resolver.py         transitive alias chains, contradiction splitting
  ├─ league_resolver.py       league fuzziness resolved by team-set fingerprints
  ├─ mapping_learner.py       learns claims from shared fixtures
  ├─ mapping_evidence.py      durable provenance ledger
  ├─ matcher.py               candidate scoring, grouping, orientation
  ├─ certainty.py             the only authority that says `verified`
  ├─ market_registry.py       per-book market IDs and label rules
  ├─ market_discovery.py      label/structure/consensus classification
  ├─ market_consensus.py      cross-book devig/median price checks
  ├─ price_guard.py           drops outlier legs
  ├─ arbitrage.py             stake split and worst-case pricing
  ├─ destinations.py          honest deep-link ladder
  └─ ai.py                    propose-only AI ranking

models/schemas.py             Pydantic models shared by every layer
config/                       settings, registries, mappings, evidence ledger
frontend/                     static HTML/CSS/JS dashboard, no bundler
scripts/                      operator tools and reproducible measurements
tests/                        offline pytest suite + frozen fixtures
cache/                        gitignored runtime state
docs/                         design, acceptance, evidence, handoff
```

### 1.3 Verified baseline (2026-11-04)

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest` | **1,251 passed**, 1 warning, 183 s |
| Lint | `python -m ruff check .` | clean |
| Types | `python -m mypy .` | clean on 134 source files |
| Generated market doc | `python scripts/generate_market_mapping_doc.py --check` | in sync |
| Cold replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` | exit 0, fixed point, 0 unresolved evidence-backed pairs |

Current real-data shape (from `cache/last_scan.json`, 2026-11-03):

| Metric | Value |
|---|---:|
| Cached matches | 7,666 |
| Cached match groups | 1,231 |
| Cached surebets | 11 |
| Cache file size | **218.5 MB** |
| Matches JSON | 17.5 MB |
| Match-group JSON | **133.1 MB** |
| Cache parse time | 2.51 s |
| Evidence ledger | 23.6 MB / 4,632 claims |
| Team alias allowlist | 3,333 entries |
| Matcher initialization | 0.72 s |

### 1.4 Strengths worth preserving

- **A real trust model.** `engine/certainty.py` is the only authority; every gate emits `MatchEvidence`; `verified` means zero outstanding reasons.
- **Safety is local, not ambient.** `find_surebets` and `evaluate_market` both refuse non-`verified` groups.
- **Documentation discipline.** `tests/test_readme_claims.py` runs the real gate against documented claims; replay and cold-start are reproducible.
- **Offline test discipline.** 1,251 tests run without bookmaker access; captured payloads live under `tests/fixtures/markets/`.
- **Honest deep-link ladder.** A link is never labeled "ticket" without a dated proof.
- **Price-quality work.** Price guard, per-book margin checks, two-source high-edge rule, and cross-book consensus are materially stronger than typical hobby scanners.
- **Security basics.** Loopback default, API-key guard on all `/api` reads, same-origin write guard, rate limits, and security headers.

### 1.5 Findings, in risk order

| # | Severity | Finding | Evidence | Impact |
|---|---|---|---|---|
| F1 | **High** | Cached group evidence embeds the entire 3,333-entry alias allowlist in every allowlisted team match. | `engine/certainty.py` records `sorted(self.alias_allowlist)` for `team_source == "allowlist"`; one group had 4 evidence entries of 97.5 KB each. | 133 MB of groups, 218 MB cache, 2.5 s parse, large `/api/debug/report`, inflated soak baseline. A pure payload bug, no trust loss. |
| F2 | **High** | Dashboard uses inline `on*` handlers and interpolates JSON strings into them. | `frontend/js/app.js` copy buttons embed `JSON.stringify(...)` inside `onclick`; `escapeHtml` does not make a value safe inside a JavaScript string in an HTML attribute. | A team/fixture name containing a quote or `)` can break the button and may become script injection from scraped data. It also blocks a strict CSP. |
| F3 | **High** | Runtime freshness is only enforced at scan time and only checked at startup for the restored cache. | `_load_cache` drops files older than 30 min **on startup**; a running server keeps serving `last_scan.json` until the next scan. | The dashboard can present hours-old "surebets" as current; the UI shows an age but has no hard stale state. |
| F4 | **Medium** | README's gate-vocabulary section is stale and the test probe has a blind spot. | README says `orientation_unresolved` is never emitted; `engine/certainty.py` emits it for a Betradar-id match with an unresolved orientation, and `tests/test_certainty.py` asserts it. The README's rejected row also omits `sport_mismatch`. | Operators and future sessions are told a false fact about the safety gate. This is the project's documented recurring defect class. |
| F5 | **Medium** | `config/bookmaker_deeplinks.json` is cached for the process lifetime. | `scrapers/common.py:_deeplink_cache` is populated once and never invalidated. | Editing a declaration requires a restart; `/api/health` can expose an old map. |
| F6 | **Medium** | `/api/debug/report` returns every group and all evidence with no pagination. | `server/api.py:get_match_report` returns `report_cache` directly. | After F1 is fixed it is still several MB; the link in Settings can freeze a browser tab. |
| F7 | **Medium** | No deployment, alerting, or metrics story. | No `Dockerfile`, no systemd unit, no `/metrics`, no notification transport; soak is manual. | The scanner is a local research tool, not an operable service. The docs already call operations "Partial". |
| F8 | **Medium** | CI checks correctness but not dependency risk or coverage. | `.github/workflows/ci.yml` runs Ruff, MyPy, generated-doc check, pytest. No `pip-audit`, no Bandit, no coverage threshold, single Python version. | A vulnerable dependency or a coverage regression is invisible. |
| F9 | **Medium** | Market identity is complete for NSoft but not for every parser. | Only the NSoft parser publishes `source_id`; `docs/PRODUCTION_READINESS.md` lists this as a blocker. | Discovery and registry coverage cannot be audited uniformly per book. |
| F10 | **Medium** | Candidate review is dominated by pairs no human can close. | The docs record ~77% league-blocked candidates and 8,618 unresolved pairs on a real scan. | Operator attention is diluted; queue metrics can look like coverage progress when they are not. |
| F11 | **Low/Medium** | Persistence is a fixed 50-entry JSON history; no bet log, bankroll, or CLV. | `_HISTORY_MAX = 50`; no models or endpoints for placed bets. | No longitudinal evaluation of whether the tool's edges persist. |
| F12 | **Low** | Documentation and config are dated but not automatically freshness-checked. | Declaration notes and evidence docs carry dates but no expiry/audit test. | A stale declaration can remain load-bearing longer than intended. |
| F13 | **High** | No opportunity-rate or arb-lifetime metric. The dashboard reports groups and surebets but not the denominator. | A public board log found only **1.34%** of 115,583 boards crossed, and only **26** of 1,553 crossings were actionable after gates. BH_Arb reports 11 surebets but no crossing rate. | A zero-surebet scan cannot be distinguished from a coverage failure. Cannot tune filters or prove the edge is real. |
| F14 | **High** | No per-book feed-integrity score or stale-book quarantine. | Price guard drops outlier legs per surebet, but a book that is stale/suspended can still supply the "best" price on the next group. Reddit/vendor consensus names stale odds the main phantom-arb source. | Phantom arbs can survive into the list; a bad feed is invisible until a human notices. |
| F15 | **Medium** | The only known twin-feed pair is hardcoded (MDShop/Admiralbet = NSoft). | `config/settings.py:PRICE_SOURCES`; a public project measured Ladbrokes/Neds as **99.9% identical** across 11,198 shared markets. | Two books on one feed can be treated as independent and manufacture a false edge; a real twin pair could be missed. |
| F16 | **Medium** | Displayed margins are derived server-side and are not recomputable from the served odds. | `/api/results` and the slip use `profit_percent`/`total_margin`; the frontend does not recompute from raw prices. | A rounding or pricing bug is invisible; the UI cannot prove the number it shows. |
| F17 | **Medium** | Event-identity edge cases are not explicitly tested. | The gate is strong on names/IDs, but there are no fixtures for same-day doubleheaders, same teams meeting twice, or kickoff near a date/bucket boundary. | A wrong merge or a split can appear in exactly the fixtures where names are identical. |
| F18 | **Medium** | Silent data loss is only partially measured. | The pairing audit finds same-fixture misses; it cannot answer "which book/sport/market is expected but absent?" The `sports-betting` docs call this the most dangerous failure: missing odds look like a smaller dataset. | Coverage can fall without an alert, and a backtest looks clean while being incomplete. |
| F19 | **Low/Medium** | All books are treated as one risk class. | No soft/sharp/exchange label, no per-book max-stake warning, no account-risk context. | The advisory output can recommend a leg at a book that will limit or reject it, with no warning. |

### 1.6 What is already fixed and should not be re-opened

These were open in `docs/HANDOFF.md` and are now implemented; keep them out of the TODO:

- `MatchGroup.evidence` is persisted and served (but see F1/F6 for payload cost).
- `group_matches` is order-insensitive and has a fall-through path.
- `build_targets` has `settled` + `offset` and converges.
- Prematch expiry uses the latest kickoff plus a two-minute buffer.
- `premier_kladionica` live BTTS and the NSoft live window have regression tests.
- `orientation_unresolved` is emitted, tested, and documented in the README.
- The approve/reject HTTP routes are gone; Diagnostics is read-only.

---

## 2. Research summary and what to adopt

The project already reflects most of the mature practice in this space. The research below is therefore used to choose **what to add**, not to justify a rewrite.

### 2.1 Event identity and entity resolution

**Consensus:** provider IDs first, reviewed/canonical aliases second, fuzzy similarity only to *find candidates*, never to confirm. A false merge is worse than a split. Keep qualifiers (`U21`, `Women`, reserve, academy, digits) that identify a different roster. Use a shared opponent to find splits, not name similarity.

**Sources:**

- [Dozor — matching the same esports match across 27 bookmakers](https://dev.to/dozor/matching-the-same-esports-match-across-27-bookmakers-entity-resolution-in-go-2dg5)
- [Reep — entity resolution applied to football](https://reep.football/entity-resolution)
- [How to normalise odds across bookmakers — OddsRelay](https://oddsrelay.io/blog/how-to-normalise-odds-across-bookmakers)
- [How to match event names across bookmakers — Betting52](https://betting52.com/betting-tools/match-event-names-across-bookmakers/)

**Adopt:**

- Competition-scoped aliases where possible; a global alias for a common token is a risk.
- A candidate-quality report that separates "actionable by an alias" from "league-blocked" (F10).
- Keep the existing Betradar-first, ledger-second, conservative-name rules. Do not replace them with a score threshold.

### 2.2 Freshness, polling, and live data

**Consensus:** pre-match polling every 30–60 s is normal; live needs a push/sub-10 s path. Stale odds and event-matching errors are the two main sources of phantom arbs. Streaming removes *your* poll interval, not the book's capture interval.

**Sources:**

- [SharpAPI — how live is real-time odds data](https://sharpapi.io/learn/how-live-is-real-time-odds-data)
- [Odds API — how a real-time odds feed works](https://odds-api.io/blog/odds-feed-api)
- [PulseScore — REST vs WebSocket vs delta streams](https://pulsescore.net/blog/live-odds-rest-vs-websocket-vs-delta-streams)
- [Sportsbook API integration guide](https://www.apibetting.com/guides/sportsbook-api-integration)

**Adopt:**

- A per-feed and per-book freshness budget, surfaced in `/api/results` and the dashboard (F3).
- Do **not** raise live polling until a push path or sub-10 s capture is actually available. Keep the existing 60 s live TTL and 600 s prematch TTL.
- Measure push-feed availability per book and add a WebSocket adapter only where it is materially fresher than polling (P2-10).
- Add a last-known-value / "price moved" state rather than silently re-pricing a different bet.

### 2.3 Arbitrage economics and execution

**Consensus:** real reachable edges are usually 0.5–5%; >5% is often stale, void, or two non-equivalent markets. Account limits and partial acceptance are the binding practical constraints. This project correctly stays advisory.

**Sources:**

- [Clawarbs — what arbitrage is and its risks](https://clawarbs.com/blog/what-arbitrage-betting/)
- [OddsShopper — how books limit arbers](https://www.oddsshopper.com/articles/betting-101/arbitrage-betting-limits-getting-banned)
- [The complete arbitrage guide 2025](https://picktheodds.app/en/blog/arbitrage-betting-the-complete-guide-in-2025)

**Adopt:**

- Keep the two-source high-edge cap, price guard, and consensus checks.
- Add per-book stake-limit fields and a partial-acceptance workflow as **advisory** features (P3).
- Do not add auto-placement. It contradicts the product's stated non-goal and the account-risk reality.

### 2.4 Similar open-source scanners

| Project | Useful idea | What not to copy |
|---|---|---|
| [cengizmandros/odds-arb-scanner](https://github.com/cengizmandros/odds-arb-scanner) | Simple FastAPI + CLI split; TTL odds cache; clear arb math. | Single-API dependency; no identity proof. |
| [nickkatsios/BetEdge](https://github.com/nickkatsios/BetEdge) | Dockerized scraper/backend/frontend separation; scheduler. | Selenium-heavy; MySQL without the trust model. |
| [TessaRichardson/SureBetsBot](https://github.com/TessaRichardson/SureBetsBot) | Kelly-style sizing; modular fetcher/calculator/UI. | Mock-first; no real cross-book identity. |
| [smartworkersai/KOS](https://github.com/smartworkersai/KOS) | Supervised async tasks; state machine; alerting. | Different product (matched betting); external API dependence. |
| [DeliciousPipe1326/edge-scanner](https://github.com/DeliciousPipe1326/edge-scanner) | Arb + middles + EV tabs; sharp-book reference. | The Odds API only; no Bosnian books. |
| [HintikkaKimmo/surebet](https://github.com/HintikkaKimmo/surebet) | Clean odds-format conversions and stake math. | Library, not a scanner. |

**Adopt:** a small CLI/daemon split already exists through `main.py` + `scripts/`; keep it. Add Docker and health checks (P1). Do not import a generic fuzzy matcher: this repo's gate is deliberately stricter.

### 2.5 Operational and API practice

**Consensus:** avoid returning more data than the screen needs; paginate large collections; compress or stream large responses; put blocking work off the event loop; expose metrics and health; make deployment reproducible.

**Sources:**

- [FastAPI response compression discussion](https://github.com/fastapi/fastapi/discussions/8571)
- [Configuring API response compression](https://oneuptime.com/blog/post/2026-01-25-configure-api-response-compression/view)
- FastAPI/pydantic performance guidance (orjson, response models, pagination).

**Adopt:** fix F1 first (the payload is mostly duplicated data, not a transport problem), then paginate F6, then consider gzip/orjson only if measurements still justify it.

### 2.6 Deep research addendum — arbitrage economics, communities, and data processing

The full research record is `docs/RESEARCH_ARBITRAGE_2026-11-04.md`. It adds four findings that change the order of work:

1. **A zero-surebet scan is not automatically a bug.** A public board log measured only **1.34%** of 115,583 boards crossing, and only **26** of 1,553 crossings survived profit/margin gates. BH_Arb currently reports groups and surebets but not the crossing rate, so it cannot tell "no edge today" from "the feeds are broken." This is F13 and task P0-6.
2. **Stale books are the main phantom-arb source.** Vendor docs, the `Rijul0107` backtest, and Reddit threads all converge on stale/suspended prices and palpable errors. The existing per-surebet price guard is good, but a per-book integrity score and quarantine state are missing. This is F14 and task P0-7.
3. **Two books can be one price source.** `Rijul0107` measured Ladbrokes/Neds as **99.9% identical** across 11,198 shared markets. BH_Arb hardcodes only the NSoft pair. A measured identical-price matrix would find both false twins and missing twins. This is F15 and task P2-7.
4. **The community's recurring failure is maintenance, not math.** Arbusers developers warn that bookmaker sites change, IPs get blocked, and a scraper needs ongoing work; Reddit warns that a 30-second cycle across five books is already too slow for many arbs. The durable response is not more clever matching; it is a smaller, observable, testable pipeline. This is F18 and task P2-9.

Community evidence is anecdotal: Reddit blocks automated fetching (HTTP 403), so the research doc uses search-index snippets of the named threads rather than full reads. The forum threads (Arbusers) were read directly. Do not treat any forum claim as a measured fact.

**What not to copy:** auto-execution, account-longevity evasion (stake jitter, "mug betting", multi-account rotation), proxy/fingerprint evasion as a core feature, and lowering the gate to raise the count. The scanner stays advisory and public-data-only.

---

## 3. Roadmap overview

| ID | Task | Priority | Effort | Depends on | Status |
|---|---|---|---|---|---|
| P0-1 | Bound the cached evidence payload | P0 | S | — | Done |
| P0-2 | Dashboard XSS + inline-handler + CSP hardening | P0 | M | — | Done |
| P0-3 | Gate-vocabulary truth audit and probe strengthening | P0 | S | — | Done |
| P0-4 | Runtime freshness and stale-state policy | P0 | M | — | Done |
| P0-5 | Reloadable deep-link declarations | P0 | S | — | Done |
| P0-6 | Opportunity-rate and arb-lifetime telemetry | P0 | M | P0-4 | Done |
| P0-7 | Feed-integrity scorecard and stale-book quarantine | P0 | M | P0-4 | Done |
| P1-1 | Paginated, filtered group-evidence API | P1 | M | P0-1 | Done |
| P1-2 | Structured logs, request IDs, metrics endpoint | P1 | M | — | Done |
| P1-3 | Reproducible deployment (Docker/systemd) | P1 | M | — | Done |
| P1-4 | CI hardening: coverage, dependency and security scans | P1 | S | — | Done |
| P1-5 | Alerting with dedupe and retry | P1 | M | P1-2 | Done |
| P1-6 | 24-hour soak and resource budget | P1 | M | P0-1, P1-2 | Waived |
| P1-7 | Raw-price invariant and rounding audit | P1 | S | P0-4 | Done |
| P2-1 | Convergent deep-link sweep automation and UI | P2 | M | P1-1 | Done |
| P2-2 | Dated re-verification of no-event declarations | P2 | S | — | Done |
| P2-3 | Publish `source_id` from every parser; complete registry coverage | P2 | L | — | Done |
| P2-4 | Multi-day replay corpus and precision/recall evaluation | P2 | L | — | Done |
| P2-5 | Sports expansion with measured admissibility | P2 | L | P2-4 | Done |
| P2-6 | Candidate-queue quality and coverage metrics | P2 | M | P0-1, P1-1 | Done |
| P2-7 | Identical-feed ("skin") detection | P2 | M | P0-7 | Done |
| P2-8 | Event-identity edge cases: doubleheaders and rematches | P2 | M | P2-4 | Done |
| P2-9 | Silent-drop coverage budget | P2 | M | P0-7 | Done |
| P2-10 | Measured push-feed discovery and per-book WebSocket adapter | P2 | M | P0-4, P0-7 | Done |
| P3-1 | Persistent storage v2 (SQLite) and migration | P3 | L | P0-1, P1-1 | Done |
| P3-2 | Bet log, bankroll, and CLV analytics | P3 | L | P3-1 | Done |
| P3-3 | Advisory execution workflow and limits | P3 | M | P3-2 | Done |
| P3-4 | Alerts, PWA, accessibility, and Bosnian UI | P3 | M | P1-5 | Not started |
| P3-5 | Authentication and key management hardening | P3 | M | P1-3 | Not started |
| P3-6 | Book risk profiles and advisory pacing | P3 | M | P1-7 | Not started |
| P3-7 | Record-only / paper-trading mode | P3 | M | P3-1 | Not started |

**Recommended first session:** P0-1, then P0-3 (both small, measurable, and they remove the largest payload and the most misleading documentation). Then P0-4 and the two research-driven tasks, P0-6 and P0-7: without a crossing-rate baseline and a feed-integrity score, the dashboard cannot tell "no edge" from "broken data." P0-2 is a separate hardening session.

---

## 4. Task details

### P0-1 — Bound the cached evidence payload

**Status:** Done
**Priority:** P0 (critical)
**Effort:** S (one session)
**Depends on:** none

**Objective:** stop persisting the entire team-alias allowlist in every evidence record; persist only the alias entries that actually proved the pair.

**Expected outcome:** one 9-book scan cache drops from ~218 MB to roughly 25–35 MB; match-group JSON drops from ~133 MB to ~8 MB; cache parse time drops from ~2.5 s to well under 1 s; `/api/debug/report` becomes usable without pagination for a moderate scan.

**Steps:**

1. In `engine/certainty.py`, replace `allowlist_entries=sorted(self.alias_allowlist)` with a helper that returns only the matching entries.
2. Build the matching index once per allowlist snapshot (the existing `_allowlist_index` cache is the right place), mapping a normalized unordered pair to the original allowlist entries.
3. Keep the evidence semantics: the record must name the entry (or entries) that proved the pairing. It must not become empty for an allowlisted proof.
4. Add a regression test that builds an allowlisted pair, serializes the group, and asserts the evidence payload is bounded by the matched entries, not the allowlist size.
5. Measure a real or fixture-based 9-book cache before/after and record the numbers in `docs/ACCEPTANCE.md` and the execution log.
6. Add a guard/health metric for cache size so this cannot regress silently.

**Acceptance criteria:**

- [x] No `MatchEvidence.allowlist_entries` contains the full allowlist.
- [x] An allowlisted group still carries the exact entry that proved it.
- [x] A synthetic 9-book group's serialized size is bounded by its own data, not by `len(alias_allowlist)`.
- [x] A real/fixture cache is under 40 MB and match-group JSON under 15 MB.
- [x] Cache restore remains semantically identical (same groups, same statuses, same surebets).
- [x] `python -m pytest`, `ruff`, `mypy`, and the generated-doc check pass.

**Tests:**

- New: `tests/test_certainty.py::test_allowlist_evidence_records_only_the_proving_entry`
- New: `tests/test_cache_serialization.py::test_cached_group_payload_is_bounded`
- Existing: `tests/test_e2e_certified.py`, `tests/test_readme_claims.py`, `tests/test_replay.py`
- Manual measurement: `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check`

**Notes / risks:** The gate's *decision* must not change. This is a serialization/evidence-cardinality fix only. Do not remove `allowlist_entries`; reviewers need the proof.

---

### P0-2 — Dashboard XSS + inline-handler + CSP hardening

**Status:** Done
**Priority:** P0
**Effort:** M
**Depends on:** none

**Objective:** remove inline event handlers, stop building JavaScript string literals inside HTML attributes, and adopt a strict nonce-based CSP.

**Expected outcome:** a team or league name containing `'`, `"`, backtick, `)`, or `</script>` cannot break a copy button or execute code; `script-src` no longer needs `'unsafe-inline'`.

**Steps:**

1. Inventory every `onclick=`, `oninput=`, and other inline handler in `frontend/index.html` and `frontend/js/app.js`.
2. Replace them with delegated or directly attached `addEventListener` handlers and `data-*` attributes.
3. Replace `copyText(${escapeHtml(JSON.stringify(...))})` patterns with a data attribute plus a listener that reads the value from the dataset.
4. Add a small `escapeAttr`/dataset helper if needed; never interpolate JSON into an attribute.
5. Generate a per-request nonce in `server/app.py`, put it on the page's script tags, and set `script-src 'self' 'nonce-…'`; remove `'unsafe-inline'` from `script-src`.
6. Keep `style-src` as-is only if no nonce path is practical; document the remaining gap if any.
7. Add tests for quoted/malicious names and header assertions.

**Acceptance criteria:**

- [x] No `on*=` attributes in shipped HTML or JS.
- [x] A fixture team name such as `O'Brien "X" <img src=x onerror=alert(1)>` renders as text and its copy button still works.
- [x] CSP response contains a nonce and no `script-src 'unsafe-inline'`.
- [x] Existing dashboard behavior and keyboard navigation are unchanged.
- [x] `tests/test_security_headers.py` and `tests/test_frontend_*.py` pass.

**Tests:**

- New: `tests/test_frontend_xss.py` (Node-run DOM assertions or string-level checks for the shipped source)
- New: `tests/test_csp_nonce.py`
- Existing: `tests/test_security_headers.py`, `tests/test_frontend_review.py`, `tests/test_frontend_empty_state.py`

**Notes / risks:** The dashboard is a static file; a nonce requires injecting a placeholder or serving the HTML through a small response builder. Do not add a bundler for this.

---

### P0-3 — Gate-vocabulary truth audit and probe strengthening

**Status:** Done
**Priority:** P0
**Effort:** S
**Depends on:** none

**Objective:** make the README's status/reason table and `HARD_REJECT_REASONS` agree with what the gate actually emits, and make the probe exercise every emitted reason.

**Expected outcome:** a reader can trust the table; the test fails if a reason is added, removed, or misclassified.

**Steps:**

1. Extend `_observed_reasons()` in `tests/test_readme_claims.py` with the Betradar-id orientation tie (`orientation_unresolved`) and a cross-sport pair (`sport_mismatch`).
2. Decide where `sport_mismatch` belongs in the vocabulary: it is an explicit `rejected` result, not a member of `HARD_REJECT_REASONS`.
3. Update README's `rejected` row to include `orientation_unresolved` and `sport_mismatch`, and delete the "never emits" wrinkle.
4. Add a test that asserts the documented reason vocabulary is exactly the observed vocabulary (no hand-maintained "dead" exceptions unless the code truly has one).
5. Search for other comments/docs that describe the gate's behavior and reconcile them.

**Acceptance criteria:**

- [x] `_observed_reasons()` produces `orientation_unresolved` and `sport_mismatch`.
- [x] README's table lists every observed reason under the correct status.
- [x] No documentation claims a reason is unreachable when `tests/test_certainty.py` proves otherwise.
- [x] The test suite fails if a new reason is added without documentation.

**Tests:**

- `tests/test_readme_claims.py::test_status_reason_vocabulary_matches_what_the_gate_emits`
- `tests/test_readme_claims.py::test_dead_hard_reject_vocabulary_is_documented_as_dead` (rewrite or remove)
- `tests/test_certainty.py::test_same_betradar_id_without_an_orientation_is_not_verified`

**Notes / risks:** This is the project's documented recurring defect class. Prefer an exact observed-vocabulary check over prose assertions.

---

### P0-4 — Runtime freshness and stale-state policy

**Status:** Done
**Priority:** P0
**Effort:** M
**Depends on:** none

**Objective:** make staleness a first-class runtime state, not a startup-only cache check.

**Expected outcome:** the API and dashboard can say "this feed is stale" and refuse to present an old surebet as current. A scan older than the configured TTL has an explicit state, and every leg carries its age.

**Steps:**

1. Add a `freshness` block to `/api/results` (mode, scan age, TTL, stale flag, per-book oldest/newest `fetched_at`, stale books).
2. Define the policy in `config/settings.py` (prematch and live TTLs already exist; add a per-book budget if useful).
3. In the dashboard, show a prominent stale banner and disable copy/verify actions that imply current prices when the feed is stale.
4. Keep the cached data visible for diagnosis, but label it as historical.
5. Add API and frontend tests for fresh, near-expiry, and stale feeds.
6. Document the policy in README and `docs/ACCEPTANCE.md`.

**Acceptance criteria:**

- [x] `/api/results` reports `stale`, `age_sec`, `ttl_sec`, and per-book freshness.
- [x] A stale feed is visually distinct and cannot be mistaken for a live opportunity.
- [x] The verify endpoint remains the only path that can re-establish a leg's current price.
- [x] Existing cache/restore behavior is unchanged for fresh data.

**Tests:**

- New: `tests/test_freshness_api.py`
- New: frontend test for the stale banner and disabled actions
- Existing: `tests/test_cache_serialization.py`, `tests/test_verify_surebet.py`

**Notes / risks:** Do not delete stale data; diagnosis needs it. The goal is labeling and action-gating, not hiding.

---

### P0-5 — Reloadable deep-link declarations

**Status:** Done
**Priority:** P0
**Effort:** S
**Depends on:** none

**Objective:** make an edit to `config/bookmaker_deeplinks.json` take effect without a process restart.

**Expected outcome:** `/api/health` reports the declaration file's load time/hash; the gate uses the new map after the file changes; a malformed file fails safe and says so.

**Steps:**

1. Track the declaration file's mtime/size (or a content hash) alongside `_deeplink_cache`.
2. On each `_load_deeplink_config()` (or a cheap `maybe_reload`), reload when the signature changes.
3. Keep the fail-safe behavior for a missing/malformed declaration.
4. Expose `loaded_at`, `source_mtime`, and a `stale` flag in `effective_deeplink_declarations`.
5. Add tests that rewrite a temp config and observe the new declaration without restarting.

**Acceptance criteria:**

- [x] A changed declaration is visible to the gate on the next call.
- [x] A malformed file does not crash a scan; it fails safe and is visible in health.
- [x] Existing declaration tests still pass.

**Tests:**

- New: `tests/test_deeplinks.py::test_declaration_change_is_picked_up_without_restart`
- New: malformed-file test in `tests/test_deeplinks.py`

**Notes / risks:** Keep the reload cheap; do not read the file on every pair evaluation. Check at scan start and on health/verify entry points.

---

### P0-6 — Opportunity-rate and arb-lifetime telemetry

**Status:** Done
**Priority:** P0
**Effort:** M
**Depends on:** P0-4

**Objective:** measure the denominator, not just the result: how many boards were seen, how many crossed, how many were actionable, and how long each opportunity survived.

**Expected outcome:** `/api/results` and `/api/health` report crossing rate, actionable rate, median margin, best margin, and p50/p90 arb lifetime. A zero-surebet scan says whether it saw no crossing, saw crossings that failed the gates, or saw only stale data.

**Steps:**

1. Define a compact per-scan summary from the groups: events, markets priced, boards, crossings at 0% and at the profit floor, actionable after all guards, median implied margin, best margin.
2. Compute it from the same pricing path `find_surebets` uses; do not create a second arb formula.
3. Track lifetime by a stable key (event identity + market + line + period + settlement): `first_crossed_at`, `last_crossed_at`, `last_seen_at`, `disappeared_at`.
4. Persist only aggregates and crossing keys per scan, not the full board (the full board is already in the cache; do not duplicate it).
5. Expose the summary in `/api/results`, `/api/health`, and a dashboard tile; add a 7-day baseline report under `docs/evidence/`.
6. Add tests with synthetic boards: no crossing, crossing below floor, crossing above floor, stale book, and a crossing that disappears on the next scan.

**Acceptance criteria:**

- [x] A scan reports boards, crossings, and actionable opportunities with explicit denominators.
- [x] A zero-surebet result distinguishes “no crossing” from “crossing below floor” from “all crossings stale/guarded.”
- [x] Arb lifetime is reported as a distribution, not a single anecdote.
- [x] The metric is computed from raw odds, not from a precomputed count.
- [x] Storage growth is bounded per scan.

**Tests:**

- New: `tests/test_opportunity_metrics.py`
- Existing: `tests/test_arbitrage.py`, `tests/test_scan_quality.py`, `tests/test_soak.py`

**Notes / risks:** Do not store every board snapshot in the JSON cache. Aggregate counters plus crossing keys are enough. The public board-log measurement is 1.34% crossing and 26 actionable out of 1,553 crossings; use it as a sanity range, not a target.

---

### P0-7 — Feed-integrity scorecard and stale-book quarantine

**Status:** Done
**Priority:** P0
**Effort:** M
**Depends on:** P0-4

**Objective:** make a bad book a visible, priced-out state instead of a silent source of phantom arbs.

**Expected outcome:** each book has a per-scan integrity score (freshness, missing rate, own-margin sanity, outlier rate, parse errors), and a book below threshold is quarantined from pricing until it recovers.

**Steps:**

1. Define per-book metrics: scan age of the oldest leg, missing-market rate, own-complete-set margin below 1.0, outlier rate against the peer median, parse/empty rate, and last successful scan.
2. Compute a state: `healthy`, `degraded`, `quarantined`, with the reason and the evidence.
3. Teach the pricing path to refuse a leg from a quarantined book and to say why; this is a price-source restriction, not a trust-rule change.
4. Persist the last N states; recover after N consecutive healthy scans, not after a single lucky one.
5. Expose the scorecard in `/api/health`, `/api/results`, and a dashboard badge; show the reason next to a refused leg.
6. Add tests: a stale book cannot supply a leg; a book with a broken set is quarantined; recovery requires healthy scans; a quarantine does not change the certainty gate.

**Acceptance criteria:**

- [x] Every enabled book has an integrity state and a reason.
- [x] A quarantined book never contributes a priced leg.
- [x] Recovery is automatic but not immediate.
- [x] The dashboard shows which book is unhealthy and why.
- [x] The certainty gate's identity decisions are untouched.

**Tests:**

- New: `tests/test_feed_integrity.py`
- Existing: `tests/test_price_guard.py`, `tests/test_market_consensus.py`, `tests/test_health_api.py` (or `tests/test_candidates_api.py` patterns)

**Notes / risks:** Quarantine is not a proof of badness; it is a temporary price-source restriction. Do not silently drop a book from the scan; show it as unhealthy.

---

### P1-1 — Paginated, filtered group-evidence API

**Status:** Done
**Priority:** P1
**Effort:** M
**Depends on:** P0-1

**Objective:** replace the unbounded `/api/debug/report` with a bounded, filterable evidence API and a small dashboard drill-down.

**Expected outcome:** an operator can inspect a group's evidence without downloading the whole report; the default response is small and paginated.

**Steps:**

1. Add `GET /api/groups?mode=&status=&sport=&limit=&offset=` returning summaries.
2. Add `GET /api/groups/{group_id}?mode=` returning one group's full evidence.
3. Keep `/api/debug/report` as a compatibility alias with a low default limit and a deprecation note.
4. Add a dashboard link from a group/row to the evidence view; show the gate reasons and link evidence.
5. Add response-size and pagination tests.

**Acceptance criteria:**

- [x] Default `/api/groups` response is bounded by `limit` (default ≤ 100).
- [x] A group lookup returns exactly that group and 404s for an unknown id.
- [x] `/api/debug/report` no longer returns every group by default.
- [x] Dashboard navigation works on a phone.

**Tests:**

- New: `tests/test_groups_api.py`
- Existing: `tests/test_frontend_review.py`, `tests/test_api_key.py`

**Notes / risks:** Preserve the evidence trail; do not truncate it. The problem is unbounded listing, not evidence detail.

---

### P1-2 — Structured logs, request IDs, metrics endpoint

**Status:** Done
**Priority:** P1
**Effort:** M
**Depends on:** none

**Objective:** make the scanner observable during unattended operation.

**Expected outcome:** every request and scan has a correlation id; `/api/metrics` exposes counters/gauges in Prometheus text format; logs are JSON-capable; a failed book is visible without reading stderr.

**Steps:**

1. Add request-id middleware (accept `X-Request-ID`, generate otherwise) and include it in logs.
2. Add counters: scans started/completed/failed, per-book successes/empties/errors, surebets found/dropped, link checks, candidate queue size, cache size, scan duration.
3. Add gauges: last scan age per feed, RSS (where available), open browser count.
4. Add `GET /api/metrics` (API-key protected) in Prometheus text format.
5. Add a JSON log formatter option controlled by `LOG_FORMAT`.
6. Test counters and the endpoint without a live server.

**Acceptance criteria:**

- [x] A scan emits one structured completion log with duration, books, groups, surebets, drops, and cache size.
- [x] `/api/metrics` exposes the counters and is protected like other `/api` routes.
- [x] No secret or full odds payload is logged.

**Tests:**

- New: `tests/test_metrics.py`
- New: `tests/test_request_id.py`

**Notes / risks:** Prometheus client is an optional dependency; a tiny text renderer avoids adding a heavy package if the project prefers minimal dependencies.

---

### P1-3 — Reproducible deployment (Docker/systemd)

**Status:** Done
**Priority:** P1
**Effort:** M
**Depends on:** none

**Objective:** make a clean deployment repeatable on a fresh Linux host.

**Expected outcome:** `docker compose up` (or a documented systemd unit) starts the scanner with a persistent `cache/` volume, a health check, and a non-root user; the README has a deployment section.

**Steps:**

1. Add `Dockerfile` (Python 3.11-slim, Playwright Chromium install, non-root user, health check).
2. Add `.dockerignore` (exclude `.venv`, `cache`, `.git`, test caches).
3. Add `docker-compose.yml` with a bind mount for `cache/` and environment passthrough.
4. Add a systemd unit example for bare-metal deployments.
5. Document backup/restore of `cache/`, `config/generated/mapping_evidence.json`, and the decision stores.
6. Add a smoke test that builds the image and hits `/api/health`.

**Acceptance criteria:**

- [x] Fresh clone + `docker compose up` serves the dashboard and `/api/health`.
- [x] Cache survives a container restart.
- [x] The container runs as a non-root user.
- [x] README has copy-paste deployment steps.

**Tests:**

- CI job: `docker build` (can be a separate optional job).
- Manual: `curl -fsS http://127.0.0.1:8000/api/health`.

**Notes / risks:** Playwright's Chromium download is the image-size driver; document the build time.

---

### P1-4 — CI hardening: coverage, dependency and security scans

**Status:** Done
**Priority:** P1
**Effort:** S
**Depends on:** none

**Objective:** catch dependency and security regressions automatically.

**Expected outcome:** CI reports coverage, runs `pip-audit`, and runs Bandit; a high-severity finding fails the job (with a documented allowlist for accepted findings).

**Steps:**

1. Add `pytest-cov`, `pip-audit`, and `bandit` to `requirements-dev.txt`.
2. Add a coverage report and a conservative threshold (start at current coverage, raise over time).
3. Add a security job with a small, explicit allowlist.
4. Consider a Python 3.11 + 3.12 matrix; keep 3.11 as the required version.
5. Document how to reproduce the jobs locally.

**Acceptance criteria:**

- [x] CI publishes a coverage summary.
- [x] `pip-audit` and `bandit` run on every push/PR.
- [x] A known false positive is documented, not silently ignored.

**Tests:** the CI workflow itself; no application test changes required.

**Notes / risks:** Do not set an arbitrary high coverage threshold that forces low-value tests. Use the current measured baseline.

---

### P1-5 — Alerting with dedupe and retry

**Status:** Done
**Priority:** P1
**Effort:** M
**Depends on:** P1-2

**Objective:** notify an operator when a new surebet above a threshold appears, when a feed goes stale, or when a book consistently fails.

**Expected outcome:** a Telegram and/or generic webhook transport sends at most one alert per event per dedupe window, retries transient failures, and never blocks a scan.

**Steps:**

1. Add an `alerts` module with a transport interface and a null transport by default.
2. Add env settings: `ALERT_WEBHOOK_URL`, `ALERT_TELEGRAM_BOT_TOKEN`, `ALERT_TELEGRAM_CHAT_ID`, `ALERT_MIN_PROFIT_PERCENT`, `ALERT_DEDUPE_MINUTES`.
3. Dedupe by a stable signature (match + market + legs + profit bucket).
4. Retry with exponential backoff; send from a background task so a failure cannot fail a scan.
5. Add a health counter for sent/failed/suppressed alerts.
6. Test with a fake transport; no network in CI.

**Acceptance criteria:**

- [x] A repeated scan does not re-alert the same event inside the dedupe window.
- [x] A failed alert is logged and counted, and does not fail the scan.
- [x] Secrets are read from env only, never logged.

**Tests:**

- New: `tests/test_alerts.py`

**Notes / risks:** Do not include full odds payloads or API keys in alert bodies. Use the existing user-facing labels.

---

### P1-6 — 24-hour soak and resource budget

**Status:** Waived — the operator skipped the 24-hour run on 2026-11-04. The
harness, budget guard and two-cycle smoke evidence remain in `docs/SOAK.md`.
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

**Notes / risks:** A short run is a smoke test, not acceptance. The project already has a 6- and 10-cycle plateau; the gap is duration.

---

### P1-7 — Raw-price invariant and rounding audit

**Status:** Done
**Priority:** P1
**Effort:** S
**Depends on:** P0-4

**Objective:** make every displayed margin recomputable from the prices the API actually served, and show the profit that survives stake rounding.

**Expected outcome:** a reviewer can take the served odds, compute `sum(1/odds)` themselves, and get the displayed margin; the slip reports both the exact and the realized (rounded) profit.

**Steps:**

1. Ensure each served leg carries the raw `odds`, `outcome_label`, `line`, and `settlement` (already mostly true).
2. Add `raw_margin`/`implied_sum` to the surebet payload and assert it equals `total_margin` within a tolerance.
3. Add a `realized` block to the slip/API: exact profit, rounded stakes, worst-case return, realized profit.
4. Add a server-side invariant test over a fixture scan: for every surebet, `abs(sum(1/odds) - total_margin) < 1e-6`.
5. Add a frontend check that the copy/displayed numbers come from the same payload, not a second calculation.
6. Document the rounding policy in README.

**Acceptance criteria:**

- [x] Every surebet's displayed margin is reproducible from its served odds.
- [x] The slip shows exact and realized profit, and never presents the exact margin as the realized one.
- [x] A rounding loss is visible, not hidden.
- [x] A test fails if a derived value is changed without its source odds.

**Tests:**

- New: `tests/test_pricing_invariant.py`
- Existing: `tests/test_arbitrage.py`, `tests/test_frontend_review.py`, `tests/test_surebet_api.py`

**Notes / risks:** This is a consistency feature, not a new pricing model. Do not change stake math while adding it.

---

### P2-1 — Convergent deep-link sweep automation and UI

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** P1-1

**Objective:** make a full per-book link sweep a one-click / scheduled operation that provably converges.

**Expected outcome:** an operator can start a sweep for MaxBet/Mozzartbet, see checked/verified/failed/remaining, stop when `remaining: 0`, and read the resulting proof/decision stores.

**Steps:**

1. Add a sweep runner that calls `POST /api/verify-links` until `remaining == 0` or a budget is exhausted.
2. Respect the existing rate limit; do not bypass it.
3. Add a small dashboard control and a status display.
4. Persist a sweep report per book/mode with timestamps and counts.
5. Add tests for convergence, partial failure, and resume.

**Acceptance criteria:**

- [x] A sweep over a fixture cache terminates with `remaining: 0`.
- [x] A failed event does not prevent other events from being checked.
- [x] The report distinguishes verified, failed, errored, and undecided.

**Tests:**

- New: `tests/test_link_sweep.py`
- Existing: `tests/test_verify_links.py`

**Notes / risks:** Keep the existing "a proof must stay re-checkable" behavior. Do not make a proof settle an event permanently.

---

### P2-2 — Dated re-verification of no-event declarations

**Status:** Done
**Priority:** P2
**Effort:** S
**Depends on:** none

**Objective:** prevent a six-book trust assumption from going stale silently.

**Expected outcome:** every `supports_event_id: false` declaration has a `verified_at` date and a note; an audit test fails or warns when a declaration is older than the policy.

**Steps:**

1. Add `verified_at` and a short evidence note to each declaration in `config/bookmaker_deeplinks.json` (or a companion audit file).
2. Add a test that every configured book has a declaration and a date.
3. Add a script to print declarations older than N days.
4. Record the manual re-check in `docs/` with the date and method.
5. Add the audit to the operator checklist.

**Acceptance criteria:**

- [x] Every book has a dated declaration.
- [x] An expired declaration is visible via a script/health field.
- [x] The README's reproduction command still works.

**Tests:**

- New: `tests/test_deeplinks.py::test_every_book_has_a_dated_declaration`

**Notes / risks:** This is a human check; automate the reminder, not the conclusion.

---

### P2-3 — Publish `source_id` from every parser; complete registry coverage

**Status:** Done
**Priority:** P2
**Effort:** L
**Depends on:** none

**Objective:** make market identity auditable for every book, not only NSoft.

**Expected outcome:** every parser emits the book's own market/source id; discovery can attribute a mapping; `unmapped_markets` is actionable per book; every registry row has a captured fixture or a dated absence proof.

**Steps:**

1. Audit each scraper for the source market id and wire it into `Market.source_id`.
2. Run `scripts/discover_markets.py` / `scripts/capture_market_fixtures.py` against captured payloads.
3. Add a coverage test: every registry row has a fixture or an explicit `_excluded`/absence entry.
4. Add per-book `unmapped_markets` counters and a health summary.
5. Regenerate `MARKET_MAPPING.md`.

**Acceptance criteria:**

- [x] Every parser sets `source_id` where the feed provides one.
- [x] Every enabled registry row has test evidence.
- [x] Unmapped IDs are counted per book, not just globally.
- [x] `generate_market_mapping_doc.py --check` passes.

**Tests:**

- Extend `tests/test_market_mapping.py`, `tests/test_market_fixtures.py`, `tests/test_registry_parser_consistency.py`
- New per-book coverage test

**Notes / risks:** Do not guess an ID. A documented absence is better than a false mapping.

---

### P2-4 — Multi-day replay corpus and precision/recall evaluation

**Status:** Done
**Priority:** P2
**Effort:** L
**Depends on:** none

**Objective:** move from one-scan snapshots to a repeatable evaluation set.

**Expected outcome:** a corpus of several days of scans with labelled pairs, plus a script that reports precision, recall, strict miss rate, false-merge rate, and coverage by book/sport.

**Steps:**

1. Capture and freeze scans for several days (respect size and privacy; no secrets).
2. Build a labelled set of same/different fixture pairs from the evidence ledger and manual review.
3. Add `scripts/evaluate_matching.py` with precision/recall and calibration by league/sport.
4. Add regression thresholds and a report under `docs/evidence/`.
5. Wire the report into the roadmap log.

**Acceptance criteria:**

- [x] The corpus has at least 3 distinct days and both prematch and live where possible.
- [x] Precision/recall are reported with denominators.
- [x] A regression below the agreed threshold fails the script.
- [x] The report states what the labels cover and what they do not.

**Tests:**

- New: `tests/test_evaluate_matching.py`
- Existing: `tests/test_replay.py`, `tests/test_pairing_audit.py`

**Notes / risks:** A missed pair is cheaper than a false merge; weight the metrics accordingly. Do not optimize precision by dropping coverage without recording it.

---

### P2-5 — Sports expansion with measured admissibility

**Status:** Done — ice hockey blocked by the measured three-book rule; no parser
was added.
**Priority:** P2
**Effort:** L
**Depends on:** P2-4

**Objective:** add a sport only when the measured feed supports at least three comparable families across at least three books with the same settlement.

**Expected outcome:** ice hockey or the next sport is either implemented with evidence or recorded as blocked with exact reasons.

**Steps:**

1. Re-run `scripts/measure_sports.py` for the candidate sport.
2. Record per-book families and settlement mismatches.
3. Add parser support only for proven families.
4. Add cross-sport non-merge tests.
5. Update `docs/MULTISPORT_EVIDENCE.md`.

**Acceptance criteria:**

- [x] The admissibility rule is applied before code.
- [x] No settlement mismatch is priced.
- [x] A blocked sport has a dated evidence entry, not a TODO.
- [x] Cross-sport pairing remains a hard reject.

**Tests:**

- Extend `tests/test_sports.py`, `tests/test_multisport_arbitrage.py`, `tests/test_market_fixtures.py`

**Notes / risks:** Do not lower the three-book threshold to make a sport fit.

---

### P2-6 — Candidate-queue quality and coverage metrics

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** P0-1, P1-1

**Objective:** make the Diagnostics queue a measure of resolvable work, not a dump of every near-miss.

**Expected outcome:** the queue reports actionable vs league-blocked vs link-blocked counts; the league-blocked share is explained; actionable candidates are prioritized; the queue size trend is visible.

**Steps:**

1. Add queue breakdown by reason to `/api/candidates` and `/api/health`.
2. Separate "an alias can close this" from "a league mapping can close this" from "no human action can close this".
3. Add a dedupe/decay policy for repeated scans.
4. Add a coverage trend chart to the dashboard.
5. Measure before/after on a real scan.

**Acceptance criteria:**

- [x] The queue payload has counts by blocker class.
- [x] A reviewer can filter to actionable candidates.
- [x] The dashboard does not present informational entries as work.
- [x] The before/after numbers are recorded.

**Tests:**

- New: `tests/test_candidate_quality.py`
- Existing: `tests/test_candidates_api.py`, `tests/test_frontend_review.py`

**Notes / risks:** Do not hide blocked candidates; label them. Suppression must remain premise-aware.

---

### P2-7 — Identical-feed ("skin") detection

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** P0-7

**Objective:** replace the single hardcoded NSoft assumption with a measured matrix of which books are actually separate price sources.

**Expected outcome:** the scanner measures exact price agreement between every book pair over shared markets; a pair above a high threshold over enough shared markets is treated as one price source; the matrix is visible in health/diagnostics.

**Steps:**

1. Build a pairwise comparison from a scan: for each shared event/market/outcome, record whether both books quote exactly the same decimal price.
2. Require a minimum sample (e.g. ≥200 shared markets) before drawing a conclusion; report the sample size.
3. Classify pairs: `independent`, `twin` (≥99% identical), `suspicious` (between thresholds), `insufficient data`.
4. Feed the twin set into the price-source rule (keep MDShop/Admiralbet as a seeded/known pair).
5. Expose the matrix and any newly detected twins in `/api/health`; add a warning when a config-declared twin is not measured as one.
6. Add tests with synthetic identical and independent books.

**Acceptance criteria:**

- [x] The price-source rule can come from measured agreement, not only a hardcoded map.
- [x] A twin pair cannot manufacture an arb between its two books.
- [x] A pair with too little shared data is not silently classified as independent.
- [x] The matrix reports sample sizes.

**Tests:**

- New: `tests/test_skin_detection.py`
- Existing: `tests/test_arbitrage.py` (one-leg-per-price-source), `tests/test_multisport_arbitrage.py`

**Notes / risks:** Identical prices are not a trust signal; they are a “same source” signal. A pair that is merely correlated is still independent for arb purposes. The public reference measured Ladbrokes/Neds at 99.9% across 11,198 shared markets.

---

### P2-8 — Event-identity edge cases: doubleheaders and rematches

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** P2-4

**Objective:** prove the gate handles the cases where names and dates are identical but the fixtures are not.

**Expected outcome:** explicit fixtures and tests for same-day doubleheaders, the same two teams meeting twice in a short window, kickoff near a date boundary, postponed/rescheduled matches, and neutral venues. The gate either distinguishes them or refuses; it never merges them by name.

**Steps:**

1. Add captured/synthetic fixtures for each case across at least two books.
2. Test the matcher and gate directly: same names, same date, different kickoff or different provider IDs; same names, different competition; same names, different leg.
3. Add a stable key component for the case if the existing signals cannot separate them (e.g. provider id, competition round, or an explicit `leg` field); do not guess.
4. Document the resolution rule in `engine/certainty.py` and README.
5. Add a regression test per case.

**Acceptance criteria:**

- [x] Two different fixtures with identical team names are never one verified group.
- [x] A legitimate doubleheader can still group across books when the provider ID or kickoff proves it.
- [x] The behavior is documented and test-pinned.
- [x] No new fuzzy rule is introduced.

**Tests:**

- New: `tests/test_identity_edge_cases.py`
- Existing: `tests/test_certainty.py`, `tests/test_matcher.py`, `tests/test_e2e_certified.py`

**Notes / risks:** The SharpAPI canonical-ID docs document both a 6-hour bucket-boundary split and a doubleheader `_g{N}` suffix mismatch. BH_Arb’s Betradar-first rule is stronger, but the no-ID case still needs proof.

---

### P2-9 — Silent-drop coverage budget

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** P0-7

**Objective:** make “a book returned less data” visible before it becomes a clean-looking, wrong dataset.

**Expected outcome:** per book/sport/market, the scanner compares observed counts with a rolling expected baseline and flags a material drop; a book returning zero while peers have events is an error, not a quiet day.

**Steps:**

1. Define a baseline from the last N scans (median or trimmed mean) per book/sport/market family.
2. Compare the current scan; flag a drop beyond a configured absolute and relative threshold.
3. Distinguish “genuinely empty” (e.g. no live games at night) from “expected but absent” using peer books and the time of day.
4. Expose the budget in `/api/health` and the dashboard; include it in the soak report.
5. Add tests with synthetic scans: stable, a 90% drop, a zero while peers are populated, and a legitimate seasonal empty.
6. Record the first real baseline in `docs/evidence/`.

**Acceptance criteria:**

- [x] A book that silently returns zero is flagged.
- [x] A market family that disappears while peers still publish it is flagged.
- [x] A legitimate empty feed does not create a false alarm.
- [x] The baseline and thresholds are documented.

**Tests:**

- New: `tests/test_coverage_budget.py`
- Existing: `tests/test_pairing_audit.py`, `tests/test_probe_feeds.py`

**Notes / risks:** This is the complement to the pairing audit: the audit asks “did we miss a pair?”, the budget asks “did we miss a whole feed?”

---

### P2-10 — Measured push-feed discovery and per-book WebSocket adapter

**Status:** Done — no book measured materially fresher, so polling remains and
no adapter is enabled.
**Priority:** P2
**Effort:** M (discovery plus one reference adapter; each additional book adds M)
**Depends on:** P0-4, P0-7

**Objective:** add a push path only where it is measured to be materially fresher than polling, without changing the certainty gate, the price-source rule, or the advisory non-goal.

**Expected outcome:** each candidate book has a recorded transport decision backed by captured traffic; a book that justifies WebSockets gets a feature-flagged adapter with snapshot/delta handling, sequence and heartbeat checks, reconnect/gap detection, a bounded latest-state buffer, and a polling fallback. A silent or gapped stream is quarantined and cannot price a leg.

**Steps:**

1. Capture each candidate book's XHR/fetch and WebSocket traffic with Playwright: handshake/auth headers and cookies, heartbeat, frame shape (snapshot vs delta, JSON vs binary/protobuf), message rate and size. Record the evidence per book under `docs/evidence/`.
2. Measure freshness and coverage against the current REST path: time to first price, update cadence, market coverage, gap/duplicate rate, and resource cost. Proceed only where the measured gain is material.
3. Define a `LiveFeed` adapter interface and a per-book feature flag. Keep the current scraper and polling path as the fallback; with the flag off, behavior must be unchanged.
4. Implement snapshot plus delta handling: sequence numbers, heartbeat, reconnect with backoff, explicit gap detection, a bounded latest-state buffer, and coalescing to the latest row per market rather than processing every tick.
5. Normalize accepted rows into the existing `Match`/`Market` models and feed the certainty gate. Never bypass the gate or price an unverified or stale leg.
6. Integrate with the P0-4 freshness state and P0-7 quarantine: every row carries `fetched_at` and `source_updated_at`; silence, a missed heartbeat or a sequence gap marks the book stale and refuses its legs.
7. Freeze captured frames as offline fixtures. Add tests for snapshot, delta, reconnect/gap, silence/stale, flag-off, and no network in CI.
8. Measure connection, event-loop and memory cost before enabling the feed in scheduled scans.

**Acceptance criteria:**

- [x] Each candidate book has a recorded transport decision with captured evidence.
- [x] A WebSocket path exists only for a book that measured materially fresher, behind a flag, with polling fallback (none qualified, so none is enabled).
- [x] Sequence, heartbeat and gap handling are explicit; a silent or gapped stream cannot price a leg.
- [x] Stream state is coalesced to the latest row per market and storage growth is bounded.
- [x] Recorded-frame tests cover snapshot, delta, reconnect, silence and flag-off (offline replay; payloads were deliberately not stored).
- [x] Existing scan behavior is unchanged when the flag is off.

**Tests:**

- New: `tests/test_live_feed.py`
- Existing: `tests/test_live_mode.py`, `tests/test_soak.py`
- Adding after P0-4: `tests/test_freshness_api.py`

**Notes / risks:** Frames may be binary or protobuf, not JSON. Use an async client (`websockets`/`aiohttp`); `websocket-client` is sync/threaded and does not fit this pipeline. A Cloudflare browser session may be required, and a long-lived Playwright context is resource-heavy enough to belong in the soak test. Streaming removes our poll interval, not the book's own update latency. Partial, unsequenced deltas are worse than polling; fail closed. Redis is unnecessary at this scale: coalesce in memory and persist only the bounded state the scan consumes.

---

### P3-1 — Persistent storage v2 (SQLite) and migration

**Status:** Done
**Priority:** P3
**Effort:** L
**Depends on:** P0-1, P1-1

**Objective:** replace the ad-hoc JSON stores for runtime state with a transactional store that supports history, queries, and safe concurrent writes.

**Expected outcome:** scans, groups, candidates, link proofs, decisions, and history live in SQLite with migrations; the JSON files remain importable and are migrated once.

**Steps:**

1. Define a schema and migration tool.
2. Move scan history and candidate/decision stores first; keep `last_scan.json` as a compatibility export until the dashboard is migrated.
3. Add indexes for book, event id, status, kickoff, and scan.
4. Add a vacuum/retention policy.
5. Add backup/restore docs.
6. Run a migration dry run on the current cache.

**Acceptance criteria:**

- [x] No data loss on migration; counts match the JSON source.
- [x] A scan writes transactionally.
- [x] A 30-day history is queryable without loading a 200 MB JSON file.
- [x] Rollback instructions exist.

**Tests:**

- New: `tests/test_storage_migration.py`
- Existing: `tests/test_cache_serialization.py`, `tests/test_replay.py`

**Notes / risks:** This is a large change; do it only after P0-1 proves the JSON path is bounded and the API is paginated. Do not combine it with a trust-rule change.

---

### P3-2 — Bet log, bankroll, and CLV analytics

**Status:** Done
**Priority:** P3
**Effort:** L
**Depends on:** P3-1

**Objective:** let an operator record what was actually placed and measure whether the edges are real.

**Expected outcome:** a bet log with stakes, accepted odds, book, timestamp, and settlement; bankroll and ROI; closing-line value where a closing price is captured; export to CSV.

**Steps:**

1. Add bet/leg models and storage.
2. Add "log this surebet" from the slip, with actual accepted odds and partial stakes.
3. Add settlement entry and P/L calculation.
4. Capture a closing price when available and compute CLV.
5. Add dashboard summaries and CSV export.
6. Keep it manual; no account integration.

**Acceptance criteria:**

- [x] A logged bet does not change the scanner's trust model.
- [x] ROI and CLV have explicit denominators and date ranges.
- [x] Partial acceptance and a missing leg are representable.
- [x] Export round-trips.

**Tests:**

- New: `tests/test_bet_log.py`, `tests/test_clv.py`

**Notes / risks:** This is the strongest long-term value feature, but it depends on honest manual entry. Do not fake settlement data.

---

### P3-3 — Advisory execution workflow and limits

**Status:** Done
**Priority:** P3
**Effort:** M
**Depends on:** P3-2

**Objective:** help an operator place a surebet safely without automating the bet.

**Expected outcome:** per-book max stake, partial acceptance, "price moved" state, and a leg-by-leg checklist that re-plans after each accepted stake.

**Steps:**

1. Add per-book stake limits from config.
2. Extend the slip to record accepted stake and odds per leg.
3. If a leg is partially accepted or the price moves, re-plan the remaining legs and show the new worst case.
4. Add a "stop/hedge" recommendation when the worst case turns negative.
5. Test the planner with partial acceptance and missing legs.

**Acceptance criteria:**

- [x] A partial acceptance cannot silently show the original profit.
- [x] The remaining stakes are recalculated from actual accepted amounts.
- [x] A negative worst case is clearly labeled.
- [x] No endpoint places a bet or logs in.

**Tests:**

- Extend `tests/test_arbitrage.py`, `tests/test_frontend_review.py`
- New: `tests/test_slip_partial_acceptance.py`

**Notes / risks:** Keep the project's non-goal: the scanner never moves money.

---

### P3-4 — Alerts, PWA, accessibility, and Bosnian UI

**Status:** Not started
**Priority:** P3
**Effort:** M
**Depends on:** P1-5

**Objective:** make the dashboard usable away from the desk and accessible to Bosnian-speaking operators.

**Expected outcome:** optional PWA install, push/webhook alerts, keyboard/screen-reader checks, and a language toggle (BS/EN) for the main labels.

**Steps:**

1. Add a web app manifest and service worker for installability (no offline betting data).
2. Add notification permission and a push/webhook preference.
3. Audit focus order, labels, contrast, and live regions.
4. Extract user-facing strings into a small dictionary; add Bosnian translations.
5. Add accessibility tests where practical.

**Acceptance criteria:**

- [ ] The app is installable and opens without a bundler.
- [ ] Alerts respect the dedupe policy.
- [ ] A keyboard-only user can scan, filter, open a slip, and copy a stake.
- [ ] The language toggle persists.

**Tests:**

- Frontend tests for the language dictionary and focus behavior
- Manual accessibility pass documented

**Notes / risks:** Do not cache live odds in the service worker; stale odds are dangerous.

---

### P3-5 — Authentication and key management hardening

**Status:** Not started
**Priority:** P3
**Effort:** M
**Depends on:** P1-3

**Objective:** make an exposed deployment safer than a single shared env key.

**Expected outcome:** multiple named keys with hashed storage and rotation, per-key rate limits, and an audit log of privileged actions.

**Steps:**

1. Add a key file/store with hashed keys and labels.
2. Add rotation and revocation.
3. Scope keys to read/scan/admin where useful.
4. Add an audit log for toggles, shutdown, and link checks.
5. Keep the env `API_KEY` as a bootstrap/admin key.

**Acceptance criteria:**

- [ ] A revoked key fails immediately.
- [ ] Keys are never stored or logged in plaintext.
- [ ] Privileged actions are attributable.
- [ ] The default remains loopback-only.

**Tests:**

- New: `tests/test_auth_keys.py`
- Existing: `tests/test_api_key.py`, `tests/test_csrf.py`

**Notes / risks:** Do not add a public signup flow. This is a single-operator tool.

---

### P3-6 — Book risk profiles and advisory pacing

**Status:** Not started
**Priority:** P3
**Effort:** M
**Depends on:** P1-7

**Objective:** tell the operator what kind of book a leg is at, and whether the stake is realistic, without implementing account evasion.

**Expected outcome:** every book has a `risk_profile` (sharp / soft / exchange / unknown), a typical max-stake note, and a limit-risk note; the slip shows a warning when a leg is at a soft book with a stake above its advisory limit. No auto-placement, no jitter, no multi-account logic.

**Steps:**

1. Add risk-profile fields to `config/settings.py` or a new `config/bookmaker_risk.json`.
2. Show a label and a warning on the slip; keep it advisory.
3. Add a per-book advisory max stake and a “stake exceeds advisory limit” flag.
4. Add a test that a profile cannot change the certainty gate or the price source.
5. Document the policy: the scanner does not evade limits or manage accounts.

**Acceptance criteria:**

- [ ] Every enabled book has a risk profile or an explicit `unknown`.
- [ ] The dashboard shows the profile and an advisory warning.
- [ ] A high stake at a soft book is visibly flagged.
- [ ] No evasion, multi-account, or auto-placement feature is added.

**Tests:**

- New: `tests/test_book_risk_profiles.py`
- Existing: `tests/test_frontend_review.py`, `tests/test_arbitrage.py`

**Notes / risks:** The research on account limits is descriptive, not a playbook. The product's stance is transparency and advisory warnings.

---

### P3-7 — Record-only / paper-trading mode

**Status:** Not started
**Priority:** P3
**Effort:** M
**Depends on:** P3-1

**Objective:** let the operator run the scanner without presenting anything as a live opportunity, and measure what a strategy would have done on recorded boards.

**Expected outcome:** a `record-only` mode stores compact board snapshots and simulated outcomes; a `paper` mode tracks a virtual bankroll and produces ROI/CLV statistics. Neither places a bet.

**Steps:**

1. Add a mode flag to the scan/API; record-only never writes to the live surebet list.
2. Store compact snapshots (event key, market, line, best odds, book, timestamp) and the gate verdict.
3. Add a paper bankroll that takes a recorded opportunity at the recorded odds and marks it to the next available price or settlement.
4. Report simulated ROI, hit rate, and CLV with explicit denominators.
5. Keep the live advisory path unchanged.
6. Document the limitations: simulated fills, no stake limits, no account effects.

**Acceptance criteria:**

- [ ] Record-only mode cannot show a live surebet as current.
- [ ] Paper results state that no bet was placed.
- [ ] ROI and CLV are computed only where the data supports them.
- [ ] The live path's behavior is unchanged when the mode is off.

**Tests:**

- New: `tests/test_record_only.py`, `tests/test_paper_bankroll.py`
- Existing: `tests/test_arbitrage.py`, `tests/test_replay.py`

**Notes / risks:** Do not let a simulated fill assume a bet was accepted at the displayed price; model rejection and partial acceptance explicitly.

---

## 5. Cross-cutting decisions and non-goals

### 5.1 Non-goals

- **Automated bet placement or bookmaker login.** The product is advisory; this is both a trust boundary and an account-risk boundary.
- **Lowering the certainty gate to increase surebet count.** A missed match is cheaper than a false merge.
- **Adding a book or market without a capture or dated absence proof.**
- **Raising live polling without a push/sub-10 s feed.** It would add load without improving the actual capture latency.
- **Treating AI as an approver.** AI may rank candidates only.

### 5.2 Trust invariants

These must hold after every task:

1. Only `verified` groups reach `engine/arbitrage.py`.
2. `verified` means zero outstanding reasons, including the link half.
3. A human or AI action cannot set `deep_link_verified`; only a browser check can.
4. A missing declaration fails safe.
5. A false merge is worse than a split; no fuzzy score alone may confirm identity.
6. `sport` is a hard identity gate; no cross-sport pricing.
7. Settlement is part of market identity; regulation vs overtime never pair.
8. One leg per bookmaker and one leg per price source.

### 5.3 Measurement discipline

Before writing a claim about behavior, run the command that proves it and paste the output. Update `docs/ACCEPTANCE.md` for any number that changes the project's readiness story. Regenerate `MARKET_MAPPING.md`; never hand-edit the generated table.

---

## 6. Execution log

Newest first. Each entry: date, task, status, commands, measured result, files changed, follow-ups.

### 2026-11-04 — P3-3: Advisory execution workflow and limits

**Task:** P3-3 (depends on P3-2, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_slip_partial_acceptance.py tests/test_frontend_review.py -q` → passed.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `config/settings.py`: `BOOK_STAKE_LIMITS` (`BOOK_MAX_STAKE_<BOOK>`, default 500).
- `/api/config`: each book carries `max_stake`.
- Slip: warns when a planned stake is over that book's advisory ceiling; the existing placed-leg inputs and `planStakes` already re-plan the remaining legs from accepted odds/stake; a negative worst case keeps the stop/hedge warning.
- `tests/test_slip_partial_acceptance.py` (new): limit exposure, re-plan logic, negative warning, log-bet only, no placement path.
- `.env.example`: limit variables.

**Trust rules:** unchanged and explicitly advisory. No endpoint logs in or places a bet; a limit warning does not prevent recording what was accepted.

**Follow-ups:** P3-4 (PWA/accessibility/Bosnian UI) is next.

---

### 2026-11-04 — P3-2: Bet log, bankroll and CLV

**Task:** P3-2 (depends on P3-1, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_bet_log.py tests/test_clv.py -q` → 9 passed.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `server/bets.py` (new): SQLite `bets` table and create/list/settle/closing/summary/CSV methods. Accepted stake/odds and void legs are explicit; P/L stays open until every leg is settled.
- `server/api.py`: `/api/bets` create/list, `/api/bets/{id}/settle`, `/api/bets/{id}/closing`, `/api/bets/summary`, `/api/bets/export.csv`, initialized on startup.
- Slip: **Log bet** action posts the current plan; Settings/Diagnostics shows the 30-day bankroll/ROI/CLV line.
- `tests/test_bet_log.py`, `tests/test_clv.py`; `docs/BET_LOG.md`.

**Trust rules:** unchanged. This is a manual record; no account integration, no placement, no trust input.

**Follow-ups:** P3-3 (advisory execution workflow) is next.

---

### 2026-11-04 — P3-1: Persistent storage v2 (SQLite)

**Task:** P3-1 (depends on P0-1 and P1-1, both complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_storage_migration.py tests/test_candidates_api.py tests/test_scan_candidates.py tests/test_metrics.py -q` → passed.
- Migration test: 3 scans + 2 decisions from JSON → identical SQLite counts; second migration is a no-op; 30-day window excludes a 45-day row; prune removes it; a SQLite backup restores the row.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `server/storage.py` (new): SQLite schema (`meta`, `scans`, `decisions`, `link_sweeps`), WAL mode, one-shot JSON migration, idempotent markers, 30-day/limited queries, transactional scan append, decision mirror, prune, vacuum and `backup()`.
- `server/api.py`: initializes and migrates storage on startup; `_append_history` writes SQLite plus the JSON export; `/api/history` accepts `days`/`mode` and queries SQLite; decision writes are mirrored and the default decision store prefers SQLite after migration.
- `.gitignore`: SQLite/WAL files.
- `docs/STORAGE.md` (new) and `docs/DEPLOYMENT.md`: schema, migration, query, retention, backup/restore and rollback.
- `tests/test_storage_migration.py` (new): counts, idempotence, 30-day query, prune, transactional append and backup.

**Trust rules:** unchanged. This is runtime storage, not mapping/price evidence. JSON files remain compatibility exports and the rollback path.

**Follow-ups:** P3-2 (bet log/bankroll/CLV) is next.

---

### 2026-11-04 — P2-10: Measured push-feed discovery

**Task:** P2-10 (depends on P0-4 and P0-7, both complete).
**Status:** Done — polling remains the measured choice; no WebSocket adapter enabled.

**Commands and results:**

- `python scripts/discover_push_feeds.py --bookmaker ...` captured transport metadata for maxbet, mozzartbet, wwin and sportplus (15–30 s each).
- maxbet/wwin: no WebSocket. mozzartbet: socket.io heartbeat, 4 frames / 108 B over 30 s, longest gap 25 s. sportplus: rabbit WS with 8 binary frames / 205 B over 15 s plus a separate live-chat socket — no odds cadence measured.
- `python -m pytest tests/test_live_feed.py -q` → 7 passed.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `scripts/discover_push_feeds.py` (new): Playwright transport probe storing only URL/frame/byte/opcode/gap/XHR metadata, never payloads, cookies or headers.
- `engine/live_feed.py` (new): disabled-by-default push state machine with sequence continuity, duplicate/gap refusal, snapshot/delta coalescing, a bounded row store, heartbeat staleness and `priceable()`; offline replay for tests.
- `config/settings.py`: `LIVE_FEED_FLAGS` off for every book.
- `tests/test_live_feed.py` (new): flag-off, snapshot, delta, gap, duplicate, silence, bound and replay.
- `docs/PUSH_FEEDS.md` and four raw capture reports under `docs/evidence/`.

**Trust rules:** unchanged. Nothing in the scan calls the state machine while the flags are off; freshness and quarantine remain the only pricing gates.

**Follow-ups:** P3-1 (SQLite storage) is next.

---

### 2026-11-04 — P2-9: Silent-drop coverage budget

**Task:** P2-9 (depends on P0-7, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_coverage_budget.py -q` → 7 passed.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `engine/coverage_budget.py` (new): per `bookmaker|sport|market` row counts, a rolling median baseline (last 20 scans), and `silent_zero` / `material_drop` flags only when a peer is still populated.
- `server/api.py`: evaluates the budget before matching on every scan, persists `cache/coverage_budget.json`, restores it on startup, and exposes `coverage_budget` in `/api/health`.
- Dashboard health line: `Coverage N flag(s)` plus each flag in the tooltip.
- `tests/test_coverage_budget.py` (new): snapshot, 90% drop, peer-populated zero, legitimate all-zero night, short baseline, bounded history, frontend hook.
- `docs/COVERAGE_BUDGET.md` and the soak report section.

**Trust rules:** unchanged. The budget is diagnostic; it does not drop a book or change pricing. Baseline requires 3 scans before it can flag.

**Follow-ups:** P2-10 (push-feed discovery) is the last P2 task.

---

### 2026-11-04 — P2-8: Event-identity edge cases

**Task:** P2-8 (depends on P2-4, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_identity_edge_cases.py tests/test_certainty.py tests/test_matcher.py tests/test_e2e_certified.py -q` → passed.
- `python -m pytest tests/test_readme_claims.py -q` → passed with `leg_mismatch` added to the rejected vocabulary.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `models/schemas.py`: optional `Match.leg` for a feed-declared doubleheader/rematch marker.
- `engine/certainty.py`: two different non-empty legs are a hard `leg_mismatch`; the reason is in `HARD_REJECT_REASONS`.
- `tests/test_identity_edge_cases.py` (new): leg mismatch, same-leg grouping, different provider ids, shared id+leg, rematch hours apart, midnight kickoff boundary, different mapped competitions, and the matcher-level doubleheader refusal.
- `README.md`: `leg_mismatch` in the rejected table and the doubleheader/rematch rule.
- `tests/test_readme_claims.py`: the reason probe now exercises `leg_mismatch`.

**Trust rules:** no fuzzy rule was added. Missing legs stay empty; only two explicitly different feed values reject, and provider ids/kickoff behavior is unchanged.

**Follow-ups:** P2-9 (silent-drop coverage budget) is next.

---

### 2026-11-04 — P2-7: Identical-feed ("skin") detection

**Task:** P2-7 (depends on P0-7, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_skin_detection.py tests/test_arbitrage.py tests/test_multisport_arbitrage.py -q` → passed.
- Real 2026-11-04 prematch cache (8,969 matches, 1,499 groups): 36 book pairs, one measured twin — **admiralbet/mdshop 11,796 shared outcomes, 100.00% identical**. Every other pair was independent, with sample sizes 9,556–11,604. No pair fell below the 200-outcome floor.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `engine/skin_detection.py` (new): pairwise agreement on same event/market/settlement/period/line, `insufficient_data` below 200 shared outcomes, `twin` >= 99%, `suspicious` >= 95%, `independent` below; measured twins registered through `config.settings.register_price_source_twin`.
- `config/settings.py`: mutable measured price-source registry behind `price_source()`; config-declared NSoft stays seeded.
- `server/api.py`: measures after grouping and before pricing; `/api/health` exposes the matrix, summary, config-mismatch warnings and newly registered twins.
- `tests/test_skin_detection.py` (new): identical/independent/insufficient classes, one-source arb rejection, declared-twin warning, health payload.
- `docs/SKIN_DETECTION.md` and `docs/evidence/2026-11-04-skin-matrix.json`.

**Trust rules:** unchanged in direction. A measured twin can only *remove* a false price source, never add trust; the NSoft seed remains and settlement identity is untouched.

**Follow-ups:** P2-8 (identity edge cases) is next.

---

### 2026-11-04 — P2-6: Candidate-queue quality and coverage metrics

**Task:** P2-6 (depends on P0-1 and P1-1, both complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_candidate_quality.py tests/test_candidates_api.py -q` → passed.
- Recomputed the real 2026-11-04 prematch cache with the current matcher and candidate builder: **5,569 queued**, **87 alias-actionable**, **4,196 league-blocked**, **0 link-pending**, **1,286 informational** (8,969 matches, 1,499 groups; 36.8 s, no network).
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `server/api.py`: `_candidate_blocker` / `_candidate_breakdown` classify each queued pair as `alias`, `league`, `link` or `other`; `/api/candidates` returns `blocker_counts` for the full queue even when the page is filtered; `/api/health` reports the same per feed; scan history records `candidate_queue` and `candidate_actionable`.
- Dashboard: the Review tab shows the blocker breakdown, and History has a Queue column with actionable/queued counts.
- `tests/test_candidate_quality.py` (new): classification, filtered API counts, health, history and frontend hooks.
- `docs/evidence/2026-11-04-candidate-quality.json`: the real before/after numbers.

**Trust rules:** unchanged. Blocked candidates are still labelled, never hidden; suppression remains premise-aware.

**Follow-ups:** P2-7 (identical-feed detection) is next.

---

### 2026-11-04 — P2-5: Sports expansion with measured admissibility

**Task:** P2-5 (depends on P2-4, complete).
**Status:** Done — the candidate sport is blocked with evidence, so no code was added.

**Commands and results:**

- `python -m pytest tests/test_sports.py -q` → passed, including the new blocked-sport assertion.
- Evidence: `docs/evidence/2026-11-04-sport-discovery.json`, measured on the same day with the fixed three-book rule.
- Ice hockey: only `sportplus` and `mbet` publish three regular-time families. NSoft lacks a full-match handicap; MaxBet's only total includes overtime. Two books, not three; incl-OT is a different settlement.
- Basketball and tennis remain the implemented non-football sports; `ice_hockey` stays out of `ENABLED_SPORTS`.

**What changed:**

- `docs/MULTISPORT_EVIDENCE.md` §5: the dated P2-5 re-audit and the exact blocker.
- `tests/test_sports.py`: `test_ice_hockey_is_blocked_by_the_three_book_rule` pins the blocked evidence, the qualifying-book count, the overtime reason and the absence from `ENABLED_SPORTS`.

**Trust rules:** unchanged. The three-book threshold was not lowered and settlement identity was not relaxed.

**Follow-ups:** P2-6 (candidate-queue quality) is next.

---

### 2026-11-04 — P2-4: Multi-day replay corpus and evaluation

**Task:** P2-4 (no dependencies).
**Status:** Done.

**Commands and results:**

- `python scripts/evaluate_matching.py --check` → **3 days**, 4 scans, both modes, 413 same / 60 different labels, precision **100%**, recall **100%**, strict miss **0%**, false merges **0**.
- `python -m pytest tests/test_evaluate_matching.py tests/test_replay.py -q` → 10 passed.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `tests/fixtures/replay/2026-09-25/` (reviewed e2e capture), `tests/fixtures/replay/2026-11-03/` (existing replay) and `tests/fixtures/replay/2026-11-04/` (bounded real prematch + live extracts) with explicit same/different label pairs under each `labels/` directory.
- `scripts/evaluate_matching.py` (new): runs the real matcher, reports precision, recall, strict miss rate, false-merge rate, denominators, books/sports/modes, and fails `--check` below the thresholds or below 3 days / both modes.
- `tests/test_evaluate_matching.py` (new): corpus shape, denominators, zero false merges, and the failure path.
- `docs/evidence/2026-11-04-matching-eval.{md,json}`: the report and its honesty limits.
- `README.md`: the evaluator command.

**Trust rules:** unchanged. The corpus is a regression snapshot; the report says the 2026-11-04 labels are gate-reviewed, not independent ground truth.

**Follow-ups:** P2-5 (sports admissibility) is next and can now use the corpus.

---

### 2026-11-04 — P2-3: Publish source_id from every parser

**Task:** P2-3 (no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_market_fixtures.py tests/test_market_mapping.py tests/test_registry_parser_consistency.py -q` → passed.
- Every captured fixture now emits a non-empty `Market.source_id`: 16 book/mode captures across mdshop, admiralbet, wwin, premier_kladionica, mbet, sportplus, mozzartbet, maxbet.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `scrapers/betole.py`, `wwin.py`, `premier_kladionica.py`, `mozzartbet.py`, `mbet.py`, `evlbet.py`, `maxbet.py`, `sportplus.py`: the market's own source id (or the registry group id the parser already used) is attached to every emitted market.
- `engine/market_registry.py`: `unmapped_by_book()` groups the process-wide counter by bookmaker.
- `server/api.py`: `/api/health` exposes `unmapped_markets_by_book`.
- `tests/test_market_fixtures.py`: a per-capture source-id assertion and a per-book grouping test. Existing `UNCOVERED_ROWS` / `BOOKS_WITHOUT_FIXTURES` remain the explicit absence evidence for rows the feed never served.

**Trust rules:** unchanged. No source id is guessed; the registry and label rules still decide market identity.

**Follow-ups:** P2-4 (multi-day replay corpus) is next.

---

### 2026-11-04 — P2-2: Dated re-verification of no-event declarations

**Task:** P2-2 (no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_deeplinks.py -q` → passed.
- `python scripts/audit_deeplinks.py --check` → all 10 declarations inside the 180-day policy.
- `python -m ruff check .`, `python -m mypy .` → clean.

**What changed:**

- `config/bookmaker_deeplinks.json`: every book now has `verified_at`; the six undated notes were rewritten as dated declaration audits without changing the conclusion.
- `config/settings.py`: `DEEPLINK_DECLARATION_MAX_AGE_DAYS` (180 days).
- `scrapers/common.py`: `declaration_verified_at()` and `declaration_audit()`, which treats a missing or malformed date as stale.
- `server/api.py`: `/api/health` exposes `deep_link_declaration_audit`.
- `scripts/audit_deeplinks.py` (new): prints the audit and exits non-zero with `--check` when any declaration is overdue.
- `tests/test_deeplinks.py`: every book has a dated note; missing/old dates are stale; health exposes the audit; the script fails when overdue.
- `README.md`: audit command.

**Trust rules:** unchanged. The dated declaration still has exactly the same effect on the gate; the audit only makes an old human decision visible.

**Follow-ups:** P2-3 (`source_id` coverage) is next.

---

### 2026-11-04 — P2-1: Convergent deep-link sweep automation and UI

**Task:** P2-1 (depends on P1-1, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest tests/test_link_sweep.py -q` → 8 passed.
- `python -m ruff check .` and `python -m mypy .` → clean.
- The runner was exercised against fake `verify-links` responses: convergence, an errored event followed by another call, budget exhaustion, a 429 wait and a whole-request failure.

**What changed:**

- `scripts/sweep_links.py` (new): loops `POST /api/verify-links` until `remaining == 0`, waits out 429 using `Retry-After` instead of raising the rate limit, keeps going after per-event errors, stops at a call budget, and appends an atomic report to `cache/link_sweeps.json`.
- `server/api.py`: `POST /api/link-sweeps` persists a sweep report (bounded to 200) and `GET /api/link-sweeps` reads the newest, filterable by book/mode.
- Dashboard Diagnostics: book/mode selector, `Sweep links` button, live checked/verified/failed/errored/remaining text; it posts the completed report to the store.
- `tests/test_link_sweep.py` (new): convergence, partial failure, budget, rate-limit pacing, request failure, persistence and dashboard hooks.
- `README.md`, `docs/CI.md`: operator command and the sweep `urlopen` allowlist entry.

**Trust rules:** unchanged. A sweep still goes through the existing rate limit, browser semaphore and decision store; it does not make a proof permanent.

**Follow-ups:** P2-2 (dated no-event declarations) is next.

---

### 2026-11-04 — P1-7: Raw-price invariant and rounding audit

**Task:** P1-7 (depends on P0-4, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest --cov --cov-report=term-missing` → **1,360 passed**, 1 warning, 162.48 s; coverage **81.99%** (floor 80%).
- `python -m pytest tests/test_pricing_invariant.py` → 6 passed.
- `python -m pytest tests/test_arbitrage.py tests/test_e2e_certified.py tests/test_verify_surebet.py tests/test_frontend_review.py` → pass.
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 155 source files.
- Market doc in sync; cold replay exit 0, fixed point.
- `pip-audit` clean; Bandit medium+ exit 0.

**What changed:**

- `engine/pricing_invariant.py` (new): exact implied sum, exact profit percent, the three stake-rounding modes and one `rounding_summary` for exact vs realized profit.
- `models/schemas.py`: `Surebet.raw_margin` (exact) and `realized: RoundingSummary`; `total_margin` stays the four-decimal display value.
- `engine/arbitrage.py`: all three surebet construction paths populate `raw_margin` and `realized` from the stake rows they serve.
- `server/api.py`: `/api/recalculate` recomputes from the served odds, accepts `rounding: exact|1|5`, and returns separate `exact` and `realized` blocks; legacy fields stay exact.
- `frontend/js/app.js`: exact profit, realized profit and rounding effect are labelled separately; the slip recomputes the margin from `sb.stakes` and refuses to present the slip if the payload and served odds disagree.
- `README.md`: pricing and rounding policy.
- `tests/test_pricing_invariant.py` (new): served-odds invariant, realized block, tamper failure, recalculate contract, frontend labels.

**Trust rules:** unchanged. The stake split and arbitrage decision still belong to `engine.arbitrage`; this is a consistency and disclosure layer only.

**Follow-ups:** P1-6 is the only P1 task still open (24-hour wall-clock run). P2-1 (deep-link sweep) is next after it.

---

### 2026-11-04 — P1-6: 24-hour soak and resource budget (partial)

**Task:** P1-6 (depends on P0-1 and P1-2, both complete).
**Status:** Waived — the operator chose to skip the 24-hour run on 2026-11-04.

**Commands and results:**

- `python -m pytest tests/test_soak.py tests/test_alerts.py -q` → 23 passed.
- Live two-cycle smoke against a local server on port 18080: `ok: true`, RSS **940.4 → 924.4 MB** (-1.7%), peak **940.4 MB** below the 1024 MB budget, cache **31.2 MB** below the 40 MB budget, **0** browser processes at both samples, 3 surebets per scan.
- Per-book states: seven books healthy in both samples; `betole` and `mozzartbet` degraded in both with `missing_markets`, named in the report rather than silently dropped.
- The 24-hour `--minutes 1440` run is **not done**; the session cannot hold a 24-hour wall clock. No leak was found or masked in the short run.

**What changed:**

- `scripts/soak.py`: `--cycles 0` now means "until `--minutes`" (the old default silently ran one scan for a 1440-minute invocation); samples now include cache bytes and per-book feed states; summarization fails on any leaked browser, an unavailable browser probe, peak RSS over `--rss-budget-mb`, or growth over `--max-growth`, and reports `books_without_healthy`.
- Resource guard: `config/settings.py` adds `RSS_BUDGET_MB`; `server/api.py` queues cache/RSS budget alerts and `/api/health` reports `memory.rss_mb`, `memory.budget_mb` and `memory.over_budget`.
- `tests/test_soak.py`: budget, any-sample browser leak, probe-unavailable, cache/per-book reporting and cycle-limit tests.
- `docs/SOAK.md` (new): the exact 24-hour command and environment, plus the smoke-run table and its limits.

**Acceptance:** unchecked. The 24-hour criteria (duration, plateau, no book silently absent for a day) require the real run in `docs/SOAK.md`; the report must be replaced with its output before this task is marked Done.

**Follow-ups:** run `python scripts/soak.py --minutes 1440 --interval 300 --pid <server-pid> --rss-budget-mb 1024 --check --out docs/evidence/...` on the deployment host, then publish the report and mark the boxes.

---

### 2026-11-04 — P1-5: Alerting with dedupe and retry

**Task:** P1-5 (depends on P1-2, complete).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → full suite passed, **1,349 tests collected** (was 1,335; +14 alert tests).
- `python -m pytest tests/test_alerts.py -q` → 14 passed.
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 153 source files.
- `python -m pip_audit` / Bandit → unchanged and clean.

**What changed:**

- `server/alerts.py` (new): `Alert`, a transport protocol, `NullTransport` default, webhook and Telegram transports, pure alert builders, and `AlertManager` with a stable signature (match + market + legs + one-point profit bucket), in-memory dedupe window, single daemon delivery worker, exponential-backoff retries and sent/failed/suppressed counters.
- `config/settings.py` and `.env.example`: `ALERT_WEBHOOK_URL`, `ALERT_TELEGRAM_BOT_TOKEN`, `ALERT_TELEGRAM_CHAT_ID`, `ALERT_MIN_PROFIT_PERCENT`, `ALERT_DEDUPE_MINUTES`, plus retry controls and `RSS_BUDGET_MB`.
- `server/api.py`: one `alert_manager` built from env, `_notify_scan_alerts` called after a completed scan, health `alerts` and `memory` blocks, and a public RSS probe. Alert evaluation is wrapped so it cannot fail the scan.
- Alert kinds: new surebet above threshold, stale feed per book, book quarantine, book backoff failure, cache budget and RSS budget.
- `server/observability.py`: public `current_rss_bytes()`.
- `docs/ALERTING.md` (new), README configuration rows, and the CI allowlist updated for the two alert transport `urlopen` calls.
- `tests/test_alerts.py` (new): dedupe window, retry/failure accounting, secret-free logs, signature stability, threshold and builder coverage, scan integration, and health snapshot.

**Trust rules:** unchanged. Alert bodies use dashboard labels, not full payloads or API keys. Delivery is off the scan path; a transport failure cannot change scan state.

**Follow-ups:** P1-6 (24-hour soak) and P1-7 (raw-price invariant) remain.

---

### 2026-11-04 — P1-4: CI hardening (coverage, dependency and security scans)

**Task:** P1-4 (first eligible task after P1-3; no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest --cov --cov-report=term-missing` → **1,335 passed**, 1 warning, 365.69 s; **81.55%** coverage across `engine`, `server`, `scrapers`, `config` and `models` (8,096 statements); the 80% floor passed.
- `python -m pytest` on **Python 3.12** (temporary uv venv) → exit 0, full suite, no failures (forward-compatibility leg).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 151 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point.
- `python -m pip_audit -r requirements.txt -r requirements-dev.txt --progress-spinner off` → **no known vulnerabilities**.
- `python -m bandit -r engine server scrapers config models main.py scripts -ll -q` → exit 0 at medium and above.
- `.github/workflows/ci.yml` parsed as valid YAML.

**What changed:**

- `requirements-dev.txt`: added `pytest-cov`, `coverage`, `pip-audit` and `bandit`; upgraded `pytest` 8.4.1 → 9.0.3 to clear `PYSEC-2026-1845` instead of allowlisting it.
- `pyproject.toml`: `[tool.coverage.run]` measures only the five application packages and `[tool.coverage.report]` enforces `fail_under = 80` (baseline 81.55%).
- `.github/workflows/ci.yml`: split into `quality`, matrixed `tests` (3.11 required, 3.12 forward-compatible) and `security`; the 3.11 test leg writes a markdown coverage summary to the run page and uploads `coverage.xml`; `pip-audit` audits runtime and dev requirements; Bandit fails at medium and above. Added `permissions: contents: read`.
- `server/api.py`: the SHA-1 review-queue id now passes `usedforsecurity=False`; it is a stable key, not a security primitive.
- `scripts/capture_market_fixtures.py`, `scripts/docker_smoke.py`, `scripts/soak.py`: three explicitly documented `# nosec` entries (`B501` for the capture-only certificate exception, `B310` for the two loopback/operator HTTP probes).
- `docs/CI.md` (new): coverage baseline and floor, local reproduction, the pip-audit upgrade and future allowlist rule, and the three-row Bandit allowlist.
- `README.md`: development commands now include coverage, pip-audit and Bandit, linking `docs/CI.md`.
- `.gitignore`: ignores `.coverage*`, `coverage.xml` and `htmlcov/`.
- `tests/test_ci_hardening.py` (new): guards the dev pins, coverage scope/floor, CI coverage publication, security jobs, matrix, allowlist documentation and ignored artifacts.

**Trust rules:** unchanged. No application behaviour changed apart from the non-security hash flag; the certainty gate, price guard, freshness and feed-integrity policy are untouched.

**Follow-ups:** P1-5 (alerting), P1-6 (24-hour soak) and P1-7 (raw-price invariant) remain. The Docker build/smoke from P1-3 still needs one run on a Docker-capable host.

---

### 2026-11-04 — P1-3: Reproducible deployment (Docker/systemd)

**Task:** P1-3 (first eligible task after P1-2; no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,328 passed**, 1 warning, 177.70 s (was 1,318; +10 tests).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 150 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- `docker-compose.yml` and `.github/workflows/docker.yml` parsed as valid YAML.
- `python scripts/docker_smoke.py --help` → CLI loads.
- **Not run locally:** `docker build` / the container smoke. The Docker daemon socket is not accessible to this session's user (`docker info` → permission denied; the user is not in the `docker` group), and `sudo` requires an interactive password. The optional Docker workflow runs the same build and smoke on a runner with Docker access.

**What changed:**

- `Dockerfile` (new): `python:3.11-slim`, pinned `requirements.txt`, Playwright Chromium via `--with-deps`, `PLAYWRIGHT_BROWSERS_PATH`, non-root `scanner` user with `BH_UID`/`BH_GID`, health check, `CMD python main.py`.
- `.dockerignore` (new): excludes git, virtualenvs, test/lint/type caches, runtime `cache`, the gitignored mapping ledger, tests, docs and secrets.
- `docker-compose.yml` (new): loopback port, `.env` interpolation, `./cache` and `./config` bind mounts, health check, read-only root, `no-new-privileges`, `/tmp` tmpfs and 1 GB `/dev/shm`.
- `deploy/bh-arb.service` (new): non-root, optional env file, restart-on-failure, `SIGINT`, `ProtectSystem=strict`, `ProtectHome=true`, state-only `ReadWritePaths`.
- `scripts/docker_smoke.py` (new): build → run with a named cache volume → health poll → non-root uid check → cache marker → restart → marker check → cleanup.
- `.github/workflows/docker.yml` (new): optional build + smoke job on deployment-path changes and manual dispatch.
- `docs/DEPLOYMENT.md` (new) and `README.md`: copy-paste Compose/systemd steps, UID/GID notes, health/metrics, smoke test, and the backup/restore list for `cache/`, the learned ledger, alias allowlist and edited declarations.
- `tests/test_deployment_assets.py` (new): offline guards for every asset above.
- `docs/PRODUCTION_READINESS.md`: Operations row now records the deployment path.

**Trust rules:** unchanged. Deployment does not alter the certainty gate, price guard, freshness or feed-integrity policy. The container runs non-root and mounts only the runtime state the scanner already writes.

**Follow-ups:** P1-4 (CI hardening) is the next eligible task. P1-5 and P1-6 remain unblocked. The Docker build/smoke should be run once on a Docker-capable host or via the optional workflow; the local limitation is recorded above.

---

### 2026-11-04 — P1-2: Structured logs, request IDs, metrics endpoint

**Task:** P1-2 (first eligible task after P1-1; no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,318 passed**, 1 warning, 173.82 s (was 1,302; +16 tests).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 148 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- New tests cover request-id echo/generation/replacement, ids on refused requests, context propagation, the JSON allowlist and traceback, `LOG_FORMAT=json`, Prometheus text/escaping, `/api/metrics` without a server, API-key protection, one structured scan-completion record, per-book outcomes, and the failed-scan counter.

**What changed:**

- `server/observability.py` (new): request/scan context ids, a log-record factory that stamps them on every record, `ContextLogFilter`, `JsonLogFormatter` with a fixed extra allowlist, `configure_logging()`, and a dependency-free Prometheus counters/gauges registry with dynamic gauge providers.
- `server/app.py`: request-id middleware accepts a safe incoming `X-Request-ID` or generates one, returns it on every response (including 401/403), and emits a debug completion line.
- `server/api.py`: scan started/completed/failed, duration, per-book success/empty/error/skipped, surebets found/dropped, link checks, candidate-queue size, cache size, last-scan age, browser-slot and RSS gauges; one structured `scan complete` log (and `scan failed` with traceback); `GET /api/metrics` in Prometheus text, protected like other routes.
- `main.py`, `config/settings.py`, `.env.example`: `LOG_FORMAT` (`text`/`json`) wired into startup logging.
- `tests/test_request_id.py`, `tests/test_metrics.py` (new); two unrelated pricing fixtures moved to a fixed 2030 kickoff because their 2026-11-04 18:00 value expires during the evening and made the suite time-dependent.
- `README.md`, `docs/ACCEPTANCE.md`, `docs/PRODUCTION_READINESS.md` document the metrics, log format and correlation ids.

**Trust rules:** unchanged. Metrics are observational only; they do not price, rank or admit a surebet. The JSON formatter serialises a fixed allowlist, so odds payloads, API keys and arbitrary extras cannot be logged. The endpoint uses the same API-key guard and dependency as every other `/api` route.

**Follow-ups:** P1-3 (reproducible deployment) and P1-4 (CI hardening) are the next eligible tasks. P1-5 and P1-6 are now unblocked by P1-2.

---

### 2026-11-04 — P1-1: Paginated, filtered group-evidence API

**Task:** P1-1 (first eligible task after P0-7; depends on P0-1, which is Done).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,302 passed**, 1 warning, 183.33 s (was 1,292; +10 tests).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 145 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- New tests prove the default page is 50 (max 200), filters/offset work, detail returns exactly one group and 404s unknown ids, summaries omit the evidence trail and stay under 100 KB for 100 groups, the compatibility alias is bounded, and the dashboard has the Evidence tab hooks.

**What changed:**

- `server/api.py`: `GET /api/groups` returns bounded summaries with status/sport/search filters and limit/offset; `GET /api/groups/{group_id}` returns one group's full evidence or 404; `/api/debug/report` is now a bounded compatibility alias with a deprecation note.
- `frontend/index.html`, `frontend/js/app.js`, `frontend/css/style.css`: Evidence tab with filters, paging, summary rows and a one-group detail view.
- `tests/test_groups_api.py`, `tests/test_frontend_evidence.py` (new); `tests/test_other_sports_frontend.py` updated for the expanded tab list.
- `README.md`, `docs/ACCEPTANCE.md`, `docs/PRODUCTION_READINESS.md` document the endpoints and drill-down.

**Trust rules:** the evidence trail is not truncated in the detail response; only the list endpoint strips it. No gate, link, settlement or price-source rule changed.

**Follow-ups:** P1-2 (structured logs, request IDs, metrics endpoint) is the next eligible task; P1-3 and P1-4 are also unblocked.

---

### 2026-11-04 — P0-7: Feed-integrity scorecard and stale-book quarantine

**Task:** P0-7 (first eligible task after P0-6; depends on P0-4, which is Done).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,292 passed**, 1 warning, 192.91 s (was 1,286; +6 tests).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 143 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- New tests prove a stale book cannot supply a priced leg, a below-1.0 own set is quarantined, recovery needs three clean scans, the gate's group is unchanged, and both APIs expose the scorecard.

**What changed:**

- `engine/feed_integrity.py` (new): per-book freshness, empty/parse, missing-market, own-margin and outlier metrics; healthy/degraded/quarantined states; bounded last-20 history; three-clean-scan recovery; `priceable_groups()` removes quarantined legs from pricing copies only.
- `engine/market_consensus.py`: exposes `complete_market_spec()` for the integrity scorer.
- `config/settings.py`: integrity thresholds and recovery/history policy.
- `server/api.py`: computes the scorecard after grouping, prices from the filtered groups, passes the same groups to the price guard, persists `cache/feed_integrity.json`, and exposes `feed_integrity` in `/api/results` and `/api/health`.
- `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js`: an unhealthy-book strip with state and reason, including `not priced` for quarantine.
- `tests/test_feed_integrity.py` (new).
- `README.md`, `docs/ACCEPTANCE.md`, `docs/PRODUCTION_READINESS.md` document the scorecard and the price-source restriction.

**Trust rules:** quarantine is applied only to pricing copies. The certainty gate, its evidence, settlement and link decisions are untouched; a subset of a verified group remains the same event. Outlier quarantine needs at least 10 comparable markets so a genuine three-book edge is not mistaken for a bad feed.

**Follow-ups:** P1-1 (paginated, filtered group-evidence API) is the next eligible task. P1-2, P1-3 and P1-4 are also unblocked.

---

### 2026-11-04 — P0-6: Opportunity-rate and arb-lifetime telemetry

**Task:** P0-6 (first eligible task after P0-5; depends on P0-4, which is Done).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,286 passed**, 1 warning, 176.90 s (was 1,278; +8 tests).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 141 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- `python scripts/opportunity_baseline.py --days 7` → renders the aggregate history report; with no live history yet it states that the local window is empty rather than inventing a number. The report is `docs/evidence/2026-11-04-opportunity-rate-baseline.md`.

**What changed:**

- `engine/opportunity_metrics.py` (new): `BoardObservation`, `ScanMetrics`, `summarize_scan()`, bounded `update_lifetimes()` and `lifetime_distribution()`.
- `engine/arbitrage.py`: `find_surebets(..., metrics=...)` records every board from the existing pricing pass, before display filters; no second arb formula.
- `server/api.py`: each scan stores `opportunity_metrics` (denominators, median/best margin, zero-result reason, p50/p90 lifetime) in `/api/results` and `/api/health`; persists compact aggregates plus the bounded crossing-key store and per-scan history to `cache/opportunity_metrics.json`.
- `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js`: a **Crossing rate** KPI and zero-result reason.
- `scripts/opportunity_baseline.py` (new) and `docs/evidence/2026-11-04-opportunity-rate-baseline.md` (new; local 7-day window explicitly marked pending).
- `tests/test_opportunity_metrics.py` (new): no crossing, below-floor crossing, above-floor action, stale group, lifetime disappearance, key cap, API exposure, aggregate-only persistence.
- `README.md`, `docs/ACCEPTANCE.md`, `docs/PRODUCTION_READINESS.md` document the metric and its limits.

**Trust rules:** observations are taken from the same engine path, before filters; the certainty gate and price guard still decide what is actionable. Stale groups are reported as `stale_data`, not as a no-crossing market.

**Follow-ups:** P0-7 (feed-integrity scorecard and stale-book quarantine) is the next eligible task. The local 7-day baseline remains empty until scheduled scans have run; the report says so.

---

### 2026-11-04 — P0-5: Reloadable deep-link declarations

**Task:** P0-5 (first eligible task after P0-4; no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,278 passed**, 1 warning, 190.98 s (was 1,275; +3 tests).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 138 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- New tests cover: a temp declaration edit visible on the next call without restart; a malformed file clearing the map and failing safe; recovery after the file is fixed; `/api/health` reporting `loaded_at`, `source_mtime`, `stale` and `error`.

**What changed:**

- `scrapers/common.py`: the declaration loader tracks `(mtime_ns, size)`, reloads on change, records `loaded_at`/`source_mtime`/`load_error`, and exposes `deeplink_declaration_source()`. `effective_deeplink_declarations()` entries now carry `loaded_at`, `source_mtime` and `stale`.
- `server/api.py`: `/api/health` adds `deep_link_declaration_source` next to `deep_link_declarations`.
- `tests/conftest.py`: resets the new loader provenance between tests.
- `tests/test_deeplinks.py`, `tests/test_candidates_api.py`: reload, fail-safe and health coverage.
- `README.md`, `docs/ACCEPTANCE.md`, `docs/HANDOFF.md` document the reload behavior; F5 is closed.

**Trust rules:** a missing or malformed declaration still grants nothing. The change removes a restart requirement; it does not make an absent or invalid declaration prove anything.

**Follow-ups:** P0-6 (opportunity-rate and arb-lifetime telemetry) and P0-7 (feed-integrity scorecard) are both unblocked by P0-4. P0-6 comes first in table order.

---

### 2026-11-04 — P0-4: Runtime freshness and stale-state policy

**Task:** P0-4 (first eligible task after P0-3; no dependencies). P0-1 was already `Done`, so it was not repeated.
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,275 passed**, 1 warning, 182.58 s (was 1,262; +13 tests).
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 138 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- Task-specific matrix in `tests/test_freshness_api.py`: fresh, near-expiry, one second past TTL, one stale book among fresh ones, live 60 s TTL, never scanned, missing timestamp, per-leg fetch time. `tests/test_frontend_freshness.py` executes the shipped staleness helper under Node and pins the stale banner and disabled copy actions.

**What changed:**

- `config/settings.py`: added `LIVE_ODDS_TTL_SECONDS = 60`; the engine and API now read the same policy.
- `server/api.py`: `_freshness_block()` adds `mode`, `scan_time`, `age_sec`, `ttl_sec`, `stale`, `state`, `stale_books` and per-book oldest/newest `fetched_at`/ages/missing counts to `/api/results` and both feeds in `/api/health`. Cached rows remain served for diagnosis.
- `models/schemas.py`, `engine/arbitrage.py`: every `SurebetStake` carries its own `fetched_at`; the engine attaches the winning book's collection time (earliest if a book is listed twice).
- `frontend/index.html`, `frontend/js/app.js`, `frontend/css/style.css`: runtime stale banner, `feed-stale` styling, age recomputed from the scan timestamp each second, copy actions disabled while stale, **Re-check odds** left enabled as the only path back to a current price.
- `tests/test_freshness_api.py` (new), `tests/test_frontend_freshness.py` (new).
- `README.md`, `docs/ACCEPTANCE.md`, `docs/PRODUCTION_READINESS.md` document the policy and the remaining freshness gaps.

**Trust rules:** no certainty-gate, link-proof, settlement, cache-restore or one-leg-per-book/price-source rule was changed. Staleness is a price-source/currentness label, not an identity decision.

**Follow-ups:** P0-5 (reloadable deep-link declarations) is the next eligible task by table order. P0-6 and P0-7 are now unblocked by P0-4.

---

### 2026-11-04 — P0-3: Gate-vocabulary truth audit

**Task:** P0-3 (first eligible task after P0-2; no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,262 passed** (was 1,261; +1 test), 1 warning.
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 136 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- Probe now observes both missing reasons: `orientation_unresolved` from a shared Betradar id with names that tie both ways, and `sport_mismatch` from a football/basketball pair. Rejected vocabulary is the four `HARD_REJECT_REASONS` members plus `sport_mismatch`; suggested vocabulary is unchanged.

**What changed:**

- `tests/test_readme_claims.py`: `_observed_reasons()` classifies by each gate result's status (not membership in `HARD_REJECT_REASONS`) and adds the orientation-tie and cross-sport cases. `test_status_reason_vocabulary_matches_what_the_gate_emits` now pins `HARD_REJECT_REASONS ⊆ rejected` and `rejected - HARD_REJECT_REASONS == {"sport_mismatch"}`. The old "dead vocabulary" test became `test_no_hard_reject_reason_is_dead`. Added `test_gate_source_reason_vocabulary_is_fully_exercised`, which scans the gate's reason sinks so a new literal fails until a probe case and README row exist.
- `tests/test_certainty.py`: replaced the stale `test_reason_vocabulary_except_orientation_is_reachable` with `test_gate_reason_vocabulary_is_reachable`, covering all ten reasons.
- `README.md`: rejected row now lists `orientation_unresolved` and `sport_mismatch`; the "never emits" wrinkle is gone and the `sport_mismatch` exception is explained.
- `docs/HANDOFF.md`: item 6 marked fixed; fixed vocabulary completed. `docs/superpowers/specs/2026-09-25-match-and-game-mapping-design.md`: reason list completed.

**Follow-ups:** P0-4 is the next eligible task (runtime freshness and stale-state policy).

---

### 2026-11-04 — P0-2: Dashboard XSS, inline handlers, nonce CSP

**Task:** P0-2 (first eligible task after P0-1; no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,261 passed** (was 1,254; +7 tests), 1 warning.
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 136 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs.
- Playwright smoke against a local uvicorn instance: no console/page errors, zero `[onclick]`/`[oninput]`/`[onchange]` elements, per-response nonce present, settings open + Escape close, theme and mode buttons, tab ArrowRight keyboard navigation, and a hostile-name copy button whose clipboard value round-tripped exactly.

**What changed:**

- `frontend/index.html`: every inline handler replaced with `data-action`/`data-*` hooks; both script tags carry `__CSP_NONCE__`.
- `frontend/js/app.js`: one delegated click/input/change handler; copy buttons use `data-copy`/`data-copy-message` via `copyAttributes`, never `JSON.stringify` in an attribute; slip actions and market chips use data attributes.
- `server/app.py`: per-request CSP nonce from `secrets.token_urlsafe`, `script-src 'self' 'nonce-…'` with no `'unsafe-inline'`, dashboard served through `HTMLResponse` with `Cache-Control: no-store`. `style-src 'unsafe-inline'` remains because generated rows set CSS custom properties; documented as the only CSP gap.
- `tests/test_csp_nonce.py` (new), `tests/test_frontend_xss.py` (new; Node-executed helpers plus hostile-name parser test).
- `docs/ACCEPTANCE.md`, `docs/PRODUCTION_READINESS.md` updated; F2's documented gap closed.

**Follow-ups:** P0-3 is the next eligible task. P1-1 remains unblocked from P0-1.

---

### 2026-11-04 — P0-1: Bound the cached evidence payload

**Task:** P0-1 (first eligible task; no dependencies).
**Status:** Done.

**Commands and results:**

- `python -m pytest` → **1,254 passed** (was 1,251; +3 tests), 1 warning.
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 134 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 false merges, 0 unresolved evidence-backed pairs, 2 ledger claims.
- Frozen-cache measurement (`cache/last_scan.json`, 7,666 matches, re-grouped offline with kickoffs shifted as the replay does):
  - cache **218.5 MB → 23.3 MB**;
  - match-group JSON **127.8 MB compact / 178.8 MB indented → 7.3 MB / 11.1 MB**;
  - allowlist evidence records **1,288 → 63**; persisted entries **4,292,904 → 118**; largest record **3,333 → 4**;
  - cache parse **2.62 s → 0.58 s** (median of 3 runs).
- Differential run with the old evidence behavior produced the same **1,237** group signatures and statuses as the new code, so decisions did not change.
- New tests: `test_allowlist_evidence_records_only_the_proving_entry`, `test_cached_group_payload_is_bounded`, `test_health_reports_the_cache_size_budget`.

**Files changed:** `engine/certainty.py` (pair→entries index; `_proving_allowlist_entries`), `server/api.py` (compact cache writer, size guard and `/api/health` `cache` block), `config/settings.py` (`CACHE_SIZE_BUDGET_BYTES`), `tests/test_certainty.py`, `tests/test_cache_serialization.py`, `tests/test_e2e_certified.py` (asserts the consulted entries instead of the whole allowlist), `docs/ACCEPTANCE.md`, `PROJECT_ROADMAP.md`.

**Follow-ups:** P0-2 is the first `Not started` task by table order; P0-3 is the roadmap's recommended small follow-up. P1-1 (paginated group-evidence API) is now unblocked; the `/api/debug/report` payload is ~11 MB for this scan, still worth pagination but no longer a 179 MB browser freeze. Compact cache writing is runtime-only; config and decision files keep readable indentation.

---

### 2026-11-04 — Deep research pass

**Task:** deeper online research on arbitrage economics and scraped-data processing.
**Status:** Done (research only; no application code changed).

**Sources read:**

- Open-source projects: `Rijul0107/sports-arbitrage-scanner`, `cengizmandros/odds-arb-scanner`,
  `smartworkersai/KOS`, `Habeel-Shamsudeen/sportsbook-scraper`,
  `declanwalpole/sportsbook-odds-scraper`, `enesmertcetin/surebet-scanner`,
  `georgedouzas/sports-betting`.
- Vendor docs/blogs: OddsJam, BetBurger, RebelBetting, ClawArbs, SharpAPI, The Odds API,
  SportsGameOdds provider comparison, OddsPapi.
- Forums: two Arbusers threads (build-your-own software, legality of scraping).
- Reddit: direct fetch was blocked (HTTP 403), so search-index snippets were used for the
  “build your own scanner”, “how does OddsJam work so quickly”, “odds scraping and storage”,
  “best odds APIs”, “how to not get banned”, “3 years of arbing”, “93.62% NHL arb”, and
  “technical guide to scraping betting odds” threads.

**Key results:**

- Public board log: **1.34%** of 115,583 boards crossed; only **26** of 1,553 crossings were
  actionable after gates; median board margin **−3.60%**; 3 boards above 10% were treated as
  data errors.
- Twin books: Ladbrokes/Neds posted identical prices **99.9%** of the time across 11,198
  shared markets. BH_Arb hardcodes only the NSoft pair.
- Community consensus: stale/suspended prices and palpable errors are the main phantom-arb
  sources; account limits are the binding practical constraint; a 30-second cycle across five
  books is often too slow for live arbs.
- Vendor consensus: raw feed > HTML; WebSocket/push for live; canonical IDs first, aliases
  second, fuzzy only for candidates; missing data looks like a smaller dataset.

**Files changed:** `docs/RESEARCH_ARBITRAGE_2026-11-04.md` (new); `PROJECT_ROADMAP.md`
(findings F13–F19, tasks P0-6, P0-7, P1-7, P2-7, P2-8, P2-9, P3-6, P3-7).

**Follow-ups:** P0-1/P0-3 remain the first implementation tasks. P0-6 and P0-7 should follow
P0-4 because they depend on a coherent freshness state. Do not start P2-7 until there is a
scan-level price-agreement matrix to feed it.

---

### 2026-11-04 — Audit and roadmap

**Task:** repository audit, external research, roadmap creation.
**Status:** Done (implementation not started).

**Commands and results:**

- `python -m pytest` → 1,251 passed, 1 warning, 183 s.
- `python -m ruff check .` → clean.
- `python -m mypy .` → clean on 134 source files.
- `python scripts/generate_market_mapping_doc.py --check` → in sync.
- `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` → exit 0, fixed point, 0 unresolved evidence-backed pairs.
- Cache measurement: `cache/last_scan.json` = 218.5 MB; matches = 17.5 MB; groups = 133.1 MB; parse = 2.51 s.
- Evidence measurement: one group held 4 allowlist evidence entries of 97.5 KB each; trimming to 5 entries reduced the simulated group JSON from 133.1 MB to 8.0 MB.
- Ledger measurement: 23.6 MB, 4,632 claims, 0.43 s load; matcher init 0.72 s.

**Findings:** F1–F12 above. The roadmap prioritizes the payload bug, the frontend injection/CSP issue, the stale documentation, runtime staleness, and declaration reload before coverage or product work.

**Files changed:** `PROJECT_ROADMAP.md` (new).

**Follow-ups:** start with P0-1 and P0-3. Do not start P1-6 until P0-1 is measured.

---

## 7. Quick reference

### Run the same checks as CI

```bash
python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check
```

### Useful measurements

```bash
# Cache shape and size
python - <<'PY'
import json, os
p = 'cache/last_scan.json'
d = json.load(open(p, encoding='utf-8'))
print('MB', round(os.path.getsize(p) / 1e6, 1))
print('matches', len(d['matches']), 'groups', len(d['match_groups']))
print('matches JSON MB', round(len(json.dumps(d['matches'])) / 1e6, 1))
print('groups JSON MB', round(len(json.dumps(d['match_groups'])) / 1e6, 1))
PY

# Pairing quality
python scripts/pairing_audit.py --check

# One real scan, recorded as evidence
python scripts/record_scan.py prematch --out docs/evidence/prematch-scan.json
```

### Where to look

| Concern | File |
|---|---|
| The gate | `engine/certainty.py` |
| Grouping | `engine/matcher.py` |
| Pricing | `engine/arbitrage.py` |
| API routes and caches | `server/api.py` |
| Security middleware | `server/app.py` |
| Deep-link declarations | `config/bookmaker_deeplinks.json` |
| Market registry | `config/bookmaker_markets.json` |
| Evidence ledger | `config/generated/mapping_evidence.json` |
| Dashboard | `frontend/index.html`, `frontend/js/app.js` |
| Tests and fixtures | `tests/`, `tests/fixtures/` |
| Prior design record | `docs/HANDOFF.md`, `docs/PRODUCTION_READINESS.md`, `docs/ACCEPTANCE.md` |
