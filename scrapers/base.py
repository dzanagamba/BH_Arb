"""
Shared scraper plumbing: the stealth Playwright launcher and the pagination
helper.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from config.settings import HEADLESS, USER_AGENT
from scrapers.cost import record_browser_seconds, record_request
from scrapers.errors import ScrapeKind

logger = logging.getLogger(__name__)


async def launch_browser() -> tuple[Playwright, Browser, BrowserContext]:
    """
    Launch a stealth-configured Chromium browser + context (anti-bot flags,
    Bosnian locale/timezone, custom UA). Used by all Playwright-based scrapers.
    Caller is responsible for closing the browser and stopping Playwright.
    """
    started = time.perf_counter()
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=HEADLESS,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-size=1920,1080",
            "--start-maximized",
        ],
    )
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="bs-BA",
        timezone_id="Europe/Sarajevo",
        java_script_enabled=True,
        extra_http_headers={
            "Accept-Language": "bs-BA,bs;q=0.9,hr;q=0.8,en-US;q=0.7,en;q=0.6",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['bs-BA', 'hr', 'en-US']});
        window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
    """)
    # Odds come from JSON endpoints; images, fonts and media only slow the
    # page load that establishes the session.
    await context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in _BLOCKED_RESOURCES
        else route.continue_(),
    )
    record_browser_seconds(time.perf_counter() - started)
    return playwright, browser, context


_BLOCKED_RESOURCES = frozenset({"image", "media", "font"})


async def goto(page, url: str, **kwargs):
    """Navigate a page and count the navigation as one measured request."""
    response = await page.goto(url, **kwargs)
    body = None
    if response is not None:
        try:
            body = await response.body()
        except Exception:  # noqa: BLE001 - size is best effort
            body = None
    record_request(len(body) if body is not None else None)
    return response


async def _record_api_response(response) -> None:
    try:
        body = await response.body()
    except Exception:  # noqa: BLE001 - size is best effort
        body = None
    record_request(len(body) if body is not None else None)


async def measured_api_get(page, url: str, **kwargs):
    """Playwright ``page.request.get`` with request/byte accounting."""
    response = await page.request.get(url, **kwargs)
    await _record_api_response(response)
    return response


async def measured_api_post(page, url: str, **kwargs):
    """Playwright ``page.request.post`` with request/byte accounting."""
    response = await page.request.post(url, **kwargs)
    await _record_api_response(response)
    return response


async def settle(page, max_ms: int) -> ScrapeKind:
    """
    Wait for the page's network to go idle, but never longer than `max_ms`.
    Replaces fixed `wait_for_timeout` sleeps: returns as soon as the session
    cookies / initial requests have finished, with the old sleep as the cap.

    Returns the shared ``ScrapeKind``. A timeout or a navigation error is
    reported as such (and logged), never silently treated as a settled page.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=max_ms)
    except PlaywrightTimeoutError:
        logger.warning("Page did not reach networkidle within %d ms", max_ms)
        return ScrapeKind.TIMEOUT
    except Exception as exc:  # noqa: BLE001 - classified for the caller
        logger.warning("Page failed while waiting for networkidle: %s", exc)
        return ScrapeKind.TRANSPORT
    return ScrapeKind.OK


async def fetch_pages(
    fetch_page: Callable[[int], Awaitable[list | None]],
    page_size: int,
    max_pages: int,
    batch: int = 4,
    first_page: int = 0,
) -> list:
    """
    Fetch offset-paginated pages `batch` at a time instead of one by one.

    `fetch_page(i)` returns that page's items, or None on failure. Results are
    concatenated in page order and collection stops at the first failed, empty
    or short page, so the output equals a sequential walk (a batch may request
    a few pages past the end; those come back empty and are dropped).
    """
    items: list = []
    page = first_page
    while page < first_page + max_pages:
        end = min(page + batch, first_page + max_pages)
        results = await asyncio.gather(*(fetch_page(i) for i in range(page, end)))
        for chunk in results:
            if not chunk:
                return items
            items.extend(chunk)
            if len(chunk) < page_size:
                return items
        page = end
    return items
