# Adapter inventory — every bookmaker / price source

Question: what are all the adapters, how does each one fetch and parse, and where
is it covered and fragile?

Scope: `scrapers/` (all 10 book adapters plus shared plumbing), the dispatch table
in `server/api.py`, the per-book registry in `config/`, and `engine/market_registry.py`.
Checked against the committed tree on 2026-11-07. No network calls were made;
transport facts come from code plus the `endpoint` fields recorded in
`tests/fixtures/markets/*.json`.

## 1. Where adapters live

| Location | Role |
|---|---|
| `scrapers/<book>.py` | the 10 book adapters |
| `scrapers/base.py` | stealth Playwright launcher, `goto`/`settle`, `fetch_pages`, `fetch_with_retry` |
| `scrapers/common.py` | NSoft bet parsing, datetime/label normalisation, deep-link building |
| `server/api.py:1021-1031` (`SCRAPERS`) | the only production dispatch table |
| `config/bookmaker_markets.json` | per-book/mode market IDs, labels, `min_legs`, `line`, `settlement` |
| `config/bookmaker_deeplinks.json` | per-book deep-link declaration/templates |
| `config/settings.py:10` (`BOOKMAKERS`) | enable flags, names, base URLs |
| `config/settings.py:217` (`PRICE_SOURCES`) | mdshop + admiralbet share `nsoft` |
| `engine/market_registry.py:327` (`registered_spec`) | shared per-book ID resolver |

No adapter lives outside `scrapers/`. `scripts/probe_feeds.py` and
`scripts/capture_market_fixtures.py` call the real scrapers but add no transport.
`engine/live_feed.py` is an unwired push-feed state machine — there are **no
websocket adapters** (module docstring, `engine/live_feed.py:1-8`;
`server/api.py:253` lists only three Playwright books).

## 2. Adapters

### 2.1 Mozzartbet — `scrapers/mozzartbet.py:355` `MozzartbetScraper`

- Transport: Playwright hybrid. Launches the stealth browser, opens the page,
  intercepts `betting/matches` responses (`:373-384`), then paginates with
  `page.request.post` (`:407-418`). Network JSON only, no DOM parsing.
- Endpoints: `GET https://www.mozzartbet.ba/sr/kladjenje` (session),
  `POST https://www.mozzartbet.ba/betting/matches` with body
  `{date, sort, pageSize, sportId, competitionIds, search, matchTypeId, currentPage}`.
- Pagination: 0-based `currentPage`, `pageSize=15` (`:395`), first page then
  `fetch_pages(..., batch=4, first_page=1)` (`:434-440`). `totalPages` bounds
  `max_pages` (cap 100, `:403-427`). One sport only (`sportId: 1`, football).
- Retry/timeout: no retry on either call; failed page returns `None` and the
  batched walk stops (`:429-431`). Navigation timeout 60 s (`:387`); `settle` 3 s.
- Parsing: `odds[]` → `game.id`/`game.shortName` dispatch to 1/2/130/3
  (`:194-258`), line from subgame names (`2+`/`0-2` etc., `:224-230`). Registry
  `lookup_type` + label/`min_legs` gate before a `Market` is emitted.
- Sport/market/settlement: football implied (no `sport=` on `Match`); market IDs
  from `engine.market_registry`; settlement from `bookmaker_markets.json`.
- Deep link: `Match.url` is the generic competition page (`:347`); the declared
  per-event template in `config/bookmaker_deeplinks.json` is applied later by
  `engine/destinations.py`, not here.
- Fixtures/tests: `tests/fixtures/markets/mozzartbet_{prematch,live}.json`;
  `tests/test_market_fixtures.py`, `test_market_mapping.py`,
  `test_market_registry_wiring.py`, `test_extra_football_lines.py`.
- Fragility: `except Exception: pass` on response capture (`:381`); broad
  `except` on page fetch (`:429`); 12 alternate team-name keys (`:48-55`) and 11
  kickoff keys (`:94-95`) are shape-drift defence; keyword exclusion
  `"dalje"/"prolaz"/"kvalifikacije"` (`:179`); hard-coded `page_size=15` (`:395`).

### 2.2 MDShop — `scrapers/mdshop.py:70` `MDShopScraper`

- Transport: plain HTTP, `httpx.AsyncClient` (30 s, `VERIFY_SSL`) + shared
  `fetch_with_retry`.
