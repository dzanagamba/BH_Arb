"""SR3-3: one Chromium per scan, a fresh context per book.

Every browser-backed scrape used to start its own Playwright and Chromium. A
scan of the three browser books therefore launched three browsers, and wwin's
two code paths each launched one. This module owns a per-scan pool instead:

* the first ``context()`` launches Playwright + Chromium through
  ``launch_browser()`` (the same stealth configuration as before);
* every book gets a **fresh context** on that browser, so cookies and cache
  never cross books;
* the browser is recycled after ``BROWSER_MAX_PAGES`` contexts or
  ``BROWSER_MAX_AGE_SECONDS``; a browser that reports disconnected is replaced
  at the next acquisition. A hung browser that still reports connected is
  replaced when the age limit is reached.

``run_scan`` opens the pool around the scraping gather, so a scan shares one
browser. A standalone ``scrape()`` (a probe, a capture script, a test) has no
active pool and gets a private one-shot pool from ``browser_session()``.

The deep-link verifier does not use the scan pool: it calls ``launch_browser()``
directly, keeping its own isolated context so a scraper session can never
influence a link check.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from config.settings import BROWSER_MAX_AGE_SECONDS, BROWSER_MAX_PAGES
from server.observability import metrics

logger = logging.getLogger(__name__)

Launch = Callable[[], Awaitable[tuple[Any, Any, Any]]]

_ACTIVE: ContextVar[BrowserPool | None] = ContextVar("bh_browser_pool", default=None)


class BrowserPool:
    """A lazily launched Chromium, recycled on a page/age budget.

    ``launch`` and ``clock`` are seams for tests: the default launcher is
    ``scrapers.base.launch_browser`` and the default clock is
    ``time.monotonic``. The pool never raises from ``aclose()``; a close
    failure is logged because the scan is already ending.
    """

    def __init__(
        self,
        *,
        max_pages: int | None = None,
        max_age_seconds: float | None = None,
        launch: Launch | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_pages = BROWSER_MAX_PAGES if max_pages is None else max_pages
        self._max_age = (
            BROWSER_MAX_AGE_SECONDS if max_age_seconds is None else max_age_seconds
        )
        self._launch = launch
        self._clock = clock
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._first_context: Any | None = None
        self._started = 0.0
        self._pages = 0

    async def _start(self) -> None:
        launch: Launch
        if self._launch is None:
            from scrapers.base import launch_browser

            launch = launch_browser
        else:
            launch = self._launch
        self._playwright, self._browser, self._first_context = await launch()
        self._started = self._clock()
        self._pages = 0

    async def _stop(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = self._first_context = None
        if browser is not None:
            try:
                await browser.close()
            except Exception as exc:  # noqa: BLE001 - the scan is ending
                logger.warning("browser close failed: %s", exc)
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception as exc:  # noqa: BLE001 - the scan is ending
                logger.warning("playwright stop failed: %s", exc)

    def _recycle_reason(self) -> str | None:
        """Why the current browser should be replaced, if it should be."""
        if self._browser is None:
            return None
        connected = getattr(self._browser, "is_connected", None)
        if callable(connected) and not connected():
            return "crash"
        if self._pages >= self._max_pages:
            return "pages"
        if self._clock() - self._started >= self._max_age:
            return "age"
        return None

    @asynccontextmanager
    async def context(self) -> AsyncIterator[Any]:
        """A fresh context; the pool's browser is launched or recycled first."""
        reason = self._recycle_reason()
        if reason is not None:
            logger.info(
                "browser pool recycled (%s) after %d context(s), %.0fs",
                reason,
                self._pages,
                self._clock() - self._started,
            )
            metrics.inc("bh_browser_recycles_total", 1, reason=reason)
            await self._stop()
        if self._browser is None:
            await self._start()
        assert self._browser is not None
        if self._first_context is not None:
            context = self._first_context
            self._first_context = None
        else:
            from scrapers.base import new_context

            context = await new_context(self._browser)
        self._pages += 1
        try:
            yield context
        finally:
            close = getattr(context, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception as exc:  # noqa: BLE001 - the book already ended
                    logger.warning("browser context close failed: %s", exc)

    async def aclose(self) -> None:
        await self._stop()


def current_browser_pool() -> BrowserPool | None:
    """The pool a scan installed, or ``None`` for a standalone scrape."""
    return _ACTIVE.get()


@asynccontextmanager
async def browser_pool(
    *,
    max_pages: int | None = None,
    max_age_seconds: float | None = None,
) -> AsyncIterator[BrowserPool]:
    """Own one browser for the duration of a scan (or a sweep)."""
    pool = BrowserPool(max_pages=max_pages, max_age_seconds=max_age_seconds)
    token = _ACTIVE.set(pool)
    try:
        yield pool
    finally:
        _ACTIVE.reset(token)
        await pool.aclose()


__all__ = ["BrowserPool", "browser_pool", "current_browser_pool"]
