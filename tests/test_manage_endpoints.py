"""C-03/C-04: management endpoints and the shutdown loopback guard.

None of these handlers had a test: `/api/status`, `/api/history`, the two config
toggles, `/api/debug/matches`, `/api/audit` and `/api/shutdown`. The shutdown
test patches the client host and captures the loop's `call_later` scheduling, so
it proves the guard without ever signalling the test process.
"""

from __future__ import annotations

import json
import signal
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from models.schemas import ScanStatus
from server import api
from server.app import app
from server.auth import ApiKeyStore
from server.storage import Storage, default_storage_path


class _FakeLoop:
    """Records `call_later` instead of running the callback."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[float, object, tuple]] = []

    def call_later(self, delay: float, callback: object, *args) -> None:
        self.scheduled.append((delay, callback, args))


def _client(monkeypatch, tmp_path) -> tuple[TestClient, ApiKeyStore]:
    store = ApiKeyStore(str(tmp_path / "api_keys.json"))
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    return TestClient(app), store


def _iso(offset_days: float = 0) -> str:
    return (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=offset_days)).isoformat()


def test_status_serves_each_feed(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "scan_status", ScanStatus(total_matches=11))
    monkeypatch.setattr(api, "live_status", ScanStatus(mode="live", total_matches=4))

    prematch = client.get("/api/status").json()
    live = client.get("/api/status?mode=live").json()

    assert prematch["mode"] == "prematch"
    assert prematch["total_matches"] == 11
    assert live["mode"] == "live"
    assert live["total_matches"] == 4


def test_history_days_zero_serves_the_in_memory_list(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    rows = [
        {"mode": "prematch", "match_groups": 1},
        {"mode": "live", "match_groups": 2},
    ]
    monkeypatch.setattr(api, "scan_history", rows)

    body = client.get("/api/history?days=0").json()

    assert body["days"] == 0
    assert body["count"] == 2
    assert body["entries"] == rows
    live_only = client.get("/api/history?days=0&mode=live").json()
    assert live_only["count"] == 1
    assert live_only["entries"] == [{"mode": "live", "match_groups": 2}]


def test_history_with_a_positive_window_reads_sqlite(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    storage = Storage(default_storage_path())
    storage.initialize()
    storage.append_scan(
        {
            "mode": "prematch",
            "scan_time": _iso(),
            "total_matches": 30,
            "match_groups": 5,
            "surebets_found": 1,
            "per_bookie": {"mozzartbet": 30},
            "errors": [],
            "candidate_queue": 0,
            "candidate_actionable": 0,
        }
    )
    storage.append_scan(
        {
            "mode": "prematch",
            "scan_time": _iso(-5),
            "total_matches": 9,
            "match_groups": 0,
            "surebets_found": 0,
            "per_bookie": {},
            "errors": [],
            "candidate_queue": 0,
            "candidate_actionable": 0,
        }
    )
    monkeypatch.setattr(api, "_storage", storage)

    body = client.get("/api/history?days=2").json()

    assert body["days"] == 2
    assert body["count"] == 1
    assert body["entries"][0]["match_groups"] == 5


def test_toggle_an_unknown_bookmaker_is_404(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)

    response = client.post("/api/config/toggle/not_a_bookmaker")

    assert response.status_code == 404
    assert "Unknown bookmaker" in response.json()["detail"]


def test_toggle_a_bookmaker_persists_and_reloads(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "_bookmaker_enabled", {"mozzartbet": True, "mdshop": True})

    response = client.post("/api/config/toggle/mozzartbet")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "bookmaker_id": "mozzartbet",
        "enabled": False,
    }
    assert api._bookmaker_enabled == {"mozzartbet": False, "mdshop": True}
    saved = json.loads(Path(api._BOOKMAKER_STATE_FILE).read_text(encoding="utf-8"))
    assert saved == {"mozzartbet": False, "mdshop": True}
    assert any(row["event"] == "toggle_bookmaker" for row in store.audit_log())

    # A restart reads the file rather than the in-memory flip.
    api._bookmaker_enabled["mozzartbet"] = True
    api._load_bookmaker_state()
    assert api._bookmaker_enabled["mozzartbet"] is False

    flipped_back = client.post("/api/config/toggle/mozzartbet")
    assert flipped_back.json()["enabled"] is True


def test_toggle_an_unknown_market_is_404(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "_market_enabled", {"experimental_test_market": False})

    response = client.post("/api/config/toggle_market/not_a_market")

    assert response.status_code == 404
    assert "Unknown experimental market" in response.json()["detail"]


def test_toggle_a_market_persists_and_reloads(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(api, "_market_enabled", {"experimental_test_market": False})

    response = client.post("/api/config/toggle_market/experimental_test_market")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "market": "experimental_test_market",
        "enabled": True,
    }
    saved = json.loads(Path(api._MARKET_STATE_FILE).read_text(encoding="utf-8"))
    assert saved == {"experimental_test_market": True}

    api._market_enabled["experimental_test_market"] = False
    api._load_market_state()
    assert api._market_enabled["experimental_test_market"] is True


def test_debug_matches_groups_the_cached_rows_by_book(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        api,
        "cached_matches",
        [
            {"bookmaker": "mozzartbet", "home_team": "Sarajevo", "away_team": "Zrinjski",
             "league": "Premijer Liga"},
            {"bookmaker": "mozzartbet", "home_team": "Borac", "away_team": "Siroki",
             "league": "Premijer Liga"},
            {"bookmaker": "mdshop", "home_team": "Velez", "away_team": "Zeljeznicar",
             "league": "Premijer Liga"},
        ],
    )

    body = client.get("/api/debug/matches").json()

    assert body["mode"] == "prematch"
    assert body["grand_total"] == 3
    assert body["totals"] == {"mozzartbet": 2, "mdshop": 1}
    assert body["matches_by_bookmaker"]["mdshop"] == [
        "Velez vs Zeljeznicar [Premijer Liga]"
    ]


def test_the_audit_endpoint_serves_privileged_events_newest_first(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)
    store.audit("key_created", "id1", "laptop")
    store.audit("key_revoked", "id2", "phone")

    entries = client.get("/api/audit?limit=10").json()["entries"]

    assert [row["event"] for row in entries] == ["key_revoked", "key_created"]
    assert entries[0]["detail"] == "phone"


def test_shutdown_from_a_non_loopback_client_is_refused(monkeypatch, tmp_path):
    _, store = _client(monkeypatch, tmp_path)
    fake_loop = _FakeLoop()
    monkeypatch.setattr(
        api, "asyncio", SimpleNamespace(get_running_loop=lambda: fake_loop)
    )
    client = TestClient(app, client=("10.0.0.7", 40000))

    response = client.post("/api/shutdown")

    assert response.status_code == 403
    assert "only allowed from this computer" in response.json()["detail"]
    assert fake_loop.scheduled == []
    # The refusal is still audited, with the requesting address.
    assert store.audit_log()[0]["event"] == "shutdown"
    assert store.audit_log()[0]["detail"] == "10.0.0.7"


def test_shutdown_from_loopback_schedules_a_sigint_and_audits(monkeypatch, tmp_path):
    _, store = _client(monkeypatch, tmp_path)
    fake_loop = _FakeLoop()
    monkeypatch.setattr(
        api, "asyncio", SimpleNamespace(get_running_loop=lambda: fake_loop)
    )
    client = TestClient(app, client=("127.0.0.1", 40000))

    response = client.post("/api/shutdown")

    assert response.status_code == 200
    assert response.json() == {"status": "stopping"}
    assert len(fake_loop.scheduled) == 1
    delay, callback, args = fake_loop.scheduled[0]
    assert delay == 0.5
    assert callback is signal.raise_signal
    assert args == (signal.SIGINT,)
    assert store.audit_log()[0]["event"] == "shutdown"
    assert store.audit_log()[0]["detail"] == "127.0.0.1"
