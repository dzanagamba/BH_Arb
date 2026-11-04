# Bet log, bankroll and CLV (P3-2)

The scanner **never places a bet**. This is a manual record of what the operator
says was actually accepted, used to measure whether the edges are real.

## Logging

The slip has **Log bet**. It posts the current plan to `POST /api/bets`:
surebet id, feed, match, market, investment and one leg per bookmaker with
planned odds/stake and accepted odds/stake. The accepted fields are what P/L
uses; a partial stake or a missing leg is representable.

| Endpoint | Purpose |
|---|---|
| `POST /api/bets` | Create an open bet from the slip (API key required). |
| `GET /api/bets?days=30` | Open and settled bets in the window. |
| `POST /api/bets/{id}/settle` | One `won`/`lost`/`void` per leg; computes staked, payout and profit. |
| `POST /api/bets/{id}/closing` | Record closing odds per leg for CLV without settling. |
| `GET /api/bets/summary?days=30` | Bankroll, ROI, CLV and explicit denominators. |
| `GET /api/bets/export.csv` | CSV round-trip of the leg rows. |

## P/L

- A `won` leg pays `accepted_stake × accepted_odds`.
- A `lost` leg pays 0.
- A `void` leg returns its accepted stake.
- The bet stays `open` until every leg has a result; a partial settlement never
  reports a profit.
- `profit = payout - staked`; `roi = profit / settled stake`.
- `bankroll = bankroll_start + profit` (`BANKROLL_START`, default 1000).

## CLV

`clv = accepted_odds / closing_odds - 1`, weighted by accepted stake, over legs
whose closing price was recorded. It is `null` when no such leg exists. The
summary states the denominator (`clv_legs`) and does not mix open and settled
bets for ROI.

## Storage

Rows live in the P3-1 `cache/bh_arb.sqlite3` (`bets` table, one JSON payload plus
status/profit). The same backup/restore and rollback rules in `docs/STORAGE.md`
apply.

## Tests

`tests/test_bet_log.py` covers create/list, accepted-stake settlement, missing
legs, voids, CSV and the slip/API wiring. `tests/test_clv.py` covers weighted
CLV, bankroll, ROI and the denominators.
