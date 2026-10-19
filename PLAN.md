# Surebet Scanner — Detailed Execution Plan (Muse 12)

> **Goal:** Fix “rare + wrong” surebets and grow arbitrage yield 5–10× while keeping false positives near zero.
> **Baseline:** `claudesurebet` == `dzanagamba/surebet-scanner` @ `7d2d5d8` (9 bookmakers, ~6057 prematch matches → ~802 groups → 0–2 surebets per scan, Mozzartbet degraded to 56 matches, EVLBet only 1X2).
> **New repo:** `surebetmuse12` — https://github.com/dzanagamba/surebet-muse12 (`plan/muse12-roadmap` @ `aa33254` → `2935d90`).
> **Status (2026-08-20):** P0 correctness + P1 yield + P2 reliability shipped. 107 tests green, ruff clean, groups 802→856 (+6.7%), WWIN 15s→~7s, Mozzart 56→800+ (projected), dust/health/TTL live.
> **Status (2026-09-26):** Phase 4 (mapping certainty) shipped — 13 tasks. `verified` requires a proven claim, and link evidence is proven two ways: a browser check opened that book's per-event URL, **or** the book declared in `config/bookmaker_deeplinks.json` that it has no per-event route. 6 of the 9 books declare `supports_event_id: false` and are verified on identity alone; the 3 that declare a route (MDShop, Admiralbet, Mozzartbet) must still have theirs proven, and MDShop's and Admiralbet's `?event=<id>` routes are **inert**, so a group holding either still cannot verify. **Zero surebets is today's expected output, and it is correct:** the shipped gate produces 0 surebets on the stored scan — a measured claim with two conditions, read in §3 *Phase 4* along with the correction that supersedes the 2026-09-25 status line.

## 0. Principles

1.  **Correctness over yield.** Never show an arb that can’t be bet. Every P1 yield change needs a P0 correctness guard (suspend check, label-set validation, staleness, cross-book distinct rule `engine/arbitrage.py:185`).
2.  **Evidence before synthesis.** Live payload captures under `tests/fixtures/` + `cache/last_scan.json` are ground truth. No “already verified” shortcuts.
3.  **One `fetched_at` to rule them.** All 9 scrapers stamped with the same scan wall-clock; mixing ages >90s is a bug, not a feature.
4.  **Matcher gates are load-bearing.** League `engine/matcher.py:208-215` + category `engine/matcher.py:204` + 120min `KICKOFF_WINDOW_MINUTES` `config/settings.py:122` are hard gates — relax only with metrics.

---

## 1. Repo Setup (Done / Next)

- [x] `git init surebetmuse12`, copy 52 source files from `claudesurebet` (excluded `.git/venv/cache/__pycache__/.mypy_cache/.pytest_cache`).
- [ ] Add `cache/.gitkeep` + `screenshots/.gitkeep` (track empty dirs, ignore `*.json` via `.gitignore:20`).
- [ ] Create `venv` (`python -m venv venv; pip install -r requirements.txt -r requirements-dev.txt; playwright install chromium`).
- [ ] Push to new GitHub remote `surebet-muse12` (private) with branch `main` + `plan/muse12-roadmap` for this doc.

Verify:

```bash
git -C surebetmuse12 log --oneline
python -m pytest -q          # 38+ tests, must stay green
python -m ruff check .
python -m mypy .
```

---

## 2. Diagnosis Recap (File-Line Precise)

### Why Rare

