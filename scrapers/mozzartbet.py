"""
Mozzartbet Scraper — mozzartbet.ba

Playwright browser for Cloudflare session, then API interception + pagination.
"""

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from datetime import UTC, datetime

from engine.market_registry import lookup_type, record_unmapped, registered_spec
from engine.structural_drift import observe
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.base import (
    browser_session,
    fetch_pages,
    goto,
    measured_api_post,
    settle,
)
from scrapers.common import parse_dt
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.retry import retry_call
from scrapers.transport import policy_for
from scrapers.wire_schemas import validate_mozzart_offer, validate_mozzart_page

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "mozzartbet"
BASE_URL = "https://www.mozzartbet.ba"
# SR7-1: one request per event for the full offer (the list endpoint carries
# four complete families; the match endpoint carries 518 odds, including the
# first-half 1X2 and the 1.5/3.5/4.5/5.5 totals). SR7-2: the operator raised the
# per-book ceiling to 60 requests/second. 32 requests are kept in flight, but the
# measured ceiling is the browser's per-host connection pool: two scans reached
# ~16 requests/second (a 40.8 s and a 43.8 s walk), so the browser transport —
# not the limiter — is the limit.
FULL_OFFER_CONCURRENCY = 32

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
    for k in ["startTime", "kickOffTime", "kickOff", "kickoff", "startAt", "date",
              "matchTime", "eventDate", "startDate", "timestamp", "dateTime"]:
        v = event.get(k)
        if v:
            dt = _parse_datetime(v)
            if dt:
                return dt
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
    return registered_spec(bookmaker, mode, source_id, market_type, line=line)


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
    ht_odds: list[OddsValue] = []
    ou_dict: dict[str, dict[str, float]] = {
        "1.5": {}, "2.5": {}, "3.5": {}, "4.5": {}, "5.5": {}
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
                "5+": "4.5", "0-4": "4.5",
                "6+": "5.5", "0-5": "5.5",
            }.get(sname)
            market_type = {
                "1.5": MarketType.OVER_UNDER_1_5,
                "2.5": MarketType.OVER_UNDER_2_5,
                "3.5": MarketType.OVER_UNDER_3_5,
                "4.5": MarketType.OVER_UNDER_4_5,
                "5.5": MarketType.OVER_UNDER_5_5,
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
                if sname in ("2+", "3+", "4+", "5+", "6+"):
                    label = f"Over {line_name}"
                else:
                    label = f"Under {line_name}"
                if label in spec.labels:
                    ou_dict[line_name][label] = val

        # First-half 1X2 (game id=4 / 1pp). Experimental, like Betole's: the
        # family has no registry row and the labels are the plain 1/X/2.
        elif gid == 4 or gshort == "1pp":
            label = _map_outcome_label(sname, MarketType.MATCH_RESULT)
            if label in ("1", "X", "2"):
                ht_odds.append(OddsValue(label=label, value=val))
        else:
            if gid is not None:
                record_unmapped(bookmaker, gid, context=f"{gshort} {gname}")

    # Only accept 1X2 when the registered minimum and label set are satisfied.
    mr_spec = lookup_type(bookmaker, mode, 1, MarketType.MATCH_RESULT)
    if (
        mr_spec is not None
        and len({o.label for o in mr_odds}) >= mr_spec.min_legs
        and {o.label for o in mr_odds}.issubset(mr_spec.labels)
    ):
        markets.append(
            Market(market_type=MarketType.MATCH_RESULT, odds=mr_odds, source_id="1")
        )

    dc_spec = lookup_type(bookmaker, mode, 2, MarketType.DOUBLE_CHANCE)
    if (
        dc_spec is not None
        and len({o.label for o in dc_odds}) >= dc_spec.min_legs
        and {o.label for o in dc_odds}.issubset(dc_spec.labels)
    ):
        markets.append(
            Market(market_type=MarketType.DOUBLE_CHANCE, odds=dc_odds, source_id="2")
        )

    btts_spec = lookup_type(bookmaker, mode, 130, MarketType.BTTS)
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
        markets.append(
            Market(market_type=MarketType.BTTS, odds=btts_odds, source_id="130")
        )

    if len({o.label for o in ht_odds}) == 3:
        markets.append(
            Market(
                market_type=MarketType.FIRST_HALF_1X2,
                odds=ht_odds,
                source_id="4",
            )
        )

    mt_map = {
        "1.5": MarketType.OVER_UNDER_1_5,
        "2.5": MarketType.OVER_UNDER_2_5,
        "3.5": MarketType.OVER_UNDER_3_5,
        "4.5": MarketType.OVER_UNDER_4_5,
        "5.5": MarketType.OVER_UNDER_5_5,
    }
    for thresh, odds_map in ou_dict.items():
        over_label = f"Over {thresh}"
        under_label = f"Under {thresh}"
        market_type = mt_map[thresh]
        spec = lookup_type(
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
            markets.append(
                Market(market_type=market_type, odds=ou_odds, source_id="3")
            )

    return markets


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
    3. Paginate through all pages with an in-page fetch (POST, SR4-8a)
    4. Parse all collected items into Match objects
    """

    async def _complete_offer(self, page, event_id, mode: str) -> list | None:
        """One event's full offer, or ``None`` when it cannot be read.

        The endpoint is a POST (an empty JSON body is enough); a GET answers
        ``{"error": "Not found. Sorry."}``. A failed offer keeps the list odds
        for that event (the events that were read still price); the failure is
        logged so it is not silent. SR4-3b: the raw payload is validated before
        the parser sees it. A drifted offer row drops the whole book, because
        the same wire shape serves every event. SR4-10: a missing ``value`` is
        a suspended pick, not drift.
        """
        try:
            response = await retry_call(
                lambda: measured_api_post(
                    page,
                    f"{BASE_URL}/betting/match/{event_id}",
                    data="{}",
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/plain, */*",
                        "medium": "WEB",
                        "Referer": f"{BASE_URL}/sr/kladjenje/sport/1/match/{event_id}",
                    },
                ),
                policy=policy_for(BOOKMAKER_ID, mode),
                label=f"mozzartbet offer {event_id}",
                account=False,
            )
        except Exception as exc:  # noqa: BLE001 - this event keeps its list odds
            logger.warning(
                "[Mozzartbet] full offer for %s failed: %s", event_id, exc
            )
            return None
        try:
            payload = await response.json()
        except ValueError as exc:
            raise ScrapeError(
                ScrapeKind.SCHEMA_DRIFT,
                f"{BOOKMAKER_ID} offer for {event_id} is not JSON: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001 - this event keeps its list odds
            logger.warning(
                "[Mozzartbet] full offer for %s failed: %s", event_id, exc
            )
            return None
        offer = validate_mozzart_offer(payload, book=BOOKMAKER_ID)
        # SR4-4: only a real offer establishes/moves the baseline; a per-event
        # error payload is a legitimate different shape and must not alarm.
        if offer.match is not None:
            observe(BOOKMAKER_ID, "offer", payload)
        odds = payload.get("match", {}).get("odds") if offer.match is not None else None
        return odds if isinstance(odds, list) and odds else None

    async def _build_matches(
        self, page, items: list[dict], live: bool, mode: str
    ) -> list[Match]:
        """Fetch every event's full offer, then parse in the list's order."""
        now_ms = _now_ms()
        seen: set[str] = set()
        matches: list[Match] = []
        semaphore = asyncio.Semaphore(FULL_OFFER_CONCURRENCY)
        lock = asyncio.Lock()

        async def one(event: dict) -> None:
            if live and not _is_in_play(event, now_ms):
                return
            event_id = event.get("id")
            offer = None
            if event_id is not None:
                async with semaphore:
                    offer = await self._complete_offer(page, event_id, mode)
            enriched = dict(event)
            if offer:
                enriched["odds"] = offer
            async with lock:
                match = _event_to_match(enriched, seen, live=live)
                if match is not None:
                    matches.append(match)

        results = await asyncio.gather(
            *(one(event) for event in items), return_exceptions=True
        )
        # A drifted offer is the book's wire shape changing, so it drops the
        # whole book (fail closed) instead of leaving the other events priced.
        for result in results:
            if isinstance(result, ScrapeError):
                raise result
            if isinstance(result, BaseException):
                logger.debug("[Mozzartbet] event parse failed: %s", result)
        return matches

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        stack = AsyncExitStack()
        context = await stack.enter_async_context(browser_session(BOOKMAKER_ID))
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
                # SR4-3b: the listener is a supplement to the paginated walk,
                # which is the path that validates the envelope and odds rows;
                # this handler cannot propagate a ScrapeError to the scrape.

            page.on("response", capture_response)

            # 1. Load the page (triggers initial API calls)
            await goto(page, f"{BASE_URL}/sr/kladjenje", wait_until="domcontentloaded", timeout=60000)
            await settle(page, 3000)

            # 2. Paginate with an in-page fetch (correct headers from the page)
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
            max_pages = 100  # safety cap; real break is short page

            async def fetch_page(page_num: int) -> list | None:
                # The POST body is a read-only page query, so retrying it is safe.
                try:
                    resp = await retry_call(
                        lambda: measured_api_post(
                            page,
                            f"{BASE_URL}/betting/matches",
                            data={**api_body, "currentPage": page_num},
                            headers={
                                "Content-Type": "application/json",
                                "Accept": "application/json, text/plain, */*",
                                "medium": "WEB",
                                "Referer": referer,
                                "x-unique-id": f"mozz_{page_num}",
                            },
                        ),
                        policy=policy_for(
                            BOOKMAKER_ID, "live" if live else "prematch"
                        ),
                        label=f"mozzartbet page {page_num}",
                        account=False,
                    )
                    try:
                        data = await resp.json()
                    except ValueError as exc:
                        raise ScrapeError(
                            ScrapeKind.SCHEMA_DRIFT,
                            f"{BOOKMAKER_ID} matches page {page_num} is not JSON: {exc}",
                        ) from exc
                    # SR4-3b: the list envelope and every item's odds array are
                    # validated before the parser reads them.
                    observe(BOOKMAKER_ID, "matches", data)
                    page_payload = validate_mozzart_page(data, book=BOOKMAKER_ID)
                    nonlocal max_pages
                    # Only totalPages is reliable for total; matchCount is per-page
                    total_pages = page_payload.totalPages
                    if isinstance(total_pages, int) and total_pages > 0:
                        max_pages = min(total_pages, 100)
                    return page_payload.items
                except ScrapeError:
                    raise
                except Exception as e:
                    logger.debug(f"[Mozzartbet] Pagination page {page_num} error: {e}")
                    return None

            # Page 0 first: its totalPages bounds the concurrent fetch of the rest.
            first = await fetch_page(0)
            if first:
                all_raw_items.extend(first)
                if len(first) >= page_size and max_pages > 1:
                    all_raw_items.extend(
                        await fetch_pages(fetch_page, page_size, max_pages - 1, first_page=1)
                    )

            # SR7-1: one full-offer request per unique event, fetched while the
            # browser session is still open. Duplicates (the page listener and
            # our pagination both see items) are collapsed first so no event is
            # requested twice.
            unique: dict[str, dict] = {}
            for event in all_raw_items:
                event_id = event.get("id")
                if event_id is not None:
                    unique.setdefault(str(event_id), event)
            matches = await self._build_matches(
                page,
                list(unique.values()),
                live,
                "live" if live else "prematch",
            )
        finally:
            await stack.aclose()

        logger.info(f"[Mozzartbet] {len(matches)} {'live' if live else 'prematch'} matches from {len(all_raw_items)} raw items")
        return matches

    async def scrape(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        # SR6-2: the shared adapter contract carries `sports_wanted`; this feed
        # walks every soccer list it is given, so the filter is accepted and
        # unused (the scan passed it nowhere before, with the same result).
        return await self.fetch_and_parse(live=live, scan_time=scan_time)
