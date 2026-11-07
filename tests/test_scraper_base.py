"""Shared browser helper: ``settle()`` reports a shared ``ScrapeKind``.

SR1-3 stopped the helper from swallowing navigation failures; SR2-1 absorbed its
local enum into ``scrapers.errors``. These tests pin the boundary: only a
completed network-idle wait is a success, and each failure kind is visible to
the caller.
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from scrapers.base import settle
from scrapers.errors import ScrapeKind


def _run(coro):
    return asyncio.run(coro)


class _Page:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, int]] = []

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.calls.append((state, timeout))
        if self.error is not None:
            raise self.error


def test_a_page_that_reaches_network_idle_is_settled():
    page = _Page()

    outcome = _run(settle(page, 3000))

    assert outcome is ScrapeKind.OK
    assert page.calls == [("networkidle", 3000)]


def test_a_navigation_timeout_is_a_failure_not_an_empty_success(caplog):
    page = _Page(PlaywrightTimeoutError("Timeout 3000ms exceeded."))

    with caplog.at_level(logging.WARNING):
        outcome = _run(settle(page, 3000))

    assert outcome is ScrapeKind.TIMEOUT
    assert outcome is not ScrapeKind.OK
    assert "3000 ms" in caplog.text


def test_any_other_navigation_error_is_a_failure(caplog):
    page = _Page(RuntimeError("page crashed"))

    with caplog.at_level(logging.WARNING):
        outcome = _run(settle(page, 3000))

    assert outcome is ScrapeKind.TRANSPORT
    assert outcome is not ScrapeKind.OK
    assert "page crashed" in caplog.text
