"""SR4-8: one committed HAR replay per browser book, through the real scrape.

Opt-in with ``BH_ARB_TEST_BROWSER=1``. Each book's committed HAR is written to
a temporary file, served to a fresh context with ``route_from_har(not_found=
"abort")`` so nothing can reach the network, and the real adapter's ``scrape()``
runs against it with the sidecar's captured ``scan_time`` (the adapters build
their request URLs from it, so capture and replay ask the same questions).

The asserted counts are the sidecar's ``replay`` block, measured when the file
was captured: if an adapter starts asking a different question, a response is
missing from the HAR, the request aborts and the numbers change, so the test
fails instead of silently replaying less.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from config.bookmakers import BROWSER_BOOKMAKERS
from scrapers import har_fixtures
from scrapers.browser_pool import browser_pool
from server.api import SCRAPERS

pytestmark = pytest.mark.skipif(
    os.getenv("BH_ARB_TEST_BROWSER") != "1",
    reason="needs Chromium; set BH_ARB_TEST_BROWSER=1 to replay the HAR fixtures",
)

BOOKS = sorted(BROWSER_BOOKMAKERS)


def _replay(book: str, fixture: Path) -> tuple[int, int]:
    meta = json.loads(har_fixtures.meta_path(book).read_text(encoding="utf-8"))
    scan_time = datetime.fromisoformat(meta["scan_time"])

    async def scenario() -> list:
        adapter = SCRAPERS.adapter(book)
        assert adapter is not None
        async with browser_pool(har_path=str(fixture)):
            return await adapter().scrape(live=False, scan_time=scan_time)

    matches = asyncio.run(scenario())
    return len(matches), sum(len(match.markets) for match in matches)


@pytest.mark.parametrize("book", BOOKS)
def test_a_browser_book_replays_from_its_committed_har(book: str, tmp_path: Path):
    committed = har_fixtures.har_path(book)
    meta = json.loads(har_fixtures.meta_path(book).read_text(encoding="utf-8"))
    fixture = tmp_path / f"{book}.har"
    fixture.write_bytes(gzip.decompress(committed.read_bytes()))

    matches, markets = _replay(book, fixture)

    assert matches > 0
    assert (matches, markets) == (meta["replay"]["matches"], meta["replay"]["markets"])
