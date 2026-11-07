# Shared scraper infrastructure — BH_Arb

Read-only map of the shared scraping layer (not per-book parsing). All paths are
relative to the repository root; line numbers refer to the tree as inspected on
2026-11-07.

## Files inspected

- `scrapers/base.py` (whole, 177 lines)
- `scrapers/__init__.py` (whole, 51 lines)
- `scrapers/cost.py` (whole, 251 lines)
- `scrapers/common.py` (structure + lines 1–30, 191–207, 302–360, 427–530, 660–692, 692–1000)
- `scrapers/mozzartbet.py` 355–470 · `admiralbet.py` 96–230 · `wwin.py` 243–330, 355–365
- `scrapers/mbet.py` 551–620 · `sportplus.py` 218–300 · `mdshop.py` 60–140 · `evlbet.py` 1–100
- `scrapers/maxbet.py` 337–470 · `betole.py` 150–240 · `premier_kladionica.py` 140–260, 420–462
- `server/scheduler.py` (whole, 89 lines) · `server/app.py` 1–90
- `server/api.py` 230–430, 1000–1045, 1720–2120, 2120–2340, 3281–3380, 3440–3625, 4440–4520, 4700–4780
- `server/observability.py` (whole, 325 lines) · `server/scan_cost.py` 1–130
- `engine/parser_contracts.py` (whole, 357 lines) · `engine/feed_integrity.py` (whole, 326 lines)
- `engine/coverage_budget.py` 1–60 · `engine/price_guard.py` (whole) · `engine/market_registry.py` 1–80, 265–348
- `engine/stale_price.py:158` · `engine/arbitrage.py:485, 706` · `models/schemas.py` 40–110, 390–402
- `config/settings.py` 1–120, 120–260, 260–350, 350–507 · `config/bookmaker_deeplinks.json` head
- `scripts/verify_deeplinks.py` 403–582 · `requirements.txt` · `Dockerfile`
- `tests/test_layering.py` 1–90

---

## 1. Class/module hierarchy and orchestration

**There is no base scraper class.** Each book exposes a plain duck-typed class
(`scrapers/admiralbet.py:96`, `mozzartbet.py:355`, `mdshop.py:70`,
`sportplus.py:218`, `mbet.py:551`, `evlbet.py:55`, `betole.py:162`,
`maxbet.py:337`, `premier_kladionica.py:145`, `wwin.py:243`) with an
`async def scrape(live, scan_time, [sports_wanted])` entry point. The majority
implement `fetch_and_parse()` and have `scrape()` delegate to it
(e.g. `mozzartbet.py:460`, `admiralbet.py:217`). Signature drift is absorbed by
`run_scan`, which first calls with `sports_wanted=ENABLED_SPORTS`, then retries
on `TypeError` mentioning `sports_wanted`/`scan_time` and finally falls back to
`scrape(live=...)` (`server/api.py:1980-1994`); books such as `wwin`, `betole`,
`evlbet` and `premier_kladionica` therefore need no sport parameter.
`scrapers/base.py` is a module
of free functions, not a superclass: `launch_browser()` (`base.py:20`), `goto()`
(`:71`), `settle()` (`:106`), `fetch_pages()` (`:118`), `fetch_with_retry()`
(`:148`), `measured_api_get/post()` (`:92`, `:99`).

**Registration is a hard-coded dict**, not discovery: `SCRAPERS` at
`server/api.py:1020-1031`. `PLAYWRIGHT_BOOKIES = {"mozzartbet", "admiralbet",
"wwin"}` at `api.py:253` duplicates the set of books that call
`launch_browser()` (`mozzartbet.py:365`, `admiralbet.py:110`, `wwin.py:257,371`).
`EVLBet` is registered but disabled in config (`config/settings.py:60`).

