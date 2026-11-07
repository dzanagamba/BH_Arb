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
    idBt 11 -> O/U totals (spec="total=X,Y", t: Over/Under); the full
               half-goal lines 0,5 / 1,5 / 2,5 / 3,5 / 4,5 / 5,5 are mapped.
               Quarter/whole lines are a different bet and are not mapped.
  Football sport id is 2. Events expose `hname`/`aname`, `tname` (league),
  `cname` (country), `startTime` (epoch seconds), `brid` (Betradar id).

Live:
  GET /content/sport-livecontent/api/LiveEvents/events?key=bs&bets=&bet=&pbet=
      -> { events: [...] } (ids=2 is football)
  GET /content/sport-livecontent/api/LiveEvents/headerBets?bets=95,6,3,11
      -> { bets: [ { "<eventId>": { odds: [{va,t}], idBt, spec } } ] }
  Same market ids as prematch.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from engine.market_registry import MARKET_REGISTRY, record_unmapped, registered_spec
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import goto, launch_browser, measured_api_get, settle
from scrapers.common import betradar_id, qualify_league

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "wwin"
BASE_URL = "https://wwin.ba"
API_ROOT = f"{BASE_URL}/content/sport-livecontent/api"
FOOTBALL_SPORT_ID = 2


def _request_market_ids(mode: str) -> list[int | str]:
    """Return the IDs requested from WWIN for a registry mode."""
    ids: set[int | str] = set()
    if mode == "prematch":
        ids.add(2)  # first-half 1X2 remains an experimental prematch feed
    for market_type in (
        MarketType.MATCH_RESULT,
        MarketType.DOUBLE_CHANCE,
        MarketType.BTTS,
        MarketType.OVER_UNDER_0_5,
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
        MarketType.OVER_UNDER_4_5,
        MarketType.OVER_UNDER_5_5,
    ):
        ids.update(MARKET_REGISTRY.ids_for("wwin", mode, market_type))
    ordered: list[int | str] = [sid for sid in (95, 6, 3, 11, 2) if sid in ids]
    known = set(ordered)
    ordered.extend(sorted((sid for sid in ids if sid not in known), key=str))
    return ordered

# Verified WWIN market ids (football).
# 95 = full-time 1X2, 6 = double chance, 3 = BTTS (Yes/No),
# 11 = totals with the line in `spec` ("total=2,5"),
# 2 = half-time 1X2 (first half result, t: 1/X/2).
# Handicap (7, 10), HT/FT (4), advance "Prolaz" (476),
# Asian totals (443), correct score (51) etc. are deliberately excluded.
WWIN_OU_LINES = {
    "0,5": MarketType.OVER_UNDER_0_5,
    "1,5": MarketType.OVER_UNDER_1_5,
    "2,5": MarketType.OVER_UNDER_2_5,
    "3,5": MarketType.OVER_UNDER_3_5,
    "4,5": MarketType.OVER_UNDER_4_5,
    "5,5": MarketType.OVER_UNDER_5_5,
}


def _wwin_registered_spec(
    mode: str,
    bet_id: int | str,
    market_type: MarketType,
    line: float | None = None,
):
    """Resolve a WWIN ``idBt`` through the registry.

    The single registry-resolution step of :func:`_build_markets_from_bets`, at
    module scope so the WWIN resolution path is directly testable.
    """
    return registered_spec("wwin", mode, bet_id, market_type, line=line)


