# Football Market Mapping

This is the canonical market audit for the nine configured bookmakers in
`config/settings.BOOKMAKERS`. The registry-backed scanner maps six of the nine
`MarketType` values in `models/schemas.py`; the remaining three
(`first_half_1x2`, `first_half_ou`, `asian_handicap`) are experimental and are
parsed directly by individual scrapers rather than declared in the registry. Any
offer with a similar-looking outcome label is ignored unless its settlement
meaning and complete outcome set are known.

Audit date: 2026-08-14. Live sources were checked where the bookmaker API was
reachable. Decimal odds are for the regular match settlement, not extra time,
penalties, or a different period.

**The table below is the authority on which source ID maps to which market.** It
is generated from `config/bookmaker_markets.json` — the same file
`engine/market_registry.py` loads — so it cannot drift from the IDs the parsers
resolve. Where the hand-written field notes at the bottom of this file disagree
with it, it wins: fix the registry and regenerate rather than editing either.

<!-- GENERATED FROM bookmaker_markets.json -->

<!-- Everything between these two markers is written by
     scripts/generate_market_mapping_doc.py.  Do not edit it by hand:
     hand edits here are lost on the next regeneration. -->

Regenerate: `python scripts/generate_market_mapping_doc.py`  
Verify without writing: `python scripts/generate_market_mapping_doc.py --check`

## Registry table (generated)

Source of truth: `config/bookmaker_markets.json`, loaded by
`engine/market_registry.py`. Values below are resolved through the loader,
so registry defaults (outcome labels, min legs, settlement) are included.
Covers 9 bookmakers and 85 book/mode/market rows.

Scope: these are the IDs the **registry declares**. It is the authority on
the declared mapping, not on parser dispatch — a book's parser may read a
subset of the IDs listed for it, because some parsers dispatch on a
hardcoded pick table rather than iterating the registry. Where a row lists
more IDs than the book actually consumes, the per-book field notes at the
bottom of this file say so.

### Mapped markets

