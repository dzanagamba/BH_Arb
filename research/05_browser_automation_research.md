# 05 — Browser automation: Playwright, crawler frameworks, and reliability patterns

Researched 2026-11-07 against PyPI, GitHub and the projects' own docs. Scope
excludes stealth plugins, fingerprint spoofing, captcha solvers,
undetected-chromedriver and camoufox-style forks: the scanner must not log in,
place bets, or evade anti-bot protection or account limits.

## Current state in this repo

- `requirements.txt` pins `playwright==1.61.0`; PyPI latest is **1.64.1**
  (2026-10-22), so the pin is three minor releases behind.
- One shared launcher, `scrapers/base.py:20-65`: `chromium.launch()` +
  `browser.new_context()` per scan run, one page per run, closed at the end
  (`scrapers/admiralbet.py:110-162`, `scrapers/mozzartbet.py:365-442`,
  `scrapers/wwin.py:257-363`).
- The launcher passes `--disable-blink-features=AutomationControlled` and
  installs an init script that rewrites `navigator.webdriver`, `navigator.plugins`,
  `navigator.languages` and `window.chrome` (`scrapers/base.py:32`, `:50-55`).
  That is fingerprint masking in the same class as the excluded tools, and it
  conflicts with the "never evade anti-bot" invariant. Reported as fact, not
  intent.
- Resource blocking is done through `context.route("**/*")`
  (`scrapers/base.py:58-63`) — the pattern that `playwright-python#3121`
  identifies as leaking one retained `asyncio.Task` per intercepted request.
- Odds already come from the books' JSON endpoints via
  `page.request.get/post` (`scrapers/base.py:92-103`), and Mozzart reads the
  page's own responses (`scrapers/mozzartbet.py:384`). DOM parsing is not the
  primary path.
- The deep-link verifier reuses one page for N targets sequentially
  (`scripts/verify_deeplinks.py:562-570`) with one navigation timeout
  (`:568`) and polling at `:459`.
- Test fixtures are hand-trimmed JSON payloads (`tests/fixtures/markets/*.json`,
  produced by `scripts/capture_market_fixtures.py`), not HAR or DOM snapshots;
  the capture script still relies on fixed sleeps (`:349`, `:379`,
  `:948`).

## 1. Playwright for Python

- **Version / date:** 1.64.1, 2026-10-22. Ten releases in the last 12 months
  (1.56 → 1.64.1). The docs site already carries 1.65 release notes
  (Chromium 158), so 1.65 was imminent but not on PyPI at fetch time.
- **License / Python:** Apache-2.0, `Requires-Python >=3.10`.
- **Maintenance:** very active — `microsoft/playwright-python` pushed
  2026-11-06, >100 commits since 2025-11-07, 2 open issues, 15.1k stars.
- Relevant capabilities, all current and documented:
  - **HAR record/replay.** `browser.new_context(record_har_path=...,
    record_har_mode="minimal"|"full", record_har_content="embed"|"attach"|"omit",
    record_har_url_filter=...)`, saved on `context.close()`. Replay via
    `page.route_from_har(har, not_found="abort"|"fallback", update=bool)` and
    the same on `BrowserContext` (`not_found="fallback"` falls through to the
    next handler). HAR can also be captured through tracing since 1.60
    (`tracing.start_har()` / `stop_har()`).
  - **Response awaiting.** `page.expect_response(url_or_predicate)` used as a
    context manager, plus `page.on("response")` for capture streams.
  - **Tracing.** `context.tracing.start(screenshots=True, snapshots=True,
    sources=True)` → `stop(path=...)`; 1.63 added `aria_snapshots` and
    `screen_snapshots`. Offline viewing with `playwright show-trace`.
  - **Auto-waiting.** Locators re-check visible/stable/receives-events/enabled
    (and, since 1.65, not-inert) before acting; `get_by_role`,
    `get_by_text` and `locator.visible` (1.63) replace raw CSS where the DOM
    is the only signal.
  - **Timeouts.** Per-action, per-navigation and `set_default_timeout` /
    `set_default_navigation_timeout`; `expect_response` accepts `timeout`.
  - **Remote/attached browsers.** `browser_type.connect()` (Playwright
    protocol, version-locked) and `connect_over_cdp()` (Chromium only;
    documented as "significantly lower fidelity" and dependent on launch
    arguments matching).
  - **Async vs sync.** Both APIs; sync cannot run inside a running event loop,
    which is why an asyncio service should stay on `async_api` (this repo
    already does).