def _build_markets_from_bets(bets: list, mode: str = "prematch") -> list[Market]:
    """Map registered WWIN bet IDs into internal markets."""
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

    def registered_spec(bet_id, market_type: MarketType, line: float | None = None):
        return _wwin_registered_spec(mode, bet_id, market_type, line=line)

    for bet in bets:
        if not isinstance(bet, dict):
            continue
        bet_id = bet.get("idBt")
        odds = read_odds(bet)

        if bet_id == 95:
            spec = registered_spec(bet_id, MarketType.MATCH_RESULT)
            if spec is None:
                continue
            by_label = {o.label: o for o in odds if o.label in spec.labels}
            if len(by_label) >= spec.min_legs and set(by_label).issubset(spec.labels):
                markets.append(Market(
                    market_type=MarketType.MATCH_RESULT,
                    odds=[by_label[label] for label in ("1", "X", "2") if label in by_label],
                    source_id=str(bet_id),
                ))
        elif bet_id == 6:
            spec = registered_spec(bet_id, MarketType.DOUBLE_CHANCE)
            if spec is None:
                continue
            by_label = {o.label: o for o in odds if o.label in spec.labels}
            if len(by_label) >= spec.min_legs and set(by_label).issubset(spec.labels):
                markets.append(Market(
                    market_type=MarketType.DOUBLE_CHANCE,
                    odds=[by_label[label] for label in ("1X", "12", "X2") if label in by_label],
                    source_id=str(bet_id),
                ))
        elif bet_id == 3:
            spec = registered_spec(bet_id, MarketType.BTTS)
            if spec is None:
                continue
            by_label = {o.label: o for o in odds}
            gg = by_label.get("Yes")
            ng = by_label.get("No")
            btts_odds = [
                OddsValue(label=label, value=value)
                for label, value in (("GG", gg.value if gg else None), ("NG", ng.value if ng else None))
                if value is not None
            ]
            actual = {odd.label for odd in btts_odds}
            if (
                spec is not None
                and gg
                and ng
                and len(actual) >= spec.min_legs
                and actual.issubset(spec.labels)
            ):
                markets.append(
                    Market(market_type=MarketType.BTTS, odds=btts_odds, source_id=str(bet_id))
                )
        elif bet_id == 2 and mode == "prematch":
            # First-half 1X2 is an experimental market retained outside the
            # core registry; keep the historical payload support.
            by_label = {o.label: o for o in odds if o.label in ("1", "X", "2")}
            if set(by_label) == {"1", "X", "2"}:
                markets.append(Market(
                    market_type=MarketType.FIRST_HALF_1X2,
                    odds=[by_label[label] for label in ("1", "X", "2")],
                    source_id=str(bet_id),
                ))
        elif bet_id == 11:
            raw_spec = str(bet.get("spec") or "")
            line = raw_spec.replace("total=", "").strip()
            canonical_line = line.replace(",", ".")
            market_type = WWIN_OU_LINES.get(line)
            if market_type is None:
                market_type = next(
                    (
                        mt
                        for key, mt in WWIN_OU_LINES.items()
                        if key.replace(",", ".") == canonical_line
                    ),
                    None,
                )
            if market_type is None:
                continue
            try:
                line_value = float(canonical_line)
            except ValueError:
                continue
            spec = registered_spec(bet_id, market_type, line=line_value)
            if spec is None:
                continue
            over = next((o for o in odds if o.label.lower() == "over"), None)
            under = next((o for o in odds if o.label.lower() == "under"), None)
            ou_odds = [
                OddsValue(label=label, value=value)
                for label, value in (
                    (f"Over {canonical_line}", over.value if over else None),
                    (f"Under {canonical_line}", under.value if under else None),
                )
                if value is not None
            ]
            actual = {odd.label for odd in ou_odds}
            if (
                spec is not None
                and over
                and under
                and len(actual) >= spec.min_legs
                and actual.issubset(spec.labels)
            ):
                markets.append(
                    Market(market_type=market_type, odds=ou_odds, source_id=str(bet_id))
                )
        else:
            if bet_id is not None:
                record_unmapped("wwin", bet_id)
    return markets


def _remember_countries(data: object, countries: dict[object, str]) -> None:
    """Collect ``categories`` (country id -> name); events carry only ``idc``."""
    if not isinstance(data, dict):
        return
    for category in data.get("categories") or []:
        if isinstance(category, dict) and category.get("id") is not None:
            countries[category["id"]] = str(category.get("cname") or "")


def _country(event: dict, countries: dict[object, str]) -> str:
    return str(event.get("cname") or countries.get(event.get("idc")) or "")


