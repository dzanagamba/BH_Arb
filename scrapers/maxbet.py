"""
MaxBet Scraper — maxbet.ba (Singular sportsbook, Direct HTTP API)

The www.maxbet.ba site embeds its sportsbook from sportsbook.maxbet.ba, an
Angular app backed by a public REST API. One request per mode returns every
football match with the odd types asked for in ``ot`` — no browser needed.

Endpoint: GET https://sportsbook.maxbet.ba/sportsbook/rest/v2/matches
Parameters: sportId=1, ot=<odd type id> (repeatable), ln=cnr,
            status=Live (live only; prematch omits it)

Odd types (measured 2026-10-27 against /rest/v2/odd_types and the matches feed):
  1  = "Konačan ishod" (1X2, regular time)   outcomeId 1001/1002/1003
  10 = "Dupla šansa"                          outcomeId 10001/10002/10003
  27 = "GG - NG"                              outcomeId 27001/27002
  17 = "Ukupno golova" (match total, line in specifiers.total)
                                              outcomeId 17001 over / 17002 under
Only these four are requested, so no other market can reach the parser.

An outcome with ``status`` other than 0 is suspended (a 1.02 "over 0.5" in a
game already scored in carries status 1), and is dropped like any inactive odd.
"""

import logging
from datetime import UTC, datetime
from urllib.parse import urlencode

from engine import sports
from engine.market_registry import MARKET_REGISTRY, MarketSpec, record_unmapped
from models.schemas import Market, Match, OddsValue
from scrapers.common import betradar_id, build_event_url, parse_dt, qualify_league
from scrapers.retry import fetch_with_retry
from scrapers.transport import transport_client

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "maxbet"

BASE_URL = "https://sportsbook.maxbet.ba"
MATCHES_API = f"{BASE_URL}/sportsbook/rest/v2/matches"
FOOTBALL_SPORT_ID = 1
ODD_TYPE_IDS = (1, 10, 27, 17)

SPORT_IDS = {
    sports.FOOTBALL: 1,
    sports.BASKETBALL: 2,
    sports.TENNIS: 5,
    sports.ICE_HOCKEY: 4,
}
SPORT_ODD_TYPE_IDS: dict[str, tuple[int, ...]] = {
    # 175 = winner incl. overtime, 16 = handicap, 224 = total points.
    sports.BASKETBALL: (175, 16, 224),
    # 175 = match winner, 176 = game handicap, 178 = total games.
    sports.TENNIS: (175, 176, 178),
}

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/",
}

# outcomeId -> canonical label. The id is language independent; the label text
# ("Više {total}") is only cross-checked against it.
OUTCOME_LABELS: dict[str, str] = {
    "1001": "1", "1002": "X", "1003": "2",
    "10001": "1X", "10002": "12", "10003": "X2",
    "27001": "GG", "27002": "NG",
    "17001": "Over", "17002": "Under",
}
_LABEL_TEXT: dict[str, tuple[str, ...]] = {
    "Over": ("više", "vise", "over", "+"),
    "Under": ("manje", "under", "-"),
}

# Event status values seen on the feed: 1 = not started, 3 = in play.
PREMATCH_STATUS = 1
LIVE_STATUS = 3


def _spec_for(mode: str, odd_type_id: int, line: float | None) -> MarketSpec | None:
    """The registry entry for an odd type (and, for totals, its exact line)."""
    specs = MARKET_REGISTRY.specs_for(BOOKMAKER_ID, mode, odd_type_id)
    if not specs:
        if not MARKET_REGISTRY.has_source_id(BOOKMAKER_ID, mode, odd_type_id):
            record_unmapped(BOOKMAKER_ID, odd_type_id)
        return None
    for spec in specs:
        if spec.line is None and line is None:
            return spec
        if spec.line is not None and line is not None and abs(spec.line - line) < 1e-9:
            return spec
    # A total at a line we do not price (0.5, 4.5, ...): known id, not a market.
    return None


def _label_for(outcome: dict) -> str | None:
    label = OUTCOME_LABELS.get(str(outcome.get("outcomeId") or ""))
    if label in _LABEL_TEXT:
        text = str(outcome.get("outcome") or "").strip().lower()
        if not text.startswith(_LABEL_TEXT[label]):
            return None
    elif label is not None:
        text = str(outcome.get("outcome") or "").strip().upper()
        if text and text != label:
            return None
    return label


def _outcome_source_updated_at(outcome: dict) -> datetime | None:
    """The book's own per-outcome update time, when the payload carries one.

    MaxBet's raw odds carry ``updateDate``/``providerTimestamp``. The capture
    trims them, so fixtures leave this empty; a live payload that has them must
    not lose them (N0-2). Unparseable or absent values stay ``None``.
    """
    return parse_dt(outcome.get("updateDate") or outcome.get("providerTimestamp"))


