"""
Mozzartbet Scraper — mozzartbet.ba

Playwright browser for Cloudflare session, then API interception + pagination.
"""

import logging
import time
from datetime import UTC, datetime

from engine.market_registry import MARKET_REGISTRY, record_unmapped
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import launch_browser
from scrapers.common import parse_dt

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "mozzartbet"
BASE_URL = "https://www.mozzartbet.ba"

# ---- Standalone helpers (no class dependency) ----

_parse_datetime = parse_dt


def _now_ms() -> int:
    """Current Unix time in milliseconds (Mozzartbet startTime units)."""
    return int(time.time() * 1000)


def _is_in_play(event: dict, now_ms: int, skew_ms: int = 300_000) -> bool:
    """True when the event has started (5-min clock-skew tolerance)."""
    start_ms = event.get("startTime")
    if not isinstance(start_ms, int | float):
        return False
    return start_ms <= now_ms + skew_ms


def _extract_team_name(val) -> str:
    if not val:
        return ""
    if isinstance(val, dict):
        return str(val.get("name", val.get("shortName", "")))
    return str(val) if isinstance(val, str) else ""


def _extract_teams(event: dict) -> tuple[str, str]:
    home_keys = [
        "home", "homeTeam", "home_team", "participant1", "homeParticipant",
        "teamHome", "team1", "Home", "homeTeamName", "hostTeam"
    ]
    away_keys = [
        "visitor", "guest", "guestTeam", "awayTeam", "away_team", "participant2",
        "guestParticipant", "teamAway", "team2", "Away", "awayTeamName", "visitorTeam"
    ]
    home = ""
    for k in home_keys:
        v = event.get(k)
        if v:
            home = _extract_team_name(v)
            if home:
                break
    away = ""
    for k in away_keys:
        v = event.get(k)
        if v:
            away = _extract_team_name(v)
            if away:
                break
    if not home or not away:
        name = str(event.get("name", event.get("matchName", event.get("eventName", ""))))
        if " - " in name:
            parts = name.split(" - ", 1)
            home = home or parts[0].strip()
            away = away or parts[1].strip()
    return home.strip(), away.strip()


def _extract_league(event: dict) -> str:
    for k in ["leagueName", "league", "competitionName", "competition",
              "tournamentName", "tournament", "championship", "League"]:
        v = event.get(k)
        if v:
            if isinstance(v, dict):
                name = v.get("name", v.get("shortName", ""))
                if name:
                    return str(name)
            elif isinstance(v, str) and v:
                return v
    return ""


def _extract_kickoff(event: dict) -> datetime | None:
    for k in ["startTime", "kickOff", "kickoff", "startAt", "date",
              "matchTime", "eventDate", "startDate", "timestamp", "dateTime"]:
        v = event.get(k)
        if v:
            dt = _parse_datetime(v)
            if dt:
                return dt
    return None


def _map_market_type(market_name: str) -> MarketType | None:
    name = str(market_name).lower().strip()
    if any(x in name for x in ["1x2", "krajnji ishod", "ishod meca", "full time result",
                                "match result", "winner", "1 x 2", "konacan ishod"]):
        return MarketType.MATCH_RESULT
    if any(x in name for x in ["gg/ng", "btts", "both teams", "gg ng", "gol-gol",
                                "oba tima da daju", "oba tima daju gol"]):
        return MarketType.BTTS
    if any(x in name for x in ["double chance", "dupla sansa", "dupla šansa"]):
        return MarketType.DOUBLE_CHANCE
    if any(x in name for x in ["over/under", "vise/manje", "vise", "manje",
                                "total goals", "ukupno golova"]):
        if "1.5" in name:
            return MarketType.OVER_UNDER_1_5
        if "3.5" in name:
            return MarketType.OVER_UNDER_3_5
        if "2.5" in name:
            return MarketType.OVER_UNDER_2_5
    return None


