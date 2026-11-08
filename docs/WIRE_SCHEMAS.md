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
fixtures freeze a match's `markets[]` array. SR4-3h added Premier Kladionica,
whose PrSync rows are positional arrays. SR4-3i added WWin, whose fixtures
freeze an event's `bets[]` rows. SR4-3j added MaxBet, whose fixtures freeze a
match's `odds[]` array (SR4-3g, EVLBet, is blocked on the SR6-3 operator
decision).

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
   rather than a row that quietly disappears. A field the live feed legitimately
   omits on some rows (a suspended pick, SR4-10) is optional with a documented
   default; keep the rename signal with a page-level guard over the whole
   response.
4. Validate immediately after `response.json()` and raise
   `ScrapeError(ScrapeKind.SCHEMA_DRIFT)`. The adapter re-raises `ScrapeError`,
   so the book drops out of the scan (fail closed) instead of returning zero
   legs as if the feed were merely empty. A non-JSON body is the same kind.
5. Count every key outside the allow-list in
   `bh_wire_unknown_keys_total{book,level,field}` and log one line per payload.
   Unknown keys are telemetry, never fatal.
6. Add fixture-backed tests: the dated capture passes, a renamed price field
   and a string price are `schema_drift`, and an unknown key still scrapes.

SR4-4 adds a second, alert-only layer at the same boundary:
`engine/structural_drift.py` fingerprints the whole raw payload (sorted key
paths plus JSON types, values ignored) and counts
`bh_wire_structure_drift_total{book,endpoint}` when the shape moves outside the
modelled fields. It never rejects a payload; the schemas still own fail-closed.

## Metrics

```text
bh_wire_unknown_keys_total{book="mdshop",level="event",field="newFeedField"} 1
bh_wire_unknown_keys_total{book="mdshop",level="bet",field="newMarketField"} 1
bh_wire_unknown_keys_total{book="mdshop",level="outcome",field="newPriceField"} 1
```

`level` is `root`, `event`, `bet` or `outcome` for the NSoft books, `root`,
`match`, `odd`, `game` or `subgame` for Mozzartbet, `root`/`row` for Betole,
`root`/`odd` for MBet, `root`/`market`/`odd` for SportPlus, `section` for
Premier Kladionica (whose rows are positional, not keyed), and
`root`/`bet`/`odd` for WWin, and `market`/`specifiers`/`outcome` for MaxBet. The
counter is rendered by the existing `/api/metrics` endpoint; no dashboard change
is needed to see it.

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
  An unpriced pick omits the `value` key entirely (measured 2026-11-08:
  105 of 518 rows in one offer; SR4-10), so `value` is optional and the parser
  skips a row without a price.
- `validate_mozzart_page()` validates `POST /betting/matches`
  (`items` + `totalPages`) in the pagination loop, including every item's
  `odds` array (the list odds are the per-event fallback now). It also raises
  `schema_drift` when a page carries odds rows but none has a numeric `value`,
  which is what a renamed price field looks like across a whole page; a single
  suspended row does not trip it.

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

### Premier Kladionica (SR4-3h)

PrSync is positional: the response is `[sections]`, each section a list of
rows, and a column's meaning is its **index**. The dated fixtures freeze two
tables: the dogTipK odds rows (`bets`) and the setTip/setTipVar/setTipTip
definition rows (`lookup`). Each model maps its positional list through a
`model_validator(mode="before")`, then the strict field types apply by position:

- `PremierOddRow` — `dog_id`, `grupa_tip_id`, `set_tip_id`, `var_id`, `tip_id`,
  `koef` (the price, column 5), `na_pon`, `dobitni`, `koef1`; a row shorter than
  nine columns is drift (the price column cannot be located).
- `PremierSetTip` — `sport_id`, `set_tip_id`, `name` (column 2).
- `PremierSetTipVar` — `sport_id`, `set_tip_id`, `var_id`, `line` (column 9).
- `PremierSetTipTip` — `sport_id`, `set_tip_id`, `tip_id`, `code` (column 4).

`validate_premier_odds` and `validate_premier_lookup` are the fixture entry
points. `_sync_call` runs `validate_premier_sync`: a **full** sync must be a
`[sections]` list with at least ten slots (each slot a list) and its sections
7/8/9 are typed; a **delta** sync carries five positional tables (execRes 5
columns, dogVar 14, dogTipK odds 9, dogLiveScore 43, scalars) and omits the
empty ones, so a section is typed as odds only when at least one row has the
dogTipK shape. Every row of a recognised odds section is then validated, so a
truncated row or a string price still drifts (SR4-13). A non-JSON body, a wrong
envelope or a drifted column raises `SCRAPE_DRIFT` and the book drops out.

