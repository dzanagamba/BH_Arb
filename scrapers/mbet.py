"""
MBet Scraper — mbet.ba (Alea Platform)

Uses the events_cached API with offset pagination.
Direct HTTP calls via httpx — no browser needed.

Endpoint: GET https://api.mbet.ba/events_cached
Parameters: live, offer_plan, fields, lang, limit, offset, start, end, orderBy
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx

from config.settings import VERIFY_SSL
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import fetch_with_retry
from scrapers.common import ah_label, parse_dt

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "mbet"

# Sport id prefix -> sport name
SPORT_MAP: dict[str, str] = {
    "fb": "football",
    "bk": "basketball",
    "tn": "tennis",
    "ih": "hockey",
    "hb": "handball",
    "wp": "waterpolo",
    "bs": "baseball",
    "sn": "snooker",
    "da": "darts",
    "mma": "mma",
    "bx": "boxing",
    "am": "american_football",
    "es": "esports",
    "vo": "volleyball",
    "tt": "table_tennis",
}

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

BASE_API = "https://api.mbet.ba/events_cached"


def _get_active_value(entry) -> float | None:
    """Extract the float value from an odds entry, returning None if suspended/inactive."""
    if isinstance(entry, dict):
        if entry.get("market_status") != "ACTIVE" or entry.get("oddtype_status") != 1:
            return None  # suspended or closed
        val = entry.get("value")
    else:
        val = entry
    try:
        f = float(val) if val is not None else 0.0
        return f if f >= 1.01 else None
    except (ValueError, TypeError):
        return None


def _resolve_mbet_market(raw_sport_id: str, odds_dict: dict) -> dict[str, list[OddsValue]]:
    """
    MBet uses dynamic odds keys like:
    - o{sport}:fs:1 (full-time 1X2)
    - o{sport}:dc:1X (full-time double chance)
    - o{sport}:gg:GG (both to score)
    - o{sport}:tg:3+ (over 2.5)
    - o{sport}:ht:1 (half-time 1X2, discarded)

    Other 1/X/2-shaped keys are deliberately not aliases for full-time result:
    `fts` is first team to score, `sh` is second-half result, and `fi` is a
    baseball first-inning market.
    """
    s = raw_sport_id
    markets: dict[str, list[OddsValue]] = {}

    # 1X2 — fs is MBet/Alea's football full-time result (Konacan ishod).
    # Do not fall back to fts/ht/sh/fi: they are different markets with the
    # same 1/X/2-shaped key suffixes.
    odds_1x2 = []
    k1 = f"o{s}:fs:1"
    kX = f"o{s}:fs:X"
    k2 = f"o{s}:fs:2"
    if k1 in odds_dict:
        o1 = _get_active_value(odds_dict.get(k1))
        oX = _get_active_value(odds_dict.get(kX))
        o2 = _get_active_value(odds_dict.get(k2))
        if o1 and oX and o2:
            odds_1x2 = [
                OddsValue(label="1", value=o1),
                OddsValue(label="X", value=oX),
                OddsValue(label="2", value=o2),
            ]
    if odds_1x2:
        markets["1X2"] = odds_1x2

    # Double Chance
    dc_k = f"o{s}:dc:"
    dc_odds = []
    for label in ("1X", "X2", "12"):
        key = dc_k + label
        odd = _get_active_value(odds_dict.get(key))
        if odd:
            dc_odds.append(OddsValue(label=label, value=odd))
    if len(dc_odds) >= 2:
        markets["DC"] = dc_odds

    # Half Time 1X2 (first-half result)
    ht_odds = []
    for label in ("1", "X", "2"):
        key = f"o{s}:ht:{label}"
        odd = _get_active_value(odds_dict.get(key))
        if odd:
            ht_odds.append(OddsValue(label=label, value=odd))
    if len(ht_odds) >= 3:
        markets["first_half_1x2"] = ht_odds

    # Asian Handicap — 2-way lines keyed as o{s}:hc:H1|{line} / H2|{line}.
    # The favourite gets the negative line: the side with the lower odds.
    hc_by_line: dict[float, dict[str, float]] = {}
    hc_prefix = f"o{s}:hc:"
    for key, entry in odds_dict.items():
        if not isinstance(key, str) or not key.startswith(hc_prefix):
            continue
        side_line = key[len(hc_prefix):]
        side, _, line_str = side_line.partition("|")
        if side not in ("H1", "H2"):
            continue
        try:
            line = float(line_str)
        except (ValueError, TypeError):
            continue
        odd = _get_active_value(entry)
        if odd is None:
            continue
        hc_by_line.setdefault(line, {})[side] = odd
    for line, sides in hc_by_line.items():
        home_odd = sides.get("H1")
        away_odd = sides.get("H2")
        if not home_odd or not away_odd:
            continue
        home_line = -line if home_odd < away_odd else line
        markets["asian_handicap"] = [
            OddsValue(label=ah_label("1", home_line), value=home_odd),
            OddsValue(label=ah_label("2", -home_line), value=away_odd),
        ]

    # Both Teams to Score
    gg_val = _get_active_value(odds_dict.get(f"o{s}:gg:GG"))
    ng_val = _get_active_value(odds_dict.get(f"o{s}:gg:NG"))
    if gg_val and ng_val:
        markets["BTTS"] = [
            OddsValue(label="GG", value=gg_val),
            OddsValue(label="NG", value=ng_val),
        ]

    # Over/Under markets — special keys
    # O/U 2.5: tg:3+ (over), tg:0-2 (under)
    # O/U 1.5: tg:2+ (over), tg:0-1 (under)
    # O/U 3.5: tg:4+ (over), tg:0-3 (under)
    ou_mappings = [
        (MarketType.OVER_UNDER_2_5, f"o{s}:tg:3+", f"o{s}:tg:0-2"),
        (MarketType.OVER_UNDER_1_5, f"o{s}:tg:2+", f"o{s}:tg:0-1"),
        (MarketType.OVER_UNDER_3_5, f"o{s}:tg:4+", f"o{s}:tg:0-3"),
    ]
    for mt, over_key, under_key in ou_mappings:
        over_val = None
        under_val = None
        if over_key in odds_dict:
            entry = odds_dict[over_key]
            if isinstance(entry, dict):
                if entry.get("market_status") != "ACTIVE" or entry.get("oddtype_status") != 1:
                    pass  # suspended — skip
                else:
                    val = entry.get("value")
                    try:
                        over_val = float(val) if val else 0
                    except (ValueError, TypeError):
                        pass
            else:
                try:
                    over_val = float(entry) if entry else 0
                except (ValueError, TypeError):
                    pass
        if under_key in odds_dict:
            entry = odds_dict[under_key]
            if isinstance(entry, dict):
                if entry.get("market_status") != "ACTIVE" or entry.get("oddtype_status") != 1:
                    pass
                else:
                    val = entry.get("value")
                    try:
                        under_val = float(val) if val else 0
                    except (ValueError, TypeError):
                        pass
            else:
                try:
                    under_val = float(entry) if entry else 0
                except (ValueError, TypeError):
                    pass
        if over_val and under_val and over_val >= 1.01 and under_val >= 1.01:
            # Build correct threshold string: "over_under_2_5" -> "2.5"
            parts = mt.value.split("_")  # e.g. ["over", "under", "2", "5"]
            threshold = f"{parts[-2]}.{parts[-1]}"  # "2.5"
            markets[mt.value] = [
                OddsValue(label=f"Over {threshold}", value=over_val),
                OddsValue(label=f"Under {threshold}", value=under_val),
            ]

    return markets


def _resolve_mbet_live_market(odds_dict: dict) -> dict[str, list[OddsValue]]:
    """
    MBet live odds use the `lfb:` key prefix with live-specific markets:
    - lfb:ft:1/X/2   → live full-time result
    - lfb:dc:1X/12/X2 → live double chance
    - lfb:bttsny:Yes/No → live both teams to score
    - lfb:tg:over|X.5 / under|X.5 → live totals (line embedded in the key)
    Other lfb:* markets (tg1sth, team totals, period markets) are excluded.
    """
    markets: dict[str, list[OddsValue]] = {}

    k1, kX, k2 = "lfb:ft:1", "lfb:ft:X", "lfb:ft:2"
    if k1 in odds_dict:
        o1 = _get_active_value(odds_dict.get(k1))
        oX = _get_active_value(odds_dict.get(kX))
        o2 = _get_active_value(odds_dict.get(k2))
        if o1 and oX and o2:
            markets["1X2"] = [
                OddsValue(label="1", value=o1),
                OddsValue(label="X", value=oX),
                OddsValue(label="2", value=o2),
            ]

    dc_odds = []
    for label in ("1X", "X2", "12"):
        odd = _get_active_value(odds_dict.get(f"lfb:dc:{label}"))
        if odd:
            dc_odds.append(OddsValue(label=label, value=odd))
    if len(dc_odds) >= 2:
        markets["DC"] = dc_odds

    btts_yes = _get_active_value(odds_dict.get("lfb:bttsny:Yes"))
    btts_no = _get_active_value(odds_dict.get("lfb:bttsny:No"))
    if btts_yes and btts_no:
        markets["BTTS"] = [
            OddsValue(label="GG", value=btts_yes),
            OddsValue(label="NG", value=btts_no),
        ]

    ou_mappings = {
        "1.5": (MarketType.OVER_UNDER_1_5, "Over 1.5", "Under 1.5"),
        "2.5": (MarketType.OVER_UNDER_2_5, "Over 2.5", "Under 2.5"),
        "3.5": (MarketType.OVER_UNDER_3_5, "Over 3.5", "Under 3.5"),
    }
    for key, entry in odds_dict.items():
        if not isinstance(key, str) or not key.startswith("lfb:tg:"):
            continue
        suffix = key[len("lfb:tg:"):]
        if "|" not in suffix:
            continue
        direction, _, line = suffix.partition("|")
        mapping = ou_mappings.get(line)
        if mapping is None:
            continue
        market_type, over_label, under_label = mapping
        value = _get_active_value(entry)
        if value is None:
            continue
        target_label = over_label if direction == "over" else under_label if direction == "under" else None
        if target_label is None:
            continue
        markets.setdefault(market_type.value, [])
        existing = next((o for o in markets[market_type.value] if o.label == target_label), None)
        if existing is None:
            markets[market_type.value].append(OddsValue(label=target_label, value=value))
        elif value > existing.value:
            existing.value = value

    return markets


class MBetScraper:
    """Scraper for mbet.ba — Alea platform, 100-event paginated API."""

    def __init__(self):
        self.base_url = BASE_API
        self.headers = dict(API_HEADERS)

    async def fetch_and_parse(self, live: bool = False) -> list[Match]:
        now = datetime.now(UTC)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        future = now + timedelta(days=14)
        future_str = future.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        all_matches: list[Match] = []
        seen_codes: set[tuple] = set()

        async with httpx.AsyncClient(timeout=30.0, verify=VERIFY_SSL) as client:
            offset = 0
            while True:
                url = (
                    f"{self.base_url}?live={'true' if live else 'false'}&offer_plan=true&fields=all"
                    f"&lang=ba&limit=100&offset={offset}"
                    f"&start={now_str}&end={future_str}"
                    f"&orderBy=startTimeAsc"
                )
                try:
                    resp = await fetch_with_retry(client, url, headers=self.headers)
                    if not resp or resp.status_code != 200:
                        logger.error(f"[MBet] HTTP {resp.status_code if resp else 'No response'} at offset {offset}")
                        break

                    data = resp.json()
                    raw_events = data.get("events", [])
                    if not raw_events:
                        break

                    for e in raw_events:
                        try:
                            match = self._parse_event(e, seen_codes, live=live)
                            if match:
                                all_matches.append(match)
                        except Exception as ex:
                            logger.debug(f"[MBet] Parse error: {ex}")
                            continue

                    if len(raw_events) < 100:
                        break
                    offset += 100

                except Exception as e:
                    logger.error(f"[MBet] Error at offset {offset}: {e}")
                    break

        logger.info(f"[MBet] Total {'live' if live else 'prematch'}: {len(all_matches)} matches")
        return all_matches

    def _parse_event(self, e: dict, seen_codes: set, live: bool = False) -> Match | None:
        raw_sport_id = e.get("id_sport", "")
        sport_name = SPORT_MAP.get(raw_sport_id)
        if sport_name != "football":
            return None  # Football-only pipeline — skip all other sports

        if live and e.get("finished"):
            return None  # Finished live events carry stale/closed odds

        competitors = e.get("competitors", [])
        if len(competitors) < 2:
            return None

        home = str(competitors[0].get("name", "")).strip()
        away = str(competitors[1].get("name", "")).strip()
        if not home or not away:
            return None

        # Prefer the event ID for dedup — team-name pairs drop 2nd meetings of the same teams
        event_id = str(e.get("id", ""))
        code = event_id if event_id else (home, away, sport_name)
        if code in seen_codes:
            return None
        seen_codes.add(code)

        # Parse start time via the shared helper (naive UTC, offset-aware)
        kickoff = parse_dt(e.get("utc_scheduled"))

        # Parse odds
        raw_odds = e.get("odds", {})
        if not isinstance(raw_odds, dict):
            return None

        market_dicts = (
            _resolve_mbet_live_market(raw_odds)
            if live
            else _resolve_mbet_market(raw_sport_id, raw_odds)
        )

        markets: list[Market] = []
        for key, odds_list in market_dicts.items():
            if key == "1X2":
                markets.append(Market(market_type=MarketType.MATCH_RESULT, odds=odds_list))
            elif key == "DC":
                markets.append(Market(market_type=MarketType.DOUBLE_CHANCE, odds=odds_list))
            elif key == "BTTS":
                markets.append(Market(market_type=MarketType.BTTS, odds=odds_list))
            elif key == "first_half_1x2":
                markets.append(Market(market_type=MarketType.FIRST_HALF_1X2, odds=odds_list))
            elif key == "asian_handicap":
                markets.append(Market(market_type=MarketType.ASIAN_HANDICAP, odds=odds_list))
            elif key == "over_under_1_5":
                markets.append(Market(market_type=MarketType.OVER_UNDER_1_5, odds=odds_list))
            elif key == "over_under_2_5":
                markets.append(Market(market_type=MarketType.OVER_UNDER_2_5, odds=odds_list))
            elif key == "over_under_3_5":
                markets.append(Market(market_type=MarketType.OVER_UNDER_3_5, odds=odds_list))

        if not markets:
            return None

        # Extract real league/tournament name from nested fields
        tournament = e.get("tournament") or {}
        category = e.get("category") or {}
        league_name = str(
            tournament.get("name") or category.get("name") or sport_name.capitalize()
        )

        return Match(
            bookmaker=BOOKMAKER_ID,
            home_team=home,
            away_team=away,
            league=league_name,
            kickoff=kickoff,
            markets=markets,
            url="https://mbet.ba/",
            match_code=event_id,
            is_live=live,
        )

    async def scrape(self, live: bool = False) -> list[Match]:
        """Compatibility wrapper."""
        return await self.fetch_and_parse(live=live)
