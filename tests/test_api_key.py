"""With API_KEY set, every /api route except health needs the header."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app as app_module


def test_read_routes_require_the_key_when_configured(monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret")
    client = TestClient(app_module.app)
    assert client.get("/api/results?mode=prematch").status_code == 401
    ok = client.get("/api/results?mode=prematch", headers={"X-API-Key": "secret"})
    assert ok.status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers={"X-API-Key": "wrong"}).status_code == 200


def test_a_wrong_key_is_rejected(monkeypatch):
    monkeypatch.setattr(app_module, "API_KEY", "secret")
    client = TestClient(app_module.app)
    assert client.get("/api/config", headers={"X-API-Key": "wrong"}).status_code == 401
