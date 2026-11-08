"""
SportPlus Scraper — sportplus.ba

Direct REST API via httpx.

Endpoint: GET https://www.sportplus.ba/api/v1/prematch/offer
Returns: { "matches": [...] } with competitor names and market arrays.
"""

import json
import logging
import re
from datetime import UTC, datetime

from engine import sports
from engine.market_registry import record_unmapped, registered_spec
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.common import betradar_id, normalize_outcome, parse_local_dt, qualify_league
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.retry import fetch_with_retry
from scrapers.transport import transport_client
from scrapers.wire_schemas import (
    validate_sportplus_live,
    validate_sportplus_prematch,
)

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "sportplus"

SPORT_MAP: dict[str, str] = {
    "NOGOMET": "football",
    "KOŠARKA": "basketball",
    "TENIS": "tennis",
    "HOKEJ": "ice_hockey",
    "RUKOMET": "handball",
    "VATERPOLO": "waterpolo",
    "BASEBALL": "baseball",
    "PIKADO": "darts",
    "SNOOKER": "snooker",
    "ULTIMATE FIGHT": "mma",
    "BOKS": "boxing",
    "FUTSAL": "futsal",
    "AM. NOGOMET": "american_football",
    "AMERIČKI NOGOMET": "american_football",
    "ODBOJKA": "volleyball",
    "STOLNI TENIS": "table_tennis",
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

_PREFIX_LABEL = re.compile(r"^[A-Z]{1,3}/")
_NUMBER = re.compile(r"[+-]?\d+(?:[.,]\d+)?")


def _wanted_sports(values: tuple[str, ...] | list[str] | None) -> set[str]:
    """Canonical sports to parse. Default is football, the historical path."""
    if values is None:
        return {sports.FOOTBALL}
    wanted = {sports.normalize_sport(value) or value for value in values}
    return wanted or {sports.FOOTBALL}


def _line_from_text(text: str) -> float | None:
    """Last signed decimal in a label/competitor string, comma or dot."""
    matches = _NUMBER.findall(str(text or ""))
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", "."))
    except ValueError:
        return None


def _sportplus_odds(odds_raw: list) -> dict[str, float]:
    values: dict[str, float] = {}
    for odd in odds_raw:
        if not isinstance(odd, dict):
            continue
        alias = str(odd.get("alias") or odd.get("field") or "")
        try:
            value = float(odd.get("value") or 0.0)
        except (TypeError, ValueError):
            continue
        if value >= 1.01:
            values[alias] = max(values.get(alias, 0.0), value)
    return values


_PERIOD_MARKERS = (
    "set",
    "četvrt",
    "cetvrt",
    "poluvrijeme",
    "poluvreme",
    "trećin",
    "trecin",
    "inning",
    "period",
)


def _has_period_marker(text: str) -> bool:
    folded = " ".join(str(text or "").casefold().split())
    return any(marker in folded for marker in _PERIOD_MARKERS)


def _parse_sportplus_sport_markets(
    raw_markets: list, sport: str, live: bool = False
) -> list[Market]:
    """Classify SportPlus basketball/tennis markets by name and structure."""
    spec = sports.spec_for(sport)
    if spec is None:
        return []
    result: list[Market] = []
    for raw in raw_markets:
        if not isinstance(raw, dict):
            continue
        name = " ".join(str(raw.get("name") or "").strip().split())
        folded = name.casefold()
        competitors = str(raw.get("competitors") or "")
        odds = _sportplus_odds(raw.get("odds", []))
        if not odds:
            continue

        family = ""
        settlement = ""
        line: float | None = None
        if sport == sports.BASKETBALL:
            if folded in ("pobjednik", "konačan pobjednik", "konacan pobjednik"):
                # Prematch "POBJEDNIK" is including overtime; the live feed's
                # "Pobjednik" is regular time and "Konačan pobjednik" is the
                # including-overtime one. Only the latter two-family name or the
                # prematch description proves the settlement.
                if live and folded == "pobjednik":
                    continue
                family, settlement = "moneyline", spec.moneyline_settlement
            elif "hendikep" in folded and not _has_period_marker(folded):
                family, settlement = "handicap", spec.handicap_settlement
                line = _line_from_text(name if live else competitors)
            elif folded.startswith("zbroj") and "uključ" not in folded and "ukljuc" not in folded:
                if _has_period_marker(folded):
                    continue
                family, settlement = "total", spec.total_settlement
                line = _line_from_text(name if live else competitors)
        elif sport == sports.TENNIS:
            if folded in ("osnovno", "pobjednik"):
                family, settlement = "moneyline", spec.moneyline_settlement
            elif "hendikep gemova" in folded and not _has_period_marker(folded):
                family, settlement = "handicap", spec.handicap_settlement
                line = _line_from_text(name if live else competitors)
            elif folded.startswith("zbroj gemova") and not _has_period_marker(folded):
                family, settlement = "total", spec.total_settlement
                line = _line_from_text(name if live else competitors)
        if not family:
            continue

        if family == "moneyline":
            labels = spec.moneyline_labels
            picked = [(label, odds[label]) for label in labels if label in odds]
            if len(picked) != len(labels):
                continue
            market_type = spec.moneyline
        elif family == "handicap":
            if line is None or "1" not in odds or "2" not in odds:
                continue
            from scrapers.common import ah_label

            market_type = spec.handicap
            # SportPlus writes the underdog/away line in the competitors suffix
            # (`h/Fils(+2,5)`), so the home line is its negation.
            home_line = -line
            picked = [
                (ah_label("1", home_line), odds["1"]),
                (ah_label("2", -home_line), odds["2"]),
            ]
        else:
            if line is None:
                continue
            under = odds.get("Manje") or odds.get("1(M)") or odds.get("M")
            over = odds.get("Više") or odds.get("Vise") or odds.get("2(V)") or odds.get("V")
            if not over or not under:
                continue
            market_type = spec.total
            magnitude = abs(line)
            picked = [(f"Over {magnitude:g}", over), (f"Under {magnitude:g}", under)]

        result.append(
            Market(
                market_type=market_type,
                odds=[OddsValue(label=label, value=value) for label, value in picked],
                source_id=str(raw.get("id") or ""),
                settlement=settlement,
                period="full_time",
            )
        )
    return result



def _registered_spec(
    mode: str,
    source_id: int | str,
    market_type: MarketType,
    line: float | None = None,
):
    return registered_spec("sportplus", mode, source_id, market_type, line=line)


class SportPlusScraper:
    """Scraper for sportplus.ba — direct REST API."""

    def __init__(self):
        self.url = BASE_API
        self.headers = dict(API_HEADERS)

    async def fetch_and_parse(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        wanted = _wanted_sports(sports_wanted)
        if live:
            return await self._fetch_live(scan_time=scan_time, sports_wanted=wanted)
        all_matches: list[Match] = []
        seen_codes: set[tuple] = set()

        async with transport_client(BOOKMAKER_ID, "prematch") as client:
            try:
                resp = await fetch_with_retry(client, self.url, headers=self.headers)

                # Response may be double-serialized
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise ScrapeError(
                        ScrapeKind.SCHEMA_DRIFT,
                        f"{BOOKMAKER_ID} response is not JSON: {exc}",
                    ) from exc
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except ValueError as exc:
                        raise ScrapeError(
                            ScrapeKind.SCHEMA_DRIFT,
                            f"{BOOKMAKER_ID} double-serialised body is not JSON: {exc}",
                        ) from exc

                # SR4-3f: validate the envelope and every market block before
                # the parser reads them.
                raw_matches = validate_sportplus_prematch(
                    data, book=BOOKMAKER_ID
                ).matches
                logger.info(f"[SportPlus] {len(raw_matches)} raw matches")

                for m in raw_matches:
                    try:
                        match = self._parse_match(m, seen_codes, wanted)
                        if match:
                            all_matches.append(match)
                    except Exception as e:
                        logger.debug(f"[SportPlus] Parse error: {e}")
                        continue

            except ScrapeError:
                raise
            except Exception as e:
                logger.error(f"[SportPlus] Fetch error: {e}")

        logger.info(f"[SportPlus] Total: {len(all_matches)} matches")
        return all_matches

    async def _fetch_live(
        self,
        scan_time: datetime | None = None,
        sports_wanted: set[str] | None = None,
    ) -> list[Match]:
        """Fetch and parse the in-play offer (`/api/v1/live/offer`)."""
        wanted = sports_wanted or {sports.FOOTBALL}
        all_matches: list[Match] = []
        seen_ids: set[str] = set()

        async with transport_client(BOOKMAKER_ID, "live") as client:
            try:
                resp = await fetch_with_retry(client, LIVE_API, headers=self.headers)

                try:
                    data = resp.json()
                except ValueError as exc:
                    raise ScrapeError(
                        ScrapeKind.SCHEMA_DRIFT,
                        f"{BOOKMAKER_ID} live response is not JSON: {exc}",
                    ) from exc
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except ValueError as exc:
                        raise ScrapeError(
                            ScrapeKind.SCHEMA_DRIFT,
                            f"{BOOKMAKER_ID} live body is not JSON: {exc}",
                        ) from exc

                # Live payload: { "date": ..., "sports": [{ id, name, matches: [...] }] }
                sports_raw = validate_sportplus_live(data, book=BOOKMAKER_ID).sports
                for sport in sports_raw:
                    if not isinstance(sport, dict):
                        continue
                    sport_name = sports.normalize_sport(sport.get("name"))
                    if sport_name not in wanted:
                        continue
                    for m in sport.get("matches", []):
                        try:
                            match = self._parse_live_match(m, seen_ids, sport_name)
                            if match:
                                all_matches.append(match)
                        except Exception as e:
                            logger.debug(f"[SportPlus] Live parse error: {e}")
                            continue
            except ScrapeError:
                raise
            except Exception as e:
                logger.error(f"[SportPlus] Live fetch error: {e}")

        logger.info(f"[SportPlus] Live total: {len(all_matches)} matches")
        return all_matches

    def _parse_live_match(self, m: dict, seen_ids: set, sport: str = "football") -> Match | None:
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
        home = _PREFIX_LABEL.sub("", home).strip()
        away = _PREFIX_LABEL.sub("", away).strip()
        if not home or not away or home.lower() == away.lower():
            return None

        markets = self._parse_live_markets(m.get("markets", []), sport)
        if not markets:
            return None

        league = str(m.get("leagueName") or sports.display_name(sport))
        return Match(
            bookmaker=BOOKMAKER_ID,
            sport=sport,
            home_team=home,
            away_team=away,
            league=league,
            kickoff=None,
            markets=markets,
            url="https://www.sportplus.ba/live",
            match_code=match_id,
            event_id=match_id,
            betradar_id=betradar_id(m.get("betRadarId")),
            deep_link_verified=False,
            is_live=True,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    def _parse_live_markets(self, raw_markets: list, sport: str = "football") -> list[Market]:
        """Parse live markets; non-football uses the sport vocabulary."""
        if sport != sports.FOOTBALL:
            return _parse_sportplus_sport_markets(raw_markets, sport, live=True)
        return self._parse_live_markets_football(raw_markets)

    def _parse_live_markets_football(self, raw_markets: list) -> list[Market]:
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

            raw_id = market.get("id")

            def append_market(
                market_type: MarketType,
                odds: list[OddsValue],
                _source_id: object = raw_id,
            ) -> None:
                if any(m.market_type == market_type for m in result):
                    return
                result.append(
                    Market(
                        market_type=market_type,
                        odds=odds,
                        source_id=(
                            str(_source_id)
                            if isinstance(_source_id, int | str)
                            else ""
                        ),
                    )
                )

            if name == "Pobjednik":
                spec = _registered_spec("live", "POBJEDNIK", MarketType.MATCH_RESULT)
                if spec is None:
                    continue
                by_label: dict[str, float] = {}
                for alias, value in read_odds():
                    if alias in spec.labels:
                        by_label[alias] = max(by_label.get(alias, 0.0), value)
                if len(by_label) >= spec.min_legs and set(by_label).issubset(spec.labels):
                    append_market(MarketType.MATCH_RESULT, [
                        OddsValue(label=label, value=by_label[label])
                        for label in ("1", "X", "2") if label in by_label
                    ])
            elif name.startswith("Dvostruka Prilika"):
                spec = _registered_spec("live", "DVOSTRUKA_PRILIKA", MarketType.DOUBLE_CHANCE)
                if spec is None:
                    continue
                by_label = {}
                for alias, value in read_odds():
                    if alias in spec.labels:
                        by_label[alias] = max(by_label.get(alias, 0.0), value)
                if len(by_label) >= spec.min_legs and set(by_label).issubset(spec.labels):
                    append_market(MarketType.DOUBLE_CHANCE, [
                        OddsValue(label=label, value=by_label[label])
                        for label in ("1X", "12", "X2") if label in by_label
                    ])
            elif name == "Oba daju gol":
                spec = _registered_spec("live", "OBA_DAJU_GOL", MarketType.BTTS)
                if spec is None:
                    continue
                gg = ng = None
                for alias, value in read_odds():
                    if alias in ("1(D)", "1D", "Da", "GG"):
                        gg = max(gg or 0.0, value)
                    elif alias in ("2(N)", "2N", "Ne", "NG"):
                        ng = max(ng or 0.0, value)
                btts_odds = [
                    OddsValue(label=label, value=value)
                    for label, value in (("GG", gg), ("NG", ng))
                    if value is not None
                ]
                actual = {odd.label for odd in btts_odds}
                if len(actual) >= spec.min_legs and actual.issubset(spec.labels):
                    append_market(MarketType.BTTS, btts_odds)
            elif name.startswith("Zbroj golova "):
                # Only the match total. "Zbroj golova domaćin 2.5" and
                # "Zbroj golova gost 2.5" are one team's goals; on 2026-10-27
                # the home total was read as match O/U 1.5 while the real
                # 1.5 line was suspended.
                import re as _re
                match_line = _re.fullmatch(r"Zbroj golova (\d+[.,]\d+)", name)
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
                spec = _registered_spec("live", "ZBROJ_GOLOVA", market_type, line=float(line))
                if spec is None:
                    continue
                over = under = None
                for alias, value in read_odds():
                    if "V" in alias:
                        over = max(over or 0.0, value)
                    elif "M" in alias:
                        under = max(under or 0.0, value)
                ou_odds = [
                    OddsValue(label=label, value=value)
                    for label, value in (
                        (f"Over {line}", over),
                        (f"Under {line}", under),
                    )
                    if value is not None
                ]
                actual = {odd.label for odd in ou_odds}
                if len(actual) >= spec.min_legs and actual.issubset(spec.labels):
                    append_market(market_type, ou_odds)
        return result

    def _parse_match(self, m: dict, seen_codes: set, wanted: set[str] | None = None) -> Match | None:
        wanted = wanted or {sports.FOOTBALL}
        raw_sport = str(m.get("sportName", "")).upper()
        sport_name = sports.normalize_sport(SPORT_MAP.get(raw_sport) or raw_sport)
        if not sport_name or sport_name not in wanted:
            return None

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

        # SportPlus sends Sarajevo wall-clock time with no offset.
        kickoff = parse_local_dt(m.get("matchDate"))

        # Extract league/competition name + country
        league_raw = m.get("leagueName")
        country_raw = m.get("countryName")
        country = str(country_raw).strip() if country_raw else ""
        if sport_name == sports.FOOTBALL:
            league_name = qualify_league(str(league_raw or ""), country)
        else:
            league_name = str(league_raw or "").strip()
        league_name = league_name or sports.display_name(sport_name)

        markets = self._parse_markets(m.get("markets", []), sport_name)
        if not markets:
            return None
        for market in markets:
            market.source_context.update({
                "sportplus_match_id": match_id,
                "sportplus_sport_id": str(m.get("sportId") or ""),
                "sportplus_match_date": str(m.get("matchDate") or ""),
                "sportplus_competitors": competitors_str,
            })

        return Match(
            bookmaker=BOOKMAKER_ID,
            sport=sport_name,
            home_team=home,
            away_team=away,
            league=league_name,
            country=country,
            kickoff=kickoff,
            markets=markets,
            url="https://www.sportplus.ba/prematch/betting",
            match_code=match_id,
            event_id=match_id,
            betradar_id=betradar_id(m.get("betRadarId")),
            deep_link_verified=False,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
        )

    def _parse_markets(self, raw_markets: list, sport: str = "football") -> list[Market]:
        """Parse SportPlus market objects into Market list."""
        if sport != sports.FOOTBALL:
            return _parse_sportplus_sport_markets(raw_markets, sport, live=False)
        # SportPlus exposes standard O/U 2.5 (id=768) and the same threshold
        # through the goal-range blocks (ids=800/802). Keep one canonical
        # market per type while retaining the best valid quote if both blocks
        # are present.
        markets_by_type: dict[MarketType, dict[str, OddsValue]] = {}

        market_context: dict[MarketType, dict[str, object]] = {}

        def _raw_alias(label: str, market_type: MarketType) -> str:
            """The SportPlus ``alias`` for a canonical label, for a ticket prefill."""
            if label in {"1", "X", "2", "1X", "12", "X2"}:
                return label
            if label == "GG":
                return "Da"
            if label == "NG":
                return "Ne"
            if label.startswith("Over "):
                return "Više"
            if label.startswith("Under "):
                return "Manje"
            if label.startswith("1 "):
                return "1"
            if label.startswith("2 "):
                return "2"
            return label

        def add_market(
            market_type: MarketType, odds: list[OddsValue], raw_market: dict
        ) -> None:
            by_label = markets_by_type.setdefault(market_type, {})
            for odd in odds:
                current = by_label.get(odd.label)
                if current is None or odd.value > current.value:
                    by_label[odd.label] = odd
            context = market_context.setdefault(market_type, {})
            context["market_code"] = str(raw_market.get("code") or "")
            context["market_id"] = str(raw_market.get("id") or "")
            aliases = context.setdefault("aliases", {})
            if isinstance(aliases, dict):
                for odd in odds:
                    aliases[odd.label] = _raw_alias(odd.label, market_type)

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
                if isinstance(market_id, int | str):
                    record_unmapped("sportplus", market_id, context=market_name)
                continue

            odds_raw = market.get("odds", [])
            if not odds_raw:
                continue

            # 1X2 & Double Chance (same market block)
            if market_name in SPORT_MAP or market_id == 1:
                source_id = market_id if isinstance(market_id, int | str) else ""
                mr_spec = _registered_spec("prematch", source_id, MarketType.MATCH_RESULT)
                dc_spec = _registered_spec("prematch", source_id, MarketType.DOUBLE_CHANCE)
                match_result_odds = []
                dc_odds = []
                for o in odds_raw:
                    alias = o.get("alias")
                    val = o.get("value")
                    try:
                        odd_val = float(val) if val else 0
                    except (ValueError, TypeError):
                        continue
                    if (
                        mr_spec is not None
                        and alias in mr_spec.labels
                        and odd_val >= 1.01
                    ):
                        match_result_odds.append(
                            OddsValue(label=normalize_outcome(alias, MarketType.MATCH_RESULT), value=odd_val)
                        )
                    elif (
                        dc_spec is not None
                        and alias in dc_spec.labels
                        and odd_val >= 1.01
                    ):
                        dc_odds.append(
                            OddsValue(label=normalize_outcome(alias, MarketType.DOUBLE_CHANCE), value=odd_val)
                        )
                if (
                    mr_spec is not None
                    and len({o.label for o in match_result_odds}) >= mr_spec.min_legs
                    and {o.label for o in match_result_odds}.issubset(mr_spec.labels)
                ):
                    add_market(MarketType.MATCH_RESULT, match_result_odds, market)
                if (
                    dc_spec is not None
                    and len({o.label for o in dc_odds}) >= dc_spec.min_legs
                    and {o.label for o in dc_odds}.issubset(dc_spec.labels)
                ):
                    add_market(MarketType.DOUBLE_CHANCE, dc_odds, market)

            # Over/Under 2.5
            elif market_name == "ZBROJ GOLOVA 2,5" or market_id == 768:
                source_id = market_id if isinstance(market_id, int | str) else ""
                spec = _registered_spec(
                    "prematch", source_id, MarketType.OVER_UNDER_2_5, line=2.5
                )
                odds_list = self._parse_ou_odds(odds_raw, "2.5")
                if spec is not None and odds_list and len(odds_list) >= spec.min_legs:
                    add_market(MarketType.OVER_UNDER_2_5, odds_list, market)

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
                    add_market(MarketType.FIRST_HALF_1X2, fh_odds, market)

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
                    ], market)

            # Both Teams to Score
            elif market_name == "OBA TIMA DAJU GOL" or market_id == 6:
                source_id = market_id if isinstance(market_id, int | str) else ""
                spec = _registered_spec("prematch", source_id, MarketType.BTTS)
                btts_odds = self._parse_btts_odds(odds_raw)
                if spec is not None and btts_odds and len(btts_odds) >= spec.min_legs:
                    add_market(MarketType.BTTS, btts_odds, market)

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
                        threshold = label.split()[-1]
                        market_type = {
                            "1.5": MarketType.OVER_UNDER_1_5,
                            "2.5": MarketType.OVER_UNDER_2_5,
                            "3.5": MarketType.OVER_UNDER_3_5,
                        }.get(threshold)
                        source_id = (
                            market_id
                            if isinstance(market_id, int | str)
                            else ""
                        )
                        spec = (
                            _registered_spec(
                                "prematch", source_id, market_type, line=float(threshold)
                            )
                            if market_type is not None
                            else None
                        )
                        if spec is not None and label in spec.labels:
                            current = goal_range_odds.get(label)
                            if current is None or odd_val > current.value:
                                goal_range_odds[label] = OddsValue(label=label, value=odd_val)
            else:
                if market_id is not None and market_name not in {
                    "PRVO POLUVRIJEME",
                    "AZIJSKI HENDIKEP",
                }:
                    record_unmapped("sportplus", market_id, context=market_name)

        for market_type, over_label, under_label in (
            (MarketType.OVER_UNDER_1_5, "Over 1.5", "Under 1.5"),
            (MarketType.OVER_UNDER_2_5, "Over 2.5", "Under 2.5"),
            (MarketType.OVER_UNDER_3_5, "Over 3.5", "Under 3.5"),
        ):
            over = goal_range_odds.get(over_label)
            under = goal_range_odds.get(under_label)
            source_id = 800
            spec = _registered_spec(
                "prematch", source_id, market_type, line=float(over_label.split()[-1])
            )
            if over is None or under is None:
                continue
            actual = {over.label, under.label}
            if (
                spec is not None
                and len(actual) >= spec.min_legs
                and actual.issubset(spec.labels)
            ):
                add_market(market_type, [over, under], market)

        result: list[Market] = []
        for market_type, odds_by_label in markets_by_type.items():
            context = market_context.get(market_type, {})
            aliases = context.get("aliases") or {}
            result.append(
                Market(
                    market_type=market_type,
                    odds=list(odds_by_label.values()),
                    source_id=str(context.get("market_id") or ""),
                    source_context={
                        "sportplus_market_code": str(context.get("market_code") or ""),
                        "sportplus_market_id": str(context.get("market_id") or ""),
                        "sportplus_odd_aliases": json.dumps(aliases),
                    },
                )
            )
        return result

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

    async def scrape(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        """Compatibility wrapper."""
        return await self.fetch_and_parse(live=live, scan_time=scan_time, sports_wanted=sports_wanted)