- Endpoint: `GET https://mdoffer.mdshop.ba/api/offer/getwebevents?sportId=&isLive=&dateFrom=&dateTo=&eventMappingTypes=1..5`.
- Pagination: none — one request per sport in `SPORT_MAP` (`:35-40`), filtered by
  `sports_wanted` (`:110-118`).
- Retry/timeout: inherits `fetch_with_retry` (3 attempts, 0.5 s × 2ⁿ backoff,
  retries 5xx/timeouts/network) plus httpx 30 s.
- Parsing: NSoft `events[].bets[]` → `parse_nsoft_bets` / `parse_nsoft_live_bets`
  (`:218-236`), which resolve registry specs and enforce label sets/`min_legs`.
- Sport/market/settlement: `sportId` map (`:35-40`); NSoft registry IDs; settlement
  from registry rows, with non-football settlements in `common.py:329-356`.
- Deep link: `build_event_url("mdshop", event_id, ...)` (`:208`), which reduces to
  the declared competition page because `supports_event_id: false`.
- Fixtures/tests: `markets/mdshop_{prematch,live}.json`,
  `e2e_certified/mdshop_prematch.json`; `test_market_fixtures.py`,
  `test_live_mode.py:300-321`, `test_scraper_common.py`, `test_e2e_certified.py`.
- Fragility: broad `except` per event and per sport (`:141`, `:145`); hard-coded
  `officeid: 1678` / `language: sr-Latn` headers (`:42-54`); no event pagination,
  so a truncated feed would be silently short.

### 2.3 Admiralbet — `scrapers/admiralbet.py:96` `AdmiralbetScraper`

- Transport: Playwright hybrid. Session on the homepage and football page
  (`:116-125`), then `page.request.get` for each sport (`:144-153`). Network JSON.
- Endpoint: `GET https://bihoffer.admiralbet.ba/api/offer/getwebevents?…`
  (same NSoft shape, `eventMappingTypes=1,2,3,4,5`).
- Pagination: none; one call per sport in `SPORT_MAP` (`:33-38`).
- Retry/timeout: no retry; one broad `try` wraps **all** sports (`:112-160`), so a
  failure on the first sport abandons the rest. Navigation 60 s; `settle` 3 s + 5 s.
- Parsing: NSoft bets via `_parse_bets` (`:75-93`) → shared parser; basketball
  winner ID 1640 override in `common.py:350-356`.
- Sport/market/settlement: as MDShop; league gets the country via
  `qualify_league` (`:69-72`).
- Deep link: `build_event_url("admiralbet", …)` (`:207`); declared
  `supports_event_id: false`.
- Fixtures/tests: `markets/admiralbet_{prematch,live}.json`,
  `e2e_certified/admiralbet_prematch.json`; `test_market_fixtures.py`,
  `test_market_mapping.py:97`, `test_live_mode.py`, `test_e2e_certified.py`.
- Fragility: broad `except` around the whole sport loop (`:159`); hard-coded
  `officeid: 2037` (`:150`); `settle` 5 s (`:125`).

### 2.4 Betole — `scrapers/betole.py:162` `BetoleScraper`

- Transport: plain HTTP, httpx (30 s) + `fetch_with_retry`.
- Endpoint: `GET https://www.betole.ba/restapi/offer/ba/sport/S/desk` with
  `desktopVersion`, `locale=ba`, `from=<offset>`.
- Pagination: offset in `range(0, 30000, 1500)` (`:176`, `PAGE_SIZE=1500`), stop on
  short page or a page with no new ids (`:214`).
- Retry/timeout: inherits `fetch_with_retry`; a failed page breaks the loop (`:187-191`).
- Parsing: `esMatches[]` with a flat `odds` dict keyed by numeric pick codes; a
  hard-coded mapping table (`:91-99`) resolves each code through `registered_spec`
  (`:36-47`, `:67-88`). `first_half_1x2` is emitted outside the registry
  (`:101-112`) and is declared experimental in `engine/parser_contracts.py:44-46`.
- Sport/market/settlement: football only (no `sport=`); registry IDs; settlement
  defaults to `full_time`.
- Deep link: fixed `OFFER_URL` (`:152`); config declares no event route.
- Fixtures/tests: `markets/betole_prematch.json` only; `tests/test_betole.py`,
  `test_market_mapping.py:252-280`, `test_market_fixtures.py`.
- Fragility: hard-coded 30 000 offset ceiling; hard-coded pick-code table; no live
  fixture; `blocked` and `live` flags required to be booleans (`:132-135`).

