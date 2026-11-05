# Bookmaker feed status — 2026-11-03

Produced by `python scripts/probe_feeds.py --books evlbet,betole --timeout 120`.
The probe runs the real scraper and reports matches, market types and errors.

| Book | Enabled | Matches | Markets published | Error |
|---|---|---:|---|---|
| Betole | yes | 1,239 | 1x2 (1,238), BTTS (1,231), first-half 1x2 (1,239), O/U 2.5 (1,239) | none |
| EVLBet | no | 0 | none | none |

EVLBet's zero is an evidence-backed absence, not a silent omission: its feed
returned no football events in this probe. It remains disabled and should be
re-probed before re-enabling. Betole's kickoff and Betradar-id fixes are what
made its 1,239 listings usable; it is enabled.

Run the probe again after a feed change or before adding a book. The 9-book
prematch scan remains the source for the other books' counts.

## Price freshness: collected time vs book update time (N0-2)

`fetched_at` is when we collected a row. `source_updated_at` is when the book
says it last moved the price. They are separate fields in `Match`, `Market` and
`OddsValue`, and a served leg carries both. A feed that publishes no timestamp
leaves `source_updated_at` empty; it is never filled from the scan clock.

Wired feeds:

| Feed | Field | Notes |
|---|---|---|
| MaxBet | `updateDate` / `providerTimestamp` per outcome | Parsed by `scrapers/maxbet.py`; the captured fixtures trim these fields, so fixtures leave the value empty. |
| Push-feed adapter | `FeedFrame.source_updated_at` | `LiveFeedState` copies it onto rows that do not carry their own timestamp. No shipped book uses a push feed yet. |
| Other polling scrapers | none observed | They leave `source_updated_at` empty and keep the existing `fetched_at` TTL. |

A row is refused as **price frozen** only when one of two rules fires:

1. the feed-provided `source_updated_at` is older than the mode's TTL
   (`ODDS_TTL_SECONDS` prematch, `LIVE_ODDS_TTL_SECONDS` live); or
2. the price has not moved for `STALE_PRICE_UNCHANGED_SCANS` scans (default 3)
   while at least one independent price source moved on the same event, market,
   line and outcome.

The second rule is deliberately not "the price did not move". A genuinely stable
market whose peers are also stable is normal and is never quarantined. A missing
source timestamp fails safe to the existing fetch-time TTL, not to "fresh". The
observation store is bounded by `STALE_PRICE_MAX_ROWS` and
`STALE_PRICE_RETENTION_SECONDS`.

A refused market is dropped for that book before pricing; the rest of the book
can still supply other rows. This is a price-source restriction, not a change to
the certainty gate: identity, settlement and one-leg-per-book rules are
untouched. Evidence is exposed as `stale_prices` in `/api/results` and
`/api/health`, as `stale_price_rows` in each `feed_integrity` scorecard, and as
a **price frozen** badge in the dashboard feed-integrity strip.