**Lazy imports** in `scrapers/__init__.py`: `_EXPORTS` name→module map and a
PEP 562 `__getattr__` (`:33-51`), with `TYPE_CHECKING` imports only (`:12-20`).
`tests/test_layering.py:52-76` asserts that importing `scrapers` or
`scrapers.common` loads no book module and no Playwright. Note that
`server/api.py:133-155` imports every scraper module eagerly at server start, so
the laziness protects tests/scripts and `engine` imports, not the running app.

**Cycle orchestration**: FastAPI lifespan starts one `asyncio` task per enabled
feed (`server/app.py:63-72`), each running `scan_loop(mode, minutes)`
(`server/scheduler.py:26-37`): sleep interval → `start_scan_if_idle(mode)` →
`run_scan(mode, True)`. `run_scan` (`api.py:1887`) sets `status.is_scanning`,
builds one `scrape_one` coroutine per book (`api.py:1933`), and runs them all
concurrently with `asyncio.gather(..., return_exceptions=True)`
(`api.py:2036-2037`). Single process, single event loop, asyncio only — no
worker pool, no multiprocessing. Mutexes: per-mode `asyncio.Lock`
(`api.py:249-250`), `_browser_sem = asyncio.Semaphore(BROWSER_CONCURRENCY)`
(`api.py:251`). `start_scan_if_idle` (`api.py:3325-3340`) prevents scheduler and
manual scans overlapping; a maintenance lock blocks both (`server/maintenance.py:59`).

## 2. HTTP stack

- Library: **httpx 0.28.1**, async API (`requirements.txt:6`). No requests,
  aiohttp, or curl_cffi anywhere in the app (`scripts/` also uses httpx).
- **No session reuse across scans.** Each scrape opens and closes its own
  `httpx.AsyncClient` in an `async with` block: `sportplus.py:237,277`,
  `mbet.py:578`, `mdshop.py:109`, `maxbet.py:362`, `evlbet.py:69`,
  `betole.py:175`, `premier_kladionica.py:152`.
- Timeouts are per module, 20–120 s: `evlbet.py:69` 20 s, `mbet.py:578` 30 s,
  `mdshop.py:109` 30 s, `betole.py:175` 30 s, `maxbet.py:362` 60 s,
  `premier_kladionica.py:152` 60 s, `sportplus.py:237` 120 s / `:277` 60 s.
- TLS verification is **off by default**: `VERIFY_SSL = os.getenv("VERIFY_SSL",
  "false")` (`config/settings.py:364`), passed to every client.
- Headers: per-module `API_HEADERS` dicts built from `dict(...)`
  (`mbet.py:555`, `mdshop.py:77`, `sportplus.py:222`, `maxbet.py:342`,
  `premier_kladionica.py:148`); EVLBet carries its own UA/Origin/Referer
  (`evlbet.py:39-47`). Browser UA from `config/settings.py:365-369`.
- No proxy configuration, no explicit httpx connection limits, no HTTP/2 tuning
  found.
- Premier Kladionica is the only scraper that POSTs JSON-RPC
  (`premier_kladionica.py:437-459`); it does **not** use `fetch_with_retry`.

## 3. Browser stack

- **Playwright async API**, Chromium only, launched per scrape via
  `launch_browser()` (`scrapers/base.py:20-65`): `async_playwright().start()`,
  `chromium.launch(headless=HEADLESS, args=[--no-sandbox,
  --disable-blink-features=AutomationControlled, ...])`, one `BrowserContext`
  with fixed UA/viewport/locale `bs-BA`/`Europe/Sarajevo`, an
  `add_init_script` that removes `navigator.webdriver`, and `context.route`
  aborting `image`, `media`, `font` (`base.py:58-63`, `:68`).
- **No pooling.** Every `scrape()` call starts and stops its own Playwright +
  browser + context and opens one page, closed in a `finally`: `mozzartbet.py:442-443`,
  `wwin.py:363-364` and `:460-461`, `admiralbet.py:162-163`. `wwin` launches
  two separate browsers (prematch :257, live :371).
