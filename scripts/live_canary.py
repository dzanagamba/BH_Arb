"""SR4-9: the daily live canary.

WHAT THIS IS
------------
Offline fixtures cannot see a book change its site. The canary runs every
configured book once, through the real adapter and the shared transport policy
(rate limiter, deadlines, no login), and writes a dated report. It compares the
run with the previous report and raises a reason when a book fails, loses more
than half its matches, or loses a market family it used to publish.

The operator decision (SR4-9, 2026-11-08) is: this host, daily. The canary is
deliberately **not** part of CI — a failing canary must never fail the main
build — and it never refreshes or rewrites a fixture. Its only write is the
report under the report directory (default ``cache/live_canary/``).

USAGE
-----
    python scripts/live_canary.py                  # every book, prematch
    python scripts/live_canary.py --live           # every book, live
    python scripts/live_canary.py --books mbet,mdshop
    python scripts/live_canary.py --strict         # exit 1 when a reason fires

The default exit code is 0 even when a reason fires, so an installed timer does
not page on an ordinary feed gap; ``--strict`` makes a one-off shell run return
1. Reports are JSON; ``docs/LIVE_CANARY.md`` documents the schema and a timer.

The structural fingerprint is the set of market families the parser emits plus
their counts. The raw-payload fingerprint is already checked inside every
adapter at its raw-JSON boundary (SR4-4), so a renamed field is reported there
before the parser drops it; this report adds the cross-run view.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.probe_feeds import probe_one  # noqa: E402

# A book that used to publish this many matches and now publishes less than
# half is worth a look. Small books are left to the market rule below.
MIN_MATCHES = 10
# Same idea per market family: a family that had at least this many markets and
# then halves is a real loss, not an ordinary list change.
MIN_MARKETS = 5

DEFAULT_REPORT_DIR = REPO_ROOT / "cache" / "live_canary"


def _registry() -> Mapping[str, Any]:
    """The configured scraper classes, imported lazily (server.api is heavy)."""
    from server.api import SCRAPERS

    return SCRAPERS


def _books_for(books: str, registry: Mapping[str, Any]) -> list[str]:
    if books.strip().lower() == "all":
        return list(registry)
    return [book.strip() for book in books.split(",") if book.strip()]


def compare(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    """Reasons this run differs from the previous one, in operator words.

    Only losses and failures count. A new market family is not a reason; it is
    reported separately so an added family is visible without being an alarm.
    """
    reasons: list[str] = []
    if current.get("error"):
        return [f"error: {current['error']}"]
    if previous is None:
        return reasons

    previous_matches = int(previous.get("matches") or 0)
    current_matches = int(current.get("matches") or 0)
    if previous_matches >= MIN_MATCHES and current_matches < previous_matches / 2:
        reasons.append(f"matches {previous_matches} -> {current_matches}")

    previous_markets = previous.get("markets") or {}
    current_markets = current.get("markets") or {}
    for market_type, previous_count in sorted(previous_markets.items()):
        if int(previous_count) < MIN_MARKETS:
            continue
        current_count = int(current_markets.get(market_type) or 0)
        if current_count < int(previous_count) / 2:
            reasons.append(f"{market_type} {previous_count} -> {current_count}")
    return reasons


def new_market_types(
    previous: dict[str, Any] | None, current: dict[str, Any]
) -> list[str]:
    if previous is None:
        return []
    return sorted(set(current.get("markets") or {}) - set(previous.get("markets") or {}))


def _load_report(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _previous_report(report_dir: Path, current_path: Path) -> dict[str, Any] | None:
    """The newest other report in the directory, or None on the first run."""
    candidates = sorted(
        (path for path in report_dir.glob("*.json") if path != current_path),
        key=lambda path: path.name,
    )
    if not candidates:
        return None
    return _load_report(candidates[-1])


def _previous_book(report: dict[str, Any] | None, bookmaker: str) -> dict[str, Any] | None:
    if report is None:
        return None
    for entry in report.get("books") or []:
        if isinstance(entry, dict) and entry.get("bookmaker") == bookmaker:
            return entry
    return None


async def run(
    books: str,
    *,
    live: bool = False,
    timeout: float = 180.0,
    scrapers: Mapping[str, Any] | None = None,
    report_dir: Path | None = None,
    today: str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Probe every selected book once and write the dated report.

    ``scrapers`` is the test seam: a mapping of book id to a class with
    ``async scrape(live=...)``. Production passes ``None`` and uses the real
    registry.
    """
    registry = scrapers if scrapers is not None else _registry()
    directory = Path(report_dir) if report_dir is not None else DEFAULT_REPORT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    day = today or datetime.now(UTC).date().isoformat()
    report_path = directory / f"{day}.json"

    previous_report = _previous_report(directory, report_path)
    results: list[dict[str, Any]] = []
    alarms = 0
    for bookmaker in _books_for(books, registry):
        scraper_class = registry.get(bookmaker)
        if scraper_class is None:
            result: dict[str, Any] = {
                "bookmaker": bookmaker,
                "matches": 0,
                "markets": {},
                "error": "no scraper registered",
                "duration_seconds": 0.0,
            }
        else:
            result = await probe_one(bookmaker, scraper_class, live, timeout)
        previous = _previous_book(previous_report, bookmaker)
        result["reasons"] = compare(previous, result)
        result["new_market_types"] = new_market_types(previous, result)
        alarms += len(result["reasons"])
        results.append(result)

    report = {
        "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
        "live": live,
        "alarms": alarms,
        "previous": previous_report.get("generated_at") if previous_report else None,
        "books": results,
    }
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report, report_path


def summarise(report: dict[str, Any], report_path: Path) -> str:
    lines = [
        f"live canary {report['generated_at']} (live={report['live']}), "
        f"{report['alarms']} alarm(s): {report_path}"
    ]
    for entry in report["books"]:
        status = "ERROR" if entry["error"] else f"{entry['matches']} matches"
        markets = ", ".join(
            f"{name}={count}" for name, count in sorted(entry["markets"].items())
        )
        line = f"  {entry['bookmaker']:20} {status:<18} {entry['duration_seconds']:>6.1f}s"
        if markets:
            line += f"  [{markets}]"
        lines.append(line)
        for reason in entry["reasons"]:
            lines.append(f"    ! {reason}")
        if entry["new_market_types"]:
            lines.append(f"    + new: {', '.join(entry['new_market_types'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", default="all", help="comma-separated ids, or all")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--report-dir", default=str(DEFAULT_REPORT_DIR), help="where the dated JSON goes"
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when any reason fires"
    )
    args = parser.parse_args(argv)

    report, report_path = asyncio.run(
        run(
            args.books,
            live=args.live,
            timeout=args.timeout,
            report_dir=Path(args.report_dir),
        )
    )
    print(summarise(report, report_path))
    if args.strict and report["alarms"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
