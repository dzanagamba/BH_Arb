# Surebet Scanner — Muse 12 🎯

A web-based arbitrage betting detection tool for the Bosnian market.

> **Open work** lives in [`PLAN.md`](PLAN.md) §4 *TODO*. The design history of
> the mapping-certainty rework is in [`docs/HANDOFF.md`](docs/HANDOFF.md).

> ### Which groups reach `verified`
>
> A surebet is only ever shown for a match group the certainty gate has
> **`verified`**, and `verified` includes the link half of the claim. Which
> proofs satisfy that half is decided per book, by the book's own declaration in
> `config/bookmaker_deeplinks.json`:
>
> * **The book declares that it has no per-event route**
>   (`supports_event_id: false`) — eight of the ten books. There is no
>   per-event URL to prove, so the declaration is itself the proof: the group
>   records a `no_event_link` evidence note and is verified on identity alone —
>   league, kickoff, category, teams, orientation. A book with no declaration at
>   all is *not* accepted this way: the gate fails safe and treats its link as
>   unproven.
> * **The book declares a per-event route** (`supports_event_id: true`) — the
>   route has to be proven by a real browser check. Mozzartbet and MaxBet declare
>   one, and their path-based patterns were browser-proven on 2026-11-03 on three
>   sampled events each: the path embeds the book's own event id, and the feed
>   supplies that id for every listing. A listing with an event id is therefore
>   verified with a `route_pattern_verified` note; a listing with no event id
>   still blocks. MDShop's and Admiralbet's declared `?event=<id>` routes are
>   **inert** — the served page is byte-identical to the plain football page and
>   the id appears nowhere in it — so on 2026-10-20 both were re-declared
>   `supports_event_id: false` with a dated note, and they now verify on identity
>   like the other route-less books.
>
> So what blocks `verified` today is identity, not links: league names the
> mappings do not equate, team spellings no one has approved, and kickoff
> deltas. Read [Match & mapping certainty](#match--mapping-certainty) before
> concluding anything about yield from a scan.
>
> **Re-check this claim yourself.** The part the repo can reproduce is *which
> books declare a per-event route at all* — two, `mozzartbet` and `maxbet`, in
> `config/bookmaker_deeplinks.json`:
>
> ```bash
> python -c "import json;d=json.load(open('config/bookmaker_deeplinks.json'));print([b for b,v in d.items() if v.get('supports_event_id') is True])"
> ```
>
> That the NSoft routes are *inert* is a measurement, not a repo fact, taken on
> 2026-09-25 and re-checked in a browser on 2026-10-20: see
> `scripts/verify_deeplinks.py` (command in *Tools* below), whose module
> docstring records the findings.
> Re-running it costs one browser navigation per event and a full pass over one
> book takes about 92 minutes, so treat the inertness as a dated measurement to
> re-confirm, not a permanent property. A sweep does converge — one call after
> the last reports nothing left to check — but only because
> `DEEP_LINK_DECISION_TTL_SECONDS` is longer than a pass; see *Tools*. The doc
> claims in this section are themselves checked by `tests/test_readme_claims.py`,
> so a claim here that stops matching the code fails the suite.

## What it does

1. Scrapes football odds from Bosnian bookmakers: Mozzartbet, MDShop, Admiralbet, MBet, SportPlus, Premier Kladionica, WWIN, MaxBet and Betole are on; EVLBet is off by default (EVLBet's feed returns no football events and has no captured payload)
2. Learns team, league and market names from the fixtures the books share on every scan (Bosnian diacritics, Cyrillic, abbreviations, youth/reserve/women markers), and keeps the evidence in a provenance ledger
3. Groups the same real-world event across bookmakers, and only a group the certainty gate *proves* is the same event is ever priced
4. Detects arbitrage (surebet) opportunities where odds guarantee a profit regardless of match outcome (enforcing strict 1-bet-per-bookmaker rule)
5. Helps place one: the bet slip re-checks the odds, orders the legs, rounds the stakes and re-plans the rest when a price moves (see *Using the dashboard*)
6. Supports two feeds — **Upcoming** (prematch) and **Live** (in-play) — each with its own cache, review queue and history

## Project layout

| Path | What lives there |
|---|---|
| `main.py` | Entry point — starts uvicorn on `HOST`/`PORT` |
| `server/` | FastAPI app (`app.py`) and every `/api/*` route plus scan orchestration (`api.py`) |
| `scrapers/` | One module per bookmaker; `base.py` holds the shared Playwright launcher and httpx retry, `common.py` the shared parsing and deep-link helpers |
| `engine/` | `normalizer.py` (names), `matcher.py` + `certainty.py` (grouping and the gate), `market_registry.py`, `arbitrage.py` (pricing and stakes), `ai.py` (optional candidate ranking) |
| `models/schemas.py` | Pydantic models shared by all of the above |
| `config/` | `settings.py` plus the JSON mappings, market registry, deep-link declarations and alias allowlist |
| `frontend/` | The static dashboard served at `/` |
| `scripts/` | Operator tools: deep-link verification, fixture capture, mapping generators, the `MARKET_MAPPING.md` generator |
| `tests/` | pytest suite; `tests/fixtures/markets/` holds captured bookmaker payloads |

## Setup

### Prerequisites
- Python 3.11+
- pip

### Install

```bash
git clone https://github.com/dzanagamba/surebet-muse12.git
cd surebet-muse12

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Run

```bash
python main.py
```

- **Dashboard**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

  Two of its fields exist because a safety gate depends on a config file the
  process reads once. `deep_link_declarations` echoes the
  `{book: supports_event_id}` map **the gate is currently using** — the config is
  cached in memory on first use and never invalidated, so editing
  `config/bookmaker_deeplinks.json` needs a restart, and a book with
  `"configured": false` is one the gate is silently failing safe on.
  `unverified_links` counts matches whose link is unproven *and can still block*,
  using the gate's own predicate: a book that declares no per-event route is
  excluded, and a book with no declaration is included, because that is the case
  where the gate refuses everything and this counter is the only thing that says
  so.

## Using the dashboard

Open http://localhost:8000 and press **Scan now** (a prematch scan takes about
three minutes).

* **Surebets** — the list on the left, best profit first (`j`/`k` move through
  it). Picking one opens the **bet slip** on the right, which:
  1. re-checks the odds at every bookmaker in it (`POST /api/verify`) and says
     plainly whether it is still a surebet; a check older than two minutes
     (30 s live) is marked stale;
  2. lists the legs in the order to place them — longest odds first, since that
     price is the one most likely to move or be limited;
  3. gives each leg's stake rounded to whole KM (changeable in Settings), the
     profit *after* rounding, and a warning when rounding eats the edge;
  4. shows how each bookmaker spells the match and copies it for the site's
     search, since most books have no per-event page; **Open ↗** opens the book;
  5. after you place a leg, type the odds you actually got and press
     **Mark placed** — the remaining stakes are re-planned to cover it, and the
     slip turns red if the bet is no longer an arbitrage;
  6. lists why the scanner trusts the legs are the same match.
* **Review** — pairings the gate refused because two books spell a team
  differently. Each shows how alike the names are; **Select strong** ticks the
  ones whose approval clears every blocker, and **Approve selected** writes them
  to the alias allowlist after a confirmation. The next scan uses them.
* **History** — every scan's counts and errors.
* **Settings** (gear) — default stake, rounding, auto-rescan, alert chime,
  which bookmakers to scan, experimental markets, and the health line.

## Configuration

Set these in `.env` (copy `.env.example`):
- `HOST` / `PORT` — bind address and port (default `127.0.0.1` / `8000`; set `HOST=0.0.0.0` only behind a firewall and an API key)
- `CORS_ORIGINS` — comma-separated origins for a separate frontend; empty means same-origin only
- `API_KEY` — when set, every state-changing endpoint (scan, toggles, recalculate, verify, verify-links, candidate decisions) and `GET /api/history` require an `X-API-Key` header. Unset by default, so set it before exposing the server beyond localhost
- `SCAN_RATE_LIMIT` — max scans a client may trigger per minute (default `3`)
- `HEADLESS` — `true` for background browser execution (default), or `false` to view browser windows (useful if CAPTCHA solving is required)
- `LOG_LEVEL` — `DEBUG`, `INFO` (default), `WARNING` or `ERROR`
- `VERIFY_SSL` — `True` to enforce TLS certificate verification on direct httpx API calls (default `False`)

Edit `config/settings.py` to change:
- `MIN_PROFIT_PERCENT` — Minimum profit % to show as a surebet (default: 0.5%)
- `KICKOFF_WINDOW_MINUTES` — Max kickoff time difference to group matches (default: 120)
- `DEFAULT_INVESTMENT` — Default total investment for stake calculation (default: 100 BAM)
- Bookmaker `enabled` status — Toggle individual bookmakers ON/OFF via config or the web UI

## Development

```bash
# Dev tools first: pip install -r requirements-dev.txt
# Run the test suite (CI runs this plus the commands below on every push:
# .github/workflows/ci.yml)
python -m pytest
python scripts/generate_market_mapping_doc.py --check

# Lint / type check
python -m ruff check .
python -m mypy .
```

## Match & mapping certainty

Since the mapping rework, "these two listings are the same match" is no longer a
fuzzy score with a threshold. It is a claim that has to be proven, and the
certainty gate is the only thing that decides it.

### The two stages

**Stage 1 — rules (`engine/certainty.py`, used by `engine/matcher.py`).**
Every candidate pairing is evaluated against hard, deterministic gates. Each gate
appends a `MatchEvidence` record explaining what it found, and the pair's status
follows from the reasons left over:

| Status | Meaning | Reason vocabulary |
|---|---|---|
| `verified` | **Zero** reasons. Every part of the claim is proven, links included. These are the only groups that reach arbitrage. | — |
| `suggested` | At least one reason is outstanding — the identity is plausible but incomplete. Not priced; queued for review. | `kickoff_missing`, `kickoff_delta`, `team_unresolved`, `link_unverified`, `no_event_link` |
| `rejected` | A hard gate contradicts the claim. | `league_mismatch`, `category_mismatch`, `betradar_mismatch` |

The reason strings above are the vocabulary the gate actually emits, and
`tests/test_readme_claims.py` proves it by *running* the gate over one broken
claim per reason and reading the results back — so a reason added or removed in
`engine/certainty.py` fails this table. One wrinkle worth knowing:
`HARD_REJECT_REASONS` — named as a symbol rather than cited by line, because a
line number here is stale the moment the module's imports change — also lists
`orientation_unresolved`, which the gate never emits; the unresolvable-orientation
case is reported as `team_unresolved`. Until that entry is either produced or
deleted, treat `rejected` as the reasons above except `orientation_unresolved`.

Five rules inside stage 1 matter more than the rest:

* **The reviewed alias allowlist is the only auto-accepted fuzzy path.** A pair
  whose raw team names differ is refused unless the pair appears in
  `config/team_alias_allowlist.json` (and scores at least 90 similarity) or in
  `config/team_alias_reviewed.json`, the pairs a person reviewed from fixture
  evidence, which carry no similarity floor ("Man.Utd" / "Manchester United").
  Either way league, kickoff and category must still agree. A canonical-name
  collision on its own is never enough.
* **Links are a machine fact, not a human one.** `deep_link_verified` may only be
  set by an actual browser check (`scripts/verify_deeplinks.py`), never by a
  human approval.
* **An unmapped league name does not block an exact fixture.** Bookmakers name
  competitions inconsistently ("Liga Two", "ENGLAND 2", "OBOS Liga"), and a
  name no mapping covers can never equal anything. When at least one side's
  league is unmapped, the pair passes the league check only if both teams match
  exactly (raw spellings, no alias), the kickoff is inside the verified window
  and the categories agree — recorded as `league_unmapped_teams_exact`
  evidence. Two *mapped* leagues that differ still reject.
* **A book that declares no per-event route is verified on identity alone.**
  The eight books declaring `supports_event_id: false` in
  `config/bookmaker_deeplinks.json` have no per-event URL to prove, so the
  declaration is the proof and the group carries a `no_event_link` evidence note
  instead of a reason. A book with **no declaration at all** is refused: the gate
  fails safe, because an absent declaration is silence rather than proof of
  absence.
* **A shared Betradar id proves identity.** MDShop, Admiralbet, SportPlus and
  WWIN carry the provider's match id. Two listings with the same non-empty id
  pass the league and team checks whatever their names (evidence reason
  `betradar_id`); kickoff, category and link checks still apply. Two different
  ids reject with `betradar_mismatch`.

**Stage 2 — AI proposals (`engine/ai.py`, used by `server/api.py`).** The AI is
consulted only about pairings the rules could not settle, and only to **rank**
them for a human. It cannot create a pairing, cannot approve one, and its
verdict is never a confidence: a "same event" answer raises a queue entry's
position and nothing else. A negative verdict sets the confidence to 0 and says
"AI says not the same event".

### The review queue

Pairings the gate refused are collected every scan into a per-feed queue
(`pending_candidates` for prematch, `pending_live_candidates` for live, so one
feed's scan never wipes the other's) and shown in the dashboard's **Review** tab
for the feed on screen. There is no dedicated URL: the Review
tab is the second tab of the dashboard, so open `http://localhost:8000` and click
**Review**. It is populated by `GET /api/candidates?mode=prematch|live`, and deciding an entry is
`POST /api/candidates/{candidate_id}/approve` or
`POST /api/candidates/{candidate_id}/reject`.

Approval grants a **team alias** and nothing else — one cross-bookmaker spelling
pair per team slot, written to `config/team_alias_allowlist.json` — so the next
scan's rules can verify the identity half of the claim. The link half stays
closed, and a decided candidate never re-enters the queue.

### Environment variables

All three are optional. With `AI_API_KEY` unset the AI stage is never entered and
the whole system runs on rules plus human review.

| Variable | Default | Meaning |
|---|---|---|
| `AI_API_KEY` | *(empty)* | API key. Unset ⇒ `MatchAI.available` is `False` and no AI adapter is built. |
| `AI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible base URL (Ollama, LM Studio, a gateway). |
| `AI_MODEL` | `gpt-4o-mini` | Model id. |

### Tools

```bash
# Rewrite the generated ID tables in MARKET_MAPPING.md from
# config/bookmaker_markets.json, or fail if they are stale.
python scripts/generate_market_mapping_doc.py
python scripts/generate_market_mapping_doc.py --check

# Learn league names and team spellings from fixtures the books share (same
# two teams + kickoff, or the same Betradar match id). Prints a summary; --report
# writes every proposal with its fixtures; --apply writes config/league_mappings.json
# and config/team_alias_allowlist.json. Run it on a fresh scan now and then.
python scripts/derive_mappings.py cache/last_scan.json --report proposals.json
python scripts/derive_mappings.py cache/last_scan.json --apply

# Prove a bookmaker's per-event deep links, one browser navigation per event.
# Reads cache/last_scan.json, so run a scan first. Defaults to every book that
# declares a per-event route; --limit defaults to 3, --offset defaults to 0.
python scripts/verify_deeplinks.py mozzartbet --limit 3
python scripts/verify_deeplinks.py --mode live --limit 20
python scripts/verify_deeplinks.py mozzartbet --limit 20 --offset 20
```

`verify_deeplinks.py` is deliberately **not** part of a scan: each event costs a
real browser navigation. It writes its verdicts into
`cache/deep_link_verifications.json`, and the next scan reads that store.

**A sweep advances — it is not a one-shot operation.** `build_targets` takes
`settled` (event ids the caller has already decided) and `offset` (a positional
resume, for a caller with no store of its own — which is the CLI), and the
`settled` ids are skipped *before* the window is cut, so a call spends its whole
budget on events nobody has looked at. `POST /api/verify-links` fills `settled`
itself from the events it has already decided, which it keeps in
`cache/deep_link_decisions.json`, so its caller keeps no cursor. Every response
echoes `remaining` — the undecided events the run did not reach — and once a book
is fully decided the call reports `remaining: 0` and checks nothing, so a sweep
loop knows when to stop. Only a completed check settles an event: a navigation
that errored is not a verdict, so it is offered again on the next call. The
endpoint stays rate-limited and capped for the same reason.

**Both store lifetimes must outlast one pass, and they are not equal.** A proof
in `cache/deep_link_verifications.json` is what lets a group reach `verified`, so
if it expires before the sweep that writes it finishes, the sweep can never hold a
complete set and no surebet can exist — which is exactly what happened: a pass over
Mozzartbet's 1,236 published events measured at 92 minutes against a one-hour
proof lifetime, and 412 stored proofs aged out with 0 of 4,260 cached matches
carrying `deep_link_verified`. So `DEEP_LINK_VERIFICATION_TTL_SECONDS` (24h) is
longer than a pass by 15.6x, and `DEEP_LINK_DECISION_TTL_SECONDS` (6h) is longer
than one by 3.9x — a decision carries no verdict, only "a check completed", so it
needs to outlive a pass and nothing more, and being too short has a functional
cost as well as a safety one: a book whose first decisions expire mid-pass is
offered them again before the pass reaches the back, so it walks in circles. The
proof is the longer of the two because it is the only one of the two that grants
anything. Both numbers are re-derived from that measurement by
`tests/test_verify_links.py::test_every_link_lifetime_outlives_a_full_pass_over_the_largest_book`,
and re-measure the sweep before trusting them: the per-event cost is a real browser
navigation, so the headroom is a number of events, not a promise.

### Fixed defects, and what keeps them fixed

Two live-mode defects were measured and recorded in-repo on 2026-09-25 and have
since been fixed. Each now has a regression test instead of a tripwire.

* **`premier_kladionica` live BTTS.** The live feed names the block
  `LIVE - OBA TIMA DAJU GOL` while prematch uses `OBA DAJU GOL`, and the parser
  compared both modes against the prematch spelling, so the registry's live row
  was unreachable (it was guarded by a strict xfail whose XPASS would fail the
  suite). The parser now matches per mode (`NAME_BTTS` / `NAME_BTTS_LIVE`); the
  registry row was deliberately not renamed, since prematch really is spelled the
  other way. `tests/test_market_fixtures.py` checks both modes against the
  captured payloads.
* **NSoft live window (`mdshop`, `admiralbet`).** NSoft filters events by
  kickoff against `dateFrom`, and both scrapers built the live request with
  `dateFrom=now`, so every already-started in-play game was filtered out. At
  2026-09-25 17:00 UTC that request returned `{"events": []}` while
  35 live football events were available — and 35 the moment `dateFrom` was
  moved back 12 hours. Both scrapers now take their window from one shared helper,
  `scrapers.common.nsoft_event_window`, which looks back 12 hours for live (the
  window the committed live fixtures were captured with) and forward 14 days for
  prematch. `tests/test_live_mode.py` pins the window each scraper requests.

### Re-verifying a surebet before betting

The card's **Verify** button calls `POST /api/verify`, which re-scrapes only the
books in that surebet, runs them through the same pipeline a scan uses (stored
link proofs applied, certainty gate, verified groups only) and re-prices the
**exact outcomes the surebet was built on** — the same line, the same 1X2/double
chance partition, in the cached home/away frame even if a book now lists the
fixture reversed. `still_profitable` is true for any remaining positive margin;
`meets_min_profit` says whether it still clears `MIN_PROFIT_PERCENT`.

## Adding more leagues/teams

- Edit `config/league_mappings.json` to add new league name variations
- Edit `config/team_mappings.json` to add new team name variations

## Notes

- Mozzartbet and Admiralbet run hybrid Playwright sessions to bypass Cloudflare protection and fetch live API data
- Direct HTTP scrapers (MDShop, MBet, SportPlus, EVLBet, and Betole's prematch feed) fetch API data directly without browser overhead
- Betole is disabled (`"enabled": False`) by default to save system resources
- All odds are displayed as European decimal odds
- Stakes are calculated for the configured `DEFAULT_INVESTMENT` and can be adjusted live in the dashboard (with optional rounding to whole KM)
- Last scan results — surebets, matches and the match report — are cached to
  `cache/last_scan.json` and restored on startup, for 30 minutes; past that the
  file is discarded rather than replayed. A restored report is re-checked against
  the link store rather than trusted, so a `verified` group survives a restart only
  while every one of its legs still has a fresh proof — a snapshot older than the
  proofs it was decided on is dropped, not shown.
- Verified football market mappings and deliberately excluded offers are documented in `MARKET_MAPPING.md`
