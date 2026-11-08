"""
Admiralbet Scraper — admiralbet.ba

Playwright hybrid: navigate to establish Cloudflare session, then
paginate through the API with an in-page ``fetch`` (SR4-8a).

API: getEventsStartingSoonFilterSelections?topN=25&skipN={skip}
"""

import logging
from contextlib import AsyncExitStack
from datetime import UTC, datetime

from engine import sports
from engine.structural_drift import observe
from models.schemas import Market, Match
from scrapers.base import browser_session, goto, measured_api_get, settle
from scrapers.common import (
    betradar_id,
    build_event_url,
    nsoft_event_window,
    nsoft_offered,
    parse_dt,
    parse_nsoft_bets,
    parse_nsoft_live_bets,
    qualify_league,
)
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.retry import retry_call
from scrapers.transport import policy_for
from scrapers.wire_schemas import validate_response

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "admiralbet"
BASE_URL = "https://www.admiralbet.ba"
API_DOMAIN = "https://bihoffer.admiralbet.ba"

SPORT_MAP: dict[int, str] = {
    1: "football",
    2: "basketball",
    3: "tennis",
    4: "ice_hockey",
}

# Bet type ID mapping — VERIFIED against the live Admiralbet catalog (2026-08):
#   - 135/1639: 1X2 (Admiralbet serves 1X2 as 1639, MDShop as 135)
#   - 152: Double Chance, 151: BTTS, 137/138: O/U goals (threshold in sBV)
#   - 136 is "Ide dalje" — the 2-way ADVANCE/qualification market that appears
#     ONLY on knockout games. It must NEVER be treated as 1X2 or DC.
#   - 148/149 (HT/2nd-half 1X2), 140 (HT/FT), 153/154/166/174 (DNB/handicap/
#     combos), 143/144/161/162 (half totals) are all excluded.
# Parsing delegates to parse_nsoft_bets(), which additionally enforces strict
# outcome label sets per market type (defense-in-depth against misclassification).


def _parse_teams(event: dict) -> tuple[str, str]:
    # Try various team name fields
    home = event.get("home", event.get("homeTeam", event.get("homeName", "")))
    away = event.get("guest", event.get("awayTeam", event.get("awayName", "")))
    if isinstance(home, dict):
        home = home.get("name", "")
    if isinstance(away, dict):
        away = away.get("name", "")
    if isinstance(home, str) and isinstance(away, str) and home and away:
        return home.strip(), away.strip()
    # Fall back to event name
    name = event.get("name", "")
    if isinstance(name, str) and " - " in name:
        parts = name.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return "", ""


def _league_name(event: dict) -> str:
    """Admiralbet names competitions without the country, so it is prefixed."""
    competition = str(event.get("competitionName") or event.get("leagueName") or "")
    return qualify_league(competition, str(event.get("regionName") or ""))


def _parse_bets(
    bets: list,
    live: bool = False,
    source_context: dict[str, str] | None = None,
    sport: str = "football",
) -> list[Market]:
    if live:
        # Live feed uses the NSoft live bet type ID space (6/18/42/995/22/28).
        return parse_nsoft_live_bets(
            bets, bookmaker=BOOKMAKER_ID, source_context=source_context
        )
    # The registry carries Admiralbet's bookmaker-specific prematch IDs.
    return parse_nsoft_bets(
        bets,
        bookmaker=BOOKMAKER_ID,
        mode="prematch",
        source_context=source_context,
        sport=sport,
    )


