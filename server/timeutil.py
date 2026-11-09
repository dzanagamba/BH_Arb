"""The one clock for server runtime state.

Runtime timestamps are naive UTC wall clock: `datetime.now(UTC)` with the
tzinfo dropped, serialized as ISO 8601. The dashboard, the caches and SQLite all
compare and display that shape, and every module used to spell it out itself.
Two spellings drifted: some wrote microseconds, some seconds, and a couple
normalized with `astimezone` while others did not. This module is the one place
that answers "what time is it" and "what string does a store hold".

`iso_now()` is the canonical written form (seconds). A caller that needs the
microsecond form for an existing field can still call `.isoformat()` on
`utcnow()`; the point is that the clock and the timezone normalization are
shared, not that every field has one precision.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Now as a naive UTC datetime — the shape every runtime store holds."""
    return datetime.now(UTC).replace(tzinfo=None)


def naive_utc(value: datetime) -> datetime:
    """Normalize an aware or naive datetime to naive UTC, and leave naive alone."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def iso_now() -> str:
    """Naive UTC now as an ISO string with second precision."""
    return utcnow().isoformat(timespec="seconds")


def iso_seconds(value: datetime) -> str:
    """A datetime as the stored ISO string: naive UTC, second precision."""
    return naive_utc(value).isoformat(timespec="seconds")
