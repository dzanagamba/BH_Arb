"""
EVLBet Scraper — evlbet.com (Direct HTTP API)

Uses EVLBet's SportsOfferApi endpoint directly via httpx — no browser needed.
Endpoint: GET https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat?SportIds=388&Limit=100&Offset={offset}
"""

import logging
from datetime import UTC, datetime

import httpx

from config.settings import VERIFY_SSL
from engine.market_registry import MARKET_REGISTRY, record_unmapped
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import fetch_with_retry
from scrapers.common import parse_dt

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "evlbet"
BASE_URL = "https://evlbet.com"
API_URL = "https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}


def _parse_dt(raw) -> datetime | None:
    return parse_dt(raw)


class EvlbetScraper:
    """EVLBet scraper using direct HTTP API calls."""

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        if live:
            # The EVLBet live feed (`/matches/live`) carries live scores and
            # match state but NO odds (its Offers arrays are always empty), so
            # live markets cannot be extracted from it. Skip EVLBet in live mode.
            logger.info("[EVLBet] Live feed exposes no odds — skipping live mode")
            return []

        all_matches: list[Match] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, verify=VERIFY_SSL) as client:
            for offset in range(0, 2000, 100):
                url = f"{API_URL}?SportIds=388&Limit=100&Offset={offset}"
                try:
                    r = await fetch_with_retry(client, url)
                    if not r or r.status_code != 200:
                        break
                    data = r.json()
                    # API sometimes returns dict with Response key, sometimes bare list (2026-08-20)
                    if isinstance(data, list):
                        events = data
                    elif isinstance(data, dict):
                        events = data.get("Response", [])
                    else:
                        events = []
                    if not events:
                        break

                    for ev in events:
                        mid = str(ev.get("Id", ""))
                        if not mid or mid in seen:
                            continue
                        seen.add(mid)

                        match = self._parse_event(ev)
                        if match:
                            all_matches.append(match)

                    if len(events) < 100:
                        break

                except Exception as e:
                    logger.error(f"[EVLBet] Error fetching offset {offset}: {e}")
                    break

        logger.info(f"[EVLBet] Total: {len(all_matches)} matches parsed")
        return all_matches

    def _parse_event(self, ev: dict) -> Match | None:
        home = str(ev.get("TeamHome") or ev.get("OriginalTeamHome") or "").strip()
        away = str(ev.get("TeamAway") or ev.get("OriginalTeamAway") or "").strip()

        if not home or not away:
            desc = str(ev.get("Description") or "")
            if " - " in desc:
                parts = desc.split(" - ", 1)
                home = home or parts[0].strip()
                away = away or parts[1].strip()

        if not home or not away:
            return None

        kickoff = _parse_dt(ev.get("MatchStartTime"))
        mid = str(ev.get("Id", ""))

        category = str(ev.get("CategoryName") or ev.get("CategoryOriginalName") or "").strip()
        league_name = str(ev.get("LeagueName") or ev.get("LeagueOriginalName") or "").strip()
        league = f"{category} - {league_name}".strip(" -") if (category and league_name) else (league_name or category or "Fudbal")

        # Parse 1X2 market from BasicOffer. Only the registered full-time
        # result ID is accepted; O/U, advance, and other offers are excluded.
        basic_offer = ev.get("BasicOffer") or {}
        if not isinstance(basic_offer, dict):
            return None
        if basic_offer.get("HasSbv") or basic_offer.get("Sbv") is not None:
            source_id = (
                basic_offer.get("BetTypeKey")
                or basic_offer.get("GameId")
                or "12005"
            )
            known = getattr(MARKET_REGISTRY, "has_source_id", None)
            if known is None or not known("evlbet", "prematch", source_id):
                record_unmapped("evlbet", source_id)
            return None
        source_id = (
            basic_offer.get("BetTypeKey")
            or basic_offer.get("GameId")
            or "12005"
        )
        spec = MARKET_REGISTRY.lookup_type(
            "evlbet", "prematch", source_id, MarketType.MATCH_RESULT
        )
        if spec is None:
            record_unmapped("evlbet", source_id)
            return None
        odds_list = basic_offer.get("Odds", [])
        mr_odds: list[OddsValue] = []

        for o in odds_list:
            if not isinstance(o, dict):
                continue
            lbl = str(o.get("Name") or o.get("Type") or "").strip()
            try:
                val = float(o.get("Odd", 0.0))
            except (ValueError, TypeError):
                continue

            if lbl in spec.labels and val >= 1.01:
                mr_odds.append(OddsValue(label=lbl, value=val))

        actual = {o.label for o in mr_odds}
        if len(actual) < spec.min_legs or not actual.issubset(spec.labels):
            return None

        markets = [Market(market_type=MarketType.MATCH_RESULT, odds=mr_odds)]

        return Match(
            bookmaker=BOOKMAKER_ID,
            home_team=home,
            away_team=away,
            league=league,
            kickoff=kickoff,
            markets=markets,
            url=f"{BASE_URL}/",
            match_code=mid,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        return await self.fetch_and_parse(live=live, scan_time=scan_time)