| # | Root Cause | Evidence | File |
|---|------------|----------|------|
| R1 | **Mozzartbet degraded** 54-56 vs 1150 expected | `cache/scan_history.json` last 3 prematch: 56, 54, 58; `BUILD_SPECIFICATION_V3.md:24` says ~54 “today” | `scrapers/mozzartbet.py:359-401` `pageSize=50` vs spec `15`, `matchCount` vs `totalPages` |
| R2 | **EVLBet single-market** 1X2 only | 1145 matches, all `market_type=1x2` (avg 1.0 mkts/match) | `scrapers/evlbet.py:107-135` |
| R3 | **Date window skew** 14d vs unbounded | `mdshop`/`mbet` 14d, `evlbet` none, `wwin` 15×24h | `scrapers/mbet.py:302`, `scrapers/mdshop.py:85`, `scrapers/wwin.py:150` |
| R4 | **League mapping misses** ~30% generic fallback | 262 `1.liga`, 110 `2.liga` as catch-alls; `PANIJA 1` not in map | `engine/matcher.py:43-46`, `config/league_mappings.json:440` |
| R5 | **Experimental markets off** | `first_half_1x2`, `first_half_ou`, `asian_handicap` defined but `enabled=false` | `config/settings.py:88-92`, `engine/arbitrage.py:127,132` |
| R6 | **Silent scraper failures** | `asyncio.gather(..., return_exceptions=True)` + `return []` hides zero-yield | `server/api.py:268-278` |
| R7 | **AH line incompatible + collapsed** | MBet overwrites per line, SportPlus only `0` | `scrapers/mbet.py:130-156`, `scrapers/sportplus.py:421` |

### Why Wrong

| # | Root Cause | File |
|---|------------|------|
| W1 | **No odds age** — mixed 20s-120s scrapers appear atomic | `models/schemas.py:31-50` no `fetched_at`, `server/api.py:268-271` concurrent |
| W2 | **Weak suspend checks** on 4 scrapers | `scrapers/mbet.py:56` GOOD (`ACTIVE`), others only `>=1.01` |
| W3 | **`Z` suffix + `kickoff=None`** → `time_score=0.65`, never expires | `scrapers/sportplus.py:291`, `scrapers/common.py:38` |
| W4 | **Stale cache replay** after restart | `server/api.py:340-367` `_load_cache()` no TTL |
| W5 | **Live `kickoff=None`** groups never filtered | `scrapers/sportplus.py:164` |

Live suspicious arbs: `maardu-tallinn` Over1.5 1.27 vs Under 7.32 (8.22%), `bayern-rb_leipzig` 1.18 vs 9.5 (4.96%) — likely suspended/dead line or category mismatch `world club friendly`.

---

## 3. Phased Plan

### Phase 0 — Correctness (P0) — Stop Showing Wrong

**Goal:** Zero phantom arbs. Every displayed surebet re-verifiable <60s stale.

| ID | Task | Files | Acceptance |
|----|------|-------|------------|
| P0-1 | **Add `fetched_at` + `scan_id`** to `Match` (`datetime`, naive UTC). Stamp once in `server/api.py:run_scan` `scan_started_at = datetime.now(UTC).replace(tzinfo=None)` and pass to every `scrape(live, fetched_at)`. | `models/schemas.py:31`, `scrapers/*.py`, `server/api.py:217-271` | `GET /api/results` returns `fetched_at`; mixed-age scan fails if spread >90s |
| P0-2 | **Unified suspend guard.** Extract `is_active_odds(value, status)` to `scrapers/common.py` (checks `market_status`, `isv`, `naPon`, `value>=1.01`). Enforce in `mozzartbet.py:187`, `sportplus.py:381`, `wwin.py:69`, `premier_kladionica.py:265`. | `scrapers/common.py:195-350` | No odds <1.01 or inactive reaches `engine/arbitrage.py:177` |
| P0-3 | **Fix `parse_dt` everywhere.** Replace ad-hoc `fromisoformat` in `sportplus.py:291` + `mbet.py:376` with `scrapers/common.py:23 parse_dt` (handles `Z`, `+02:00` → UTC). Add `tests/test_scraper_common.py` case for `Z`. | `scrapers/common.py:23`, `scrapers/sportplus.py:291`, `scrapers/mbet.py:302` | `parse_dt("2026-08-15T18:00:00Z")` == `parse_dt("2026-08-15T20:00:00+02:00")` |
| P0-4 | **Mozzartbet pagination fix.** Use `pageSize=15` per `BUILD_SPECIFICATION_V3.md:127`; read `totalPages` fallback to `matchCount` fallback to `<pageSize` break. Capture fixtures. | `scrapers/mozzartbet.py:358-401` | Mozzartbet prematch ≥800 matches on next live scan (vs 56 today) |
| P0-5 | **Uniform scan window.** `run_scan` computes `window_start = scan_started_at`, `window_end = start+14d` and passes to `mdshop/mbet/wwin`. Remove per-scraper `datetime.now()`. | `server/api.py:217`, `scrapers/mdshop.py:83`, `scrapers/mbet.py:302`, `scrapers/wwin.py:139` | All prematch books report same `dateFrom/dateTo` in logs |
| P0-6 | **Cache TTL + badge.** `_save_cache` stores `fetched_at` + `scan_id`; `_load_cache` rejects `>30min` old; dashboard shows `Odds age: Xs` + `Verify Odds` auto-prompts if >120s. | `server/api.py:322-367`, `frontend/js/app.js:155-` | Restart doesn’t show 8h-old arbs |
| P0-7 | **Rate-limit + lock fix.** Hold `_scan_lock` during whole `run_scan` (not just trigger), separate `prematch` vs `live` locks. | `server/api.py:63,403` | Two rapid `POST /api/scan` second returns `already_scanning` reliably |

