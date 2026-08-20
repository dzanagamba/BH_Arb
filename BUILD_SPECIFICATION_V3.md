# Surebet Platform — Complete Build Specification V3

> **Purpose**: Self-contained reference for building/maintaining a surebet detection platform for 6 Bosnian bookmakers. Covers all scraper architectures, API endpoints, critical headers, known bugs, and integration details.

---

## 1. Project Overview

Scrapes football odds from **6 Bosnian bookmakers**, normalizes team names across them, and detects arbitrage (surebet) opportunities where combined odds guarantee profit.

**Target**: Bosnia & Herzegovina  
**Language**: Bosnian/Serbian/Croatian (team names, market labels)  
**Markets**: 1X2, Double Chance, O/U 1.5/2.5/3.5, BTTS

---

## 2. The 9 Bookmakers & Current Match Yield

| # | Bookmaker | ID | Approach | Match Yield | Speed |
|---|-----------|----|----------|-------------|-------|
| 1 | **MDShop** | `mdshop` | httpx (direct API) | ~1,150 | ~2s |
| 2 | **MBet** | `mbet` | httpx (paginated API) | ~1,060 | ~8s |
| 3 | **SportPlus** | `sportplus` | httpx (direct API) | ~1,030 | ~2s |
| 4 | **Mozzartbet** | `mozzartbet` | Playwright hybrid | ~54 (today) | ~15s |
| 5 | **Admiralbet** | `admiralbet` | Playwright hybrid | ~1,150 | ~15s |
| 6 | **EVLBet** | `evlbet` | httpx (direct API) | ~1,520 | ~5s |
| 7 | **Betole** | `betole` | httpx prematch feed (disabled) | ~610 | ~5s |
| 8 | **Premier Kladionica** | `premier_kladionica` | httpx PrSync RPC | ~1,310 | ~20s |
| 9 | **WWIN** | `wwin` | Playwright hybrid REST | ~1,600 | ~15s |

**Total**: ~9,500 matches from 8 working scrapers in ~60s (Betole disabled by default).

---

## 3. Three Scraper Types

### Type A: Pure httpx (no browser)

Used for bookmakers whose APIs don't require Cloudflare-bypassed sessions.

**Files**: `scrapers/mdshop.py`, `scrapers/mbet.py`, `scrapers/sportplus.py`, `scrapers/evlbet.py`

**Pattern**:
```python
async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
    resp = await client.get(url, headers={...})
    data = resp.json()
    # Parse data into Match objects
```

**Pros**: Fast (~2-8s), low memory, no browser overhead.  
**Cons**: Won't work if API requires browser-specific cookies/headers.  
**Note**: `verify=False` is now configurable via the `VERIFY_SSL` setting (default off).

### Type B: Playwright Hybrid (session + API calls)

Uses Playwright to open a headless browser **only** to establish a Cloudflare-bypassed session, then makes API calls through `page.request` (Playwright's APIRequestContext which inherits the browser's cookies/headers).

**Files**: `scrapers/mozzartbet.py`, `scrapers/admiralbet.py`

**Pattern**:
```python
async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto("https://...", wait_until="domcontentloaded")
    # Now page.request has the browser's session
    resp = await page.request.get("https://api...", headers={...})
    data = await resp.json()
    await browser.close()
```

**Pros**: Bypasses Cloudflare, uses real browser session.  
**Cons**: Slower (~15s per bookmaker), higher memory due to Chromium.

### Type C: Playwright Interception (legacy)

Opens a browser, navigates to the SPA, intercepts all JSON responses the page naturally makes, and parses them. Betole now uses its direct prematch feed first; this remains a legacy fallback for captured ExeFeed payloads.

**File**: `scrapers/betole.py`, `scrapers/base.py`

---

## 4. Critical API Details Per Bookmaker

### 4.1 MDShop — `scrapers/mdshop.py`