def parse_maxbet_odds(odds: list, mode: str = "prematch") -> list[Market]:
    """Parse a match's ``odds[]`` array into registry-validated markets."""
    markets: list[Market] = []
    for market in odds or []:
        if not isinstance(market, dict):
            continue
        odd_type_id = market.get("id")
        if odd_type_id is None:
            continue
        line: float | None = None
        total = (market.get("specifiers") or {}).get("total")
        if total is not None:
            try:
                line = float(str(total))
            except (TypeError, ValueError):
                continue
        spec = _spec_for(mode, odd_type_id, line)
        if spec is None:
            continue

        values: dict[str, float] = {}
        source_times: dict[str, datetime | None] = {}
        for outcome in market.get("outcomes") or []:
            if not isinstance(outcome, dict):
                continue
            if outcome.get("status") != 0 or outcome.get("marketAvailableForBetting") is False:
                continue
            label = _label_for(outcome)
            if label is None:
                continue
            if label in ("Over", "Under"):
                label = f"{label} {spec.line:g}"
            try:
                value = float(outcome.get("oddValue") or 0.0)
            except (TypeError, ValueError):
                continue
            if value < 1.01 or label not in spec.labels or label in values:
                continue
            values[label] = value
            source_times[label] = _outcome_source_updated_at(outcome)

        if len(values) >= spec.min_legs and set(values) <= spec.labels:
            markets.append(Market(
                market_type=spec.market_type,
                odds=[
                    OddsValue(
                        label=label,
                        value=value,
                        source_updated_at=source_times.get(label),
                    )
                    for label, value in values.items()
                ],
                source_id=str(odd_type_id),
            ))
    return markets


_TOTAL_UNDER = ("manje", "under", "up-", "-", "1(m)")
_TOTAL_OVER = ("više", "vise", "over", "up+", "+", "2(v)")


def _outcome_side(outcome: dict) -> str:
    text = str(outcome.get("outcome") or "").strip().casefold()
    for token in _TOTAL_UNDER:
        if text.startswith(token):
            return "under"
    for token in _TOTAL_OVER:
        if text.startswith(token):
            return "over"
    return ""


def parse_sport_odds(odds: list, sport: str, mode: str = "prematch") -> list[Market]:
    """Parse a non-football MaxBet ``odds[]`` array by the sport's odd types."""
    spec = sports.spec_for(sport)
    ids = SPORT_ODD_TYPE_IDS.get(sport)
    if spec is None or ids is None:
        return []
    markets: list[Market] = []
    for market in odds or []:
        if not isinstance(market, dict):
            continue
        odd_type_id = market.get("id")
        if odd_type_id not in ids:
            continue
        outcomes = [
            item
            for item in (market.get("outcomes") or [])
            if isinstance(item, dict)
            and item.get("status") == 0
            and item.get("marketAvailableForBetting") is not False
        ]
        values: dict[str, float] = {}
        source_times: dict[str, datetime | None] = {}
        for outcome in outcomes:
            try:
                value = float(outcome.get("oddValue") or 0.0)
            except (TypeError, ValueError):
                continue
            if value < 1.01:
                continue
            label = str(outcome.get("outcome") or "").strip()
            label_for_value = ""
            if odd_type_id == 175:
                if label not in ("1", "2"):
                    continue
                label_for_value = label
                values[label_for_value] = value
            elif odd_type_id in (16, 176):
                hcp = (market.get("specifiers") or {}).get("hcp")
                try:
                    line = float(str(hcp))
                except (TypeError, ValueError):
                    continue
                if label.startswith(("H1", "HG1")):
                    label_for_value = f"1 {line:g}"
                elif label.startswith(("H2", "HG2")):
                    label_for_value = f"2 {-line:g}"
                if label_for_value:
                    values[label_for_value] = value
            else:
                side = _outcome_side(outcome)
                total = (market.get("specifiers") or {}).get("total")
                try:
                    line = float(str(total))
                except (TypeError, ValueError):
                    continue
                if side:
                    label_for_value = f"{'Over' if side == 'over' else 'Under'} {abs(line):g}"
                    values[label_for_value] = value
            if label_for_value:
                source_times[label_for_value] = _outcome_source_updated_at(outcome)

        if odd_type_id == 175:
            if set(values) != set(spec.moneyline_labels):
                continue
            markets.append(
                Market(
                    market_type=spec.moneyline,
                    odds=[
                        OddsValue(
                            label=label,
                            value=values[label],
                            source_updated_at=source_times.get(label),
                        )
                        for label in spec.moneyline_labels
                    ],
                    source_id=str(odd_type_id),
                    settlement=spec.moneyline_settlement,
                )
            )
        elif odd_type_id in (16, 176):
            if len(values) != 2:
                continue
            markets.append(
                Market(
                    market_type=spec.handicap,
                    odds=[
                        OddsValue(
                            label=label,
                            value=value,
                            source_updated_at=source_times.get(label),
                        )
                        for label, value in values.items()
                    ],
                    source_id=str(odd_type_id),
                    settlement=spec.handicap_settlement,
                )
            )
        else:
            if len(values) != 2:
                continue
            markets.append(
                Market(
                    market_type=spec.total,
                    odds=[
                        OddsValue(
                            label=label,
                            value=value,
                            source_updated_at=source_times.get(label),
                        )
                        for label, value in values.items()
                    ],
                    source_id=str(odd_type_id),
                    settlement=spec.total_settlement,
                )
            )
    return markets


