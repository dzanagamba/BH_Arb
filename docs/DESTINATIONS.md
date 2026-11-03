# Surebet leg destinations — dated coverage record

**Checked:** 2026-11-03  
**Scope:** the nine enabled football books. EVLBet is disabled and excluded.  
**Method:** operator spot check in the OpenChamber browser against each book's
own site. No bookmaker credentials were stored and no bet was placed. A route is
confirmed only when the fixture (and, for a ticket-filled route, the populated
selection) was seen on the page.

The machine-readable record is `config/bookmaker_destinations.json`. It is the
only input to `engine/destinations.py`; the dashboard does not infer a label
from the presence of a URL. A route without a confirmed proof is never used at a
higher rung: a ticket route without a populated-ticket proof is not a ticket, and
a per-event route without a fixture proof is not a match page.

## Route ladder

| Rung | Meaning |
|---|---|
| `ticket_filled` | The fixture opens with this leg's selection already on the ticket. Where the site accepts it, the planned stake is shown too. |
| `match_page` | The per-event page for the fixture. |
| `search` | The book's own spelling, offered for copying (and a search URL only when one is confirmed). |
| `competition` | The book's competition page. |

## Prematch

| Book | Best route | URL pattern | Identifier | Confirmed sample |
|---|---|---|---|---|
| Mozzartbet | match page | `https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/{event_id}` | feed event id | `10088115`, Shakhtar – Sporting |
| MDShop | ticket filled | `https://www.mdshop.ba/sport-site/sr/#/betting/prematch?sport=Fudbal&ticketItems={ticket_items}` | NSoft `[sport, region, competition, event, bet, outcome]` | `6971587`, Shakhtar Donetsk – Sporting; 1 @ 3.42 on the slip |
| Admiralbet | ticket filled | `https://www.admiralbet.ba/sport-site/sr/#/betting/prematch?sport=Fudbal&ticketItems={ticket_items}` | NSoft `[sport, region, competition, event, bet, outcome]` | `6971587`, Shakhtar Donetsk – Sporting; GG @ 1.64 on the slip |
| Betole | match page | `https://www.betole.ba/match-special/{event_id}` | feed event id (not `matchCode`) | `91367737`, Sporting CP – Moreirense (operator-confirmed; the embedded panel has a site JS error) |
| MBet | match page | `https://mbet.ba/single?id={event_id}` | feed event id | `e:fb:sha-spo:0001`, Shakhtar Donetsk – Sporting CP |
| SportPlus | competition + manual prefill script | `https://www.sportplus.ba/prematch/betting` | book spelling for copying | football competition page; the slip itself is localStorage-only |
| Premier Kladionica | competition | `https://www.premier-kladionica.com/ponuda/` | book spelling for copying | `/ponuda/`; `/ponuda/<id>` is 404 |
| WWIN | competition fallback | `https://wwin.ba/kladjenje/#/top-bets` | book spelling for copying | direct `#/top-bets/match/4684404` showed the generic page, not the fixture |
| MaxBet | competition fallback | `https://www.maxbet.ba/ba` | book spelling for copying | `/match/971607` and `sportsbook.maxbet.ba/sport/1` rendered blank; `www.maxbet.ba/ba` opened |

## Live

