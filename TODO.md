# Surebet Scanner — Project TODO & Roadmap

## ✅ Completed — Last Roadmap Sweep

### P0 — Bugs

- [x] **Kickoff times display in wrong timezone** — Added `parseKickoff()` in `frontend/js/app.js` that appends `Z` to naive-UTC kickoff strings; cards and copy-details now show correct local kickoff times.
- [x] **Bookmaker toggles reset on restart** — Toggles persist to `cache/bookmaker_state.json`, restored on startup via `_load_bookmaker_state()`.
- [x] **Progress bar counts disabled bookmakers** — `updateScanProgress` now uses the count of *enabled* bookmakers as denominator.
- [x] **Alert sound fires on every rescan** — Surebet fingerprints (`surebetSignature()`) tracked in `knownSurebetSignatures`; the chime only plays for *new* high-profit surebets.

### P1 — Quality / consistency

- [x] **Unify Playwright stealth launches** — Shared `launch_browser()` in `scrapers/base.py` (anti-bot flags, bs-BA locale, Europe/Sarajevo tz, custom UA); used by BaseScraper, Mozzartbet, and Admiralbet.
- [x] **Pipeline integration test** — `tests/test_pipeline.py` feeds realistic 3-bookmaker fixtures through normalize → match → arbitrage and asserts grouping, kickoff-gate, and surebet output.
- [x] **Refine `WOMEN_PATTERN`** — `\bW\b` no longer matches when followed by a letter (no more "W Connection" false positives).
- [x] **Document env vars** — `.env.example` now covers `VERIFY_SSL`, `API_KEY`, `SCAN_RATE_LIMIT`.

### P2 — Features

- [x] **Fix Betole scraper** — Direct prematch `/restapi/offer/ba/sport/S/desk` parser maps verified numeric pick codes (1/2/3=1X2, 7/8/9=DC, 272/273=BTTS, O/U 1.5/2.5/3.5) and skips live/blocked/period/combo/`IDE DALJE` offers. Legacy `_resolve_exefeed_events()` remains covered by synthetic tests.
- [x] **Scan History & Persistence** — Per-scan entries (time, matches, groups, surebets, per-bookie counts, errors) persisted to `cache/scan_history.json` (last 50); `GET /api/history` + dashboard history panel.
- [x] **Auth / Rate Limiting** — Optional `API_KEY` (X-API-Key header) on scan/toggle/recalculate/verify/history; sliding-window scan rate limit per client IP (`SCAN_RATE_LIMIT`, default 3/min).
- [x] **Direct Bookmaker Match Links** — `Surebet.match_urls` (bookmaker → match URL) collected from groups with `MATCH_URL_TEMPLATES` fallback; stake rows render clickable bookmaker links.
- [x] **Odds Drift / Live Verification** — `POST /api/verify` re-scrapes only the surebet's bookmakers, re-groups the match, and returns cached vs current margin/profit, per-outcome drift, and `still_profitable`; "Verify Odds" button on every card.
- [x] **Matcher performance** — League-bucket index (`groups_by_league`) cuts candidate groups per match from O(all) to O(same-league + generic); verified by the existing matcher/pipeline tests.

---

## 🔴 Critical Bugs & Stability

- [x] **Bookmaker filter toggle out of sync** — `toggleBookmakerAPI()` now updates the `activeBookmakers` Set and calls `applyFilters()`; the initial set includes `mbet`, `sportplus`, and `evlbet`.
- [x] **Dead config values** — `KICKOFF_WINDOW_MINUTES` (120), `FUZZY_MATCH_THRESHOLD` (80), and `TEAM_MATCH_MIN_PERCENT` (70) are now used by the matcher (`engine/matcher.py`).
- [x] **Inconsistent kickoff timezone handling** — SportPlus now normalizes aware datetimes to naive UTC like all other scrapers.
- [x] **No cache restore on startup** — Added `_load_cache()` in `server/api.py`, wired into the FastAPI startup event.
- [x] **`total_margin` bug (found via tests)** — `Surebet.total_margin` used the last evaluated permutation instead of the optimal one (`best_implied`). Fixed in `engine/arbitrage.py`.

---

## 🟠 Engine, Matching & Math

