# Record-only and paper-trading mode (P3-7)

The scanner is advisory and **never places a bet**. These two modes make that
boundary explicit and let an operator measure what the scanner saw without
presenting a recorded price as a live opportunity.

| Run mode | What it publishes | What it stores |
|---|---|---|
| `advisory` (default) | The normal live surebet list | Nothing new; behavior is unchanged |
| `record_only` | **No live surebets** | One compact snapshot per verified opportunity |
| `paper` | **No live surebets** | Compact snapshots plus virtual positions and marks |

## Running a scan

```bash
# Normal advisory scan; this is the default and is unchanged.
curl -s -X POST 'http://127.0.0.1:8000/api/scan?mode=prematch'

# Record what this scan priced, but show no live surebet.
curl -s -X POST 'http://127.0.0.1:8000/api/scan?mode=prematch&run_mode=record_only'

# Record and maintain a virtual paper bankroll.
curl -s -X POST 'http://127.0.0.1:8000/api/scan?mode=prematch&run_mode=paper'
```

The dashboard's **Settings → Scanning → Run mode** selector sends the same
parameter. The choice is stored in the browser, not in the server's settings.

A non-advisory scan still updates matches and diagnostic groups, but writes an
empty live surebet list for that feed. `/api/results` reports `run_mode` and
`recorded_opportunities`, and the dashboard shows a banner saying no live
surebet is shown. The next advisory scan returns to the normal path.

## What a record contains

`GET /api/paper/opportunities?days=30&limit=200` returns compact rows:

- event identity: sport, teams, league, kickoff and a stable key;
- market, line, feed mode and scan timestamp;
- the gate verdict (`verified` — anything else never reached pricing);
- `profit_percent` and `total_margin`;
- the best recorded odds and the bookmaker that quoted them;
- one leg per bookmaker with its outcome label and odds.

This is a bounded ledger, not a second copy of the scan cache. It deliberately
does not store the full match report, raw HTML, evidence payloads or every
non-crossing board.

## Paper positions and marks

In `paper` mode a scan opens at most one virtual position per stable key. Entry
uses the recorded odds and a fixed paper stake (`PAPER_STAKE`, 100 by default).
The next paper scan marks the position:

- **available**: every entry leg still has a quoted price. `clv` is the
  entry-stake-weighted `entry_odds / current_odds - 1` (the same direction as
  the manual bet log).
- **unavailable**: at least one entry leg is gone or the opportunity no longer
  crosses. The position stays open; it is not silently re-priced.

`GET /api/paper/positions` lists positions. The mark is a **next available
price**, not a true closing price and not a settlement.

## Simulated fills (N2-2)

A paper position no longer assumes every leg fills at the planned stake. On
each mark the store applies deterministic rules and records one status per leg:

| Status | When | Filled stake |
|---|---|---|
| `filled` | the price is still quoted and within tolerance, and the planned stake is at or below the book's advisory cap | planned stake |
| `partial` | the price is unchanged but the planned stake exceeds `BOOK_STAKE_LIMITS[book]` | the advisory cap |
| `rejected` | the current price moved by more than `PAPER_FILL_PRICE_TOLERANCE` | `0` |
| `missing` | the leg is no longer quoted, or the opportunity disappeared | `0` |

The rules are probability-free and deterministic. There is no model of an
account accepting or rejecting a bet, no cash movement and no bookmaker
interaction. The advisory cap comes from the same `BOOK_STAKE_LIMITS` /
`bookmaker_risk.json` values the slip shows; a fill does not invent a new odds.

Settings:

| Variable | Default | Meaning |
|---|---:|---|
| `PAPER_FILL_ENABLED` | `true` | Apply rejection/partial rules. `false` keeps the old "every leg fills at the entry stake" behavior. |
| `PAPER_FILL_PRICE_TOLERANCE` | `0.0` | Relative price move allowed before a leg is rejected. `0` rejects any move. |
| `PAPER_FILL_PARTIAL_ENABLED` | `true` | Allow a stake above the book cap to fill partially at the cap. |

The mark includes `fills` (per leg: planned/filled stake, entry/current odds and
reason), `fill_complete` (every leg `filled` or `partial`), `filled_stake`,
`planned_stake` and `worst_case_profit`. The worst case is the minimum payout
across the recorded outcomes at the filled stakes, minus the filled stake; a
rejected or missing outcome contributes a zero payout, so a partial hedge can
be negative. With no filled stake it is `null`, not zero.