**Verify P0:** `python -m pytest` green, `ruff`/`mypy` clean, live prematch scan logs show 5–6k matches with mozzartbet ≥800 and no `kickoff=None` on prematch.

### Phase 1 — Yield (P1) — 5–10× More *Real* Opportunities

**Goal:** 15–30 groups with `profit≥0.5%` per prematch scan (vs 0–2 today), without raising false-group rate >1%.

| ID | Task | Files | Acceptance |
|----|------|-------|------------|
| P1-1 | **EVLBet market expansion audit.** Re-capture `sportsapis.evlbet.com/.../matches/flat` for 1,500 events; confirm if `DetailedOffer` carries BTTS/O/U. If yes, parse; if not, document and **exclude EVL from BTTS/O_U arb legs** (prevent impossible combos). | `scrapers/evlbet.py:107-135`, `MARKET_MAPPING.md:168-178` | EVL avg mkts/match either >1 or explicitly single-market with code comment + test |
| P1-2 | **League mappings auto-grow.** Script `scripts/generate_mappings.py` reads `cache/last_scan.json` (last 7 days) → proposes new `league_mappings.json` entries where `league_normalized` is generic but raw appears >5×. Manual review + commit. | `config/league_mappings.json`, `engine/normalizer.py:288-316` | Generic league share drops from ~30% → <15% |
| P1-3 | **Matcher recall tuning (measured).** A/B test on `cache/last_scan.json` snapshot: try `FUZZY_MATCH_THRESHOLD 80→75` for O/U/BTTS-only groups, keep 80 for 1X2; add `country` soft gate `engine/matcher.py:197` (both non-empty & mismatch → reject). Keep `team token_set_ratio` 70. Evaluate via `tests/test_matcher.py` + `tests/test_pipeline.py`. | `engine/matcher.py:190-255`, `config/settings.py:122-124` | Groups 802 → 950-1050 without new `WOMEN_PATTERN` false positives |
| P1-4 | **Asian handicap unification.** Fix `mbet.py:130-156` to keep dict `ah_by_line: dict[float, dict[str,float]]` not overwrite; expand `sportplus.py:421` to parse lines `-0.5/0/0.5/1` from `id=25` variants; align `ah_label` `scrapers/common.py:76-81`. Enable `asian_handicap` in `config/settings.py:88` after audit. Add `tests/test_new_markets.py`. | `scrapers/mbet.py:130`, `scrapers/sportplus.py:398-432`, `scrapers/common.py:68-103`, `config/settings.py:88` | AH arb possible across MBet↔SportPlus on same signed line |
| P1-5 | **WWIN + Premier throughput.** WWIN: fetch Playwright cookies once, then `httpx.AsyncClient` for 60 `PrematchEvents/events` calls (15 days ×4 bet groups) concurrently (`asyncio.gather` batch 6). Premier: concurrent delta sync `asyncio.gather` over `ODDS_CHUNK` 150. | `scrapers/wwin.py:136-218`, `scrapers/premier_kladionica.py:213-223` | WWIN prematch time 15s → 7s; Premier 20s → 10s |
| P1-6 | **Profit-threshold strategy.** Keep `MIN_PROFIT_PERCENT=0.5` `config/settings.py:95` for default display, but surface 0.2-0.5% as “Dust” tab with auto-verify required. Histogram in `GET /api/debug/report`. | `engine/arbitrage.py:193-205`, `frontend/js/app.js:155` | Dust tab shows 5-10 extra candidates, none auto-tradeable |
| P1-7 | **Bookmaker health dashboard.** `GET /api/health` already exists `server/api.py:419` — extend with per-book `last_success, last_count, avg_time, error`. Frontend badge per book. | `server/api.py:419-429`, `frontend/index.html/js` | Failing scraper obvious in ≤1 scan, not silent |

