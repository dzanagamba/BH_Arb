"""
EVLBet Scraper — evlbet.com (Direct HTTP API)

Uses EVLBet's SportsOfferApi endpoint directly via httpx — no browser needed.
Endpoint: GET https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat?SportIds=388&Limit=100&Offset={offset}
"""

import logging
from datetime import UTC, datetime

from engine.market_registry import has_source_id, record_unmapped, registered_spec
from engine.structural_drift import observe
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import fetch_pages
from scrapers.common import parse_dt
from scrapers.errors import ScrapeError
from scrapers.retry import fetch_with_retry
from scrapers.transport import transport_client

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "evlbet"
BASE_URL = "https://evlbet.com"
API_URL = "https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat"

# EVLBet's single registered full-time result ID, used when a BasicOffer omits
# both BetTypeKey and GameId.
_DEFAULT_BASIC_OFFER_ID = "12005"


def _evlbet_registered_spec(
    mode: str,
    source_id: int | str,
    market_type: MarketType,
    line: float | None = None,
):
    """Resolve an EVLBet ``BasicOffer`` ID through the registry.

    The single registry-resolution step of ``EvlbetScraper._parse_event``, at
    module scope so the EVLBet resolution path is directly testable.
    """
    return registered_spec(BOOKMAKER_ID, mode, source_id, market_type, line=line)

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

        async with transport_client(
            BOOKMAKER_ID, "prematch", headers=HEADERS
        ) as client:

            async def fetch_page(index: int) -> list | None:
                offset = index * 100
                url = f"{API_URL}?SportIds=388&Limit=100&Offset={offset}"
                try:
                    r = await fetch_with_retry(client, url)
                    data = r.json()
                    # SR4-4: alert on a raw-shape change; alert only.
                    observe(BOOKMAKER_ID, "flat-offer", data)
                    # API sometimes returns dict with Response key, sometimes bare list (2026-08-20)
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict):
                        return data.get("Response", [])
                    return []
                except ScrapeError:
                    raise
                except Exception as e:
                    logger.error(f"[EVLBet] Error fetching offset {offset}: {e}")
                    return None

            events = await fetch_pages(fetch_page, page_size=100, max_pages=20)

        for ev in events:
            mid = str(ev.get("Id", ""))
            if not mid or mid in seen:
                continue
            seen.add(mid)

            match = self._parse_event(ev)
            if match:
                all_matches.append(match)

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

        kickoff = parse_dt(ev.get("MatchStartTime"))
        mid = str(ev.get("Id", ""))

        category = str(ev.get("CategoryName") or ev.get("CategoryOriginalName") or "").strip()
        league_name = str(ev.get("LeagueName") or ev.get("LeagueOriginalName") or "").strip()
        league = f"{category} - {league_name}".strip(" -") if (category and league_name) else (league_name or category or "Fudbal")

        # Parse 1X2 market from BasicOffer. Only the registered full-time
        # result ID is accepted; O/U, advance, and other offers are excluded.
        basic_offer = ev.get("BasicOffer") or {}
        if not isinstance(basic_offer, dict):
            return None
        source_id = (
            basic_offer.get("BetTypeKey")
            or basic_offer.get("GameId")
            or _DEFAULT_BASIC_OFFER_ID
        )
        if basic_offer.get("HasSbv") or basic_offer.get("Sbv") is not None:
            if not has_source_id("evlbet", "prematch", source_id):
                record_unmapped("evlbet", source_id)
            return None
        spec = _evlbet_registered_spec("prematch", source_id, MarketType.MATCH_RESULT)
        if spec is None:
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

        markets = [
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=mr_odds,
                source_id=str(source_id),
            )
        ]

        return Match(
            bookmaker=BOOKMAKER_ID,
            home_team=home,
            away_team=away,
            league=league,
            kickoff=kickoff,
            markets=markets,
            url=f"{BASE_URL}/",
            match_code=mid,
            event_id=mid,
            deep_link_verified=False,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    async def scrape(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        # SR6-2: part of the shared adapter contract; accepted and unused.
        return await self.fetch_and_parse(live=live, scan_time=scan_time)