Positional data has no field names to call unknown, so the counter reports
**unknown section slots** — slots past the fifteen the parser documents — at
`level="section"`, `field="<index>"`. The event, sports, competition-group,
dogVar, dogLiveScore and execRes sections have no dated capture and stay
unmodelled.

Tests: `tests/test_wire_schemas_premier.py`; the real delta envelope is
`tests/fixtures/wire/premier_kladionica_delta.json`.

### WWin (SR4-3i)

WWIN is a Playwright hybrid. The dated fixtures freeze the `bets[]` array the
parser reads — `idBt`, `spec`, and `odds[]` with `t`/`va`/`isv` — not the event
shell around it. The same row arrives in three envelopes:

- `WwinOdd` — `t` and `va` are required (`va` must already be a number),
  `isv` is optional because the documented live `headerBets` row is `{va, t}`.
- `WwinBet` — `idBt` (int), `spec` (the line specifier), `odds`.
- `WwinEventsPage` — prematch `{"p": [...]}` (historically also
  `{"events": [...]}`) or live `{"events": [...]}`; the event dicts stay raw.
- `WwinHeaderBetsPage` — `{"bets": [{"<eventId>": bet}]}`; the event id is data,
  not a field name.

`validate_wwin_bets` is the fixture entry point. `validate_wwin_events` runs on
each events page (it requires the mode's page key and validates every event's
`bets`) and `validate_wwin_header_bets` on each live `headerBets` page, all
immediately after the body is decoded. Response bodies are classified by shape
(SR4-11): a **0-byte body is "no rows for that slice"** and does not drop the
book (measured 2026-11-08: days 8–9 of the 15-day prematch walk answer HTTP 200
with an empty body for every bet group); an HTML page is `blocked` (a
challenge); any other non-JSON body, a missing page key, a non-object
event/header item or a drifted bet row raises `SCHEMA_DRIFT` and the book drops
out. Unknown keys are counted at `level="root"` for the envelopes and
`level="bet"`/`"odd"` for the rows. The event shell (teams, kickoff,
competition) has no dated capture and stays unmodelled.

Tests: `tests/test_wire_schemas_wwin.py`.

### MaxBet (SR4-3j)

MaxBet is plain HTTP and its matches response is one bare `[event, ...]` list.
The dated fixtures freeze one match's `odds[]` array, so that array is the
typed part; the event shell stays unmodelled.

- `MaxbetSpecifiers` — `total` and `hcp`; the feed spells lines as strings.
- `MaxbetOutcome` — `outcome`, `outcomeId`, `status`, `oddValue` (required but
  nullable) and `marketAvailableForBetting` (required but nullable). A renamed
  price field or a string price is drift; a null price is kept because the
  parser already drops it.
- `MaxbetMarket` — `id`, `name`, `specifiers` (optional: line-less markets omit
  the key) and `outcomes`.

`validate_maxbet_odds` is the fixture entry point; `validate_maxbet_events` runs
in `fetch_and_parse` immediately after `response.json()` and validates the bare
list and every event's `odds`. A non-JSON body, a non-list response, a
non-object event or a drifted market/outcome row raises `SCRAPE_DRIFT` and the
book drops out. Unknown keys are counted at `level="market"`, `"specifiers"`
and `"outcome"`. A renamed specifier on a totals market degrades to "no line"
rather than drift, because line-less markets legitimately omit `specifiers`.

Tests: `tests/test_wire_schemas_maxbet.py`.

## Follow-up rows

One book per session, each with its own capture and allow-list:
`SR4-3b` Mozzartbet (done 2026-11-08), `SR4-3c` Admiralbet (done 2026-11-08),
`SR4-3d` Betole (done 2026-11-08), `SR4-3e` MBet (done 2026-11-08),
`SR4-3f` SportPlus (done 2026-11-08), `SR4-3g` EVLBet (**blocked on SR6-3**:
disabled book, empty capture, operator decision pending), `SR4-3h` Premier
Kladionica (done 2026-11-08), `SR4-3i` WWin (done 2026-11-08), `SR4-3j` MaxBet
(done 2026-11-08).