`GET /api/paper/summary` keeps the two numbers separate:

- `execution_adjusted`: open positions with a complete fill record
  (`filled`/`partial` only). It reports the filled stake, worst-case profit, ROI
  and its own denominator. It is `null` when no position has a complete fill
  record, so an unfilled position is never called profitable.
- `simulated_open`: the optimistic **“if all filled”** number, explicitly
  labelled and using all open positions at their entry odds.

Settling a marked position uses the per-leg `filled_stake`; an unmarked position
falls back to the planned paper stake, which preserves the pre-N2-2 behavior.

A paper position can be settled manually with the same leg results the manual
bet log uses:

```bash
curl -s -X POST http://127.0.0.1:8000/api/paper/positions/<id>/settle \
  -H 'Content-Type: application/json' \
  -d '{"legs":[
    {"outcome_label":"1","result":"won"},
    {"outcome_label":"X","result":"lost"},
    {"outcome_label":"2","result":"lost"}
  ]}'
```

A missing leg result leaves the position open. A void leg returns its paper
stake. No match-result feed is assumed.

## Summary and denominators

`GET /api/paper/summary?days=30` returns:

- `opportunities_recorded`: compact rows in the window;
- `positions`, `open_positions`, `settled_positions`;
- `staked`, `profit`, `roi`, `bankroll`: **settled positions only**;
- `simulated_open`: open positions at their entry odds, if every leg filled;
- `execution_adjusted`: complete fill records only, with filled stake,
  worst-case profit and ROI;
- `fill_rules`: whether fills, partial fills and the price tolerance are active;
- `hit_rate`: marked positions whose entry legs were all still quoted, over
  `hit_rate_positions`;
- `clv`, `clv_legs`: entry-stake-weighted next-price CLV, only for legs with a
  mark;
- `denominators` and `no_bet_placed: true` on every response.

`roi` is `null` until a paper position is settled. `clv` is `null` until a
position is marked. A number without its denominator is not reported as one.

## Dashboard (N2-1)

The **Paper** tab is read-mostly and advisory. It shows summary tiles for
recorded rows, positions, open/settled, ROI, hit rate and CLV, each with its
denominator. The ledger is filtered by run mode, feed and position status, and
both tables page with Previous/Next. The `no_bet_placed` notice is always
visible; the pane has no live-slip or copy action.

Open positions carry one result selector per entry leg and a **Settle** button.
Settling posts the same leg results as the manual bet log; a missing result
leaves the position open. An unavailable mark shows its reason (for example
"opportunity disappeared from the next scan"), so a missing price is not
mistaken for a settlement.

## CSV export

`GET /api/paper/export.csv?days=30&run_mode=&feed_mode=&status=` returns one CSV
covering both stores. The first column is `kind` (`opportunity` or `position`).
Every field the dashboard displays is included, including the leg list as
`legs_json`, the mark fields and the mark reason. The export uses the same
filters as the tables and is not capped by the current page.

```bash
curl -fsS 'http://127.0.0.1:8000/api/paper/export.csv?days=30' -o paper.csv
```

## Store size and retention

`/api/paper/summary` includes a `store` block: the SQLite bytes, row counts for
`recorded_opportunities` and `paper_positions`, the N1-1 retention window/row
cap, and the last maintenance time. The Paper tab prints the same values under
the tables. Retention is bounded by `RETENTION_PAPER_DAYS` and
`RETENTION_PAPER_MAX_ROWS`; see `docs/STORAGE.md`.

## Limitations

- **No bet is placed.** The paper bankroll is a local simulation; there is no
  login, ticket, stake acceptance or money movement.
- **Fills are simulated, not proven.** The default now rejects a moved price,
  treats a disappeared leg as missing and caps a stake at the book's advisory
  limit, but this is still a deterministic model. It does not prove a real
  bookmaker would accept the stake.
- **No stake limits or account effects.** The simulation does not model a book
  rejecting a stake, limiting an account or voiding a palpable error. The cap is
  an advisory paper rule, not an account action.
- **CLV is a next-scan mark.** It is not the true closing price and should not
  be compared with a settled bet's recorded closing line.
- **The live advisory path is unchanged** when `run_mode` is omitted or
  `advisory`. Schedulers keep using advisory scans.
