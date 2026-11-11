# Acceptance record — 2026-11-03

This is the dated evidence behind the production-readiness claim. It is a
measurement, not a promise: every number below was produced by the command
named next to it.

## CI and replay

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest` | **1,177 passed** |
| Lint | `python -m ruff check .` | clean |
| Types | `python -m mypy .` | clean on 121 source files |
| Market doc | `python scripts/generate_market_mapping_doc.py --check` | in sync |
| Cold replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` | exit 0, fixed point |
| Seeded replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --seeded --check` | exit 0 |

The cold replay starts with an empty evidence ledger, learns from the frozen
corpus, and reaches a pass that adds no claim and changes no verdict. It has 0
false merges and 0 unresolved evidence-backed pairs.

## Cache payload (P0-1, 2026-11-04)

F1 was a pure payload bug: every `team_identity` record whose proof used the
alias allowlist persisted `sorted(alias_allowlist)` instead of the entry that
proved the pairing. The gate's decision was correct; the evidence was a copy of
configuration.

Measured on the frozen 2026-11-03 nine-book cache (`cache/last_scan.json`,
7,666 matches) by re-grouping the cached matches offline with the same gate:

| Metric | Before | After |
|---|---:|---:|
| Cache file | **218.5 MB** | **23.3 MB** |
| Match-group JSON (compact) | 127.8 MB | **7.3 MB** |
| Match-group JSON (indented) | 178.8 MB | 11.1 MB |
| Allowlist evidence records | 1,288 | 63 |
| Allowlist entries persisted | 4,292,904 | **118** |
| Largest record | 3,333 entries | **4 entries** |
| Cache parse time | 2.62 s | **0.58 s** |

The post-fix cache is written as compact JSON (it is a machine file, not
hand-edited config), so the group JSON occupies its 7.3 MB compact form. A
differential run with the previous evidence behavior produced the **same 1,237
group signatures and statuses**, so the gate's decisions did not change.

`/api/health` now reports `cache.prematch_bytes`, `cache.live_bytes`,
`cache.budget_bytes` (default 40 MB, `CACHE_SIZE_BUDGET_BYTES`) and
`cache.over_budget`; `_save_cache` logs a warning over budget.

Regression tests:
`tests/test_certainty.py::test_allowlist_evidence_records_only_the_proving_entry`
and `tests/test_cache_serialization.py::test_cached_group_payload_is_bounded`.


## Runtime freshness (P0-4, 2026-11-04)

F3 was a different failure from a stale cache file: the cache was bounded and
restored correctly, but a running server kept serving `last_scan.json` without a
hard stale state, so the dashboard could present hours-old prices as current.

The policy is now explicit and shared by the engine, the API and the dashboard:

- Prematch prices expire after `ODDS_TTL_SECONDS` (600 s); live prices after
  `LIVE_ODDS_TTL_SECONDS` (60 s).
- `/api/results` returns `freshness` with `mode`, `scan_time`, `age_sec`,
  `ttl_sec`, `stale`, `state`, `stale_books`, and a `per_book` map carrying each
  book's oldest/newest `fetched_at`, ages, missing-timestamp count and stale
  flag. `/api/health` exposes the same block for both feeds.
- A stale feed keeps its cached rows for diagnosis but is labelled historical.
  The dashboard shows an alert banner, marks rows as stale, and disables copy
  actions. **Re-check odds** stays enabled: `POST /api/verify` is still the only
  path that re-establishes a leg's current price.
- Each `SurebetStake` now carries its own `fetched_at`, so the slip can show the
  age of the exact leg being placed instead of only the group's oldest fetch.

A book with no timestamp, or a scan with no completed run, is treated as stale:
silence is not proof of freshness. The test matrix covers fresh, near-expiry,
past-TTL, one stale book among fresh ones, live's tighter TTL, never-scanned,
missing timestamps, and per-leg fetch times.

Tests: `tests/test_freshness_api.py`, `tests/test_frontend_freshness.py`.

## Reloadable deep-link declarations (P0-5, 2026-11-04)

F5 was an operator trap: `_deeplink_cache` was populated once and never
invalidated, so editing `config/bookmaker_deeplinks.json` had no effect until a
process restart, and the gate kept using the old declarations invisibly.

The loader now keeps the file's `(mtime_ns, size)` signature. It reloads on the
next declaration lookup when the signature changes, so a scan, a verify, or a
health call uses the edited map without a restart. The fallback direction is
unchanged: a missing or malformed file clears the cache, which makes every book
block rather than inherit trust from a stale map.

`/api/health` reports `deep_link_declaration_source` with `loaded_at`,
`source_mtime`, `current_mtime`, `source_size`, `stale` and `error`. Each entry
in `deep_link_declarations` also carries `loaded_at`, `source_mtime` and `stale`,
so the map the gate is using is distinguishable from the file on disk.

Tests: `tests/test_deeplinks.py` (change without restart, malformed fail-safe,
recovery after fixing the file, health reporting) and
`tests/test_candidates_api.py` (health source fields).

## Opportunity-rate and arb-lifetime telemetry (P0-6, 2026-11-04)

F13 was the missing denominator: the dashboard reported groups and surebets but
could not say whether a zero-surebet scan saw no crossing, saw crossings that
failed the gates, or priced only stale data.

`engine/opportunity_metrics.py` observes every board the real pricing pass
evaluates. A board is one event + market + line + period + settlement with the
best cross-book combination; the observation is taken before the display
filters, so a below-floor crossing and a price-guard drop are still counted.
`/api/results` and `/api/health` report:

| Field | Meaning |
|---|---|
| `boards` | Market instances the engine actually priced |
| `crossed` | Boards with implied sum below 1.0 |
| `crossed_above_floor` | Crossings at or above `DUST_PROFIT_PERCENT` (0.2%) |
| `actionable` | Surebets kept after the price guard |
| `crossing_rate_percent` | `crossed / boards` |
| `floor_crossing_rate_percent` | `crossed_above_floor / boards` |
| `actionable_rate_percent` | `actionable / boards` |
| `median_margin`, `best_margin` | Median/minimum implied sum across boards |
| `zero_result_reason` | `actionable`, `no_crossing`, `crossing_below_floor`, `crossing_guarded`, `stale_data`, `expired_data`, `unverified_data`, or `no_priced_boards` |
| `lifetime` | p50/p90 seconds, sample count and live count |

Crossing keys are `event + market + line + period + settlement`; each record
keeps `first_crossed_at`, `last_crossed_at`, `last_seen_at` and
`disappeared_at`. The store is bounded to 5,000 keys and a 7-day retention.
Only aggregates, the crossing-key map, and one compact aggregate row per scan
are persisted; the full board is not duplicated.

The dashboard adds a **Crossing rate** tile and shows the actionable count or
the zero-result reason beneath it. `scripts/opportunity_baseline.py --days 7`
renders the aggregate report; the dated baseline is
`docs/evidence/2026-11-04-opportunity-rate-baseline.md`.

Tests: `tests/test_opportunity_metrics.py` (no crossing, below-floor crossing,
above-floor actionable, stale group, disappearance, bounded keys, API exposure,
and aggregate-only persistence).

## Feed integrity and stale-book quarantine (P0-7, 2026-11-04)

F14 was the phantom-arb path the per-surebet price guard could not close: a book
can be stale, suspended or internally broken and still quote the "best" price on
the next group.

Every enabled book now gets a per-scan scorecard in `feed_integrity` on
`/api/results` and `/api/health`:

| Metric | Evidence |
|---|---|
| Freshness | Oldest `fetched_at` for the book against the feed TTL |
| Empty/parse failure | Scraper progress and per-book error text |
| Missing markets | Market families at least two peer price sources publish but the book omits |
| Own-margin sanity | Complete sets whose own implied sum is below 1.0 |
| Outlier rate | Outlier rows from `find_outliers` over comparable complete markets |
| Last success | Last scan in which the book returned data without a parse failure |

States are `healthy`, `degraded` and `quarantined`, with machine-readable
`reasons` and the metric evidence. A stale, empty, parse-failed, below-1.0 or
high-outlier-rate book is quarantined. Outlier-rate quarantine needs at least 10
comparable markets, because in a three-book group the book supplying a real edge
is always the median "outlier"; below that sample it is a degradation warning,
not a quarantine.

Quarantine is enforced by removing that book from the group copies passed to
`find_surebets` and the price guard. The original group, its evidence and the
certainty verdict are untouched: a subset of a proved group is still the same
event, and identity decisions never consult integrity state. The dashboard
shows the unhealthy book and its reason and marks a quarantined book
`not priced`.

Recovery is automatic but not immediate: a quarantined book remains out of
pricing until three consecutive fully healthy scans. The scorecard keeps a
bounded last-20-state history per book in `cache/feed_integrity.json`.

Tests: `tests/test_feed_integrity.py` (stale book cannot supply a leg, a broken
own set is quarantined, recovery needs consecutive clean scans, the gate's group
is unchanged, every enabled book has a state/reason, and both APIs expose the
scorecard).

## Bounded group-evidence API and dashboard drill-down (P1-1, 2026-11-04)

`/api/debug/report` used to return every group and every evidence record. After
P0-1 the payload was no longer 179 MB, but it was still unbounded and could
freeze a browser tab.

The evidence API is now split:

| Endpoint | Behaviour |
|---|---|
| `GET /api/groups?mode=&status=&sport=&search=&limit=&offset=` | Bounded summaries (default 50, max 200); evidence stripped, reason codes kept |
| `GET /api/groups/{group_id}?mode=` | Exactly one group with its full evidence and bookmaker legs; 404 for an unknown id |
| `GET /api/debug/report?mode=&limit=&offset=` | Compatibility alias with the same low default limit, plus a `deprecated` note |

The dashboard adds an **Evidence** tab: filters and paging call `/api/groups`,
and selecting a row fetches only `/api/groups/{id}`. The layout wraps on narrow
screens. No dedicated URL or history entry is created, so the Diagnostics tab's
"no dedicated URL" contract is unchanged.

Tests: `tests/test_groups_api.py` (default page size, filters, offset, exact
detail and 404, summary size without evidence, compatibility alias, live mode)
and `tests/test_frontend_evidence.py` (tab, endpoints, filter reload, narrow
layout hooks).

## Structured logs, request IDs and metrics (P1-2, 2026-11-04)

An unattended scanner needs to answer two questions from a distance: *which
request failed?* and *is the feed actually working?* Neither had a durable
answer before: logs were unstructured text and the only counters were in
`/api/health`.

**Correlation.** `server/observability.py` keeps a request id and a scan id in
context variables. `server/app.py` accepts `X-Request-ID` when it is short and
log-safe (`^[A-Za-z0-9._:-]{1,128}$`) and generates one otherwise, then returns
it on every response, including 401/403. A log-record factory stamps both ids on
every record, so pytest capture, uvicorn and operator handlers all see them.
`run_scan` creates a `scan_id` and publishes it for the duration of the scan.

**Structured logs.** `LOG_FORMAT=json` switches the root handler to
`JsonLogFormatter`; anything else keeps `req=<id>` in the text line. The JSON
formatter serialises only a fixed allowlist of extras, so an accidental
`extra={"api_key": ...}` or an odds payload cannot leak into the log. A
completed scan emits exactly one `scan complete` record with `mode`,
`duration_seconds`, `books`, `books_total`, `groups`, `surebets`, `drops` and
`cache_bytes`; a failure emits `scan failed` with the traceback.

**Metrics.** `GET /api/metrics` renders Prometheus text with no extra
dependency. The registry exposes:

| Metric | Type | Meaning |
|---|---|---|
| `bh_scans_started_total{mode}` | counter | Scans entered |
| `bh_scans_completed_total{mode}` | counter | Scans that reached the end |
| `bh_scans_failed_total{mode}` | counter | Scans that raised |
| `bh_scan_duration_seconds{mode}` | gauge | Last completed scan duration |
| `bh_scan_seconds_total{mode}` | counter | Cumulative scan seconds |
| `bh_book_results_total{mode,book,outcome}` | counter | `success`, `empty`, `error`, `skipped` |
| `bh_book_kinds_total{mode,book,kind}` | counter | SR2-1 kind: `ok`, `empty`, `blocked`, `rate_limited`, `timeout`, `transport`, `upstream_5xx`, `parse_error`, `schema_drift`, `skipped` |
| `bh_surebets_found{mode}` / `_total` | gauge / counter | Last and cumulative surebet count |
| `bh_surebets_dropped_total{mode,reason}` | counter | Price-guard drops |
| `bh_link_checks_total{mode,book,outcome}` | counter | Deep-link checks (`verified`, `failed`, `errored`) |
| `bh_candidate_queue_size{mode}` | gauge | Review queue after the scan |
| `bh_cache_size_bytes{mode}` | gauge | Persisted scan cache |
| `bh_last_scan_age_seconds{mode}` | gauge | Age of the last completed scan |
| `bh_browser_slots_in_use` | gauge | Playwright slots held against `BROWSER_CONCURRENCY` |
| `bh_rss_bytes` | gauge | Process resident memory |

Zero-valued series are registered at import so a fresh process is scrapable
immediately. `/api/metrics` is subject to the same API-key guard and
`_require_api_key` dependency as the other routes.

Tests: `tests/test_request_id.py` (echo, generate, hostile/oversized header,
id on a refused request, context filter, JSON formatter allowlist, traceback,
`LOG_FORMAT=json`) and `tests/test_metrics.py` (text escaping, endpoint without
a server, API-key protection, one structured scan-completion record, counters,
per-book empty/error outcomes, failed-scan counter).

## Raw-price invariant and rounding audit (P1-7, 2026-11-04)

Every surebet now carries `raw_margin` (exact `sum(1/odds)`) and `realized`, a
`RoundingSummary` built from the stake rows actually served. `total_margin`
stays the four-decimal display value, so a reviewer can compare
`round(sum(1/odds), 4)` to it and use `raw_margin` for the exact check.

`POST /api/recalculate` recomputes from the served odds, accepts
`rounding: exact | 1 | 5`, and returns separate `exact` and `realized` blocks.
The legacy `guaranteed_return`/`guaranteed_profit` fields remain and are the
exact values, never disguised as realized ones.

The dashboard slip shows **exact profit**, **realized profit** and the
**rounding effect**. It also recomputes the margin from `sb.stakes` and blocks
the slip with a warning if the served odds do not reproduce `raw_margin` /
`profit_percent`; it does not silently trust a second calculation.

`tests/test_pricing_invariant.py` asserts the invariant for every surebet from a
real-shaped group, checks the rounded summary, exercises `/api/recalculate`, and
tampers with `total_margin` without changing the odds to prove the test fails
when a derived value moves.

## 24-hour soak (P1-6, waived by the operator on 2026-11-04; see `ROADMAP.md`)

The harness and resource guard are complete: `--cycles 0` now means "until
`--minutes`", samples carry cache bytes and per-book feed states, and any leaked
browser or RSS/cache budget breach fails `--check`. The two-cycle smoke run
(RSS 940.4 → 924.4 MB, 0 browsers, cache 31.2 MB) is in
[`docs/SOAK.md`](SOAK.md); it is not a substitute for the 24-hour run. The
acceptance boxes stay unchecked because the run was waived, not passed.

## Operator alerts (P1-5, 2026-11-04)

An unattended scanner had no way to say that a new edge appeared, a feed went
stale or a book kept failing. The new `server/alerts.py` decides what to say;
delivery is separate from the scan.

**Transports.** The default is `NullTransport`, so a checkout that configures
nothing sends nothing. `WebhookTransport` POSTs one JSON object;
`TelegramTransport` uses the Bot API. Both are built from environment values in
`configured_alert_manager()`. URLs and tokens are absent from `repr()`, logs and
`/api/health`; even a transport exception is logged by type only, because a
Telegram URL contains the bot token.

**Dedupe.** The signature is a hash of match, market, leg identities and a
one-point profit bucket. The odds are excluded so a tick inside the same bucket
does not re-alert. One window is `ALERT_DEDUPE_MINUTES` (default 60), held in
memory and reset on restart.

**Delivery.** A single daemon worker sends queued alerts with exponential
backoff (`ALERT_RETRY_ATTEMPTS`, default 3). A failure increments
`bh_alerts_failed_total` and the health counter; it cannot propagate into the
scan. `_notify_scan_alerts` is also wrapped as a second boundary.

**Triggers.** Surebets at or above `ALERT_MIN_PROFIT_PERCENT`, stale feed per
book, a quarantined or degraded book with its reasons, the scheduled-scan
backoff threshold, cache budget and RSS budget.

**Secrets.** `.env` / systemd environment only. `tests/test_alerts.py` uses a
fake transport that raises `RuntimeError("token=SUPERSECRET")` and asserts the
secret never reaches the log. A health test configures a webhook URL containing
`SECRET` and asserts it is not in the response.

## CI hardening (P1-4, 2026-11-04)

The unit-test job proved correctness but published no coverage number, and
nothing audited dependencies or scanned for dangerous constructs on each push.

**Coverage.** `[tool.coverage.run]` measures `engine`, `server`, `scrapers`,
`config` and `models` (8,096 statements; tests, operator scripts and generated
state excluded). The measured baseline is **81.55%**; `fail_under = 80` keeps a
small cushion below it rather than forcing low-value tests. *(Superseded 2026-11-11 by M6-1: coverage now counts branches, measured 88.05 %, `fail_under = 87.05`; see `docs/CI.md`.)* The Python 3.11 CI
test leg runs `pytest --cov`, prints the missing-line report, appends a markdown
summary to the workflow run page, and uploads `coverage.xml` as an artifact.

**Dependency audit.** `pip-audit` runs against `requirements.txt` and
`requirements-dev.txt` on every push and pull request. The first run found
`pytest 8.4.1` affected by `PYSEC-2026-1845` (fixed in `9.0.3`); the dependency
was upgraded and the full suite re-run rather than suppressing the advisory.

**Static scan.** Bandit runs at medium severity and above; low-severity
best-effort cleanup findings are visible but non-blocking. Three call sites
carry an inline, reasoned `# nosec`: the capture-only `verify=False` client
(`B501`) and two loopback/operator `urlopen` probes (`B310`). The SHA-1 review
queue id is not a security primitive and now passes `usedforsecurity=False`
instead of being allowlisted.

