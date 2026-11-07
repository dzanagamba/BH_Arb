"""SR2-3: bounded retries with jitter, Retry-After and attempt accounting."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from scrapers.cost import begin_book, finish_book
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.retry import fetch_with_retry, retry_after_seconds
from scrapers.transport import policy_for


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _policy(**overrides):
    return replace(policy_for("mbet", "prematch"), **overrides)


def _sleep_recorder(delays: list[float]):
    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    return sleep


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _fetch(handler, *, policy=None, sleep=None, now=None, rand=None):
    async def scenario():
        kwargs = {
            "policy": policy or _policy(),
            "sleep": sleep or _sleep_recorder([]),
            "rand": rand or (lambda: 0.5),
        }
        if now is not None:
            kwargs["now"] = now
        async with _client(handler) as client:
            return await fetch_with_retry(
                client,
                "https://example.test/feed",
                **kwargs,
            )

    return scenario


def test_a_429_honours_retry_after_then_succeeds():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"ok": True})

    delays: list[float] = []
    response = asyncio.run(
        _fetch(handler, sleep=_sleep_recorder(delays))()
    )

    assert response.status_code == 200
    assert len(calls) == 2
    assert delays == [2.0]


def test_a_403_is_one_attempt_and_blocked():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403)

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(_fetch(handler)())

    assert caught.value.kind is ScrapeKind.BLOCKED
    assert len(calls) == 1


def test_a_challenge_page_is_blocked_on_the_first_attempt():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, headers={"cf-mitigated": "challenge"})

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(_fetch(handler)())

    assert caught.value.kind is ScrapeKind.BLOCKED
    assert len(calls) == 1


def test_a_5xx_uses_full_jitter_and_the_attempt_cap():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    delays: list[float] = []
    policy = _policy(retry_budget=3, retry_backoff_base=1.0, retry_max_backoff=8.0)

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(
            _fetch(
                handler,
                policy=policy,
                sleep=_sleep_recorder(delays),
                rand=lambda: 1.0,
            )()
        )

    assert caught.value.kind is ScrapeKind.UPSTREAM_5XX
    assert len(calls) == 3
    # full jitter with rand() == 1: 1s, then 2s.
    assert delays == [1.0, 2.0]


def test_the_total_time_budget_stops_before_the_next_attempt():
    calls = []
    clock = _Clock()
    delays: list[float] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        clock.advance(seconds)

    policy = _policy(
        retry_budget=10,
        retry_total_seconds=1.0,
        retry_backoff_base=0.5,
        retry_max_backoff=8.0,
    )

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(
            _fetch(
                handler,
                policy=policy,
                sleep=sleep,
                now=clock,
                rand=lambda: 1.0,
            )()
        )

    assert caught.value.kind is ScrapeKind.UPSTREAM_5XX
    assert len(calls) == 2
    assert delays == [0.5]


def test_retry_after_is_capped():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "999"})

    delays: list[float] = []
    policy = _policy(retry_budget=2, retry_after_cap=5.0)

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(
            _fetch(handler, policy=policy, sleep=_sleep_recorder(delays))()
        )

    assert caught.value.kind is ScrapeKind.RATE_LIMITED
    assert delays == [5.0]


def test_transport_errors_retry_then_end_as_transport():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ScrapeError) as caught:
        asyncio.run(_fetch(handler)())

    assert caught.value.kind is ScrapeKind.TRANSPORT
    assert len(calls) == 3


def test_every_attempt_is_recorded_by_the_cost_collector():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200)

    begin_book("mbet", "prematch")
    try:
        asyncio.run(_fetch(handler)())
    finally:
        record = finish_book("success")

    assert record is not None
    assert record["requests"] == 2


def test_a_successful_request_is_one_attempt_and_one_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200)

    begin_book("mbet", "prematch")
    try:
        asyncio.run(_fetch(handler)())
    finally:
        record = finish_book("success")

    assert len(calls) == 1
    assert record is not None
    assert record["requests"] == 1


def test_retry_after_seconds_understands_an_http_date():
    class Response:
        headers = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}

    # A past date is clamped to zero, not a negative sleep.
    assert retry_after_seconds(Response()) == 0.0


def test_wwin_has_no_private_retry_loop():
    source = Path("scrapers/wwin.py").read_text(encoding="utf-8")

    assert "for attempt in range" not in source
    assert "retry_call" in source
