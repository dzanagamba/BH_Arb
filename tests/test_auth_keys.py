"""P3-5: named keys are hashed, scoped, revocable and auditable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import api
from server.app import app
from server.auth import ApiKeyStore


def _store(tmp_path: Path) -> ApiKeyStore:
    return ApiKeyStore(str(tmp_path / "api_keys.json"))


def test_a_key_is_returned_once_and_only_a_hash_is_stored(tmp_path):
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read", "scan"])

    raw = (tmp_path / "api_keys.json").read_text(encoding="utf-8")
    assert token.startswith("bh_")
    assert token not in raw
    assert record["label"] == "laptop"
    assert "hash" not in record and "salt" not in record
    assert store.verify(token)["id"] == record["id"]
    assert store.verify("wrong") is None


def test_revocation_fails_the_next_request(tmp_path):
    store = _store(tmp_path)
    token, record = store.create("laptop", ["admin"])

    assert store.revoke(record["id"]) is True
    assert store.verify(token) is None
    assert store.active_keys() == []


def test_invalid_scopes_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        _store(tmp_path).create("bad", ["root"])


def test_audit_log_records_create_and_revoke(tmp_path):
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read"])
    store.revoke(record["id"])

    events = [row["event"] for row in store.audit_log()]

    assert "key_revoked" in events
    assert "key_created" in events
    assert token not in json.dumps(store.audit_log())


def test_the_api_creates_scopes_and_revokes_a_key(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "bootstrap")
    client = TestClient(app)
    headers = {"X-API-Key": "bootstrap"}

    created = client.post(
        "/api/keys",
        headers=headers,
        json={"label": "phone", "scopes": ["read"]},
    )
    assert created.status_code == 200
    token = created.json()["token"]
    key_id = created.json()["key"]["id"]

    # A read-scoped key cannot reach admin metadata.
    denied = client.get("/api/keys", headers={"X-API-Key": token})
    assert denied.status_code == 403

    revoked = client.delete(f"/api/keys/{key_id}", headers=headers)
    assert revoked.status_code == 200
    assert client.get("/api/keys", headers={"X-API-Key": token}).status_code == 401


def test_the_env_key_remains_the_bootstrap_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "api_key_store", _store(tmp_path))
    monkeypatch.setattr(api, "API_KEY", "bootstrap")
    client = TestClient(app)

    assert client.get("/api/keys").status_code == 401
    assert (
        client.get("/api/keys", headers={"X-API-Key": "bootstrap"}).status_code
        == 200
    )


def test_a_revoked_key_cannot_use_a_scan_scope(tmp_path, monkeypatch):
    store = _store(tmp_path)
    token, record = store.create("scanner", ["scan"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    client = TestClient(app)

    # The route reaches the scan gate before any background work only when the
    # key is valid; a revoked key must stop at authentication.
    assert store.revoke(record["id"])
    response = client.post("/api/scan", headers={"X-API-Key": token})
    assert response.status_code == 401