**Matrix.** Python 3.11 remains the required runtime. 3.12 runs the same suite
as a forward-compatibility check.

**Local reproduction** is documented in `docs/CI.md`; the README development
section lists the same commands.

## Reproducible deployment (P1-3, 2026-11-04)

A fresh Linux host had no shipped deployment path: the README described
`python main.py`, and the runtime state, browser install and non-root step were
all implicit.

**Docker.** `Dockerfile` builds from `python:3.11-slim`, installs
`requirements.txt`, runs `playwright install --with-deps chromium` into
`/ms-playwright`, copies the app owned by a non-root `scanner` user
(`BH_UID`/`BH_GID`, default `1000`), and exposes a `HEALTHCHECK` against
`/api/health`. `.dockerignore` keeps `.venv`, caches, git metadata, tests, docs
and secrets out of the context while retaining the tracked
`config/generated/bookmaker_markets.json`.

`docker-compose.yml` builds the image, publishes on loopback by default, mounts
`./cache:/app/cache` and `./config:/app/config`, runs with `read_only: true`,
`no-new-privileges`, a `/tmp` tmpfs and 1 GB `/dev/shm` for Chromium, and
declares the same health check. Environment values pass through
`${VAR:-default}` interpolation from `.env`.

**systemd.** `deploy/bh-arb.service` runs as `bh-arb`, uses an optional
`/etc/bh-arb.env`, restarts on failure, sends `SIGINT` for a graceful shutdown,
and hardens the unit with `ProtectSystem=strict`, `ProtectHome=true` and
`ReadWritePaths` limited to `cache/`, `config/generated/` and the alias
allowlist.