def _map_outcome_label(label: str, market_type: MarketType) -> str:
    raw = str(label).strip()
    rl = raw.lower()
    if market_type == MarketType.MATCH_RESULT:
        if raw in ("1", "Home"):
            return "1"
        if rl in ("x", "draw", "neriješeno", "remi"):
            return "X"
        if raw in ("2", "Away"):
            return "2"
        return raw
    if market_type in (MarketType.OVER_UNDER_1_5, MarketType.OVER_UNDER_2_5, MarketType.OVER_UNDER_3_5):
        t = {"OVER_UNDER_1_5": "1.5", "OVER_UNDER_2_5": "2.5", "OVER_UNDER_3_5": "3.5"}[market_type.name]
        if rl in ("over", "vise", "više", "3+") or "over" in rl:
            return f"Over {t}"
        if rl in ("under", "manje", "0-2") or "under" in rl:
            return f"Under {t}"
        return raw
    if market_type == MarketType.BTTS:
        if rl in ("gg", "da", "yes", "both", "gol-gol"):
            return "GG"
        if rl in ("ng", "ne", "no"):
            return "NG"
        return raw
    if market_type == MarketType.DOUBLE_CHANCE:
        u = raw.upper()
        if u in ("1X", "12", "X2"):
            return u
        return raw
    return raw


def _registered_spec(
    bookmaker: str,
    mode: str,
    source_id: int | str,
    market_type: MarketType,
    line: float | None = None,
):
    spec = MARKET_REGISTRY.lookup_type(
        bookmaker, mode, source_id, market_type, line=line
    )
    known = getattr(MARKET_REGISTRY, "has_source_id", None)
    if spec is None and (known is None or not known(bookmaker, mode, source_id)):
        record_unmapped(bookmaker, source_id)
    return spec


