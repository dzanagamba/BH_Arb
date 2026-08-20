# Scraper Logic Reference

For each bookmaker, this file explains:
- What API endpoint(s) the scraper calls
- What auth/session/cookies it needs
- How it extracts matches, teams, and odds
- How it handles pagination

All scrapers accept a `live: bool = False` flag on `scrape()` / `fetch_and_parse()`.
Prematch and live feeds use DIFFERENT market ID spaces (see `MARKET_MAPPING.md`
for the verified live matrix). The server runs the two modes independently:
separate status objects, separate caches (`cache/last_scan.json` prematch,
`cache/last_live_scan.json` live), and mode-aware endpoints
(`/api/scan?mode=live`, `/api/results?mode=live`, ...). The dashboard has a
Future Matches / Live Matches toggle.

## 1. MDShop (`scrapers/mdshop.py`)

**Type:** Pure httpx (no browser)

**API Endpoint:**
```
GET https://mdoffer.mdshop.ba/api/offer/getwebevents
    ?sportId={1-15}
    &isLive=false
    &dateFrom={ISO datetime}
    &dateTo={+14 days}
    &eventMappingTypes=1,2,3,4,5
```

**Headers needed:**
```json
{
  "Accept": "application/utf8+json, ...",
  "Accept-Encoding": "gzip, deflate",
  "language": "sr-Latn",
  "officeid": "1678",
  "referer": "https://www.mdshop.ba/"
}
```

**Returns:** `{ events: [...] }` — each event has `name` ("Team A - Team B"), `dateTime`, `bets[]`.

**Bet data:** Each bet has `betTypeId` (int), `sbv` (float threshold, lowercase!), `betOutcomes[]` with `name` (label) and `odd` (decimal).

**Bet type mapping (VERIFIED against live catalog, 2026-08):**
- `135` → 1X2 (only accepted when ALL of 1/X/2 are present)
- `152` → Double Chance (needs ≥2 of 1X/12/X2)
- `151` → BTTS (needs GG + NG)
- `137`/`138` → Over/Under (threshold from `sbv`; only 1.5/2.5/3.5 supported)
- `136` → **"Ide dalje" ADVANCE market (2-way, knockout games only) — deliberately EXCLUDED** (never 1X2/DC!)
- `148`/`149` → half-time 1X2s, `140` → HT/FT, `153`/`154`/`166`/`174` → DNB/handicap/combos, `143`/`144`/`161`/`162` → half-total variants — **all excluded**

**Pagination:** None needed — queries 14 days of events in one call. Loops through sport IDs 1-15.

---

## 2. MBet (`scrapers/mbet.py`)

**Type:** Pure httpx (no browser)

**API Endpoint:**
```
GET https://api.mbet.ba/events_cached
    ?live=false
    &offer_plan=true
    &fields=all
    &lang=ba
    &limit=100
    &offset={0, 100, 200, ...}
    &start={ISO datetime}
    &end={+14 days}
    &orderBy=startTimeAsc
```

**Headers:** Standard UA + Accept.

**Returns:** `{ events: [...] }` — each event has `id_sport` ("fb", "bk", "tn"...), `competitors[{name}]`, `utc_scheduled`, `odds{}`.

**Odds format:** Dynamic football keys use the `ofb` sport prefix:
- `ofb:fs:1/X/2` → full-time result (`Konacan ishod`)
- `ofb:dc:1X/12/X2` → full-time double chance
- `ofb:gg:GG/NG` → both teams to score
- `ofb:tg:2+` + `0-1` → O/U 1.5; `3+` + `0-2` → O/U 2.5; `4+` + `0-3` → O/U 3.5
- `ofb:fts` → first team to score; `ofb:ht`/`ofb:sh` → first/second-half result; all excluded
- `ofb:fi` is a baseball first-inning code, not a football fallback

Each odds value is `{ value: float }` or just a float.

**Pagination:** Offset-based. Starts at 0, increments by 100. Stops when response has < 100 events.

**Sport filtering:** Only processes known sport IDs (fb=football, bk=basketball, etc.). Unknown sports skipped.

---

## 3. SportPlus (`scrapers/sportplus.py`)

**Type:** Pure httpx (no browser)

**API Endpoint:**
```
GET https://www.sportplus.ba/api/v1/prematch/offer
```

**Headers:** Standard UA + Accept-Encoding.

**Returns:** `{ matches: [...] }` — each match has `competitors` (string "Team A - Team B"), `matchDate`, `sportName`, `markets[]`.

**Market format:** Each market has `id` (int) and `name` (string), plus `odds[]` with `alias` and `value`.

**Market detection (by name or ID):**
- `NOGOMET` / id `1` → full-time 1X2 + DC from the combined block
- `OBA TIMA DAJU GOL` / id `6` → BTTS
- `ZBROJ GOLOVA 2,5` / id `768` → O/U 2.5
- `RASPON GOLOVA` / id `800/802` → O/U 1.5 (`2+`/`01`), O/U 2.5 (`3+`/`02`), and O/U 3.5 (`4+`/`03`); duplicate O/U 2.5 is consolidated
- First-half, first-goal, advance, handicap, combo, exact-score, corner, card, and other period markets are excluded