**Smoke test.** `scripts/docker_smoke.py` builds the image, starts it with a
named cache volume, polls `/api/health`, asserts `id -u` is non-zero, writes a
marker to `/app/cache`, restarts the container and verifies the marker survived.
`.github/workflows/docker.yml` runs the build and this smoke test on demand and
when deployment inputs change; it is deliberately separate from the fast unit
job because the Chromium layer dominates the build time.

**Backup/restore.** `docs/DEPLOYMENT.md` documents the trust inputs that must be
backed up together: `cache/` (scan caches, history, opportunity metrics, feed
integrity, deep-link verification/decision stores), the learned ledger
`config/generated/mapping_evidence.json`, the human alias allowlist, and edited
deep-link declarations.

Tests: `tests/test_deployment_assets.py` covers the Dockerfile's base image,
Playwright install, non-root user, health check; `.dockerignore` entries; the
Compose mounts/health/hardening; the systemd unit's non-root and write paths; the
smoke script's build/restart/uid markers; README copy-paste steps; backup list;
and the optional Docker workflow.

**Verification limit:** the image build and container smoke were not executed in
this session because the local Docker socket is not accessible to the session
user (`docker info` → permission denied; the user is not in the `docker` group).
The assets and the smoke script are validated offline, and the optional Docker
workflow runs exactly that build and smoke on a Docker-capable runner.

