# BH_Arb

Arbitrage research scanner for the Bosnian bookmaker market. It scrapes odds,
decides which listings describe the same match, and prices only the groups the
certainty gate can defend. Football is the primary feed; basketball and tennis
have their own tab and never pair with football. It never places a bet.

> ### What `verified` means
>
> A surebet is shown only for a match group the certainty gate marks `verified`,
> and `verified` includes the link half of the claim. The rule is per book, from
> `config/bookmaker_deeplinks.json`:
>
> * A book that declares **no per-event route** (`supports_event_id: false`,
>   eight of the ten configured books) has **no per-event URL** to prove. The
>   declaration is the proof: the group carries a `no_event_link` evidence note and is verified on identity alone — league, kickoff, category, teams and orientation. A book with no declaration is refused; the gate fails safe.
> * **Mozzartbet** and **MaxBet** declare a route and must prove it. Their
>   path-based patterns were browser-proven on 2026-11-03. A listing with an
>   event id verifies with a `route_pattern_verified` note; one without an id
>   still blocks. MDShop's and Admiralbet's declared `?event=<id>` routes are
>   **inert** — the served page is byte-identical to the plain football page —
>   so on 2026-10-20 they were re-declared `supports_event_id: false`.
>
> Which books declare a route is reproducible:
>
> ```bash
> python -c "import json;d=json.load(open('config/bookmaker_deeplinks.json'));print([b for b,v in d.items() if v.get('supports_event_id') is True])"
> ```
>
> The inertness itself is a dated browser measurement, not a repo fact: taken on
> 2026-09-25 and re-checked on 2026-10-20. See `scripts/verify_deeplinks.py`,
> whose module docstring records the findings. `tests/test_readme_claims.py`
> keeps these claims aligned with the code.

## What it does

- Scrapes ten configured Bosnian bookmakers. Nine are enabled by default;
  EVLBet is disabled because its feed returns no football events.
- Learns team aliases and league equivalences from shared fixtures and keeps the
  evidence in a provenance ledger.
- Groups listings across books and prices only the groups the certainty gate
  proves. A book contributes at most one leg, and books sharing an odds feed
  count as one price source.
- Re-checks a bet slip by re-scraping only its books and re-pricing the exact
  outcomes.
- Runs Upcoming and Live as independent feeds, and shows basketball and tennis
  in a separate **Other sports** tab. Cross-sport pairing is a hard reject.

## Quick start

Requires Python 3.11+, network access to the bookmakers, and Playwright
Chromium for the browser-backed books.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install --with-deps chromium   # Linux; drop --with-deps on Windows/macOS
cp .env.example .env

