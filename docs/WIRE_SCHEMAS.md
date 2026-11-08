# Strict wire schemas (SR4-3 / SR4-3b)

The parsers read the payload the transport returned, so a feed that renames a
price field or starts serving prices as strings used to reach the parser and
produce a partial (or silently wrong) result. SR4-3 puts one strict schema
between `response.json()` and the parser, one book at a time.

MDShop was the first book: direct HTTP, one JSON envelope
(`{"events": [...]}`) and no browser session. Its schema lives in
`scrapers/wire_schemas.py` and is validated in
`scrapers/mdshop.py::fetch_and_parse` before the per-event loop. SR4-3b added
Mozzartbet, a Playwright hybrid; its capture freezes the odds rows rather than
an event envelope (see below). SR4-3c reuses the NSoft models for Admiralbet
after its own dated captures proved the same shape. SR4-3d added Betole, whose
price rows are `{pick_code: price}` maps. SR4-3e added MBet, whose odds map
holds either a typed entry or a bare number. SR4-3f added SportPlus, whose
fixtures freeze a match's `markets[]` array.

## The pattern for the next book

1. **Model the raw wire objects**, not the normalised `Match`/`Market` result:
   response envelope, event, market block and each price row.
2. Use `ConfigDict(strict=True, extra="allow")`.
   - `strict=True` means a price served as `"1.85"` (string), `true` or a
     renamed field is a validation error. Nothing is coerced silently.
   - `extra="allow"` means a field the book added does not break the scrape.
3. Keep the model fields as the **allow-list** the adapter consumes. `sBV`,
   `betTypeId` and `betOutcomes` are examples; a new consumed field means one
   model edit plus its allow-list entry. A field the dated capture always
   carries is **required but nullable** (`float | None`), so a rename is drift
   rather than a row that quietly disappears.
4. Validate immediately after `response.json()` and raise
   `ScrapeError(ScrapeKind.SCHEMA_DRIFT)`. The adapter re-raises `ScrapeError`,
   so the book drops out of the scan (fail closed) instead of returning zero
   legs as if the feed were merely empty. A non-JSON body is the same kind.
5. Count every key outside the allow-list in
   `bh_wire_unknown_keys_total{book,level,field}` and log one line per payload.
   Unknown keys are telemetry, never fatal.
6. Add fixture-backed tests: the dated capture passes, a renamed price field
   and a string price are `schema_drift`, and an unknown key still scrapes.

## Metrics

```text
bh_wire_unknown_keys_total{book="mdshop",level="event",field="newFeedField"} 1
bh_wire_unknown_keys_total{book="mdshop",level="bet",field="newMarketField"} 1
bh_wire_unknown_keys_total{book="mdshop",level="outcome",field="newPriceField"} 1
```

`level` is `root`, `event`, `bet` or `outcome` for the NSoft books, `root`,
`match`, `odd`, `game` or `subgame` for Mozzartbet, `root`/`row` for Betole,
`root`/`odd` for MBet, and `root`/`market`/`odd` for SportPlus. The counter is
rendered by the existing `/api/metrics` endpoint; no dashboard change is needed
to see it.

## Books

### MDShop (SR4-3)

`NSoftResponse` / `NSoftEvent` / `NSoftBet` / `NSoftOutcome`, validated by
`validate_response()` in `fetch_and_parse` and by `validate_bets()` on the
`bets` array both dated fixtures freeze. A failure drops the whole book.

### Mozzartbet (SR4-3b)

`MozzartGame` / `MozzartSubgame` / `MozzartOdd` model one price row
(`game.id`/`name`/`shortName`, `subgame.name`, `value`), and two envelopes wrap
them:

- `validate_mozzart_offer()` validates `POST /betting/match/{id}`
  (`{"match": {"odds": [...]}}`) in `MozzartbetScraper._complete_offer`,
  immediately after `response.json()`. A per-event error payload
  (`{"error": "Not found. Sorry."}`) validates with `match = None`, so that
  event keeps its list odds; a drifted odds row falls out as `schema_drift`.
- `validate_mozzart_page()` validates `POST /betting/matches`
  (`items` + `totalPages`) in the pagination loop, including every item's
  `odds` array (the list odds are the per-event fallback now).

`_build_matches` re-raises a `ScrapeError` returned by a per-event task, so a
drifted row drops the whole book (the same wire shape serves every event)
instead of leaving the other events priced. The list *item* shell (teams,
kickoff, competition) has no dated capture yet, so it stays unmodelled: its
keys are neither rejected nor counted. A renamed team or kickoff field still
drops that event silently; SR4-4/SR5-1 own the structural drift alarm.

Tests: `tests/test_wire_schemas_mozzartbet.py`.

### Admiralbet (SR4-3c)

Admiralbet is a Playwright hybrid serving the **same NSoft `getwebevents`
envelope** as MDShop, so it reuses `NSoftResponse` / `NSoftEvent` / `NSoftBet`
/ `NSoftOutcome` instead of defining a second shape. Reuse was allowed only
after Admiralbet's own dated captures (prematch and live) passed the strict
schema with no unknown keys, which `tests/test_wire_schemas_admiralbet.py`
pins.