## Browser hardening

`server/app.py` sets `Content-Security-Policy` (`default-src 'self'`,
`object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`,
`connect-src 'self'`), `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` on the dashboard and
every API response. Every request gets a fresh CSP nonce; the dashboard's two
script tags (the pre-paint theme bootstrap and `/js/app.js`) are stamped with it
and `script-src` is `'self' 'nonce-…'` with no `'unsafe-inline'`.

The dashboard no longer ships or generates inline `on*` handlers or JSON inside
HTML attributes. Actions are `data-action` attributes read by one delegated
listener; copy buttons carry `data-copy`/`data-copy-message` values escaped for
attribute context. A scraped name such as
`O'Brien "X" <img src=x onerror=alert(1)>` stays text and its copy button passes
the exact string to the clipboard.

`style-src` also has no `'unsafe-inline'`: the dashboard sets colours and
progress widths as CSS custom properties through the CSSOM
(`element.style.setProperty`), not as inline style attributes, and no inline
`<style>` block is shipped. `style-src` is `'self'` plus the Google Fonts
stylesheet origin.

Tests: `tests/test_csp_nonce.py`, `tests/test_csp_styles.py`,
`tests/test_frontend_xss.py`.

## Soak

`python scripts/soak.py --cycles 10 --interval 5 --pid <server-pid> --check`:

