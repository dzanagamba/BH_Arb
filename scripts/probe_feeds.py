"""Probe one or more configured bookmaker feeds and report what they publish.

This is the repeatable evidence behind a book being disabled, enabled, or
onboarded: it runs the real scraper and reports match counts, market types and
errors. It never changes settings or mappings.

    python scripts/probe_feeds.py --books evlbet,betole
    python scripts/probe_feeds.py --books all --live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import BOOKMAKERS  # noqa: E402
from scrapers.browser_pool import browser_pool  # noqa: E402
from server.api import SCRAPERS  # noqa: E402


async def probe_one(bookmaker: str, scraper_class: type, live: bool, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        matches = await asyncio.wait_for(scraper_class().scrape(live=live), timeout=timeout)
    except Exception as exc:  # a probe reports failure, it does not crash the run
        return {
            "bookmaker": bookmaker,
            "matches": 0,
            "markets": {},
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "duration_seconds": round(time.monotonic() - started, 1),
        }
    markets = Counter(
        market.market_type.value for match in matches for market in match.markets
    )
    return {
        "bookmaker": bookmaker,
        "matches": len(matches),
        "markets": dict(sorted(markets.items())),
        "error": "",
        "duration_seconds": round(time.monotonic() - started, 1),
    }


def _selected(books: str) -> list[str]:
    if books.strip().lower() == "all":
        return list(BOOKMAKERS)
    return [book.strip() for book in books.split(",") if book.strip()]


async def run(books: list[str], live: bool, timeout: float) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    # SR3-3: a probe of several browser books shares one Chromium, like a scan.
    async with browser_pool():
        for bookmaker in books:
            scraper_class = SCRAPERS.get(bookmaker)
            if scraper_class is None:
                results.append(
                    {
                        "bookmaker": bookmaker,
                        "matches": 0,
                        "markets": {},
                        "error": "no scraper registered",
                        "duration_seconds": 0.0,
                    }
                )
                continue
            results.append(await probe_one(bookmaker, scraper_class, live, timeout))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", default="all", help="comma-separated ids, or all")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--out", help="write the JSON report here")
    args = parser.parse_args(argv)

    books = _selected(args.books)
    results = asyncio.run(run(books, args.live, args.timeout))
    text = json.dumps({"live": args.live, "books": results}, indent=2, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