- Concurrency is capped by `BROWSER_CONCURRENCY = 3` (`config/settings.py:377`)
  via the semaphore acquired in `run_scan` (`api.py:1965-1968`) and in the verify
  path (`api.py:4482-4500`).
- Pattern is **hybrid**: browser visits the site to obtain Cloudflare/session
  cookies, then JSON is pulled through `page.request` (`measured_api_get/post`,
  `base.py:92-103`) rather than DOM scraping. Mozzartbet additionally captures
  network responses with `page.on("response", capture_response)`
  (`mozzartbet.py:378-386`). Wait strategy is `wait_for_load_state("networkidle",
  timeout=max_ms)` with the exception swallowed (`base.py:106-115`).
- Deep-link verification (`scripts/verify_deeplinks.py:560-577`) reuses the same
  launcher: one browser/context/page for a whole book run, `page.on("response")`
  JSON capture with a size cap and a settle poll loop (`:416-499`), then
  `context.close()` / `browser.close()` / `playwright.stop()`.

## 4. Retry / backoff

- **Hand-rolled only; no tenacity.** `fetch_with_retry()` (`base.py:148-177`):
  `max_retries=3`, `backoff_factor=0.5`, sleep `0.5 * 2**(attempt-1)` (0.5 s,
  1 s). Retries **only HTTP ≥ 500** and `httpx.TimeoutException` /
  `NetworkError` / `RequestError`; any status < 500 is returned immediately, so
  **403/429 are neither retried nor given special handling**. Returns `None`
  after exhaustion. No jitter.
- Used by `mbet.py:589`, `sportplus.py:239,279`, `mdshop.py:120`,
  `maxbet.py:374`, `evlbet.py:75`, `betole.py:177`.
- WWIN has its own 3-attempt loop with `0.5 * 2**attempt` sleeps for non-200
  and exceptions (`wwin.py:276-311`).
- Premier Kladionica: single attempt, logs and returns `None`
  (`premier_kladionica.py:437-459`).
- Alert delivery retries separately, 3 attempts with exponential backoff
  (`server/alerts.py:569-574`).
- `classify_exception()` maps failures to `blocked` vs `parse_error` by string
  markers (`cost.py:105-115`).

## 5. Rate limiting / throttling / cooldowns

- **Inbound API throttling only**: per-client sliding window
  (`api.py:3291-3322`) with separate buckets for scans, verifies and deep-link
  checks; limits `SCAN_RATE_LIMIT=3`, `VERIFY_RATE_LIMIT=10`,
  `DEEP_LINK_VERIFY_RATE_LIMIT=2` per 60 s (`settings.py:393,420,424`).
- **Per-book scheduled-scan backoff**: after
  `BOOK_BACKOFF_AFTER_FAILURES=3` consecutive empty/error runs, a book is
  skipped for `2**n * interval` capped at `BOOK_BACKOFF_MAX_MINUTES=60`
  (`api.py:1740-1764`, `settings.py:414-415`); manual scans ignore it
  (`api.py:1943`).
- **Browser concurrency cap** 3 (`settings.py:377`, `api.py:251`).
- **Feed-integrity quarantine** removes a book from pricing for the scan, with
  recovery after 3 consecutive clean scans (`engine/feed_integrity.py:231-247`,
  `settings.py:433`).
- Runtime per-book disable toggles persisted in `cache/bookmaker_state.json`
  (`api.py:242-318`).
- Outgoing request throttling: only `wwin` uses `asyncio.Semaphore(6)`
  (`wwin.py:270`) and `fetch_pages` fetches in batches of 4 (`base.py:122,137`).
  **No per-book outbound rate limiter, no per-cycle wall-clock timeout** (no
  `asyncio.wait_for`/`asyncio.timeout` anywhere in `server/`, `scrapers/`,
  `engine/`); a scan ends only when every scraper coroutine ends or its
  per-request timeouts fire.

## 6. Pagination helpers