| Sample | Matches | Groups | Surebets | RSS | Browsers | Errors |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6,497 | 1,046 | 5 | 726.4 MB | 0 | 1 |
| 10 | 6,493 | 1,046 | 5 | 897.9 MB | 0 | 1 |

Memory grew **23.6%** (limit 50%), no browser process survived a scan, and the
run passed `--check`.

`python scripts/soak.py --cycles 3 --interval 5 --pid <server-pid> --check`
on the final gate (including the pairing and CSP changes):

| Sample | Matches | Groups | Surebets | RSS | Browsers | Errors |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6,501 | 1,044 | 12 | 779.9 MB | 0 | 1 |
| 3 | 6,500 | 1,044 | 12 | 888.7 MB | 0 | 1 |

Memory grew **13.95%**, no browser process survived, and the run passed
`--check`.

`python scripts/soak.py --cycles 6 --interval 5 --pid <server-pid> --check`
on the final code (punctuation, expiry and CSP included):

| Sample | Matches | Groups | Surebets | RSS | Browsers | Errors |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6,397 | 1,037 | 9 | 755.2 MB | 0 | 0 |
| 6 | 6,397 | 1,037 | 9 | 870.5 MB | 0 | 0 |

Memory grew **15.27%**, no browser process survived, all six scans returned the
same 1,037 groups and 9 surebets, and the run passed `--check`.

