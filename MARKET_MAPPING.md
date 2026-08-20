# Football Market Mapping

This is the canonical market audit for the seven configured bookmakers. The
scanner emits only the six `MarketType` values in `models/schemas.py`. Any
offer with a similar-looking outcome label is ignored unless its settlement
meaning and complete outcome set are known.

Audit date: 2026-08-14. Live sources were checked where the bookmaker API was
reachable. Decimal odds are for the regular match settlement, not extra time,
penalties, or a different period.

## Live (In-Play) Feeds

The app supports two scan modes: `prematch` (future matches) and `live`
(in-play matches). Live feeds use their own market structures, verified
against the live APIs (2026-08-14):

| Bookmaker | Live feed | Mapped markets | Notes |
| --- | --- | --- | --- |
| MDShop / Admiralbet | `getwebevents?isLive=true` | NSoft live IDs: `6`=1X2 (score in `sbv`), `18`/`42`=DC, `995`=BTTS, `22`/`28`=O/U (line in `sbv`) | Different ID space from prematch; SRL simulated events skipped; dead sides (e.g. under 2.5 at 3-0) are dropped |
| MBet | `events_cached?live=true` | `lfb:ft`=1X2, `lfb:dc`=DC, `lfb:bttsny` (Yes/No)=BTTS, `lfb:tg:over\|X.5`=O/U | `finished` events and CLOSED markets skipped; `tg1sth` (1st-half totals) excluded |
| SportPlus | `/api/v1/live/offer` | by market name: `Pobjednik`=1X2, `Dvostruka Prilika`=DC, `Oba daju gol`=BTTS (`1(D)`/`2(N)`), `Zbroj golova X.5`=O/U (`1(M)`/`2(V)`) | Matches with `betting: false` skipped; `ML/`-style team prefixes stripped |
| Mozzartbet | `betting/matches` with `date:"live"` | same games as prematch (1/2/3/130) | feed also returns upcoming fixtures — only events whose `startTime` has passed are kept |
| EVLBet | — | none | the live feed (`matches/live`) carries scores but no odds (`Offers` always empty); EVLBet is skipped in live mode |
| Betole | same desk feed, `live: true` events | same pick codes as prematch (1/2/3, 7/8/9, 272/273, O/U pairs) | SRL simulated events skipped |

The arbitrage engine keeps in-play groups (past kickoffs) in live mode; the
prematch mode still expires matches that started more than 15 minutes ago.

## WWIN

Platform: `sport-livecontent` REST API (Playwright session for Cloudflare).
Football sport id is `2`; events expose `brid` (Betradar id).

| Source offer | Mapping | Decision |
| --- | --- | --- |
| `idBt=95` (t: `1/X/2`) | Full-time 1X2 | Supported only with all three |
| `idBt=6` (t: `1X/12/X2`) | Full-time double chance | Supported with ≥2 legs |
| `idBt=3` (t: `Yes/No`) | BTTS | Supported |
| `idBt=11` (spec `total=1,5`/`2,5`/`3,5`, t: `Over`/`Under`) | O/U goals | Supported for 1.5/2.5/3.5 only |
| `idBt=7` (DNB), `10` (3-way handicap), `4` (HT/FT), `2` (1st-half 1X2), `476` ("Prolaz" advance), `443` (Asian totals incl. quarter lines), `51` (correct score) | Other | Excluded |

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
outcome codes (e.g. `1/X/2`, `da/ne`, `m/v`) from `setTipTip`.

| Source offer (football, grupaTipID=2) | Mapping | Decision |
| --- | --- | --- |
| `UTAKMICA` with kods `1/X/2` | Full-time 1X2 | Supported only with all three |
| `UTAKMICA` with kods `1X/X2/12` | Full-time double chance | Supported with ≥2 legs |
| `OBA DAJU GOL` (kods `da/ne` or `o-da/o-ne`) | BTTS | Supported |
| `ZBROJ GOLOVA` (kods `m/v`) with line `(-1,5+)`/`(-2,5+)`/`(-3,5+)` | O/U 1.5/2.5/3.5 | Supported |
| `LIVE - UTAKMICA` / `LIVE - OBA DAJU GOL` / `LIVE - ZBROJ GOLOVA` | In-play markets | Used in live mode only |
| `HENDIKEP`, `KLAĐENJE NA POBJEDU` (DNB), `POLUVRIJEME / KRAJ`, `1./2. POLUVRIJEME - ...`, `TOČAN ...`, `RASPON ...`, `PAR/NEPAR`, corners/cards, `NAČIN PROLAZA` (advance), scorers, combos | Other | Excluded |

