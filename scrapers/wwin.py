"""
WWIN Scraper — wwin.ba

Playwright hybrid (browser session for Cloudflare) + REST API via page.request.

Verified against the live feed (2026-08-15):

Prematch:
  GET /content/sport-livecontent/api/PrematchEvents/events
      ?key=bs&bets=95,6,3,11&tfrom={epoch}&tto={epoch}&spid=2
  Returns { p: [events] } where each event embeds `bets[]`:
    idBt 95 -> 1X2 (t: 1/X/2)
    idBt 6  -> double chance (t: 1X/12/X2)
    idBt 3  -> BTTS (t: Yes/No)
    idBt 11 -> O/U totals (spec="total=X,Y", t: Over/Under); only
               lines 1,5 / 2,5 / 3,5 are supported.
  Football sport id is 2. Events expose `hname`/`aname`, `tname` (league),
  `cname` (country), `startTime` (epoch seconds), `brid` (Betradar id).

Live:
  GET /content/sport-livecontent/api/LiveEvents/events?key=bs&bets=&bet=&pbet=
      -> { events: [...] } (ids=2 is football)
  GET /content/sport-livecontent/api/LiveEvents/headerBets?bets=95,6,3,11
      -> { bets: [ { "<eventId>": { odds: [{va,t}], idBt, spec } } ] }
  Same market ids as prematch.
"""

import logging
from datetime import UTC, datetime, timedelta

from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import launch_browser

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "wwin"
BASE_URL = "https://wwin.ba"
API_ROOT = f"{BASE_URL}/content/sport-livecontent/api"
FOOTBALL_SPORT_ID = 2
MARKET_IDS = "95,6,3,11,2"

# Verified WWIN market ids (football).
# 95 = full-time 1X2, 6 = double chance, 3 = BTTS (Yes/No),
# 11 = totals with the line in `spec` ("total=2,5"),
# 2 = half-time 1X2 (first half result, t: 1/X/2).
# Handicap (7, 10), HT/FT (4), advance "Prolaz" (476),
# Asian totals (443), correct score (51) etc. are deliberately excluded.
WWIN_OU_LINES = {
    "1,5": MarketType.OVER_UNDER_1_5,
    "2,5": MarketType.OVER_UNDER_2_5,
    "3,5": MarketType.OVER_UNDER_3_5,
}


def _build_markets_from_bets(bets: list) -> list[Market]:
    """Map verified WWIN bets into internal markets (shared prematch/live)."""
    markets: list[Market] = []

    def read_odds(bet: dict) -> list[OddsValue]:
        odds: list[OddsValue] = []
        for o in bet.get("odds", []) or []:
            if not isinstance(o, dict):
                continue
            label = str(o.get("t") or "")
            try:
                value = float(o.get("va", 0.0))
            except (ValueError, TypeError):
                continue
            if value >= 1.01 and o.get("isv", 1) != 0:
                odds.append(OddsValue(label=label, value=value))
        return odds

    for bet in bets:
        if not isinstance(bet, dict):
            continue
        bet_id = bet.get("idBt")
        odds = read_odds(bet)

        if bet_id == 95:
            by_label = {o.label: o for o in odds if o.label in ("1", "X", "2")}
            if set(by_label) == {"1", "X", "2"}:
                markets.append(Market(
                    market_type=MarketType.MATCH_RESULT,
                    odds=[by_label[label] for label in ("1", "X", "2")],
                ))
        elif bet_id == 6:
            by_label = {o.label: o for o in odds if o.label in ("1X", "12", "X2")}
            if len(by_label) >= 2:
                markets.append(Market(
                    market_type=MarketType.DOUBLE_CHANCE,
                    odds=[by_label[label] for label in ("1X", "12", "X2") if label in by_label],
                ))
        elif bet_id == 3:
            by_label = {o.label: o for o in odds}
            gg = by_label.get("Yes")
            ng = by_label.get("No")
            if gg and ng:
                markets.append(Market(
                    market_type=MarketType.BTTS,
                    odds=[OddsValue(label="GG", value=gg.value), OddsValue(label="NG", value=ng.value)],
                ))
        elif bet_id == 2:
            by_label = {o.label: o for o in odds if o.label in ("1", "X", "2")}
            if set(by_label) == {"1", "X", "2"}:
                markets.append(Market(
                    market_type=MarketType.FIRST_HALF_1X2,
                    odds=[by_label[label] for label in ("1", "X", "2")],
                ))
        elif bet_id == 11:
            spec = str(bet.get("spec") or "")
            line = spec.replace("total=", "").strip()
            market_type = WWIN_OU_LINES.get(line)
            if market_type is None:
                continue
            over = next((o for o in odds if o.label.lower() == "over"), None)
            under = next((o for o in odds if o.label.lower() == "under"), None)
            if over and under:
                markets.append(Market(
                    market_type=market_type,
                    odds=[
                        OddsValue(label=f"Over {line.replace(',', '.')}", value=over.value),
                        OddsValue(label=f"Under {line.replace(',', '.')}", value=under.value),
                    ],
                ))
    return markets


