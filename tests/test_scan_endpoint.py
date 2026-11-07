"""C-02: the POST /api/scan contract and its guards.

Every existing `/api/scan` test stopped at authentication, CSRF or an invalid
mode. These tests reach the handler body: the success response and its one
background task, the busy and maintenance short-circuits, the invalid run mode
and the per-client throttle. `run_scan` and `start_scan_if_idle` are stubbed, so
no scraper runs and no browser opens.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from models.schemas import ScanStatus
from server import api
from server.app import app
from server.auth import ApiKeyStore


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(
        api, "api_key_store", ApiKeyStore(str(tmp_path / "api_keys.json"))
    )
    monkeypatch.setattr(api, "API_KEY", "")
    monkeypatch.setattr(api, "maintenance_running", lambda: False)
    monkeypatch.setattr(api, "_scan_request_times", {})
    return TestClient(app)


def _stub_scan(monkeypatch) -> tuple[list[str], list[tuple]]:
    started: list[str] = []
    runs: list[tuple] = []

    async def fake_start(mode: str) -> bool:
        started.append(mode)
        return True

    async def fake_run(mode: str, scheduled: bool = False, run_mode: str = "advisory"):
        runs.append((mode, scheduled, run_mode))

    monkeypatch.setattr(api, "start_scan_if_idle", fake_start)
    monkeypatch.setattr(api, "run_scan", fake_run)
    return started, runs


def test_a_successful_scan_returns_started_and_queues_one_task(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    started, runs = _stub_scan(monkeypatch)

    response = client.post("/api/scan?mode=prematch&run_mode=advisory")

    assert response.status_code == 200
    assert response.json() == {
        "status": "started",
        "mode": "prematch",
        "run_mode": "advisory",
        "message": "Scan started. Poll /api/status for progress.",
    }
    assert started == ["prematch"]
    assert runs == [("prematch", False, "advisory")]


def test_a_scan_that_is_already_running_queues_nothing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    started, runs = _stub_scan(monkeypatch)
    monkeypatch.setattr(api, "scan_status", ScanStatus(is_scanning=True))

    response = client.post("/api/scan?mode=prematch")

    assert response.status_code == 200
    assert response.json()["status"] == "already_scanning"
    assert "already in progress" in response.json()["message"]
    assert started == []
    assert runs == []


def test_maintenance_refuses_a_scan_before_claiming_the_feed(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    started, runs = _stub_scan(monkeypatch)
    monkeypatch.setattr(api, "maintenance_running", lambda: True)

    response = client.post("/api/scan?mode=prematch")

    assert response.status_code == 200
    assert response.json()["status"] == "maintenance"
    assert started == []
    assert runs == []


def test_an_unknown_run_mode_is_a_400_before_any_task(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    started, runs = _stub_scan(monkeypatch)

    response = client.post("/api/scan?mode=prematch&run_mode=free_money")

    assert response.status_code == 400
    assert "run_mode" in response.json()["detail"]
    assert started == []
    assert runs == []


def test_the_scan_throttle_returns_429(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    started, runs = _stub_scan(monkeypatch)
    monkeypatch.setattr(api, "SCAN_RATE_LIMIT", 1)
    monkeypatch.setattr(api, "RATE_LIMIT_WINDOW_SECONDS", 60)
    # The open/local mode keys the window on the TestClient's client host.
    monkeypatch.setattr(api, "_scan_request_times", {"testclient": [time.time()]})

    response = client.post("/api/scan?mode=prematch")

    assert response.status_code == 429
    assert "Rate limit exceeded" in response.json()["detail"]
    assert started == []
    assert runs == []
