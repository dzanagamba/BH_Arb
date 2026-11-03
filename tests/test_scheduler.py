"""Scheduled scans stay off by default and never overlap a manual scan."""

from __future__ import annotations

import asyncio

import pytest

from server import api, scheduler


def test_idle_guard_claims_the_feed_once():
    status, _, _, _, _ = api._state_for("prematch")
    original = status.is_scanning
    status.is_scanning = False
    try:
        assert asyncio.run(api.start_scan_if_idle("prematch")) is True
        assert status.is_scanning is True
        assert asyncio.run(api.start_scan_if_idle("prematch")) is False
    finally:
        status.is_scanning = original


def test_idle_guard_refuses_a_feed_a_verify_holds():
    status, _, _, _, _ = api._state_for("prematch")
    original = status.is_scanning
    status.is_scanning = False
    lock = api._lock_for("prematch")
    try:
        asyncio.run(lock.acquire())
        assert asyncio.run(api.start_scan_if_idle("prematch")) is False
    finally:
        lock.release()
        status.is_scanning = original


def test_the_loop_runs_one_scan_then_cancels(monkeypatch):
    calls: list[str] = []

    async def fake_sleep(_seconds: float) -> None:
        return None

    async def fake_start(mode: str) -> bool:
        return True

    async def fake_run(mode: str) -> None:
        calls.append(mode)
        raise asyncio.CancelledError

    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "start_scan_if_idle", fake_start)
    monkeypatch.setattr(scheduler, "run_scan", fake_run)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler.scan_loop("prematch", 1))
    assert calls == ["prematch"]


def test_the_loop_does_nothing_when_the_feed_is_busy(monkeypatch):
    calls: list[str] = []

    async def fake_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    async def fake_run(mode: str) -> None:
        calls.append(mode)

    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "run_scan", fake_run)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler.scan_loop("prematch", 1))
    assert calls == []