### 2.5 EVLBet — `scrapers/evlbet.py:55` `EvlbetScraper` (disabled)

- Transport: plain HTTP, httpx (20 s) + `fetch_with_retry`.
- Endpoint: `GET https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat?SportIds=388&Limit=100&Offset=`.
- Pagination: `fetch_pages(page_size=100, max_pages=20)` → up to 2 000 events.
- Retry/timeout: inherits `fetch_with_retry`; per-page failure returns `None` and
  stops the walk.
- Parsing: `BasicOffer` only, 1X2 (`:127-160`); `BetTypeKey`/`GameId` else
  default `12005`; anything with `HasSbv`/`Sbv` is dropped (`:135-139`).
- Sport/market/settlement: football only; registry ID 12005; `full_time`.
- Deep link: fixed site root (`:177`).
- Fixtures/tests: **no fixture** — declared in
  `test_market_fixtures.py:127-129`; parser covered by `test_market_mapping.py:281-295`
  and `test_market_registry_wiring.py`.
- Fragility: response is "sometimes a dict with `Response`, sometimes a bare list"
  (`:79-84`), a live-observed shape drift; broad `except` (`:85`); live mode
  returns `[]` because the live feed has no odds (`:59-64`); disabled in
  `config/settings.py` since 2026-10-20.

### 2.6 MaxBet — `scrapers/maxbet.py:337` `MaxBetScraper`

- Transport: plain HTTP, httpx (60 s) + `fetch_with_retry`.
- Endpoint: `GET https://sportsbook.maxbet.ba/sportsbook/rest/v2/matches` with
  `sportId`, repeated `ot` (odd type), `ln=cnr`, `status=Live` in live mode.
- Pagination: none — one request per sport returns every match (`:363-393`).
- Retry/timeout: inherits `fetch_with_retry`, but a football failure raises
  `RuntimeError` (`:377-382`) so the book is reported as errored rather than empty;
  other sports warn and continue.
- Parsing: `odds[]` filtered by registry `specs_for(book, mode, odd_type_id)`
  (`:87-100`); `outcomeId` → canonical label with a text cross-check (`:103-113`);
  suspended/side-unavailable outcomes dropped (`:151`).
- Sport/market/settlement: registry for football; `engine/sports.py` `spec_for`
  for basketball/tennis (`:198-313`), settlement from the sport spec.
- Deep link: `build_event_url("maxbet", …)` (`:445`); the only other book with
  `supports_event_id: true` + `route_pattern_verified: true`.
- Fixtures/tests: `markets/maxbet_{prematch,live}.json`; `tests/test_maxbet.py`,
  `test_market_fixtures.py`, `test_parser_contracts.py` (contract case),
  `test_market_registry_wiring.py`.
- Fragility: hard-coded odd-type IDs (`:44`, `:52-57`); text-prefix label checks
  `_LABEL_TEXT` (`:77-80`); football raise couples the whole book to one request;
  no fixture for non-football.

### 2.7 MBet — `scrapers/mbet.py:551` `MBetScraper`

- Transport: plain HTTP, httpx (30 s) + `fetch_with_retry`.
- Endpoint: `GET https://api.mbet.ba/events_cached?live=&offer_plan=true&fields=all&lang=ba&limit=100&offset=&start=&end=&orderBy=startTimeAsc`.
- Pagination: offset = index × 100, `fetch_pages(page_size=100, max_pages=200)`
  (`:580-598`); 14-day window from the scan clock (`:565-573`).
- Retry/timeout: inherits `fetch_with_retry`; failed page returns `None` and stops.
- Parsing: flat key dict (`o<sport>:fs:1` etc.). Football resolver `_resolve_mbet_market`
  (`:85-284`) handles 1X2/DC/BTTS/HT-1X2/AH/OU; live resolver `_resolve_mbet_live_market`
  (`:287-405`); non-football keys in `_resolve_mbet_sport_market` (`:436-548`).
- Sport/market/settlement: `id_sport` prefix map (`:28-47`) → `sports.normalize_sport`;
  registry for football, `sports.spec_for` settlements for basketball/tennis/hockey.
- Deep link: fixed `https://mbet.ba/` (`:733`); config declares no event route.
- Fixtures/tests: `markets/mbet_{prematch,live}.json`,
  `e2e_certified/mbet_prematch.json`; `test_market_fixtures.py`,
  `test_market_mapping.py:218-250`, `test_live_mode.py:129-157`,
  `test_e2e_certified.py`.