- Generic concurrent page walker: `fetch_pages(fetch_page, page_size,
  max_pages, batch=4, first_page=0)` (`base.py:118-145`). It stops at the first
  failed/empty/short page so concurrent results equal a sequential walk. Used by
  `mbet.py:603` (offset 100, max 200), `evlbet.py:100` (offset 100, max 20),
  `mozzartbet.py:437-440` (currentPage, pageSize 15, cap 100).
- Hand-rolled loops: `betole.py:174` (offset 0…30000 step `PAGE_SIZE`, stops on
  short page), `wwin.py:269-313` (15 days × bet-id pairs, then merge by event
  id), `premier_kladionica.py:229-240` (event-id chunks, concurrent
  `_delta_sync`).

## 7. Anti-breakage controls

- **Typed models**: pydantic v2 `Match`, `Market`, `OddsValue`, `MatchGroup`,
  `Surebet` (`models/schemas.py:40-110, 274-390`). Parsers construct these, so a
  missing/wrong-typed field fails at parse time per event.
- **Dated parser contracts**: `engine/parser_contracts.py` records top-level
  keys, source-id set, label set, structural paths and a fingerprint per
  fixture; `diff_contract()` (`:206-229`) yields a concrete diff instead of a
  vague parse error. Enforced in CI by
  `scripts/refresh_fixtures.py --check`; health block `contract_health()`
  (`:330-357`) exposes stale/missing coverage at `/api/health`
  (`server/api.py:3527`).
- **Feed integrity scorecard** (`engine/feed_integrity.py:172-296`): critical
  reasons `parse_error`, `empty_feed`/`skipped_backoff`, `stale_prices`,
  `own_margin_below_one`, `outlier_rate`; warnings `missing_markets`,
  `outlier_rate`. Quarantined books are stripped from pricing only
  (`:299-326`); the gate is untouched.
- **Coverage budget** (`engine/coverage_budget.py:32+`): per book/sport/market
  counts vs rolling median, flags a ≥50 % drop only when peers still publish
  (peers prevent night-time false alarms).
- **Stale/frozen prices** (`engine/stale_price.py:158`) and **price guard**
  (`engine/price_guard.py:15`) drop legs that are outliers against peer
  de-vigged prices.
- **Profit sanity cap** `MAX_SUREBET_PROFIT_PERCENT=20 %` rejects implausible
  surebets (`config/settings.py:243`, `engine/arbitrage.py:706`).
- **Unknown market IDs** are counted per book (`engine/market_registry.py:51-60`)
  and surfaced in health; excluded IDs are ignored.
- **Empty-result alarms**: when other books returned data, a book reporting
  `done` with zero matches is logged and appended to `status.errors`
  (`api.py:2061-2067`); an odds-age spread > 90 s between books is warned
  (`api.py:2069-2081`).
- Fail-safe config: a malformed/missing `config/bookmaker_deeplinks.json`
  grants no declarations and blocks links (`scrapers/common.py:718-745`); market
  risk/declaration files fall back to explicit "unknown" (`settings.py:111-130`).

## 8. Observability

- **stdlib `logging`**, not structlog. JSON or text formatter with a
  request/scan correlation id installed via a log-record factory
  (`server/observability.py:78-104, 143-182`); configured in `main.py:14`.
- **Hand-rolled Prometheus registry** (`observability.py:203-291`), rendered at
  `/api/metrics` (protected by the API key, `api.py:3453-3460`).
- Scraper metrics: `bh_scans_started/completed/failed`, `bh_scan_seconds_total`,
  `bh_book_results_total{mode,book,outcome}`, `bh_browser_slots_in_use`,
  `bh_book_seconds`, `bh_book_requests`, `bh_book_bytes`,
  `bh_book_failure_rate`, `bh_surebets_*`, coverage and mapping-ratio gauges
  (`api.py:1767-1801, 1841-1866`). Zero-valued baselines are pre-registered
  (`api.py:1777-1804`).
- **Per-book cost records** with wall/browser seconds, requests, bytes, outcome,
  matches, markets and explicit "missing" reasons (`scrapers/cost.py:118-177`);
  aggregated per scan (`cost.py:180-251`) and over a 20-scan window
  (`server/scan_cost.py:106-130`).
