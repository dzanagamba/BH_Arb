"""Per-book scan cost instrumentation (N1-3).

The scanner answers "what does a full scan cost?" with measured wall time,
browser-open time, request count, response bytes and an outcome per book. The
collector is a context variable so the shared HTTP/browser helpers can add to
the book currently being scraped without threading a parameter through every
parser.

Only counts, durations, sizes and outcome labels are kept. URLs, headers,
cookies and payloads are deliberately not part of the record.
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

OUTCOMES = ("success", "empty", "parse_error", "blocked", "skipped")

_BLOCKED_MARKERS = (
    "403",
    "429",
    "access denied",
    "blocked",
    "captcha",
    "challenge",
    "cloudflare",
    "forbidden",
    "net::err",
    "timeout",
)


@dataclass
class BookCost:
    """Mutable collector for one book's attempt in one scan."""

    bookmaker: str
    mode: str
    uses_browser: bool
    started_at: datetime
    started_monotonic: float
    browser_seconds: float | None = None
    requests: int = 0
    bytes_known: int = 0
    bytes_seen: bool = False
    bytes_unavailable: bool = False
    outcome: str = "unknown"
    note: str = ""
    matches: int = 0
    markets: int = 0
    missing: list[str] = field(default_factory=list)


_current: ContextVar[BookCost | None] = ContextVar("bh_book_cost", default=None)


def begin_book(
    bookmaker: str, mode: str, *, uses_browser: bool = False
) -> Token[BookCost | None]:
    """Start collecting for the book the current task is scraping."""
    return _current.set(
        BookCost(
            bookmaker=bookmaker,
            mode=mode,
            uses_browser=uses_browser,
            started_at=datetime.now(UTC).replace(tzinfo=None),
            started_monotonic=time.perf_counter(),
        )
    )


def current_book() -> BookCost | None:
    return _current.get()


def record_browser_seconds(seconds: float) -> None:
    """Add one browser-open interval to the active book, if any."""
    cost = _current.get()
    if cost is None:
        return
    cost.browser_seconds = (cost.browser_seconds or 0.0) + max(0.0, seconds)


def record_request(response_bytes: int | None = None) -> None:
    """Count one HTTP request and its response size when it is measurable."""
    cost = _current.get()
    if cost is None:
        return
    cost.requests += 1
    if response_bytes is None:
        cost.bytes_unavailable = True
        return
    cost.bytes_known += max(0, int(response_bytes))
    cost.bytes_seen = True


def response_bytes(response: Any) -> int | None:
    """Body size of an httpx response, or ``None`` when it is not readable."""
    try:
        return len(response.content)
    except Exception:  # noqa: BLE001 - size is best effort
        return None


def classify_exception(exc: BaseException) -> str:
    """Map a scraper failure to ``blocked`` or ``parse_error``.

    The split is deliberately text-based and conservative: a bot wall, a 403/429
    or a timeout is ``blocked``; anything else is a parser/data failure. It never
    changes whether a book is priced.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in _BLOCKED_MARKERS):
        return "blocked"
    return "parse_error"


def finish_book(
    outcome: str,
    *,
    note: str = "",
    matches: int = 0,
    markets: int = 0,
) -> dict[str, Any] | None:
    """Close the active book and return its JSON-safe cost record."""
    cost = _current.get()
    if cost is None:
        return None
    _current.set(None)
    cost.outcome = outcome if outcome in OUTCOMES else "parse_error"
    cost.note = note
    cost.matches = max(0, int(matches))
    cost.markets = max(0, int(markets))
    cost.missing = _missing_reasons(cost)
    wall = round(max(0.0, time.perf_counter() - cost.started_monotonic), 3)
    browser = (
        round(cost.browser_seconds, 3)
        if cost.browser_seconds is not None
        else None
    )
    requests = cost.requests if cost.requests > 0 else None
    measured_bytes = cost.bytes_known if cost.bytes_seen else None
    return {
        "bookmaker": cost.bookmaker,
        "mode": cost.mode,
        "outcome": cost.outcome,
        "wall_seconds": wall,
        "browser_seconds": browser,
        "requests": requests,
        "bytes": measured_bytes,
        "matches": cost.matches,
        "markets": cost.markets,
        "missing": cost.missing,
        "note": cost.note,
        "started_at": cost.started_at.isoformat(timespec="seconds"),
    }


def _missing_reasons(cost: BookCost) -> list[str]:
    missing: list[str] = []
    if cost.outcome == "skipped":
        missing.append("browser_seconds: not attempted")
    elif cost.uses_browser:
        if cost.browser_seconds is None:
            missing.append("browser_seconds: browser open not measured")
    else:
        missing.append("browser_seconds: book does not use a browser")
    if cost.requests <= 0:
        missing.append("requests: not attempted or no request observed")
    if cost.bytes_seen is False:
        if cost.requests > 0:
            missing.append("bytes: response size unavailable")
        else:
            missing.append("bytes: not attempted")
    elif cost.bytes_unavailable:
        missing.append("bytes: some responses had no measurable size")
    return missing


def build_scan_report(
    mode: str,
    scan_time: datetime,
    books: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Summarize one scan's per-book records with explicit denominators."""
    totals: dict[str, Any] = {
        "books": len(books),
        "success": 0,
        "empty": 0,
        "parse_error": 0,
        "blocked": 0,
        "skipped": 0,
        "wall_seconds": 0.0,
        "browser_seconds": 0.0,
        "browser_seconds_measured": False,
        "requests": 0,
        "requests_measured": False,
        "bytes": 0,
        "bytes_measured": False,
        "matches": 0,
        "markets": 0,
    }
    for record in books.values():
        outcome = str(record.get("outcome") or "")
        if outcome in totals:
            totals[outcome] += 1
        totals["wall_seconds"] += float(record.get("wall_seconds") or 0.0)
        browser = record.get("browser_seconds")
        if browser is not None:
            totals["browser_seconds"] += float(browser)
            totals["browser_seconds_measured"] = True
        requests = record.get("requests")
        if requests is not None:
            totals["requests"] += int(requests)
            totals["requests_measured"] = True
        measured = record.get("bytes")
        if measured is not None:
            totals["bytes"] += int(measured)
            totals["bytes_measured"] = True
        totals["matches"] += int(record.get("matches") or 0)
        totals["markets"] += int(record.get("markets") or 0)

    totals["wall_seconds"] = round(totals["wall_seconds"], 3)
    totals["browser_seconds"] = (
        round(totals["browser_seconds"], 3)
        if totals["browser_seconds_measured"]
        else None
    )
    totals["requests"] = totals["requests"] if totals["requests_measured"] else None
    totals["bytes"] = totals["bytes"] if totals["bytes_measured"] else None
    totals["seconds_per_match"] = (
        round(totals["wall_seconds"] / totals["matches"], 4)
        if totals["matches"]
        else None
    )
    totals["requests_per_match"] = (
        round(totals["requests"] / totals["matches"], 4)
        if totals["requests"] is not None and totals["matches"]
        else None
    )
    totals["bytes_per_match"] = (
        round(totals["bytes"] / totals["matches"], 2)
        if totals["bytes"] is not None and totals["matches"]
        else None
    )
    return {
        "mode": mode,
        "scan_time": scan_time.isoformat(timespec="seconds"),
        "books": books,
        "totals": totals,
    }