- Fragility: broad `except` in fetch and parse loops (`:594`, `:605`); `max_pages=200`
  cap; hard-coded per-sport key prefixes (`:412-433`); duplicate OU code paths
  (simple keys vs `tg:` live keys).

### 2.8 SportPlus — `scrapers/sportplus.py:218` `SportPlusScraper`

- Transport: plain HTTP, httpx (120 s prematch, 60 s live) + `fetch_with_retry`.
- Endpoints: `GET /api/v1/prematch/offer`, `GET /api/v1/live/offer`.
- Pagination: none — one response holds all matches (`:249`) and all sports live
  (`:289-303`).
- Retry/timeout: inherits `fetch_with_retry`; on non-200 returns `[]`.
- Parsing: `matches[]`; football markets identified by **name or id** (`:634-765`),
  live football markets by exact Bosnian names (`:411-491`), non-football by name
  heuristics + `_line_from_text` regex (`:116-205`). Two response shapes handled:
  dict or a double-serialised JSON string (`:244-247`).
- Sport/market/settlement: `sportName` → `SPORT_MAP` (`:28-45`); registry for
  football, `sports.spec_for` for basketball/tennis; `parse_local_dt` treats
  timestamps as Sarajevo wall-clock (`:519`).
- Deep link: fixed prematch/live page (`:343`, `:551`); config declares no route.
- Fixtures/tests: `markets/sportplus_{prematch,live}.json`,
  `e2e_certified/sportplus_prematch.json`; `test_market_fixtures.py`,
  `test_market_mapping.py`, `test_live_mode.py:159-271`, `test_sports.py`,
  `test_new_markets.py`, `test_e2e_certified.py`.
- Fragility: broad `except` at four levels (`:257`, `:261`, `:301`, `:304`);
  name-string equality for live markets (`:411`, `:437`, `:455`); period-marker
  keyword list (`:98-108`) is a hand-maintained vocabulary; 120 s timeout is the
  largest in the suite.

### 2.9 WWIN — `scrapers/wwin.py:243` `WWINScraper`

- Transport: Playwright hybrid. Session on `/kladjenje/` or `/kladjenje-uzivo/`,
  then `page.request.get` against the content API (`:260-290`, `:374-409`).
  Network JSON, no DOM.
- Endpoints: `PrematchEvents/events?key=bs&bets=&tfrom=&tto=&spid=2`;
  `LiveEvents/events?key=bs…`; `LiveEvents/headerBets?bets=&ids=`.
- Pagination/iteration: prematch loops 15 days × bet-id pairs (max two ids per
  call, `:265-269`, `:312`), `asyncio.gather` with a 6-slot semaphore (`:270`);
  live fetches events then `headerBets` in chunks of 100 event ids (`:399-409`).
- Retry/timeout: adapter-specific 3 attempts with `asyncio.sleep(0.5 × 2ⁿ)`
  (`:276-310`); `headerBets` has **no** retry (continues on non-200, `:410-415`).
  Navigation 60 s; `settle` 5 s.
- Parsing: `bets[]` by `idBt` — 95/6/3/11/2 (`:98-227`); the `else` branch records
  every other id as unmapped.
- Sport/market/settlement: football only (`spid=2`, no `sport=` on `Match`);
  registry IDs; `full_time`.
- Deep link: fixed `/kladjenje/` (`:355`) and `/kladjenje-uzivo/` (`:451`);
  config declares no event route.
- Fixtures/tests: `markets/wwin_{prematch,live}.json`,
  `e2e_certified/wwin_prematch.json`; `tests/test_new_bookmakers.py:17-79`,
  `test_market_fixtures.py`, `test_e2e_certified.py`.
- Fragility: broad `except` at four points (`:302`, `:304`, `:388`, `:414`);
  hard-coded bet ids and 15-day loop; `headerBets` silently loses a chunk on error.

### 2.10 Premier Kladionica — `scrapers/premier_kladionica.py:145` `PremierKladionicaScraper`

- Transport: plain HTTP, httpx (60 s), **no** `fetch_with_retry`. JSON-RPC over
  `POST https://svc-web.premier-kladionica.com/PrSync/PrSync.ashx`, body
  `[[[4,1,0],7,{"dogadjajIDs":"…","clientVer":…}]]`.