| Book | Best route | URL pattern | Identifier | Confirmed sample |
|---|---|---|---|---|
| Mozzartbet | match page | `https://www.mozzartbet.ba/sr/uzivo/mec/1/{event_id}` | feed event id | `74560606`, Shakhtar M19 – Sporting M19 |
| MDShop | ticket filled | `https://www.mdshop.ba/sport-site/sr/#/betting/live?sport=Fudbal&ticketItems={ticket_items}` | NSoft `[sport, region, competition, event, bet, outcome]` | `7030846`, Estrela U23 – Santa Clara U23; rest-of-match 1 @ 2.34 on the slip |
| Admiralbet | ticket filled | `https://www.admiralbet.ba/sport-site/sr/#/betting/live?sport=Fudbal&ticketItems={ticket_items}` | NSoft `[sport, region, competition, event, bet, outcome]` | `7030846`, Estrela U23 – Santa Clara U23; rest-of-match 1 @ 2.34 on the slip |
| Betole | search fallback (no live leg priced) | `https://www.betole.ba/live-special/{match_code}` is valid; no live leg is produced | book spelling for copying | live route `273` opened Shakhtar Donetsk U19 – Sporting CP U19; live markets lack a score guard, so no leg is priced |
| MBet | match page | `https://mbet.ba/single-live?id={event_id}` | feed event id | `e:fb:sha-spo:0002`, Shakhtar Donetsk U19 – Sporting CP U19 |
| SportPlus | competition | `https://www.sportplus.ba/live` | book spelling for copying | live competition page |
| Premier Kladionica | competition | `https://www.premier-kladionica.com/ponuda/` | book spelling for copying | live offer on the same page |
| WWIN | competition fallback | `https://wwin.ba/kladjenje-uzivo/#/sport/2` | book spelling for copying | direct `#/match/4713116` showed the generic live page, not the fixture |
| MaxBet | competition fallback | `https://www.maxbet.ba/ba` | book spelling for copying | `/match/1006541` rendered blank; `www.maxbet.ba/ba` opened with top matches |

## SportPlus manual ticket prefill

SportPlus has no per-event URL and no ticket query parameter. Its Angular page
keeps the slip in `localStorage["cn-prematch.ticket"]`: an object with `pairs`, `info` and
`type`. On load, `checkTicketFromStorage` matches each pair against the current
offer by `matchId`, `market.code` and `odd.alias`, then recalculates the slip.

The dashboard therefore keeps the honest `competition` label and additionally
offers **Copy SportPlus prefill script (manual, not a link)**. The script:

1. fetches `/api/v1/prematch/offer` (the response is XML-wrapped JSON),
2. finds the match by the scraper's `sportplus_match_id`,
3. finds the market by `sportplus_market_code`,
4. finds the selection by the alias recorded for that outcome,
5. writes one pair with the planned stake to `localStorage["cn-prematch.ticket"]` and
   reloads the page.

It never places a bet. It is not labelled `ticket-filled` because a URL cannot
perform it and the operator must paste it into the SportPlus page console. The
live offer has a different shape, so the script is prematch-only.

## Honest limits

- **NSoft stake.** MDShop and Admiralbet accept the selection and its odds in
  the URL (`ticketItems`). They do not accept a stake query parameter, so the
  slip shows the site's default stake. The dashboard labels these links
  “pick prefilled; set stake” and still shows the planned stake for copying.
- **Betole live.** The client route `live-special/{matchCode}` is valid — the
  sampled live event `273` opened Shakhtar Donetsk U19 – Sporting CP U19. The
  scraper does not price Betole live because its desk feed exposes
  rest-of-match markets without a score field, so a live 1X2 leg cannot be
  distinguished safely from a full-time one. No live leg is produced, and the
  destination falls back instead of inventing a link. Adding live mappings
  needs a score guard first.
- **Operator-browser truth.** The first pass confirmed several routes only in a
  headless probe. Re-checking them one by one in the actual operator browser
  changed the classification: Betole prematch/live, WWIN prematch/live and
  MaxBet prematch/live render blank or generic pages, so they are recorded as
  failed routes. WWIN and MaxBet use a confirmed competition page; Betole's own
  site rendered blank even at the competition page, so it is a copy-only search
  fallback. The attempts are in the JSON record. This is the intended behaviour:
  a route the operator cannot reach is not called a match page.
- **Search URLs.** Mozzartbet, MDShop, Admiralbet, Betole, MBet, SportPlus,
  Premier Kladionica, WWIN and MaxBet expose in-page search, not a stable
  query-string URL. Their search rung therefore offers the book's own spelling
  for copying instead of inventing a query URL. When a competition URL is also
  recorded, the dashboard uses that clickable page and keeps the spelling for
  its in-page search.
- **No gate effect.** These destinations never set `deep_link_verified`, never
  change a group's status, and are not part of the certainty gate. A manual link
  check still cannot make an unverified group display.
