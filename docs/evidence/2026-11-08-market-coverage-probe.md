# Market-coverage probe: Mozzartbet and Betole (2026-11-08)

Question: both books are flagged `degraded — missing markets` while peers publish up
to 14 market families. Are the parsers dropping markets the feeds actually serve?

Method: live probes, read-only, one request or one browser session per endpoint on
2026-11-08 between 00:00 and 00:30 (local). No fixtures were written and no scan
settings were changed.

## Betole — `GET /restapi/offer/ba/sport/S/desk`

- 1,415 events in the response, 820 parsed matches in the scan.
- 30 distinct pick codes across all events, and the same set on every event:
  `1 2 3 4 5 6 22 24 272 273` (the four supported families plus the
  experimental first-half 1X2) and 20 more codes on 1,106 of the events.
- Those 20 codes (plus `335`/`336`) are exactly the registry's
  `_excluded.betole` list, so they are deliberately not recorded as unmapped.
- Betole serves its bet-type catalog at
  `GET /restapi/offer/ba/ttg_lang?desktopVersion=2.47.6.10&locale=ba`
  (`betMap`, `betPickMap`, `betPickGroupMap`; 1,204 bets, 6,426 picks). Decoding
  the excluded codes there shows they are **not supported market families**:

| codes | catalog name | what it is |
|---|---|---|
| 284, 285, 286 | `AT_1` / `AT_X` / `AT_2` | team wins the match *or* the first half |
| 295, 296 | `DP_1` / `DP_2` | team wins both halves |
| 316, 317, 363, 364, 50244, 50310, 50311, 50685, 51568, 53171, 55173, 55182, 615 | `P1_PLUS_D2_PLUS`, `G1P1_3_G2P1_3`, … | goals in the first half **and** the second half / by full time (mix games) |
| 335, 336 | `K_ID_1` / `K_ID_2` | qualification / advance to the next round |
| 55352, 55353 | `G2INROW_Y` / `G2INROW_N` | one team scores two goals in a row |

- No handicap, no 1.5/3.5 totals and no double chance is present in this feed,
  which matches the 2026-11-05 fixture provenance.
- The event's `oddsCount` is ~860 against 30 picks in `odds`: the full offer only
  exists on the match page (per-event request). The sport page's
  `GET /restapi/offer/ba/bp/desk` is a page layout catalog, not offers.

## Mozzartbet — `POST /betting/matches` (the adapter's list endpoint)

- One page (15 events, `pageSize=15`, `date=all_days`, `sportId=1`) carries
  14 odds per event and 5 `oddsGroup` entries:
  - `Konačan ishod` (1X2): `1`, `X`, `2`
  - `Dupla šansa` (DC): `1X`, `12`, `X2`
  - `Ukupno golova na meču` (totals): `2+`, `0-2`, `3+` — only the 2.5 line is
    complete (`2+`/`0-1` would be needed for 1.5)
  - `Oba tima daju gol` (BTTS): `gg`, `ng`, plus `gg3+` (not our BTTS family)
  - `Broj golova u prvom i drugom poluvremenu`: per-half goals (mix game)
  - Plus game `141` "Mozzart kombinacije", excluded.
- Unknown games would be recorded as unmapped; none were, so the parser is not
  dropping anything the list feed carries.
- The same event reports `totalOddsCount` 518 while the list carries 14: the
  full offer lives on the match page (per-event request).

## Conclusion

Neither parser drops a supported family. The list/desk endpoints genuinely carry
four complete supported families per event. More markets for these two books means
one request per event (652 Mozzartbet + 820 Betole in the 2026-11-07 scan), which
would take the scan from 124 requests to roughly 1,470 (+12.9x) and add ~130 s per
book at the current 5 requests/second ceiling — over the 240 s per-adapter
deadline. That is an operator decision, tracked as SR7-1.

## Outcome (2026-11-08, same day)

The operator chose **B — full fetch** (SR7-1). Both books now parse their full
offer:

- **Betole** has a bulk endpoint: `GET /restapi/offer/ba/matches/by-ids` with
  `matchIdsToken=<comma-separated ids>` and `annex=0` (the annex code comes from
  `/ibet2/parametersData.json`). One request per 40 events, so 809 matches cost
  22 requests including the desk listing. The pick codes are the same as the
  desk feed's; the full offer adds 7/8/9 (double chance) and the 1.5/3.5/4.5/5.5
  totals, all of which are now emitted.
- **Mozzartbet** has no bulk variant (the list call's load flags change nothing),
  so `POST /betting/match/{id}` is fetched per event (the GET form answers
  "Not found"). The full offer adds game 4 (first-half 1X2) and the complete
  1.5/3.5/4.5 totals.
- Measured: requests per scan 124 → 777, bytes 234.7 MB → 433.0 MB, scan wall
  105 s → 237 s; markets per event betole 4.0 → 8.2, Mozzartbet 4.1 → 7.9; both
  books left `degraded` (Mozzartbet's missing rate 0.558 → 0.170).
- Handicap and Asian handicap remain unmapped: the offers carry the picks
  (Betole 201-203 / 421-426) but not the line value in the odds map, so they
  need a separate capture before they can be priced.

Reproduce: `scrapers/betole._fetch_full_offers` and
`scrapers/mozzartbet.MozzartbetScraper._complete_offer` are the two fetchers;
`tests/test_full_offer_markets.py` pins their shape and the family sets.
