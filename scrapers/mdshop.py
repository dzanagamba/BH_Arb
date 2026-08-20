"""
MDShop Scraper — mdshop.ba (Direct HTTP API)

Uses NSoft's getwebevents API endpoint directly via httpx — no browser needed.
Much faster and more reliable than Playwright-based interception.

Endpoint: GET /api/offer/getwebevents
Parameters: sportId, isLive, dateFrom, dateTo, eventMappingTypes
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx

from config.settings import VERIFY_SSL
from models.schemas import Market, Match
from scrapers.base import fetch_with_retry
from scrapers.common import (
    nsoft_event_url,
    parse_dt,
    parse_nsoft_bets,
    parse_nsoft_live_bets,
    parse_teams_from_name,
)

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "mdshop"

SPORT_MAP: dict[int, str] = {
    1: "football",
}

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/utf8+json, application/json;q=0.9, text/plain;q=0.8, */*;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "language": "sr-Latn",
    "officeid": "1678",
    "referer": "https://www.mdshop.ba/",
    "Content-Type": "application/json",
}

BASE_API = "https://mdoffer.mdshop.ba/api/offer/getwebevents"

# NSoft bet type mapping — VERIFIED against the live MDShop catalog (2026-08):
# 135=1X2, 152=Double Chance, 151=BTTS, 137/138=O/U goals (threshold in sbv).
# 136 ("Ide dalje" advance market, knockout games only), 148/149 (half-time
# 1X2s), 140 (HT/FT), 153/154/166/174 (DNB/handicap/combos) and the half-total
# variants 143/144/161/162 are deliberately excluded. Parsing delegates to
# parse_nsoft_bets(), which also enforces strict outcome label sets.


def _parse_teams_from_name(event_name: str) -> tuple[str, str]:
    return parse_teams_from_name(event_name)


def _parse_dt(raw) -> datetime | None:
    return parse_dt(raw)


class MDShopScraper:
    """
    MDShop scraper using direct HTTP API calls.
    No Playwright needed — fast and reliable.
    """

    def __init__(self):
        self.base_url = BASE_API
        self.headers = dict(API_HEADERS)

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        """
        Fetch events for all sports and parse into Match objects.
        `live=True` fetches the in-play feed, which uses a different bet type
        ID space handled by parse_nsoft_live_bets().
        `scan_time` (naive UTC) is the single wall-clock for this scan — passed from
        server/api.py:run_scan so all scrapers use the same 14-day window. When None,
        falls back to now for standalone/test usage.
        """
        now_aware = (scan_time.replace(tzinfo=UTC) if scan_time and scan_time.tzinfo is None else scan_time) if scan_time else datetime.now(UTC)
        now_str = now_aware.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        future = now_aware + timedelta(days=14)
        future_str = future.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

        all_matches: list[Match] = []
        seen_codes: set[tuple] = set()  # (home, away, sport)

        async with httpx.AsyncClient(timeout=30.0, verify=VERIFY_SSL) as client:
            for sport_id, sport_name in SPORT_MAP.items():
                url = (
                    f"{self.base_url}?sportId={sport_id}&isLive={'true' if live else 'false'}"
                    f"&dateFrom={now_str}&dateTo={future_str}"
                    f"&eventMappingTypes=1&eventMappingTypes=2"
                    f"&eventMappingTypes=3&eventMappingTypes=4&eventMappingTypes=5"
                )
                try:
                    response = await fetch_with_retry(client, url, headers=self.headers)
                    if not response or response.status_code != 200:
                        logger.debug(
                            f"[MDShop] Sport {sport_name} returned {response.status_code if response else 'No response'}"
                        )
                        continue

                    data = response.json()
                    events = data.get("events", [])
                    if not events:
                        continue

                    logger.info(
                        f"[MDShop] {sport_name} {'live' if live else 'prematch'}: {len(events)} events"
                    )

                    for ev in events:
                        try:
                            match = self._parse_event(ev, sport_name, seen_codes, live=live)
                            if match:
                                all_matches.append(match)
                        except Exception as e:
                            logger.debug(f"[MDShop] Parse error: {e}")
                            continue

                except Exception as e:
                    logger.error(f"[MDShop] Error fetching {sport_name}: {e}")
                    continue

        logger.info(f"[MDShop] Total {'live' if live else 'prematch'}: {len(all_matches)} matches")
        return all_matches

    def _parse_event(
        self, ev: dict, sport_name: str, seen_codes: set, live: bool = False
    ) -> Match | None:
        """Parse a single API event dictionary into a Match."""
        event_name = ev.get("name", "")
        if " - " not in event_name:
            return None

        if live:
            # Skip simulated-reality events ("SRL ...") — not real matches
            name_l = event_name.lower()
            comp_l = str(ev.get("competitionName") or "").lower()
            if "srl" in name_l or "srl" in comp_l or "simul" in comp_l or "virtual" in comp_l:
                return None

        home, away = _parse_teams_from_name(event_name)
        if not home or not away:
            return None

        # Prefer the event ID for dedup — team-name pairs drop 2nd meetings of the same teams
        event_id = str(ev.get("id", ""))
        code = event_id if event_id else (home, away, sport_name)
        if code in seen_codes:
            return None
        seen_codes.add(code)

        kickoff = _parse_dt(ev.get("dateTime"))

        markets = self._parse_bets(ev.get("bets", []), live=live)
        if not markets:
            return None

        league_name = str(
            ev.get("competitionName") or ev.get("regionName") or ev.get("groupName") or ev.get("categoryName") or sport_name.capitalize()
        )

        return Match(
            bookmaker=BOOKMAKER_ID,
            home_team=home,
            away_team=away,
            league=league_name,
            kickoff=kickoff,
            markets=markets,
            url=nsoft_event_url("https://www.mdshop.ba", event_id, live=live),
            match_code=event_id,
            is_live=live,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    def _parse_bets(self, bets: list, live: bool = False) -> list[Market]:
        """Parse bet objects into Market list (validated NSoft parser)."""
        if live:
            return parse_nsoft_live_bets(bets)
        return parse_nsoft_bets(bets)

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        """
        Wrapper method compatible with our existing scraper interface.
        """
        return await self.fetch_and_parse(live=live, scan_time=scan_time)
