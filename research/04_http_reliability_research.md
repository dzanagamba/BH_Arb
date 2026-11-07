# HTTP client & reliability libraries for a polite odds scanner

**Research date:** 2026-11-07. Versions, release dates and stars were read the same day from
PyPI's JSON API (`https://pypi.org/pypi/<name>/json`) and the GitHub REST API. Stars are
approximate and will move.

**Scope.** The scanner scrapes public bookmaker JSON APIs and a few pages, must not log in,
place bets, or evade rate limits/anti-bot systems. Tools whose value proposition is
fingerprint spoofing, captcha solving, proxy rotation for evasion, or "bypassing bot
protections" are reported but **out of scope** and are never recommended.

## Snapshot (2026-11-07)

| Library | Latest | Released | Stars | License | Python | Async | Verdict |
|---|---|---|---|---|---|---|---|
| scrapy | 2.20.0 | 2026-11-06 | 65.3k | BSD-3 | >=3.11 | via Twisted/asyncio | borrow patterns |
| scrapy-playwright | 0.0.48 | 2026-07-10 | 1.5k | BSD-3 | >=3.10 | yes | borrow (only with Scrapy) |
| crawlee | 1.11.1 | 2026-11-05 | 9.7k | Apache-2.0 | >=3.10 | yes | borrow patterns |
| crawl4ai | 0.9.5 | 2026-10-14 | 87.0k | Apache-2.0 | >=3.10 | yes | avoid |
| httpx | 0.28.1 | 2024-12-06 | 15.7k | BSD-3 | >=3.8 | yes | **adopt (already used)** |
| httpx-retries | 0.6.0 | 2026-07-06 | 77 | MIT | >=3.10 | yes | optional |
| hishel | 2.0.0 | 2026-11-05 | 418 | BSD-3 | >=3.10 | yes | avoid for odds |
| respx | 0.23.1 | 2026-04-08 | 845 | BSD-3 | >=3.8 | yes | **adopt (tests)** |
| pytest-httpx | 0.36.2 | 2026-04-09 | 455 | MIT | >=3.10 | yes | alternative |
| aiolimiter | 1.3.0 | 2026-09-07 | 789 | MIT | >=3.10 | async only | **adopt** |
| httpx-ratelimiter | 0.0.6 | 2024-06-11 | n/a | n/a | ~3.9 | yes | avoid |
| curl_cffi | 0.17.0 | 2026-10-26 | 6.8k | MIT | >=3.10 | yes | **out of scope** |
| tenacity | 9.2.1 | 2026-10-07 | 8.8k | Apache-2.0 | >=3.10 | yes | adopt/alt |
| stamina | 26.1.0 | 2026-04-13 | 1.5k | MIT | >=3.10 | yes | **adopt** |
| backoff | 2.2.1 | 2022-10-05 | 2.7k | MIT | >=3.7,<4 | yes | **avoid (archived)** |
| urllib3 | 2.8.0 | 2026-09-15 | 4.1k | MIT | >=3.10 | no | borrow semantics |
| pyrate-limiter | 4.5.1 | 2026-10-20 | 531 | MIT | >=3.10 | yes | optional |
| limits | 5.8.0 | 2026-02-05 | 653 | MIT | >=3.10 | yes | optional (multi-process) |
| throttled-py | 3.5.0 | 2026-08-30 | 651 | MIT | >=3.10 | yes | optional |
| pybreaker | 1.4.1 | 2025-09-21 | 701 | BSD-3 | >=3.9 | sync (+Tornado) | borrow/avoid |
| aiobreaker | 1.2.0 | 2021-05-17 | 30 | BSD-3 | >=3.6 | asyncio | **avoid (abandoned)** |
| purgatory | 3.0.1 | 2024-11-02 | 5 | MIT | >=3.9 | yes | avoid (niche) |
| circuitbreaker | 2.1.3 | 2025-03-31 | 521 | BSD-3 | unset | yes | optional |
| otel-instr-httpx | 0.66b2 | 2026-10-29 | 1.1k* | Apache-2.0 | >=3.10 | yes | defer |
| prometheus-client | 0.26.0 | 2026-07-24 | 4.4k | Apache-2.0 + BSD-2 | >=3.9 | sync | avoid (in-house) |
| structlog | 26.1.0 | 2026-06-06 | 5.0k | MIT/Apache | >=3.10 | sync | avoid (in-house) |

