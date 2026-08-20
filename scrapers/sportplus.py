"""
SportPlus Scraper — sportplus.ba

Direct REST API via httpx.

Endpoint: GET https://www.sportplus.ba/api/v1/prematch/offer
Returns: { "matches": [...] } with competitor names and market arrays.
"""

import json
import logging
from datetime import UTC, datetime

import httpx

from config.settings import VERIFY_SSL
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import fetch_with_retry
from scrapers.common import normalize_outcome

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "sportplus"

SPORT_MAP: dict[str, str] = {
    "NOGOMET": "football",
    "KOŠARKA": "basketball",
    "TENIS": "tennis",
    "HOKEJ": "hockey",
    "RUKOMET": "handball",
    "VATERPOLO": "waterpolo",
    "BASEBALL": "baseball",
    "PIKADO": "darts",
    "SNOOKER": "snooker",
    "ULTIMATE FIGHT": "mma",
    "BOKS": "boxing",
    "FUTSAL": "futsal",
}

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
}

BASE_API = "https://www.sportplus.ba/api/v1/prematch/offer"
LIVE_API = "https://www.sportplus.ba/api/v1/live/offer"


class SportPlusScraper:
    """Scraper for sportplus.ba — direct REST API."""

    def __init__(self):
        self.url = BASE_API
        self.headers = dict(API_HEADERS)

    async def fetch_and_parse(self, live: bool = False) -> list[Match]:
        if live:
            return await self._fetch_live()
        all_matches: list[Match] = []
        seen_codes: set[tuple] = set()

        async with httpx.AsyncClient(timeout=120.0, verify=VERIFY_SSL) as client:
            try:
                resp = await fetch_with_retry(client, self.url, headers=self.headers)
                if not resp or resp.status_code != 200:
                    logger.error(f"[SportPlus] HTTP {resp.status_code if resp else 'No response'}")
                    return []

                # Response may be double-serialized
                data = resp.json()
                if isinstance(data, str):
                    data = json.loads(data)

                raw_matches = data.get("matches", [])
                logger.info(f"[SportPlus] {len(raw_matches)} raw matches")

                for m in raw_matches:
                    try:
                        match = self._parse_match(m, seen_codes)
                        if match:
                            all_matches.append(match)
                    except Exception as e:
                        logger.debug(f"[SportPlus] Parse error: {e}")
                        continue

            except Exception as e:
                logger.error(f"[SportPlus] Fetch error: {e}")

        logger.info(f"[SportPlus] Total: {len(all_matches)} matches")
        return all_matches

    async def _fetch_live(self) -> list[Match]:
        """Fetch and parse the in-play offer (`/api/v1/live/offer`)."""
        all_matches: list[Match] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=60.0, verify=VERIFY_SSL) as client:
            try:
                resp = await fetch_with_retry(client, LIVE_API, headers=self.headers)
                if not resp or resp.status_code != 200:
                    logger.error(f"[SportPlus] Live HTTP {resp.status_code if resp else 'No response'}")
                    return []

                data = resp.json()
                if isinstance(data, str):
                    data = json.loads(data)

                # Live payload: { "date": ..., "sports": [{ id, name, matches: [...] }] }
                sports = data.get("sports", []) if isinstance(data, dict) else []
                for sport in sports:
                    if not isinstance(sport, dict):
                        continue
                    if str(sport.get("name", "")).upper() != "NOGOMET":
                        continue
                    for m in sport.get("matches", []):
                        try:
                            match = self._parse_live_match(m, seen_ids)
                            if match:
                                all_matches.append(match)
                        except Exception as e:
                            logger.debug(f"[SportPlus] Live parse error: {e}")
                            continue
            except Exception as e:
                logger.error(f"[SportPlus] Live fetch error: {e}")

        logger.info(f"[SportPlus] Live total: {len(all_matches)} matches")
        return all_matches

    def _parse_live_match(self, m: dict, seen_ids: set) -> Match | None:
        """Parse a live match object (nested under sports[].matches)."""
        if not isinstance(m, dict):
            return None
        if m.get("betting") is False:
            return None  # No betting available on this live match

        match_id = str(m.get("id", ""))
        if not match_id or match_id in seen_ids:
            return None
        seen_ids.add(match_id)

        home = str(m.get("home", "") or "").strip().rstrip("/").strip()
        away = str(m.get("away", "") or "").strip().rstrip("/").strip()
        # Live feeds prefix names with short labels like "ML/" or "SR/"
        import re as _re
        home = _re.sub(r"^[A-Z]{1,3}/", "", home).strip()
        away = _re.sub(r"^[A-Z]{1,3}/", "", away).strip()
        if not home or not away or home.lower() == away.lower():
            return None

        markets = self._parse_live_markets(m.get("markets", []))
        if not markets:
            return None

        return Match(
            bookmaker=BOOKMAKER_ID,
            home_team=home,
            away_team=away,
            league="Fudbal",
            kickoff=None,
            markets=markets,
            url="https://www.sportplus.ba/live",
            match_code=match_id,
            is_live=True,
        )

    def _parse_live_markets(self, raw_markets: list) -> list[Market]:
        """
        Parse live SportPlus markets by NAME (the live ID space is shared
        across sports, so IDs alone are ambiguous):
        - "Pobjednik"                    → 1X2
        - "Dvostruka Prilika (1X - 12 - X2)" → double chance
        - "Oba daju gol"                 → BTTS (aliases 1(D)/2(N))
        - "Zbroj golova X.5"             → O/U X.5 (aliases 1(M)/2(V))
        """
        result: list[Market] = []
        for market in raw_markets:
            if not isinstance(market, dict):
                continue
            name = str(market.get("name", "")).strip()
            odds_raw = market.get("odds", [])
            if not odds_raw:
                continue

            def read_odds() -> list[tuple[str, float]]:
                out = []
                for o in odds_raw:  # noqa: B023
                    if not isinstance(o, dict):
                        continue
                    alias = o.get("alias")
                    try:
                        value = float(o.get("value", 0.0))
                    except (ValueError, TypeError):
                        continue
                    if value >= 1.01:
                        out.append((str(alias), value))
                return out

            def append_market(market_type: MarketType, odds: list[OddsValue]) -> None:
                if any(m.market_type == market_type for m in result):
                    return
                result.append(Market(market_type=market_type, odds=odds))

            if name == "Pobjednik":
                by_label: dict[str, float] = {}
                for alias, value in read_odds():
                    if alias in ("1", "X", "2"):
                        by_label[alias] = max(by_label.get(alias, 0.0), value)
                if set(by_label) == {"1", "X", "2"}:
                    append_market(MarketType.MATCH_RESULT, [
                        OddsValue(label=label, value=by_label[label])
                        for label in ("1", "X", "2")
                    ])
            elif "Dvostruka Prilika" in name:
                by_label = {}
                for alias, value in read_odds():
                    if alias in ("1X", "12", "X2"):
                        by_label[alias] = max(by_label.get(alias, 0.0), value)
                if len(by_label) >= 2:
                    append_market(MarketType.DOUBLE_CHANCE, [
                        OddsValue(label=label, value=by_label[label])
                        for label in ("1X", "12", "X2") if label in by_label
                    ])
            elif name == "Oba daju gol":
                gg = ng = None
                for alias, value in read_odds():
                    if alias in ("1(D)", "1D", "Da", "GG"):
                        gg = max(gg or 0.0, value)
                    elif alias in ("2(N)", "2N", "Ne", "NG"):
                        ng = max(ng or 0.0, value)
                if gg and ng:
                    append_market(MarketType.BTTS, [
                        OddsValue(label="GG", value=gg),
                        OddsValue(label="NG", value=ng),
                    ])
            elif name.startswith("Zbroj golova "):
                import re as _re
                match_line = _re.search(r"(\d+[.,]\d+)", name)
                if not match_line:
                    continue
                line = match_line.group(1).replace(",", ".")
                market_type = {
                    "1.5": MarketType.OVER_UNDER_1_5,
                    "2.5": MarketType.OVER_UNDER_2_5,
                    "3.5": MarketType.OVER_UNDER_3_5,
                }.get(line)
                if market_type is None:
                    continue
                over = under = None
                for alias, value in read_odds():
                    if "V" in alias:
                        over = max(over or 0.0, value)
                    elif "M" in alias:
                        under = max(under or 0.0, value)
                if over and under:
                    append_market(market_type, [
                        OddsValue(label=f"Over {line}", value=over),
                        OddsValue(label=f"Under {line}", value=under),
                    ])
        return result

    def _parse_match(self, m: dict, seen_codes: set) -> Match | None:
        raw_sport = str(m.get("sportName", "")).upper()
        sport_name = SPORT_MAP.get(raw_sport)
        if sport_name != "football":
            return None  # Football-only pipeline — skip all other sports

        competitors_str = m.get("competitors", "")
        if " - " not in competitors_str:
            return None

        parts = competitors_str.split(" - ", 1)
        home = parts[0].strip()
        away = parts[1].strip()
        if not home or not away:
            return None

        # Prefer the match ID for dedup — team-name pairs drop 2nd meetings of the same teams
        match_id = str(m.get("id", ""))
        code = match_id if match_id else (home, away, sport_name)
        if code in seen_codes:
            return None
        seen_codes.add(code)

        # Parse match date — normalize to naive UTC to match all other scrapers
        match_date_str = m.get("matchDate")
        kickoff = None
        if match_date_str:
            try:
                dt = datetime.fromisoformat(match_date_str)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(UTC).replace(tzinfo=None)
                kickoff = dt
            except (ValueError, TypeError):
                pass

        # Extract league/competition name + country
        league_raw = m.get("leagueName")
        country_raw = m.get("countryName")
        country = ""
        if league_raw and str(league_raw).strip() not in ("-", ""):
            league_name = str(league_raw).strip()
            country = str(country_raw).strip() if country_raw else ""
        elif country_raw and str(country_raw).strip() not in ("-", ""):
            league_name = str(country_raw).strip()
        else:
            league_name = sport_name.capitalize()

        markets = self._parse_markets(m.get("markets", []))
        if not markets:
            return None

        return Match(
            bookmaker=BOOKMAKER_ID,
            home_team=home,
            away_team=away,
            league=league_name,
            country=country,
            kickoff=kickoff,
            markets=markets,
            url="https://www.sportplus.ba/prematch/betting",
            match_code=match_id,
        )

    def _parse_markets(self, raw_markets: list) -> list[Market]:
        """Parse SportPlus market objects into Market list."""
        # SportPlus exposes standard O/U 2.5 (id=768) and the same threshold
        # through the goal-range blocks (ids=800/802). Keep one canonical
        # market per type while retaining the best valid quote if both blocks
        # are present.
        markets_by_type: dict[MarketType, dict[str, OddsValue]] = {}

        def add_market(market_type: MarketType, odds: list[OddsValue]) -> None:
            by_label = markets_by_type.setdefault(market_type, {})
            for odd in odds:
                current = by_label.get(odd.label)
                if current is None or odd.value > current.value:
                    by_label[odd.label] = odd

        goal_range_odds: dict[str, OddsValue] = {}
        range_labels = {
            "2+": "Over 1.5",
            "01": "Under 1.5",
            "3+": "Over 2.5",
            "02": "Under 2.5",
            "4+": "Over 3.5",
            "03": "Under 3.5",
        }

        # Qualification/advance markets (e.g. id=1285 "NAČIN PROLAZA") are
        # 1X2-shaped but NOT match results — always exclude them.
        ADVANCE_KEYWORDS = ("DALJE", "PROLAZ", "KVALIFIKACIJE", "ADVANCE", "QUALIF")

        for market in raw_markets:
            if not isinstance(market, dict):
                continue
            market_id = market.get("id")
            market_name = str(market.get("name", "")).upper().strip()
            if any(w in market_name for w in ADVANCE_KEYWORDS):
                continue

            odds_raw = market.get("odds", [])
            if not odds_raw:
                continue

            # 1X2 & Double Chance (same market block)
            if market_name in SPORT_MAP or market_id == 1:
                match_result_odds = []
                dc_odds = []
                for o in odds_raw:
                    alias = o.get("alias")
                    val = o.get("value")
                    try:
                        odd_val = float(val) if val else 0
                    except (ValueError, TypeError):
                        continue
                    if alias in ("1", "X", "2") and odd_val >= 1.01:
                        match_result_odds.append(
                            OddsValue(label=normalize_outcome(alias, MarketType.MATCH_RESULT), value=odd_val)
                        )
                    elif alias in ("1X", "12", "X2") and odd_val >= 1.01:
                        dc_odds.append(
                            OddsValue(label=normalize_outcome(alias, MarketType.DOUBLE_CHANCE), value=odd_val)
                        )
                # 1X2 is only valid when ALL THREE outcomes are present
                if {o.label for o in match_result_odds} == {"1", "X", "2"}:
                    add_market(MarketType.MATCH_RESULT, match_result_odds)
                # Double Chance requires at least 2 distinct legs
                if len({o.label for o in dc_odds}) >= 2:
                    add_market(MarketType.DOUBLE_CHANCE, dc_odds)

            # Over/Under 2.5
            elif market_name == "ZBROJ GOLOVA 2,5" or market_id == 768:
                odds_list = self._parse_ou_odds(odds_raw, "2.5")
                if odds_list:
                    add_market(MarketType.OVER_UNDER_2_5, odds_list)

            # First Half 1X2 (id=4 "PRVO POLUVRIJEME")
            elif market_name == "PRVO POLUVRIJEME" or market_id == 4:
                fh_odds = []
                for o in odds_raw:
                    alias = o.get("alias")
                    val = o.get("value")
                    try:
                        odd_val = float(val) if val else 0
                    except (ValueError, TypeError):
                        continue
                    if alias in ("1", "X", "2") and odd_val >= 1.01:
                        fh_odds.append(
                            OddsValue(label=normalize_outcome(alias, MarketType.FIRST_HALF_1X2), value=odd_val)
                        )
                if {o.label for o in fh_odds} == {"1", "X", "2"}:
                    add_market(MarketType.FIRST_HALF_1X2, fh_odds)

            # Asian Handicap (id=25 "AZIJSKI HENDIKEP") — level-ball (0-line):
            # both sides refund at 1.00 on a draw ("neriješeno kvota 1,00").
            elif market_name == "AZIJSKI HENDIKEP" or market_id == 25:
                by_alias = {o.get("alias"): o.get("value") for o in odds_raw if o.get("alias") in ("1", "2")}
                try:
                    home_val = float(by_alias.get("1") or 0)
                    away_val = float(by_alias.get("2") or 0)
                except (ValueError, TypeError):
                    home_val = away_val = 0.0
                if home_val >= 1.01 and away_val >= 1.01:
                    add_market(MarketType.ASIAN_HANDICAP, [
                        OddsValue(label="1 0", value=home_val),
                        OddsValue(label="2 0", value=away_val),
                    ])

            # Both Teams to Score
            elif market_name == "OBA TIMA DAJU GOL" or market_id == 6:
                btts_odds = self._parse_btts_odds(odds_raw)
                if btts_odds:
                    add_market(MarketType.BTTS, btts_odds)

            # Goal Range — maps to O/U 1.5, O/U 2.5, O/U 3.5
            elif market_name == "RASPON GOLOVA" or market_id in (800, 802):
                for o in odds_raw:
                    alias = o.get("alias")
                    val = o.get("value")
                    try:
                        odd_val = float(val) if val else 0
                    except (ValueError, TypeError):
                        continue
                    label = range_labels.get(alias)
                    if label and odd_val >= 1.01:
                        current = goal_range_odds.get(label)
                        if current is None or odd_val > current.value:
                            goal_range_odds[label] = OddsValue(label=label, value=odd_val)

        for market_type, over_label, under_label in (
            (MarketType.OVER_UNDER_1_5, "Over 1.5", "Under 1.5"),
            (MarketType.OVER_UNDER_2_5, "Over 2.5", "Under 2.5"),
            (MarketType.OVER_UNDER_3_5, "Over 3.5", "Under 3.5"),
        ):
            over = goal_range_odds.get(over_label)
            under = goal_range_odds.get(under_label)
            if over and under:
                add_market(market_type, [over, under])

        return [
            Market(market_type=market_type, odds=list(odds_by_label.values()))
            for market_type, odds_by_label in markets_by_type.items()
        ]

    def _parse_ou_odds(self, odds_raw: list, threshold: str) -> list[OddsValue]:
        """Parse Over/Under odds from a market block."""
        over = None
        under = None
        for o in odds_raw:
            alias = str(o.get("alias", "")).lower()
            val = o.get("value")
            try:
                odd_val = float(val) if val else 0
            except (ValueError, TypeError):
                continue
            if alias in ("više", "vise", "over") and odd_val >= 1.01:
                over = OddsValue(label=f"Over {threshold}", value=odd_val)
            elif alias in ("manje", "under") and odd_val >= 1.01:
                under = OddsValue(label=f"Under {threshold}", value=odd_val)
        if over and under:
            return [over, under]
        return []

    def _parse_btts_odds(self, odds_raw: list) -> list[OddsValue]:
        """Parse Both Teams to Score odds."""
        gg = None
        ng = None
        for o in odds_raw:
            alias = str(o.get("alias", "")).lower()
            val = o.get("value")
            try:
                odd_val = float(val) if val else 0
            except (ValueError, TypeError):
                continue
            if alias in ("da", "gg") and odd_val >= 1.01:
                gg = OddsValue(label="GG", value=odd_val)
            elif alias in ("ne", "ng") and odd_val >= 1.01:
                ng = OddsValue(label="NG", value=odd_val)
        if gg and ng:
            return [gg, ng]
        return []

    async def scrape(self, live: bool = False) -> list[Match]:
        """Compatibility wrapper."""
        return await self.fetch_and_parse(live=live)