def _teams(event: dict) -> tuple[str, str]:
    """Home/away as the event name spells them, else the competitor list.

    The event name ("Boston River v Torque") uses the full club names the
    other books use; the competitor records are often abbreviated
    ("Montevideo C.").
    """
    name = str(event.get("name") or "")
    if name.count(" v ") == 1:
        home, away = (part.strip() for part in name.split(" v "))
        if home and away:
            return home, away
    competitors = event.get("competitors") or []
    if len(competitors) == 2:
        return (
            str(competitors[0].get("name") or "").strip(),
            str(competitors[1].get("name") or "").strip(),
        )
    return "", ""


class MaxBetScraper:
    """MaxBet scraper using the sportsbook's public REST API."""

    def __init__(self) -> None:
        self.headers = dict(API_HEADERS)

    async def fetch_and_parse(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        wanted = (
            [sports.FOOTBALL]
            if sports_wanted is None
            else [
                sports.normalize_sport(value) or value
                for value in sports_wanted
                if (sports.normalize_sport(value) or value) in SPORT_IDS
            ]
        )
        if not wanted:
            return []

        all_matches: list[Match] = []
        async with transport_client(
            BOOKMAKER_ID, "live" if live else "prematch"
        ) as client:
            for sport in wanted:
                params: list[tuple[str, str | int]] = [("sportId", SPORT_IDS[sport])]
                if sport == sports.FOOTBALL:
                    params += [("ot", odd_type) for odd_type in ODD_TYPE_IDS]
                else:
                    params += [("ot", odd_type) for odd_type in SPORT_ODD_TYPE_IDS[sport]]
                if live:
                    params.append(("status", "Live"))
                params.append(("ln", "cnr"))

                # A list of pairs keeps the repeated `ot` keys.
                response = await fetch_with_retry(
                    client, f"{MATCHES_API}?{urlencode(params)}", headers=self.headers
                )
                events = response.json()
                if not isinstance(events, list):
                    if sport == sports.FOOTBALL:
                        raise RuntimeError("MaxBet matches feed did not return a list")
                    continue
                all_matches.extend(self.parse_events(events, live=live, sport=sport))

        logger.info(f"[MaxBet] {'live' if live else 'prematch'}: {len(all_matches)} matches")
        return all_matches

    def parse_events(self, events: list, live: bool = False, sport: str = "football") -> list[Match]:
        mode = "live" if live else "prematch"
        wanted_status = LIVE_STATUS if live else PREMATCH_STATUS
        requested_sport_id = SPORT_IDS.get(sport, FOOTBALL_SPORT_ID)
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        seen: set[str] = set()
        matches: list[Match] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("eventType") != "Match" or event.get("antepost"):
                continue
            if event.get("sportId") != requested_sport_id or event.get("status") != wanted_status:
                continue
            event_id = str(event.get("id") or "")
            if not event_id or event_id in seen:
                continue
            home, away = _teams(event)
            if not home or not away:
                continue
            markets = (
                parse_maxbet_odds(event.get("odds") or [], mode=mode)
                if sport == sports.FOOTBALL
                else parse_sport_odds(event.get("odds") or [], sport, mode=mode)
            )
            if not markets:
                continue
            seen.add(event_id)
            external = event.get("externalIds") or {}
            matches.append(Match(
                bookmaker=BOOKMAKER_ID,
                sport=sport,
                home_team=home,
                away_team=away,
                # League names carry the country in English ("Germany DFB
                # Pokal"); `country` stays empty on purpose, because the
                # matcher compares it as text and the other books name
                # countries in Bosnian.
                league=(
                    qualify_league(
                        str(event.get("leagueName") or ""), str(event.get("categoryName") or "")
                    )
                    if sport == sports.FOOTBALL
                    else str(event.get("leagueName") or "")
                ),
                kickoff=parse_dt(event.get("startDate")),
                markets=markets,
                url=build_event_url(BOOKMAKER_ID, event_id, BASE_URL, live=live),
                match_code=str(external.get("shortCode") or ""),
                event_id=event_id,
                betradar_id=betradar_id(external.get("betradarUnified")),
                deep_link_verified=False,
                is_live=live,
                fetched_at=fetched_at,
            ))
        return matches

    async def scrape(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        return await self.fetch_and_parse(
            live=live, scan_time=scan_time, sports_wanted=sports_wanted
        )