- Pagination/iteration: one full sync, then delta sync per 150 event ids
  (`ODDS_CHUNK`, `:230-247`); all chunks are gathered concurrently with no cap.
- Retry/timeout: none — a failed call logs, records `None`, and returns `None`;
  the book then reports empty (`:437-459`).
- Parsing: positional array sections (2 sports, 3 groups, 5 events, 7/8/9 market
  definitions) and `dogTipK` odds rows decoded by `(setTipID, varID, tipID)`
  (`:279-429`). Market classification is by **normalised market name**
  (`UTAKMICA`, `OBA DAJU GOL`, `ZBROJ GOLOVA`, …).
- Sport/market/settlement: football only (`FOOTBALL_SPORT_ID = 2`, `:64`);
  registry IDs by name-derived prefix (`UTAKMICA_1X2`, `LIVE_…`, `:315-399`);
  `full_time`.
- Deep link: fixed `/ponuda/` (`:268`); config declares no event route.
- Fixtures/tests: `markets/premier_kladionica_{prematch,live}.json`;
  `tests/test_new_bookmakers.py:81-200`, `test_new_markets.py:242-290`,
  `test_market_fixtures.py` (mode-aware BTTS regression), `test_parser_contracts.py`.
- Fragility: positional `row[0..14]` indexing (`:197-224`) and `sections[2]/[3]/[5]/[7]/[8]/[9]`
  (`:160-199`) are the most shape-sensitive code in the repo; hard-coded RPC
  envelope (`:431-443`); host moved `svc-test → svc-web` on 2026-10-27 (docstring
  `:4-6`); broad `except` (`:444`).

## 3. Shared plumbing (applies to all)

- `launch_browser` (`scrapers/base.py:21-65`): Chromium, `--no-sandbox`, locale
  `bs-BA`, TZ `Europe/Sarajevo`, `navigator.webdriver` patched, image/media/font
  aborted. Browser concurrency capped at 3 (`config/settings.py:377`,
  `server/api.py:251`).
- `fetch_with_retry` (`scrapers/base.py:145-177`): 3 attempts, `0.5 × 2ⁿ` backoff,
  retries 5xx/timeouts/network only; 4xx returns immediately; `None` on exhaustion.
- `fetch_pages` (`:122-143`): batched offset walk, stops at first empty/short/failed
  page, so a mid-feed failure truncates silently.
- `settle` (`:105-114`): `networkidle` bounded by the old fixed sleep; swallows
  timeouts. No `wait_for_timeout` remains.
- `parse_dt` (`scrapers/common.py:59-100`) is the one datetime parser; SportPlus
  uses `parse_local_dt` (`:40`) for offset-less local times.

## 4. Sport / market / settlement mapping (pointers only)

- Sport: `engine/sports.py` — `SPORT_ALIASES` (`:34-49`), `normalize_sport` (`:122`),
  `spec_for` (`:128`), per-sport settlement strings (`:79-116`).
- Market: `engine/market_registry.py` — `MarketSpec` (`:90-109`),
  `lookup`/`lookup_type` (`:275-318`), `registered_spec` (`:327-345`).
  Data: `config/bookmaker_markets.json`; generated rows merged only with provenance
  (`engine/market_registry.py:199-259`).
- Settlement: registry `settlement` per row; non-football settlement comes from
  `engine/sports.py`; `Market.settlement` default `"full_time"` (`models/schemas.py:71`).
- Price-source identity: `config/settings.py:217` seeds mdshop+admiralbet as `nsoft`;
  `engine/skin_detection.py` may register measured twins at runtime.

## 5. Deep links

`config/bookmaker_deeplinks.json` drives `build_event_url`
(`scrapers/common.py:957-981`); only `mozzartbet` and `maxbet` declare
`supports_event_id: true` (both with `route_pattern_verified: true`), the other
eight declare `false` and resolve to a competition/base page. Ticket prefill,
the `ticket_filled → match_page → search → competition` ladder and the NSoft
`ticketItems` builder live in `engine/destinations.py:37`, `:238-344`, `:402-434`.
All nine enabled books were spot-checked on 2026-11-03
(`config/bookmaker_destinations.json` header and `books` keys).

## 6. Output validation

Adapters do not validate against a JSON Schema. They construct Pydantic models
(`models/schemas.py:40-145`), so field types are coerced/checked at construction,
and every market is additionally gated by registry `labels` + `min_legs`
(and `requires_sbv` for NSoft live). A separate payload-shape contract layer
(`engine/parser_contracts.py`) fingerprints each fixture's IDs, labels and
structure; CI enforces it via `scripts/refresh_fixtures.py --check`
(`tests/test_parser_contracts.py:48-56`).