class WWINScraper:
    """Scraper for wwin.ba — Playwright session + REST API."""

    async def fetch_and_parse(self, live: bool = False) -> list[Match]:
        if live:
            return await self._fetch_live()
        return await self._fetch_prematch()

    async def _fetch_prematch(self) -> list[Match]:
        all_matches: list[Match] = []
        seen_ids: set[str] = set()
        now = datetime.now(UTC)

        p, browser, context = await launch_browser()
        try:
            page = await context.new_page()
            await page.goto(f"{BASE_URL}/kladjenje/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            # The events endpoint accepts at most two bet ids per call, so fetch
            # the markets in groups and merge by event id.
            bet_groups = ("95,6", "3", "11", "2")
            for day_offset in range(0, 15):
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
                tfrom = int((day_start - timedelta(hours=1)).timestamp())
                tto = int((day_start + timedelta(days=1, hours=2)).timestamp())

                merged: dict[str, dict] = {}
                for bets in bet_groups:
                    resp = await page.request.get(
                        f"{API_ROOT}/PrematchEvents/events",
                        params={
                            "key": "bs",
                            "bets": bets,
                            "tfrom": str(tfrom),
                            "tto": str(tto),
                            "spid": str(FOOTBALL_SPORT_ID),
                        },
                        headers={"Accept": "application/json, text/plain, */*", "Referer": f"{BASE_URL}/kladjenje/"},
                    )
                    if resp.status != 200:
                        logger.debug(f"[WWIN] HTTP {resp.status} for day {day_offset} bets={bets}")
                        continue
                    try:
                        data = await resp.json()
                        events = (data.get("events") or data.get("p") or []) if isinstance(data, dict) else []
                    except Exception:
                        continue
                    for event in events:
                        if not isinstance(event, dict) or event.get("id") is None:
                            continue
                        event_id = str(event["id"])
                        if event_id not in merged:
                            merged[event_id] = {**event, "bets": []}
                        merged[event_id]["bets"].extend(event.get("bets", []) or [])

                for event_id, event in merged.items():
                    if event_id in seen_ids:
                        continue
                    seen_ids.add(event_id)
                    home = str(event.get("hname") or "").strip()
                    away = str(event.get("aname") or "").strip()
                    if not home or not away:
                        continue

                    markets = _build_markets_from_bets(event.get("bets", []) or [])
                    if not markets:
                        continue

                    kickoff = None
                    start = event.get("startTime")
                    if isinstance(start, int | float) and start > 0:
                        kickoff = datetime.fromtimestamp(start, tz=UTC).replace(tzinfo=None)

                    all_matches.append(Match(
                        bookmaker=BOOKMAKER_ID,
                        home_team=home,
                        away_team=away,
                        league=str(event.get("tname") or event.get("cname") or "Fudbal"),
                        country=str(event.get("cname") or ""),
                        kickoff=kickoff,
                        markets=markets,
                        url=f"{BASE_URL}/kladjenje/",
                        match_code=event_id,
                    ))
        finally:
            await browser.close()
            await p.stop()

        logger.info(f"[WWIN] Prematch total: {len(all_matches)} matches")
        return all_matches

    async def _fetch_live(self) -> list[Match]:
        all_matches: list[Match] = []
        p, browser, context = await launch_browser()
        try:
            page = await context.new_page()
            await page.goto(f"{BASE_URL}/kladjenje-uzivo/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            resp = await page.request.get(
                f"{API_ROOT}/LiveEvents/events",
                params={"key": "bs", "bets": "", "bet": "", "pbet": ""},
                headers={"Accept": "application/json, text/plain, */*", "Referer": f"{BASE_URL}/kladjenje-uzivo/"},
            )
            if resp.status != 200:
                logger.error(f"[WWIN] Live HTTP {resp.status}")
                return []
            try:
                data = await resp.json()
            except Exception:
                return []
            events = data.get("events", []) if isinstance(data, dict) else []
            football = [e for e in events if isinstance(e, dict) and e.get("ids") == FOOTBALL_SPORT_ID]
            if not football:
                return []

            ids = [str(e.get("idEvent")) for e in football if e.get("idEvent")]
            bet_map: dict[str, list] = {}
            for chunk_start in range(0, len(ids), 100):
                chunk = ids[chunk_start:chunk_start + 100]
                r2 = await page.request.get(
                    f"{API_ROOT}/LiveEvents/headerBets",
                    params={"bets": MARKET_IDS, "ids": ",".join(chunk)},
                    headers={"Accept": "application/json, text/plain, */*", "Referer": f"{BASE_URL}/kladjenje-uzivo/"},
                )
                if r2.status != 200:
                    continue
                try:
                    d2 = await r2.json()
                except Exception:
                    continue
                if not isinstance(d2, dict):
                    continue
                # headerBets returns one entry per (event, market) pair
                for item in d2.get("bets", []) or []:
                    if not isinstance(item, dict):
                        continue
                    for event_id, bet in item.items():
                        if isinstance(bet, dict):
                            bet_map.setdefault(str(event_id), []).append(bet)

            for event in football:
                event_id = str(event.get("idEvent") or "")
                if not event_id:
                    continue
                home = str(event.get("hname") or "").strip()
                away = str(event.get("aname") or "").strip()
                if not home or not away:
                    continue
                markets = _build_markets_from_bets(bet_map.get(event_id, []))
                if not markets:
                    continue
                kickoff = None
                start = event.get("startTime")
                if isinstance(start, int | float) and start > 0:
                    kickoff = datetime.fromtimestamp(start, tz=UTC).replace(tzinfo=None)
                all_matches.append(Match(
                    bookmaker=BOOKMAKER_ID,
                    home_team=home,
                    away_team=away,
                    league=str(event.get("tname") or event.get("cname") or "Fudbal"),
                    country=str(event.get("cname") or ""),
                    kickoff=kickoff,
                    markets=markets,
                    url=f"{BASE_URL}/kladjenje-uzivo/",
                    match_code=event_id,
                    is_live=True,
                ))
        finally:
            await browser.close()
            await p.stop()

        logger.info(f"[WWIN] Live total: {len(all_matches)} matches")
        return all_matches

    async def scrape(self, live: bool = False) -> list[Match]:
        return await self.fetch_and_parse(live=live)
