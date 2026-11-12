"""One shared scrape-outcome taxonomy (SR2-1).

Every way a book's scrape can end is classified here, once. The scan, health,
metrics and (from SR2-2 onward) the retry/breaker policy read the same ``kind``.
Classification is structural — exception type, HTTP status and challenge
headers — never a substring search of an error message.

The legacy ``outcome`` field stays on the scan-cost record: ``ok`` maps to
``success`` and the new transport kinds keep the old ``blocked``/``parse_error``
bucket so existing health fields and dashboards keep working.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import httpx
import pydantic
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class ScrapeKind(StrEnum):
    """The outcome of one book's scrape attempt."""

    OK = "ok"
    EMPTY = "empty"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    UPSTREAM_5XX = "upstream_5xx"
    PARSE_ERROR = "parse_error"
    SCHEMA_DRIFT = "schema_drift"
    # Not a scrape result: the book was disabled or backing off. It lives in the
    # same enum so every per-book record carries one kind.
    SKIPPED = "skipped"


class ScrapeError(Exception):
    """A scrape failure whose kind is already classified.

    ``retry_call`` raises this once the policy is spent; ``run_scan`` can then
    record the exact kind without re-inspecting a response or an error text.
    """

    def __init__(self, kind: ScrapeKind, message: str = "") -> None:
        self.kind = kind
        super().__init__(message or kind.value)


class EmptyBodyError(Exception):
    """A 2xx response whose body is empty or whitespace only.

    The feed answered but delivered nothing — a dropped or truncated response,
    not a shape change. ``retry_call`` classifies it ``transport``, so it is
    retried inside the book's existing attempt budget, and a book that never
    sends a body fails closed as an unreadable feed instead of raising a false
    schema-drift alarm (SR8-5).
    """


# The historical outcome labels. ``blocked`` used to absorb every timeout and
# 429 (the text classifier's markers); keeping that mapping means an existing
# failure-rate dashboard does not change meaning with this task.
_KIND_OUTCOMES: dict[ScrapeKind, str] = {
    ScrapeKind.OK: "success",
    ScrapeKind.EMPTY: "empty",
    ScrapeKind.BLOCKED: "blocked",
    ScrapeKind.RATE_LIMITED: "blocked",
    ScrapeKind.TIMEOUT: "blocked",
    ScrapeKind.TRANSPORT: "parse_error",
    ScrapeKind.UPSTREAM_5XX: "parse_error",
    ScrapeKind.PARSE_ERROR: "parse_error",
    ScrapeKind.SCHEMA_DRIFT: "parse_error",
    ScrapeKind.SKIPPED: "skipped",
}

_OUTCOME_KINDS: dict[str, ScrapeKind] = {
    "success": ScrapeKind.OK,
    "empty": ScrapeKind.EMPTY,
    "blocked": ScrapeKind.BLOCKED,
    "parse_error": ScrapeKind.PARSE_ERROR,
    "error": ScrapeKind.PARSE_ERROR,
    "skipped": ScrapeKind.SKIPPED,
}

_NON_FAILURE_KINDS = frozenset(
    {ScrapeKind.OK, ScrapeKind.EMPTY, ScrapeKind.SKIPPED}
)


def legacy_outcome(kind: ScrapeKind | str) -> str:
    """Map a kind onto the historical ``outcome`` label."""
    try:
        return _KIND_OUTCOMES[ScrapeKind(kind)]
    except (ValueError, KeyError):
        return "parse_error"


def kind_for_outcome(outcome: str) -> ScrapeKind:
    """Recover a kind for a record written before this taxonomy existed."""
    return _OUTCOME_KINDS.get(str(outcome), ScrapeKind.PARSE_ERROR)


def is_failure_kind(kind: ScrapeKind | str) -> bool:
    """True for a kind that counts against a book's health."""
    try:
        return ScrapeKind(kind) not in _NON_FAILURE_KINDS
    except ValueError:
        return True


def _status_of(response: Any) -> int:
    status: Any = getattr(response, "status_code", None)
    if status is None:
        status = getattr(response, "status", 0)
    try:
        return int(status) if status is not None else 0
    except (TypeError, ValueError):
        return 0


def header_value(headers: Any, name: str) -> str:
    """Case-insensitive header lookup for httpx, Playwright and test dicts."""
    try:
        items = headers.items()
    except AttributeError:
        return ""
    for key, value in items:
        if str(key).lower() == name:
            return str(value).lower()
    return ""


def classify_response(response: Any) -> ScrapeKind:
    """Classify an httpx or Playwright response by status and challenge header.

    A Cloudflare challenge can be served with 200 or 503, so the
    ``cf-mitigated: challenge`` header is checked before the status. Other
    unexpected 4xx statuses are ``transport``: the feed could not be fetched,
    but the endpoint was not an auth wall or an upstream outage.
    """
    status = _status_of(response)
    if header_value(getattr(response, "headers", None) or {}, "cf-mitigated") == "challenge":
        return ScrapeKind.BLOCKED
    if 200 <= status < 400:
        return ScrapeKind.OK
    if status == 429:
        return ScrapeKind.RATE_LIMITED
    if status in {401, 403, 407, 451}:
        return ScrapeKind.BLOCKED
    if 500 <= status < 600:
        return ScrapeKind.UPSTREAM_5XX
    return ScrapeKind.TRANSPORT


def classify_exception(exc: BaseException) -> ScrapeKind:
    """Classify a scraper exception by type, never by its message text."""
    if isinstance(exc, ScrapeError):
        return exc.kind
    if isinstance(exc, PlaywrightTimeoutError):
        return ScrapeKind.TIMEOUT
    if isinstance(exc, httpx.TimeoutException):
        return ScrapeKind.TIMEOUT
    if isinstance(exc, TimeoutError):
        return ScrapeKind.TIMEOUT
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_response(exc.response)
    if isinstance(exc, httpx.HTTPError):
        return ScrapeKind.TRANSPORT
    if isinstance(exc, EmptyBodyError):
        return ScrapeKind.TRANSPORT
    if isinstance(exc, PlaywrightError):
        return ScrapeKind.TRANSPORT
    if isinstance(exc, pydantic.ValidationError):
        return ScrapeKind.SCHEMA_DRIFT
    return ScrapeKind.PARSE_ERROR


def classify_scrape(
    matches: list[Any] | None = None,
    *,
    error: BaseException | None = None,
) -> ScrapeKind:
    """Classify one completed attempt: an error wins, otherwise rows or empty."""
    if error is not None:
        return classify_exception(error)
    return ScrapeKind.OK if matches else ScrapeKind.EMPTY


__all__ = [
    "EmptyBodyError",
    "ScrapeError",
    "ScrapeKind",
    "classify_exception",
    "classify_response",
    "classify_scrape",
    "header_value",
    "is_failure_kind",
    "kind_for_outcome",
    "legacy_outcome",
]