**Verify P1:** Prematch scan consistently 900-1100 multi-book groups; 3–7 arbs `≥0.5%` on weekdays, 10+ on heavy days, all `still_profitable` on immediate `POST /api/verify`.

### Phase 2 — Reliability & Scale (P2)

| ID | Task | Detail | File |
|----|------|--------|------|
| P2-1 | Browser pool | Single `launch_browser()` `scrapers/base.py:35` shared across Mozzartbet/Admiralbet/WWIN (2 contexts, `bs-BA` locale). | `scrapers/base.py:35-71` |
| P2-2 | Unified retry | `fetch_with_retry` `scrapers/base.py:74-101` for every `httpx` scraper, with 403 → fresh context. | `scrapers/*.py` |
| P2-3 | Odds TTL expiry | `engine/arbitrage.py:86-95` reject groups where any leg `now - fetched_at > 180s` in live mode. | `engine/arbitrage.py:86` |
| P2-4 | Incremental verify | `POST /api/verify` already re-scrapes involved books `server/api.py:563-597` — add cache key by `scan_id` to avoid re-grouping whole 6k. | `server/api.py:563` |
| P2-5 | Observability | Structured logs + `/api/debug/report` per-league miss reasons. | `server/api.py:535`, `engine/matcher.py:182` |

### Phase 3 — Product & Growth (P3)

* **Deep links:** Populate `bet_url` `models/schemas.py:45` for NSoft (`nsoft_event_url` `scrapers/common.py:105` + `ticketItems` when reverse-engineered) and MBet/SportPlus.
* **Notifications:** Telegram/Discord webhook on `profit>1.5%` new `surebetSignature` `frontend/js/app.js:30` mirrored server-side.
* **New books:** Evaluate 2–3 BiH books beyond 9 (e.g., MaxBet BiH, Meridianbet) — same NSoft/Alea audit as `MARKET_MAPPING.md`.
* **Sim/sim-paper trading:** Small-stakes probe on `dust` arbs to measure realized vs displayed odds (books often limit).

### Phase 4 — Mapping certainty (Done)

Shipped in `.superpowers/sdd/2026-09-25-match-and-game-mapping/`, 13 tasks.
The premise: the old matcher decided "same match" with a fuzzy score and a
threshold, so a wrong pairing and a right one looked alike. Phase 4 replaces the
score with a claim that has to be proven.

**Task list (all shipped).** Data model (`MatchEventStatus`, `MatchEvidence`,
`MatchGroup`, `CandidateReview`) · the `CertaintyGate` and its reason vocabulary ·
league equivalence restricted to declared pairs · the shared market registry
(`config/bookmaker_markets.json`) · declared deep links
(`config/bookmaker_deeplinks.json` + `build_event_url`) · the AI candidate layer
(`engine/ai.py`) · the review queue and its API · candidate suppression and
human approval · captured-payload fixture tests for every registry entry · the
deep-link verification endpoint and Playwright checker · the end-to-end guard
(`tests/test_e2e_certified.py`) · docs (`README.md` § *Match & mapping certainty*).

**The invariant everything else serves:** a `verified` group requires ZERO
reasons, links included. Allowlisted fuzzy aliases are the only auto-accepted
fuzzy path. The AI never auto-approves a pair — a human approval grants team
identity only, never `deep_link_verified`, which is a machine fact.

