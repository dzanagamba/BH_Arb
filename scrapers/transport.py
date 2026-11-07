"""Per-book HTTP transport policy and one client per book per scan (SR2-2).

Every direct-API adapter used to build its own ``httpx.AsyncClient`` with a
module-level timeout and no explicit limits. This module owns that policy:

* ``TransportPolicy`` is the frozen per-book, per-mode configuration (timeouts,
  connection limits, retry budget, rate limit and TLS verification).
* ``TransportPool`` keeps one client per ``(book, mode)`` for the life of one
  scan and closes all of them when the scan ends.
* ``transport_client()`` is the adapter seam. Inside a scan it yields the
  pool's shared client; in a standalone script or test it yields a private
  client and closes it, so no call site needs to know which case it is in.

``requests_per_second`` and ``retry_budget`` are carried here for SR2-4 and
SR2-3; this task only moves the timeouts and connection limits into the policy.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import httpx

from config.settings import VERIFY_SSL

# Existing timeout values, moved without change. SportPlus's prematch and live
# feeds have always used different caps.
_BOOK_TIMEOUTS: dict[str, dict[str, float]] = {
    "betole": {"prematch": 30.0, "live": 30.0},
    "evlbet": {"prematch": 20.0, "live": 20.0},
    "maxbet": {"prematch": 60.0, "live": 60.0},
    "mbet": {"prematch": 30.0, "live": 30.0},
    "mdshop": {"prematch": 30.0, "live": 30.0},
    "premier_kladionica": {"prematch": 60.0, "live": 60.0},
    "sportplus": {"prematch": 120.0, "live": 60.0},
}


@dataclass(frozen=True)
class TransportPolicy:
    """One book's HTTP transport rules for one feed."""

    connect_timeout: float
    read_timeout: float
    total_timeout: float
    max_connections: int = 10
    max_keepalive_connections: int = 5
    requests_per_second: float | None = None
    # Total attempts, including the first. SR2-3 reads this as the attempt cap.
    retry_budget: int = 3
    retry_total_seconds: float = 30.0
    retry_backoff_base: float = 0.5
    retry_max_backoff: float = 8.0
    retry_after_cap: float = 60.0
    verify: bool = VERIFY_SSL

    def timeout(self) -> httpx.Timeout:
        """The policy as an ``httpx.Timeout``; every phase keeps its old cap."""
        return httpx.Timeout(
            self.total_timeout,
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=self.total_timeout,
            pool=self.total_timeout,
        )

    def limits(self) -> httpx.Limits:
        """The policy as explicit ``httpx.Limits``."""
        return httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections,
        )


DEFAULT_POLICY = TransportPolicy(30.0, 30.0, 30.0)

POLICIES: dict[tuple[str, str], TransportPolicy] = {
    (book, mode): TransportPolicy(timeout, timeout, timeout)
    for book, modes in _BOOK_TIMEOUTS.items()
    for mode, timeout in modes.items()
}


def policy_for(bookmaker: str, mode: str) -> TransportPolicy:
    """Return the policy for a book/feed, with a conservative default."""
    return POLICIES.get((bookmaker, mode), DEFAULT_POLICY)


def _client(policy: TransportPolicy, **kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=policy.timeout(),
        limits=policy.limits(),
        verify=policy.verify,
        **kwargs,
    )


class TransportPool:
    """One ``AsyncClient`` per (book, mode) for one scan."""

    def __init__(self) -> None:
        self._clients: dict[tuple[str, str], httpx.AsyncClient] = {}

    def client(self, bookmaker: str, mode: str, **kwargs: Any) -> httpx.AsyncClient:
        """Return this scan's client for the book, creating it once.

        Extra keyword arguments (for example EVLBet's static headers) are used
        only when the client is created; every later request in the same scan
        shares the same client.
        """
        key = (bookmaker, mode)
        existing = self._clients.get(key)
        if existing is not None:
            return existing
        client = _client(policy_for(bookmaker, mode), **kwargs)
        self._clients[key] = client
        return client

    @property
    def books(self) -> frozenset[tuple[str, str]]:
        """The (book, mode) pairs that have a client in this scan."""
        return frozenset(self._clients)

    async def aclose(self) -> None:
        """Close every client this pool created."""
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()


_ACTIVE_POOL: ContextVar[TransportPool | None] = ContextVar(
    "bh_transport_pool", default=None
)
_ACTIVE_POLICY: ContextVar[TransportPolicy | None] = ContextVar(
    "bh_transport_policy", default=None
)


def current_policy() -> TransportPolicy | None:
    """The policy of the client the current task is using, if it is in a block."""
    return _ACTIVE_POLICY.get()


@asynccontextmanager
async def transport_pool() -> AsyncIterator[TransportPool]:
    """Open a scan's transport, then close every client even on failure."""
    pool = TransportPool()
    token = _ACTIVE_POOL.set(pool)
    try:
        yield pool
    finally:
        _ACTIVE_POOL.reset(token)
        await pool.aclose()


@asynccontextmanager
async def transport_client(
    bookmaker: str, mode: str, **kwargs: Any
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield the scan's shared client, or a private client outside a scan."""
    policy = policy_for(bookmaker, mode)
    pool = _ACTIVE_POOL.get()
    token = _ACTIVE_POLICY.set(policy)
    try:
        if pool is not None:
            yield pool.client(bookmaker, mode, **kwargs)
            return
        async with _client(policy, **kwargs) as client:
            yield client
    finally:
        _ACTIVE_POLICY.reset(token)


__all__ = [
    "DEFAULT_POLICY",
    "POLICIES",
    "TransportPolicy",
    "TransportPool",
    "current_policy",
    "policy_for",
    "transport_client",
    "transport_pool",
]
