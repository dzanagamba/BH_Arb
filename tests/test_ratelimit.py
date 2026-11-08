"""SR2-4: one outgoing rate limiter per bookmaker."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx

from config.settings import SCRAPER_BOOK_RATES, SCRAPER_REQUESTS_PER_SECOND
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.ratelimit import BookRateLimiter, limiter_for, reset_limiters
from scrapers.retry import fetch_with_retry
from scrapers.transport import (
    DEFAULT_POLICY,
    POLICIES,
    current_policy,
    policy_for,
    transport_client,
)

ALL_BOOKS = {
    "admiralbet",
    "betole",
    "evlbet",
    "maxbet",
    "mbet",
    "mdshop",
    "mozzartbet",
    "premier_kladionica",
    "sportplus",
    "wwin",
}


class FakeClock:
    """A clock the fake sleep moves; no test waits real time."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _fake_sleep(clock: FakeClock, waits: list[float] | None = None):
    async def sleep(seconds: float) -> None:
        if waits is not None:
            waits.append(seconds)
        clock.value += seconds
        await asyncio.sleep(0)

    return sleep


def test_n_attempts_take_at_least_n_over_r_seconds():
    async def scenario() -> tuple[float, list[float]]:
        clock = FakeClock()
        waits: list[float] = []
        limiter = BookRateLimiter(
            "mbet", 4.0, clock=clock, sleep=_fake_sleep(clock, waits)
        )
        for _ in range(5):
            await limiter.acquire()
        return clock.value, waits

    elapsed, waits = asyncio.run(scenario())

    assert elapsed >= 5 / 4.0
    assert waits == [0.25] * 5


def test_concurrent_attempts_queue_instead_of_bursting():
    async def scenario() -> float:
        clock = FakeClock()
        limiter = BookRateLimiter(
            "wwin", 10.0, clock=clock, sleep=_fake_sleep(clock)
        )

        async def attempt() -> None:
            await limiter.acquire()

        await asyncio.gather(*(attempt() for _ in range(6)))
        return clock.value

    # Six attempts at 10/s span at least 0.6 s, whatever the concurrency.
    assert asyncio.run(scenario()) >= 6 / 10.0


def test_the_limiter_is_per_book_and_per_event_loop():
    async def scenario():
        mbet = limiter_for("mbet", 5.0)
        assert mbet is limiter_for("mbet", 5.0)
        assert mbet is not limiter_for("mdshop", 5.0)
        # A different rate is a different limiter, so a policy change is visible.
        assert limiter_for("mbet", 2.0) is not mbet
        return mbet

    first = asyncio.run(scenario())
    second = asyncio.run(scenario())
    # A new loop (a new process or a test) must not reuse a limiter.
    assert first is not second


def test_a_missing_or_zero_rate_disables_the_limiter():
    async def scenario():
        assert limiter_for("mbet", None) is None
        assert limiter_for("mbet", 0) is None
        assert limiter_for("", 5.0) is None

    asyncio.run(scenario())


def test_every_book_carries_its_rate_and_a_book_name():
    assert {book for book, _mode in POLICIES} == ALL_BOOKS
    for (book, _mode), policy in POLICIES.items():
        assert policy.bookmaker == book
        expected = SCRAPER_BOOK_RATES.get(book, SCRAPER_REQUESTS_PER_SECOND)
        assert policy.requests_per_second == expected
    # SR7-2: the operator raised Mozzartbet to 60/s; other books keep 5/s.
    assert POLICIES[("mozzartbet", "prematch")].requests_per_second == 60.0
    assert POLICIES[("mbet", "prematch")].requests_per_second == 5.0
    # The fallback policy is for code that is not a book: no limiter.
    assert DEFAULT_POLICY.bookmaker == ""
    assert DEFAULT_POLICY.requests_per_second is None


def test_a_transport_client_exposes_its_book_policy():
    async def scenario() -> tuple[str, float | None]:
        async with transport_client("mbet", "prematch"):
            policy = current_policy()
            assert policy is not None
            return policy.bookmaker, policy.requests_per_second

    assert asyncio.run(scenario()) == ("mbet", 5.0)


def test_retry_acquires_one_slot_per_attempt_including_retries(monkeypatch):
    acquisitions: list[tuple[str, float | None]] = []

    class CountingLimiter:
        def __init__(self, book: str, rate: float | None) -> None:
            self.book = book
            self.rate = rate

        async def acquire(self) -> None:
            acquisitions.append((self.book, self.rate))

        async def __aenter__(self):
            await self.acquire()

        async def __aexit__(self, *exc_info) -> None:
            return None

    def fake_limiter_for(bookmaker, requests_per_second):
        if not bookmaker:
            return None
        return CountingLimiter(bookmaker, requests_per_second)

    monkeypatch.setattr("scrapers.retry.limiter_for", fake_limiter_for)

    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    async def sleep(_seconds: float) -> None:
        return None

    async def scenario():
        policy = replace(policy_for("mbet", "prematch"), requests_per_second=5.0)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await fetch_with_retry(
                client, "https://example.test/feed", policy=policy, sleep=sleep
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert len(calls) == 3
    assert acquisitions == [("mbet", 5.0)] * 3


def test_a_blocked_attempt_is_not_retried_but_still_takes_its_slot(monkeypatch):
    acquisitions: list[float] = []

    class CountingLimiter:
        async def acquire(self) -> None:
            acquisitions.append(1.0)

        async def __aenter__(self):
            await self.acquire()

        async def __aexit__(self, *exc_info) -> None:
            return None

    monkeypatch.setattr(
        "scrapers.retry.limiter_for", lambda *_args: CountingLimiter()
    )

    def handler(request):
        return httpx.Response(403)

    async def scenario():
        policy = replace(policy_for("mbet", "prematch"), requests_per_second=5.0)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            await fetch_with_retry(
                client,
                "https://example.test/feed",
                policy=policy,
                sleep=lambda _seconds: asyncio.sleep(0),
            )

    try:
        asyncio.run(scenario())
    except ScrapeError as exc:
        assert exc.kind is ScrapeKind.BLOCKED
    else:  # pragma: no cover - the assertion above is the point
        raise AssertionError("a 403 must raise blocked")
    assert len(acquisitions) == 1


def test_reset_limiters_forgets_every_limiter():
    async def scenario():
        first = limiter_for("mbet", 5.0)
        reset_limiters()
        return first, limiter_for("mbet", 5.0)

    first, second = asyncio.run(scenario())
    assert first is not second
