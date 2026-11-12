"""Bounded retries with jitter, ``Retry-After`` and attempt accounting (SR2-3).

Hand-rolled rather than adding ``stamina``: the project already owns attempt
accounting (``scrapers.cost``), the per-book policy (``scrapers.transport``) and
the outcome taxonomy (``scrapers.errors``), and every one of those has to see
each attempt. The policy stays small, explicit and fully tested.

The rules:

* 403/401/407/451 and challenge pages are one attempt and ``blocked``;
* 429 waits for ``Retry-After`` (capped) and counts against the budget;
* 5xx, timeout and transport failures retry with full jitter;
* the attempt cap and total-time budget come from the book's
  :class:`~scrapers.transport.TransportPolicy`;
* every attempt is recorded unless the caller already accounts for it.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from scrapers.cost import record_request, response_bytes
from scrapers.errors import (
    EmptyBodyError,
    ScrapeError,
    ScrapeKind,
    classify_exception,
    classify_response,
    header_value,
)
from scrapers.ratelimit import limiter_for
from scrapers.transport import DEFAULT_POLICY, TransportPolicy, current_policy
from server.observability import metrics

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
Random = Callable[[], float]

_RETRYABLE = frozenset(
    {
        ScrapeKind.TIMEOUT,
        ScrapeKind.TRANSPORT,
        ScrapeKind.UPSTREAM_5XX,
        ScrapeKind.RATE_LIMITED,
    }
)


def _status(response: Any) -> int:
    raw = getattr(response, "status_code", None)
    if raw is None:
        raw = getattr(response, "status", 0)
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def retry_after_seconds(response: Any) -> float | None:
    """The wait a ``Retry-After`` header asks for; ``retry_call`` applies the cap."""
    raw = header_value(getattr(response, "headers", None) or {}, "retry-after")
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, seconds)


def _jittered_delay(attempt: int, policy: TransportPolicy, rand: Random) -> float:
    ceiling = min(
        policy.retry_max_backoff,
        policy.retry_backoff_base * (2 ** (attempt - 1)),
    )
    return max(0.0, rand() * ceiling)


async def retry_call(
    send: Callable[[], Awaitable[Any]],
    *,
    policy: TransportPolicy | None = None,
    label: str = "request",
    account: bool = True,
    sleep: Sleep = asyncio.sleep,
    now: Clock = time.monotonic,
    rand: Random = random.random,
) -> Any:
    """Run ``send`` until it returns an OK response or the policy is spent.

    Returns the first response classified ``ok``. Raises
    :class:`~scrapers.errors.ScrapeError` carrying the final kind when the
    attempt cap or the total-time budget is reached, or immediately for a
    non-retryable kind such as ``blocked``. Every attempt — the first one and
    each retry — waits for its book's rate-limit slot first.
    """
    active = policy or current_policy() or DEFAULT_POLICY
    attempts = max(1, active.retry_budget)
    limiter = limiter_for(active.bookmaker, active.requests_per_second)
    started = now()
    kind = ScrapeKind.TRANSPORT
    detail = "no attempt made"

    for attempt in range(1, attempts + 1):
        if attempt > 1 and now() - started >= active.retry_total_seconds:
            raise ScrapeError(
                kind, f"{label}: {detail} after {attempt - 1} attempt(s)"
            )

        retry_after: float | None = None
        attempt_started = now()

        def _record_attempt(
            status: str | None = None,
            *,
            attempt: int = attempt,
            started: float = attempt_started,
        ) -> None:
            """One attempt, its latency, and the retry when it is not the first."""
            metrics.inc("bh_scraper_attempts_total", 1, book=active.bookmaker)
            metrics.observe(
                "bh_scraper_attempt_seconds",
                now() - started,
                book=active.bookmaker,
            )
            if attempt > 1:
                metrics.inc("bh_scraper_retries_total", 1, book=active.bookmaker)
            if status is not None:
                metrics.inc(
                    "bh_http_status_total",
                    1,
                    book=active.bookmaker,
                    status=status,
                )

        try:
            if limiter is None:
                response = await send()
            else:
                async with limiter:
                    response = await send()
        except ScrapeError:
            _record_attempt()
            raise
        except Exception as exc:  # noqa: BLE001 - classified, then retried or raised
            _record_attempt()
            if account:
                record_request(None)
            kind = classify_exception(exc)
            if kind not in _RETRYABLE:
                raise
            detail = f"{type(exc).__name__}: {exc}"
        else:
            _record_attempt(str(_status(response)))
            if account:
                record_request(response_bytes(response))
            kind = classify_response(response)
            if kind is ScrapeKind.OK:
                return response
            detail = f"HTTP {_status(response)}"
            if kind is not ScrapeKind.RATE_LIMITED and kind not in _RETRYABLE:
                raise ScrapeError(kind, f"{label}: {detail}")
            if kind is ScrapeKind.RATE_LIMITED:
                retry_after = retry_after_seconds(response)

        remaining = active.retry_total_seconds - (now() - started)
        if attempt >= attempts or remaining <= 0:
            raise ScrapeError(
                kind, f"{label}: {detail} after {attempt} attempt(s)"
            )
        delay = (
            retry_after
            if retry_after is not None
            else _jittered_delay(attempt, active, rand)
        )
        delay = min(delay, active.retry_after_cap, remaining)
        if delay >= remaining:
            raise ScrapeError(
                kind, f"{label}: {detail} after {attempt} attempt(s); budget spent"
            )
        logger.warning(
            "%s: %s (attempt %d/%d), retrying in %.2fs",
            label,
            detail,
            attempt,
            attempts,
            delay,
        )
        await sleep(max(0.0, delay))

    raise ScrapeError(kind, f"{label}: {detail} after {attempts} attempt(s)")


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict | None = None,
    params: dict | None = None,
    *,
    method: str = "GET",
    content: bytes | str | None = None,
    json: Any | None = None,
    policy: TransportPolicy | None = None,
    account: bool = True,
    require_body: bool = False,
    sleep: Sleep = asyncio.sleep,
    now: Clock = time.monotonic,
    rand: Random = random.random,
) -> httpx.Response:
    """The httpx adapter over :func:`retry_call`.

    ``method``/``content``/``json`` exist for the Premier JSON-RPC read; every
    call in this project is a read-only odds query, so POST retries are safe.

    ``require_body`` treats a 2xx response whose body is empty or whitespace
    only as an :class:`~scrapers.errors.EmptyBodyError`: the site answered but
    delivered nothing, so ``retry_call`` spends the attempt budget it already
    has on it (SR8-5). The returned response is always one that carried bytes.
    """

    async def send() -> httpx.Response:
        response = await client.request(
            method,
            url,
            headers=headers,
            params=params,
            content=content,
            json=json,
        )
        if require_body and classify_response(response) is ScrapeKind.OK:
            body = getattr(response, "content", b"") or b""
            if not bytes(body).strip():
                raise EmptyBodyError(
                    f"HTTP {getattr(response, 'status_code', '?')} with an empty body"
                )
        return response

    return await retry_call(
        send,
        policy=policy,
        label=url,
        account=account,
        sleep=sleep,
        now=now,
        rand=rand,
    )


__all__ = ["fetch_with_retry", "retry_after_seconds", "retry_call"]