## Supported Internal Markets

| Internal type | Required outcomes | Meaning |
| --- | --- | --- |
| `1x2` | `1`, `X`, `2` | Full-time match result |
| `double_chance` | At least two of `1X`, `12`, `X2` | Full-time double chance |
| `btts` | `GG`, `NG` | Both teams to score |
| `over_under_1_5` | `Over 1.5`, `Under 1.5` | Total match goals |
| `over_under_2_5` | `Over 2.5`, `Under 2.5` | Total match goals |
| `over_under_3_5` | `Over 3.5`, `Under 3.5` | Total match goals |

## MDShop

Platform: NSoft `getwebevents`, standard NSoft IDs, threshold in lowercase
`sbv`.

| Source offer | Mapping | Decision |
| --- | --- | --- |
| `betTypeId=135` | Full-time 1X2 | Supported only with all `1/X/2` |
| `betTypeId=152` | Full-time double chance | Supported with at least two valid legs |
| `betTypeId=151` | BTTS | Supported only with `GG/NG` |
| `betTypeId=137/138` + `sbv=1.5/2.5/3.5` | Full-time O/U | Supported |
| `136` | "Ide dalje" advance/qualification, two-way `1/2` | Excluded |
| `140`, `148`, `149` | HT/FT and half-time 1X2 | Excluded |
| `143`, `144`, `161`, `162` | Half-period totals | Excluded |
| `153`, `154`, `166`, `174` | DNB, handicap, or result-without-goals variants | Excluded |

Unsupported O/U thresholds such as `4.5`, `5.5`, and `6.5` are excluded.

## Admiralbet

Platform: NSoft `getwebevents`, but Admiralbet uses `sBV` and has a
bookmaker-specific full-time result ID.

| Source offer | Mapping | Decision |
| --- | --- | --- |
| `betTypeId=1639` | Full-time 1X2 | Supported only with all `1/X/2` |
| `betTypeId=152` | Full-time double chance | Supported with at least two valid legs |
| `betTypeId=151` | BTTS | Supported only with `GG/NG` |
| `betTypeId=137/138` + `sBV=1.5/2.5/3.5` | Full-time O/U | Supported |
| `136` | "Ide dalje" advance/qualification, two-way `1/2` | Excluded; never DC or 1X2 |
| `140`, `148`, `149`, `143`, `144`, `161`, `162` | HT/FT, half-time, or half-total variants | Excluded |
| `153`, `154`, `166`, `174` | DNB, handicap, or result-without-goals variants | Excluded |

The live catalog confirmed `1639` is the real Admiralbet 1X2 offer. The old
`136 -> double_chance` mapping was incorrect and caused qualification odds to
pollute cross-market arbitrage.

## MBet

Platform: Alea `events_cached`. Football market metadata was also checked via
`/markets?platform=web&lang=ba&extended=true`.

| Source key | Mapping | Decision |
| --- | --- | --- |
| `ofb:fs:1/X/2` | `Konacan ishod`, full-time result | Supported only when all three exist |
| `ofb:dc:1X/12/X2` | `Dupla sansa`, full-time | Supported |
| `ofb:gg:GG/NG` | `GG/NG` | Supported |
| `ofb:tg:2+` + `0-1` | O/U 1.5 | Supported |
| `ofb:tg:3+` + `0-2` | O/U 2.5 | Supported |
| `ofb:tg:4+` + `0-3` | O/U 3.5 | Supported |
| `ofb:fts` | First team to score; labels may look like `1/X/2` | Excluded |
| `ofb:ht`, `ofb:sh` | First-half or second-half result | Excluded |
| `ofb:htdc`, `ofb:shdc` | Period-specific double chance | Excluded |
| `ofb:dnb`, `ofb:hc` | Draw-no-bet or handicap | Excluded |
| `ofb:fi` | First-inning result for baseball, not football | Excluded |
| Other `ofb:tg:*` | Exact/range goal totals or team goals | Excluded |

