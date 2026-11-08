# Bet log, bankroll and CLV (P3-2)

The scanner **never places a bet**. This is a manual record of what the operator
says was actually accepted, used to measure whether the edges are real.

## Logging

The slip has **Log bet**. It posts the current plan to `POST /api/bets`:
surebet id, feed, match, market, investment and one leg per bookmaker with
planned odds/stake and accepted odds/stake. The accepted fields are what P/L
uses; a partial stake or a missing leg is representable. The payload also carries
the stable `event_key`, `kickoff`, league, sport and each leg's exact source
market (`market_type`, `line`, `settlement`, `period`), so a later scan can
capture a closing line without guessing which bet it belongs to. The server
fills those fields from the cached surebet when an older client omits them.

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

### Accepted odds and stake are a pair

The accepted fields are what P/L uses, so their zero has one meaning: the leg
was **not placed**. `accepted_odds: 0` and `accepted_stake: 0` together are that
sentinel — a rejected leg, or a stake the book did not take. `null` means "not
typed" and falls back to the planned odds or stake.

A **positive** accepted stake with `accepted_odds: 0` is an impossible claim: a
stake cannot be accepted at a price that does not exist. `POST /api/bets`
refuses it with `422` and writes no row, because the old leniency silently
treated it as not placed and dropped the operator's money from P/L without a
warning. The guard is create-time only: a row already stored with that pair still
settles as not placed, and nothing is rewritten. A zero accepted stake with a
real price stays accepted — the price is known, no money is at stake.

## CLV

`clv = accepted_odds / closing_odds - 1`, weighted by accepted stake, over legs
whose closing price was recorded. It is `null` when no such leg exists. The
summary states the denominator (`clv_legs`) and does not mix open and settled
bets for ROI.

### Automatic closing capture (N0-4)

Every scan captures the latest pre-kickoff price for each open bet's legs from
the same verified groups it prices. Matching is exact:

* the event must match the bet's stable `event_key` (or, for older bets, the
  canonical teams and kickoff);
* the bookmaker must still be in the scan and not quarantined;
* the market type, settlement, line and outcome label must match the leg's exact
  source market;
* a market refused by the frozen-price rule (N0-2) is not used.

The closing record freezes at kickoff (or `CLOSING_CAPTURE_CUTOFF_MINUTES` before
it). A scan never writes a price after that point, never overwrites a manual
entry, and never touches a settled bet. A missing or mismatched price leaves
`closing_odds` null and records a `closing_reason` such as `no_kickoff`,
`after_kickoff`, `event_not_in_scan`, `book_not_in_scan`,
`market_not_offered`, `settlement_mismatch`, `line_mismatch`,
`outcome_not_offered` or `stale_price`.

Each leg carries `closing_source` (`scan` or `manual`) and
`closing_captured_at`. `POST /api/bets/{id}/closing` is still the manual
override and is labelled `manual`; a later scan leaves it alone.
`GET /api/bets/summary` reports `closing_legs`, `closing_sources`,
`closing_capture` (legs total / with closing / missing, by source and reason)
and the last scan's `last_capture` counts. The dashboard's bet-log line shows
the same numerator and denominator.

## Storage

Rows live in the P3-1 `cache/bh_arb.sqlite3` (`bets` table, one JSON payload plus
status/profit). The same backup/restore and rollback rules in `docs/STORAGE.md`
apply.

## Tests

`tests/test_bet_log.py` covers create/list, accepted-stake settlement, missing
legs, voids, CSV and the slip/API wiring. `tests/test_clv.py` covers weighted
CLV, bankroll, ROI and the denominators. `tests/test_auto_clv.py` covers
pre-kickoff capture, missing/mismatched prices, wrong settlement and line, a
missing book, a missing kickoff, the post-kickoff freeze, settled bets, manual
override and the summary sources.
