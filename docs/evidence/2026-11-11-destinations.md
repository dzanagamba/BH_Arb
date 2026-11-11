# 2026-11-11 destination re-check (SR9-1)

**Question:** does every surebet leg's link open the exact match, or a slip
holding the leg's selection?
**Fixtures:** taken from that day's scans (prematch `14:00:57`, live
`14:29`, state restored), mostly America MG – Avai (Brazil Serie B, 14.11.
20:30, listed by all nine books) and Czech Republic U19 – Netherlands U19 (in
play). Links were built with `engine.destinations.build_destination()` from the
cached `Match` rows, then opened.
**Browsers:** the OpenChamber browser panel ("panel", the operator's embedded
browser with the operator's own session) and plain headless Chromium 1440×900
with no request blocking ("headless"). The 2026-11-03 record showed the two can
disagree, so each verdict names which one saw it.
**Safety:** no login, no stake entered, nothing submitted. Ticket links only
prefill the site's slip. One America MG pick from the MaxBet test stayed on the
panel's MaxBet slip (the slip is a cross-origin frame the panel cannot click);
it was never submitted.

## Verdicts

| Book | Mode | Link the dashboard built | Result | Seen in |
|---|---|---|---|---|
| Mozzartbet | prematch | `/sr/kladjenje/sport/1/match/10105660` | fixture page | panel |
| Mozzartbet | live | `/sr/uzivo/mec/1/10108850` (prematch id) | **no fixture** — live list only | headless |
| MDShop | prematch | `ticketItems=[[1,10,772,7060446,644826088,2018088225]]` | slip: America MG – Avai, 1 @ 3.90 | panel |
| MDShop | live | `ticketItems=[[1,2,16,7070062,645832210,2021224627]]` | slip: Bangladesh – Sri Lanka, 1 selection | headless |
| Admiralbet | prematch | `ticketItems=[[1,10,772,7060446,644826220,2018088901]]` | slip: America MG – Avai, 1 @ 3.90 | panel |
| Admiralbet | live | same ids as MDShop | slip: Bangladesh – Sri Lanka | headless |
| Betole | prematch | `/match-special/91420001` | fixture page with 1X2 3.65/3.35/1.85 | headless (panel renders the whole site blank) |
| Betole | live | — | no live legs (adapter returns 0 live matches) | — |
| MBet | prematch | `/single?id=e:fb:ame-ava:0002` | fixture page | panel |
| MBet | live | `/single-live?id=e:fb:cze-net:0001` | **404 page** | headless |
| SportPlus | prematch | `/prematch/betting` (competition) | page opens | headless |
| SportPlus | live | `/live` (competition) | **404 page** | headless |
| Premier Kladionica | prematch | `/ponuda/` (competition) | page opens, empty until a league is picked | headless |
| Premier Kladionica | live | `/ponuda/` (competition) | no live list there | headless |
| WWIN | prematch | `#/top-bets` (competition) | page opens | panel |
| WWIN | live | `#/sport/2` (competition) | page opens | headless |
| MaxBet | prematch | `www.maxbet.ba/ba` (competition) | home page | headless |
| MaxBet | live | `www.maxbet.ba/ba` (competition) | home page | headless |

## Routes found or changed

| Book | Mode | Route | Result | Seen in |
|---|---|---|---|---|
| MaxBet | both | `https://www.maxbet.ba/ba/sportsbook/match/{event_id}` | fixture page (prematch 1024788; live 1028009 in play) | panel + headless |
| MaxBet | prematch | `…/sportsbook/match/{event_id}?outcome={outcome id}` | **selection on the slip**: America MG – Avai, Konačan ishod 1 @ 3.70 (outcome `146730868`) | panel + headless |
| MBet | live | `https://mbet.ba/live?id={event_id}` (what the site navigates to on click) | fixture with live markets | panel + headless |
| Mozzartbet | live | `/sr/uzivo/mec/1/{live id}` with the live-feed id `74723528` | fixture with in-play markets | headless |
| WWIN | prematch | `#/top-bets/match/{event_id}` (4730200) | fixture page | headless only — panel shows the empty shell |
| WWIN | live | `#/match/{event_id}` (4734682) | in-play fixture | headless only |
| SportPlus | live | `/live/betting` (site's own link) | live list | headless |
| Premier Kladionica | live | `/live` | live rows | headless |

MaxBet's outcome id is the `id` of each `odds[].outcomes[]` entry in the
`/sportsbook/rest/v2/matches/{id}` payload (for example
`{"id": 146730868, "outcome": "America MG", "outcomeId": "1001", "oddValue": 3.7}`);
`outcomeId` is the type id, not this one. The Mozzartbet live id
(`74723528`) equals SportPlus's id for the same match.

## Applied to `config/bookmaker_destinations.json`

Every route above carries a 2026-11-11 proof, and the previous proof moved to
`attempts`. Promoted: MaxBet match page (both modes), MBet live `/live?id=`.
Demoted: Mozzartbet live match page (falls back to `/sr/uzivo`). URL fixes:
SportPlus live `/live/betting`, Premier live `/live`. WWIN stays `failed` until an
operator click confirms it. The MaxBet ticket route needs the outcome id in the
adapter and is SR9-2 work. `config/bookmaker_deeplinks.json` (the gate) was not
changed; its MaxBet template `sportsbook.maxbet.ba/match/{id}` renders blank in
both browsers — operator decision.

Screenshots: `docs/evidence/2026-11-11-destinations/`.

## Operator follow-up (same day)

The operator opened `https://wwin.ba/kladjenje/#/top-bets/match/4730200` and
`https://www.betole.ba/match-special/91420001` in a normal browser: both
"open the match". WWIN prematch was promoted to a confirmed match page and
Betole's proof names the check; WWIN live awaits its own click. The operator
also approved changing the MaxBet gate template to
`https://www.maxbet.ba/ba/sportsbook/match/{event_id}`, now applied in
`config/bookmaker_deeplinks.json`.
