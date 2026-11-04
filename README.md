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
playwright install chromium
cp .env.example .env

python main.py
```

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

## Dashboard

- **Surebets** — best profit first. Selecting one opens the bet slip, which
  re-checks the odds, orders legs longest-odds-first, rounds stakes to whole KM,
  and re-plans the remaining legs after you mark one as placed. If the feed has
  crossed its TTL, a banner marks the list as historical and copy actions are
  disabled until you re-check or scan again.
- **Diagnostics** — pairings the gate could not prove, with the evidence it
  used. This view is read-only.
- **History** — per-scan counts and errors for both feeds.
- **Settings** — stake, rounding, auto-rescan, alert sound, enabled bookmakers,
  experimental markets and the health line.

## Configuration

Copy `.env.example` to `.env` and set only what you need:

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address and port. Use `0.0.0.0` only behind a firewall and with `API_KEY` set. |
| `API_KEY` | *(empty)* | When set, every `/api` route except `/api/health` requires an `X-API-Key` header. |
| `CORS_ORIGINS` | *(empty)* | Allowed origins for a separate frontend; empty means same-origin only. |
| `SCAN_RATE_LIMIT` | `3` | Maximum scans a client may trigger per minute. |
| `HEADLESS` | `true` | Set `false` to watch Playwright browsers. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `VERIFY_SSL` | `false` | Enforce TLS verification on direct HTTP calls. |
| `AUTO_SCAN_PREMATCH_MINUTES` | `0` | Scheduled prematch scans; `0` disables them. |
| `AUTO_SCAN_LIVE_MINUTES` | `0` | Scheduled live scans; `0` disables them. |
| `AUTO_LEARN_MAPPINGS` | `true` | Learn team, league and market claims from real scans. |
| `PRICE_GUARD_ENABLED` | `true` | Drop a surebet whose leg is a price outlier. |

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
| `rejected` | A hard gate contradicts the claim. | `league_mismatch`, `category_mismatch`, `betradar_mismatch`, `orientation_unresolved`, `sport_mismatch` |

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

### Diagnostics

Pairings the gate refused are collected every scan into a per-feed queue
(`pending_candidates` for prematch, `pending_live_candidates` for live), so one
feed’s scan never wipes the other’s. They are shown in the dashboard’s
**Diagnostics** tab. There is no dedicated URL: Diagnostics is the second tab,
so open `http://localhost:8000` and click **Diagnostics**. It is populated by
`GET /api/candidates?mode=prematch|live` and is read-only: there is no approve
or reject endpoint. AI proposals can raise a queue entry’s position and nothing
else.

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
| `server/` | FastAPI app, `/api/*` routes, scan orchestration, scheduling and mapping coverage. |
| `scrapers/` | One module per bookmaker; `base.py` has the Playwright launcher and HTTP retry, `common.py` shared parsing and deep-link helpers. |
| `engine/` | Normalization, name and league resolution, mapping learning, matching, the certainty gate, market registry, price guard and pricing. |
| `models/schemas.py` | Pydantic models shared by every layer. |
| `config/` | Runtime settings, bookmaker and market registries, deep-link declarations, mappings and the generated evidence ledger. |
| `frontend/` | Static dashboard served at `/`; no bundler. |
| `scripts/` | Operator tools for deep-link checks, fixture capture, mapping derivation and `MARKET_MAPPING.md` generation. |
| `tests/` | Offline pytest suite; `tests/fixtures/markets/` holds captured payloads. |
| `cache/` | Gitignored runtime state: last scan per feed, history, link proofs and decisions. |
| `docs/` | Design history, acceptance notes, readiness assessments and evidence. |

## Development

Install the dev tools once, then run the same checks as CI:

```bash
pip install -r requirements-dev.txt

python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
```

- Tests must stay offline: use fakes, `httpx.MockTransport` or
  `tests/fixtures/`. A test must never call a bookmaker.
- Frontend tests run the shipped JavaScript under Node 22 and skip without it.
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
```

## Adding bookmakers, markets and names

- **Bookmaker:** add `scrapers/<book>.py`, register it in `SCRAPERS` and
  `BOOKMAKERS`, add its deep-link declaration, market registry rows and captured
  fixtures, then add parser and gate tests. Mark it as a Playwright book only if
  it really needs a browser.
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
