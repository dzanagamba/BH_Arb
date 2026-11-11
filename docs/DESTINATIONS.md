# Surebet leg destinations — dated coverage record

**Checked:** 2026-11-03; re-checked 2026-11-11 (SR9-1, and SR9-2 for the
MaxBet ticket and WWIN live)  
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

Re-checked 2026-11-11 (SR9-1) against fixtures from that day's scan; each
route's `proof.method` in the JSON record says whether the OpenChamber panel,
plain headless Chromium, or both showed it.

| Book | Best route | URL pattern | Identifier | Confirmed sample (2026-11-11) |
|---|---|---|---|---|
| Mozzartbet | match page | `https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/{event_id}` | feed event id | `10105660`, America Mineiro – Avai (panel) |
| MDShop | ticket filled | `https://www.mdshop.ba/sport-site/sr/#/betting/prematch?sport=Fudbal&ticketItems={ticket_items}` | NSoft `[sport, region, competition, event, bet, outcome]` | `7060446`, America MG – Avai; 1 @ 3.90 on the slip (panel) |
| Admiralbet | ticket filled | `https://www.admiralbet.ba/sport-site/sr/#/betting/prematch?sport=Fudbal&ticketItems={ticket_items}` | NSoft `[sport, region, competition, event, bet, outcome]` | `7060446`, America MG – Avai; 1 @ 3.90 on the slip (panel) |
| Betole | match page | `https://www.betole.ba/match-special/{event_id}` | feed event id (not `matchCode`) | `91420001`, America MG – Avai (operator's browser and headless; the panel renders all of Betole blank) |
| MBet | match page | `https://mbet.ba/single?id={event_id}` | feed event id | `e:fb:ame-ava:0002`, America MG – Avai (panel) |
| SportPlus | competition + manual prefill script | `https://www.sportplus.ba/prematch/betting` | book spelling for copying | page opened; no per-event route found yet (SR9-2) |
| Premier Kladionica | competition | `https://www.premier-kladionica.com/ponuda/` | book spelling for copying | page opened; no per-event route found yet (SR9-2) |
| WWIN | **match page (new)** | `https://wwin.ba/kladjenje/#/top-bets/match/{event_id}` | feed event id | `4730200`, America MG – Avai SC (operator's browser and headless; the panel shows an empty shell) |
| MaxBet | **ticket filled (new)** | `https://www.maxbet.ba/ba/sportsbook/match/{event_id}?outcome={outcome_id}` | feed event id + the row's own `odds[].outcomes[].id` | `1027619`, CD Universitario – Herrera FC; 1 @ 1.55 on the slip with the site's default stake (headless). Falls back to the confirmed match page when the row id is absent (SR9-2) |

## Live

| Book | Best route | URL pattern | Identifier | Confirmed sample (2026-11-11) |
|---|---|---|---|---|
| Mozzartbet | **competition (demoted)** | `https://www.mozzartbet.ba/sr/uzivo` | book spelling for copying | The live page needs the live-feed id (`/sr/uzivo/mec/1/74723528` opened Czech Republic M19 – Netherland M19), but the adapter's live rows carry the prematch id, which opens nothing. SR9-2 / SR8-1 |
| MDShop | ticket filled | `…/#/betting/live?sport=Fudbal&ticketItems={ticket_items}` | NSoft ids | `7070062`, Bangladesh – Sri Lanka; selection on the slip (headless) |
| Admiralbet | ticket filled | `…/#/betting/live?sport=Fudbal&ticketItems={ticket_items}` | NSoft ids | `7070062`, Bangladesh – Sri Lanka; selection on the slip (headless) |
| Betole | search fallback (no live leg priced) | — | book spelling for copying | not re-checked: the adapter returns no live matches (SR8-1) and live legs are not priced |
| MBet | **match page (route changed)** | `https://mbet.ba/live?id={event_id}` | feed event id | `e:fb:cze-net:0001`, Czech Republic U19 – Netherlands U19 (panel and headless); the old `single-live?id=` is now a 404 |
| SportPlus | competition (URL changed) | `https://www.sportplus.ba/live/betting` | book spelling for copying | `/live` is now a 404; `/live/betting` is the site's own live link |
| Premier Kladionica | competition (URL changed) | `https://www.premier-kladionica.com/live` | book spelling for copying | `/live` lists the in-play rows; `/ponuda/` does not |
| WWIN | **match page (new)** | `https://wwin.ba/kladjenje-uzivo/#/match/{event_id}` | feed live event id | `4732588`, Z.Podbrezova – Z.Moravce (operator's browser, 2026-11-11; the panel shows an empty shell, as for prematch) |
| MaxBet | **ticket filled (new)** | `https://www.maxbet.ba/ba/sportsbook/match/{event_id}?outcome={outcome_id}` | feed event id + the row's own `odds[].outcomes[].id` | `1032215`, CD Ibiza Islas Pitiusas – UD Arenal at HT; 1 @ 1.21 on the slip (headless). Falls back to the confirmed match page when the row id is absent (SR9-2) |

### Gate vs destination (MaxBet)

Until 2026-11-11 `config/bookmaker_deeplinks.json` declared MaxBet's route as
`https://sportsbook.maxbet.ba/match/{event_id}`, which renders blank in a
browser. By operator decision (2026-11-11) the declaration now names the page
that opens the fixture, `https://www.maxbet.ba/ba/sportsbook/match/{event_id}`,
for both modes; the fallback is `https://www.maxbet.ba/ba`. Event identity and
`route_pattern_verified` are unchanged.

### Operator browser checks (2026-11-11)

The operator opened the WWIN prematch route
(`#/top-bets/match/4730200`) and the Betole match route
(`/match-special/91420001`) in a normal browser and both showed the fixture. The
OpenChamber panel renders both sites as an empty shell, so it is not the reference
for these two books. WWIN prematch is a confirmed match page. Later the same day
the operator opened the WWIN live route for a live fixture from that day's scan
(`#/match/4732588`, Z.Podbrezova – Z.Moravce) and reported that it opens the
fixture, so WWIN live is a confirmed match page too.

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
- **MaxBet stake.** `?outcome=<row id>` puts the selection and its price on the
  slip; the stake stays the site's default (0.50 BAM). No stake parameter was
  found, so the ticket label also says “pick prefilled; set stake”. The row id is
  the `id` of each `odds[].outcomes[]` entry in the adapter's own list response;
  `outcomeId` is the market-type id and fills nothing.
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
  fallback. (2026-11-11: MaxBet is resolved by the `/ba/sportsbook/match/` path;
  WWIN opens in headless Chromium but still not in the panel.) The attempts are in
  the JSON record. This is the intended behaviour:
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
