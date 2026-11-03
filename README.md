# BH_Arb

Arbitrage research scanner for the Bosnian football betting market. It compares
odds across bookmakers, proves which listings describe the same match, and
prices only the groups the certainty gate can defend. It never places a bet.

> ### What `verified` means
>
> A surebet is shown only for a match group the certainty gate marks `verified`,
> and `verified` includes the link half of the claim. Which proof satisfies that
> half is decided per book, by the book's declaration in
> `config/bookmaker_deeplinks.json`:
>
> * A book that declares **no per-event route** (`supports_event_id: false`,
>   eight of the ten books) has **no per-event URL** to prove, so the
>   declaration is the proof: the group carries a `no_event_link` evidence note and is verified on identity alone — league, kickoff, category, teams, orientation. A book with no declaration at all is refused; the gate fails safe.
> * A book that declares a route (`supports_event_id: true` — **Mozzartbet** and
>   **MaxBet**) must prove it. Their path-based patterns were browser-proven on
>   2026-11-03 on three sampled events each: a listing with an event id verifies
>   with a `route_pattern_verified` note, while a listing without an id still
>   blocks. MDShop's and Admiralbet's declared `?event=<id>` routes are
>   **inert** — the served page is byte-identical to the plain football page —
>   so on 2026-10-20 both were re-declared `supports_event_id: false` and now
>   verify on identity like the other route-less books.
>
> What blocks `verified` today is identity, not links: league names the
> mappings do not equate, team spellings the ledger has not proven, and kickoff
> deltas.
>
> The repo can reproduce which books declare a route:
>
> ```bash
> python -c "import json;d=json.load(open('config/bookmaker_deeplinks.json'));print([b for b,v in d.items() if v.get('supports_event_id') is True])"
> ```
>
> The inertness itself is a dated browser measurement, not a repo fact: taken on
> 2026-09-25 and re-checked on 2026-10-20. See `scripts/verify_deeplinks.py`,
> whose module docstring records the findings. These claims are checked by
> `tests/test_readme_claims.py`, so a claim that stops matching the code fails
> the suite.

## What it does

- **Scrapes** ten configured Bosnian bookmakers. Mozzartbet, MDShop, Admiralbet,
  Betole, MBet, SportPlus, Premier Kladionica, WWIN and MaxBet are enabled by
  default; EVLBet is configured but disabled because its feed returns no
  football events.
- **Learns names** from the fixtures the books share on every scan — Bosnian
  diacritics, Cyrillic, abbreviations, youth/reserve/women markers — and keeps
  the evidence in a provenance ledger.
- **Groups events** across books and lets only a group the certainty gate proves
  is the same event reach pricing.
- **Prices surebets**: for each verified group it finds the combination of
  distinct bookmakers whose odds guarantee a profit, then returns the stake
  split, worst-case return and margin. A book contributes at most one leg, and
  books that share an odds feed (MDShop and Admiralbet both run on NSoft) count
  as one price source.
- **Re-checks a bet slip**: before you place a bet, the dashboard can re-scrape
  only the books in that surebet, re-price the exact outcomes, and tell you
  whether the edge still exists.
- **Runs two independent feeds**: **Upcoming** (prematch) and **Live**
  (in-play), each with its own cache, locks, diagnostics queue and history.

## Quick start

### Requirements

- Python 3.11+
- pip
- Network access to the bookmakers for live scans
- Playwright Chromium for the browser-backed books

### Install

