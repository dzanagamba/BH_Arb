"""Unattended scan loop.

Off by default. When `AUTO_SCAN_PREMATCH_MINUTES` or `AUTO_SCAN_LIVE_MINUTES` is
positive, the FastAPI lifespan starts one loop per feed. A loop never overlaps a
manual scan: it asks `start_scan_if_idle` first and skips the tick when the feed
is already busy. Exceptions are logged and the loop continues; a scheduler that
dies on one bad scrape is worse than no scheduler.
"""

from __future__ import annotations

import asyncio
import logging

from server.api import run_scan, start_scan_if_idle

logger = logging.getLogger(__name__)


async def scan_loop(mode: str, minutes: int) -> None:
    if minutes <= 0:
        return
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            if await start_scan_if_idle(mode):
                await run_scan(mode, True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled %s scan failed; the loop will try again", mode)
