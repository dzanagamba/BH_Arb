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

from config.settings import (
    MAINTENANCE_ENABLED,
    MAINTENANCE_INTERVAL_HOURS,
    MAINTENANCE_STARTUP_DELAY_SECONDS,
)
from server.api import live_status, run_scan, scan_status, start_scan_if_idle
from server.maintenance import run_maintenance

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


async def maintenance_loop(
    *,
    interval_hours: float | None = None,
    startup_delay_seconds: float | None = None,
) -> None:
    """Run bounded retention once a day, off the scan path.

    The loop skips a tick while either feed is scanning, and the runner itself
    refuses to overlap a scan write through the process-wide guard. A failure
    is logged and retried on the next tick: maintenance must never stop the
    scheduler or a scan.
    """
    if not MAINTENANCE_ENABLED:
        return
    interval = (
        MAINTENANCE_INTERVAL_HOURS if interval_hours is None else interval_hours
    )
    if interval <= 0:
        return
    delay = (
        MAINTENANCE_STARTUP_DELAY_SECONDS
        if startup_delay_seconds is None
        else startup_delay_seconds
    )
    await asyncio.sleep(max(0.0, delay))
    while True:
        try:
            busy = scan_status.is_scanning or live_status.is_scanning
            if not busy:
                report = await asyncio.to_thread(
                    run_maintenance,
                    vacuum=True,
                    scan_active=lambda: (
                        scan_status.is_scanning or live_status.is_scanning
                    ),
                )
                if report.get("ok"):
                    logger.info(
                        "Maintenance finished: pruned=%s paper=%s vacuumed=%s",
                        report.get("pruned"),
                        report.get("paper"),
                        report.get("vacuumed"),
                    )
                else:
                    logger.info("Maintenance skipped: %s", report.get("skipped"))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Maintenance failed; the loop will try again")
        await asyncio.sleep(interval * 3600)