**Note:** Response can be double-serialized (string containing JSON). Handle with `json.loads()` if needed.

**Pagination:** None — single API call returns all matches.

---

## 4. Mozzartbet (`scrapers/mozzartbet.py`)

**Type:** Playwright hybrid (browser session + API calls)

**Why Playwright?** Uses Cloudflare + custom `medium: WEB` header that's checked server-side. Pure httpx gets 403 "Pogresan medium".

**Flow:**
1. Open headless Chromium
2. Navigate to `https://www.mozzartbet.ba/sr/kladjenje` (gets Cloudflare cookies + session)
3. Wait 3s for JS to initialize
4. Loop pages 1-35 via `page.request.post()` to the betting API

**API Endpoint (POST):**
```
POST https://www.mozzartbet.ba/betting/matches
Headers:
  Content-Type: application/json
  Accept: application/json, text/plain, */*
  medium: WEB                    ← CRITICAL — without this you get 403
  Referer: https://www.mozzartbet.ba/sr/kladjenje/sport/1?date=all_days

Body:
{
  "date": "all_days",
  "sort": "bycompetition",
  "currentPage": {1..35},
  "pageSize": 15,
  "sportId": 1,
  "competitionIds": [],
  "search": "",
  "matchTypeId": 0
}
```

**Returns:** `{ items: [...], totalPages: N, totalItems: N }`

**Event parsing:** Each item has `home`/`guest` (team names), `leagueName`, `startTime`, and `odds[]` array with `game.id`/`shortName`, `subgame.name`, and `value`.

**Market detection:** Uses the verified game IDs/short names:
- `id=1` / `ki` / `Konacan ishod` → full-time 1X2
- `id=2` / `ds` / `Dupla sansa` → full-time DC
- `id=3` / `ug` / `Ukupno golova` → O/U 1.5/2.5/3.5 from outcome pairs
- `id=130` / `tgg` → BTTS; combo outcome `gg3+` is excluded
- `id=141` combinations and any `dalje`/`prolaz`/`kvalifikacije` game are excluded

**Pagination:** Stops when a page returns < 15 items or API errors.

---

## 5. Admiralbet (`scrapers/admiralbet.py`)

**Type:** Playwright hybrid (browser session + API calls)

**Why Playwright?** Needs Cloudflare Turnstile session + specific `officeid` header that changes per session.

**Flow:**
1. Navigate to `https://www.admiralbet.ba` (gets Cloudflare token)
2. Navigate to `https://www.admiralbet.ba/sport-prematch?sport=Fudbal` (loads the SPA)
3. Fetch the full football catalog in ONE `getwebevents` call (no pagination)

**API Endpoint (GET):**
```
GET https://bihoffer.admiralbet.ba/api/offer/getwebevents
    ?sportId=1
    &isLive=false
    &dateFrom=2026-07-29T17:00:00.000
    &dateTo=2031-07-29T17:00:00.000
    &eventMappingTypes=1,2,3,4,5

Headers:
  Accept: application/utf8+json, ...
  language: bs-Latn             ← CRITICAL
  officeid: 2037                ← CRITICAL (differs from MDShop's 1678!)
  Referer: https://www.admiralbet.ba/sport-prematch?sport=Fudbal
```

**Returns:** `{ events: [...] }` — array of events, each with `name` ("Team A - Team B"), `bets[]`.

