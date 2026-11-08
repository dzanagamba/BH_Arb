"""SR3-2: the browser route must not retain a task per intercepted request.

Playwright's Python client keeps completed ``asyncio.Task`` objects for routed
requests until the Playwright connection closes (playwright-python#3121). That
was a CPython 3.14 asyncio bug, fixed upstream in python/cpython#152585 and
closed on 2026-07-02; this project runs Python 3.11/3.12, where it never
applied. The production ``launch_browser()`` still installs
``context.route("**/*")`` to abort images, media and fonts, so the invariant is
worth a pin: loading several image-heavy pages through that route must not grow
the number of retained, completed tasks.

The test is opt-in with the other Chromium checks:

    BH_ARB_TEST_BROWSER=1 python -m pytest tests/test_browser_route_leak.py
"""

from __future__ import annotations

import asyncio
import gc
import os

import pytest

from scrapers.base import launch_browser

pytestmark = pytest.mark.skipif(
    os.getenv("BH_ARB_TEST_BROWSER") != "1",
    reason="needs Chromium; set BH_ARB_TEST_BROWSER=1 to run the leak check",
)

# A leak would add roughly two retained tasks per intercepted request; these
# pages carry 40 images each, so a leak is hundreds of tasks. The bound keeps
# ordinary transient tasks from failing the test while catching that growth.
MAX_TASK_GROWTH = 50
IMAGES_PER_PAGE = 40
PAGES = 6


def _done_tasks() -> int:
    """Completed asyncio tasks still reachable, as in the upstream repro."""
    gc.collect()
    return sum(
        1 for obj in gc.get_objects() if isinstance(obj, asyncio.Task) and obj.done()
    )


def _page(index: int) -> str:
    images = "".join(
        f'<img src="http://x-{index}-{i}.example/i.png">' for i in range(IMAGES_PER_PAGE)
    )
    return f"data:text/html,<html><body>{images}</body></html>"


def test_the_browser_route_retains_no_task_per_intercepted_request():
    async def scenario() -> tuple[int, int]:
        playwright, browser, context = await launch_browser()
        try:
            page = await context.new_page()
            await page.goto(_page(0), wait_until="load", timeout=10_000)
            await asyncio.sleep(0.2)
            baseline = _done_tasks()
            for index in range(1, PAGES + 1):
                await page.goto(_page(index), wait_until="load", timeout=10_000)
            await asyncio.sleep(0.3)
            return baseline, _done_tasks()
        finally:
            await browser.close()
            await playwright.stop()

    baseline, after = asyncio.run(scenario())

    assert after - baseline <= MAX_TASK_GROWTH, (
        f"{after - baseline} completed tasks retained for "
        f"{PAGES} pages x {IMAGES_PER_PAGE} blocked requests "
        f"(baseline {baseline}, after {after})"
    )