def _parse_markets(
    event: dict,
    mode: str = "prematch",
    bookmaker: str = BOOKMAKER_ID,
) -> list[Market]:
    markets: list[Market] = []
    raw_odds = event.get("odds")
    if not raw_odds or not isinstance(raw_odds, list):
        return markets

    mr_odds: list[OddsValue] = []
    dc_odds: list[OddsValue] = []
    btts_dict: dict[str, float] = {}
    ou_dict: dict[str, dict[str, float]] = {
        "1.5": {}, "2.5": {}, "3.5": {}
    }

    for o in raw_odds:
        if not isinstance(o, dict):
            continue
        game = o.get("game") or {}
        subgame = o.get("subgame") or {}
        raw_gid = game.get("id") if isinstance(game, dict) else None
        gid: int | str | None
        if isinstance(raw_gid, str) and raw_gid.isdigit():
            gid = int(raw_gid)
        else:
            gid = raw_gid
        gshort = str(game.get("shortName", "") if isinstance(game, dict) else "").lower()
        gname = str(game.get("name", "") if isinstance(game, dict) else "").lower()

        # Qualification/advance games ("ko ide dalje", "prolaz", ...) are not
        # match results — always exclude them.
        if any(w in f"{gshort} {gname}" for w in ("dalje", "prolaz", "kvalifikacije")):
            if gid is not None:
                record_unmapped(bookmaker, gid, context=f"{gshort} {gname}")
            continue

        sname = str(subgame.get("name", "") if isinstance(subgame, dict) else "").strip()

        try:
            val = float(o["value"]) if o.get("value") else 0.0
        except (ValueError, TypeError):
            continue
        if val < 1.01:
            continue

        # 1X2 (Game id=1 or ki / konačan ishod)
        if gid == 1 or gshort == "ki" or "konačan ishod" in gname or "konacan ishod" in gname:
            spec = _registered_spec(
                bookmaker, mode, gid if gid is not None else gname, MarketType.MATCH_RESULT
            )
            label = _map_outcome_label(sname, MarketType.MATCH_RESULT)
            if spec is not None and label in spec.labels:
                mr_odds.append(OddsValue(label=label, value=val))

        # Double Chance (Game id=2 or ds / dupla šansa)
        elif gid == 2 or gshort == "ds" or "dupla šansa" in gname or "dupla sansa" in gname:
            spec = _registered_spec(
                bookmaker, mode, gid if gid is not None else gname, MarketType.DOUBLE_CHANCE
            )
            label = _map_outcome_label(sname, MarketType.DOUBLE_CHANCE)
            if spec is not None and label in spec.labels:
                dc_odds.append(OddsValue(label=label, value=val))

        # BTTS (Game id=130 or tgg / oba tima daju gol)
        elif gid == 130 or gshort == "tgg" or "oba tima daju gol" in gname:
            spec = _registered_spec(
                bookmaker, mode, gid if gid is not None else gname, MarketType.BTTS
            )
            s_lower = sname.lower()
            if spec is not None and s_lower in ("gg", "da"):
                btts_dict["GG"] = val
            elif spec is not None and s_lower in ("ng", "ne"):
                btts_dict["NG"] = val

        # Total Goals Over/Under (Game id=3 or ug / ukupno golova)
        elif gid == 3 or gshort == "ug" or "ukupno golova" in gname:
            line_name = {
                "2+": "1.5", "0-1": "1.5",
                "3+": "2.5", "0-2": "2.5",
                "4+": "3.5", "0-3": "3.5",
            }.get(sname)
            market_type = {
                "1.5": MarketType.OVER_UNDER_1_5,
                "2.5": MarketType.OVER_UNDER_2_5,
                "3.5": MarketType.OVER_UNDER_3_5,
            }.get(line_name or "")
            spec = (
                _registered_spec(
                    bookmaker,
                    mode,
                    gid if gid is not None else gname,
                    market_type,
                    line=float(line_name),
                )
                if market_type is not None and line_name is not None
                else None
            )
            if spec is not None and line_name is not None:
                if sname in ("2+", "3+", "4+"):
                    label = f"Over {line_name}"
                else:
                    label = f"Under {line_name}"
                if label in spec.labels:
                    ou_dict[line_name][label] = val
        else:
            if gid is not None:
                record_unmapped(bookmaker, gid, context=f"{gshort} {gname}")

    # Only accept 1X2 when the registered minimum and label set are satisfied.
    mr_spec = MARKET_REGISTRY.lookup_type(bookmaker, mode, 1, MarketType.MATCH_RESULT)
    if (
        mr_spec is not None
        and len({o.label for o in mr_odds}) >= mr_spec.min_legs
        and {o.label for o in mr_odds}.issubset(mr_spec.labels)
    ):
        markets.append(Market(market_type=MarketType.MATCH_RESULT, odds=mr_odds))

    dc_spec = MARKET_REGISTRY.lookup_type(bookmaker, mode, 2, MarketType.DOUBLE_CHANCE)
    if (
        dc_spec is not None
        and len({o.label for o in dc_odds}) >= dc_spec.min_legs
        and {o.label for o in dc_odds}.issubset(dc_spec.labels)
    ):
        markets.append(Market(market_type=MarketType.DOUBLE_CHANCE, odds=dc_odds))

    btts_spec = MARKET_REGISTRY.lookup_type(bookmaker, mode, 130, MarketType.BTTS)
    btts_odds = [
        OddsValue(label=label, value=btts_dict[label])
        for label in ("GG", "NG")
        if label in btts_dict
    ]
    actual = {odd.label for odd in btts_odds}
    if (
        btts_spec is not None
        and len(actual) >= btts_spec.min_legs
        and actual.issubset(btts_spec.labels)
    ):
        markets.append(Market(market_type=MarketType.BTTS, odds=btts_odds))

    mt_map = {
        "1.5": MarketType.OVER_UNDER_1_5,
        "2.5": MarketType.OVER_UNDER_2_5,
        "3.5": MarketType.OVER_UNDER_3_5,
    }
    for thresh, odds_map in ou_dict.items():
        over_label = f"Over {thresh}"
        under_label = f"Under {thresh}"
        market_type = mt_map[thresh]
        spec = MARKET_REGISTRY.lookup_type(
            bookmaker, mode, 3, market_type, line=float(thresh)
        )
        ou_odds = [
            OddsValue(label=label, value=odds_map[label])
            for label in (over_label, under_label)
            if label in odds_map
        ]
        actual = {odd.label for odd in ou_odds}
        if (
            spec is not None
            and len(actual) >= spec.min_legs
            and actual.issubset(spec.labels)
        ):
            markets.append(Market(market_type=market_type, odds=ou_odds))

    return markets


def _find_events_in_payload(data, _depth: int = 0) -> list[dict]:
    """Recursively find event dicts with home/away teams in nested structures."""
    if _depth > 8:
        return []
    events = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                h, a = _extract_teams(item)
                if h and a:
                    events.append(item)
                else:
                    for val in item.values():
                        if isinstance(val, list | dict):
                            events.extend(_find_events_in_payload(val, _depth + 1))
    elif isinstance(data, dict):
        h, a = _extract_teams(data)
        if h and a:
            return [data]
        for key in ["items", "matches", "events", "games", "data", "content",
                     "results", "fixtures", "list", "offerEvents", "prematch"]:
            val = data.get(key)
            if val and isinstance(val, list | dict):
                found = _find_events_in_payload(val, _depth + 1)
                if found:
                    events.extend(found)
                    break
        else:
            for val in data.values():
                if isinstance(val, list | dict):
                    events.extend(_find_events_in_payload(val, _depth + 1))
    return events