## SportPlus

Platform: REST prematch offer. Football was found under `sportName=NOGOMET`.

| Source market | Mapping | Decision |
| --- | --- | --- |
| `id=1`, `NOGOMET` | Combined full-time 1X2 and DC block | Supported with complete labels |
| `id=6`, `OBA TIMA DAJU GOL` | BTTS (`Da/Ne`) | Supported |
| `id=768`, `ZBROJ GOLOVA 2,5` | O/U 2.5 (`Vise/Manje`) | Supported |
| `id=800/802`, `RASPON GOLOVA` | O/U 1.5, 2.5, and 3.5 from `2+/01`, `3+/02`, `4+/03` | Supported; duplicate O/U 2.5 is consolidated |
| `id=4`, `PRVO POLUVRIJEME` | First-half result/DC | Excluded |
| `id=5`, `TKO DA PRVI GOL` | First team to score | Excluded |
| `id=25`, `AZIJSKI HENDIKEP`; `308-311`, `HENDIKEP` | Handicap | Excluded |
| `id=1285`, `NAČIN PROLAZA` | Advance/qualification | Excluded |
| `id=178`, `POLUVRIJEME ILI KRAJ` | Period-or-full-time combination | Excluded |
| Other combo, scorer, exact-score, corner, card, and period markets | Different settlement | Excluded |

The parser keeps one canonical market per `MarketType` when standard O/U 2.5
and the equivalent goal-range block are both present.

## Mozzartbet

Platform: `betting/matches` API behind a Playwright session.

| Source game | Mapping | Decision |
| --- | --- | --- |
| `id=1`, short name `ki` | `Konacan ishod`, full-time 1X2 | Supported only with `1/X/2` |
| `id=2`, short name `ds` | `Dupla sansa` | Supported with valid DC legs |
| `id=3`, short name `ug` | `Ukupno golova`; live aliases `2+/0-1`, `3+/0-2`, `4+/0-3` | Supported for 1.5/2.5/3.5 |
| `id=130`, short name `tgg` | BTTS (`gg/ng`) | Supported; `gg3+` combo is excluded |
| `id=141`, short name `kmb` | Mozzart combinations | Excluded |
| Games named `dalje`, `prolaz`, or `kvalifikacije` | Advance/qualification | Excluded |

## EVLBet

Platform: SportsOfferApi football feed (`SportIds=388`). The live catalog
returned one basic offer signature across the sampled 1,500 events:
`BetTypeKey=12005`, `GameId=1`, description `Ishod meca`, and odds `1/X/2`.

| Source offer | Mapping | Decision |
| --- | --- | --- |
| `BasicOffer` `12005` / `GameId=1` | Full-time 1X2 | Supported only with all three outcomes |
| `BasicOffer` with `HasSbv` or `Sbv` | Line-based market, not full-time result | Excluded |
| Other/extended offers | Not present in the verified flat feed | Not mapped until a concrete payload is verified |

## Betole

Betole is disabled by default. Its direct prematch feed is not NSoft
`betTypeId` data; odds are keyed by numeric pick codes in `esMatches[].odds`.
The live feed and `ttg_lang` definitions were checked directly.

| Pick codes | Mapping | Decision |
| --- | --- | --- |
| `1/2/3` | Full-time 1X2 (`KI_1/KI_X/KI_2`) | Supported only with all three |
| `7/8/9` | Full-time DC (`1X/12/X2`) | Supported with at least two |
| `272/273` | BTTS (`GG/NG`) | Supported |
| `242/21` | O/U 1.5 | Supported when both are present |
| `24/22` | O/U 2.5 | Supported when both are present |
| `25/219` | O/U 3.5 | Supported when both are present |
| `4/5/6` | First-half result | Excluded |
| `10-18`, `284-286`, `295-296`, and other combinations | Period/combo markets | Excluded |
| `335/336` (`IDE DALJE`) | Advance/qualification | Excluded |

The scraper uses `/restapi/offer/ba/sport/S/desk`, skips live/blocked events,
and paginates with the feed's `from` offset. Synthetic tests also cover the
legacy reference resolver and the verified pick-code mappings.