After removing the cache's double JSON serialization, a three-cycle run started
at **626.4 MB** and ended at **782.6 MB** (24.9%), with 0 surviving browsers and
9–10 surebets per scan. The absolute high-water mark fell from 875 MB to 783 MB.

A ten-cycle run on the final matching code produced this RSS curve:

`592.8 → 701.7 → 760.4 → 758.5 → 757.5 → 796.0 → 768.4 → 767.4 → 767.4 → 767.4 MB`

It **plateaued at about 767 MB after cycle 7**, with 29.45% growth from the first
sample (limit 50%), 0 surviving browsers, 0 errors and 10–12 surebets per cycle.
The plateau is the important result: growth is not linear. The 24-hour run was
not performed. `docs/SOAK.md` records the P1-6 harness changes and a two-cycle
smoke run (RSS 940.4 → 924.4 MB, cache 31.2 MB, 0 browsers, both below budget);
P1-6 was waived by the operator on 2026-11-04 and is excluded, not passed (see
`ROADMAP.md`).
On the six-cycle soak's nine surebets, seven
re-verified at a fresh price (Najran–Jubbah, Anaitasuna–Alaves,
Zakynthos–Niki Volou, Manchester United–Roma, Roma–Sassuolo, Villarreal–PSG and
Mainz–Bayern); the two Boston United–Leicester U21 legs were gone on re-check and
are reported as gone.

