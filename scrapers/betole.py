"""
Betole Scraper — betole.ba

Platform: ExeFeed / NSoft
Strategy: Intercept ALL JSON payloads after loading `https://www.betole.ba/ba/sport/S`.

ExeFeed uses a reference-based data architecture: events are NOT flat objects
with home/away keys. `betPages[]` arrays carry references (event IDs) that must
be resolved against `betMap{}` (event lookup) and `betPickGroupMap{}` /
`betPickMap{}` (odds lookup). `_resolve_exefeed_events` performs that resolution
and falls back to the generic recursive finder for flat payloads.
"""

import logging
from datetime import UTC, datetime

import httpx
from playwright.async_api import Page

from config.settings import BOOKMAKERS, VERIFY_SSL
from engine.market_registry import MARKET_REGISTRY, record_unmapped
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import BaseScraper, fetch_with_retry
from scrapers.common import parse_nsoft_bets
from scrapers.mozzartbet import (
    _extract_kickoff,
    _extract_league,
    _extract_teams,
    _find_events_in_payload,
    _parse_markets,
)

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "betole"
BOOKMAKER_CONFIG = BOOKMAKERS[BOOKMAKER_ID]
OFFER_URL = "https://www.betole.ba/ba/sport/S"
API_URL = "https://www.betole.ba/restapi/offer/ba/sport/S/desk"
API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}
PAGE_SIZE = 1500


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
        spec = MARKET_REGISTRY.lookup_type(
            "betole", mode, code, market_type, line=line
        )
        known = getattr(MARKET_REGISTRY, "has_source_id", None)
        if spec is None and (known is None or not known("betole", mode, code)):
            record_unmapped("betole", code)
        return spec

    def build_market(
        market_type: MarketType,
        code_to_label: dict[str, str],
        *,
        line: float | None = None,
    ) -> Market | None:
        spec = None
        odds: list[OddsValue] = []
        for code, label in code_to_label.items():
            candidate = registered_spec(code, market_type, line=line)
            if candidate is not None:
                spec = candidate
            value = read_odd(code)
            if value is not None and candidate is not None and label in candidate.labels:
                odds.append(OddsValue(label=label, value=value))
        if spec is None or len(odds) < spec.min_legs:
            return None
        if not {o.label for o in odds}.issubset(spec.labels):
            return None
        return Market(market_type=market_type, odds=odds)

    markets: list[Market] = []
    mappings = [
        (MarketType.MATCH_RESULT, {"1": "1", "2": "X", "3": "2"}, None),
        (MarketType.DOUBLE_CHANCE, {"7": "1X", "8": "12", "9": "X2"}, None),
        (MarketType.BTTS, {"272": "GG", "273": "NG"}, None),
        (MarketType.FIRST_HALF_1X2, {"4": "1", "5": "X", "6": "2"}, None),
        (MarketType.OVER_UNDER_1_5, {"242": "Over 1.5", "21": "Under 1.5"}, 1.5),
        (MarketType.OVER_UNDER_2_5, {"24": "Over 2.5", "22": "Under 2.5"}, 2.5),
        (MarketType.OVER_UNDER_3_5, {"25": "Over 3.5", "219": "Under 3.5"}, 3.5),
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
                markets.append(Market(market_type=market_type, odds=odds))
            continue
        market = build_market(market_type, code_to_label, line=line)
        if market is not None:
            markets.append(market)

    known_codes = {
        "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "21", "22", "24", "25", "219", "242", "272", "273",
    }
    for code in raw_odds:
        if str(code) not in known_codes:
            record_unmapped("betole", code)
    return markets


def _resolve_ref(ref: dict, bet_map: dict) -> dict | None:
    """Resolve a reference entry against the betMap lookup table."""
    rid = ref.get("id") or ref.get("eventId") or ref.get("eventID") or ref.get("matchId") or ref.get("matchID")
    if rid is None:
        return None
    target = bet_map.get(str(rid))
    if target is None and not isinstance(rid, str):
        target = bet_map.get(rid)
    if isinstance(target, dict) and target is not ref:
        # Merge reference-level overrides onto the resolved event
        merged = {**target, **{k: v for k, v in ref.items() if v is not None and k not in ("id", "eventId", "eventID", "matchId", "matchID")}}
        return merged
    return None


def _resolve_exefeed_events(data, _depth: int = 0, root_bet_map: dict | None = None) -> list[dict]:
    """
    Recursively resolve ExeFeed reference-based payloads into flat event dicts
    (with name/dateTime/bets) that the standard parsing helpers understand.
    """
    if _depth > 10:
        return []
    events: list[dict] = []

    if isinstance(data, list):
        for item in data:
            events.extend(_resolve_exefeed_events(item, _depth + 1, root_bet_map))
        return events

    if not isinstance(data, dict):
        return events

    # Flat event dicts (name + odds/bets) are usable directly
    name = data.get("name") or data.get("eventName") or data.get("matchName")
    if isinstance(name, str) and (" - " in name or " vs " in name.lower()):
        if data.get("bets") or data.get("odds") or data.get("betMap"):
            return [data]

    # Collect lookup tables from this container (and inherit from ancestors)
    bet_map = data.get("betMap") or data.get("eventsMap") or {}
    if not isinstance(bet_map, dict):
        bet_map = {}
    lookup: dict = {**(root_bet_map or {}), **bet_map}

    # Resolve reference lists against the lookup table
    for key in ("items", "events", "offerEvents", "matches", "list", "matchList", "betPages"):
        refs = data.get(key)
        if refs is None:
            continue
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, dict):
                    resolved = _resolve_ref(ref, lookup)
                    if resolved:
                        events.append(resolved)
                        continue
                events.extend(_resolve_exefeed_events(ref, _depth + 1, lookup))
        elif isinstance(refs, dict):
            events.extend(_resolve_exefeed_events(refs, _depth + 1, lookup))

    # Deep-scan remaining container keys not already handled above
    for key in ("data", "response", "content", "result"):
        val = data.get(key)
        if isinstance(val, list | dict):
            events.extend(_resolve_exefeed_events(val, _depth + 1, lookup))

    return events


