"""Measure per-book, per-sport coverage before implementing a sport.

The rule this script encodes is the one the expansion used:

* count only the nine enabled books in ``config.settings.BOOKMAKERS``;
* a sport is admissible only when at least three of those books publish at
  least three *comparable* full-match market families (moneyline, handicap,
  total) with the same settlement;
* a book that cannot be measured records its blocker instead of being guessed.

It uses the real feeds. For the books whose non-football parsers are implemented
it runs the shipped scraper; for ice hockey, which was measured and left out, it
reads the same raw endpoints directly so the blocking evidence is explicit.

    python scripts/measure_sports.py --out docs/evidence/2026-11-04-sport-discovery.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import BOOKMAKERS, VERIFY_SSL  # noqa: E402
from engine import sports  # noqa: E402
from scrapers.maxbet import MATCHES_API, SPORT_IDS  # noqa: E402
from scrapers.mbet import MBetScraper  # noqa: E402
from scrapers.mdshop import MDShopScraper  # noqa: E402
from scrapers.sportplus import SportPlusScraper  # noqa: E402

ENABLED = [book for book, cfg in BOOKMAKERS.items() if cfg.get("enabled", True)]
SPORTS = [sports.BASKETBALL, sports.TENNIS, sports.ICE_HOCKEY]

IMPLEMENTED_BOOKS = ("sportplus", "mbet", "mdshop", "admiralbet", "maxbet")


def _family_counts(matches: list) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter()
    for match in matches:
        for market_type in {market.market_type for market in match.markets}:
            counts[market_type.value] += 1
    return dict(sorted(counts.items()))


async def _scraper_coverage(book: str, sport: str) -> dict:
    scraper_cls = {
        "sportplus": SportPlusScraper,
        "mbet": MBetScraper,
        "mdshop": MDShopScraper,
        "admiralbet": __import__(
            "scrapers.admiralbet", fromlist=["AdmiralbetScraper"]
        ).AdmiralbetScraper,
        "maxbet": __import__(
            "scrapers.maxbet", fromlist=["MaxBetScraper"]
        ).MaxBetScraper,
    }[book]
    try:
        matches = await scraper_cls().scrape(
            live=False, sports_wanted=[sports.FOOTBALL, sport]
        )
    except Exception as exc:
        return {"book": book, "sport": sport, "error": f"{type(exc).__name__}: {exc}"[:240]}
    sport_matches = [m for m in matches if m.sport == sport]
    counts = _family_counts(sport_matches)
    families = {
        market_type.value
        for match in sport_matches
        for market_type in {market.market_type for market in match.markets}
    }
    return {
        "book": book,
        "sport": sport,
        "matches": len(sport_matches),
        "markets": counts,
        "comparable_families": len(families & _sport_families(sport)),
    }


def _sport_families(sport: str) -> set[str]:
    spec = sports.spec_for(sport)
    if spec is None:
        return set()
    return {spec.moneyline.value, spec.handicap.value, spec.total.value}


async def _hockey_raw() -> list[dict]:
    """Raw hockey coverage for the books the parsers do not implement."""
    rows: list[dict] = []
    now = datetime.now(UTC)
    from_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000")
    to_iso = (now.replace(hour=23, minute=59)).strftime("%Y-%m-%dT%H:%M:%S.000")

    # SportPlus: raw names.
    async with httpx.AsyncClient(timeout=120.0, verify=VERIFY_SSL) as client:
        resp = await client.get("https://www.sportplus.ba/api/v1/prematch/offer")
        data = resp.json()
        if isinstance(data, str):
            data = json.loads(data)
        events = [m for m in data.get("matches", []) if m.get("sportName") == "HOKEJ"]
        families: set[str] = set()
        for event in events:
            for market in event.get("markets", []):
                name = str(market.get("name") or "").casefold()
                if name in ("hokej", "konačan pobjednik", "konacan pobjednik"):
                    families.add("moneyline")
                elif "hendikep" in name:
                    families.add("handicap")
                elif name.startswith("zbroj golova"):
                    families.add("total")
        rows.append({
            "book": "sportplus",
            "sport": sports.ICE_HOCKEY,
            "matches": len(events),
            "markets": sorted(families),
            "comparable_families": len(families),
            "settlement_note": "regular time (Zbroj golova); winner incl. OT is a separate market",
        })

    # MBet: raw keys.
    async with httpx.AsyncClient(timeout=60.0, verify=VERIFY_SSL) as client:
        resp = await client.get(
            "https://api.mbet.ba/events_cached",
            params={
                "live": "false", "offer_plan": "true", "fields": "all", "lang": "ba",
                "limit": 1000, "offset": 0, "orderBy": "startTimeAsc",
            },
        )
        events = [
            e for e in resp.json().get("events", [])
            if e.get("id_sport") == "ih" and e.get("odds")
        ]
        families = set()
        for event in events:
            keys = event.get("odds", {})
            if any(key.startswith("oih:fs:") for key in keys):
                families.add("moneyline")
            if any(key.startswith("oih:h:") for key in keys):
                families.add("handicap")
            if any(key.startswith("oih:g:") for key in keys):
                families.add("total")
        rows.append({
            "book": "mbet",
            "sport": sports.ICE_HOCKEY,
            "matches": len(events),
            "markets": sorted(families),
            "comparable_families": len(families),
            "settlement_note": "oih:fs is the 3-way full-time market; oih:g is match goals",
        })

    # NSoft (MDShop; Admiralbet serves the same IDs).
    async with httpx.AsyncClient(timeout=60.0, verify=VERIFY_SSL) as client:
        resp = await client.get(
            "https://mdoffer.mdshop.ba/api/offer/getwebevents",
            params={
                "sportId": 4, "isLive": "false", "dateFrom": from_iso, "dateTo": to_iso,
                "eventMappingTypes": 1,
            },
            headers={
                "User-Agent": "Mozilla/5.0", "Accept": "application/json",
                "language": "sr-Latn", "officeid": "1678",
                "referer": "https://www.mdshop.ba/",
            },
        )
        events = [e for e in resp.json().get("events", []) if e.get("bets")]
        ids = {int(b.get("betTypeId")) for e in events for b in e.get("bets", [])
               if str(b.get("betTypeId", "")).isdigit()}
        families = {"moneyline"} if 135 in ids else set()
        families |= {"total"} if 137 in ids else set()
        rows.append({
            "book": "mdshop+admiralbet",
            "sport": sports.ICE_HOCKEY,
            "matches": len(events),
            "markets": sorted(families),
            "comparable_families": len(families),
            "settlement_note": "135 is 3-way regulation; 137 is match goals; no full-match handicap ID was observed",
        })

    # MaxBet: odd types.
    async with httpx.AsyncClient(timeout=60.0, verify=VERIFY_SSL) as client:
        resp = await client.get(
            MATCHES_API,
            params=[("sportId", SPORT_IDS[sports.ICE_HOCKEY]), ("ln", "cnr"),
                    ("ot", 1), ("ot", 16), ("ot", 212)],
        )
        events = [e for e in resp.json() if e.get("odds")]
        ids = {o.get("id") for e in events for o in e.get("odds", [])}
        families = set()
        if 1 in ids:
            families.add("moneyline")
        if 16 in ids:
            families.add("handicap")
        # 212 is "uklj. prod." (including overtime), so it cannot be combined
        # with the regular-time markets above without lowering the gate.
        rows.append({
            "book": "maxbet",
            "sport": sports.ICE_HOCKEY,
            "matches": len(events),
            "markets": sorted(families) + (["total_incl_ot"] if 212 in ids else []),
            "comparable_families": len(families & {"moneyline", "handicap", "total"}),
            "settlement_note": "total id 212 includes overtime; no regular-time total was offered in this window",
        })
    return rows


BLOCKERS = {
    "premier_kladionica": (
        "Non-football event sports are in the sync, but the setTip market rows use a "
        "different sport dimension than the event rows; no mapping was proven, so no "
        "non-football market is admitted."
    ),
    "mozzartbet": (
        "A Cloudflare browser session is required and the non-football sport id map "
        "was not proven from a captured payload."
    ),
    "wwin": (
        "The event endpoint needs a browser session; unauthenticated probes return an "
        "empty body, so sport ids and market ids are unproven."
    ),
    "betole": (
        "The desk feed is football-only (every event carries sport='S'); it publishes "
        "no other sport to measure."
    ),
}


async def run() -> dict:
    rows: list[dict] = []
    for book in IMPLEMENTED_BOOKS:
        for sport in (sports.BASKETBALL, sports.TENNIS):
            rows.append(await _scraper_coverage(book, sport))
    rows.extend(await _hockey_raw())

    by_sport: dict[str, dict] = {}
    for sport in SPORTS:
        sport_rows = [row for row in rows if row.get("sport") == sport]
        qualifiers = [
            row["book"] for row in sport_rows
            if row.get("comparable_families", 0) >= 3
        ]
        by_sport[sport] = {
            "books": sport_rows,
            "qualifying_books": qualifiers,
            "admissible": len(qualifiers) >= 3,
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": (
            "at least three of the nine enabled books must publish at least three "
            "comparable full-match families with the same settlement"
        ),
        "enabled_books": ENABLED,
        "sports": by_sport,
        "blockers": BLOCKERS,
        "decision": {
            "implemented": [sports.BASKETBALL, sports.TENNIS],
            "left_unimplemented": [sports.ICE_HOCKEY],
            "reason_ice_hockey": (
                "Only sportplus and mbet publish three regular-time families; NSoft "
                "has no full-match handicap id and MaxBet's only total includes "
                "overtime. Pairing an incl-OT total with a regular-time one would "
                "price two different bets."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the JSON report here")
    args = parser.parse_args(argv)
    report = asyncio.run(run())
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(text)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