## Real prematch scan (verified sample)

`python main.py`, then `POST /api/scan?mode=prematch` at **2026-11-03 04:39 UTC**.

| Metric | Value |
|---|---|
| Books returning matches | 9 / 9 enabled (Betole, MaxBet, MDShop, Admiralbet, MBet, SportPlus, Premier Kladionica, WWIN, Mozzartbet) |
| Matches | 6,492 |
| Verified groups | 1,043 |
| Listings in groups | 5,805 |
| Groups with all nine books | 126 |
| False merges (different Betradar ids in one group) | 0 |
| Price outliers | 3 (dropped with their surebets) |
| Surebets shown | 9 |

The price guard dropped three outlier legs: Kitakyushu–Reilac Shiga (MaxBet X2,
SportPlus 1) and Kanazawa–Parceiro N (SportPlus 1). The nine shown were
re-checked with `POST /api/verify`:

| Match | Market | Profit | Books | Re-check |
|---|---|---:|---|---|
| kanazawa – parceiro n | double chance | 8.28% | mdshop / mozzartbet | not found on fresh data |
| anaitasuna ft – alaves | BTTS | 1.69% | betole / maxbet | still profitable |
| boston united – leicester u21 | double chance | 1.52% | sportplus / wwin | not found on fresh data |
| villarreal – psg | 1X2 | 1.20% | mdshop / mozzartbet / wwin | still profitable |
| tochigi – fukushima | double chance | 0.51% | mdshop / mozzartbet | still profitable |
| bodo/glimt – lille | double chance | 0.49% | betole / maxbet | still profitable |
| atl madrid – bayern munich | double chance | 0.42% | mdshop / mozzartbet | still profitable |
| roma – sassuolo | double chance | 0.42% | mbet / mozzartbet | still profitable |
| tochigi – fukushima | 1X2 | 0.33% | mdshop / mozzartbet | still profitable |

Seven of nine re-verified at a fresh price; two disappeared before the re-check
and are reported as gone rather than as confirmed arbs.

The final-gate soak scan at **04:54 UTC** found **6,500 matches, 1,044 verified
groups and 12 surebets**, including `mainz – bayern munich` 1X2 at 0.27%, a
fixture that only paired after the anchor fix. The latest scan at **07:54 UTC** found **6,624 matches, 1,074 verified groups
and 11 surebets**. Pairing quality is now in the health payload: `/api/health`
and `/api/results` carry the same `pairing` summary the audit computes. The
06:30 verified sample had 10 surebets; eight re-verified at a fresh price and
the two Boston United–Leicester U21 legs were gone.

## Pairing coverage

`python scripts/pairing_audit.py --check` reads the same cache the dashboard
serves and exits non-zero when a same-fixture offer is left unpaired or a group
repeats a bookmaker.

| Metric | Value |
|---|---:|
| Matches | 6,624 |
| Verified multi-book groups | 1,074 |
| Listings in groups | 5,987 |
| Ungrouped listings | 637 |
| Duplicate listings from a book already in the group | 305 |
| Strict misses (same league, ±15 min, both teams ≥80% alike) | 22 |
| Strict miss rate | **0.33%** |
| Groups repeating a bookmaker | 0 |

Per-book grouping, including duplicate listings:

| Book | Grouped / matches | Rate |
|---|---:|---:|
| MDShop | 627 / 638 | 98.3% |
| Admiralbet | 627 / 638 | 98.3% |
| MBet | 634 / 659 | 96.2% |
| WWIN | 733 / 763 | 96.1% |
| SportPlus | 735 / 750 | 98.0% |
| Premier Kladionica | 767 / 855 | 89.7% |
| MaxBet | 759 / 839 | 90.5% |
| Betole | 843 / 1,147 | 73.5% |
| Mozzartbet | 262 / 335 | 78.2% |

The low Betole/Mozzartbet rates are mostly duplicate listings and leagues no
other book carries, not same-fixture misses: only 22 offers in the whole scan
have a strict counterpart in another book that the matcher failed to pair. The
remaining examples are abbreviations, transliterations and one-sided qualifiers
the veto correctly keeps apart, such as `Hamburger` / `Hamburger SV`,
`Enppi` / `Asyut Petrol`, `Chindia T.` / `Chindia Tar.`, and
`AFC Emley` / `Emley`.

