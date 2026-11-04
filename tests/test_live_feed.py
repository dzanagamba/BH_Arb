"""P2-10: a push stream must be continuous, fresh and bounded to price."""

from __future__ import annotations

import time
from collections.abc import Callable

from config.settings import LIVE_FEED_FLAGS
from engine.live_feed import FeedFrame, LiveFeedState, ReplayLiveFeed


def _row(event: str, outcome: str, odds: float) -> dict:
    return {"event_id": event, "market": "btts", "line": "", "outcome": outcome, "odds": odds}


def _state(
    *,
    max_rows: int = 10,
    heartbeat_timeout_seconds: float = 15,
    clock: Callable[[], float] | None = None,
) -> LiveFeedState:
    return LiveFeedState(
        enabled=True,
        max_rows=max_rows,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        clock=clock or time.monotonic,
    )


def test_every_shipped_flag_is_off_and_a_disabled_feed_cannot_price():
    assert not any(LIVE_FEED_FLAGS.values())
    state = LiveFeedState(enabled=False)
    state.apply(FeedFrame(seq=1, rows=[_row("e1", "GG", 2.0)]))

    assert state.state == "disabled"
    assert state.priceable() is False
    assert state.rows() == []


def test_snapshot_then_delta_coalesces_to_the_latest_row():
    state = _state()
    state.apply(FeedFrame(seq=1, kind="snapshot", rows=[_row("e1", "GG", 2.0)]))
    state.apply(FeedFrame(seq=2, kind="delta", rows=[_row("e1", "GG", 2.1)]))

    assert state.priceable() is True
    assert state.rows() == [_row("e1", "GG", 2.1)]


def test_a_sequence_gap_refuses_the_stream():
    state = _state()
    state.apply(FeedFrame(seq=1, kind="snapshot", rows=[_row("e1", "GG", 2.0)]))
    state.apply(FeedFrame(seq=3, kind="delta", rows=[_row("e1", "GG", 2.1)]))

    assert state.state == "gapped"
    assert state.priceable() is False
    assert state.rows() == []


def test_a_duplicate_or_older_sequence_is_refused():
    state = _state()
    state.apply(FeedFrame(seq=1, kind="snapshot", rows=[_row("e1", "GG", 2.0)]))
    state.apply(FeedFrame(seq=1, kind="delta", rows=[_row("e1", "GG", 2.1)]))

    assert state.state == "duplicate"
    assert state.priceable() is False


def test_silence_past_the_heartbeat_timeout_refuses_the_rows():
    clock = [1000.0]
    state = _state(clock=lambda: clock[0])
    state.apply(FeedFrame(seq=1, kind="snapshot", rows=[_row("e1", "GG", 2.0)], received_at=clock[0]))
    assert state.priceable() is True

    clock[0] += 16
    assert state.is_stale() is True
    assert state.priceable() is False
    assert state.rows() == []


def test_the_latest_row_store_is_bounded():
    state = _state(max_rows=2)
    state.apply(
        FeedFrame(
            seq=1,
            kind="snapshot",
            rows=[_row(f"e{i}", "GG", 2.0) for i in range(5)],
        )
    )

    assert len(state.rows()) == 2


def test_replay_covers_snapshot_and_delta_without_a_network():
    replay = ReplayLiveFeed(
        [
            FeedFrame(seq=1, kind="snapshot", rows=[_row("e1", "GG", 2.0)]),
            FeedFrame(seq=2, kind="delta", rows=[_row("e1", "NG", 1.9)]),
        ],
        enabled=True,
        max_rows=10,
        heartbeat_timeout_seconds=15,
    )

    state = replay.run()

    assert state.priceable() is True
    assert {row["outcome"] for row in state.rows()} == {"GG", "NG"}
