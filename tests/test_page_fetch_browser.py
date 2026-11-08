"""SR4-8a route A: Chromium's own route sees the browser adapters' API call.

Opt-in with ``BH_ARB_TEST_BROWSER=1``, like the other Chromium checks. The point
of route A is that the JSON endpoints are requested by the page, so
``context.route`` (and therefore HAR record/replay, SR4-8) covers them. This
test loads a document through a route, issues the adapter's request from inside
it, and asserts the route handler fired for both — no real network is used.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from scrapers.base import launch_browser, measured_api_get, measured_api_post

pytestmark = pytest.mark.skipif(
    os.getenv("BH_ARB_TEST_BROWSER") != "1",
    reason="needs Chromium; set BH_ARB_TEST_BROWSER=1 to run the route check",
)

ORIGIN = "https://book.example"


def test_an_in_page_fetch_is_visible_to_context_route():
    async def scenario():
        playwright, browser, context = await launch_browser()
        seen: list[str] = []
        bodies: list[object] = []

        async def handle(route):
            url = route.request.url
            seen.append(url)
            if url.endswith("/app"):
                await route.fulfill(
                    status=200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    body="<html><body>book</body></html>",
                )
                return
            bodies.append(route.request.post_data_json)
            await route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body='{"ok": true, "weekday": "subota"}',
            )

        try:
            await context.route(f"{ORIGIN}/**", handle)
            page = await context.new_page()
            await page.goto(f"{ORIGIN}/app", wait_until="domcontentloaded")

            got = await measured_api_get(
                page, f"{ORIGIN}/api/events", params={"sportId": "1"}
            )
            posted = await measured_api_post(
                page, f"{ORIGIN}/api/matches", data={"page": 2}
            )
            data = await got.json()
            return (
                seen,
                bodies,
                data,
                got.status,
                await posted.json(),
                await got.body(),
            )
        finally:
            await context.close()
            await browser.close()
            await playwright.stop()

    seen, bodies, data, status, posted, body = asyncio.run(scenario())

    # Both the document and the API call went through the route, so a HAR can
    # record and replay them (SR4-8); page.request would have bypassed it.
    assert seen == [f"{ORIGIN}/app", f"{ORIGIN}/api/events?sportId=1", f"{ORIGIN}/api/matches"]
    assert bodies == [None, {"page": 2}]
    assert status == 200
    assert data == {"ok": True, "weekday": "subota"}
    assert posted == {"ok": True, "weekday": "subota"}
    assert body == b'{"ok": true, "weekday": "subota"}'
