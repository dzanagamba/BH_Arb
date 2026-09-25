# Surebet Scanner — Muse 12 🎯

> **Working repo:** `surebetmuse12` (fresh fork of `dzanagamba/surebet-scanner` @ `7d2d5d8`). See `PLAN.md` for the full P0→P3 roadmap to fix “rare + wrong” surebets.

A web-based arbitrage betting detection tool for the Bosnian market.

> ### ⚠️ Current state: the scanner finds zero surebets, by design
>
> A surebet is only ever shown for a match group the certainty gate has
> **`verified`**, and `verified` requires a proven deep link on *both* sides.
> MDShop's and Admiralbet's declared `?event=<id>` routes are **inert** — the
> served page is byte-identical to the plain football page and the id appears
> nowhere in it — so their links can never be proven and **in production zero
> groups reach `verified` and zero surebets are produced.** Only Mozzartbet's
> link verifies.
>
> This is a bookmaker-side routing fact, not a bug in the code: the gate, the
> registry and the parsers are correct and tested. Read
> [Match & mapping certainty](#match--mapping-certainty) before concluding
> anything about yield from a scan.

## What it does

1. Scrapes football odds from 9 Bosnian bookmakers (Mozzartbet, MDShop, Admiralbet, MBet, SportPlus, EVLBet, Premier Kladionica and WWIN active; Betole disabled by default)
2. Normalizes team/league names (handling Bosnian diacritics, Cyrillic, phonetic transliterations)
3. Matches the same real-world events across bookmakers using multi-dimensional fingerprinting (with home/away swap detection)
4. Detects arbitrage (surebet) opportunities where odds guarantee a profit regardless of match outcome (enforcing strict 1-bet-per-bookmaker rule)
5. Supports two scan modes — **Future Matches** (prematch) and **Live Matches** (in-play) — with a dashboard toggle, per-mode caching, and per-mode history
6. Displays results in a premium dark-themed web dashboard

## Setup

### Prerequisites
- Python 3.11+
- pip

### Install

```bash
cd surebet

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

## Configuration

Edit `config/settings.py` (or `.env`) to change:
- `HEADLESS` — `True` for background browser execution (default), or `False` to view browser windows (useful if CAPTCHA solving is required)
- `VERIFY_SSL` — `True` to enforce TLS certificate verification on direct httpx API calls (default `False`)
- `MIN_PROFIT_PERCENT` — Minimum profit % to show as a surebet (default: 0.5%)
- `KICKOFF_WINDOW_MINUTES` — Max kickoff time difference to group matches (default: 120)
- `DEFAULT_INVESTMENT` — Default total investment for stake calculation (default: 100 BAM)
- Bookmaker `enabled` status — Toggle individual bookmakers ON/OFF via config or the web UI

## Development

```bash
# Run the test suite
python -m pytest

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
| `rejected` | A hard gate contradicts the claim. | `league_mismatch`, `category_mismatch`, `orientation_unresolved` |

Two rules inside stage 1 matter more than the rest:

* **The reviewed alias allowlist is the only auto-accepted fuzzy path.** A pair
  whose raw team names differ is refused unless the pair appears in
  `config/team_alias_allowlist.json`. A canonical-name collision on its own is
  never enough.
* **Links are a machine fact, not a human one.** `deep_link_verified` may only be
  set by an actual browser check (`scripts/verify_deeplinks.py`), never by a
  human approval.

**Stage 2 — AI proposals (`engine/ai.py`, used by `server/api.py`).** The AI is
consulted only about pairings the rules could not settle, and only to **rank**
them for a human. It cannot create a pairing, cannot approve one, and its
verdict is never a confidence: a "same event" answer raises a queue entry's
position and nothing else. A negative verdict sets the confidence to 0 and says
"AI says not the same event".

### The review queue

Pairings the gate refused are collected every scan into `pending_candidates` and
shown in the dashboard's **Review** tab. There is no dedicated URL: the Review
tab is the second tab of the dashboard, so open `http://localhost:8000` and click
**Review**. It is populated by `GET /api/candidates`, and approving or rejecting
an entry is `POST /api/candidates/{candidate_id}/approve` / `.../reject`.

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

# Prove a bookmaker's per-event deep links, one browser navigation per event.
# Reads cache/last_scan.json, so run a scan first. Defaults to every book that
# declares a per-event route; --limit defaults to 3.
python scripts/verify_deeplinks.py mozzartbet --limit 3
python scripts/verify_deeplinks.py --mode live --limit 20
```

`verify_deeplinks.py` is deliberately **not** part of a scan: each event costs a
real browser navigation. It writes its verdicts into
`cache/deep_link_verifications.json`, and the next scan reads that store.

**It is not a one-shot operation.** `build_targets` has no offset, no cursor and
no skip-already-checked, so a repeated call re-checks the same first N events
forever. A per-book sweep over 600+ events cannot converge today; the fix is a
cursor (with one echoed in the response), not a bigger `--limit`. The HTTP
endpoint `POST /api/verify-links` is rate-limited and capped for the same reason.

### Known defects, recorded in-repo

* **`premier_kladionica` live BTTS.** The live feed names the block
  `LIVE - OBA TIMA DAJU GOL` while the parser's `NAME_BTTS` is `OBA DAJU GOL`,
  so the registry's live row is unreachable. Guarded by
  `xfail(strict=True)` in `tests/test_market_fixtures.py`: fixing the parser
  turns it into an **XPASS**, which pytest reports as a **failure**, so the
  parser and the marker cannot drift apart. The fix is to make `NAME_BTTS`
  mode-aware, *not* to rename the registry row.
* **NSoft live window (`mdshop`, `admiralbet`).** NSoft filters events by
  kickoff against `dateFrom`, and the window is built with `dateFrom=now`, so
  every already-started in-play game is filtered out. At 2026-09-25 17:00 UTC the
  request returned `{"events": []}` while 35 live football events were available
  — and 35 the moment `dateFrom` was moved back 12 hours. Both books therefore
  most likely return **no live matches at all** today. Recorded as a
  `KNOWN DEFECT` comment in `scrapers/mdshop.py`; the behaviour is unchanged
  because it needs its own decision.

## Adding more leagues/teams

- Edit `config/league_mappings.json` to add new league name variations
- Edit `config/team_mappings.json` to add new team name variations

## Notes

- Mozzartbet and Admiralbet run hybrid Playwright sessions to bypass Cloudflare protection and fetch live API data
- Direct HTTP scrapers (MDShop, MBet, SportPlus, EVLBet, and Betole's prematch feed) fetch API data directly without browser overhead
- Betole is disabled (`"enabled": False`) by default to save system resources
- All odds are displayed as European decimal odds
- Stakes are calculated for the configured `DEFAULT_INVESTMENT` and can be adjusted live in the dashboard (with optional rounding to whole KM)
- Last scan results are cached to `cache/last_scan.json` and restored on startup
- Verified football market mappings and deliberately excluded offers are documented in `MARKET_MAPPING.md`