python main.py
```

Re-run `playwright install chromium` after changing the Playwright pin: the
browser bundle is versioned, and a stale one fails with "Executable doesn't
exist".

- Dashboard: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

Open the dashboard and press **Scan now**. A live prematch scan takes a few
minutes. The server binds to `127.0.0.1` by default; set `API_KEY` before
exposing it beyond localhost.

## How a scan works

`POST /api/scan` starts one background scan for the chosen feed:

```text
POST /api/scan
  → scrapers/*.py            fetch and normalize one bookmaker's offers
  → engine/normalizer.py     canonical team, league and market names
  → engine/matcher.py        candidate match groups
  → engine/certainty.py      verified / suggested / rejected, with evidence
  → engine/arbitrage.py      stake split, worst case, profit margin
  → cache/*.json + frontend  results for the dashboard
```

- Scrapers run concurrently. `mozzartbet`, `admiralbet` and `wwin` share a
  Playwright concurrency limit; the rest use direct HTTP.
- Mapping learning runs before grouping, so aliases proved by the current scan
  are available to the matcher in the same pass.
- Only `verified` groups are priced. Refused pairings go to the read-only
  Diagnostics queue.
- Prematch and live use separate locks and write `cache/last_scan.json` and
  `cache/last_live_scan.json`. A scan is cached for 30 minutes and re-checked
  against the link store on restore.
- `POST /api/verify` re-scrapes just the books in one surebet and re-prices the
  exact market and outcomes it was built on.
- **Freshness is a runtime state.** `/api/results` carries a `freshness` block:
  mode, scan age, TTL, `stale`, per-book oldest/newest `fetched_at`, and the
  stale books. Prematch prices expire after `ODDS_TTL_SECONDS` (600 s); live
  prices after `LIVE_ODDS_TTL_SECONDS` (60 s). A stale scan keeps its rows for
  diagnosis but is labelled historical. The dashboard shows a banner and
  disables copy actions; **Re-check odds** stays available as the only path that
  re-establishes a leg's current price.
- **A frozen price is refused, not just aged.** `fetched_at` (when we collected
  a row) and `source_updated_at` (when the book says it moved) are separate.
  A row is refused as **price frozen** when the feed timestamp is older than the
  mode's TTL, or when it has not moved for three scans while an independent peer
  did move. A stable market with stable peers is never refused, and a feed with
  no timestamp falls back to the existing fetch-time TTL. The evidence is in
  `stale_prices` on `/api/results` and `/api/health`, and `stale_price_rows` on
  each feed-integrity scorecard. This is a price-source restriction, not a
  certainty-gate change.
- **Opportunity rate is measured, not inferred.** The same pricing pass that
  emits surebets also counts boards, crossings, crossings above the profit floor,
  and actionable opportunities. `/api/results` and `/api/health` expose
  `opportunity_metrics`, including a `zero_result_reason` that separates "no
  board crossed", "crossed below floor", "all crossings guarded", and stale or
  unverified feeds. Crossing lifetimes are kept as a bounded key store and
  summarized as p50/p90. The dashboard shows a crossing-rate tile.
- **Every enabled book has a feed-integrity state.** The scorecard checks
  freshness, empty/parse failures, missing markets, a complete set whose own
  margin is below 1.0, and outlier rate against the peer median. `healthy`,
  `degraded` and `quarantined` are exposed in `feed_integrity` in
  `/api/results` and `/api/health`. A quarantined book is removed from the
  copies used for pricing, with its reason shown in the dashboard; recovery
  needs three consecutive clean scans. This is a price-source restriction, not
  a change to the certainty gate.
- **Each book has one operational health state.** `book_health` in
  `/api/health` reduces the SR2-1 scrape kind, the SR2-6 breaker and the runtime
  toggle to `healthy`, `degraded`, `open`, `blocked`, `drifted` or `disabled`,
  with a one-line reason. It is a diagnostic; pricing still reads feed integrity
  and the certainty gate.
- **Unattended operation is observable.** Every request accepts or generates an
  `X-Request-ID`, returns it on the response, and stamps it on every log record
  emitted while the request runs; a scan gets its own `scan_id`. Set
  `LOG_FORMAT=json` for one JSON object per line. `GET /api/metrics` serves
  Prometheus text: scan started/completed/failed, per-book success/empty/error,
  surebets found/dropped, link checks, candidate-queue size, cache size, scan
  duration, last-scan age per feed, browser slots in use, process RSS, plus
  per-book attempts/retries, HTTP status, attempt-latency histogram, schema
  drift, browser recycles and the last-success timestamp. Every family is
  documented in [`docs/METRICS.md`](docs/METRICS.md). The endpoint is protected
  like every other `/api` route when `API_KEY` is set; the default
  loopback-only mode leaves it open. A completed scan emits one `scan complete`
  record with duration, book counts, groups, surebets, drops and cache size —
  never odds or credentials.

## Dashboard

- **Surebets** — best profit first. Selecting one opens the bet slip, which
  re-checks the odds, orders legs longest-odds-first, rounds stakes to whole KM,
  and re-plans the remaining legs after you mark one as placed. If the feed has
  crossed its TTL, a banner marks the list as historical and copy actions are
  disabled until you re-check or scan again.
- **Diagnostics** — pairings the gate could not prove, with the evidence it
  used. This view is read-only.
- **Evidence** — a bounded list of group summaries filtered by status, sport or
  search. Opening one group fetches its full gate evidence and bookmaker legs;
  the list never downloads every group's evidence at once.
- **History** — per-scan counts and errors for both feeds.
- **Settings** — stake, rounding, scan run mode (advisory / record-only /
  paper), auto-rescan, alert sound, enabled bookmakers, experimental markets and
  the health line. Unhealthy books also appear in a feed-integrity strip above
  the tabs, with the reason they are degraded or quarantined from pricing.
- **Installable shell** — the dashboard registers a service worker for the
  static app shell only. It never caches `/api` responses or odds; an offline
  reload shows the shell, and a stale scan is still labelled historical.

`python scripts/opportunity_baseline.py --days 7` prints the aggregate
opportunity-rate baseline for the recorded scan history. The first local
baseline is `docs/evidence/2026-11-04-opportunity-rate-baseline.md`; until a
7-day run exists it records the public reference (1.34% crossing) and says the
local window is still empty rather than inventing a number.

## Pricing and rounding

Every surebet carries the legs' served `odds` plus `raw_margin` (the exact
`sum(1/odds)`) and `total_margin` (the same value rounded to four decimals for
display). `profit_percent` is derived from that margin and rounded to two
decimals. A reviewer can recompute it from the payload without trusting a
second calculation.

`POST /api/recalculate` accepts `rounding: "exact" | "1" | "5"` and returns both
numbers separately:

- `exact` — the profit if the investment were split proportionally with no
  stake rounding;
- `realized` — the worst actual return of the rounded stakes, minus what those
  stakes cost, plus the `rounding_loss`;
- `raw_margin` / `implied_sum` — the exact source value.

The dashboard slip shows **exact profit** and **realized profit** side by side,
plus the rounding effect. The realized number is never labelled as the exact
one. Stakes round to cents (`exact`), whole units (`1`) or multiples of five
(`5`).

## Record-only and paper trading

A scan can run in three modes through `POST /api/scan?run_mode=…`:

- `advisory` (default) — the normal live surebet list; unchanged.
- `record_only` — stores a compact snapshot of each verified opportunity and
  publishes **no live surebet**. `/api/paper/opportunities` returns the ledger.
- `paper` — does the same and maintains virtual positions, a paper bankroll,
  execution hit rate and next-scan CLV through `/api/paper/summary`.

A non-advisory scan writes an empty live list for that feed and the dashboard
shows a banner saying no live surebet is shown. Paper positions are marked
against the next scan and can be settled manually; a missing leg result leaves
the position open. Neither mode places a bet, logs in, or models account
effects. Every paper response carries `no_bet_placed: true`, and ROI/CLV are only
reported with explicit denominators. See [`docs/PAPER_MODE.md`](docs/PAPER_MODE.md).

## Deployment

The shortest reproducible path on a fresh Linux host:

```bash
git clone https://github.com/dzanagamba/BH_Arb.git
cd BH_Arb
mkdir -p cache
docker compose up --build -d
curl -fsS http://127.0.0.1:8000/api/health
```

The dashboard is at `http://127.0.0.1:8000/`. The image runs as a non-root
`scanner` user, publishes only on loopback by default, and bind-mounts `cache/`
and `config/` so scan history, learned mappings and deep-link decisions survive
a restart. The first build installs Chromium and takes roughly 5–10 minutes
(1–1.5 GB); later builds reuse the dependency layer.

`python scripts/docker_smoke.py` builds the image, starts it, checks
`/api/health`, verifies the runtime uid is non-root, and proves a marker in
`/app/cache` survives a container restart.

For UID/GID matching, systemd, health checks, and the exact backup/restore list
(`cache/`, `config/generated/mapping_evidence.json`,
`config/team_alias_allowlist.json`, `config/bookmaker_deeplinks.json`), see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Release gates (Docker smoke,
CycloneDX SBOM, grouped dependency updates and the local equivalents) are in
[`docs/RELEASE.md`](docs/RELEASE.md).

### Authentication and scopes

One middleware guards every `/api` route except `/api/health`. It accepts the
bootstrap `API_KEY` or a named key from `config/generated/api_keys.json`
(stored as a PBKDF2 hash, revocable, audited). With neither a bootstrap key nor
any stored key the API stays open, which is the documented local-only mode and
safe only on the loopback default; set `API_KEY` before exposing the port.

| Scope | Grants |
|---|---|
| `read` | Every `GET`/`HEAD` (results, status, config, groups, history, metrics, candidates, bets/paper reads, CSV downloads). |
| `scan` | The write routes: `POST /api/scan`, `/api/verify`, `/api/recalculate`, `/api/verify-links`, `/api/link-sweeps`, `/api/bets`, the bet/paper settle and closing writes. |
| `admin` | Config toggles, shutdown, key creation/listing/revocation and the audit log. |

A dashboard key normally needs `read` and `scan`; `admin` is for operator
actions. A key with only `scan` cannot read results, and a revoked key fails on
its next request. The dashboard sends the key on every fetch, poll and download
(it asks once and keeps it in `sessionStorage`). Successful verifications are
cached for `AUTH_CACHE_SECONDS` (a revocation is still immediate) and repeated
wrong keys are throttled per address by `AUTH_FAILURE_RATE_LIMIT` before any
PBKDF2 work; see [`docs/AUTH.md`](docs/AUTH.md).

## Configuration

Copy `.env.example` to `.env` and set only what you need:

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address and port. Use `0.0.0.0` only behind a firewall and with `API_KEY` set. |
| `API_KEY` | *(empty)* | The bootstrap/admin key. When set, every `/api` route except `/api/health` requires a key: this value or a named key from `config/generated/api_keys.json`. |
| `CORS_ORIGINS` | *(empty)* | Allowed origins for a separate frontend; empty means same-origin only. |
| `SCAN_RATE_LIMIT` | `3` | Maximum scans a client may trigger per minute. |
| `VERIFY_RATE_LIMIT` | `10` | On-demand surebet re-verifications per client per minute; `0` disables the limit. |
| `DEEP_LINK_VERIFY_RATE_LIMIT` | `2` | Deep-link checks per client per minute; `0` disables the limit. |
| `AUTH_FAILURE_RATE_LIMIT` | `10` | Failed API-key attempts per client address per `RATE_LIMIT_WINDOW_SECONDS` before `429`; `0` disables the limit. A wrong key costs one PBKDF2 hash, so this is the CPU ceiling. |
| `AUTH_CACHE_SECONDS` | `60` | How long a successful named-key verification is cached in memory, so polling does not repeat the ~85 ms PBKDF2; `0` disables the cache. A revocation through the API is immediate; this only bounds an out-of-band edit. |
| `HEADLESS` | `true` | Set `false` to watch Playwright browsers. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `LOG_FORMAT` | `text` | `text` for the readable line, `json` for one JSON object per line. Both carry `request_id`/`scan_id`. |
| `VERIFY_SSL` | `false` | Enforce TLS verification on direct HTTP calls. |
| `SCRAPER_REQUESTS_PER_SECOND` | `5` | Outgoing ceiling per bookmaker, in requests per second (retries included); `0` disables it. |
| `SCRAPER_BOOK_RATES` | `mozzartbet=60` | Per-book overrides of that ceiling, as `book=rate` pairs. Mozzartbet runs at 60/s so its per-event full offer does not dominate the scan. |
| `SCRAPER_BOOK_TIMEOUT_SECONDS` | `240` | One adapter's budget. A book that overruns is reported `timeout` and missing from the scan; the others still price. |
| `SCRAPER_SCAN_TIMEOUT_SECONDS` | `600` | Budget for the whole scraping phase. Books still running are cancelled (context released) and the scan prices what returned. |
| `BROWSER_MAX_PAGES` / `BROWSER_MAX_AGE_SECONDS` | `200` / `600` | A scan shares one Chromium; it is recycled after this many book contexts or this many seconds. A disconnected browser is replaced at the next book. |
| `FORENSICS_ENABLED` | `true` | Keep a Playwright trace and screenshot for a failed browser book under `cache/forensics/<book>/<scan_id>/`. Cookies and storage state are never written. |
| `FORENSICS_MAX_MB` / `FORENSICS_MAX_AGE_DAYS` | `200` / `7` | Retention caps for that directory, applied after every capture. |
| `BOOK_BACKOFF_AFTER_FAILURES` | `3` | Consecutive failures before a book's circuit breaker opens; `blocked`/`429` open it immediately. See `/api/health` → `scheduler.breakers`. |
| `BOOK_BACKOFF_MAX_MINUTES` | `60` | Cap on the breaker's cooldown, which doubles on every consecutive open. |
| `AUTO_SCAN_PREMATCH_MINUTES` | `0` | Scheduled prematch scans; `0` disables them. |
| `AUTO_SCAN_LIVE_MINUTES` | `0` | Scheduled live scans; `0` disables them. |
| `AUTO_LEARN_MAPPINGS` | `true` | Learn team, league and market claims from real scans. |
| `PRICE_GUARD_ENABLED` | `true` | Drop a surebet whose leg is a price outlier. |
| `ALERT_WEBHOOK_URL` | *(empty)* | Generic webhook for operator alerts; empty means no transport. See [`docs/ALERTING.md`](docs/ALERTING.md). |
| `ALERT_TELEGRAM_BOT_TOKEN` / `ALERT_TELEGRAM_CHAT_ID` | *(empty)* | Telegram alert transport; both are required. |
| `ALERT_MIN_PROFIT_PERCENT` / `ALERT_DEDUPE_MINUTES` | `3.0` / `60` | Minimum profit and per-signature dedupe window. |
| `RSS_BUDGET_MB` | `1024` | Soft memory budget reported by `/api/health`. |
| `BOOK_MAX_STAKE_<BOOK>` | from `config/bookmaker_risk.json` | Advisory per-book stake ceiling shown in the slip. See [`docs/BOOK_RISK.md`](docs/BOOK_RISK.md). |

Optional AI ranking uses an OpenAI-compatible endpoint. It can only order the
Diagnostics queue; it cannot create or approve a pairing.

| Variable | Default | Meaning |
|---|---|---|
| `AI_API_KEY` | *(empty)* | API key. Unset means the AI stage is never entered. |
| `AI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible base URL. |
| `AI_MODEL` | `gpt-4o-mini` | Model id. |

Tuning that belongs in code lives in `config/settings.py`: `MIN_PROFIT_PERCENT`
(`0.5`), `DUST_PROFIT_PERCENT` (`0.2`), `DEFAULT_INVESTMENT` (`100` BAM),
`KICKOFF_WINDOW_MINUTES` (`120`), `MAX_SUREBET_PROFIT_PERCENT` (`20`),
`ODDS_TTL_SECONDS` (600), `LIVE_ODDS_TTL_SECONDS` (60), `PRICE_SOURCES` and
`BROWSER_CONCURRENCY`.

Book risk profiles (`sharp` / `soft` / `exchange` / `unknown`) live in
`config/bookmaker_risk.json`. They are advisory metadata only: they never enter
the certainty gate, the price-source rule, or the stake math. The policy and
the no-evasion/no-placement stance are in
[`docs/BOOK_RISK.md`](docs/BOOK_RISK.md).

## Match & mapping certainty

“These two listings are the same match” is not a fuzzy score with a threshold.
It is a claim that has to be proven. The certainty gate in
`engine/certainty.py`, used by `engine/matcher.py`, is the only authority.
Each gate appends a `MatchEvidence` record, and the reasons left over decide the
status:

| Status | Meaning | Reason vocabulary |
|---|---|---|
| `verified` | Zero reasons. Every part of the claim is proven, links included. Only these groups reach arbitrage. | — |
| `suggested` | At least one reason is outstanding: plausible but incomplete. Shown in Diagnostics only. | `kickoff_missing`, `kickoff_delta`, `team_unresolved`, `link_unverified`, `no_event_link` |
| `rejected` | A hard gate contradicts the claim. | `league_mismatch`, `category_mismatch`, `betradar_mismatch`, `leg_mismatch`, `orientation_unresolved`, `sport_mismatch` |

The strings above are the vocabulary the gate actually emits, and
`tests/test_readme_claims.py` proves it by running the gate over one broken claim
per reason. `sport_mismatch` is the one reason not in `HARD_REJECT_REASONS`: the
gate returns it as an explicit `rejected` result before that set is consulted,
because a sport boundary is a contradiction no other evidence can override.
Every member of `HARD_REJECT_REASONS` is reachable and appears in the table.

### What the gate trusts

- **Evidence, not a score.** Team aliases and league equivalences are learned
  from shared fixtures and Betradar ids, then stored in
  `config/generated/mapping_evidence.json`. The evidence ledger is the main
  trust source. `config/team_alias_allowlist.json` still supplies reviewed alias
  pairs as seed data; `config/team_alias_reviewed.json` is legacy migration
  input. The default pipeline does not ask a person to approve a pair.
- **Name and group proof.** Lossless differences (club designators, token
  abbreviations, punctuation) are accepted, while a shared city token is not
  enough. A candidate can be proved by any supporting member of the group, not
  only its anchor. An unmapped league does not block an exact fixture, and a
  shared Betradar id proves identity outright.
- **A link is a machine fact.** It is never by a human approval that
  `deep_link_verified` is set; only `scripts/verify_deeplinks.py` or
  `POST /api/verify-links`, after a real browser check, may set it.
- **A second fixture is not a name match.** Different provider ids reject. A
  feed-declared `leg` (doubleheader/rematch) that differs rejects as
  `leg_mismatch`; it is never inferred from names. Same teams outside the
  kickoff window are a `kickoff_delta`, not one event, and a kickoff across a
  date boundary is judged by the absolute minutes.

### Diagnostics

Pairings the gate refused are collected every scan into a per-feed queue
(`pending_candidates` for prematch, `pending_live_candidates` for live), so one
feed’s scan never wipes the other’s. They are shown in the dashboard’s
**Diagnostics** tab. There is no dedicated URL: Diagnostics is the second tab,
so open `http://localhost:8000` and click **Diagnostics**. It is populated by
`GET /api/candidates?mode=prematch|live` and is read-only: there is no approve
or reject endpoint. AI proposals can raise a queue entry’s position and nothing
else. Each card carries a **proposal-only** remediation block: the exact team
aliases or league equivalence that would be needed, what the evidence ledger
already says about them, and the exact gate reasons. The **Top recurring
blockers** panel groups the queue by book pair, league and reason with the queue
size as its denominator; the strict-miss trend shows the same grouping over
scans. Nothing in that panel applies a mapping. The same report is available
offline:

```bash
python scripts/candidate_remediation.py --top 20
```

See `docs/CANDIDATE_REMEDIATION.md` for the ranking and denominator rules.

`GET /api/health` carries the same counts plus the feed, breaker and
admissibility state. Its measured summary (parser contracts, admissibility,
retention and the walks over cached matches and candidates) is reused for
`HEALTH_CACHE_SECONDS` (default 2 s, `0` disables); the payload's
`health_cache` block says when it was built, and a scan drops it so a finished
scan is visible on the next poll. The live fields (scanning state, counters,
breakers, book health) are computed every request.

### Language and accessibility

The dashboard ships English and Bosnian. All UI chrome comes from
`frontend/js/i18n.js`; a language change repaints the generated list, slip and
tabs. Scraped names and league labels are data and are never translated.
`tests/test_i18n_coverage.py` fails on a missing key or a lost placeholder.

Accessibility is machine-checked: `tests/test_accessibility_axe.py` covers
landmarks, names, the results-tab semantics, live regions and the keyboard path,
and `scripts/a11y_audit.py` runs a live Chromium audit with optional axe-core.
The reviewed exception list and the keyboard-only run are in
`docs/ACCESSIBILITY.md`.

### Parser fixtures and drift

Each frozen market payload has a dated contract in
`tests/fixtures/markets/contracts.json`: required keys, source ids, labels and
nested shape. `python scripts/refresh_fixtures.py --check` (also in CI) fails on
a changed payload, a missing enabled book or a capture older than 120 days, and
prints the exact id/label/shape diff. `/api/health.parser_contracts` exposes the
same coverage and staleness. A diff never edits the registry; a new market still
needs its admissibility evidence. See `docs/PARSER_CONTRACTS.md`.

### Deep-link verification

`scripts/verify_deeplinks.py` proves a bookmaker’s per-event links with real
browser navigations. It reads `cache/last_scan.json`, so run a scan first:

```bash
python scripts/verify_deeplinks.py mozzartbet --limit 3
python scripts/verify_deeplinks.py --mode live --limit 20
```

Verdicts go to `cache/deep_link_verifications.json`; the next scan reads that
store. The check is deliberately not part of a scan because each event costs a
navigation.

Declaration edits in `config/bookmaker_deeplinks.json` are picked up without a
restart: the loader tracks the file's mtime and size and reloads when they
change. `/api/health` exposes `deep_link_declaration_source` with `loaded_at`,
`source_mtime`, `stale` and `error`, and each declaration entry carries the same
provenance. A malformed file clears the map and fails safe (every book blocks);
health says why instead of silently continuing with the old map.

**A sweep advances; it is not a one-shot operation.** `build_targets` takes
`settled` (event ids the caller has already decided) and `offset` (a positional
resume, for a caller with no store of its own — which is the CLI), and the
`settled` ids are skipped *before* the window is cut. `POST /api/verify-links`
fills `settled` from `cache/deep_link_decisions.json`; once a book is fully
decided the response reports `remaining: 0`.

**A sweep does converge.** Both stores must outlive one pass. The proof is the longer of the two:
`DEEP_LINK_VERIFICATION_TTL_SECONDS` (24h) outlives a pass, while
`DEEP_LINK_DECISION_TTL_SECONDS` (6h) only needs to outlive it, because a
decision says "a check completed" and carries no verdict.

### Regression guards

Two live-mode defects are fixed and pinned by regression tests.
`premier_kladionica` now reads `NAME_BTTS_LIVE` for live BTTS. The NSoft live
window (`mdshop`, `admiralbet`) now comes from `nsoft_event_window` instead of
`dateFrom=now`; the old request returned no events while 35 live football events
were available with a 12 hours lookback. See `tests/test_market_fixtures.py`
and `tests/test_live_mode.py`.

## Project layout

| Path | Responsibility |
|---|---|
| `main.py` | Starts uvicorn on `HOST`/`PORT`. |
| `server/` | FastAPI app, `/api/*` routes, auth, scan orchestration, scheduling, storage, paper/bet ledgers, alerts and mapping coverage. |
| `scrapers/` | One module per bookmaker; `base.py` has the Playwright launcher and HTTP retry, `common.py` shared parsing and deep-link helpers. |
| `engine/` | Normalization, name and league resolution, mapping learning, matching, the certainty gate, market registry, price guard and pricing. |
| `models/schemas.py` | Pydantic models shared by every layer. |
| `config/` | Runtime settings, bookmaker and market registries, deep-link declarations, mappings and the generated evidence ledger. |
| `frontend/` | Static dashboard served at `/`; no bundler. Includes the installable static-shell service worker. |
| `scripts/` | Operator tools for deep-link checks, fixture capture, mapping derivation and `MARKET_MAPPING.md` generation. |
| `tests/` | Offline pytest suite; `tests/fixtures/markets/` holds captured payloads. |
| `cache/` | Gitignored runtime state: last scan per feed, history, link proofs and decisions. |
| `docs/` | Design history, acceptance notes, readiness assessments and evidence. |
| `Dockerfile`, `.dockerignore`, `docker-compose.yml` | Reproducible non-root container with a Chromium install and health check. |
| `deploy/bh-arb.service` | Hardened systemd unit for a bare-metal install. |

## Development

Install the dev tools once, then run the same checks as CI:

```bash
pip install -r requirements.txt -r requirements-dev.txt

python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/audit_admissibility.py --check
python scripts/refresh_fixtures.py --check
python scripts/check_test_isolation.py

# Opt-in property load budgets (skipped in the normal fast suite)
BH_ARB_TEST_SLOW=1 python -m pytest tests/test_perf_budgets.py

# Opt-in Chromium checks, including the committed HAR replays
BH_ARB_TEST_BROWSER=1 python -m pytest tests/test_browser_har_replay.py

# Same coverage and security gates as CI
python -m pytest --cov --cov-report=term-missing
python -m pip_audit -r requirements.txt -r requirements-dev.txt --progress-spinner off
python -m bandit -r engine server scrapers config models main.py scripts -ll -q
```

The coverage floor is 80% (measured baseline 85.63%) and Bandit fails at medium
severity or above. Accepted `# nosec` entries and the coverage baseline are
documented in [`docs/CI.md`](docs/CI.md).

- Tests must stay offline: use fakes, `httpx.MockTransport` or
  `tests/fixtures/`. A test must never call a bookmaker.
- Tests must not read or write the checkout's runtime state. `tests/conftest.py`
  redirects the generated ledger, `cache/` and the SQLite store to a temporary
  tree; run both ledger modes with `python scripts/check_test_isolation.py`.
  Never delete the operator's ledger to make a test pass.
- Frontend tests run the shipped JavaScript under Node 22 and skip without it.
- The browser books' transport is recorded as scrubbed HAR fixtures and replayed
  with `BH_ARB_TEST_BROWSER=1`; see [`docs/HAR_REPLAY.md`](docs/HAR_REPLAY.md)
  for the format, the scrubbing rules and `scripts/capture_har.py`.
- Pricing and identity rules also have property-based coverage in
  `tests/test_properties_pricing.py` and `tests/test_properties_identity.py`.
  The load budgets are opt-in (`BH_ARB_TEST_SLOW=1`); see
  [`docs/PROPERTY_TESTS.md`](docs/PROPERTY_TESTS.md).
- Sport and market admissibility is re-audited against a dated baseline
  (`scripts/audit_admissibility.py --check`, N3-2). A new family is a warning,
  never an admission; see
  [`docs/ADMISSIBILITY_AUDIT.md`](docs/ADMISSIBILITY_AUDIT.md).
- `tests/test_readme_claims.py` checks the factual claims in this file against
  the code. `MARKET_MAPPING.md` is generated; regenerate it, never hand-edit it.
- `tests/fixtures/e2e_certified/` is frozen. Do not edit or re-capture it.

## Operator tools

```bash
# Learn league names and team spellings from fixtures the books share.
python scripts/derive_mappings.py cache/last_scan.json --report proposals.json
python scripts/derive_mappings.py cache/last_scan.json --apply

# Regenerate the market ID tables, or fail if they are stale.
python scripts/generate_market_mapping_doc.py --check

# Record one real scan's per-sport metrics.
python scripts/record_scan.py prematch --out docs/evidence/prematch-scan.json

# Sweep one book's declared event links until verify-links reports remaining 0.
python scripts/sweep_links.py --bookmaker mozzartbet --mode prematch --check

# Show dated no-event declarations; --check fails when one is overdue.
python scripts/audit_deeplinks.py --check

# Precision/recall over the frozen multi-day replay corpus.
python scripts/evaluate_matching.py --check

# Capture XHR/WebSocket transport metadata for a bookmaker decision.
python scripts/discover_push_feeds.py --bookmaker mozzartbet --seconds 20
```

## Adding bookmakers, markets and names

- **Bookmaker:** add `scrapers/<book>.py`, then one declaration in
  `config/bookmakers.py` (name, adapter module/class, transport, enabled flag,
  timeouts). `BOOKMAKERS`, the lazy `SCRAPERS` registry, `PLAYWRIGHT_BOOKIES`
  and the transport policies are derived from it; the consistency test fails if
  a module has no declaration or a declaration has no module. Then add its
  deep-link declaration, market registry rows and captured fixtures, and the
  parser and gate tests.
- **Market:** add the source ids and labels to `config/bookmaker_markets.json`,
  capture a payload under `tests/fixtures/markets/`, add a registry test, and
  regenerate `MARKET_MAPPING.md`.
- **League and team names:** prefer the ledger and `scripts/derive_mappings.py`
  over hand edits. Inspect Diagnostics to see what the gate refused.

## Notes

- All odds are European decimal odds. Stakes are calculated for
  `DEFAULT_INVESTMENT` and can be adjusted in the dashboard.
- This is a research tool. It does not log in to bookmakers, move money or place
  bets.