\* OpenTelemetry monorepo stars, not per-instrumentation.

## What the project already does

- `httpx==0.28.1` and `playwright==1.61.0` are pinned (`requirements.txt:3`, `:6`).
- Each direct-API scraper creates its own `AsyncClient` with only a timeout and
  `verify=VERIFY_SSL`: `scrapers/sportplus.py:237`, `scrapers/mdshop.py:109`,
  `scrapers/mbet.py:578`, `scrapers/premier_kladionica.py:152`, `scrapers/evlbet.py:69`,
  `scrapers/maxbet.py:362`, `scrapers/betole.py:175`. No shared pool, HTTP/2, or limits.
- The only shared retry helper is `scrapers/base.py:148-177`: 3 attempts, `0.5 * 2**n`
  sleep, retries only `status >= 500` and transport exceptions. **429 is not retried**
  (`:164`), `Retry-After` is ignored, and there is no jitter.
- `scrapers/wwin.py:270` adds a private `Semaphore(6)` and its own retry loop at `:276-306`
  that treats any non-200 as retryable and returns `[]` on final failure, so a blocked feed
  and an empty feed look the same to the caller.
- Cost accounting is per attempt in `fetch_with_retry` (`scrapers/base.py:163,170`) and
  implemented in `scrapers/cost.py:89-101`; outcome classification already has a
  `blocked` bucket (`scrapers/cost.py:16-27,105+`).
- There is a dependency-free Prometheus text registry and JSON log formatter in
  `server/observability.py:143` and `:218-282`, plus `/api/metrics`.
- No `asyncio.timeout()`/`wait_for()` wraps a book scan anywhere in `scrapers/`, `engine/`
  or `server/` (grep, 2026-11-07).

## 1. Frameworks