- [x] **Missing date gate** — Enforced timezone-safe date/time comparison (<120 min kickoff diff).
- [x] **Home/Away swap detection & odds flipping** — Normalizes flipped team order and auto-swaps outcome labels (`1` ↔ `2`, `1X` ↔ `X2`).
- [x] **Non-greedy group assignment** — Matcher evaluates all candidate groups and assigns to the highest confidence group.
- [x] **Filter expired matches** — Automatically rejects matches whose kickoff time has already passed.
- [x] **League mappings expansion** — Expanded coverage for Hungarian, Scottish, Czech 2, Russian, Polish, Swiss, Irish, Romanian, Bulgarian, Chinese, USL, and Cup leagues.
- [x] **Centralized threshold config** — `KICKOFF_WINDOW_MINUTES`, `FUZZY_MATCH_THRESHOLD`, `TEAM_MATCH_MIN_PERCENT`, `EXPIRY_BUFFER_MINUTES`, `MAX_SUREBET_PROFIT_PERCENT` all live in `config/settings.py` and are consumed by the engine.
- [x] **Duplicate `_parse_markets` call** — Removed in `scrapers/sportplus.py`.
- [x] **Cross-market Double Chance Arbitrage** — Engine now detects surebets combining 1X2 with Double Chance (partitions `(1, X2)`, `(2, 1X)`, `(X, 12)`), enforcing distinct bookmakers per leg; filter added to the dashboard.
- [x] **Odds Drift / Live Verification** — `POST /api/verify` re-scrapes involved bookmakers and reports drift + `still_profitable`; Verify Odds button on cards.

---

## 🟡 Scraper Performance, Resilience & Refactor

- [x] **7 Supported Bookmakers** — Mozzartbet, MDShop, Admiralbet, MBet, SportPlus, EVLBet, and Betole (disabled).
- [x] **Admiralbet Full Catalog** — Upgraded Admiralbet to `getwebevents` API endpoint (600+ matches scraped).
- [x] **MDShop & Scrapers Soccer Filter** — Filtered direct HTTP scrapers strictly to soccer (`sportId=1` / `388`).
- [x] **Headless Config Respect** — Mozzartbet & Admiralbet respect `HEADLESS` setting from `config/settings.py`.
- [x] **HTTP Retries & Backoff** — Added `fetch_with_retry()` with exponential backoff to all direct-API scrapers.
- [x] **Deprecated `datetime.utcnow()`** — Replaced with `datetime.now(timezone.utc)` across all scrapers.
- [x] **Dynamic Mozzartbet Pagination** — Uses `matchCount` and `pageSize=50` instead of a hardcoded cap.
- [x] **Deduplicated scraper helpers** — `parse_dt`, `normalize_outcome`, `parse_teams_from_name` centralized in `scrapers/common.py`.
- [x] **`verify=False` configurable** — All 4 httpx clients now use the `VERIFY_SSL` setting (default off, enable via `.env`).
- [x] **`scrapers/__init__.py`** — Exports `EvlbetScraper` and lists all scrapers in `__all__`.
- [x] **Football-only filters** — MBet and SportPlus now skip all non-football sports (were leaking basketball/tennis/esports into the pipeline).
- [x] **Event-ID dedup** — All scrapers dedup by match/event ID (with team-name fallback) so the same teams meeting twice in the 14-day window are no longer dropped.
- [x] **Timezone-offset parsing** — `parse_dt` converts explicit offsets (`Z`, `+02:00`) to UTC instead of silently truncating them; MBet kickoffs now use the shared helper.
- [x] **"Dom"/"Gost" outcome labels** — NSoft home/away aliases recognized in `normalize_outcome`.
- [x] **Special-category gate** — `detect_special_category` (U21/Women/Reserve/Esports) now populates `category_tags`; the matcher hard-rejects groupings with conflicting categories.
- [x] **UTC expiry fix** — `_is_expired` compares naive-UTC kickoffs against UTC time, not local time (matches expired ~2h early).
- [x] **Country enrichment** — SportPlus now populates `Match.country` from `countryName` (no gate — country fields are unreliable across bookmakers).
- [x] **Fix Betole scraper** — ExeFeed resolver (`betPages[]` → `betMap{}`) + NSoft bets parsing in `scrapers/betole.py`; synthetic tests pass (live payload verification pending).
- [x] **Bet type mapping audit (all bookmakers)** — Verified every bookmaker's market structure against LIVE catalogs (2026-08). Fixed the "Ide dalje" bug: NSoft betTypeId 136 (advance/qualification market on knockout games) was mapped to Double Chance on Admiralbet, polluting 1X2/DC pools with qualification odds. Added strict label-set validation (1X2 requires all of 1/X/2; DC ≥2 of 1X/12/X2; BTTS both; O/U both), advance-name guards (SportPlus "PROLAZ/DALJE", Mozzartbet "dalje/prolaz"), MBet `fs`-only full-time result handling, SportPlus aggregation of split goal-range blocks, and Betole numeric pick-code mapping. Live-verified: 0 NSoft leaks, 0 incomplete 1X2 markets, and complete supported-market shapes across all reachable feeds; 22 market-mapping regression tests.
- [x] **Live matches mode** — Every scraper now accepts `live=True` and fetches its in-play feed with verified live market mappings (NSoft live IDs 6/18/42/995/22/28, MBet `lfb:*`, SportPlus name-based live markets, Mozzartbet `date:"live"` with in-play filter, Betole live events from the desk feed; EVLBet skipped — its live payload carries no odds). The arbitrage engine keeps past-kickoff groups in live mode via `allow_past_kickoffs`. The server runs separate `prematch`/`live` status objects and caches (`last_scan.json` / `last_live_scan.json`), and every endpoint (`/api/scan`, `/status`, `/results`, `/verify`, `/recalculate`, `/debug/*`) is mode-aware. The dashboard has a **Future Matches / Live Matches** toggle with live badges and mode-aware history. Live-verified end-to-end: 544 in-play matches across books, 11 cross-book groups, a real live O/U arb detected; 13 new live-mode regression tests.
- [x] **Add Premier Kladionica and WWIN** — Both platforms reverse-engineered from live payloads and verified before implementation. WWIN (`sport-livecontent` API; Playwright session for Cloudflare): idBt 95=1X2, 6=DC, 3=BTTS, 11=O/U (line in `spec`); prematch `events` endpoint serves ≤2 bet ids per call so markets are fetched in three groups and merged. Premier Kladionica (PrSync JSON-RPC): `dogTipK` odds with `setTip`/`setTipVar`/`setTipTip` market decoding; `UTAKMICA`=1X2+DC, `OBA DAJU GOL`=BTTS, `ZBROJ GOLOVA`=O/U (lines from setTipVar); `LIVE -`-prefixed templates used in live mode; advance/handicap/period/corners/cards markets excluded. E2E verified: 8,870 matches across 9 books, 1,107 correct cross-book groups (e.g. Bolton-Preston grouped across 5 bookmakers), 0 malformed 1X2 markets; 8 new regression tests.

