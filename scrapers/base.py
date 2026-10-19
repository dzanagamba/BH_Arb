"""
Base Scraper Class with Network Payload Interception Architecture

Intercepts XHR/Fetch JSON requests as the Playwright browser navigates
the bookmaker SPAs. Data is parsed directly from API responses.
"""

import asyncio
import logging
from abc import ABC, abstractmethod

import httpx
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    async_playwright,
)

from config.settings import (
    BLOCKED_URL_FRAGMENTS,
    HEADLESS,
    NAVIGATION_TIMEOUT_MS,
    SCRAPE_TIMEOUT_MS,
    SLOW_MO,
    USER_AGENT,
)
from models.schemas import Match

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
        slow_mo=SLOW_MO,
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


class BaseScraper(ABC):
    """Abstract Base Class for all bookmaker scrapers using JSON response interception."""

    def __init__(self):
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.captured_json_payloads: list[dict] = []

    @property
    @abstractmethod
    def bookmaker_name(self) -> str: ...

    @property
    @abstractmethod
    def bookmaker_id(self) -> str: ...

    @property
    @abstractmethod
    def url(self) -> str: ...

    @property
    def extra_blocked_fragments(self) -> list[str]:
        return []

    async def scrape(self) -> list[Match]:
        """Main scraping orchestrator."""
        self.captured_json_payloads = []

        try:
            await self.start_browser()
            assert self.context is not None
            page = await self.context.new_page()
            page.set_default_timeout(SCRAPE_TIMEOUT_MS)
            page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)

            page.on("response", self._handle_response)

            logger.info(f"[{self.bookmaker_name}] Navigating to {self.url}")
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            except Exception as nav_e:
                logger.warning(f"[{self.bookmaker_name}] Initial navigation warning: {nav_e}")

            await self._wait_for_data(page)

            logger.info(
                f"[{self.bookmaker_name}] Captured {len(self.captured_json_payloads)} "
                f"JSON payloads. Extracting matches..."
            )

            raw_matches = await self.extract_matches(page)
            cleaned = self._post_process_matches(raw_matches)

            logger.info(
                f"[{self.bookmaker_name}] {len(raw_matches)} raw → {len(cleaned)} after filtering"
            )
            return cleaned

        except Exception as e:
            logger.error(f"[{self.bookmaker_name}] Scrape failed: {e}", exc_info=True)
            return []
        finally:
            await self.stop_browser()

    async def _handle_response(self, response: Response) -> None:
        """Playwright network response interceptor."""
        try:
            url_lower = response.url.lower()

            all_blocked = BLOCKED_URL_FRAGMENTS + self.extra_blocked_fragments
            if any(frag in url_lower for frag in all_blocked):
                return

            content_type = response.headers.get("content-type", "").lower()
            is_json = any(k in content_type for k in ["json", "text/plain", "javascript"])
            is_api_path = any(k in url_lower for k in ["api", "offer", "match", "event", "sport", "restapi", "betting"])

            if not (is_json or is_api_path):
                return

            try:
                data = await response.json()
            except Exception:
                return

            if not isinstance(data, dict | list):
                return

            if isinstance(data, list) and len(data) == 0:
                return
            if isinstance(data, dict) and len(data) == 0:
                return

            self.captured_json_payloads.append({
                "url": response.url,
                "data": data,
            })
            logger.debug(
                f"[{self.bookmaker_name}] Captured JSON ({len(str(data))} chars) "
                f"from: {response.url[:100]}"
            )

        except Exception as e:
            logger.debug(f"[{self.bookmaker_name}] Response handler error: {e}")

    async def start_browser(self) -> None:
        """Launch Playwright browser with stealth settings."""
        self.playwright, self.browser, self.context = await launch_browser()

    async def stop_browser(self) -> None:
        """Clean up browser resources."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.debug(f"[{self.bookmaker_name}] Browser cleanup error: {e}")

    @abstractmethod
    async def extract_matches(self, page: Page) -> list[Match]: ...

    async def _progressive_scroll(self, page: Page) -> None:
        """Scroll through both the window and inner virtual scroll containers to trigger lazy loading."""
        try:
            # 1. Scroll window
            for i in range(1, 6):
                await page.evaluate(f"window.scrollTo(0, {i * 1000})")
                await asyncio.sleep(0.5)

            # 2. Scroll inner scroll containers (div.__view, div.__panel, etc.)
            await page.evaluate("""() => {
                const scrollables = document.querySelectorAll('div.__view, div.__panel, .virtual-scroll, .scroll-container, main');
                for (const el of scrollables) {
                    if (el.scrollHeight > el.clientHeight + 100) {
                        el.scrollTop += 2000;
                    }
                }
            }""")
            await asyncio.sleep(0.8)

            # 3. Click any 'Prikaži više' or 'Učitaj još' button if present
            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, a, .load-more'));
                for (const b of btns) {
                    const txt = (b.innerText || '').toLowerCase();
                    if (txt.includes('prikaži više') || txt.includes('učitaj još') || txt.includes('svi mečevi') || txt.includes('load more')) {
                        b.click();
                    }
                }
            }""")
            await asyncio.sleep(0.5)

            await page.evaluate("window.scrollTo(0, 0)")

        except Exception as e:
            logger.debug(f"[{self.bookmaker_name}] Scroll error: {e}")

    async def _wait_for_data(self, page: Page) -> None:
        """Wait strategy for SPA data loading."""
        if HEADLESS:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                await asyncio.sleep(4)
            await self._progressive_scroll(page)
            await asyncio.sleep(2)
        else:
            logger.info(f"[{self.bookmaker_name}] Browser open. Solve CAPTCHA if shown. Waiting 15s for data...")
            for _ in range(5):
                await asyncio.sleep(3)
                await self._progressive_scroll(page)

    def _post_process_matches(self, matches: list[Match]) -> list[Match]:
        """Deduplicate and sanitize matches."""
        valid_matches = []
        seen = set()

        for match in matches:
            if not match.home_team or not match.away_team:
                continue

            if match.home_team.strip().lower() == match.away_team.strip().lower():
                continue

            if not match.has_markets():
                continue

            kickoff_key = match.kickoff.date().isoformat() if match.kickoff else ""
            league_key = (match.league or "").strip().lower()
            dedup_key = (
                f"{match.home_team.strip().lower()}|{match.away_team.strip().lower()}"
                f"|{league_key}|{kickoff_key}|{(match.match_code or '').strip()}"
            )
            if dedup_key in seen:
                continue

            seen.add(dedup_key)
            valid_matches.append(match)

        return valid_matches
