"""Scan-cost history aggregation (N1-3).

The scraper wrapper writes one bounded per-scan, per-book record. This module
turns that history into the per-book table an operator reads, with explicit scan
and book denominators. It never reads a URL, header or payload: only the counts
and durations the wrapper recorded.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from server.timeutil import naive_utc, utcnow

FAILURE_OUTCOMES = frozenset({"parse_error", "blocked"})


def load_history(path: str | Path) -> list[dict[str, Any]]:
    """Read the bounded scan-cost history; a missing/bad file is empty."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    history = payload.get("history") if isinstance(payload, dict) else payload
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _scan_time(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("scan_time")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return naive_utc(parsed)
    return parsed


def _add(
    target: dict[str, Any], record: dict[str, Any], field: str, measured: str
) -> None:
    value = record.get(field)
    if value is None:
        return
    target[field] += float(value)
    target[measured] = True


def _finalize(entry: dict[str, Any]) -> None:
    entry["wall_seconds"] = round(entry["wall_seconds"], 3)
    entry["browser_seconds"] = (
        round(entry["browser_seconds"], 3)
        if entry["browser_seconds_measured"]
        else None
    )
    entry["requests"] = entry["requests"] if entry["requests_measured"] else None
    entry["bytes"] = entry["bytes"] if entry["bytes_measured"] else None
    attempts = entry["scans"]
    entry["failure_rate"] = (
        round((entry["parse_error"] + entry["blocked"]) / attempts, 4)
        if attempts
        else None
    )
    matches = entry["matches"]
    entry["seconds_per_match"] = (
        round(entry["wall_seconds"] / matches, 4) if matches else None
    )
    entry["requests_per_match"] = (
        round(entry["requests"] / matches, 4)
        if entry["requests"] is not None and matches
        else None
    )
    entry["bytes_per_match"] = (
        round(entry["bytes"] / matches, 2)
        if entry["bytes"] is not None and matches
        else None
    )


def _empty_bucket() -> dict[str, Any]:
    return {
        "scans": 0,
        "success": 0,
        "empty": 0,
        "parse_error": 0,
        "blocked": 0,
        "skipped": 0,
        "wall_seconds": 0.0,
        "browser_seconds": 0.0,
        "browser_seconds_measured": False,
        "requests": 0.0,
        "requests_measured": False,
        "bytes": 0.0,
        "bytes_measured": False,
        "matches": 0,
        "markets": 0,
        "missing": [],
    }


def book_failure_rates(
    history: list[dict[str, Any]],
    mode: str,
    *,
    window: int = 20,
) -> dict[str, float]:
    """Failure rate per book over the newest ``window`` scans of one feed."""
    buckets: dict[str, dict[str, int]] = {}
    seen = 0
    for entry in history:
        if entry.get("mode") != mode:
            continue
        seen += 1
        if seen > window:
            break
        for book, record in (entry.get("books") or {}).items():
            if not isinstance(record, dict):
                continue
            bucket = buckets.setdefault(book, {"attempts": 0, "failures": 0})
            bucket["attempts"] += 1
            if record.get("outcome") in FAILURE_OUTCOMES:
                bucket["failures"] += 1
    return {
        book: round(bucket["failures"] / bucket["attempts"], 4)
        for book, bucket in buckets.items()
        if bucket["attempts"]
    }


def aggregate(
    history: list[dict[str, Any]],
    *,
    days: int,
    mode: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate the per-book table over a date window."""
    current = now or utcnow()
    cutoff = current - timedelta(days=max(0, days))
    per_book: dict[str, dict[str, Any]] = {}
    scans_by_mode: dict[str, int] = {}
    scans = 0
    for entry in history:
        stamp = _scan_time(entry)
        if stamp is None or stamp < cutoff:
            continue
        entry_mode = str(entry.get("mode") or "")
        if mode and entry_mode != mode:
            continue
        scans += 1
        scans_by_mode[entry_mode] = scans_by_mode.get(entry_mode, 0) + 1
        for book, record in (entry.get("books") or {}).items():
            if not isinstance(record, dict):
                continue
            bucket = per_book.setdefault(book, _empty_bucket())
            bucket["scans"] += 1
            outcome = str(record.get("outcome") or "")
            if outcome in bucket:
                bucket[outcome] += 1
            _add(bucket, record, "wall_seconds", "wall_seconds_measured")
            _add(bucket, record, "browser_seconds", "browser_seconds_measured")
            _add(bucket, record, "requests", "requests_measured")
            _add(bucket, record, "bytes", "bytes_measured")
            bucket["matches"] += int(record.get("matches") or 0)
            bucket["markets"] += int(record.get("markets") or 0)
            for reason in record.get("missing") or []:
                if reason not in bucket["missing"]:
                    bucket["missing"].append(str(reason))

    for bucket in per_book.values():
        _finalize(bucket)

    totals = _empty_bucket()
    for bucket in per_book.values():
        totals["scans"] = scans
        for key in ("success", "empty", "parse_error", "blocked", "skipped"):
            totals[key] += bucket[key]
        totals["wall_seconds"] += bucket["wall_seconds"]
        if bucket["browser_seconds"] is not None:
            totals["browser_seconds"] += bucket["browser_seconds"]
            totals["browser_seconds_measured"] = True
        if bucket["requests"] is not None:
            totals["requests"] += bucket["requests"]
            totals["requests_measured"] = True
        if bucket["bytes"] is not None:
            totals["bytes"] += bucket["bytes"]
            totals["bytes_measured"] = True
        totals["matches"] += bucket["matches"]
        totals["markets"] += bucket["markets"]
    totals["scans"] = scans
    _finalize(totals)
    totals["books"] = len(per_book)
    totals["scans_by_mode"] = dict(sorted(scans_by_mode.items()))
    return {
        "days": days,
        "mode": mode or "all",
        "scans": scans,
        "books": len(per_book),
        "scans_by_mode": dict(sorted(scans_by_mode.items())),
        "per_book": dict(sorted(per_book.items())),
        "totals": totals,
    }