```bash
git clone https://github.com/dzanagamba/BH_Arb.git
cd BH_Arb

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

### Run

```bash
python main.py
```

- Dashboard: http://localhost:8000
- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

Open the dashboard and press **Scan now**. A prematch scan takes about three
minutes because most bookmakers are fetched live. The server binds to
`127.0.0.1` by default; set `API_KEY` before exposing it beyond localhost.

## How it works

A scan is orchestrated by `server/api.py` and moves through one pipeline:

```text
POST /api/scan
  → scrapers/*.py            fetch and normalize one bookmaker's offers
  → engine/normalizer.py     canonical team, league and market names
  → engine/matcher.py        candidate match groups
  → engine/certainty.py      verified / suggested / rejected, with evidence
  → engine/arbitrage.py      stake split, worst case, profit margin
  → cache/*.json + frontend  results for the dashboard
```

- Scrapers run concurrently. Browser-backed books (`mozzartbet`, `admiralbet`,
  `wwin`) share a Playwright concurrency limit; the rest use direct HTTP.
- Mapping learning runs before grouping, so aliases and league equivalences
  proved by the current scan are available to the matcher in the same pass.
- Prematch and live scans do not share state. They have separate locks and
  write `cache/last_scan.json` and `cache/last_live_scan.json`.
- Only `verified` groups are priced. Suggested and rejected pairings never reach
  the arbitrage engine; they are collected for the read-only Diagnostics view.
- A successful scan is cached for 30 minutes. A restored snapshot is re-checked
  against the link store, so a group survives a restart only while its link
  proofs are still fresh.
- `POST /api/verify` re-scrapes just the books in one surebet, applies the same
  pipeline, and re-prices the exact market and outcomes the surebet was built
  on.

## Using the dashboard

- **Surebets** — best profit first. Selecting one opens the bet slip, which
  re-checks the odds, orders legs longest-odds-first, rounds stakes to whole KM,
  shows the profit after rounding, and re-plans the remaining legs after you
  mark one as placed. It also lists the evidence that the legs are the same
  match.
- **Diagnostics** — pairings the gate could not prove, with the evidence it
  used. This view is read-only: the evidence ledger learns automatically, and
  nothing here changes a mapping.
- **History** — per-scan counts and errors for both feeds.
- **Settings** — default stake, rounding, auto-rescan, alert sound, enabled
  bookmakers, experimental markets, and the health line.

## Configuration

Copy `.env.example` to `.env` and set only what you need:

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address and port. Use `0.0.0.0` only behind a firewall and with `API_KEY` set. |
| `API_KEY` | *(empty)* | When set, every `/api` route except `/api/health` requires an `X-API-Key` header. The dashboard asks for it once per tab. |
| `CORS_ORIGINS` | *(empty)* | Comma-separated origins for a separate frontend; empty means same-origin only. |
| `SCAN_RATE_LIMIT` | `3` | Maximum scans a client may trigger per minute. |
| `HEADLESS` | `true` | Set `false` to watch Playwright browsers, for example while solving a CAPTCHA. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `VERIFY_SSL` | `false` | Enforce TLS verification on direct httpx calls. |
| `AUTO_SCAN_PREMATCH_MINUTES` | `0` | Scheduled prematch scans; `0` disables them. |
| `AUTO_SCAN_LIVE_MINUTES` | `0` | Scheduled live scans; `0` disables them. |
| `AUTO_LEARN_MAPPINGS` | `true` | Learn team/league/market claims from each real scan. |
| `PRICE_GUARD_ENABLED` | `true` | Drop a surebet whose leg is a price outlier against the other books. |

Tuning that belongs in code lives in `config/settings.py`: `MIN_PROFIT_PERCENT`
(default `0.5`), `DUST_PROFIT_PERCENT` (`0.2`), `DEFAULT_INVESTMENT` (`100` BAM),
`KICKOFF_WINDOW_MINUTES` (`120`), `MAX_SUREBET_PROFIT_PERCENT` (`20`),
`ODDS_TTL_SECONDS`, `PRICE_SOURCES`, and `BROWSER_CONCURRENCY`.

## Match & mapping certainty

"These two listings are the same match" is not a fuzzy score with a threshold.
It is a claim that has to be proven, and the certainty gate is the only thing
that decides it.

### Stage 1 — deterministic rules

`engine/certainty.py`, used by `engine/matcher.py`, evaluates every candidate
pairing against hard, deterministic gates. Each gate appends a `MatchEvidence`
record explaining what it found, and the pair's status follows from the reasons
left over:

| Status | Meaning | Reason vocabulary |
|---|---|---|
| `verified` | Zero reasons. Every part of the claim is proven, links included. These are the only groups that reach arbitrage. | — |
| `suggested` | At least one reason is outstanding — the identity is plausible but incomplete. Not priced; shown in the read-only Diagnostics queue. | `kickoff_missing`, `kickoff_delta`, `team_unresolved`, `link_unverified`, `no_event_link` |
| `rejected` | A hard gate contradicts the claim. | `league_mismatch`, `category_mismatch`, `betradar_mismatch` |

The reason strings are the vocabulary the gate actually emits, and
`tests/test_readme_claims.py` proves it by running the gate over one broken claim
per reason and reading the results back. One wrinkle: `HARD_REJECT_REASONS` also
lists `orientation_unresolved`, which the gate never emits; the
unresolvable-orientation case is reported as `team_unresolved`. Treat
`rejected` as the reasons above except `orientation_unresolved` until that entry
is produced or deleted.

The rules that matter most:

- **The evidence ledger is the trust source.** Team aliases and league
  equivalences are learned from shared fixtures and Betradar ids, then persisted
  in `config/generated/mapping_evidence.json`. The reviewed allowlist and
  `config/team_alias_reviewed.json` are migration input only; the default
  pipeline never asks a person to approve a pair.
- **Lossless name rules are deterministic, not fuzzy guesses.** A leading or
  trailing club designator (`FC Liefering` / `Liefering`), a token abbreviation
  (`Man Utd` / `Manchester Utd`, `Dynamo D` / `Dynamo Dresden`), or a
  punctuation-only difference (`Shimizu S-Pulse` / `Shimizu S Pulse`) is
  accepted. A shared city token is not enough: `Manchester Utd` /
  `Manchester City` is rejected.
- **The group, not its first member, proves identity.** A candidate can be
  proved by the group's canonical league or by any supporting member. A generic
  league name (`bundesliga`) is fingerprinted by its team set and resolved per
  fixture against a country-qualified spelling.
- **Links are a machine fact.** It is never by a human approval that `deep_link_verified` is set; only `scripts/verify_deeplinks.py` or `POST /api/verify-links`, after a real browser check, may set it.
- **An unmapped league name does not block an exact fixture.** When at least one
  side's league is unmapped, the pair passes the league check only if both teams
  match exactly (raw spellings, no alias), the kickoff is inside the verified
  window and the categories agree — recorded as `league_unmapped_teams_exact`
  evidence. Two mapped leagues that differ still reject.
- **A book that declares no per-event route is verified on identity alone.** The
  eight books declaring `supports_event_id: false` in
  `config/bookmaker_deeplinks.json` have no per-event URL to prove, so the
  declaration is the proof and the group carries a `no_event_link` evidence note
  instead of a reason. A book with no declaration at all is refused: the gate
  fails safe, because an absent declaration is silence rather than proof of
  absence.
- **A shared Betradar id proves identity.** MDShop, Admiralbet, SportPlus and
  WWIN carry the provider's match id. Two listings with the same non-empty id
  pass the league and team checks whatever their names (evidence reason
  `betradar_id`); kickoff, category and link checks still apply. Two different
  ids reject with `betradar_mismatch`.

### Stage 2 — AI proposals (optional)

`engine/ai.py` is consulted only about pairings the rules could not settle, and
only to rank them for Diagnostics. It cannot create a pairing, cannot approve
one, and its answer is never a confidence: a "same event" answer raises a queue
entry's position and nothing else. A negative verdict sets the confidence to 0
and says "AI says not the same event".

| Variable | Default | Meaning |
|---|---|---|
| `AI_API_KEY` | *(empty)* | API key. Unset means the AI stage is never entered. |
| `AI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible base URL (Ollama, LM Studio, a gateway). |
| `AI_MODEL` | `gpt-4o-mini` | Model id. |

### Diagnostics queue

Pairings the gate refused are collected every scan into a per-feed queue
(`pending_candidates` for prematch, `pending_live_candidates` for live, so one
feed's scan never wipes the other's) and shown in the dashboard's
**Diagnostics** tab for the feed on screen. There is no dedicated URL:
Diagnostics is the second tab of the dashboard, so open
`http://localhost:8000` and click **Diagnostics**. It is populated by
`GET /api/candidates?mode=prematch|live` and is read-only: there is no approve
or reject endpoint. The evidence ledger learns team, league and market spellings
automatically on every scan; the tab exists so an operator can inspect what the
gate refused and why.

### Deep-link verification

`scripts/verify_deeplinks.py` proves a bookmaker's per-event links with real
browser navigations. It reads `cache/last_scan.json`, so run a scan first:

```bash
python scripts/verify_deeplinks.py mozzartbet --limit 3
python scripts/verify_deeplinks.py --mode live --limit 20
python scripts/verify_deeplinks.py mozzartbet --limit 20 --offset 20
```

The script writes verdicts to `cache/deep_link_verifications.json`; the next scan
reads that store. It is deliberately not part of a scan because each event costs
a real browser navigation.

**A sweep advances; it is not a one-shot operation.** `build_targets` takes
`settled` (event ids the caller has already decided) and `offset` (a positional
resume, for a caller with no store of its own — which is the CLI), and the
`settled` ids are skipped *before* the window is cut, so a call spends its whole
budget on events nobody has looked at. `POST /api/verify-links` fills `settled`
itself from `cache/deep_link_decisions.json`, so its caller keeps no cursor.
Every response echoes `remaining`, and once a book is fully decided the call
reports `remaining: 0` and checks nothing.

**A sweep does converge.** Both stores must outlive one pass. The proof is the longer of the two:
`DEEP_LINK_VERIFICATION_TTL_SECONDS` (24h) outlives a pass, while
`DEEP_LINK_DECISION_TTL_SECONDS` (6h) only needs to outlive it, because a
decision says "a check completed" and carries no verdict. The numbers come from
a measured 92-minute pass over Mozzartbet's published events; re-measure the
sweep before trusting the headroom.

### Fixed defects, and what keeps them fixed

Two live-mode defects were measured and recorded in-repo on 2026-09-25 and have
since been fixed. Each now has a regression test instead of a tripwire.

- **`premier_kladionica` live BTTS.** The live feed names the block
  `LIVE - OBA TIMA DAJU GOL` while prematch uses `OBA DAJU GOL`, so the parser
  compared both modes against the prematch spelling and the registry's live row
  was unreachable. The parser now matches per mode (`NAME_BTTS` /
  `NAME_BTTS_LIVE`); `tests/test_market_fixtures.py` checks both modes against
  the captured payloads.
- **NSoft live window (`mdshop`, `admiralbet`).** NSoft filters events by
  kickoff against `dateFrom`, and both scrapers built the live request with
  `dateFrom=now`, so already-started in-play games were filtered out. At
  2026-09-25 17:00 UTC that request returned no events while 35 live football events
  were available once the window moved back 12 hours. Both scrapers now take
  their window from `scrapers.common.nsoft_event_window`, and
  `tests/test_live_mode.py` pins the window each scraper requests.

### Re-verifying a surebet before betting

The bet slip's **Verify** button calls `POST /api/verify`. That re-scrapes only
the books in the surebet, runs the same pipeline (stored link proofs applied,
certainty gate, verified groups only), and re-prices the exact outcomes the
surebet was built on — the same line and the same 1X2/double-chance partition,
in the cached home/away frame even if a book now lists the fixture reversed.
`still_profitable` is true for any remaining positive margin;
`meets_min_profit` says whether it still clears `MIN_PROFIT_PERCENT`.

## Project layout

| Path | Responsibility |
|---|---|
| `main.py` | Starts uvicorn on `HOST`/`PORT`. |
| `server/` | FastAPI app (`app.py`), all `/api/*` routes and scan orchestration (`api.py`), scheduling and mapping coverage. |
| `scrapers/` | One module per bookmaker. `base.py` holds the shared Playwright launcher and HTTP retry; `common.py` holds shared parsing, windows and deep-link helpers. |
| `engine/` | Normalization, name/league resolution, mapping learning, matching, the certainty gate, market registry, price guard and arbitrage pricing. |
| `models/schemas.py` | Pydantic models shared by every layer. |
| `config/` | Runtime settings, bookmaker and market registries, deep-link declarations, league/team mappings, and the generated evidence ledger. |
| `frontend/` | Static dashboard served at `/`; no bundler. |
| `scripts/` | Operator tools for deep-link checks, fixture capture, mapping derivation and `MARKET_MAPPING.md` generation. |
| `tests/` | Offline pytest suite; `tests/fixtures/markets/` holds captured bookmaker payloads. |
| `cache/` | Gitignored runtime state: last scan per feed, history, link proofs and decisions. |
| `PLAN.md` | Open work and the autonomy contract. |
| `docs/HANDOFF.md` | Design history and remaining work. |

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
- Frontend tests execute the shipped JavaScript under Node 22. Without Node they
  skip, so a green local run can hide frontend breakage.
- `tests/test_readme_claims.py` checks the factual claims in this file against
  the code. If you change behavior documented here, update the README and run
  that file specifically.
- `MARKET_MAPPING.md` is generated from `config/bookmaker_markets.json` between
  marker comments. Regenerate it; never hand-edit the generated block.
- `tests/fixtures/e2e_certified/` is frozen. Do not edit or re-capture it.

## Operator tools

```bash
# Learn league names and team spellings from fixtures the books share.
# --report writes every proposal with its fixtures; --apply writes config/.
python scripts/derive_mappings.py cache/last_scan.json --report proposals.json
python scripts/derive_mappings.py cache/last_scan.json --apply

# Regenerate the ID tables in MARKET_MAPPING.md, or fail if they are stale.
python scripts/generate_market_mapping_doc.py
python scripts/generate_market_mapping_doc.py --check
```

## Adding bookmakers, markets and names

- **Bookmaker:** add `scrapers/<book>.py`, register it in `SCRAPERS` and
  `BOOKMAKERS`, add its deep-link declaration, market registry rows and captured
  fixtures, then add parser and gate tests. Mark it as a Playwright book only if
  it really needs a browser.
- **Market:** add the source ids and labels to `config/bookmaker_markets.json`,
  capture a payload under `tests/fixtures/markets/`, add a registry test, and
  regenerate `MARKET_MAPPING.md`.
- **League and team names:** do not hand-edit
  `config/team_alias_allowlist.json`, `config/league_mappings.json` or
  `config/league_equivalences.json`. The ledger learns from scans; use
  `scripts/derive_mappings.py` for bulk changes and inspect the Diagnostics tab
  to see what the gate refused.

## Notes

- All odds are European decimal odds. Stakes are calculated for
  `DEFAULT_INVESTMENT` and can be adjusted in the dashboard.
- `MIN_PROFIT_PERCENT` is the display floor for a surebet; `DUST_PROFIT_PERCENT`
  is the lower bound for low-value "dust" opportunities shown separately.
- Mozzartbet, Admiralbet and WWIN use Playwright sessions to fetch their live
  feeds. MDShop, MBet, SportPlus, Betole, Premier Kladionica and MaxBet use
  direct HTTP.
- EVLBet is disabled by default because its feed returns no football events.
- The engine enforces at most one leg per bookmaker and at most one leg per
  price source. MDShop and Admiralbet share the NSoft feed.
- This is a research tool. It does not log in to bookmakers, move money or place
  bets.
