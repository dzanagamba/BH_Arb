"""Pairing quality is part of the health and results payloads."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import api
from server.app import app


def _summary() -> dict:
    return {
        "matches": 6_567,
        "groups": 1_073,
        "ungrouped": 627,
        "duplicate_listings": 305,
        "strict_misses": 18,
        "strict_miss_rate": 0.0027,
        "duplicate_book_groups": [],
    }


def test_health_exposes_the_pairing_summary(monkeypatch):
    monkeypatch.setattr(api, "_pairing_summary", {"prematch": _summary()})
    body = TestClient(app).get("/api/health").json()

    assert body["pairing"]["strict_misses"] == 18
    assert body["pairing"]["strict_miss_rate"] == 0.0027
    assert body["live_pairing"] == {}


def test_results_expose_the_pairing_summary(monkeypatch):
    monkeypatch.setattr(api, "_pairing_summary", {"prematch": _summary()})
    body = TestClient(app).get("/api/results?mode=prematch").json()

    assert body["pairing"]["strict_miss_rate"] == 0.0027
    assert body["pairing"]["duplicate_book_groups"] == []


def test_pairing_summary_is_recomputed_from_the_served_rows():
    api._pairing_summary.pop("prematch", None)

    api._refresh_pairing_summary("prematch", [], [])

    summary = api._pairing_summary["prematch"]
    assert summary["matches"] == 0
    assert summary["groups"] == 0
    assert summary["strict_misses"] == 0
    assert summary["strict_miss_rate"] == 0.0
    assert summary["duplicate_book_groups"] == []