**HEADLINE RESULT, and it is not a good-looking one.** `verified` groups were
unreachable in production. MDShop's and Admiralbet's declared `?event=<id>`
routes are **inert**: the served page is byte-identical to the plain football
prematch page, the id appears in none of ~250 captured response bodies or in
rendered text, and `?event=` provokes no event-scoped request. Only Mozzartbet
verifies (15/15, via `$.match.id`; a dead id answers 200 with 14 bytes instead of
328 KB). Consequence, measured on a real 1,592-match three-book feed: **0 of 197
candidate groups verified, so zero surebets were produced.** The gate, the
registry and the parsers are correct and tested.

**Correction (2026-09-26): that measurement was the gate being stricter than the
design specified, not only a bookmaker-side routing fact.** The gate never read
`supports_event_id`, so the six books that declare no per-event route were refused
for the links they never claimed to have — the declaration was documented in
§4 of the design spec and wired to nothing. The gate now consults
`config/bookmaker_deeplinks.json`: a declared-false book is verified on identity
alone with a `no_event_link` evidence note, a declared-true book still needs its
route proven, and a book with no declaration fails safe. So "flipping the route to
`supports_event_id: false`" is no longer the no-op this section used to call it —
it is exactly what such a book now relies on. The bookmaker-side routing fact
above stands on its own: a group holding MDShop or Admiralbet still cannot be
`verified` while their routes are inert.

**Measured on the stored scan (2026-09-26).** `cache/last_scan.json`: 6,999
matches, 7 books, `scan_time 2026-08-20T18:26:52Z` — 36 days old — and **0 of
6,999 matches carry a proven link**. The matcher and the arbitrage engine are
pure functions of that file, so the whole measurement is offline:

| scenario | verified groups | surebets |
|---|---|---|
| **A — links exactly as cached (the state this repo is in)** | **16** | **0** |
| B — plus Mozzartbet's link *faked* proven | 179 | 0 |
| C — every book's link *faked* proven (the ceiling) | 516 | 0 |

Before the fix, the same gate with the declaration lookup answering "nothing is
declared", A and B are 0/0 and C is **516/0** — bit-identical, which is the
monotonicity datum: the change only ever adds pairs, it removes none.

**Conditions, and read them before quoting any of the three.**
* **A is the only scenario the repo is actually in.** B and C require setting
  `deep_link_verified=True` on matches no browser check has proven. **No browser
  check has been run in this repo** — nothing in `cache/` carries a
  `deep_link_verified` flag, and `scripts/verify_deeplinks.py` is on-demand,
  never part of a scan. Until `/api/verify-links?bookmaker=mozzartbet` is run and
  its result stored, B and C are arithmetic, not observations.
* **A surebet count from this cache needs two rewrites.** Every match's
  `fetched_at` has to be reset to now and kickoffs shifted into the future, or
  the engine refuses every leg for reasons unrelated to the link gate. Both are
  applied and neither touches link state. A surebet that appears only after those
  two rewrites is not evidence that the arbitrage is still on.
* **The group counts above predate the order fix.** `MatchMatcher.group_matches`
  used to let the first match to arrive anchor its group, so this feed gave 16, 34
  or 106 for scenario A depending only on the order the books were fed in. It now
  processes listings in a total order and falls through to the next-best group
  when the gate refuses one, so a count no longer depends on input order — but
  the figures here were taken before that change and have not been re-measured
  (see `docs/HANDOFF.md` §4 for after-fix numbers on a newer cache).
* Zero surebets on a 36-day-old cache is a statement about that cache, not about
  any book's prices today.

**Superseded figure.** The whole-branch report of 2026-09-26
(`whole-branch-fix-link-declaration.md`, §6) quotes "202 groups / 1 surebet" for
scenario B. It does not reproduce: the shipped gate gives 179/0. Its surebet is
`premier_kladionica` Over 2.5 at 2.15 against `sportplus` Under 2.5 at 1.9 —
both prices are really in the capture, and 1/2.15 + 1/1.9 is 0.86% — but those
two matches are 120 minutes apart and `VERIFIED_KICKOFF_WINDOW_MINUTES` is 15, so
the gate refuses the pair with `kickoff_delta` at *any* link state. The matcher
admits it as a candidate (`KICKOFF_WINDOW_MINUTES` is 120) and the gate then
rejects it; that is the pairing working, not a link problem. The report's 26 and
532 group figures do not reproduce either, for the order reason above.