def _event_to_match(event: dict, seen: set, live: bool = False) -> Match | None:
    home, away = _extract_teams(event)
    if not home or not away:
        return None
    mid = str(event.get("id", event.get("matchId", event.get("eventId", ""))))
    # Prefer the event ID for dedup — team-name pairs drop 2nd meetings of the same teams
    code = mid if mid else f"{home}|{away}"
    if code in seen:
        return None
    seen.add(code)
    league = _extract_league(event)
    kickoff = _extract_kickoff(event)
    markets = _parse_markets(event, mode="live" if live else "prematch")
    if not markets:
        return None
    return Match(
        bookmaker=BOOKMAKER_ID, home_team=home, away_team=away, league=league,
        kickoff=kickoff, markets=markets,
        url=f"{BASE_URL}/sr/{'uzivo' if live else 'kladjenje'}/sport/1", match_code=mid,
        event_id=mid, deep_link_verified=False,
        is_live=live,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )

# ---- Scraper class ----

class MozzartbetScraper:
    """
    Uses Playwright to:
    1. Open the betting page (Cloudflare session)
    2. Intercept the initial JSON payloads
    3. Paginate through all pages via page.request (POST)
    4. Parse all collected items into Match objects
    """

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        p, browser, context = await launch_browser()
        all_raw_items: list[dict] = []
        try:
            page = await context.new_page()

            # Intercept initial API responses + our own paginated calls
            seen_urls: set[str] = set()

            async def capture_response(response):
                url = response.url
                if "betting/matches" in url and url not in seen_urls:
                    seen_urls.add(url)
                    try:
                        data = await response.json()
                        items = data.get("items", []) if isinstance(data, dict) else []
                        all_raw_items.extend(items)
                    except Exception:
                        pass

            page.on("response", capture_response)

            # 1. Load the page (triggers initial API calls)
            await page.goto(f"{BASE_URL}/sr/kladjenje", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            # 2. Paginate via page.request (with correct headers from the page)
            # Site uses currentPage 0-based and pageSize 15. The API returns
            # matchCount per page (not total) and nextStepPath, so we paginate
            # until a short page is returned. Vision 2026-08-20 showed 88 Fudbal
            # fixtures but scraper only returned 23 due to early break on matchCount.
            page_size = 15
            api_body: dict = {
                "date": "live" if live else "all_days",
                "sort": "bycompetition",
                "pageSize": page_size, "sportId": 1,
                "competitionIds": [], "search": "", "matchTypeId": 0,
            }
            referer = f"{BASE_URL}/sr/kladjenje/sport/1?date=all_days"
            page_num = 0
            max_pages = 100  # safety cap; real break is short page

            while page_num < max_pages:
                api_body["currentPage"] = page_num
                try:
                    resp = await page.request.post(
                        f"{BASE_URL}/betting/matches",
                        data=api_body,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/plain, */*",
                            "medium": "WEB",
                            "Referer": referer,
                            "x-unique-id": f"mozz_{page_num}",
                        },
                    )
                    if resp.status != 200:
                        logger.debug(f"[Mozzartbet] Page {page_num} status {resp.status}")
                        break
                    data = await resp.json()
                    items = data.get("items", [])
                    if not items:
                        break
                    all_raw_items.extend(items)

                    # Only totalPages is reliable for total; matchCount is per-page
                    total_pages = data.get("totalPages")
                    if isinstance(total_pages, int) and total_pages > 0:
                        max_pages = min(total_pages, 100)

                    logger.debug(f"[Mozzartbet] Page {page_num}/{max_pages}: {len(items)} items")
                    if len(items) < page_size:
                        break
                    page_num += 1

                except Exception as e:
                    logger.debug(f"[Mozzartbet] Pagination page {page_num} error: {e}")
                    break
        finally:
            await browser.close()
            await p.stop()

        # Deduplicate and parse. The "live" date filter also returns upcoming
        # fixtures, so keep only events that have actually started.
        seen: set[str] = set()
        matches: list[Match] = []
        now_ms = _now_ms()
        for ev in all_raw_items:
            if live and not _is_in_play(ev, now_ms):
                continue
            m = _event_to_match(ev, seen, live=live)
            if m:
                matches.append(m)

        logger.info(f"[Mozzartbet] {len(matches)} {'live' if live else 'prematch'} matches from {len(all_raw_items)} raw items")
        return matches

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        return await self.fetch_and_parse(live=live, scan_time=scan_time)
