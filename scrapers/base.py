"""
Shared scraper plumbing: the stealth Playwright launcher and an httpx GET with
retries.
"""

import asyncio
import logging

import httpx
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from config.settings import HEADLESS, USER_AGENT

logger = logging.getLogger(__name__)


async def launch_browser() -> tuple[Playwright, Browser, BrowserContext]:
    """
    Launch a stealth-configured Chromium browser + context (anti-bot flags,
    Bosnian locale/timezone, custom UA). Used by all Playwright-based scrapers.
    Caller is responsible for closing the browser and stopping Playwright.
    """
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
    return playwright, browser, context


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
) -> httpx.Response | None:
    """
    Fetch a URL using httpx with exponential backoff retries for transient
    HTTP 5xx server errors and connection/timeout failures.
    """
    for attempt in range(1, max_retries + 1):
        try:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code < 500:
                return resp
            logger.warning(
                f"HTTP {resp.status_code} on {url} (attempt {attempt}/{max_retries})"
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RequestError) as e:
            logger.warning(
                f"Request failed: {e} on {url} (attempt {attempt}/{max_retries})"
            )

        if attempt < max_retries:
            await asyncio.sleep(backoff_factor * (2 ** (attempt - 1)))
    return None