**Recorded, not fixed** (both have tripwires):
* `premier_kladionica/live/btts` — the live BTTS block is named
  `LIVE - OBA TIMA DAJU GOL`, the parser's `NAME_BTTS` is `OBA DAJU GOL`.
  `xfail(strict=True)`, so fixing the parser fails the suite until the marker is
  removed. The fix is mode-awareness, not a registry rename.
* NSoft live window (`mdshop`, `admiralbet`) — `dateFrom=now` excludes every
  already-started in-play game, so both books most likely return no live matches
  at all today. `KNOWN DEFECT` comment in `scrapers/mdshop.py`.

**Fixed since the above list was written:**
* `build_targets` takes `settled` and `offset`, so a per-book link sweep advances
  instead of re-checking its first N events. The endpoint fills `settled` itself
  from `cache/deep_link_decisions.json`, which records every COMPLETED check — a
  navigation that errored is not a verdict, so that event is offered again. This
  — not the rate limit — was what blocked convergence. A sweep still costs
  `events / limit` calls at 2 calls/min: 608 mozzartbet events at the cap of 20
  is 31 calls, about 15 minutes.

**Verification.** `pytest` 572 passed + 1 xfailed (2026-09-26), `ruff` clean,
`mypy` clean.
`tests/test_e2e_certified.py` drives mbet/wwin/sportplus through their real
parsers on the real 2026-09-25 captures and asserts the chain end to end,
including that a spoiled claim in any one book removes the surebet. Its constants
are tied to the captured prices, so re-running `scripts/capture_market_fixtures.py`
requires re-deriving `EXPECTED_LEGS` / `EXPECTED_MARGIN` / `UNSWAPPED_COMBINATIONS`.

---

## 4. Execution Order (Next 2 Weeks)

**Week 1 (P0):** P0-4 → P0-3 → P0-5 → P0-1 → P0-2 → P0-6 → P0-7. Each with fixture test.
**Week 2 (P1):** P1-1 → P1-5 → P1-2 → P1-3 → P1-4 → P1-6 → P1-7.

Do not start P1 before P0 green + Mozzartbet fixed (otherwise yield metrics lie).

---

## 5. Test Plan

* Existing: `python -m pytest` must stay green. Key suites: `test_arbitrage.py` (one-bet-per-bookmaker), `test_matcher.py` (swap/category), `test_market_mapping.py` (22 tests), `test_pipeline.py`.
* New: `tests/test_scraper_common.py::test_parse_dt_z`, `tests/test_mozzartbet_pagination.py`, `tests/test_staleness.py` (mix-age reject), `tests/test_evlbet_markets.py`.
* Live: manual `POST /api/scan?mode=prematch` + `POST /api/verify` on each displayed arb before considering it real.

---

## 6. Risks

* **Cloudflare tightening** on WWIN/Premier — mitigated by cookie-reuse + retry; fallback to `betole` disabled toggle.
* **Matcher relaxation causing false groups** (e.g., Borac BL vs Borac Čačak) — mitigated by `country` soft gate + keeping league hard gate, only relaxing for O/U/BTTS.
* **EVLBet overreach** mis-parsing `HasSbv` as O/U — mitigated by strict label-set validation `scrapers/common.py:325-333`.

---

## 7. Definition of Done

* Prematch scan: 5k-9k matches, 900-1150 multi-book groups, 3-10 arbs `≥0.5%` on demand, each `verify` `still_profitable` within 60s.
* No `kickoff=None` on prematch, no `mozzartbet` <500, no generic league >15%.
* All new code covered by `pytest` + `ruff` + `mypy`, `MARKET_MAPPING.md` updated with any new market.

*Generated for `surebetmuse12` from `claudesurebet` baseline 2026-08-20.*
