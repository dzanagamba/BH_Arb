"""SR3-3: one Chromium per scan, a fresh context per book, with recycling.

A scan of the three browser books used to launch three browsers. The pool
launches one, hands every book its own context, and replaces the browser on a
page/age budget or when it reports disconnected. These tests use a fake
launcher, so no Chromium is needed and the launch count is the assertion.
"""

from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Error as PlaywrightError

from scrapers.browser_pool import BrowserPool, browser_pool, current_browser_pool
from scrapers.errors import ScrapeKind, classify_exception


class _FakePlaywright:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakeContext:
    def __init__(self, browser: _FakeBrowser, index: int) -> None:
        self.browser = browser
        self.index = index
        self.closed = False
        self.scripts: list[str] = []
        self.routes: list[str] = []

    async def add_init_script(self, script: str) -> None:
        self.scripts.append(script)

    async def route(self, pattern: str, handler: Any) -> None:
        self.routes.append(pattern)

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, launch_index: int) -> None:
        self.launch_index = launch_index
        self.closed = False
        self.crashed = False
        self.contexts: list[_FakeContext] = []

    def is_connected(self) -> bool:
        return not self.crashed

    async def new_context(self, **kwargs: Any) -> _FakeContext:
        context = _FakeContext(self, len(self.contexts))
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        self.closed = True


class _Launcher:
    """A fake ``launch_browser`` that records every launch."""

    def __init__(self) -> None:
        self.calls: list[tuple[_FakePlaywright, _FakeBrowser, _FakeContext]] = []

    async def __call__(self) -> tuple[_FakePlaywright, _FakeBrowser, _FakeContext]:
        playwright = _FakePlaywright()
        browser = _FakeBrowser(len(self.calls))
        context = await browser.new_context()
        self.calls.append((playwright, browser, context))
        return playwright, browser, context

    @property
    def launches(self) -> int:
        return len(self.calls)


def _pool(launcher: _Launcher, **kwargs: Any) -> BrowserPool:
    return BrowserPool(launch=launcher, **kwargs)


def test_one_browser_serves_every_book_with_a_fresh_context():
    launcher = _Launcher()
    pool = _pool(launcher)

    async def scenario():
        async with pool.context() as first:
            pass
        async with pool.context() as second:
            pass
        return first, second

    first, second = asyncio.run(scenario())

    assert launcher.launches == 1
    assert first is launcher.calls[0][2]
    assert second is not first
    assert first.closed and second.closed
    assert second.scripts and second.routes == ["**/*"]


def test_the_browser_is_recycled_after_the_page_budget():
    launcher = _Launcher()
    pool = _pool(launcher, max_pages=2)

    async def scenario():
        for _ in range(3):
            async with pool.context():
                pass
        await pool.aclose()

    asyncio.run(scenario())

    assert launcher.launches == 2
    assert launcher.calls[0][1].closed is True


def test_the_browser_is_recycled_after_the_age_budget():
    launcher = _Launcher()
    now = [0.0]
    pool = _pool(launcher, max_age_seconds=10, max_pages=100, clock=lambda: now[0])

    async def scenario():
        async with pool.context():
            pass
        now[0] = 11.0
        async with pool.context():
            pass
        await pool.aclose()

    asyncio.run(scenario())

    assert launcher.launches == 2


def test_a_crashed_browser_is_replaced_on_the_next_context():
    launcher = _Launcher()
    pool = _pool(launcher)

    async def scenario():
        async with pool.context():
            pass
        launcher.calls[0][1].crashed = True
        async with pool.context():
            pass
        await pool.aclose()

    asyncio.run(scenario())

    assert launcher.launches == 2
    assert launcher.calls[0][1].closed is True


def test_the_pool_closes_both_the_browser_and_playwright():
    launcher = _Launcher()
    pool = _pool(launcher)

    async def scenario():
        async with pool.context():
            pass
        await pool.aclose()

    asyncio.run(scenario())

    playwright, browser, _ = launcher.calls[0]
    assert browser.closed is True
    assert playwright.stopped is True


def test_the_scan_pool_is_visible_to_the_scrape_and_cleared_after():

    async def scenario() -> tuple[bool, bool]:
        async with browser_pool() as pool:
            inside = current_browser_pool() is pool
        after = current_browser_pool() is None
        return inside, after

    inside, after = asyncio.run(scenario())

    assert inside is True
    assert after is True


def test_a_browser_crash_is_a_transport_failure_not_an_ok_scrape():
    assert classify_exception(PlaywrightError("Target closed")) is ScrapeKind.TRANSPORT


def test_a_context_close_failure_does_not_break_the_pool():
    class ExplodingContext(_FakeContext):
        async def close(self) -> None:
            raise RuntimeError("already gone")

    class ExplodingLauncher:
        async def __call__(self):
            browser = _FakeBrowser(0)
            return _FakePlaywright(), browser, ExplodingContext(browser, 0)

    pool = BrowserPool(launch=ExplodingLauncher())

    async def scenario():
        async with pool.context():
            pass
        await pool.aclose()

    asyncio.run(scenario())