class WWINScraper:
    """Scraper for wwin.ba — Playwright session + REST API."""

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        if live:
            return await self._fetch_live(scan_time=scan_time)
        return await self._fetch_prematch(scan_time=scan_time)

    async def _fetch_prematch(self, scan_time: datetime | None = None) -> list[Match]:
        all_matches: list[Match] = []
        seen_ids: set[str] = set()
        now = (scan_time.replace(tzinfo=UTC) if scan_time and scan_time.tzinfo is None else scan_time) if scan_time else datetime.now(UTC)

        countries: dict[object, str] = {}
        p, browser, context = await launch_browser()
        try:
            page = await context.new_page()
            await goto(page, f"{BASE_URL}/kladjenje/", wait_until="domcontentloaded", timeout=60000)
            await settle(page, 5000)

            # The events endpoint accepts at most two bet ids per call, so fetch
            # the markets in groups and merge by event id. P2: parallel fetch with retry.
            request_ids = _request_market_ids("prematch")
            bet_groups = tuple(
                ",".join(str(sid) for sid in request_ids[start:start + 2])
                for start in range(0, len(request_ids), 2)
            )
            sem = asyncio.Semaphore(6)

            async def fetch_one(day_offset: int, bets: str):
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
                tfrom = int((day_start - timedelta(hours=1)).timestamp())
                tto = int((day_start + timedelta(days=1, hours=2)).timestamp())
                for attempt in range(3):
                    try:
                        async with sem:
                            resp = await measured_api_get(
                                page,
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
                            if attempt < 2:
                                await asyncio.sleep(0.5 * (2 ** attempt))
                                continue
                            logger.debug(f"[WWIN] HTTP {resp.status} for day {day_offset} bets={bets}")
                            return day_offset, bets, []
                        try:
                            data = await resp.json()
                            _remember_countries(data, countries)
                            events = (data.get("events") or data.get("p") or []) if isinstance(data, dict) else []
                            return day_offset, bets, events
                        except Exception:
                            return day_offset, bets, []
                    except Exception as e:
                        if attempt < 2:
                            await asyncio.sleep(0.5 * (2 ** attempt))
                            continue
                        logger.debug(f"[WWIN] fetch error day {day_offset} bets={bets}: {e}")
                        return day_offset, bets, []
                return day_offset, bets, []

            tasks = [fetch_one(d, b) for d in range(15) for b in bet_groups]
            results = await asyncio.gather(*tasks)

            # Merge by day then by event_id
            by_day: dict[int, dict[str, dict]] = {}
            for day_offset, _bets, events in results:
                bucket = by_day.setdefault(day_offset, {})
                for event in events:
                    if not isinstance(event, dict) or event.get("id") is None:
                        continue
                    event_id = str(event["id"])
                    if event_id not in bucket:
                        bucket[event_id] = {**event, "bets": []}
                    bucket[event_id]["bets"].extend(event.get("bets", []) or [])

            for day_offset in sorted(by_day.keys()):
                merged = by_day[day_offset]
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
                        league=qualify_league(str(event.get("tname") or ""), _country(event, countries)) or "Fudbal",
                        country=_country(event, countries),
                        kickoff=kickoff,
                        markets=markets,
                        url=f"{BASE_URL}/kladjenje/",
                        match_code=event_id,
                        event_id=event_id,
                        betradar_id=betradar_id(event.get("brid")),
                        deep_link_verified=False,
                        fetched_at=datetime.now(UTC).replace(tzinfo=None),
                    ))
        finally:
            await browser.close()
            await p.stop()

        logger.info(f"[WWIN] Prematch total: {len(all_matches)} matches")
        return all_matches

    async def _fetch_live(self, scan_time: datetime | None = None) -> list[Match]:
        all_matches: list[Match] = []
        p, browser, context = await launch_browser()
        try:
            page = await context.new_page()
            await goto(page, f"{BASE_URL}/kladjenje-uzivo/", wait_until="domcontentloaded", timeout=60000)
            await settle(page, 5000)

            resp = await measured_api_get(
                page,
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
            countries: dict[object, str] = {}
            _remember_countries(data, countries)
            events = data.get("events", []) if isinstance(data, dict) else []
            football = [e for e in events if isinstance(e, dict) and e.get("ids") == FOOTBALL_SPORT_ID]
            if not football:
                return []

            ids = [str(e.get("idEvent")) for e in football if e.get("idEvent")]
            bet_map: dict[str, list] = {}
            for chunk_start in range(0, len(ids), 100):
                chunk = ids[chunk_start:chunk_start + 100]
                r2 = await measured_api_get(
                    page,
                    f"{API_ROOT}/LiveEvents/headerBets",
                    params={
                        "bets": ",".join(str(sid) for sid in _request_market_ids("live")),
                        "ids": ",".join(chunk),
                    },
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
                markets = _build_markets_from_bets(
                    bet_map.get(event_id, []), mode="live"
                )
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
                    league=qualify_league(str(event.get("tname") or ""), _country(event, countries)) or "Fudbal",
                    country=_country(event, countries),
                    kickoff=kickoff,
                    markets=markets,
                    url=f"{BASE_URL}/kladjenje-uzivo/",
                    match_code=event_id,
                    event_id=event_id,
                    betradar_id=betradar_id(event.get("brid")),
                    deep_link_verified=False,
                    is_live=True,
                    fetched_at=datetime.now(UTC).replace(tzinfo=None),
                ))
        finally:
            await browser.close()
            await p.stop()

        logger.info(f"[WWIN] Live total: {len(all_matches)} matches")
        return all_matches

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        return await self.fetch_and_parse(live=live, scan_time=scan_time)