**Bet data:** Uses `sBV` (capital BV, unlike MDShop's lowercase `sbv`). Same NSoft betTypeIds, EXCEPT Admiralbet serves 1X2 as `1639` (not `135`).

**Bet type mapping (VERIFIED against live catalog, 2026-08):**
- `1639` (and `135`) → 1X2 (only when ALL of 1/X/2 are present)
- `152` → Double Chance, `151` → BTTS, `137`/`138` → O/U (1.5/2.5/3.5 via `sBV`)
- `136` → **"Ide dalje" ADVANCE market — deliberately EXCLUDED** (was previously misread as Double Chance, polluting cross-market DC arbs with qualification odds on knockout games)
- `148`/`149`/`140`/`153`/`154`/`166`/`174`/`143`/`144`/`161`/`162` → excluded

**Live verification:** The current full-catalog response includes 1X2 (`1639`), DC (`152`), BTTS (`151`), and O/U (`137`) together. Half-time, advance, handicap, combo, and half-total IDs are intentionally not emitted.

**Legacy:** The older paginated endpoint `getEventsStartingSoonFilterSelections?skipN={0,25,...}` is no longer used.

---

## 6. Betole (`scrapers/betole.py`)

**Type:** Direct httpx prematch feed, with legacy Playwright interception fallback

**Status:** Direct prematch parser implemented and live-verified. The feed is
available at `/restapi/offer/ba/sport/S/desk`; its `esMatches[].odds` object uses
numeric Betole pick codes rather than NSoft `betTypeId` objects. The legacy
browser/ExeFeed resolver remains as a fallback for captured reference payloads.

**Flow:**
1. Fetches `/restapi/offer/ba/sport/S/desk` in `from=1500` pages
2. Skips live/blocked events and parses `home`, `away`, `kickOffTime`, and `odds{}`
3. Maps verified pick codes: `1/2/3` = 1X2, `7/8/9` = DC, `272/273` = BTTS, `242/21`, `24/22`, `25/219` = O/U 1.5/2.5/3.5
4. Excludes first-half, handicap, combination, and `IDE DALJE` picks
5. Retains the browser/ExeFeed resolver only for legacy captured payloads

The direct feed paginates with the `from` offset and skips live or blocked
events. Synthetic coverage verifies both direct pick-code mappings and legacy
reference resolution.

---

## 7. EVLBet (`scrapers/evlbet.py`)

**Type:** Pure httpx (no browser)

**API Endpoint:**
```
GET https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat
    ?SportIds=388
    &Limit=100
    &Offset={0, 100, 200, ...}
```

**Headers:** Standard UA + Origin/Referer for `https://evlbet.com`.

**Returns:** `{ Response: [...] }` — each event has `TeamHome`/`TeamAway`, `MatchStartTime`, `LeagueName`, `CategoryName`, and a `BasicOffer.Odds[]` array.

**Markets:** Only 1X2 is parsed (from `BasicOffer`). Stops pagination when a page returns < 100 events.

---

## 8. WWIN (`scrapers/wwin.py`)

**Type:** Playwright hybrid (session for Cloudflare) + REST API via `page.request`

**API Endpoints:**
```
GET /content/sport-livecontent/api/PrematchEvents/events
    ?key=bs&bets={ids}&tfrom={epoch}&tto={epoch}&spid=2
GET /content/sport-livecontent/api/LiveEvents/events?key=bs&bets=&bet=&pbet=
GET /content/sport-livecontent/api/LiveEvents/headerBets?bets={ids}
```

**Market ids (verified live, football sport id = 2):** `95`=1X2 (`1/X/2`), `6`=DC (`1X/12/X2`), `3`=BTTS (`Yes/No`), `11`=O/U with the line in `spec` (`total=2,5`, `Over`/`Under`) — only 1.5/2.5/3.5 supported. DNB (`7`), 3-way handicap (`10`), HT/FT (`4`), 1st-half 1X2 (`2`), advance "Prolaz" (`476`), Asian totals (`443`), correct score (`51`) are excluded.

**Quirk:** the prematch `events` endpoint serves at most TWO bet ids per call — the scraper fetches three groups (`95,6`, `3`, `11`) per day-window and merges by event id. Live mode pairs `LiveEvents/events` with `headerBets` odds.

---

## 9. Premier Kladionica (`scrapers/premier_kladionica.py`)

**Type:** Pure httpx — `PrSync` JSON-RPC

**Endpoint:**
```
POST https://svc-test.premier-kladionica.com/PrSync/PrSync.ashx
Body: [[[4,1,0],7,{"dogadjajIDs":"","clientVer":0}]]   (full sync)
      [[[4,1,0],7,{"dogadjajIDs":"<event ids>","clientVer":<ver>}]]  (odds delta)
```

**Response sections (positional, empty ones omitted):**
`execRes, tipIgre, sport, grupaDog, setDog, dog, grupaTip, setTip, setTipVar, setTipTip, not used, dogVar, dogTipK, pravila, dogLiveScore`

Odds are `dogTipK` rows: `[dogID, grupaTipID, setTipID, setTipVarID, setTipTipID, koef, naPon, ...]`. Market names come from `setTip`, lines (e.g. `(-2,5+)`) from `setTipVar`, outcome codes from `setTipTip` (keyed by `(sport, setTipID, tipID)`).

**Market mapping (football, grupaTipID=2):** `UTAKMICA` = 1X2 + DC; `OBA DAJU GOL` = BTTS (`da/ne`, `o-da/o-ne`); `ZBROJ GOLOVA` = O/U with lines `(-1,5+)`/`(-2,5+)`/`(-3,5+)`. `LIVE -`-prefixed templates are used in live mode. Handicaps, periods, HT/FT, "NAČIN PROLAZA" (advance), corners, cards, scorers, and combos are excluded.

---

## Shared Helper Functions

### `scrapers/common.py` (shared across direct-API scrapers)

- `parse_dt(raw)` — unified datetime parsing to naive UTC (ISO strings / epoch timestamps)
- `normalize_outcome(label, market_type)` — unified outcome label normalization (1/X/2, Over/Under, GG/NG, Double Chance) recognizing English + Bosnian aliases
- `parse_teams_from_name(name)` — split "Team A - Team B" / "Team A vs Team B"

### `scrapers/mozzartbet.py` (imported by betole)

- `_extract_teams(event)` — tries 12+ key names for home/away teams, falls back to parsing `name` field with " - " separator
- `_extract_league(event)` — tries 8 key names for league/competition/tournament
- `_extract_kickoff(event)` — tries 10 key names for start time, supports multiple datetime formats
- `_parse_markets(event)` — parses the `odds[]` array into `Market` objects with type detection + outcome normalization
- `_find_events_in_payload(data)` — recursively searches nested dicts/lists for objects that have home+away teams (used for interception-based scrapers)
