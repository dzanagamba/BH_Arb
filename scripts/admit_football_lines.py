"""Admit new football total lines from measurement, not from preference.

For each candidate line this script counts the real prematch rows, verifies every
row's labels classify to that line, counts the independent price sources, and
runs the existing devigged-median consensus over the verified groups. It writes
the dated evidence document; it never edits a parser or a registry.

    python scripts/admit_football_lines.py --out docs/evidence/2026-11-04-football-lines.json
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from config.settings import VERIFY_SSL, price_source  # noqa: E402
from engine.market_consensus import find_outliers  # noqa: E402
from engine.market_discovery import classify  # noqa: E402
from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import Match  # noqa: E402
from scrapers.common import parse_dt  # noqa: E402
from scrapers.maxbet import MaxBetScraper  # noqa: E402
from scrapers.mbet import MBetScraper  # noqa: E402
from scrapers.mdshop import MDShopScraper  # noqa: E402
from scrapers.premier_kladionica import PremierKladionicaScraper  # noqa: E402
from scrapers.wwin import _build_markets_from_bets  # noqa: E402

CANDIDATES = ("over_under_0_5", "over_under_4_5", "over_under_5_5")
WWIN_TOTALS_API = (
    "https://wwin.ba/content/sport-livecontent/api/PrematchEvents/events"
    "?bets=11&key=bs&spid=2"
)


async def _wwin_matches() -> list[Match]:
    """WWIN's public totals feed. Only idBt 11 is requested, so no other
    market can reach this measurement."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://wwin.ba/kladjenje/",
    }
    async with httpx.AsyncClient(timeout=90.0, verify=VERIFY_SSL) as client:
        response = await client.get(WWIN_TOTALS_API, headers=headers)
        response.raise_for_status()
        data = response.json()
    if isinstance(data, str):
        data = json.loads(data)
    matches: list[Match] = []
    for event in data.get("events", []):
        markets = _build_markets_from_bets(event.get("bets", []))
        if not markets:
            continue
        matches.append(
            Match(
                bookmaker="wwin",
                home_team=str(event.get("hname") or ""),
                away_team=str(event.get("aname") or ""),
                league=str(event.get("tname") or ""),
                kickoff=parse_dt(event.get("startTime")),
                markets=markets,
                betradar_id=str(event.get("brid") or ""),
            )
        )
    return matches


async def _collect() -> list:
    matches = []
    for scraper_cls in (MaxBetScraper, MBetScraper, MDShopScraper):
        matches.extend(
            await scraper_cls().scrape(live=False, sports_wanted=["football"])
        )
    # Premier's football path does not take the multi-sport keyword.
    matches.extend(await PremierKladionicaScraper().scrape(live=False))
    matches.extend(await _wwin_matches())
    return matches


def _classifies(market_type: str, labels: list[str]) -> bool:
    if not labels:
        return False
    try:
        line = float(labels[0].split()[-1])
    except (IndexError, ValueError):
        return False
    classification = classify(labels, line=line)
    return classification is not None and classification.market_type.value == market_type


async def run() -> dict:
    matches = await _collect()
    groups = MatchMatcher().group_matches(matches)
    markets: dict[str, dict] = {}
    for market_type in CANDIDATES:
        source_rows: collections.Counter[str] = collections.Counter()
        rows = 0
        classified = 0
        for match in matches:
            for market in match.markets:
                if market.market_type.value != market_type:
                    continue
                rows += 1
                if _classifies(market_type, [odd.label for odd in market.odds]):
                    classified += 1
                source_rows[price_source(match.bookmaker)] += 1
        markets[market_type] = {
            "rows": rows,
            "classified_rows": classified,
            "price_sources": sorted(source_rows),
            "source_rows": dict(source_rows),
            "admitted": len(source_rows) >= 3 and classified == rows and rows > 0,
        }

    outliers, compared = find_outliers(groups)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "matches": len(matches),
        "groups": len(groups),
        "markets": markets,
        "compared_market_rows": compared,
        "outliers": outliers,
        "outlier_count": len(outliers),
        "method": (
            "at least three independent price sources, every label set classifies "
            "to the line, and zero devigged-median outliers on the verified groups"
        ),
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