- `/api/health` aggregates feed-integrity states, stale prices, coverage
  budgets/trends, scan cost, parser-contract health, scheduler backoff and
  last-scan ages (`api.py:3462-3625`). Per-book last success is
  `feed_integrity[*].last_successful_scan` (`engine/feed_integrity.py:249-252`).
- No dashboards in `server/` beyond the health/metrics payloads; the frontend is
  under `frontend/`.

## 9. Dependencies (scraping-related)

`requirements.txt`: `playwright==1.61.0` (:3), `httpx==0.28.1` (:6),
`pydantic==2.13.4` (:4), `rapidfuzz==3.14.5` (:5), `python-dotenv==1.2.2` (:7),
`tzdata==2026.5` (:8). `requirements-dev.txt` adds pytest/ruff/mypy/hypothesis/
pip-audit/bandit. No tenacity, no aiohttp, no requests, no structlog, no
prometheus_client, no curl_cffi. Docker installs Chromium via
`playwright install --with-deps chromium` (`Dockerfile:38-39`).

## 10. Risks / uncertainties

1. **No whole-scan timeout.** A hung browser or a slow endpoint can hold the
   per-mode lock indefinitely (individual navigation/request timeouts are 20–120 s,
   but loops over days/pages can be long). Not verified whether an outer
   supervisor exists outside this repo.
2. **429/403 not retried and no `Retry-After` handling.** Rate-limited responses
   surface as `empty`/`parse_error`, which then feeds the backoff counter; a
   transient throttle can look like a broken parser.
3. **Retries are synchronized** (no jitter) and only 3 attempts; several books
   retrying in the same tick can amplify load.
4. **Config duplication:** the Playwright set (`api.py:253`) and the SCRAPERS
   dict (`api.py:1020`) are hand-maintained; a new book must be added in both,
   plus `settings.BOOKMAKERS` and deeplink/destination JSON. Missing one produces
   `no scraper registered` at run time, not at import.
5. **TLS verification defaults off** (`settings.py:364`); acceptable for public
   odds feeds but a MITM surface.
6. **No cross-process coordination**: state (`_bookmaker_enabled`, backoff,
   metrics) is per process; multi-worker uvicorn would duplicate scans/backoff
   state. Deployment currently runs one process (`Dockerfile` CMD `python main.py`).
7. Uncertain: exact scraper-level request volume for `wwin` (15 days × bet
   groups) depends on `_request_market_ids`; I did not enumerate it.

## Conclusions

1. Shared scraping infrastructure is a **function library plus a hard-coded
   registry**, not a class hierarchy; `base.py` supplies browser launch,
   measurement, pagination and the single retry helper.
2. Orchestration is a **single-process asyncio fan-out** (`gather` over books)
   with per-feed locks, a 3-browser global semaphore, and an optional scheduler
   loop that never overlaps a manual scan.
3. **HTTP is httpx with a fresh client per scrape**, 20–120 s timeouts, TLS
   verification off by default, and no proxy/pooling/connection-limit tuning.
4. **Playwright is async and per-scrape**: one Chromium+context+page per book,
   session establishment via a real page load, data via `page.request` and
   `page.on("response")`, always closed in `finally`.
5. **Retries are minimal and hand-rolled** (3 attempts, 5xx/network only, no
   jitter, no 429 handling); Premier Kladionica has no retry at all.
6. **Anti-breakage is layered after parsing**, not only inside it: pydantic
   models, dated fixtures/contracts, feed-integrity quarantine, coverage deltas
   and price-outlier guards.
7. **Observability is stdlib logging + a home-grown Prometheus registry**, with
   rich `/api/health` and per-scan cost accounting; no external metrics or
   tracing dependency.
8. The main operational gaps are the **absence of a per-scan wall-clock
   timeout**, naive retry policy for throttling, and several hand-synchronized
   registries that can drift.
