"""Per-book health state machine (SR5-2).

``/api/health`` already carries a lot of per-book evidence: the SR2-1 scrape
kind, the SR2-6 circuit breaker, the SR4-4 drift counter and the runtime
enable toggle. This module reduces that evidence to one state an operator (or
an alert) can act on, without inventing a second source of truth:

``healthy``
    The last recorded attempt returned matches and nothing is tripping.
``degraded``
    Some evidence is unhealthy but the book is still allowed to run: an empty
    or failed last attempt, a half-open probe, an elevated failure rate, or a
    book that has not been scanned yet.
``open``
    The SR2-6 breaker is open, so scheduled scans skip the book until its
    cooldown elapses.
``blocked``
    The last attempt was refused by the site (challenge, 403, 429 folded into
    the SR2-1 ``blocked`` kind by the adapter).
``drifted``
    The last attempt was rejected by a strict wire schema (SR2-1
    ``schema_drift``); the book is missing from the scan until a human reviews
    the payload.
``disabled``
    The runtime toggle or the config disabled the book.

The function is pure: it takes the facts and returns ``(state, reason)``. The
endpoint gathers the facts, so tests do not need a running server or a scan.
"""

from __future__ import annotations

from typing import Any

from scrapers.errors import ScrapeKind, kind_for_outcome

HEALTHY = "healthy"
DEGRADED = "degraded"
OPEN = "open"
BLOCKED = "blocked"
DRIFTED = "drifted"
DISABLED = "disabled"

STATES: tuple[str, ...] = (HEALTHY, DEGRADED, OPEN, BLOCKED, DRIFTED, DISABLED)

FAILURE_RATE_DEGRADED = 0.5

# Kinds that leave the book usable in principle but not healthy this scan.
_DEGRADED_KINDS = frozenset(
    {
        ScrapeKind.EMPTY.value,
        ScrapeKind.RATE_LIMITED.value,
        ScrapeKind.TIMEOUT.value,
        ScrapeKind.TRANSPORT.value,
        ScrapeKind.UPSTREAM_5XX.value,
        ScrapeKind.PARSE_ERROR.value,
        ScrapeKind.SKIPPED.value,
    }
)


def derive_state(
    *,
    enabled: bool,
    breaker_state: str,
    last_kind: str | None,
    failure_rate: float | None = None,
    has_scan: bool = True,
) -> tuple[str, str]:
    """Return ``(state, reason)`` for one book and one feed.

    ``last_kind`` is the SR2-1 kind of the most recent attempt (``None`` when
    the scan history has no record). ``breaker_state`` is the SR2-6 snapshot
    state: ``closed``, ``open`` or ``half_open``.
    """
    if not enabled:
        return DISABLED, "disabled by config or runtime toggle"
    if last_kind == ScrapeKind.BLOCKED.value:
        return BLOCKED, "last attempt was refused by the site"
    if last_kind == ScrapeKind.SCHEMA_DRIFT.value:
        return DRIFTED, "last payload was rejected as schema drift"
    if breaker_state == "open":
        return OPEN, "circuit breaker open; scheduled scans skip the book"
    if not has_scan or last_kind is None:
        return DEGRADED, "no scan recorded yet"
    if (
        failure_rate is not None
        and failure_rate >= FAILURE_RATE_DEGRADED
        and last_kind != ScrapeKind.OK.value
    ):
        return DEGRADED, f"failure rate {failure_rate:.0%} over the recent window"
    if last_kind == ScrapeKind.OK.value:
        if failure_rate is not None and failure_rate >= FAILURE_RATE_DEGRADED:
            return DEGRADED, f"recovering; failure rate {failure_rate:.0%}"
        return HEALTHY, "last attempt returned matches"
    if breaker_state == "half_open":
        return DEGRADED, "circuit breaker half-open; one probe is allowed"
    if last_kind in _DEGRADED_KINDS:
        return DEGRADED, f"last attempt ended as {last_kind}"
    return DEGRADED, f"unrecognised last kind {last_kind}"


def build_book_health(
    mode: str,
    *,
    bookmakers: dict[str, dict[str, Any]],
    enabled: dict[str, bool],
    breakers: dict[str, dict[str, Any]],
    scan_cost: dict[str, Any] | None,
    failure_rates: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """One ``derive_state`` result per configured book for one feed.

    ``scan_cost`` is the last SR2-1/N1-3 report (``{"books": {...}}``); a book
    missing from it has no recorded attempt. Only ids, kinds, counts and
    durations are copied — never a URL or a payload.
    """
    records = (scan_cost or {}).get("books") or {}
    health: dict[str, dict[str, Any]] = {}
    for book, config in bookmakers.items():
        record = records.get(book)
        record = record if isinstance(record, dict) else {}
        raw_kind = record.get("kind")
        if not raw_kind:
            raw_kind = (
                record.get("outcome")
                and kind_for_outcome(str(record["outcome"])).value
            )
        last_kind = str(raw_kind) if raw_kind else None
        breaker = breakers.get(book) or {}
        breaker_state = str(breaker.get("state") or "closed")
        state, reason = derive_state(
            enabled=bool(enabled.get(book, bool(config.get("enabled", True)))),
            breaker_state=breaker_state,
            last_kind=last_kind,
            failure_rate=failure_rates.get(book),
            has_scan=bool(record),
        )
        health[book] = {
            "bookmaker": book,
            "mode": mode,
            "state": state,
            "reason": reason,
            "last_kind": last_kind,
            "breaker_state": breaker_state,
            "failure_rate": failure_rates.get(book),
            "matches": record.get("matches"),
            "last_scan_seconds": record.get("wall_seconds"),
            "browser_seconds": record.get("browser_seconds"),
        }
    return health


__all__ = [
    "BLOCKED",
    "DEGRADED",
    "DISABLED",
    "DRIFTED",
    "HEALTHY",
    "OPEN",
    "STATES",
    "build_book_health",
    "derive_state",
]
