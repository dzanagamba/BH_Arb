"""
Shared scraper plumbing: the stealth Playwright launcher, the in-page fetch
the browser books call their APIs with (SR4-8a) and the pagination helper.
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from config.settings import HEADLESS, USER_AGENT
from scrapers.cost import record_browser_seconds, record_request
from scrapers.errors import ScrapeKind

logger = logging.getLogger(__name__)


async def new_context(
    browser: Browser, *, record_har_path: str | None = None
) -> BrowserContext:
    """A fresh stealth context on an existing browser (one per book).

    Every context gets its own cookies and cache; a book cannot see another
    book's session. The route and init script are the same ones the one-shot
    launcher uses.

    SR4-8: ``record_har_path`` turns on Playwright's HAR recording for the
    context (bodies embedded), which is how the scrubbed browser-book fixtures
    are captured. It is used by the capture script only; a scan never sets it.
    """
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
        record_har_path=record_har_path,
        record_har_content="embed" if record_har_path else None,
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
    return context


async def launch_browser(
    *, record_har_path: str | None = None
) -> tuple[Playwright, Browser, BrowserContext]:
    """
    Launch a stealth-configured Chromium browser + context (anti-bot flags,
    Bosnian locale/timezone, custom UA). Used by standalone scripts; a scan
    shares one browser through ``browser_session()`` instead.
    ``record_har_path`` is the SR4-8 capture seam (HAR recording, bodies
    embedded); a scan never passes it.
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
    context = await new_context(browser, record_har_path=record_har_path)
    record_browser_seconds(time.perf_counter() - started)
    return playwright, browser, context


@asynccontextmanager
async def browser_session(bookmaker: str = "") -> AsyncIterator[BrowserContext]:
    """A fresh context from the scan's shared browser, or a private one-shot.

    Inside ``browser_pool()`` every book gets its own context but the whole
    scan shares one Chromium (SR3-3). Standalone callers (a probe, a capture
    script, a test that calls ``scrape()`` directly) get a private pool that
    lives for that one call, so the old one-browser-per-scrape behaviour is
    preserved where no scan owns the lifecycle.

    SR3-4: tracing starts with the context. A session that raises writes a
    trace and a screenshot under ``cache/forensics/``; a successful one discards
    the trace. The capture never carries cookies or storage state.
    """
    from scrapers import forensics
    from scrapers.browser_pool import BrowserPool, current_browser_pool

    pool = current_browser_pool()
    private = BrowserPool() if pool is None else None
    active = pool if pool is not None else private
    assert active is not None
    try:
        async with active.context() as context:
            await forensics.begin(context)
            try:
                yield context
            except BaseException:
                pages = getattr(context, "pages", None) or []
                await forensics.capture_failure(
                    context, pages[-1] if pages else None, bookmaker
                )
                raise
            else:
                await forensics.discard(context)
    finally:
        if private is not None:
            await private.aclose()


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


#: Default wall-clock cap for one in-page fetch. It mirrors the 30 s default
#: Playwright's ``APIRequestContext`` used for ``page.request``; the adapter
#: deadline (SR2-5) still bounds a whole scrape.
PAGE_FETCH_TIMEOUT_SECONDS = 30.0

#: Body sizes go through ``btoa`` so the reply is JSON-serialisable.
_PAGE_FETCH_SCRIPT = """
async (request) => {
  const response = await fetch(request.url, {
    method: request.method,
    headers: request.headers,
    credentials: request.credentials,
    redirect: "follow",
    body: request.body,
  });
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(index, index + chunk));
  }
  const headers = {};
  response.headers.forEach((value, key) => { headers[key] = value; });
  return {status: response.status, url: response.url, headers: headers, body: btoa(binary)};
}
"""


class PageResponse:
    """The adapters' view of one in-page ``fetch`` reply.

    It is deliberately the subset of ``httpx.Response`` / Playwright
    ``APIResponse`` the adapters already used: ``status``, ``headers``,
    ``body()``, ``json()`` and ``content`` (for byte accounting). ``json()``
    raises ``ValueError`` on a body that is not JSON, exactly like the two
    libraries it replaces.
    """

    def __init__(
        self, url: str, status: int, headers: dict[str, str], content: bytes
    ) -> None:
        self.url = url
        self.status = status
        self.status_code = status
        self.headers = headers
        self.content = content

    async def body(self) -> bytes:
        return self.content

    async def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    async def json(self) -> Any:
        return json.loads(self.content)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PageResponse {self.status} {self.url} {len(self.content)}B>"


def _fetch_url(url: str, params: dict[str, Any] | str | None) -> str:
    if not params:
        return url
    query = params if isinstance(params, str) else urlencode(params, doseq=True)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def _fetch_body(
    data: Any, headers: dict[str, str]
) -> tuple[str | None, dict[str, str]]:
    """The request body and headers, mirroring Playwright's ``data`` rules.

    A dict or list is JSON-serialised and gets ``application/json`` when the
    caller did not set a content type; a string is sent unchanged. That is what
    ``page.request.post(data=...)`` did, so the endpoints keep the same request
    shape.
    """
    if data is None:
        return None, headers
    if isinstance(data, str):
        return data, headers
    if isinstance(data, bytes):
        return data.decode("utf-8"), headers
    body = json.dumps(data, allow_nan=False)
    if not any(key.lower() == "content-type" for key in headers):
        headers = {**headers, "Content-Type": "application/json"}
    return body, headers


async def _page_fetch(
    page,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | str | None = None,
    data: Any = None,
    timeout_seconds: float | None = None,
) -> PageResponse:
    """One request issued by the page itself, then measured.

    SR4-8a route A: the call runs as ``fetch`` inside the loaded document, so
    ``context.route`` and HAR record/replay cover it (``page.request`` bypassed
    both). Cookies, the page's UA and its Cloudflare clearance are the browser's
    own, and the request counts against the book's rate limiter because
    ``retry_call`` wraps this call. The timeout is enforced in Python, so an
    overrun is the shared ``timeout`` kind and not a text-matched JS error.
    """
    body, request_headers = _fetch_body(data, dict(headers or {}))
    payload = {
        "url": _fetch_url(url, params),
        "method": method,
        "headers": request_headers,
        "body": body,
        "credentials": "include",
    }
    limit = PAGE_FETCH_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    async with asyncio.timeout(limit):
        raw = await page.evaluate(_PAGE_FETCH_SCRIPT, payload)

    content = base64.b64decode(raw.get("body") or "")
    record_request(len(content))
    return PageResponse(
        url=str(raw.get("url") or payload["url"]),
        status=int(raw["status"]),
        headers={str(k).lower(): str(v) for k, v in (raw.get("headers") or {}).items()},
        content=content,
    )


async def measured_api_get(page, url: str, **kwargs) -> PageResponse:
    """A page-issued GET with request/byte accounting."""
    return await _page_fetch(page, "GET", url, **kwargs)


async def measured_api_post(page, url: str, **kwargs) -> PageResponse:
    """A page-issued POST with request/byte accounting."""
    return await _page_fetch(page, "POST", url, **kwargs)


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