### Gate fixes that produced this measurement

1. **The anchor is not the group.** A candidate was compared only with the
   group's first member, so a valid listing was rejected when that member used
   a different league spelling (`germany, bundesliga` beside seven
   `bundesliga` listings). The gate now checks the group's canonical league and
   every member's league, and clears an anchor-only mismatch when the group
   proves it.
2. **A group member can prove a team.** The same anchor-only problem hid a
   team spelling another member could prove (`A. Salzburg` beside
   `Austria Salzburg`). Orientation is now accepted from any member while a
   member supports the canonical fields.
3. **Club designators are not aliases.** `FC Liefering` / `Liefering` and
   `SV Austria Salzburg` / `Austria Salzburg` are accepted without a learned
   alias, but only when the canonical ids and the remaining spelling agree.
   `Atletico Madrid` / `Madrid` is explicitly not such a pair.
4. **Generic leagues get fingerprints.** `bundesliga` is too vague for a hard
   league id but its team set is what resolves it against
   `germany, bundesliga`. The learner now records generic fingerprints and the
   resolver compares canonical team ids, so `Mainz – Bayern` pairs across all
   nine books.
5. **Canonical punctuation is lossless.** `shimizu s-pulse` and
   `shimizu s pulse` were different canonical ids even though their raw names
   were equal. Comparing canonical ids with the same punctuation folding fixed
   MBet/Admiralbet fixtures in Japan, Korea, Norway and Saudi Arabia; MBet's
   grouping rate rose from 97.3% to 98.7%.
6. **One-sided qualifiers are accepted only when unambiguous.** `Werder` /
   `Werder Bremen`, `Central Coast` / `Central Coast Mariners` and
   `Slatina CSM` / `CSM Slatina` pair. Extra tokens that can name a different
   club (`City`, `United`, `Inter`, `Real`, `Atletico`, `Deportivo`) are
   vetoed, and so are ambiguous shared names such as `Sporting` /
   `Sporting CP`.
7. **Processing order uses the same open-league definition as candidates.**
   Betole's unmapped `germany, bundesliga` no longer sorts as a specific league
   ahead of Mozzart's `bundesliga`, so Mozzart anchors and Betole joins through
   the resolver instead of one of them becoming a singleton.
8. **Pairing quality is a health metric.** Every scan stores the audit result in
   `_pairing_summary`; `/api/health` exposes `pairing`/`live_pairing` and
   `/api/results` exposes `pairing`. The number cannot drift from the cached
   rows because it is computed from them, and it is recomputed after a cache
   restore so a restart does not lose it.
9. **Prematch expiry is real.** A group is dropped once the latest kickoff any
   book claims is more than two minutes past. Live mode still prices started
   matches; the old 15-minute prematch grace kept pricing fixtures that had
   already begun.

## Betole and EVLBet

`BetoleScraper().scrape(live=False)` returns **1,239** matches. The scraper was
fixed to read `kickOffTime` and to keep `brMatchId` as a Betradar id. Betole is
enabled; its first verified surebet was `anaitasuna ft – alaves` BTTS at 1.69%.

`python scripts/probe_feeds.py --books evlbet,betole` returns **0** matches for
EVLBet and **1,239** for Betole; the dated report is `docs/FEED_STATUS.md`.
EVLBet remains disabled and is an evidence-backed absence, not a silent omission.

## Known gaps

* First-half over/under (`first_half_ou`) is enabled but had no offer in the
  scan; the price guard applies if a book starts publishing it.
* Betole publishes several unregistered market codes; they are counted in
  `/api/health.unmapped_markets` and are not used for pricing.
* The legacy approve/reject HTTP routes are removed; the dashboard is read-only.
  The direct migration functions remain for legacy tests but are not reachable.
* Execution limits, bankroll and the 24-hour soak are not done.
* `script-src` is nonce-based with no `'unsafe-inline'`; `style-src` is
  `'self'` plus the Google Fonts stylesheet origin, with no inline styles.
* In-play remains deferred.

**Verdict:** the prematch scanner is working and finds real, re-verified
surebets across the nine scrapable books. It is ready for supervised prematch
use; it is not yet a fully unattended betting product.