class BetoleScraper(BaseScraper):
    """Scraper for betole.ba — ExeFeed platform."""

    @property
    def bookmaker_name(self) -> str:
        return str(BOOKMAKER_CONFIG["name"])

    @property
    def bookmaker_id(self) -> str:
        return BOOKMAKER_ID

    @property
    def url(self) -> str:
        # Navigate directly to sport/S (football)
        return "https://www.betole.ba/ba/sport/S"

    @property
    def extra_blocked_fragments(self) -> list[str]:
        return ["casino", "live-casino", "virtual", "slots", "poker", "jackpot"]

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        """Fetch Betole's direct prematch feed and parse its pick-code odds.

        The desk feed mixes prematch and in-play events (`live` flag per
        event); in live mode only the in-play ones are kept.
        `scan_time` is accepted for uniform window API compatibility (not used — desk feed is unwindowed).
        """
        matches: list[Match] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=30.0, verify=VERIFY_SSL) as client:
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
                if not response or response.status_code != 200:
                    logger.debug(
                        f"[Betole] HTTP {response.status_code if response else 'No response'} at offset {offset}"
                    )
                    break

                try:
                    data = response.json()
                    events = data.get("esMatches", []) if isinstance(data, dict) else []
                except (ValueError, TypeError):
                    break
                if not isinstance(events, list) or not events:
                    break

                new_events = 0
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    event_id = str(event.get("id") or event.get("matchCode") or "")
                    if not event_id or event_id in seen_ids:
                        continue
                    seen_ids.add(event_id)
                    new_events += 1

                    is_live_flag = bool(event.get("live"))
                    if is_live_flag != live:
                        continue
                    if event.get("blocked"):
                        continue
                    home = str(event.get("home") or "").strip()
                    away = str(event.get("away") or "").strip()
                    if not home or not away:
                        continue
                    name_l = f"{home} {away}".lower()
                    if live and "srl" in name_l:
                        continue  # Simulated reality — not a real match

                    markets = _parse_betole_markets(
                        event.get("odds", {}), mode="live" if live else "prematch"
                    )
                    if not markets:
                        continue
                    matches.append(Match(
                        bookmaker=BOOKMAKER_ID,
                        home_team=home,
                        away_team=away,
                        league=str(event.get("leagueName") or "Fudbal"),
                        kickoff=_extract_kickoff({"kickOffTime": event.get("kickOffTime")}),
                        markets=markets,
                        url=OFFER_URL,
                        match_code=str(event.get("matchCode") or event_id),
                        is_live=live,
                        fetched_at=datetime.now(UTC).replace(tzinfo=None),
                    ))

                if len(events) < PAGE_SIZE or new_events == 0:
                    break

        logger.info(f"[Betole] {len(matches)} {'live' if live else 'prematch'} matches parsed")
        return matches

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        return await self.fetch_and_parse(live=live, scan_time=scan_time)

    async def extract_matches(self, page: Page) -> list[Match]:
        matches: list[Match] = []
        seen_codes = set()

        logger.info(
            f"[{self.bookmaker_name}] Processing {len(self.captured_json_payloads)} captured payloads"
        )

        for payload_info in self.captured_json_payloads:
            data = payload_info.get("data")
            if data is None:
                continue

            # ExeFeed reference resolution first, flat-payload fallback second
            events = _resolve_exefeed_events(data)
            if not events:
                events = _find_events_in_payload(data)

            for event in events:
                try:
                    home, away = _extract_teams(event)
                    if not home or not away:
                        continue

                    code = f"{home}|{away}"
                    if code in seen_codes:
                        continue
                    seen_codes.add(code)

                    league = _extract_league(event)
                    kickoff = _extract_kickoff(event)

                    markets = _parse_markets(event)
                    raw_bets = event.get("bets")
                    if not markets and isinstance(raw_bets, list):
                        # NSoft-style bets array (ExeFeed under the hood is NSoft)
                        markets = parse_nsoft_bets(raw_bets)

                    if not markets:
                        continue

                    match_id = str(event.get("id", event.get("matchId", event.get("eventId", ""))))

                    matches.append(Match(
                        bookmaker=BOOKMAKER_ID,
                        home_team=home,
                        away_team=away,
                        league=league,
                        kickoff=kickoff,
                        markets=markets,
                        url=OFFER_URL,
                        match_code=match_id,
                    ))

                except Exception as e:
                    logger.debug(f"[{self.bookmaker_name}] Event parse error: {e}")
                    continue

        logger.info(f"[{self.bookmaker_name}] Extracted {len(matches)} matches")
        return matches