| Item | Value |
|------|-------|
| **Base URL** | `https://mdoffer.mdshop.ba` |
| **Endpoint** | `GET /api/offer/getwebevents? sportId={1-15}&isLive=false& dateFrom={now}&dateTo={+14d}& eventMappingTypes=1,2,3,4,5` |
| **Header `officeid`** | `1678` |
| **Header `language`** | `sr-Latn` |
| **Header `Accept-Encoding`** | `gzip, deflate` (NOT brotli) |
| **Bet type IDs** | 135=1X2, 152=DC, 151=BTTS, 137/138=O/U (via `sbv`). **136="Ide dalje" advance market — excluded** (knockout games only). Half-time 1X2s (148/149), HT/FT (140), DNB/handicap/combos (153/154/166/174) and half totals (143/144/161/162) all excluded. |
| **Key bug** | Field is `sbv` (lowercase), NOT `sBV`! |
| **Pagination** | None needed — queries 14 days at once |
| **Sport loop** | Iterates sportIds 1-15 (football=1) |

### 4.2 MBet — `scrapers/mbet.py`

| Item | Value |
|------|-------|
| **Base URL** | `https://api.mbet.ba` |
| **Endpoint** | `GET /events_cached? live=false&offer_plan=true&fields=all& lang=ba&limit=100&offset={0,100,200...}& start={now}&end={+14d}&orderBy=startTimeAsc` |
| **Sport IDs** | `fb`=football, `bk`=basketball, `tn`=tennis, etc. |
| **Odds format** | Football keys use `ofb`: `ofb:fs:1/X/2` (full-time 1X2), `ofb:dc:1X/12/X2` (DC), `ofb:gg:GG/NG` (BTTS), and `ofb:tg:2+/0-1`, `3+/0-2`, `4+/0-3` (O/U 1.5/2.5/3.5). `fts`, `ht`, `sh`, `dnb`, `hc`, and combo keys are excluded. |
| **Pagination** | Offset-based. Starts 0, +=100. Stops when < 100 items returned. |

### 4.3 SportPlus — `scrapers/sportplus.py`

| Item | Value |
|------|-------|
| **Base URL** | `https://www.sportplus.ba` |
| **Endpoint** | `GET /api/v1/prematch/offer` |
| **Response format** | `{ matches: [...] }` — can be double-serialized (JSON string inside JSON) |
| **Market detection** | id=1 (`NOGOMET`) = full-time 1X2 + DC; id=768 = O/U 2.5; id=6 = BTTS; id=800/802 (`RASPON GOLOVA`) = O/U 1.5/2.5/3.5 |
| **Goal range aliases** | `2+`/`01` = O/U 1.5, `3+`/`02` = O/U 2.5, `4+`/`03` = O/U 3.5; duplicate O/U 2.5 is consolidated |
| **Pagination** | None — single call |

### 4.4 Mozzartbet — `scrapers/mozzartbet.py`

| Item | Value |
|------|-------|
| **Base URL** | `https://www.mozzartbet.ba` |
| **Endpoint** | `POST /betting/matches` |
| **Body** | `{ date:"all_days", sort:"bycompetition", currentPage:N, pageSize:15, sportId:1 }` |
| **CRITICAL header** | `medium: WEB` — without this you get 403 "Pogresan medium" |
| **Other headers** | `Content-Type: application/json`, `Referer: /sr/kladjenje/sport/1?date=all_days` |
| **Why Playwright?** | Cloudflare + custom `medium` header checked server-side. Pure httpx gets 403. |
| **Pagination** | Pages 1-35 via `currentPage`. Stops when < 15 items returned. |
| **Market detection** | Verified IDs: 1/`ki` = full-time 1X2, 2/`ds` = full-time DC, 3/`ug` = O/U 1.5/2.5/3.5, 130/`tgg` = BTTS. id=141 combinations and qualification/advance game names are excluded. |
| **Shared helpers** | `_extract_teams`, `_extract_league`, `_extract_kickoff`, `_parse_markets`, `_find_events_in_payload` — also used by Betole |

### 4.5 Admiralbet — `scrapers/admiralbet.py`

