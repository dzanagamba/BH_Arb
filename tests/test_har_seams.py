"""SR4-8: the capture/replay seams stay off unless a fixture run asks for them.

A scan must never record a HAR, never serve one, and never change the context it
gets. The capture tool turns recording on for one context; a replay test turns
routing on and aborts everything the file does not carry. These tests pin that
with fakes, so they need no Chromium.
"""

from __future__ import annotations

import asyncio
from typing import Any

from scrapers import base
from scrapers.browser_pool import BrowserPool, browser_pool


class FakeContext:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.closed = False
        self.har_routes: list[tuple[str, str]] = []
        self.scripts: list[str] = []
        self.routes: list[str] = []

    async def route_from_har(self, path: str, *, not_found: str = "abort") -> None:
        self.har_routes.append((path, not_found))

    async def add_init_script(self, script: str) -> None:
        self.scripts.append(script)

    async def route(self, pattern: str, handler: Any) -> None:
        self.routes.append(pattern)

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.kwargs: list[dict[str, Any]] = []

    def is_connected(self) -> bool:
        return True

    async def new_context(self, **kwargs: Any) -> FakeContext:
        self.kwargs.append(kwargs)
        context = FakeContext(self)
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        pass


class FakePlaywright:
    async def stop(self) -> None:
        pass


def _fake_launch(recorded: list[dict[str, Any]]):
    async def launch(**kwargs: Any):
        recorded.append(kwargs)
        browser = FakeBrowser()
        return FakePlaywright(), browser, await browser.new_context(**kwargs)

    return launch


def _one_browser(browser: FakeBrowser):
    async def launch():
        return FakePlaywright(), browser, await browser.new_context()

    return launch


def test_new_context_only_records_a_har_when_asked():
    browser = FakeBrowser()

    asyncio.run(base.new_context(browser, record_har_path="/tmp/x.har"))
    asyncio.run(base.new_context(browser))

    assert browser.kwargs[0]["record_har_path"] == "/tmp/x.har"
    assert browser.kwargs[0]["record_har_content"] == "embed"
    assert browser.kwargs[1]["record_har_path"] is None
    assert browser.kwargs[1]["record_har_content"] is None


def test_a_replay_context_serves_the_file_and_aborts_the_rest():
    browser = FakeBrowser()

    async def scenario() -> FakeContext:
        pool = BrowserPool(launch=_one_browser(browser), har_path="/tmp/x.har")
        async with pool.context() as context:
            return context

    context = asyncio.run(scenario())

    assert context.har_routes == [("/tmp/x.har", "abort")]


def test_a_scan_records_nothing_and_routes_nothing(monkeypatch):
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(base, "launch_browser", _fake_launch(recorded))

    async def scenario() -> FakeContext:
        async with browser_pool() as pool:
            async with pool.context() as context:
                return context

    context = asyncio.run(scenario())

    assert context.har_routes == []
    assert recorded == [{}]


def test_the_capture_tool_turns_recording_on_for_the_book(monkeypatch):
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(base, "launch_browser", _fake_launch(recorded))

    async def scenario() -> FakeContext:
        async with browser_pool(record_har_path="/tmp/out.har") as pool:
            async with pool.context() as context:
                return context

    context = asyncio.run(scenario())

    assert recorded == [{"record_har_path": "/tmp/out.har"}]
    assert context.har_routes == []