---

## 🔵 Server, Concurrency & API

- [x] **ASGI Application Error Fix** — Resolved Starlette CORS middleware conflict (`allow_origins=["*"]` + `allow_credentials=False`).
- [x] **Windows Event Loop Policy** — Configured `WindowsProactorEventLoopPolicy()` in `server/app.py`.
- [x] **Scan Deadlock Safety** — Wrapped `run_scan()` in `try...finally` to reset `scan_status.is_scanning`.
- [x] **Concurrent Request Lock** — Protected `/api/scan` with `asyncio.Lock()`.
- [x] **Load cache on startup** — `_load_cache()` restores `cached_surebets`, `cached_matches`, and `last_scan_time` from `cache/last_scan.json`.
- [x] **Scan Status Multi-Bookmaker Progress** — Added `bookmaker_progress` map (scraping/done/error/skipped per bookmaker) to `ScanStatus`; frontend renders per-bookie badges.
- [x] **Health Monitoring Endpoint** — Added `GET /api/health`.
- [x] **Scan History & Persistence** — `cache/scan_history.json` (last 50 scans) + `GET /api/history` + dashboard panel.
- [x] **Auth / Rate Limiting** — Optional `API_KEY` (X-API-Key) + per-IP scan rate limit (`SCAN_RATE_LIMIT`).

---

## 🟣 Frontend UX & Dashboard

- [x] **EVLBet & Bookmaker Brand Colors** — Integrated brand color badges in dashboard.
- [x] **Search & Filter Bar** — Search by team name or league.
- [x] **Sorting Controls** — Sort by profit %, kickoff time, or league name.
- [x] **Stake Rounding Toggle** — Round stakes to exact / nearest 1 KM / nearest 5 KM (persisted in `localStorage`).
- [x] **Auto-Rescan Toggle** — Background rescan every 2/5/10 minutes with live countdown display.
- [x] **Audio Alert Fixes & Mute Toggle** — Single reused `AudioContext` (no leak), sound only on fresh scan results (not page load), mute button persisted.
- [x] **Copy Bet Details Button** — Clipboard copy of teams, market, profit, and stakes per bookmaker.
- [x] **Clean up dead code** — Removed unused `toggleBookmaker()`, `formatOdds()`, `getBookmakerColor()`; fixed empty-state text/badges to include EVLBet.
- [x] **Direct Bookmaker Match Links** — `Surebet.match_urls` + clickable stake-row links with `MATCH_URL_TEMPLATES` fallback.

---

## 🟢 Quality, Security & DevOps

- [x] **Automated Test Suite** — Added `pytest` tests for normalizer, matcher (gates + swap), arbitrage math (incl. cross-market DC), scraper helpers, ExeFeed resolver, and the full pipeline (`tests/`). `38 passed`.
- [x] **Dependency Hygiene** — Pinned exact versions in `requirements.txt`; removed unused `aiofiles`; added `requirements-dev.txt` (ruff, mypy).
- [x] **Linter / Typechecker** — Added `pyproject.toml` with ruff + mypy config; `ruff check .` clean, `mypy .` clean.
- [x] **Complete `models/__init__.py`** — Exports all 8 schemas.
- [x] **Update stale docs** — README, `BUILD_SPECIFICATION_V3.md`, and `ScraperLogic.md` now reflect 7 bookmakers, the `getwebevents` Admiralbet endpoint, shared `scrapers/common.py`, and new config/settings.