| Item | Value |
|------|-------|
| **Base URL** | `https://www.admiralbet.ba` |
| **API domain** | `https://bihoffer.admiralbet.ba` |
| **Endpoint** | `GET /api/offer/getwebevents? sportId=1&isLive=false&dateFrom=...&dateTo=...& eventMappingTypes=1,2,3,4,5` (single call, full catalog — NOT paginated) |
| **Header `officeid`** | `2037` (DIFFERENT from MDShop's `1678`!) |
| **Header `language`** | `bs-Latn` (DIFFERENT from MDShop's `sr-Latn`!) |
| **Bet type IDs** | 1639=1X2 (NOT 135!), 152=DC, 151=BTTS, 137/138=O/U (via `sBV`). **136="Ide dalje" advance market — excluded** (was wrongly mapped to DC before 2026-08 audit; polluted cross-market DC arbs on knockout games). |
| **Live verification** | `1639` 1X2, `152` DC, `151` BTTS, and `137` O/U were all present in the live full-catalog response. |
| **Why Playwright?** | Cloudflare Turnstile + session cookies from page load. |
| **Legacy** | The older `getEventsStartingSoonFilterSelections?skipN={0,25,...}` paginated endpoint is no longer used. |

### 4.6 Betole — `scrapers/betole.py`

**Status**: Direct prematch parser implemented and live-verified. The feed is
available at `/restapi/offer/ba/sport/S/desk`; its `esMatches[].odds` object uses
numeric Betole pick codes rather than NSoft `betTypeId` objects. The legacy
browser/ExeFeed resolver remains as a fallback for captured reference payloads.

**Payload shape**: Direct events expose `home`, `away`, `kickOffTime`, and
`odds{pickCode: odd}`. Verified mappings are `1/2/3`=1X2, `7/8/9`=DC,
`272/273`=BTTS, `242/21`, `24/22`, `25/219`=O/U 1.5/2.5/3.5. First-half,
combination, handicap, and `IDE DALJE` picks are excluded. Legacy `betPages[]`
reference resolution remains covered by synthetic tests.

---

## 5. Key Bugs Fixed

### `sbv` vs `sBV` casing
- MDShop returns `sbv` (all lowercase) for Over/Under thresholds  
- Admiralbet returns `sBV` (capital BV)  
- **Fix**: Check both: `bet.get("sbv") or bet.get("sBV")`

### Brotli compression crash (MDShop)
- httpx brotli decoder crashes on MDShop responses  
- **Fix**: Explicit `Accept-Encoding: gzip, deflate` header (omit brotli)

### `medium: WEB` header (Mozzartbet)
- Server checks a custom `medium` header set by the SPA's JavaScript  
- Pure httpx calls get 403 "Pogresan medium"  
- **Fix**: Add `"medium": "WEB"` header to all POST requests

### `officeid` differs per bookmaker
- MDShop uses `officeid: 1678`  
- Admiralbet uses `officeid: 2037`  
- **Fix**: Each scraper must use its correct `officeid`

---

## 6. Server & Frontend

### Server (`server/app.py` + `server/api.py`)

- FastAPI with CORS enabled
- All 9 scrapers registered in `SCRAPERS` dict
- `GET /api/health` — basic health check
- `GET /api/config` — returns bookmaker config (name, enabled, color)
- `POST /api/config/toggle/{id}` — enable/disable a bookmaker at runtime
- `POST /api/scan` — triggers background scan
- `GET /api/status` — poll scan progress
- `GET /api/results` — cached surebets/matches
- `GET /api/debug/report` — match grouping debug info
- `POST /api/recalculate` — recalculate stakes for an investment amount

**Enabled state**: Stored in-memory in `_bookmaker_enabled` dict. Respects runtime toggles. Scan cycle checks `_is_enabled(id)` not `config["enabled"]`.

### Frontend (`frontend/index.html`, `css/style.css`, `js/app.js`)

- Dark glassmorphism dashboard
- Bookmaker toggle chips in filter bar (click to enable/disable via API)
- Scan button triggers background scan, polls status every 2s
- Surebet cards show profit %, market, teams, optimal stakes per bookmaker
- Investment calculator per card (recalculates stakes in real-time)
- Filters: market type dropdown, min profit %, bookmaker toggles
- Sound alert for high-profit (>3%) surebets

---

## 7. Data Flow

```
User clicks "Scan Now" (Future Matches or Live Matches tab)
  → POST /api/scan?mode=prematch|live (BackgroundTask)
    → asyncio.gather(
        MDShop.fetch_and_parse(live),    # httpx ~2s
        MBet.fetch_and_parse(live),      # httpx ~8s
        SportPlus.fetch_and_parse(live), # httpx ~2s
        Mozzartbet.fetch_and_parse(live),# Playwright ~15s (date:"live" + in-play filter)
        Admiralbet.fetch_and_parse(live),# Playwright ~15s
        Betole.fetch_and_parse(live),    # httpx prematch feed, live-flagged events (disabled by default)
        EVLBet.fetch_and_parse(live),    # prematch only — live payload has no odds
        PremierKladionica.fetch_and_parse(live),  # httpx PrSync RPC (live: LIVE - templates)
        WWIN.fetch_and_parse(live),      # Playwright REST (live: LiveEvents/events + headerBets)
      )
    → all Match objects (is_live flag) → MatchMatcher.group_matches()
      → League gate → Date gate → Team fuzzy matching (rapidfuzz 80%)
    → MatchGroup[] → ArbitrageEngine.find_surebets(allow_past_kickoffs=live)
      → For each market type: find best odds per outcome across bookmakers
      → If sum of implied probabilities < 1.0 → surebet!
    → Cache per mode (last_scan.json / last_live_scan.json) → Frontend polls and displays
```

---

## 8. Matching Logic

### League Gate (HARD requirement)
Two matches MUST have the same normalized league to be compared. Prevents "Borac Banja Luka" (BiH league) from matching with "Borac Čačak" (Serbian league).

### Date Gate (HARD requirement)
Kickoff dates must match (YYYY-MM-DD). Prevents the same teams playing on different matchdays.

### Team Matching (fuzzy, threshold 80%)
Uses rapidfuzz `token_sort_ratio` on cleaned names. Cleaning steps:
1. Lowercase + remove diacritics (ž→z, č→c, š→s, đ→d)
2. Strip common prefixes (FK, FC, NK, etc.)
3. Strip "(N)" neutral venue markers
4. Check known mappings file
5. If ratio ≥ 85%, auto-lock mapping for future runs

### Confidence Score
`0.4×home_similarity + 0.4×away_similarity + 0.2×time_proximity`

Minimum 70% per individual team AND overall 80%.

---

## 9. Key Files

| File | Purpose |
|------|---------|
| `config/settings.py` | Bookmaker URLs, colors, enabled state defaults, matching thresholds |
| `models/schemas.py` | Pydantic models: Match, Market, OddsValue, Surebet |
| `scrapers/common.py` | Shared helpers (datetime parsing, outcome normalization, team parsing) |
| `scrapers/mdshop.py` | Type A: httpx direct API |
| `scrapers/mbet.py` | Type A: httpx paginated API |
| `scrapers/sportplus.py` | Type A: httpx direct API |
| `scrapers/evlbet.py` | Type A: httpx paginated API |
| `scrapers/mozzartbet.py` | Type B: Playwright hybrid + shared helpers |
| `scrapers/admiralbet.py` | Type B: Playwright hybrid |
| `scrapers/betole.py` | Type C: Playwright interception (broken) |
| `server/api.py` | FastAPI routes + scan orchestrator |
| `frontend/index.html` | Dashboard HTML |
| `frontend/js/app.js` | Dashboard JS (polling, rendering, toggles) |
| `frontend/css/style.css` | Dark glassmorphism theme |
| `ScraperLogic.md` | AI-readable scraper details |

---

## 10. Dependencies

```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
playwright>=1.40.0
pydantic>=2.5.0
rapidfuzz>=3.5.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

Post-install: `playwright install chromium`

---

## 11. Running

```bash
cd /path/to/project
source venv/Scripts/activate   # Windows
python main.py                  # Starts on http://localhost:8000
```
