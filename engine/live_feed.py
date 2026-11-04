"""Feature-flagged push-feed state machine (P2-10).

No book is wired to this yet: the 2026-11-04 transport capture found either no
WebSocket or heartbeat-sized traffic, so polling remains the measured choice.
The state machine is here so a future adapter cannot bypass the rules that make
a stream safe: sequence continuity, bounded coalescing, heartbeat freshness and
explicit refusal to price a gap or a silent feed.

```python
state = LiveFeedState(max_rows=1000, heartbeat_timeout_seconds=15)
state.apply(FeedFrame(seq=1, kind="snapshot", rows=[...]))
if state.priceable():   # False on a gap, stale silence or flag-off
    rows = state.rows()
```
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

FrameKind = Literal["snapshot", "delta"]


@dataclass(frozen=True)
class FeedFrame:
    seq: int
    rows: list[dict[str, Any]]
    kind: FrameKind = "delta"
    received_at: float = field(default_factory=time.monotonic)
    source_updated_at: str = ""


class LiveFeedState:
    """Coalesce snapshot/delta rows and refuse unsafe streams."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        max_rows: int = 5000,
        heartbeat_timeout_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = enabled
        self.max_rows = max(1, max_rows)
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self._clock = clock
        self._rows: dict[str, dict[str, Any]] = {}
        self._last_seq: int | None = None
        self._last_frame_at: float | None = None
        self.state = "disabled" if not enabled else "empty"
        self.last_error = ""

    def _row_key(self, row: dict[str, Any]) -> str:
        return "|".join(
            str(row.get(key) or "")
            for key in ("event_id", "market", "line", "outcome")
        )

    def apply(self, frame: FeedFrame) -> str:
        """Apply one frame; return the state after it."""
        if not self.enabled:
            self.state = "disabled"
            return self.state
        if self._last_seq is not None and frame.seq <= self._last_seq:
            self.state = "duplicate"
            self.last_error = f"sequence {frame.seq} is not newer than {self._last_seq}"
            return self.state
        if self._last_seq is not None and frame.seq != self._last_seq + 1:
            self.state = "gapped"
            self.last_error = f"expected sequence {self._last_seq + 1}, got {frame.seq}"
            self._last_seq = frame.seq
            self._last_frame_at = frame.received_at
            return self.state
        if frame.kind == "snapshot":
            self._rows.clear()
        for row in frame.rows:
            self._rows[self._row_key(row)] = dict(row)
        if len(self._rows) > self.max_rows:
            # Keep the newest keys rather than grow without bound.
            keep = list(self._rows)[-self.max_rows :]
            self._rows = {key: self._rows[key] for key in keep}
        self._last_seq = frame.seq
        self._last_frame_at = frame.received_at
        self.state = "healthy"
        self.last_error = ""
        return self.state

    def is_stale(self, now: float | None = None) -> bool:
        if not self.enabled or self._last_frame_at is None:
            return True
        current = self._clock() if now is None else now
        return current - self._last_frame_at > self.heartbeat_timeout_seconds

    def priceable(self, now: float | None = None) -> bool:
        return self.enabled and self.state == "healthy" and not self.is_stale(now)

    def rows(self) -> list[dict[str, Any]]:
        if not self.priceable():
            return []
        return list(self._rows.values())


class ReplayLiveFeed:
    """Offline frame replay used by tests; never a network transport."""

    def __init__(self, frames: Iterable[FeedFrame], **state_kwargs: Any) -> None:
        self.frames = list(frames)
        self.state = LiveFeedState(**state_kwargs)

    def run(self) -> LiveFeedState:
        for frame in self.frames:
            self.state.apply(frame)
        return self.state
