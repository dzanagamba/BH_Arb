"""Capture the scrubbed HAR fixtures the browser books replay (SR4-8).

    python scripts/capture_har.py --books admiralbet,wwin
    python scripts/capture_har.py --books all --scan-time 2026-11-08T17:30:00+00:00

For each book it records a live HAR through the real adapter and browser pool,
keeps the page document plus that book's API calls (everything else is dropped),
scrubs cookies and authorization headers, writes ``tests/fixtures/har/<book>.har.gz``
with a ``<book>.meta.json`` sidecar, and then replays the new file offline
through the same adapter so the sidecar records the verified output.

A HAR is a transport recording, not a market fixture: it is never used to price
anything, and a replay is opt-in (``BH_ARB_TEST_BROWSER=1``) because it needs
Chromium.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.bookmakers import BROWSER_BOOKMAKERS  # noqa: E402
from scrapers import har_fixtures  # noqa: E402
from scrapers.browser_pool import browser_pool  # noqa: E402
from server.api import SCRAPERS  # noqa: E402


def _scan_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC).replace(second=0, microsecond=0)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _books(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return sorted(BROWSER_BOOKMAKERS)
    return [book.strip() for book in value.split(",") if book.strip()]


async def capture_one(
    book: str,
    scan_time: datetime,
    *,
    out_dir: Path,
    raw_dir: Path,
) -> dict[str, Any]:
    raw_path = raw_dir / f"{book}.har"
    if raw_path.exists():
        raw_path.unlink()

    started = time.monotonic()
    adapter = SCRAPERS.adapter(book)
    if adapter is None:
        raise SystemExit(f"{book}: no adapter registered")
    async with browser_pool(record_har_path=str(raw_path)):
        live_matches = await adapter().scrape(live=False, scan_time=scan_time)
    capture_seconds = round(time.monotonic() - started, 1)

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    trimmed = har_fixtures.trim(
        raw, book=book, max_offers=har_fixtures.MAX_REPLAY_OFFERS.get(book)
    )
    fixture = har_fixtures.write_fixture(trimmed, book, out_dir)

    # Replay the new file offline through the same adapter, so the sidecar's
    # expected output is measured, not assumed.
    plain = raw_dir / f"{book}-replay.har"
    plain.write_bytes(har_fixtures.to_json_bytes(trimmed))
    started = time.monotonic()
    async with browser_pool(har_path=str(plain)):
        replay_matches = await adapter().scrape(live=False, scan_time=scan_time)
    replay_seconds = round(time.monotonic() - started, 1)
    plain.unlink(missing_ok=True)
    if not replay_matches:
        raise SystemExit(f"{book}: the new HAR replayed zero matches")
    replay = {
        "matches": len(replay_matches),
        "markets": sum(len(match.markets) for match in replay_matches),
    }
    recorded_at = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    meta = har_fixtures.write_meta(
        book,
        scan_time=scan_time.isoformat(),
        recorded_at=recorded_at,
        entries=len(trimmed["log"]["entries"]),
        replay=replay,
        directory=out_dir,
    )
    raw_path.unlink(missing_ok=True)
    return {
        "bookmaker": book,
        "capture_seconds": capture_seconds,
        "capture_matches": len(live_matches),
        "replay_seconds": replay_seconds,
        "replay": replay,
        "entries": len(trimmed["log"]["entries"]),
        "fixture": str(fixture.relative_to(REPO_ROOT)),
        "fixture_kb": round(fixture.stat().st_size / 1000, 1),
        "meta": str(meta.relative_to(REPO_ROOT)),
    }


async def run(
    books: list[str], scan_time: datetime, out_dir: Path, raw_dir: Path | None
) -> int:
    reports = []
    if raw_dir is None:
        with tempfile.TemporaryDirectory(prefix="bh-har-") as tmp:
            return await run(books, scan_time, out_dir, Path(tmp))
    for book in books:
        reports.append(
            await capture_one(book, scan_time, out_dir=out_dir, raw_dir=raw_dir)
        )
        print(json.dumps(reports[-1], sort_keys=True), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", default="all", help="comma-separated ids, or all")
    parser.add_argument(
        "--scan-time",
        help="the ISO time every request is built from (recorded in the sidecar)",
    )
    parser.add_argument("--out-dir", type=Path, default=har_fixtures.HAR_DIR)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        help="where the unscrubbed capture is written (never committed)",
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        run(
            _books(args.books),
            _scan_time(args.scan_time),
            args.out_dir,
            args.raw_dir,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
