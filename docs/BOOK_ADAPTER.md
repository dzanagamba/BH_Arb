# Book adapter contract

A new bookmaker is a scraper module plus a data adapter. It must not require an
edit to `config/team_mappings.json`, `config/league_mappings.json`,
`config/team_alias_allowlist.json` or `config/bookmaker_markets.json`.

## What an adapter emits

1. A `Match` skeleton: `bookmaker`, the book's own `home_team` / `away_team`
   spelling, `league`, `kickoff` (naive UTC), `event_id`, `url`, `mode`
   (`is_live`), and any `betradar_id` the feed carries.
2. One `RawOffer` per market, with the book's own identifiers and labels:

```python
RawOffer(
    bookmaker="newbook",
    mode="prematch",
    event_key="event-123",
    market_key="market-456",
    source_id="456",
    labels=["Over 2.5", "Under 2.5"],
    line=2.5,
    period="full_time",
    odds=[OddsValue(label="Over 2.5", value=1.95), OddsValue(label="Under 2.5", value=1.90)],
    raw_payload_hash="sha256:...",
)
```

Do not choose a `MarketType` in the adapter. `engine/market_discovery.py` does
that from labels, line and period; `engine/market_consensus.py` checks the result
against other books on the same fixture.

## What the discovery pipeline does

* **Names** — the learner (`engine/mapping_learner.py`) proves team aliases and
  league equivalences from shared Betradar ids and exact shared fixtures, and
  writes them to `config/generated/mapping_evidence.json`. The gate reads only
  accepted, non-stale claims.
* **Markets** — `engine/market_discovery.classify()` accepts a complete label
  set, and `engine/market_consensus.compare()` accepts it only when at least two
  other books agree on the de-vigged probabilities. A row with no corroboration
  is quarantined, not guessed; `scripts/discover_markets.py` records the ledger
  evidence. (The old `engine/raw_market_resolver.resolve_offers` wrapper was
  retired in M5-4 because no adapter used it.)
* **Absence** — a market the book never publishes is recorded as
  `market_absence` with the capture dates and payload hashes. Do not silently
  omit it.

## Tests an adapter must add

1. A fixture test that runs the real parser over a captured payload and asserts
   the `Match` skeleton and at least one classified `RawOffer`.
2. A classifier test for every label set the book uses, including one incomplete
   set that must return `None`.
3. A consensus test on a shared fixture with two other books, or an explicit
   `insufficient_evidence` result when the book is the only one offering the
   market.
4. A no-config-edit test: onboarding the book must not change the hand-written
   mapping files.

## What is deliberately not automated

A feed that publishes no football, a CAPTCHA that needs a person, or a market
whose settlement rule cannot be proven from captures is a blocker. Record the
evidence and the recheck date; do not fabricate a mapping to make coverage look
complete.
