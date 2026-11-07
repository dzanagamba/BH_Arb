"""One outgoing rate limiter per bookmaker (SR2-4).

Before this module the only outgoing throttle was wwin's private
``Semaphore(6)``: it caps concurrency, not the rate, so fifteen day buckets
still start together. This module spaces one book's attempts at a configured
rate, whatever the adapter's concurrency is.

Kept in-house rather than adding ``aiolimiter`` (the roadmap's suggestion):
the acceptance criterion is a deterministic "N attempts at R per second take at
least N/R seconds" test, which needs a clock and sleep seam, and the project
already owns the per-book policy and per-attempt accounting this has to fit
into. The reservation model below is also stricter than a leaky bucket with
burst: no burst, so the first attempt waits one interval and every later
attempt waits for its own slot.

A limiter is per bookmaker and per event loop (``retry_call`` always runs inside
a coroutine), so a scan shares one limiter per book and a second scan reuses it:
politeness must not reset at a scan boundary. Tests get ``reset_limiters()``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from weakref import WeakKeyDictionary

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class BookRateLimiter:
    """Reserve the next start slot for one book, then wait for it.

    With ``requests_per_second = R`` every attempt waits until its slot, one
    ``1/R`` after the previous one, so ``N`` attempts always take at least
    ``N/R`` seconds. Concurrent callers (``fetch_pages`` batches, wwin's
    parallel day/bet walk) queue behind each other instead of all starting at
    once. A cancelled waiter may waste its slot; it never lets two attempts
    share one.
    """

    def __init__(
        self,
        bookmaker: str,
        requests_per_second: float,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.bookmaker = bookmaker
        self.requests_per_second = float(requests_per_second)
        self.interval = 1.0 / self.requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_at = float("-inf")
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait for this attempt's slot."""
        async with self._lock:
            now = self._clock()
            if self._next_at <= now:
                # First attempt, or the queue has drained: this one waits a
                # full interval too, so N attempts span at least N/R seconds.
                self._next_at = now + self.interval
                delay = self.interval
            else:
                slot = self._next_at
                self._next_at = slot + self.interval
                delay = slot - now
        await self._sleep(delay)

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"<BookRateLimiter({self.bookmaker!r}, "
            f"{self.requests_per_second:g}/s) at {id(self):#x}>"
        )


_LIMITERS: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, BookRateLimiter]
] = WeakKeyDictionary()


def limiter_for(
    bookmaker: str, requests_per_second: float | None
) -> BookRateLimiter | None:
    """This loop's limiter for the book, or ``None`` when the rate is disabled."""
    if not requests_per_second or requests_per_second <= 0 or not bookmaker:
        return None
    loop = asyncio.get_running_loop()
    per_loop = _LIMITERS.get(loop)
    if per_loop is None:
        per_loop = {}
        _LIMITERS[loop] = per_loop
    key = f"{bookmaker}:{requests_per_second:g}"
    limiter = per_loop.get(key)
    if limiter is None:
        limiter = BookRateLimiter(bookmaker, requests_per_second)
        per_loop[key] = limiter
    return limiter


def reset_limiters() -> None:
    """Forget every limiter; tests use it, the scanner does not."""
    _LIMITERS.clear()


__all__ = ["BookRateLimiter", "limiter_for", "reset_limiters"]