class AdmiralbetScraper:
    """Admiralbet — Playwright hybrid (session + API pagination)."""

    async def fetch_and_parse(
        self,
        live: bool = False,
        scan_time: datetime | None = None,
        sports_wanted: tuple[str, ...] | list[str] | None = None,
    ) -> list[Match]:
        wanted = (
            {sports.FOOTBALL}
            if sports_wanted is None
            else {sports.normalize_sport(value) or value for value in sports_wanted}
        )
        stack = AsyncExitStack()
        context = await stack.enter_async_context(browser_session(BOOKMAKER_ID))
        all_raw_events: list[dict] = []
        try:
            page = await context.new_page()

            # 1. Get Cloudflare session
            await goto(page, BASE_URL, wait_until="domcontentloaded", timeout=60000)
            await settle(page, 3000)

            # 2. Navigate to football prematch page (loads API)
            await goto(
                page,
                f"{BASE_URL}/sport-prematch?sport=Fudbal",
                wait_until="domcontentloaded", timeout=60000,
            )
            await settle(page, 5000)

            # 3. Fetch each requested sport. Live looks back 12h: NSoft filters
            #    by kickoff, so a window starting at now drops every game
            #    already in play. See `scrapers.common.nsoft_event_window`.
            now_aware = (scan_time.replace(tzinfo=UTC) if scan_time and scan_time.tzinfo is None else scan_time) if scan_time else datetime.now(UTC)
            window_from, window_to = nsoft_event_window(now_aware, live)
            date_from = window_from.strftime("%Y-%m-%dT%H:%M:%S.000")
            date_to = window_to.strftime("%Y-%m-%dT%H:%M:%S.000")

            for sport_id, sport_name in SPORT_MAP.items():
                if sport_name not in wanted:
                    continue
                url = (
                    f"{API_DOMAIN}/api/offer/getwebevents"
                    f"?sportId={sport_id}&isLive={'true' if live else 'false'}"
                    f"&dateFrom={date_from}&dateTo={date_to}"
                    f"&eventMappingTypes=1,2,3,4,5"
                )
                async def fetch_events(url=url):
                    return await measured_api_get(
                        page,
                        url,
                        headers={
                            "Accept": "application/utf8+json, application/json;q=0.9, text/plain;q=0.8, */*;q=0.7",
                            "language": "bs-Latn",
                            "officeid": "2037",
                            "Referer": f"{BASE_URL}/sport-prematch?sport=Fudbal",
                        },
                    )

                resp = await retry_call(
                    fetch_events,
                    policy=policy_for(
                        BOOKMAKER_ID, "live" if live else "prematch"
                    ),
                    label="admiralbet events",
                    account=False,
                )
                try:
                    data = await resp.json()
                except ValueError as exc:
                    raise ScrapeError(
                        ScrapeKind.SCHEMA_DRIFT,
                        f"{BOOKMAKER_ID} response is not JSON: {exc}",
                    ) from exc
                # SR4-4: alert on a raw-shape change outside the modelled
                # fields; alert only, the payload is untouched.
                observe(
                    BOOKMAKER_ID,
                    f"{'live' if live else 'prematch'}:events:{sport_id}",
                    data,
                )
                # SR4-3c: Admiralbet serves the same NSoft envelope as MDShop,
                # so it reuses the NSoft models. The adapter's historical
                # bare-list form is wrapped so the same schema applies; a
                # non-JSON body or a drifted row is schema drift.
                if isinstance(data, list):
                    envelope: dict = {"events": data}
                else:
                    envelope = data
                validate_response(envelope, book=BOOKMAKER_ID)
                events = envelope.get("events", []) if isinstance(envelope, dict) else []
                if isinstance(events, list):
                    all_raw_events.extend(events)
        except ScrapeError:
            raise
        except Exception as e:
            logger.error(f"[Admiralbet] Fetch error: {e}")
        finally:
            await stack.aclose()

        # Parse events into Match objects
        seen = set()
        matches: list[Match] = []
        for ev in all_raw_events:
            if not isinstance(ev, dict) or not nsoft_offered(ev):
                continue
            if live:
                # Skip simulated-reality events ("SRL ...") — not real matches
                name_l = str(ev.get("name", "")).lower()
                comp_l = str(ev.get("competitionName") or "").lower()
                if "srl" in name_l or "srl" in comp_l or "simul" in comp_l or "virtual" in comp_l:
                    continue
            home, away = _parse_teams(ev)
            if not home or not away:
                continue
            mid = str(ev.get("id", ev.get("eventId", "")))
            # Prefer the event ID for dedup — team-name pairs drop 2nd meetings of the same teams
            code = mid if mid else f"{home}|{away}"
            if code in seen:
                continue
            seen.add(code)
            league = _league_name(ev)
            kickoff = parse_dt(ev.get("dateTime") or ev.get("dateFrom") or ev.get("kickoff"))
            sport_name = SPORT_MAP.get(int(ev.get("sportId") or 0), "football")
            source_context = {
                "sport_id": str(ev.get("sportId") or ""),
                "region_id": str(ev.get("regionId") or ""),
                "region_name": str(ev.get("regionName") or ""),
                "competition_id": str(ev.get("competitionId") or ""),
                "competition_name": str(ev.get("competitionName") or ""),
                "event_id": mid,
                "event_name": str(ev.get("name") or ""),
            }
            markets = _parse_bets(
                ev.get("bets", []), live=live, source_context=source_context,
                sport=sport_name,
            )
            if not markets:
                continue
            matches.append(Match(
                bookmaker=BOOKMAKER_ID, sport=sport_name, home_team=home, away_team=away,
                league=league, kickoff=kickoff, markets=markets,
                url=build_event_url("admiralbet", mid, BASE_URL, live=live), match_code=mid,
                event_id=mid, source_context=source_context, deep_link_verified=False,
                betradar_id=betradar_id(ev.get("betRadarEventId"), ev.get("externalEventId")),
                is_live=live,
                fetched_at=datetime.now(UTC).replace(tzinfo=None),
            ))

        logger.info(f"[Admiralbet] {len(matches)} {'live' if live else 'prematch'} matches from {len(all_raw_events)} raw events")
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