## 7. Summary table

| Book | Transport | Pagination / iteration | Retry | Schema-validated | Fixture coverage | Fragility notes |
|---|---|---|---|---|---|---|
| mozzartbet | Playwright → network JSON (POST) | 0-based pages, size 15, cap 100, batch 4 | none (page fail = stop) | Pydantic + registry | prematch + live | silent capture `except`, many shape fallbacks |
| mdshop | httpx | one call per sport | base (3×) | Pydantic + registry | prematch + live + e2e | broad excepts, no event paging |
| admiralbet | Playwright → network JSON (GET) | one call per sport | none | Pydantic + registry | prematch + live + e2e | one broad try aborts all sports |
| betole | httpx | offset 0–30 000 step 1 500 | base (3×) | Pydantic + registry | prematch only | hard-coded pick codes, offset ceiling |
| evlbet | httpx | offset, 20 pages × 100 | base (3×) | Pydantic + registry | none (disabled) | dict-or-list response, no live odds |
| maxbet | httpx | one call per sport | base (3×), football raises | Pydantic + registry/sport | prematch + live | hard-coded odd-type ids |
| mbet | httpx | offset, 200 pages × 100 | base (3×) | Pydantic + registry/sport | prematch + live + e2e | broad excepts, key-prefix tables |
| sportplus | httpx | none (one payload) | base (3×) | Pydantic + registry/sport | prematch + live + e2e | name-string matching, 120 s timeout |
| wwin | Playwright → network JSON (GET) | 15 days × bet pairs; live chunks of 100 | custom 3× (headerBets none) | Pydantic + registry | prematch + live + e2e | silent chunk loss, hard-coded ids |
| premier_kladionica | httpx JSON-RPC | full sync + delta per 150 ids | none | Pydantic + registry | prematch + live | positional indices, no retry |

## 8. Risks / uncertainties

- **Not verified against live feeds today.** Transport and shape claims come from
  code and dated fixtures (2026-10-20 – 2026-11-05). Feeds may have moved.
- **No DOM-parsing adapter exists**, so this inventory cannot say whether any book
  has silently switched from JSON to server-rendered HTML.
- **Silent truncation is systemic**: `fetch_pages` stops on a failed page and every
  adapter treats a short result as a complete one. Under-reporting is not
  distinguishable from a quiet match day in the per-book counts.
- **Registry-vs-feed drift** is only caught where a captured fixture exists; EVLBet
  and parts of Betole/Premier/Mozzartbet O/U rows are declared uncovered
  (`tests/test_market_fixtures.py:83-129`).
- **`except Exception` is used 22 times across `scrapers/`**, mostly around parse
  or fetch loops; exceptions are logged at debug and the row is dropped. This is
  intentional availability-over-completeness, but it hides feed changes.
- The two browser paths that matter for anti-bot (mozzartbet, wwin) rely on
  `--disable-blink-features=AutomationControlled` and a patched `navigator`; a
  Cloudflare rule change would surface as an empty scan, not an error.

## 9. Conclusions

1. Ten adapters: seven plain HTTP and three Playwright hybrids; zero websocket,
   zero DOM-scraping.
2. All three browser adapters still take odds from JSON — Playwright is used only
   to obtain a session/cookies, never to read HTML.
3. Four adapters dominate structural risk: premier_kladionica (positional arrays),
   sportplus (name-based classification), betole (hand-coded pick codes) and
   wwin (hard-coded bet ids + custom retry).
4. Retry behaviour is not uniform: three adapters have no retry at all
   (mozzartbet, admiralbet, premier), wwin has a private backoff, the rest inherit
   the 3-attempt helper.
5. Pagination is heterogeneous: four books are single-request (mdshop,
   admiralbet, maxbet, sportplus), the rest page by offset, day or event chunk.
6. Market correctness is enforced by the registry (`labels`, `min_legs`,
   `requires_sbv`), not by adapter-level schemas; only captured fixtures prove the
   IDs against the real feeds.
7. Deep links are only truly per-event for mozzartbet and maxbet; the other eight
   are declared linkless and fall back to competition pages.
8. EVLBet is the only adapter with no fixture and is disabled; every other book
   has at least one dated capture.
