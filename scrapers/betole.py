"""
Betole Scraper — betole.ba

Platform: ExeFeed / NSoft
Strategy: page through the direct `restapi/offer/ba/sport/S/desk` JSON feed with
httpx and map its numeric pick codes to markets.
"""

import asyncio
import logging
from datetime import UTC, datetime

from engine.market_registry import record_unmapped, registered_spec
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.common import parse_dt
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.retry import fetch_with_retry
from scrapers.transport import transport_client
from scrapers.wire_schemas import (
    validate_betole_desk,
    validate_betole_offers,
)

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "betole"
OFFER_URL = "https://www.betole.ba/ba/sport/S"
API_URL = "https://www.betole.ba/restapi/offer/ba/sport/S/desk"
# SR7-1: the full offer for a batch of event ids. The desk feed above carries
# only four complete supported families; this endpoint carries the whole offer
# (763 picks against 30 on the 2026-11-08 probe) at roughly 3 KB per event, so
# batching keeps the scan at ~21 extra requests for ~820 events instead of one
# request per event.
BULK_URL = "https://www.betole.ba/restapi/offer/ba/matches/by-ids"
BULK_BATCH = 40
# Batches in flight. The batches are independent; the per-book limiter still
# spaces every request at the configured ceiling, so this only hides latency.
BULK_CONCURRENCY = 8
API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}
PAGE_SIZE = 1500


def _betole_registered_spec(
    mode: str,
    code: int | str,
    market_type: MarketType,
    line: float | None = None,
):
    """Resolve a Betole pick code through the registry.

    The single registry-resolution step of :func:`_parse_betole_markets`, at
    module scope so the Betole resolution path is directly testable.
    """
    return registered_spec("betole", mode, code, market_type, line=line)


def _parse_betole_markets(raw_odds: dict, mode: str = "prematch") -> list[Market]:
    """Map registered Betole pick-code groups into supported markets."""
    if not isinstance(raw_odds, dict):
        return []

    def read_odd(code: str) -> float | None:
        try:
            value = float(raw_odds.get(code, 0.0))
        except (ValueError, TypeError):
            return None
        return value if value >= 1.01 else None

    def registered_spec(
        code: str, market_type: MarketType, line: float | None = None
    ):
        return _betole_registered_spec(mode, code, market_type, line=line)

    def build_market(
        market_type: MarketType,
        code_to_label: dict[str, str],
        *,
        line: float | None = None,
    ) -> Market | None:
        spec = None
        matched_code = ""
        odds: list[OddsValue] = []
        for code, label in code_to_label.items():
            candidate = registered_spec(code, market_type, line=line)
            if candidate is not None:
                spec = candidate
                matched_code = code
            value = read_odd(code)
            if value is not None and candidate is not None and label in candidate.labels:
                odds.append(OddsValue(label=label, value=value))
        if spec is None or len(odds) < spec.min_legs:
            return None
        if not {o.label for o in odds}.issubset(spec.labels):
            return None
        return Market(market_type=market_type, odds=odds, source_id=matched_code)

    markets: list[Market] = []
    mappings = [
        (MarketType.MATCH_RESULT, {"1": "1", "2": "X", "3": "2"}, None),
        (MarketType.DOUBLE_CHANCE, {"7": "1X", "8": "12", "9": "X2"}, None),
        (MarketType.BTTS, {"272": "GG", "273": "NG"}, None),
        (MarketType.FIRST_HALF_1X2, {"4": "1", "5": "X", "6": "2"}, None),
        (MarketType.OVER_UNDER_1_5, {"242": "Over 1.5", "21": "Under 1.5"}, 1.5),
        (MarketType.OVER_UNDER_2_5, {"24": "Over 2.5", "22": "Under 2.5"}, 2.5),
        (MarketType.OVER_UNDER_3_5, {"25": "Over 3.5", "219": "Under 3.5"}, 3.5),
        (MarketType.OVER_UNDER_4_5, {"27": "Over 4.5", "453": "Under 4.5"}, 4.5),
        (MarketType.OVER_UNDER_5_5, {"223": "Over 5.5", "266": "Under 5.5"}, 5.5),
    ]
    for market_type, code_to_label, line in mappings:
        if market_type == MarketType.FIRST_HALF_1X2 and mode == "prematch":
            # Experimental market; retain the existing verified code mapping.
            odds = [
                OddsValue(label=label, value=value)
                for code, label in code_to_label.items()
                if (value := read_odd(code)) is not None
            ]
            if len(odds) == 3:
                markets.append(
                    Market(market_type=market_type, odds=odds, source_id=str(next(iter(code_to_label))))
                )
            continue
        market = build_market(market_type, code_to_label, line=line)
        if market is not None:
            markets.append(market)

    known_codes = {
        "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "21", "22", "24", "25", "219", "242", "272", "273",
        "27", "453", "223", "266",
    }
    for code in raw_odds:
        if str(code) not in known_codes:
            record_unmapped("betole", code)
    return markets