**Scrapy 2.20.0** (2026-11-06, 65.3k stars, BSD-3, Python >=3.11) is the reference
implementation of polite crawling. AutoThrottle adjusts per-domain delay from observed
latency, targeting `AUTOTHROTTLE_TARGET_CONCURRENCY` (default 1.0) with start delay 5 s and
max delay 60 s (`scrapy/settings/default_settings.py:255-259`; docs
https://docs.scrapy.org/en/latest/topics/autothrottle.html). RetryMiddleware defaults to
`RETRY_TIMES = 2` and `RETRY_HTTP_CODES = [408, 429, 500, 502, 503, 504, 522, 524]`
(`scrapy/settings/default_settings.py:598-600`), with jittered download delay
(`DOWNLOAD_DELAY_JITTER = 0.5`, `:319`), disk-backed request queues/JOBDIR resume, and a
stats collector. It does **not** honour `Retry-After`: `process_response` only checks the
status code (`scrapy/downloadermiddlewares/retry.py:158-169`). Verdict: **borrow patterns,
do not adopt.** The project's value is in 11 hand-written per-book adapters returning
`Market` objects plus per-book cost accounting; expressing them as spiders means a rewrite,
a second scheduler/queue model, and Twisted/asyncio-reactor integration next to FastAPI.
Keep the adapter call graph; copy the per-domain throttle, retry-code list, jitter and stats
ideas.

**scrapy-playwright 0.0.48** (2026-07-10, 1.5k stars, BSD-3) is a download handler that
runs selected requests through Playwright while leaving scheduling and item processing to
Scrapy (https://github.com/scrapy-plugins/scrapy-playwright). It is the right bridge *if*
Scrapy were adopted, and its context/max-pages settings are a good model for browser
reuse. It adds no stealth by itself; recommendation only applies inside a Scrapy adoption.
Verdict: **borrow the context-reuse pattern, do not add.**

**Crawlee for Python 1.11.1** (2026-11-05, 9.7k stars, Apache-2.0, Python >=3.10) has the
strongest reliability toolbox of the three: `AutoscaledPool`, persistent request queue,
`SessionPool` with rotation and persistence, per-request retries, `max_requests_per_crawl`,
statistics, and `AdaptivePlaywrightCrawler` (HTTP first, browser fallback). But its defaults
are explicitly anti-bot: `retry_on_blocked=True` is documented as "the crawler attempts to
bypass bot protections automatically", and `max_session_rotations=10` rotates sessions on
blocks (`src/crawlee/crawlers/_basic/_basic_crawler.py:153,170,293-296,343`); the README
markets crawling that will "fly under the radar of modern bot protections". Using it with
those defaults would violate the project's stated policy, and disabling them removes much of
its value. Verdict: **borrow the autoscaled-concurrency, queue-persistence and
HTTP-then-browser ideas; do not adopt.**

**Crawl4AI 0.9.5** (2026-10-14, 87.0k stars, Apache-2.0) is an LLM-oriented
markdown/structured-extraction crawler with a browser pool and caching. `BrowserConfig`
exposes `enable_stealth` and proxy configuration
(https://github.com/unclecode/crawl4ai/blob/main/docs/md_v2/core/browser-crawler-config.md),
and the project is optimised for page-to-markdown, not JSON APIs. Verdict: **avoid** —
wrong problem shape plus stealth features out of scope.

## 2. httpx ecosystem

**httpx 0.28.1** (2024-12-06, 15.7k stars, BSD-3, Python >=3.8) remains the latest stable
release. The 1.0 line exists only as pre-releases: `1.0.dev1`…`1.0.dev6` on PyPI (latest
2026-08-31) and a `1.0.0.beta0` git tag; `CHANGELOG.md` has only an `UNRELEASED` section
that drops Python 3.8 and exposes `FunctionAuth`
(https://github.com/encode/httpx/blob/master/CHANGELOG.md). The repository is active
(pushed 2026-10-02, 140 open issues) but the stable release has not moved in ~23 months.
httpx itself provides sync/async clients, connection pooling with `httpx.Limits`,
per-phase `httpx.Timeout`, event hooks, and transports, but **no retry policy and no rate
limiter** (https://www.python-httpx.org/advanced/resource-limits/). Verdict: **keep and
use**; do not chase 1.0 dev builds. Watch **httpx2 2.16.0** (2026-10-21, pydantic
continuation of httpx, Python >=3.11, https://github.com/pydantic/httpx2) as a possible
future migration, not for this task.

**httpx-retries 0.6.0** (2026-07-06, 77 stars, MIT) is a `RetryTransport` for sync and async
clients, explicitly listed by httpx as a third-party plugin
(https://www.python-httpx.org/third_party_packages/). Its `Retry` defaults are sensible for
this project: retry methods exclude POST, status forcelist `[429, 502, 503, 504]`,
transport exceptions `TimeoutException/NetworkError/RemoteProtocolError`,
`respect_retry_after_header=True`, full jitter, `max_backoff_wait`, `total_timeout`
(https://github.com/will-ockmore/httpx-retries/blob/main/httpx_retries/retry.py). Caveat:
retries happen inside the transport, so the project's `record_request` and outcome
classification would count one logical request and miss every retry — a regression for the
N1-3 cost metrics. Verdict: **optional** if attempt accounting is moved into an event hook
or transport wrapper; otherwise not. A second option, `httpx-retry` (2025.4.23, MIT,
https://github.com/mharrisb1/httpx-retry), takes a middleware approach but has not released
in ~18 months and has no advantage over httpx-retries; ignore it.

**hishel 2.0.0** (2026-11-05, 418 stars, BSD-3) implements RFC 9111 HTTP caching for httpx,
requests and ASGI, with sync/async, SQLite/Redis storage and TTL/TTI controls
(https://github.com/karpetrosyan/hishel). Caching odds is wrong: prices are the product and
must be fresh; conditional GET would also hide feed outages. Verdict: **avoid for market
data**; acceptable only for static reference payloads (team lists, sport trees) with an
explicit short TTL.

**respx 0.23.1** (2026-04-08, 845 stars, BSD-3) mocks httpx at the transport/router level,
supports sync/async and call assertions, and is listed by httpx
(https://lundberg.github.io/respx/). **pytest-httpx 0.36.2** (2026-04-09, 455 stars, MIT) is
a simpler pytest fixture for the same job. The test suite currently has no HTTP mocking
library (grep for respx/pytest-httpx/MockTransport finds none), so adapter tests either hit
the network or use ad-hoc fakes. Verdict: **adopt respx** for new adapter tests; pytest-httpx
is an acceptable lighter alternative, but pick one.

**aiolimiter 1.3.0** (2026-09-07, 789 stars, MIT, Python >=3.10) is a small asyncio leaky
bucket: `AsyncLimiter(rate, period)` used as `async with limiter:`. Single-process,
monotonic-clock based, no persistence, no Redis (https://github.com/mjpieters/aiolimiter).
That matches one scan process with a per-book limit. Verdict: **adopt**.

**httpx-ratelimiter 0.0.6** (2024-06-11) is a thin `LimiterTransport` wrapper around
pyrate-limiter (https://github.com/CralixRaev/httpx_ratelimiter); it has had no release in
~29 months and its rate limit applies transport-wide rather than per book. Verdict:
**avoid**; aiolimiter + pyrate-limiter cover the same ground with current releases.

**curl_cffi 0.17.0** (2026-10-26, 6.8k stars, MIT) is a libcurl binding whose selling point
is impersonating browser TLS/JA3 and HTTP/2 fingerprints, with links to JS-challenge
solving ("If you are blocked … impersonate", https://github.com/lexiforest/curl_cffi). This
is evasion tooling. Verdict: **out of scope; do not use.**

## 3. Retry / backoff

**tenacity 9.2.1** (2026-10-07, 8.8k stars, Apache-2.0, Python >=3.10) is the
general-purpose standard: decorators, stop/wait/retry conditions, sync+async, context
manager form. It is unopinionated, so every project re-invents jitter and total-time budgets
(https://tenacity.readthedocs.io/). Verdict: **adopt only if you want full control**;
otherwise prefer stamina.

**stamina 26.1.0** (2026-04-13, 1.5k stars, MIT, Python >=3.10) is an opinionated wrapper
over tenacity with the right defaults: retry only named exception types, exponential backoff
with jitter, both attempt and total-time limits, automatic async (including Trio), type-hint
preservation, a testing switch to disable retries, and built-in Prometheus/structlog/logging
instrumentation when those packages are installed. Its `on=` hook may return a custom
backoff in seconds or a `timedelta`, explicitly for `Retry-After`
(https://stamina.hynek.me/en/stable/tutorial.html). Verdict: **adopt** — it fits the
per-attempt accounting model because the decorated function still runs once per attempt.

**backoff 2.2.1** (2022-10-05, 2.7k stars, MIT) is **archived on GitHub since 2024-05-02**
and has had no release since 2022. Verdict: **avoid**; do not add it to new code.

**urllib3 Retry 2.8.0** (2026-09-15, 4.1k stars, MIT) is mature and has the semantics worth
copying: `total`, `connect/read/status` budgets, `status_forcelist`, `backoff_factor`,
`backoff_jitter`, and `Retry-After` handling. It only works with urllib3/requests, not
httpx. Verdict: **borrow the semantics** (not the dependency); httpx-retries is the closest
port.

## 4. Rate limiting

**aiolimiter** — see above. Best fit for a single async scan process; per-book instance,
acquire once per HTTP attempt, keep the limit conservative (start ~1–2 req/s, burst 2) and
tune from 429s and latency.

**pyrate-limiter 4.5.1** (2026-10-20, 531 stars, MIT, Python >=3.10) supports exact sliding
window, fixed window and GCRA/token bucket, multiple simultaneous rates, per-key buckets,
and in-memory/SQLite/Redis/Postgres backends with sync and async APIs
(https://github.com/vutran1710/PyrateLimiter). Verdict: **optional**; adopt only if limits
must survive restarts or be shared across processes.

**limits 5.8.0** (2026-02-05, 653 stars, MIT, Python >=3.10) offers fixed/sliding/moving
window strategies over Redis/Memcached/MongoDB with identical sync and async APIs
(https://limits.readthedocs.io/). It is the right choice if the API server and scan worker
must share budgets; overkill for one process. Verdict: **optional, multi-process only.**

**throttled-py 3.5.0** (2026-08-30, 651 stars, MIT, Python >=3.10) has five algorithms,
memory/Redis stores, sync+async and FastAPI integration
(https://github.com/ZhuoZhuoCrayon/throttled-py). Active and capable, but a larger API
surface and less Western adoption than aiolimiter. Verdict: **optional**, no advantage here.

## 5. Circuit breakers and bulkheads

**pybreaker 1.4.1** (2025-09-21, 701 stars, BSD-3) is thread-safe and mature, with failure
thresholds, reset timeouts, listeners, generator support and optional Redis, but async
support is limited to Tornado (`https://github.com/danielfm/pybreaker`). In an asyncio
scanner it would count coroutine creation, not awaited failures, unless every call is
wrapped. Verdict: **borrow the state machine, do not adopt.**

**aiobreaker 1.2.0** (2021-05-17, 30 stars) is an asyncio fork of pybreaker last pushed in
2022. Verdict: **avoid (abandoned).**

**purgatory 3.0.1** (2024-11-02, 5 stars, MIT) is asyncio-native with sync support and a
clean API (https://github.com/mardiros/purgatory), but has a five-star community and last
commit 2025-07. Verdict: **avoid for production**; too little maintenance surface.

**circuitbreaker 2.1.3** (2025-03-31, 521 stars, BSD-3) supports sync and async decorators
with the classic 5-failure/30-second defaults
(https://github.com/fabfuel/circuitbreaker). The ergonomic `@circuit` decorator keeps state
per decorated function; per-book breakers must use the class form. Maintenance has been
quiet for ~20 months. Verdict: **optional**; the class form works but gives no scan-level
integration.

**Recommendation:** write a ~50-line per-book async breaker (closed → open on N consecutive
transport/5xx/429 failures, cooldown, one half-open probe, reset on success), driven by the
outcomes `scrapers/cost.py` already classifies. It keeps state where the scanner needs it and
adds a gauge for `/api/metrics`. For bulkheads, use `asyncio.Semaphore` per book (already the
pattern in `scrapers/wwin.py:270`) and `asyncio.timeout()` (Python 3.11, stdlib) around each
book adapter; `anyio` is not needed and would introduce a second concurrency model.

## 6. Observability

**opentelemetry-instrumentation-httpx 0.66b2** (2026-10-29, Apache-2.0) instruments httpx
and httpx2 clients with spans, supports instrumenting all or individual clients, and is
still a beta 0.x instrumentation
(https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation/opentelemetry-instrumentation-httpx).
It is useful only with a collector/backend and adds context-propagation overhead. Verdict:
**defer**; use it if the scanner joins an existing OTel deployment.

**prometheus-client 0.26.0** (2026-07-24, 4.4k stars, Apache-2.0) is the official client with
counters/gauges/histograms and a multiprocess mode. This project already renders the
Prometheus text format itself (`server/observability.py:218-282`) and exposes `/api/metrics`,
so adding the dependency duplicates a working, tested subsystem. Verdict: **avoid**; add
retry/breaker/429 counters to the existing registry.

**structlog 26.1.0** (2026-06-06, 5.0k stars, MIT/Apache-2.0) provides structured,
contextvar-aware logging with JSON/logfmt renderers. The project already has
`JsonLogFormatter` with request/scan ids (`server/observability.py:143+`). Verdict:
**avoid**; borrow field conventions if richer logs are wanted.

## Recommended minimal stack

| Concern | Choice | Reason |
|---|---|---|
| HTTP | `httpx==0.28.1` (existing), one `AsyncClient` per book, explicit `Limits` + `Timeout` | Already the stack; no stable 1.0; a client per book keeps cookies/connections isolated |
| Retry | `stamina` around one accounted `fetch_once()` | Jitter, attempt + total budget, async, `Retry-After` via backoff hook, retries stay visible to `record_request` |
| Rate limit | `aiolimiter.AsyncLimiter` per book, acquired per attempt | Tiny, async-native, exactly the per-host politeness needed |
| Breaker | ~50-line per-book async breaker | Avoids sync-only pybreaker and abandoned aiobreaker; state fits scan accounting |
| Timeout | `asyncio.timeout()` around each book adapter | Stdlib 3.11; closes the "scan hangs forever" gap |
| Tests | `respx` | Transport-level httpx mocking, sync+async, listed by httpx |
| Logs/metrics | keep in-house `server/observability.py` | Prometheus text + JSON logs already exist; add retry/429/breaker counters |

No framework, no hishel, no prometheus-client, no structlog, no OTel, no curl_cffi.

Sketch of the integration point (not implemented):

```
async def fetch_once(client, url, *, limiter, breaker, **kw) -> httpx.Response:
    async with limiter:                       # aiolimiter, per book
        breaker.before_call()                 # raises CircuitOpen -> outcome "blocked"
        try:
            resp = await client.get(url, **kw)
        finally:
            record_request(...)               # one count per network attempt
        if resp.status_code in RETRY_STATUS:  # 408/429/5xx
            resp.raise_for_status()
        breaker.on_success()
        return resp
# stamina.retry(on=..., attempts=3, timeout=30) wraps fetch_once
```

## Risks and uncertainties

1. **httpx release stall.** Stable 0.28.1 is from 2024-12; 1.0 is dev-only and httpx2 is a
   new fork. Pin 0.28.1, run `pip-audit`, and review the 1.0/httpx2 split before any upgrade
   (https://github.com/encode/httpx/releases, https://github.com/pydantic/httpx2).
2. **Retrying multiplies load.** With N books × 3 attempts, a bad night can triple request
   volume. Budget retries per scan and cap total sleep; prefer breaker-open over retrying a
   dead feed.
3. **`Retry-After` can be huge.** Honour it but cap it (e.g. 60 s) and count it as a
   `blocked` outcome so the scanner backs off instead of hammering.
4. **Transport-level retries hide attempts.** Any `RetryTransport` solution must be paired
   with attempt-level accounting, or the cost metrics (`scrapers/cost.py`) will understate
   real load.
5. **Existing browser code conflicts with the stated policy.** `launch_browser()` sets
   `--disable-blink-features=AutomationControlled` and patches `navigator.webdriver`,
   plugins and `window.chrome` (`scrapers/base.py:31-55`). That is anti-bot evasion; it is
   not part of any recommendation here and should be reviewed separately if the policy is
   to be enforced in code.
6. **Unknown per-book limits.** No book publishes a quota; the initial aiolimiter rates are
   guesses. Tune from 429 frequency, latency, and the existing `blocked` outcome counts.
7. **Framework star counts are not fit.** Scrapy/Crawlee are excellent, but adopting either
   would replace working adapters and the N1-3 cost model. This is a judgement from the
   code shape, not a benchmark.
8. **Coverage gaps.** I did not benchmark any library, did not inspect Scrapy's Twisted
   integration in this repo, and did not verify whether `stamina`'s `on=` predicate can see
   response headers directly (its documented escape hatch is the custom backoff hook). I
   also did not evaluate HTTP/2 or DNS behaviour.

## Conclusions

1. **Do not adopt a scraping framework.** Scrapy 2.20 and Crawlee 1.11 are healthy, but the
   adapter + per-book cost architecture is the project's asset; borrow autothrottle,
   retry-code lists, jitter and session-reuse patterns instead.
2. **The concrete reliability gap is retry policy, not the client.** `fetch_with_retry`
   never retries 429, ignores `Retry-After`, has no jitter, and `wwin.py` duplicates a
   weaker loop. Fix that before adding any framework.
3. **Keep httpx 0.28.1.** 1.0 is still dev-only (1.0.dev6, 2026-08-31); httpx2 is a watch
   item, not a migration.
4. **Add one polite limiter per book** (`aiolimiter`); today there is no rate limiting
   except `wwin`'s private `Semaphore(6)`.
5. **Use stamina for retries**, with a `Retry-After`-aware backoff hook; avoid archived
   `backoff` and skip `httpx-retries` unless attempt accounting is redesigned.
6. **Write the breaker yourself** (async, per book, ~50 lines). pybreaker is sync-only,
   aiobreaker is abandoned, and purgatory is too small a project to depend on.
7. **Observability is already solved in-house**; add retry/429/breaker counters to
   `server/observability.py` rather than adopting prometheus-client, structlog or OTel.
8. **Adopt respx for HTTP adapter tests**; the suite currently has no httpx mocking layer,
   which makes retry/limiter/breaker behaviour hard to test deterministically.
