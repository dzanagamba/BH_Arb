"""One circuit breaker per book and feed, fed by the SR2-1 kinds (SR2-6).

The only breaker before this module was the scheduled-scan backoff in
``server/api.py``: after three failures of any kind it skipped a book for
``2**n * interval`` minutes, capped. It could not tell a site refusing us from
our own parse bug, so a parser change could bench a healthy book for an hour and
a 403 was retried just as patiently as a timeout.

This breaker is small and in-house (``aiobreaker`` is abandoned, ``pybreaker``
is sync-only):

* ``closed`` — attempts allowed.
* ``open`` — attempts refused until the cooldown ends.
* ``half-open`` — exactly one probe is allowed; its outcome closes or re-opens.

Which kind opens it, and how fast:

* ``blocked`` and ``rate_limited`` — the site refusing us: open on the first
  one, with twice the cooldown of an ordinary failure.
* ``empty``, ``timeout``, ``transport``, ``upstream_5xx`` — soft failures: open
  after ``failure_threshold`` consecutive ones.
* ``parse_error``, ``schema_drift``, ``skipped`` — neutral: our parser or our
  own skip is not the site refusing us, so they neither open nor reset it.

Every consecutive open doubles the cooldown up to a cap; any ``ok`` resets the
breaker to ``closed``. State is in-process only, exactly like the backoff it
replaces, so a restart starts every book closed.

One breaker per ``(mode, book)``: a book's prematch and live endpoints are
different feeds, and blocking one says nothing about the other. The registry is
per process; tests use :func:`reset_breakers`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from scrapers.errors import ScrapeKind

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"
STATES = (CLOSED, OPEN, HALF_OPEN)

Clock = Callable[[], float]

# The site refusing us: open immediately and stay open longer.
_HARD_KINDS = frozenset({ScrapeKind.BLOCKED, ScrapeKind.RATE_LIMITED})
# The feed is failing without refusing us.
_SOFT_KINDS = frozenset(
    {
        ScrapeKind.EMPTY,
        ScrapeKind.TIMEOUT,
        ScrapeKind.TRANSPORT,
        ScrapeKind.UPSTREAM_5XX,
    }
)


class BookCircuitBreaker:
    """Consecutive-failure breaker for one book's feed."""

    def __init__(
        self,
        mode: str,
        bookmaker: str,
        *,
        clock: Clock = time.monotonic,
        failure_threshold: int = 3,
        open_seconds: float = 300.0,
        max_open_seconds: float = 3600.0,
        hard_multiplier: float = 2.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if open_seconds <= 0 or max_open_seconds <= 0 or hard_multiplier <= 0:
            raise ValueError("cooldowns and the hard multiplier must be positive")
        self.mode = mode
        self.bookmaker = bookmaker
        self.failure_threshold = failure_threshold
        self.open_seconds = float(open_seconds)
        self.max_open_seconds = float(max_open_seconds)
        self.hard_multiplier = float(hard_multiplier)
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CLOSED
        self._failures = 0
        self._opens = 0
        self._open_until = 0.0
        self._probe_taken = False
        self._last_kind = ""

    @property
    def state(self) -> str:
        """The state right now, without reserving a half-open probe."""
        with self._lock:
            if self._state == OPEN and self._clock() >= self._open_until:
                return HALF_OPEN
            return self._state

    def allow(self) -> bool:
        """Whether one attempt may start now.

        When an open cooldown has elapsed this moves to ``half-open`` and
        reserves the one probe; a concurrent caller is refused until that probe
        is recorded.
        """
        with self._lock:
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                if self._clock() < self._open_until:
                    return False
                self._state = HALF_OPEN
                self._probe_taken = True
                return True
            if self._probe_taken:
                return False
            self._probe_taken = True
            return True

    def record(self, kind: ScrapeKind) -> None:
        """Feed one completed attempt's outcome to the breaker."""
        if kind is ScrapeKind.OK:
            with self._lock:
                self._close()
            return

        with self._lock:
            self._last_kind = kind.value
            if kind not in _HARD_KINDS and kind not in _SOFT_KINDS:
                # Our parser or our own skip: not the site refusing us. The
                # probe is released so a later attempt can still probe.
                if self._state == HALF_OPEN:
                    self._probe_taken = False
                return

            hard = kind in _HARD_KINDS
            self._failures += 1
            if self._state == HALF_OPEN:
                self._trip(hard)
                return
            if hard or self._failures >= self.failure_threshold:
                self._trip(hard)

    def snapshot(self) -> dict:
        """A JSON-safe view for health, metrics and tests."""
        with self._lock:
            remaining = 0.0
            if self._state != CLOSED:
                remaining = max(0.0, self._open_until - self._clock())
            state = self._state
            if state == OPEN and remaining <= 0:
                state = HALF_OPEN
            return {
                "bookmaker": self.bookmaker,
                "state": state,
                "consecutive_failures": self._failures,
                "opens": self._opens,
                "cooldown_remaining_seconds": round(remaining, 1),
                "last_kind": self._last_kind,
            }

    def _trip(self, hard: bool) -> None:
        """Open the breaker; the caller holds the lock."""
        self._opens += 1
        multiplier = self.hard_multiplier if hard else 1.0
        seconds = self.open_seconds * multiplier * 2 ** (self._opens - 1)
        self._open_until = self._clock() + min(seconds, self.max_open_seconds)
        self._state = OPEN
        self._probe_taken = False

    def _close(self) -> None:
        """Close and forget the streak; the caller holds the lock."""
        self._state = CLOSED
        self._failures = 0
        self._opens = 0
        self._open_until = 0.0
        self._probe_taken = False


_BREAKERS: dict[tuple[str, str], BookCircuitBreaker] = {}
_BREAKERS_LOCK = threading.Lock()


def breaker_for(
    mode: str,
    bookmaker: str,
    *,
    clock: Clock | None = None,
    failure_threshold: int | None = None,
    open_seconds: float | None = None,
    max_open_seconds: float | None = None,
    hard_multiplier: float | None = None,
) -> BookCircuitBreaker:
    """This process's breaker for one feed of one book.

    The options (and ``clock``) apply only when the breaker is created; a later
    caller gets the existing instance unchanged. That is what keeps one breaker
    per book: every scan records outcomes into the object the first call made.
    """
    key = (mode, bookmaker)
    with _BREAKERS_LOCK:
        breaker = _BREAKERS.get(key)
        if breaker is None:
            breaker = BookCircuitBreaker(
                mode,
                bookmaker,
                clock=clock or time.monotonic,
                failure_threshold=(
                    3 if failure_threshold is None else failure_threshold
                ),
                open_seconds=300.0 if open_seconds is None else open_seconds,
                max_open_seconds=(
                    3600.0 if max_open_seconds is None else max_open_seconds
                ),
                hard_multiplier=2.0 if hard_multiplier is None else hard_multiplier,
            )
            _BREAKERS[key] = breaker
        return breaker


def reset_breakers() -> None:
    """Forget every breaker; tests use it, the scanner does not."""
    with _BREAKERS_LOCK:
        _BREAKERS.clear()


__all__ = [
    "CLOSED",
    "HALF_OPEN",
    "OPEN",
    "STATES",
    "BookCircuitBreaker",
    "breaker_for",
    "reset_breakers",
]
