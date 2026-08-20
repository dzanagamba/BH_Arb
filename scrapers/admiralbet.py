"""
Admiralbet Scraper — admiralbet.ba

Playwright hybrid: navigate to establish Cloudflare session, then
paginate through the API via page.request.

API: getEventsStartingSoonFilterSelections?topN=25&skipN={skip}
"""

import logging
from datetime import UTC, datetime, timedelta

from models.schemas import Market, MarketType, Match
from scrapers.base import launch_browser
from scrapers.common import nsoft_event_url, parse_dt, parse_nsoft_bets, parse_nsoft_live_bets

logger = logging.getLogger(__name__)

def _parse_dt(raw) -> datetime | None:
    return parse_dt(raw)

BOOKMAKER_ID = "admiralbet"
BASE_URL = "https://www.admiralbet.ba"
API_DOMAIN = "https://bihoffer.admiralbet.ba"

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


def _parse_bets(bets: list, live: bool = False) -> list[Market]:
    if live:
        # Live feed uses the NSoft live bet type ID space (6/18/42/995/22/28).
        return parse_nsoft_live_bets(bets)
    # Validated shared parser, with Admiralbet's own prematch IDs (1639 = 1X2).
    # Rejects incomplete/misclassified markets (e.g. the "Ide dalje" advance
    # market) via label-set validation.
    return parse_nsoft_bets(bets, extra_bet_types={1639: MarketType.MATCH_RESULT})


class AdmiralbetScraper:
    """Admiralbet — Playwright hybrid (session + API pagination)."""

    async def fetch_and_parse(self, live: bool = False) -> list[Match]:
        p, browser, context = await launch_browser()
        all_raw_events: list[dict] = []
        try:
            page = await context.new_page()

            # 1. Get Cloudflare session
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)

            # 2. Navigate to football prematch page (loads API)
            await page.goto(
                f"{BASE_URL}/sport-prematch?sport=Fudbal",
                wait_until="domcontentloaded", timeout=60000,
            )
            await page.wait_for_timeout(5000)

            # 3. Fetch all football events via getwebevents endpoint
            now = datetime.now(UTC)
            date_from = now.strftime("%Y-%m-%dT%H:%M:%S.000")
            date_to = (now + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S.000")

            url = (
                f"{API_DOMAIN}/api/offer/getwebevents"
                f"?sportId=1&isLive={'true' if live else 'false'}"
                f"&dateFrom={date_from}&dateTo={date_to}"
                f"&eventMappingTypes=1,2,3,4,5"
            )
            resp = await page.request.get(
                url,
                headers={
                    "Accept": "application/utf8+json, application/json;q=0.9, text/plain;q=0.8, */*;q=0.7",
                    "language": "bs-Latn",
                    "officeid": "2037",
                    "Referer": f"{BASE_URL}/sport-prematch?sport=Fudbal",
                },
            )
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, dict):
                    all_raw_events = data.get("events", [])
                elif isinstance(data, list):
                    all_raw_events = data
        except Exception as e:
            logger.error(f"[Admiralbet] Fetch error: {e}")
        finally:
            await browser.close()
            await p.stop()

        # Parse events into Match objects
        seen = set()
        matches: list[Match] = []
        for ev in all_raw_events:
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
            league = str(ev.get("competitionName") or ev.get("regionName") or ev.get("leagueName") or "")
            kickoff = _parse_dt(ev.get("dateTime") or ev.get("dateFrom") or ev.get("kickoff"))
            markets = _parse_bets(ev.get("bets", []), live=live)
            if not markets:
                continue
            matches.append(Match(
                bookmaker=BOOKMAKER_ID, home_team=home, away_team=away,
                league=league, kickoff=kickoff, markets=markets,
                url=nsoft_event_url(BASE_URL, mid, live=live), match_code=mid,
                is_live=live,
            ))

        logger.info(f"[Admiralbet] {len(matches)} {'live' if live else 'prematch'} matches from {len(all_raw_events)} raw events")
        return matches

    async def scrape(self, live: bool = False) -> list[Match]:
        return await self.fetch_and_parse(live=live)
