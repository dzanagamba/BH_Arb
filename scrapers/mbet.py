"""
MBet Scraper — mbet.ba (Alea Platform)

Uses the events_cached API with offset pagination.
Direct HTTP calls via httpx — no browser needed.

Endpoint: GET https://api.mbet.ba/events_cached
Parameters: live, offer_plan, fields, lang, limit, offset, start, end, orderBy
"""

import logging
from datetime import UTC, datetime, timedelta

from engine import sports
from engine.market_registry import lookup_type, record_unmapped, registered_spec
from engine.structural_drift import observe
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import fetch_pages
from scrapers.common import ah_label, parse_dt
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.retry import fetch_with_retry
from scrapers.transport import transport_client
from scrapers.wire_schemas import validate_mbet_response

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "mbet"

# Sport id prefix -> sport name
SPORT_MAP: dict[str, str] = {
    "fb": "football",
    "bk": "basketball",
    "bb": "basketball",
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
    "af": "american_football",
    "es": "esports",
    "vo": "volleyball",
    "vb": "volleyball",
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


def _registered_spec(
    mode: str,
    source_id: str,
    market_type: MarketType,
    line: float | None = None,
):
    return registered_spec("mbet", mode, source_id, market_type, line=line)


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
    prefix = f"o{s}:"
    for key in odds_dict:
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        market_prefix = key[len(prefix):].split(":", 1)[0]
        if market_prefix not in {"fs", "dc", "gg", "tg", "ht", "hc"}:
            record_unmapped("mbet", f"ofb:{market_prefix}")

    # 1X2 — fs is MBet/Alea's football full-time result (Konacan ishod).
    # Do not fall back to fts/ht/sh/fi: they are different markets with the
    # same 1/X/2-shaped key suffixes.
    source_id = "ofb:fs"
    spec = _registered_spec("prematch", source_id, MarketType.MATCH_RESULT)
    odds_1x2 = []
    k1 = f"o{s}:fs:1"
    kX = f"o{s}:fs:X"
    k2 = f"o{s}:fs:2"
    if spec is not None and k1 in odds_dict:
        o1 = _get_active_value(odds_dict.get(k1))
        oX = _get_active_value(odds_dict.get(kX))
        o2 = _get_active_value(odds_dict.get(k2))
        by_label = {"1": o1, "X": oX, "2": o2}
        odds_1x2 = [
            OddsValue(label=label, value=value)
            for label, value in by_label.items()
            if value is not None and label in spec.labels
        ]
        if len(odds_1x2) < spec.min_legs or not {o.label for o in odds_1x2}.issubset(spec.labels):
            odds_1x2 = []
    if odds_1x2:
        markets["1X2"] = odds_1x2

    # Double Chance
    source_id = "ofb:dc"
    spec = _registered_spec("prematch", source_id, MarketType.DOUBLE_CHANCE)
    dc_k = f"o{s}:dc:"
    dc_odds = []
    for label in ("1X", "X2", "12"):
        key = dc_k + label
        odd = _get_active_value(odds_dict.get(key))
        if odd and spec is not None and label in spec.labels:
            dc_odds.append(OddsValue(label=label, value=odd))
    if spec is not None and len(dc_odds) >= spec.min_legs:
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
    # P1-4: preserve all handicap lines (previous code overwrote, keeping only last line)
    if hc_by_line:
        ah_odds: list[OddsValue] = []
        for line, sides in hc_by_line.items():
            home_odd = sides.get("H1")
            away_odd = sides.get("H2")
            if not home_odd or not away_odd:
                continue
            home_line = -line if home_odd < away_odd else line
            ah_odds.extend([
                OddsValue(label=ah_label("1", home_line), value=home_odd),
                OddsValue(label=ah_label("2", -home_line), value=away_odd),
            ])
        if ah_odds:
            markets["asian_handicap"] = ah_odds

    # Both Teams to Score
    source_id = "ofb:gg"
    spec = _registered_spec("prematch", source_id, MarketType.BTTS)
    gg_val = _get_active_value(odds_dict.get(f"o{s}:gg:GG"))
    ng_val = _get_active_value(odds_dict.get(f"o{s}:gg:NG"))
    btts_odds = [
        OddsValue(label=label, value=value)
        for label, value in (("GG", gg_val), ("NG", ng_val))
        if value is not None
    ]
    actual = {odd.label for odd in btts_odds}
    if (
        spec is not None
        and gg_val
        and ng_val
        and len(actual) >= spec.min_legs
        and actual.issubset(spec.labels)
    ):
        markets["BTTS"] = btts_odds

    # Over/Under markets — special keys
    # O/U 2.5: tg:3+ (over), tg:0-2 (under)
    # O/U 1.5: tg:2+ (over), tg:0-1 (under)
    # O/U 3.5: tg:4+ (over), tg:0-3 (under)
    ou_mappings = [
        (MarketType.OVER_UNDER_2_5, f"o{s}:tg:3+", f"o{s}:tg:0-2"),
        (MarketType.OVER_UNDER_1_5, f"o{s}:tg:2+", f"o{s}:tg:0-1"),
        (MarketType.OVER_UNDER_3_5, f"o{s}:tg:4+", f"o{s}:tg:0-3"),
        (MarketType.OVER_UNDER_4_5, f"o{s}:tg:5+", f"o{s}:tg:0-4"),
        (MarketType.OVER_UNDER_5_5, f"o{s}:tg:6+", f"o{s}:tg:0-5"),
    ]
    for mt, over_key, under_key in ou_mappings:
        threshold = {
            MarketType.OVER_UNDER_1_5: "1.5",
            MarketType.OVER_UNDER_2_5: "2.5",
            MarketType.OVER_UNDER_3_5: "3.5",
            MarketType.OVER_UNDER_4_5: "4.5",
            MarketType.OVER_UNDER_5_5: "5.5",
        }[mt]
        spec = _registered_spec("prematch", "ofb:tg", mt, line=float(threshold))
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
        ou_odds = [
            OddsValue(label=label, value=value)
            for label, value in (
                (f"Over {threshold}", over_val),
                (f"Under {threshold}", under_val),
            )
            if value is not None
        ]
        actual = {odd.label for odd in ou_odds}
        if (
            spec is not None
            and over_val
            and under_val
            and over_val >= 1.01
            and under_val >= 1.01
            and len(actual) >= spec.min_legs
            and actual.issubset(spec.labels)
        ):
            markets[mt.value] = ou_odds

    return markets


def _resolve_mbet_live_market(odds_dict: dict) -> dict[str, list[OddsValue]]:
    """
    Resolve MBet's live ``lfb:`` market prefixes through the live registry.
    Other live market families (period/team totals) are intentionally ignored.
    """
    markets: dict[str, list[OddsValue]] = {}
    for key in odds_dict:
        if not isinstance(key, str) or not key.startswith("lfb:"):
            continue
        market_prefix = key[len("lfb:"):].split(":", 1)[0]
        if market_prefix not in {"ft", "dc", "bttsny", "tg"}:
            record_unmapped("mbet", f"lfb:{market_prefix}")

    spec = _registered_spec("live", "lfb:ft", MarketType.MATCH_RESULT)
    k1, kX, k2 = "lfb:ft:1", "lfb:ft:X", "lfb:ft:2"
    if spec is not None and k1 in odds_dict:
        values = {
            "1": _get_active_value(odds_dict.get(k1)),
            "X": _get_active_value(odds_dict.get(kX)),
            "2": _get_active_value(odds_dict.get(k2)),
        }
        result = [
            OddsValue(label=label, value=value)
            for label, value in values.items()
            if value is not None and label in spec.labels
        ]
        if len(result) >= spec.min_legs and {o.label for o in result}.issubset(spec.labels):
            markets["1X2"] = result

    spec = _registered_spec("live", "lfb:dc", MarketType.DOUBLE_CHANCE)
    dc_odds = []
    for label in ("1X", "X2", "12"):
        odd = _get_active_value(odds_dict.get(f"lfb:dc:{label}"))
        if odd and spec is not None and label in spec.labels:
            dc_odds.append(OddsValue(label=label, value=odd))
    if spec is not None and len(dc_odds) >= spec.min_legs:
        markets["DC"] = dc_odds

    spec = _registered_spec("live", "lfb:bttsny", MarketType.BTTS)
    btts_yes = _get_active_value(odds_dict.get("lfb:bttsny:Yes"))
    btts_no = _get_active_value(odds_dict.get("lfb:bttsny:No"))
    btts_odds = [
        OddsValue(label=label, value=value)
        for label, value in (("GG", btts_yes), ("NG", btts_no))
        if value is not None
    ]
    actual = {odd.label for odd in btts_odds}
    if (
        spec is not None
        and btts_yes
        and btts_no
        and len(actual) >= spec.min_legs
        and actual.issubset(spec.labels)
    ):
        markets["BTTS"] = btts_odds

    ou_mappings = {
        "1.5": (MarketType.OVER_UNDER_1_5, "Over 1.5", "Under 1.5"),
        "2.5": (MarketType.OVER_UNDER_2_5, "Over 2.5", "Under 2.5"),
        "3.5": (MarketType.OVER_UNDER_3_5, "Over 3.5", "Under 3.5"),
        "4.5": (MarketType.OVER_UNDER_4_5, "Over 4.5", "Under 4.5"),
        "5.5": (MarketType.OVER_UNDER_5_5, "Over 5.5", "Under 5.5"),
    }
    for key, entry in odds_dict.items():
        if not isinstance(key, str) or not key.startswith("lfb:tg:"):
            continue
        suffix = key[len("lfb:tg:"):]
        if "|" not in suffix:
            continue
        direction, _, line_text = suffix.partition("|")
        mapping = ou_mappings.get(line_text)
        if mapping is None:
            continue
        market_type, over_label, under_label = mapping
        spec = _registered_spec("live", "lfb:tg", market_type, line=float(line_text))
        if spec is None:
            continue
        value = _get_active_value(entry)
        if value is None:
            continue
        target_label = over_label if direction == "over" else under_label if direction == "under" else None
        if target_label is None or target_label not in spec.labels:
            continue
        markets.setdefault(market_type.value, [])
        existing = next((o for o in markets[market_type.value] if o.label == target_label), None)
        if existing is None:
            markets[market_type.value].append(OddsValue(label=target_label, value=value))
        elif value > existing.value:
            existing.value = value

    for market_key, odds in list(markets.items()):
        source_id, market_enum = {
            "1X2": ("lfb:ft", MarketType.MATCH_RESULT),
            "DC": ("lfb:dc", MarketType.DOUBLE_CHANCE),
            "BTTS": ("lfb:bttsny", MarketType.BTTS),
            "over_under_1_5": ("lfb:tg", MarketType.OVER_UNDER_1_5),
            "over_under_2_5": ("lfb:tg", MarketType.OVER_UNDER_2_5),
            "over_under_3_5": ("lfb:tg", MarketType.OVER_UNDER_3_5),
            "over_under_4_5": ("lfb:tg", MarketType.OVER_UNDER_4_5),
            "over_under_5_5": ("lfb:tg", MarketType.OVER_UNDER_5_5),
        }.get(market_key, (None, None))
        line = {
            "over_under_1_5": 1.5,
            "over_under_2_5": 2.5,
            "over_under_3_5": 3.5,
            "over_under_4_5": 4.5,
            "over_under_5_5": 5.5,
        }.get(market_key)
        spec = (
            lookup_type(
                "mbet", "live", source_id, market_enum, line=line
            )
            if source_id is not None and market_enum is not None
            else None
        )
        if spec is None or len(odds) < spec.min_legs:
            del markets[market_key]

    return markets


def _active(odds_dict: dict, key: str) -> float | None:
    return _get_active_value(odds_dict.get(key))


def _sport_market_keys(sport: str, live: bool) -> dict[str, str]:
    """Key prefixes for one sport. Live keys carry a leading ``l``."""
    prefix = f"l{sport}" if live else f"o{sport}"
    if sport == "bb":
        return {
            "moneyline": f"{prefix}:fsot" if not live else f"{prefix}:ft",
            "handicap": f"{prefix}:hc" if not live else f"{prefix}:h",
            "total": f"{prefix}:p" if not live else f"{prefix}:tg",
        }
    if sport == "tn":
        return {
            "moneyline": f"{prefix}:fs",
            "handicap": f"{prefix}:hg",
            "total": f"{prefix}:g" if not live else f"{prefix}:tg",
        }
    if sport == "ih":
        return {
            "moneyline": f"{prefix}:fs" if not live else f"{prefix}:ft",
            "handicap": f"{prefix}:h",
            "total": f"{prefix}:g" if not live else f"{prefix}:tg",
        }
    return {}


def _resolve_mbet_sport_market(
    sport: str, odds_dict: dict, live: bool = False
) -> dict[str, list[tuple[MarketType, list[OddsValue], str]]]:
    """Resolve MBet's non-football keys into canonical sport markets.

    Returns ``{family: [(market_type, odds, settlement)]}``. Only complete
    two-way sets are kept; a 1/X/2 key that carries a draw is not the two-way
    basketball moneyline.
    """
    canonical = {"bb": sports.BASKETBALL, "tn": sports.TENNIS, "ih": sports.ICE_HOCKEY}.get(sport)
    spec = sports.spec_for(canonical or "")
    if spec is None:
        return {}
    keys = _sport_market_keys(sport, live)
    if not keys:
        return {}
    out: dict[str, list[tuple[MarketType, list[OddsValue], str]]] = {}

    # Moneyline.
    one = _active(odds_dict, f"{keys['moneyline']}:1")
    two = _active(odds_dict, f"{keys['moneyline']}:2")
    if one and two:
        labels = spec.moneyline_labels
        if labels == ("1", "2"):
            # A 1/X/2 key is a regular-time three-way market, not the two-way
            # including-overtime winner. It cannot be relabelled as one.
            if _active(odds_dict, f"{keys['moneyline']}:X") is not None:
                pass
            else:
                out["moneyline"] = [
                    (
                        spec.moneyline,
                        [OddsValue(label="1", value=one), OddsValue(label="2", value=two)],
                        spec.moneyline_settlement,
                    )
                ]
        elif labels == ("1", "X", "2"):
            draw = _active(odds_dict, f"{keys['moneyline']}:X")
            if draw:
                out["moneyline"] = [
                    (
                        spec.moneyline,
                        [
                            OddsValue(label="1", value=one),
                            OddsValue(label="X", value=draw),
                            OddsValue(label="2", value=two),
                        ],
                        spec.moneyline_settlement,
                    )
                ]

    # Handicap: side keys H1|line / H2|line (prematch) or 1|line / 2|line.
    hc_prefix = f"{keys['handicap']}:"
    lines: dict[float, dict[str, float]] = {}
    for key, entry in odds_dict.items():
        if not isinstance(key, str) or not key.startswith(hc_prefix):
            continue
        side, _, line_text = key[len(hc_prefix):].partition("|")
        try:
            line = float(line_text)
        except ValueError:
            continue
        value = _get_active_value(entry)
        if value is None:
            continue
        # MBet's key line is that side's own line: `1|-2.5` is home -2.5 and
        # `2|2.5` is away +2.5. Canonicalise to the home line.
        if side in ("H1", "1"):
            lines.setdefault(line, {})["1"] = value
        elif side in ("H2", "2"):
            lines.setdefault(-line, {})["2"] = value
    handicap_odds: list[OddsValue] = []
    for home_line, sides in sorted(lines.items()):
        if "1" in sides and "2" in sides:
            from scrapers.common import ah_label

            handicap_odds.extend([
                OddsValue(label=ah_label("1", home_line), value=sides["1"]),
                OddsValue(label=ah_label("2", -home_line), value=sides["2"]),
            ])
    if handicap_odds:
        out["handicap"] = [(spec.handicap, handicap_odds, spec.handicap_settlement)]

    # Total: OVER/UNDER tokens per line.
    total_prefix = f"{keys['total']}:"
    totals: dict[float, dict[str, float]] = {}
    for key, entry in odds_dict.items():
        if not isinstance(key, str) or not key.startswith(total_prefix):
            continue
        suffix = key[len(total_prefix):]
        direction, _, line_text = suffix.partition("|")
        try:
            line = abs(float(line_text))
        except ValueError:
            continue
        value = _get_active_value(entry)
        if value is None:
            continue
        token = direction.casefold()
        if token in ("over", "(+)", "viš", "vis"):
            totals.setdefault(line, {})["over"] = value
        elif token in ("under", "(-)", "manj"):
            totals.setdefault(line, {})["under"] = value
    total_odds: list[OddsValue] = []
    for line, sides in sorted(totals.items()):
        if "over" in sides and "under" in sides:
            total_odds.extend([
                OddsValue(label=f"Over {line:g}", value=sides["over"]),
                OddsValue(label=f"Under {line:g}", value=sides["under"]),
            ])
    if total_odds:
        out["total"] = [(spec.total, total_odds, spec.total_settlement)]
    return out


class MBetScraper:
    """Scraper for mbet.ba — Alea platform, 100-event paginated API."""

    def __init__(self):
        self.base_url = BASE_API
        self.headers = dict(API_HEADERS)

    async def fetch_and_parse(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        # Single wall-clock from run_scan ensures uniform 14-day window across scrapers
        now_aware = (scan_time.replace(tzinfo=UTC) if scan_time and scan_time.tzinfo is None else scan_time) if scan_time else datetime.now(UTC)
        wanted = (
            {sports.FOOTBALL}
            if sports_wanted is None
            else {sports.normalize_sport(value) or value for value in sports_wanted}
        )
        now_str = now_aware.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        future = now_aware + timedelta(days=14)
        future_str = future.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        all_matches: list[Match] = []
        seen_codes: set[tuple] = set()

        async with transport_client(
            BOOKMAKER_ID, "live" if live else "prematch"
        ) as client:

            async def fetch_page(index: int) -> list | None:
                offset = index * 100
                url = (
                    f"{self.base_url}?live={'true' if live else 'false'}&offer_plan=true&fields=all"
                    f"&lang=ba&limit=100&offset={offset}"
                    f"&start={now_str}&end={future_str}"
                    f"&orderBy=startTimeAsc"
                )
                try:
                    resp = await fetch_with_retry(client, url, headers=self.headers)
                except ScrapeError:
                    raise
                except Exception as e:
                    logger.error(f"[MBet] Error at offset {offset}: {e}")
                    return None
                try:
                    payload = resp.json()
                except ValueError as exc:
                    raise ScrapeError(
                        ScrapeKind.SCHEMA_DRIFT,
                        f"mbet page at offset {offset} is not JSON: {exc}",
                    ) from exc
                # SR4-3e: validate the envelope and every event's odds map
                # before the parser reads them.
                observe(BOOKMAKER_ID, "events", payload)
                return validate_mbet_response(payload, book=BOOKMAKER_ID).events

            raw_events = await fetch_pages(fetch_page, page_size=100, max_pages=200)

        for e in raw_events:
            try:
                match = self._parse_event(e, seen_codes, live=live, wanted=wanted)
                if match:
                    all_matches.append(match)
            except Exception as ex:
                logger.debug(f"[MBet] Parse error: {ex}")
                continue

        logger.info(f"[MBet] Total {'live' if live else 'prematch'}: {len(all_matches)} matches")
        return all_matches

    def _parse_event(
        self,
        e: dict,
        seen_codes: set,
        live: bool = False,
        wanted: set[str] | None = None,
    ) -> Match | None:
        wanted = wanted or {sports.FOOTBALL}
        raw_sport_id = e.get("id_sport", "")
        sport_name = sports.normalize_sport(SPORT_MAP.get(raw_sport_id) or raw_sport_id)
        if sport_name not in wanted:
            return None

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

        markets: list[Market] = []
        if sport_name == sports.FOOTBALL:
            market_dicts = (
                _resolve_mbet_live_market(raw_odds)
                if live
                else _resolve_mbet_market(raw_sport_id, raw_odds)
            )
            source_ids = (
                {
                    "1X2": "lfb:ft",
                    "DC": "lfb:dc",
                    "BTTS": "lfb:bttsny",
                    "over_under_1_5": "lfb:tg",
                    "over_under_2_5": "lfb:tg",
                    "over_under_3_5": "lfb:tg",
                }
                if live
                else {
                    "1X2": "ofb:fs",
                    "DC": "ofb:dc",
                    "BTTS": "ofb:gg",
                    "first_half_1x2": "ofb:ht",
                    "asian_handicap": "ofb:hc",
                    "over_under_1_5": "ofb:tg",
                    "over_under_2_5": "ofb:tg",
                    "over_under_3_5": "ofb:tg",
                    "over_under_4_5": "ofb:tg",
                    "over_under_5_5": "ofb:tg",
                }
            )
            for key, odds_list in market_dicts.items():
                source_id = source_ids.get(key, "")
                if key == "1X2":
                    markets.append(Market(market_type=MarketType.MATCH_RESULT, odds=odds_list, source_id=source_id))
                elif key == "DC":
                    markets.append(Market(market_type=MarketType.DOUBLE_CHANCE, odds=odds_list, source_id=source_id))
                elif key == "BTTS":
                    markets.append(Market(market_type=MarketType.BTTS, odds=odds_list, source_id=source_id))
                elif key == "first_half_1x2":
                    markets.append(Market(market_type=MarketType.FIRST_HALF_1X2, odds=odds_list, source_id=source_id))
                elif key == "asian_handicap":
                    markets.append(Market(market_type=MarketType.ASIAN_HANDICAP, odds=odds_list, source_id=source_id))
                elif key == "over_under_1_5":
                    markets.append(Market(market_type=MarketType.OVER_UNDER_1_5, odds=odds_list, source_id=source_id))
                elif key == "over_under_2_5":
                    markets.append(Market(market_type=MarketType.OVER_UNDER_2_5, odds=odds_list, source_id=source_id))
                elif key == "over_under_3_5":
                    markets.append(Market(market_type=MarketType.OVER_UNDER_3_5, odds=odds_list, source_id=source_id))
                elif key == "over_under_4_5":
                    markets.append(Market(market_type=MarketType.OVER_UNDER_4_5, odds=odds_list, source_id=source_id))
                elif key == "over_under_5_5":
                    markets.append(Market(market_type=MarketType.OVER_UNDER_5_5, odds=odds_list, source_id=source_id))
        else:
            for entries in _resolve_mbet_sport_market(raw_sport_id, raw_odds, live=live).values():
                for market_type, odds_list, settlement in entries:
                    markets.append(
                        Market(
                            market_type=market_type,
                            odds=odds_list,
                            settlement=settlement,
                        )
                    )

        if not markets:
            return None

        # Extract real league/tournament name from nested fields
        tournament = e.get("tournament") or {}
        category = e.get("category") or {}
        league_name = str(
            tournament.get("name") or category.get("name") or sports.display_name(sport_name)
        )

        return Match(
            bookmaker=BOOKMAKER_ID,
            sport=sport_name,
            home_team=home,
            away_team=away,
            league=league_name,
            kickoff=kickoff,
            markets=markets,
            url="https://mbet.ba/",
            match_code=event_id,
            event_id=event_id,
            deep_link_verified=False,
            is_live=live,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    async def scrape(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        """Compatibility wrapper."""
        return await self.fetch_and_parse(
            live=live, scan_time=scan_time, sports_wanted=sports_wanted
        )