- **Memory in long-running processes.** `playwright-python#3121` (opened
  2026-06-18, closed 2026-07-02) measured ~160 retained done `asyncio.Task`s per
  context that used `context.route()`; RSS grew ~3.5 MB/URL, 721 MB at 200
  image-heavy pages. Every Python-level route handler leaks, whether it
  `continue_()`s or `abort()`s. Root cause was in CPython (`asyncio.wait`
  await-graph), fixed by `python/cpython#152585` (merged 2026-07-02); the
  issue's own workaround is CDP `Network.setBlockedURLs`. Older long-running
  leaks are tracked in `microsoft/playwright#6319` (still receiving "2026, still
  happening" reports). Docs ship no "restart every N pages" recipe; recycling
  the context (or browser) after N pages and closing the `async_playwright`
  connection periodically is community practice, corroborated by
  `scrapy-playwright`'s `PLAYWRIGHT_MAX_PAGES_PER_CONTEXT`.
- **Fit: adopt, upgrade the pin.** It is already the engine; the useful work is
  configuration, not replacement. Reason: HAR/trace/expect_response directly
  serve "prove the page opened the right event" and "keep a forensic record of
  a failed capture".

## 2. pytest-playwright

- 0.10.0 (2026-10-08), Apache-2.0, `>=3.10`, 4 releases in 12 months.
- Fixtures: session-scoped `browser`/`playwright`, function-scoped `context`/
  `page`, plus `browser_context_args`, `browser_type_launch_args` and
  `connect_options` overrides; `--tracing on|off|retain-on-failure` and
  `--browser`.
- **Fit: adopt for the deep-link/browser tests only.** These tests currently
  need no framework, but `--tracing retain-on-failure` plus per-test context
  isolation is exactly the forensic behaviour wanted, at the cost of one test
  dependency. Scripts (`scripts/verify_deeplinks.py`) should keep hand-rolled
  tracing, since they are CLI tools, not pytest.

## 3. Crawlee for Python

- 1.11.1 (2026-11-05), Apache-2.0, `>=3.10`; 156 published versions in the
  last 12 months (many betas), changelog current through 2026-11-06.
- Provides `PlaywrightCrawler`, `AdaptivePlaywrightCrawler`, `BrowserPool`
  (pre/post launch, page-create and page-close hooks; active/inactive/closed
  states), `SessionPool` (proxy/cookie pairing, block filtering), `Statistics`
  (finished/failed, retries histogram, per-status-code counts) and
  `AutoscaledPool`.
- Positioning is explicitly anti-detection ("fly under the radar of modern bot
  protections"), and it offers browserforge fingerprint/header generators.
  Those parts are out of scope here.
- **Fit: borrow patterns, do not adopt.** Reason: it replaces the scheduler,
  storage and request model of a scanner that already has its own engine
  (`engine.*`) and a `cache/` contract; its value for three bookmakers and a
  deep-link checker is small, and its optional fingerprint machinery would drag
  excluded capability into the dependency tree. Borrow: pool lifecycle hooks,
  per-domain concurrency, and a `Statistics`-shaped run summary.

## 4. Crawl4AI

- 0.9.5 (2026-10-14), Apache-2.0, `>=3.10`, 14 releases in 12 months, docs at
  v0.9.x.
- Aimed at LLM/RAG markdown extraction; has `CacheMode` (`ENABLED`,
  `DISABLED`, `READ_ONLY`, `WRITE_ONLY`, `BYPASS`), network/console capture,
  hooks, session management, and an "Undetected Browser" / anti-bot fallback
  path (out of scope).
- 0.9.5 is a **security release**: six coordinated advisories in the Docker
  server, including SSRF through the cache validator, page JS injection via
  `css_selector`/`wait_for`, ReDoS through caller regexes, and Chromium
  launched with certificate checks off.
- **Fit: avoid.** Reason: the extraction target is prose, not a bookmaker JSON
  payload; adopting it adds a cloud-coupled, server-shaped dependency with a
  recent security record, for capabilities Playwright already provides.
  Borrow only the idea of an explicit cache-mode enum if HTTP caching of API
  responses is ever introduced.

## 5. scrapy-playwright

- 0.0.48 (2026-07-10), BSD-3-Clause, `>=3.10`, 4 releases in 12 months
  (Jan, Jan, Jun, Jul 2026), ~1.5k stars, 13 open issues, active-ish.
- A Scrapy download handler: `Request.meta["playwright"]=True`, `PageMethod`
  lists, `playwright_include_page`, and `PLAYWRIGHT_MAX_PAGES_PER_CONTEXT` to
  recycle a context after N pages. Docs warn that unclosed pages count against
  that limit and freeze the crawl, so an errback must close pages.
- **Fit: avoid, borrow two rules.** Reason: no Scrapy in this stack, and the
  plugin rides Scrapy's scheduler. Borrow: recycle the context after N pages
  and always close pages in `finally`/errback.

## 6. Alternatives worth knowing

| Tool | State | Verdict |
| --- | --- | --- |
| Browserless (self-host/cloud) | Docker image, README current; **SSPL-1.0 or commercial license**; `ws://host` endpoint driven by unmodified Playwright/Puppeteer | Avoid: licence is incompatible with a private scanner; the capability (a remote ws endpoint) is available from `playwright run-server` / `connect()` |
| `connect_over_cdp` | Playwright API, Chromium-only, documented as lower fidelity; `artifacts_dir` added 1.61 | Borrow only if a long-lived warm browser is needed; local `launch()` is simpler for 3 books |
| Selenium 4 | 4.52.0 (2026-10-29), Apache-2.0, 14 releases/12mo; WebDriver BiDi (W3C, network/script/logging modules) is the standards-track successor to CDP | Avoid: a rewrite with no capability this scanner needs |
| pydoll | 3.0.0 (2026-09-29), MIT, 28 releases/12mo, raw CDP, Playwright-compatible import shim, HAR recording and network monitoring | Out of scope: product positioning is fingerprint injection, CAPTCHA/Turnstile handling, humanised input |
| nodriver | 0.50.99 (2026-10-26), **AGPL-3.0**, evasion-first | Out of scope (purpose and licence) |
| playwright-stealth / camoufox | 2.0.3 / 0.5.9 (2026-11-01) | Out of scope: stealth/fingerprint spoofing |

## 7. Patterns that matter here

1. **Prefer the site's JSON API over DOM.** Already the primary path
   (`scrapers/base.py:92-103`); the browser is then only a session/cookie
   factory. Cheapest reliability win: keep it, and treat DOM scraping as a
   fallback with an explicit marker.
2. **Capture network responses rather than scraping rendered text.**
   `page.on("response")` + `response.body()` filtered by URL and
   `resource_type in {"xhr","fetch"}` (as `scrapers/mozzartbet.py:384` and
   `scripts/verify_deeplinks.py:443` do), or `expect_response` when exactly one
   call is expected.
3. **HAR as offline fixture.** `record_har_path` + `record_har_mode="minimal"`
   for a regression fixture; `route_from_har(..., not_found="abort")` to make a
   test fail loudly when a new endpoint appears. This would upgrade the current
   hand-trimmed JSON fixtures with provenance for the *page* layer, which they
   cannot cover today.
4. **Trace/screenshot on failure only.** Start tracing per target, stop to a
   path in the failure branch; in pytest use `--tracing retain-on-failure`.
   Bounded disk: one trace per failure, not per run.
5. **Health watchdog.** Cheap checks: `browser.is_connected()`, a
   `page.goto("about:blank")` round-trip, page count vs. expected, and process
   RSS. Recycle the context after N pages (or M minutes), and restart the whole
   `async_playwright` connection when RSS crosses a threshold.
6. **Per-page timeouts.** `set_default_navigation_timeout` plus an explicit
   action timeout plus an outer `asyncio.wait_for` per target so one hung SPA
   cannot stall a 200-target verification run.
7. **Resource blocking.** Keep it, but implement it without a Python route
   handler: CDP `Network.setBlockedURLs` (the documented workaround in
   `playwright-python#3121`), or `route.abort()` only for a short-lived context.
8. **One page per unit of work.** Reusing a single page across many navigations
   is the memory profile that leaks; a fresh page per target inside a recycled
   context is the safer default (and matches SPA state assumptions).

## 8. Recommended approach

1. Upgrade `playwright` to the current 1.64.x line and keep the pin exact;
   upgrade in the same change as the browser bundle (`playwright install`).
2. Remove the fingerprint-masking init script and the
   `--disable-blink-features=AutomationControlled` flag from
   `scrapers/base.py`; keep locale/timezone/UA/viewport as ordinary site
   configuration. Block resources via CDP instead of `context.route`.
3. Keep `launch_browser()` as the single seam, but give it a lifecycle: context
   per N pages or per M minutes, page per target, `finally` closes everywhere,
   and an `is_connected()`/RSS watchdog that rebuilds the browser.
4. Convert the two browser paths (`scripts/verify_deeplinks.py`,
   `scripts/capture_market_fixtures.py`) to `expect_response`/response capture
   with per-target timeouts, and write a trace + screenshot only on failure.
5. Add HAR record/replay for one representative SPA flow per book, so a parser
   or selector change can be tested offline; keep the existing trimmed JSON
   payload fixtures as the API-layer tests.
6. Do not adopt Crawlee, Crawl4AI, scrapy-playwright or Browserless; borrow the
   pool hooks, the statistics shape, the context-recycle limit and the
   cache-mode idea.

## 9. Risks and uncertainties

- **Pin lag.** 1.61.0 → 1.64.1 is three minors of Chromium jumps
  (149 → 157/158); bookmaker SPAs may behave differently after an upgrade and
  the change is not testable offline without HAR fixtures.
- **Leak fix depends on CPython, not Playwright.** CI runs 3.11/3.12
  (`.github/workflows/ci.yml:18`, `:47`); the `asyncio.wait` fix landed on
  CPython main on 2026-07-02 and its backport status to 3.11/3.12 was not
  verified. Until then, treat `context.route` as a leak source on the pinned
  interpreters.
- **Docs ahead of PyPI.** The 1.65 notes (not-inert actionability, cookie
  matching per RFC 6265, proxy credentials no longer sent to sites) are on the
  docs site but 1.65 was not published at fetch time; behaviour may differ from
  the installed version.
- **GitHub API rate limits** blocked repo-level commit counts for everything
  except `microsoft/playwright-python`; maintenance verdicts for the other
  projects rest on PyPI release dates plus changelogs.
- **Crawl4AI 0.9.5 advisories** were read from its CHANGELOG, not the GHSA
  pages; the fix list is as the maintainers describe it.
- Not covered: proxy rotation, residential egress, TLS/JA3 fingerprinting,
  Playwright's WebKit/Firefox behaviour, and any load/concurrency benchmarking.

## 10. Conclusions

1. Playwright for Python is healthy and current (1.64.1, 2026-10-22, Apache-2.0,
   Python >=3.10, 10 releases/12 months); the repo runs an older 1.61.0.
2. HAR record/replay, `expect_response`, tracing and locator auto-waiting
   already cover the reliability and forensics needs here; no framework is
   required.
3. The resource-blocking route handler in `scrapers/base.py:58` is the exact
   pattern behind playwright-python#3121's memory growth; CDP blocking is the
   documented alternative.
4. The launcher's `navigator.webdriver`/plugins/chrome overrides are
   fingerprint masking, which the trust policy excludes; removing them is a
   policy fix, not a performance trade-off.
5. Crawlee and Crawl4AI are maintained but shaped for large crawls and LLM
   extraction; borrow their lifecycle/statistics patterns, do not adopt.
6. scrapy-playwright's only transferable rule is recycling the context after N
   pages and closing pages on error paths.
7. Selenium 4.52/BiDi, Browserless (SSPL), pydoll and nodriver are either a
   rewrite with no gain, licence-incompatible, or evasion-oriented.
8. The highest-value additions are cheap: per-target timeouts, trace on failure,
   CDP resource blocking, context recycling, and one HAR fixture per book.