`validate_response()` runs in `scrape()` immediately after `response.json()`,
before any event is parsed. The adapter's historical bare-list form (the
payload being the events array itself) is wrapped as `{"events": [...]}` first,
so both shapes get the same schema. A non-JSON body or a drifted row is
`schema_drift` and drops the book.

The list *event* shell is validated only through the fields MDShop's capture
proved. Admiralbet's parser also reads fallback keys (`home`/`guest`,
`dateFrom`/`kickoff`, `leagueName`) that have no dated capture; if the live
shell carries them they are counted as unknown event keys, and a renamed team
field still drops that event silently (SR4-4/SR5-1 own structural drift).

Tests: `tests/test_wire_schemas_admiralbet.py`.

### Betole (SR4-3d)

Betole is plain HTTP on the ExeFeed platform, and neither earlier shape fits:
its "price row" is a `{pick_code: price}` **map**, not an object with a price
field. Two envelopes wrap that map:

- `BetoleDeskPage` — the desk listing, `{"esMatches": [event, ...]}`; each event
  carries its own `odds` map, which is the per-event fallback now that every
  event also gets a full offer. `validate_betole_desk()` runs in the pagination
  loop immediately after `response.json()`.
- `BetoleOfferRow` — one row of the batched full offer,
  `{"id": ..., "odds": {...}}`. `validate_betole_offers()` runs right after
  `response.json()` in `_fetch_full_offers`, so a drifted batch raises instead
  of silently keeping the desk odds.

`validate_betole_offer_map()` validates the captured `bets` map directly. The
map **keys are pick codes, not field names**, so they are data rather than an
allow-list: every code is accepted (the parser's `record_unmapped` tracks the
ones it cannot price) and the unmapped `284` control stays in the capture. The
**values** are the pricing surface: a string or boolean price is drift, an
integer is accepted, and a `null` pick is kept because the parser already reads
it as "no price".

The desk *event* shell (teams, kickoff, live flags) has no dated capture, so it
stays unmodelled: its keys are neither rejected nor counted, and a renamed team
field still drops that event silently. `esMatches` itself is required, so a
renamed envelope key fails instead of reading as an empty page.

Tests: `tests/test_wire_schemas_betole.py`.

### MBet (SR4-3e)

MBet is plain HTTP on the Alea platform: envelope `{"events": [...]}`, and each
event's `odds` is a map whose **keys are oddtype keys** (`ofb:fs:1`,
`lfb:tg:over|2.5`, ...) and whose values are either an entry object or a bare
number. The entry object (`MbetOdd`) carries `value`, `market_key`,
`oddtype_key`, `market_status` and `oddtype_status`; the capture writes all five
for every key (values may be null), so they are required — a renamed `value` or
status field is drift instead of an odd the parser reads as suspended.

- `validate_mbet_odds()` validates the captured `bets` map directly, so both
  dated fixtures (prematch and live) prove it.
- `validate_mbet_response()` validates the envelope (`events` required) and
  every event's odds map; it runs in `fetch_and_parse`'s page fetch right after
  `response.json()`.

Oddtype keys are data, like Betole's pick codes: every key is accepted and the
parser's `record_unmapped` keeps tracking the families it cannot price. A
string price is drift, an integer is accepted, and a bare number or `null`
entry is kept because the parser already reads that form. The event *shell*
(sport id, competitors, kickoff, tournament) has no dated capture and stays
unmodelled: its keys are neither rejected nor counted, so a renamed team field
still drops that event silently.

Tests: `tests/test_wire_schemas_mbet.py`.

### SportPlus (SR4-3f)

SportPlus is plain HTTP. Its dated fixtures freeze one match's `markets[]`
array: each block is `{"id", "name", "odds": [{"alias", "value"}, ...]}`, and
those three block fields plus the two price fields are the allow-list
(`SportplusMarket` / `SportplusOdd`). Two envelopes wrap the array:

- `SportplusPrematchPage` — `{"matches": [match, ...]}`;
  `validate_sportplus_prematch()` runs in `fetch_and_parse` after the optional
  double-serialised decode (`resp.json()` returning a JSON *string*).
- `SportplusLivePage` — `{"sports": [{"name": ..., "matches": [...]}]}`, with a
  `date` key that is declared (untyped) but never read so it stays out of the
  unknown-key telemetry. `validate_sportplus_live()` runs in `_fetch_live`.

Both envelope keys (`matches`, `sports`) are required, so a renamed envelope
key fails instead of reading as an empty offer. `odds` is required but nullable
because the parser already treats a block with no odds as empty; `value` and
`alias` are required but nullable, so a renamed price field or a string price
is drift. The match *shell* (sport name, competitors, kickoff, league) has no
dated capture and stays unmodelled: its keys are neither rejected nor counted,
so a renamed team field still drops that match silently.

Tests: `tests/test_wire_schemas_sportplus.py`.

## Follow-up rows

One book per session, each with its own capture and allow-list:
`SR4-3b` Mozzartbet (done 2026-11-08), `SR4-3c` Admiralbet (done 2026-11-08),
`SR4-3d` Betole (done 2026-11-08), `SR4-3e` MBet (done 2026-11-08),
`SR4-3f` SportPlus (done 2026-11-08), `SR4-3g` EVLBet,
`SR4-3h` Premier Kladionica, `SR4-3i` WWin, `SR4-3j` MaxBet.