def _event_to_match(event: dict, live: bool) -> Match | None:
    """Build one Match from a Betole desk event, including its Betradar id."""
    event_id = str(event.get("id") or event.get("matchCode") or "")
    if not event_id:
        return None
    if bool(event.get("live")) != live:
        return None
    if event.get("blocked"):
        return None
    home = str(event.get("home") or "").strip()
    away = str(event.get("away") or "").strip()
    if not home or not away:
        return None
    if live and "srl" in f"{home} {away}".lower():
        return None  # Simulated reality — not a real match
    markets = _parse_betole_markets(event.get("odds", {}), mode="live" if live else "prematch")
    if not markets:
        return None
    return Match(
        bookmaker=BOOKMAKER_ID,
        home_team=home,
        away_team=away,
        league=str(event.get("leagueName") or "Fudbal"),
        kickoff=parse_dt(event.get("kickOffTime")),
        markets=markets,
        url=OFFER_URL,
        match_code=str(event.get("matchCode") or event_id),
        event_id=event_id,
        betradar_id=str(event.get("brMatchId") or ""),
        deep_link_verified=False,
        is_live=live,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _desk_candidate(event: dict, live: bool) -> bool:
    """Whether this desk event can become a match in the requested mode.

    Used before the full-offer fetch so a live or blocked event does not cost a
    batch slot (the desk feed mixes prematch and in-play events).
    """
    if not isinstance(event, dict):
        return False
    if bool(event.get("live")) != live or event.get("blocked"):
        return False
    return bool(
        str(event.get("home") or "").strip()
        and str(event.get("away") or "").strip()
    )


async def _fetch_full_offers(client, events: list[dict], live: bool) -> dict[str, dict]:
    """Fetch complete offers for these events, in batches.

    The desk listing carries four complete supported families per event; this
    endpoint carries the whole offer (double chance, the 1.5/3.5/4.5/5.5
    totals and the first-half 1X2 already served by the desk). A failed batch is
    logged and its events keep the desk odds, the same way a failed page in
    `fetch_pages` stops the walk with what it has.
    """
    offers: dict[str, dict] = {}
    ids = [str(event.get("id")) for event in events if event.get("id") is not None]
    if not ids:
        return offers
    mode = "live" if live else "prematch"
    chunks = [ids[start:start + BULK_BATCH] for start in range(0, len(ids), BULK_BATCH)]
    semaphore = asyncio.Semaphore(BULK_CONCURRENCY)

    async def one(chunk: list[str]) -> list | None:
        async with semaphore:
            try:
                response = await fetch_with_retry(
                    client,
                    BULK_URL,
                    headers=API_HEADERS,
                    params={
                        "annex": "0",
                        "desktopVersion": "2.47.6.10",
                        "locale": "ba",
                        "matchIdsToken": ",".join(chunk),
                    },
                )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise ScrapeError(
                        ScrapeKind.SCHEMA_DRIFT,
                        f"betole full-offer batch is not JSON: {exc}",
                    ) from exc
                # SR4-3d: validate the raw rows before they can reach the parser.
                return validate_betole_offers(payload, book=BOOKMAKER_ID)
            except ScrapeError:
                raise
            except Exception as exc:  # noqa: BLE001 - a batch failure keeps the desk odds
                logger.warning(
                    "[Betole] full-offer batch for %d events failed, keeping "
                    "desk odds: %s",
                    len(chunk),
                    exc,
                )
                return None

    results = await asyncio.gather(
        *(one(chunk) for chunk in chunks), return_exceptions=True
    )
    for result in results:
        if isinstance(result, ScrapeError):
            raise result
        if not isinstance(result, list):
            continue
        for row in result:
            offers[str(row.id)] = row.odds
    logger.debug("[Betole] %s: %d full offers", mode, len(offers))
    return offers


class BetoleScraper:
    """Scraper for betole.ba — ExeFeed platform."""

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        """Fetch Betole's desk listing, then each event's full offer.

        The desk feed mixes prematch and in-play events (`live` flag per
        event); in live mode only the in-play ones are kept. The desk listing
        itself carries only four complete supported families, so each event's
        full offer is fetched in batches before parsing (SR7-1).
        `scan_time` is accepted for uniform window API compatibility (not used — desk feed is unwindowed).
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()
        events: list[dict] = []

        async with transport_client(
            BOOKMAKER_ID, "live" if live else "prematch"
        ) as client:
            for offset in range(0, 30000, PAGE_SIZE):
                response = await fetch_with_retry(
                    client,
                    API_URL,
                    headers=API_HEADERS,
                    params={
                        "desktopVersion": "2.47.6.7",
                        "locale": "ba",
                        "from": str(offset),
                    },
                )

                try:
                    data = response.json()
                except ValueError as exc:
                    raise ScrapeError(
                        ScrapeKind.SCHEMA_DRIFT,
                        f"betole desk page at offset {offset} is not JSON: {exc}",
                    ) from exc
                # SR4-3d: validate the envelope and every event's odds map
                # before the parser reads them.
                page_events = validate_betole_desk(
                    data, book=BOOKMAKER_ID
                ).esMatches
                if not page_events:
                    break

                new_events = 0
                for event in page_events:
                    if not isinstance(event, dict):
                        continue
                    event_id = str(event.get("id") or event.get("matchCode") or "")
                    if not event_id or event_id in seen_ids:
                        continue
                    seen_ids.add(event_id)
                    new_events += 1
                    if _desk_candidate(event, live):
                        events.append(event)

                if len(page_events) < PAGE_SIZE or new_events == 0:
                    break

            offers = await _fetch_full_offers(client, events, live)

        for event in events:
            event_id = str(event.get("id") or event.get("matchCode") or "")
            odds = offers.get(event_id) or event.get("odds") or {}
            match = _event_to_match({**event, "odds": odds}, live)
            if match is not None:
                matches.append(match)

        logger.info(f"[Betole] {len(matches)} {'live' if live else 'prematch'} matches parsed")
        return matches

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        return await self.fetch_and_parse(live=live, scan_time=scan_time)

