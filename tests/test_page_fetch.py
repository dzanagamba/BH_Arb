"""SR4-8a route A: browser API calls are issued by the page, not ``page.request``.

WHAT THESE TESTS PROVE
----------------------
``measured_api_get``/``measured_api_post`` run ``fetch`` inside the loaded
document and hand the adapters the same response surface they used before
(``status``, ``headers``, ``body()``, ``json()``, ``content``), so the two
browser adapters and their parsers are unchanged while the request becomes
visible to ``context.route`` and HAR record/replay — the point of route A.
The tests pin the request shape (method, encoded query, headers, JSON body for a
dict, a string body unchanged), the body round-trip (empty, non-ASCII), byte
accounting, the Python-side timeout that classifies as ``timeout``, a page error
that classifies as ``transport``, and a blocked status that reaches
``retry_call`` once.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
A fake page cannot prove Chromium actually fetches; the opt-in
``tests/test_page_fetch_browser.py`` proves route interception with a real
browser, and the SR4-8a live probe proves the three bookmaker endpoints still
answer. Nothing here changes pricing, which still needs verified groups.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import pytest
from playwright.async_api import Error as PlaywrightError

from scrapers import base
from scrapers.base import (
    PAGE_FETCH_TIMEOUT_SECONDS,
    PageResponse,
    measured_api_get,
    measured_api_post,
)
from scrapers.errors import ScrapeError, ScrapeKind, classify_exception, classify_response
from scrapers.retry import retry_call
from scrapers.transport import TransportPolicy


def _reply(
    body: bytes,
    status: int = 200,
    headers: dict[str, str] | None = None,
    url: str = "https://book.example/api",
) -> dict[str, Any]:
    return {
        "status": status,
        "url": url,
        "headers": headers if headers is not None else {"content-type": "application/json"},
        "body": base64.b64encode(body).decode("ascii"),
    }


class FakePage:
    """A page whose ``evaluate`` returns canned replies and records the call."""

    def __init__(self, replies: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
        self.replies = list(replies or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error = kwargs.get("error")
        self.delay = float(kwargs.get("delay") or 0.0)

    async def evaluate(self, script: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((script, payload))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        if not self.replies:
            raise AssertionError("FakePage has no reply left")
        return self.replies.pop(0)

    @property
    def payload(self) -> dict[str, Any]:
        assert len(self.calls) == 1
        return self.calls[0][1]


def test_a_get_runs_fetch_inside_the_page():
    payload = {"ok": True, "name": "Ćirović"}
    page = FakePage([_reply(json.dumps(payload, ensure_ascii=False).encode())])

    response = asyncio.run(
        measured_api_get(
            page,
            "https://book.example/api",
            headers={"Accept": "application/json", "Referer": "https://book.example/"},
            params={"sportId": "1", "isLive": "false"},
        )
    )

    assert page.payload["method"] == "GET"
    assert page.payload["url"] == "https://book.example/api?sportId=1&isLive=false"
    assert page.payload["headers"] == {
        "Accept": "application/json",
        "Referer": "https://book.example/",
    }
    assert page.payload["body"] is None
    # Cookies and the browser's own Cloudflare clearance go with it.
    assert page.payload["credentials"] == "include"
    # The script is a function page.evaluate can run in the document.
    assert page.calls[0][0].lstrip().startswith("async (request)")
    assert "fetch(" in page.calls[0][0]

    assert isinstance(response, PageResponse)
    assert response.status == 200
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert asyncio.run(response.json()) == payload
    expected = json.dumps(payload, ensure_ascii=False)
    assert asyncio.run(response.text()) == expected
    assert asyncio.run(response.body()) == expected.encode()


def test_a_dict_post_is_sent_as_json_and_a_string_body_is_unchanged():
    page = FakePage([_reply(b"{}"), _reply(b"{}")])

    asyncio.run(
        measured_api_post(
            page,
            "https://book.example/betting/matches",
            data={"date": "all_days", "sportId": 1},
            headers={"Accept": "application/json"},
        )
    )
    body, headers = page.payload["body"], page.payload["headers"]
    assert json.loads(body) == {"date": "all_days", "sportId": 1}
    # Playwright set application/json for a dict; the in-page path must too.
    assert headers["Content-Type"] == "application/json"
    assert page.payload["method"] == "POST"

    asyncio.run(
        measured_api_post(
            page,
            "https://book.example/betting/match/42",
            data="{}",
            headers={"Content-Type": "application/json"},
        )
    )
    assert page.calls[1][1]["body"] == "{}"
    assert page.calls[1][1]["headers"] == {"Content-Type": "application/json"}


def test_the_body_size_is_counted_once(monkeypatch):
    recorded: list[int | None] = []
    monkeypatch.setattr(base, "record_request", recorded.append)
    page = FakePage([_reply("ć".encode() * 10)])

    asyncio.run(measured_api_get(page, "https://book.example/api"))

    assert recorded == [len("ć".encode() * 10)]


def test_an_empty_body_is_empty_and_not_json():
    page = FakePage([_reply(b"")])

    response = asyncio.run(measured_api_get(page, "https://book.example/api"))

    assert asyncio.run(response.body()) == b""
    with pytest.raises(ValueError):
        asyncio.run(response.json())


def test_a_slow_fetch_is_a_python_timeout(monkeypatch):
    page = FakePage([_reply(b"{}")], delay=1.0)

    with pytest.raises(TimeoutError) as caught:
        asyncio.run(
            measured_api_get(page, "https://book.example/api", timeout_seconds=0.01)
        )

    assert classify_exception(caught.value) is ScrapeKind.TIMEOUT
    assert PAGE_FETCH_TIMEOUT_SECONDS == 30.0


def test_a_page_error_is_transport():
    page = FakePage([_reply(b"{}")], error=PlaywrightError("Failed to fetch"))

    with pytest.raises(PlaywrightError) as caught:
        asyncio.run(measured_api_get(page, "https://book.example/api"))

    assert classify_exception(caught.value) is ScrapeKind.TRANSPORT


def test_a_blocked_status_reaches_retry_call_once():
    page = FakePage([_reply(b"blocked", status=403)])
    policy = TransportPolicy(
        connect_timeout=1.0,
        read_timeout=1.0,
        total_timeout=1.0,
        requests_per_second=None,
        retry_backoff_base=0.0,
    )

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(
            retry_call(
                lambda: measured_api_get(page, "https://book.example/api"),
                policy=policy,
                label="probe",
                account=False,
            )
        )

    assert caught.value.kind is ScrapeKind.BLOCKED
    assert len(page.calls) == 1


def test_a_503_is_retried_and_the_ok_body_returned():
    page = FakePage([_reply(b"{}", status=503), _reply(b'{"ok": true}')])
    policy = TransportPolicy(
        connect_timeout=1.0,
        read_timeout=1.0,
        total_timeout=5.0,
        requests_per_second=None,
        retry_backoff_base=0.0,
    )

    response = asyncio.run(
        retry_call(
            lambda: measured_api_get(page, "https://book.example/api"),
            policy=policy,
            label="probe",
            account=False,
        )
    )

    assert len(page.calls) == 2
    assert asyncio.run(response.json()) == {"ok": True}


def test_a_challenge_header_is_blocked_not_ok():
    response = PageResponse(
        "https://book.example/api",
        200,
        {"cf-mitigated": "challenge"},
        b"<html>challenge</html>",
    )

    assert classify_response(response) is ScrapeKind.BLOCKED


def test_no_adapter_calls_page_request():
    """Route A only holds if every browser adapter goes through the page."""
    offenders = []
    for path in (Path(__file__).resolve().parents[1] / "scrapers").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "request"
                and isinstance(node.value, ast.Name)
                and node.value.id == "page"
            ):
                offenders.append(path.name)
                break

    assert not offenders, offenders