| Bookmaker | Mode | Market | Source IDs | Outcome labels | Min legs | Line | Settlement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mdshop` | prematch | Full-time 1X2 (`1x2`) | `135` | 1, 2, X | 3 | — | full_time |
| `mdshop` | prematch | Double Chance (`double_chance`) | `152` | 12, 1X, X2 | 2 | — | full_time |
| `mdshop` | prematch | BTTS (`btts`) | `151` | GG, NG | 2 | — | full_time |
| `mdshop` | prematch | Over/Under 1.5 (`over_under_1_5`) | `137`, `138` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `mdshop` | prematch | Over/Under 2.5 (`over_under_2_5`) | `137`, `138` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `mdshop` | prematch | Over/Under 3.5 (`over_under_3_5`) | `137`, `138` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `mdshop` | live | Full-time 1X2 (`1x2`) | `6` | 1, 2, X | 3 | — | full_time |
| `mdshop` | live | Double Chance (`double_chance`) | `18`, `42` | 12, 1X, X2 | 2 | — | full_time |
| `mdshop` | live | BTTS (`btts`) | `995` | GG, NG | 2 | — | full_time |
| `mdshop` | live | Over/Under 1.5 (`over_under_1_5`) | `22`, `28` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `mdshop` | live | Over/Under 2.5 (`over_under_2_5`) | `22`, `28` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `mdshop` | live | Over/Under 3.5 (`over_under_3_5`) | `22`, `28` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `admiralbet` | prematch | Full-time 1X2 (`1x2`) | `1639` | 1, 2, X | 3 | — | full_time |
| `admiralbet` | prematch | Double Chance (`double_chance`) | `152` | 12, 1X, X2 | 2 | — | full_time |
| `admiralbet` | prematch | BTTS (`btts`) | `151` | GG, NG | 2 | — | full_time |
| `admiralbet` | prematch | Over/Under 1.5 (`over_under_1_5`) | `137`, `138` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `admiralbet` | prematch | Over/Under 2.5 (`over_under_2_5`) | `137`, `138` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `admiralbet` | prematch | Over/Under 3.5 (`over_under_3_5`) | `137`, `138` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `admiralbet` | live | Full-time 1X2 (`1x2`) | `6` | 1, 2, X | 3 | — | full_time |
| `admiralbet` | live | Double Chance (`double_chance`) | `18`, `42` | 12, 1X, X2 | 2 | — | full_time |
| `admiralbet` | live | BTTS (`btts`) | `995` | GG, NG | 2 | — | full_time |
| `wwin` | prematch | Full-time 1X2 (`1x2`) | `95` | 1, 2, X | 3 | — | full_time |
| `wwin` | prematch | Double Chance (`double_chance`) | `6` | 12, 1X, X2 | 2 | — | full_time |
| `wwin` | prematch | BTTS (`btts`) | `3` | GG, NG | 2 | — | full_time |
| `wwin` | prematch | Over/Under 1.5 (`over_under_1_5`) | `11` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `wwin` | prematch | Over/Under 2.5 (`over_under_2_5`) | `11` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `wwin` | prematch | Over/Under 3.5 (`over_under_3_5`) | `11` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `wwin` | live | Full-time 1X2 (`1x2`) | `95` | 1, 2, X | 3 | — | full_time |
| `wwin` | live | Double Chance (`double_chance`) | `6` | 12, 1X, X2 | 2 | — | full_time |
| `wwin` | live | BTTS (`btts`) | `3` | GG, NG | 2 | — | full_time |
| `wwin` | live | Over/Under 1.5 (`over_under_1_5`) | `11` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `wwin` | live | Over/Under 2.5 (`over_under_2_5`) | `11` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `wwin` | live | Over/Under 3.5 (`over_under_3_5`) | `11` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `premier_kladionica` | prematch | Full-time 1X2 (`1x2`) | `UTAKMICA_1X2` | 1, 2, X | 3 | — | full_time |
| `premier_kladionica` | prematch | Double Chance (`double_chance`) | `UTAKMICA_DC` | 12, 1X, X2 | 2 | — | full_time |
| `premier_kladionica` | prematch | BTTS (`btts`) | `OBA_DAJU_GOL` | GG, NG | 2 | — | full_time |
| `premier_kladionica` | prematch | Over/Under 1.5 (`over_under_1_5`) | `ZBROJ_GOLOVA` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `premier_kladionica` | prematch | Over/Under 2.5 (`over_under_2_5`) | `ZBROJ_GOLOVA` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `premier_kladionica` | prematch | Over/Under 3.5 (`over_under_3_5`) | `ZBROJ_GOLOVA` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `premier_kladionica` | live | Full-time 1X2 (`1x2`) | `LIVE_UTAKMICA` | 1, 2, X | 3 | — | full_time |
| `premier_kladionica` | live | Double Chance (`double_chance`) | `UTAKMICA_DC` | 12, 1X, X2 | 2 | — | full_time |
| `premier_kladionica` | live | BTTS (`btts`) | `LIVE_OBA_DAJU_GOL` | GG, NG | 2 | — | full_time |
| `mbet` | prematch | Full-time 1X2 (`1x2`) | `ofb:fs` | 1, 2, X | 3 | — | full_time |
| `mbet` | prematch | Double Chance (`double_chance`) | `ofb:dc` | 12, 1X, X2 | 2 | — | full_time |
| `mbet` | prematch | BTTS (`btts`) | `ofb:gg` | GG, NG | 2 | — | full_time |
| `mbet` | prematch | Over/Under 1.5 (`over_under_1_5`) | `ofb:tg` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `mbet` | prematch | Over/Under 2.5 (`over_under_2_5`) | `ofb:tg` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `mbet` | prematch | Over/Under 3.5 (`over_under_3_5`) | `ofb:tg` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `mbet` | live | Full-time 1X2 (`1x2`) | `lfb:ft` | 1, 2, X | 3 | — | full_time |
| `mbet` | live | Double Chance (`double_chance`) | `lfb:dc` | 12, 1X, X2 | 2 | — | full_time |
| `mbet` | live | BTTS (`btts`) | `lfb:bttsny` | GG, NG | 2 | — | full_time |
| `mbet` | live | Over/Under 1.5 (`over_under_1_5`) | `lfb:tg` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `mbet` | live | Over/Under 2.5 (`over_under_2_5`) | `lfb:tg` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `mbet` | live | Over/Under 3.5 (`over_under_3_5`) | `lfb:tg` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `sportplus` | prematch | Full-time 1X2 (`1x2`) | `1` | 1, 2, X | 3 | — | full_time |
| `sportplus` | prematch | Double Chance (`double_chance`) | `1` | 12, 1X, X2 | 2 | — | full_time |
| `sportplus` | prematch | BTTS (`btts`) | `6` | GG, NG | 2 | — | full_time |
| `sportplus` | prematch | Over/Under 1.5 (`over_under_1_5`) | `800`, `802` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `sportplus` | prematch | Over/Under 2.5 (`over_under_2_5`) | `768`, `800`, `802` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `sportplus` | prematch | Over/Under 3.5 (`over_under_3_5`) | `800`, `802` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `sportplus` | live | Full-time 1X2 (`1x2`) | `POBJEDNIK` | 1, 2, X | 3 | — | full_time |
| `sportplus` | live | Double Chance (`double_chance`) | `DVOSTRUKA_PRILIKA` | 12, 1X, X2 | 2 | — | full_time |
| `sportplus` | live | BTTS (`btts`) | `OBA_DAJU_GOL` | GG, NG | 2 | — | full_time |
| `sportplus` | live | Over/Under 1.5 (`over_under_1_5`) | `ZBROJ_GOLOVA` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `sportplus` | live | Over/Under 2.5 (`over_under_2_5`) | `ZBROJ_GOLOVA` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `sportplus` | live | Over/Under 3.5 (`over_under_3_5`) | `ZBROJ_GOLOVA` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `evlbet` | prematch | Full-time 1X2 (`1x2`) | `12005` | 1, 2, X | 3 | — | full_time |
| `betole` | prematch | Full-time 1X2 (`1x2`) | `1`, `2`, `3`, `135` | 1, 2, X | 3 | — | full_time |
| `betole` | prematch | Double Chance (`double_chance`) | `2`, `7`, `8`, `9`, `152` | 12, 1X, X2 | 2 | — | full_time |
| `betole` | prematch | BTTS (`btts`) | `130`, `151`, `272`, `273` | GG, NG | 2 | — | full_time |
| `betole` | prematch | Over/Under 1.5 (`over_under_1_5`) | `3`, `21`, `137`, `138`, `242` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `betole` | prematch | Over/Under 2.5 (`over_under_2_5`) | `3`, `22`, `24`, `137`, `138` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `betole` | prematch | Over/Under 3.5 (`over_under_3_5`) | `3`, `25`, `137`, `138`, `219` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `mozzartbet` | prematch | Full-time 1X2 (`1x2`) | `1` | 1, 2, X | 3 | — | full_time |
| `mozzartbet` | prematch | Double Chance (`double_chance`) | `2` | 12, 1X, X2 | 2 | — | full_time |
| `mozzartbet` | prematch | BTTS (`btts`) | `130` | GG, NG | 2 | — | full_time |
| `mozzartbet` | prematch | Over/Under 1.5 (`over_under_1_5`) | `3` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `mozzartbet` | prematch | Over/Under 2.5 (`over_under_2_5`) | `3` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `mozzartbet` | prematch | Over/Under 3.5 (`over_under_3_5`) | `3` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |
| `mozzartbet` | live | Full-time 1X2 (`1x2`) | `1` | 1, 2, X | 3 | — | full_time |
| `mozzartbet` | live | Double Chance (`double_chance`) | `2` | 12, 1X, X2 | 2 | — | full_time |
| `mozzartbet` | live | BTTS (`btts`) | `130` | GG, NG | 2 | — | full_time |
| `mozzartbet` | live | Over/Under 1.5 (`over_under_1_5`) | `3` | Over 1.5, Under 1.5 | 2 | 1.5 | full_time |
| `mozzartbet` | live | Over/Under 2.5 (`over_under_2_5`) | `3` | Over 2.5, Under 2.5 | 2 | 2.5 | full_time |
| `mozzartbet` | live | Over/Under 3.5 (`over_under_3_5`) | `3` | Over 3.5, Under 3.5 | 2 | 3.5 | full_time |

### Deliberately unmapped source IDs

The `_excluded` block of the registry: offers that are recognised and
deliberately not mapped, mostly advance/qualification, half-time,
handicap, period and combination markets. Listing an ID here suppresses
the unmapped-market health diagnostic for it, so an operator does not
chase a market the project intends to ignore. It is a declaration of
intent, not a rejection mechanism: a parser still has to decline the
offer on its own, and no ID may appear both here and in the table above.
A name pattern applies to any source ID that matches it.

| Bookmaker | Excluded IDs / name patterns |
| --- | --- |
| `admiralbet` | `1`, `10`, `11`, `14`, `17`, `24`, `30`, `39`, `41`, `43`, `56`, `136`, `140`, `143`, `144`, `148`, `149`, `153`, `154`, `161`, `162`, `166`, `174`, `261`, `303`, `304`, `437`, `1064` |
| `betole` | `335`, `336` |
| `mbet` | `lfb:tg1sth`, `ofb:dnb`, `ofb:fi`, `ofb:fts`, `ofb:htdc`, `ofb:sh`, `ofb:shdc` |
| `mdshop` | `1`, `10`, `11`, `14`, `17`, `24`, `30`, `39`, `41`, `43`, `56`, `136`, `140`, `143`, `144`, `148`, `149`, `153`, `154`, `161`, `162`, `166`, `174`, `261`, `303`, `304`, `437`, `1064` |
| `mozzartbet` | `141`, `*DALJE*`, `*KVALIFIKACIJE*`, `*PROLAZ*` |
| `premier_kladionica` | `1435`, `1440`, `*HENDIKEP*`, `*HT/FT*`, `*KARTICE*`, `*KLAĐENJE*POBJEDU*`, `*KOMBINACIJA*`, `*KUTOVI*`, `*PAR/NEPAR*`, `*POLUVRIJEME*KRAJ*`, `*PROLAZ*`, `*RASPON*`, `*REZULTAT*`, `*STRIJELCI*`, `*TOČAN*` |
| `sportplus` | `5`, `178`, `308`, `309`, `310`, `311`, `1285`, `*ADVANCE*`, `*DALJE*`, `*KVALIFIKACIJE*`, `*PROLAZ*`, `*QUALIF*` |
| `wwin` | `4`, `7`, `10`, `51`, `443`, `476` |
<!-- END GENERATED FROM bookmaker_markets.json -->

---

## Per-book field notes (hand-written)

Everything below this line is hand-written analysis of the live bookmaker
catalogs: which endpoint each book uses, how each feed encodes outcome labels and
thresholds, and why a market that looks like a match result must be refused. The
generator above never touches this section — edit it freely.

It deliberately contains **no ID-to-market tables**: those now live in the
generated table, which is machine-checked against the registry. What remains here
is the knowledge the registry cannot hold — feed shape, label vocabularies,
filtering rules and the history of past mapping mistakes.

## Live (In-Play) Feeds

The app supports two scan modes: `prematch` (future matches) and `live`
(in-play matches). Live feeds use their own market structures and their own ID
space, verified against the live APIs (2026-08-14). The live source IDs for each
book are in the generated table above; the operational details are here.

| Bookmaker | Live feed | Operational notes |
| --- | --- | --- |
| MDShop / Admiralbet | `getwebevents?isLive=true` | Different ID space from prematch; for the live result offer `sbv` carries the running score rather than a threshold, and for the totals offers it carries the threshold. SRL simulated events skipped; dead sides (e.g. under 2.5 at 3-0) are dropped |
| MBet | `events_cached?live=true` | `finished` events and CLOSED markets skipped; the first-half totals key `lfb:tg1sth` is excluded |
| SportPlus | `/api/v1/live/offer` | Markets are keyed by name, not ID: `Pobjednik`, `Dvostruka Prilika`, `Oba daju gol` (outcomes `1(D)`/`2(N)`), `Zbroj golova X.5` (outcomes `1(M)`/`2(V)`). Matches with `betting: false` skipped; `ML/`-style team prefixes stripped |
| Mozzartbet | `betting/matches` with `date:"live"` | The feed also returns upcoming fixtures — only events whose `startTime` has passed are kept |
| WWIN | `sport-livecontent` REST | Same endpoint family as prematch, filtered by the live market-id group |
| EVLBet | — | The live feed (`matches/live`) carries scores but no odds (`Offers` is always empty), so EVLBet is skipped in live mode |
| Betole | same desk feed, `live: true` events | Same pick codes as prematch; SRL simulated events skipped |

The arbitrage engine keeps in-play groups (past kickoffs) in live mode; the
prematch mode still expires matches that started more than 15 minutes ago.

## WWIN

Platform: `sport-livecontent` REST API (Playwright session for Cloudflare).
Football sport id is `2`; events expose `brid` (Betradar id).

Each bet carries its numeric offer id in `idBt` and its outcome label in `t`:
`1`/`X`/`2` for the result, `1X`/`12`/`X2` for double chance, `Yes`/`No` for
BTTS, and `Over`/`Under` for totals. The totals threshold arrives in the bet's
`spec` field as `total=1,5` / `total=2,5` / `total=3,5` and is normalised before
the registry lookup, so only the 1.5/2.5/3.5 lines resolve. A 1X2 offer is
accepted only with all three `1`/`X`/`2` sides; double chance needs at least two
valid legs.

The IDs below are excluded, and the reason each is excluded is audit knowledge the
generated table cannot hold — the table records *that* they are excluded, not
*what they are*:

- `idBt=7` — draw no bet.
- `idBt=10` — three-way handicap.
- `idBt=4` — half-time / full-time.
- `idBt=476` — "Prolaz", the advance market.
- `idBt=443` — Asian totals, including quarter lines such as `2.25` and `2.75`
  that have no representation in the supported Over/Under set.
- `idBt=51` — correct score.

`idBt=2` was previously listed here as excluded. It is not: in prematch the
parser reads it as `first_half_1x2`, an experimental market retained outside the
core registry, the same treatment `ofb:ht` gets at MBet.

The prematch `events` endpoint serves at most two bet ids per call, so the
scraper fetches three groups (`95,6`, `3`, `11`) and merges by event id.

## Premier Kladionica

Platform: `PrSync` JSON-RPC (`svc-test.premier-kladionica.com/PrSync/PrSync.ashx`,
method 7). Positional response sections are indexed by:
`execRes, tipIgre, sport, grupaDog, setDog, dog, grupaTip, setTip, setTipVar,
setTipTip, not used, dogVar, dogTipK, pravila, dogLiveScore`.

Odds arrive via the delta sync (`dogadjajIDs` + `clientVer`) as `dogTipK` rows:
`[dogID, grupaTipID, setTipID, setTipVarID, setTipTipID, koef, naPon, ...]`.
Market names come from `setTip`, lines (e.g. `(-2,5+)`) from `setTipVar`, and
outcome codes (e.g. `1/X/2`, `da/ne`, `m/v`) from `setTipTip`. Football is
`grupaTipID=2`.

The feed's own vocabulary is richer than the registry keys, so the parser derives
a normalised source ID before looking anything up. Do not expect the feed to
contain `UTAKMICA_1X2`: the feed says `UTAKMICA`, and the outcome codes decide
which market it is — `1`/`X`/`2` for the result, `1X`/`X2`/`12` for double chance
from the same name. `OBA DAJU GOL` spells its outcomes `da`/`ne` or `o-da`/`o-ne`,
and `ZBROJ GOLOVA` spells them `m`/`v` with the line in `setTipVar` as
`(-1,5+)`/`(-2,5+)`/`(-3,5+)`. The live variants arrive as `LIVE - UTAKMICA`,
`LIVE - OBA DAJU GOL` and `LIVE - ZBROJ GOLOVA`, and are only used in live mode.

The remaining `setTip` names on the football tip group are excluded by name
pattern; see the excluded table above. They are the original Bosnian feed names,
so they are worth recognising on sight: `HENDIKEP` (handicap),
`KLAĐENJE NA POBJEDU` (draw-no-bet), `POLUVRIJEME / KRAJ` (half-time/full-time),
`TOČAN …` (exact score), `RASPON …` (goal range), `PAR/NEPAR` (odd/even),
`KUTOVI` (corners), `KARTICE` (cards), `STRIJELCI` (scorers), `KOMBINACIJA`
(combinations) and `NAČIN PROLAZA` (advance).

## MDShop

Platform: NSoft `getwebevents`, standard NSoft IDs in the bet's `betTypeId`
field, threshold in lowercase `sbv`. Outcome labels arrive as `1`/`X`/`2`,
`1X`/`12`/`X2`, `GG`/`NG` and a localised over/under pair that the parser
normalises before the registry lookup.

The one ID pair is shared by all three Over/Under lines, so the threshold in
`sbv` is part of the lookup key, not a separate market. Unsupported thresholds
such as `4.5`, `5.5` and `6.5` are excluded. Advance/qualification, half-time,
half-period totals, DNB, handicap, correct-score and combination offers are
excluded by ID; see the excluded table above for the full list.

## Admiralbet

Platform: NSoft `getwebevents`, but Admiralbet uses `sBV` (note the capital `B`,
unlike MDShop) and has a bookmaker-specific full-time result ID.

The live catalog confirmed `1639` is the real Admiralbet 1X2 offer. The old
`136 -> double_chance` mapping was incorrect and caused qualification odds to
pollute cross-market arbitrage. `136` is the two-way "Ide dalje"
advance/qualification market and is now excluded, which is why the full-time
result needed its own ID here.

## MBet

Platform: Alea `events_cached`. Football market metadata was also checked via
`/markets?platform=web&lang=ba&extended=true`.

Odds arrive as colon-separated keys. Prematch uses `o<sport>:<market>:<outcome>`,
so the registry key is the middle two segments — `ofb:fs` is `Konacan ishod` (the
full-time result), `ofb:dc` is `Dupla sansa`, and `ofb:gg` is BTTS. The prematch
totals market uses outcome codes rather than words: `ofb:tg:2+` with `ofb:tg:0-1`
for 1.5, `ofb:tg:3+` with `ofb:tg:0-2` for 2.5 and `ofb:tg:4+` with `ofb:tg:0-3`
for 3.5. Only those six sides are read, so any other `ofb:tg:*` key is silently
ignored. Live drops the `o` prefix and the sport segment: the keys are
`lfb:ft:1`, `lfb:dc:1X`, `lfb:bttsny:Yes`, and the totals carry the direction and
threshold in the side name — `lfb:tg:over|1.5`, `lfb:tg:under|1.5`, and so on,
where the `|` is a literal part of the key and not a separator.

Six prefixes are dispatched: `fs`, `dc`, `gg`, `tg`, `ht` and `hc`. The last two
are **not** full-time result markets, and they are not ignored either — they are
experimental markets parsed directly, outside the registry:

- `ofb:ht` with sides `1`/`X`/`2` becomes `first_half_1x2`.
- `ofb:hc` is a two-way handicap keyed `H1|<line>` / `H2|<line>` and becomes
  `asian_handicap`; the favourite is the side with the lower odds, and all
  handicap lines are preserved rather than overwritten.

Two other prefixes look like the result market and are genuinely not mapped:
`ofb:fts` is first team to score (its labels can be `1`/`X`/`2`), and `ofb:fi` is
a baseball first-inning market that the football feed still carries. `ofb:sh` is
the second-half result. All three are in the registry's `_excluded` block, so
their unmapped-market diagnostic is suppressed on purpose.

## SportPlus

Platform: REST prematch offer. Football was found under `sportName=NOGOMET`.

The prematch feed is keyed by a numeric `id` field, and one id carries two
markets: the `NOGOMET` block (id `1`) is a combined full-time result and double
chance, accepted only when the complete label set is present. BTTS arrives as
`OBA TIMA DAJU GOL` (id `6`) with `Da`/`Ne` outcomes. The totals arrive twice
over: id `768` is a plain `ZBROJ GOLOVA 2,5` with `Vise`/`Manje` outcomes, and
ids `800`/`802` are the `RASPON GOLOVA` goal-range block whose `2+`/`01`,
`3+`/`02` and `4+`/`03` sides cover 1.5, 2.5 and 3.5. The parser keeps one
canonical market per `MarketType`, so a duplicate Over/Under 2.5 from the two
blocks is consolidated rather than emitted twice.

`id=4` (`PRVO POLUVRIJEME`) and `id=25` (`AZIJSKI HENDIKEP`) are supported
experimental markets, parsed directly rather than through the registry — an
earlier version of this file wrongly listed them as excluded. Everything else on
this book that is not a result/DC/BTTS/total is excluded by id or name pattern:
`TKO DA PRVI GOL` (first team to score, id `5`), the `HENDIKEP` block (ids
`308`-`311`), `NAČIN PROLAZA` advance (id `1285`), `POLUVRIJEME ILI KRAJ`
(half-time-or-full-time, id `178`), plus scorers, exact scores, corners, cards
and period markets.

## Mozzartbet

Platform: `betting/matches` API behind a Playwright session. Games are
identified by a numeric `id` with a short name: id `1` / `ki` is
`Konacan ishod`, id `2` / `ds` is `Dupla šansa`, id `3` / `ug` is
`Ukupno golova` and id `130` / `tgg` is `Oba tima daju gol`. The totals game
reports its sides under different names in live (`2+`/`0-1`, `3+`/`0-2`,
`4+`/`0-3`) than in prematch, so the parser matches on the game's short name and
resolves the line from the side names. The `gg3+` combination game and the `kmb`
combination game (id `141`) are excluded, as are games named `dalje`, `prolaz` or
`kvalifikacije`.

## EVLBet

Platform: SportsOfferApi football feed (`SportIds=388`). The live catalog
returned one basic offer signature across the sampled 1,500 events:
`BetTypeKey=12005`, `GameId=1`, description `Ishod meca`, and odds `1/X/2`.

Only the registered full-time result ID is accepted, and only with all three
outcomes. A `BasicOffer` carrying `HasSbv` or `Sbv` is a line-based market, not a
full-time result, and is rejected before any market is built. No extended or
detailed offers were present in the verified flat feed, so nothing else is mapped
until a concrete payload is captured.

## Betole

Betole is disabled by default. Its direct prematch feed is not NSoft `betTypeId`
data; odds are keyed by numeric pick codes in `esMatches[].odds`, and the
result pick codes carry the source labels `KI_1`/`KI_X`/`KI_2`. The live feed and
the `ttg_lang` market definitions were checked directly.

The scraper uses `/restapi/offer/ba/sport/S/desk`, skips live/blocked events, and
paginates with the feed's `from` offset. Pick codes `4`/`5`/`6` are a supported
experimental first-half result rather than an excluded market, and the period and
combination codes (`10`-`18`, `284`-`286`, `295`-`296`) are not mapped. The
`IDE DALJE` advance/qualification pair is `335`/`336`. Synthetic tests also
cover the legacy reference resolver and the verified pick-code mappings.

Note that the registry declares more pick codes per market than the parser reads
— for example the Over/Under rows list `137`/`138` and `3` alongside Betole's own
`242`/`21`, `24`/`22` and `25`/`219`. Those extra codes are harmless supersets
but they are not exercised, so treat the Betole row of the generated table as the
union of everything Betole might emit rather than a description of what it
currently parses.
