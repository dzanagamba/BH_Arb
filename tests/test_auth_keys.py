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


def test_revoking_the_last_key_keeps_a_dependency_guard_closed(tmp_path, monkeypatch):
    """C-09: revocation must not reopen the API through `has_any_keys()`.

    The store still has a record (revoked), so `_require_api_key` cannot take
    the "no keys configured" local-only path even with `API_KEY=""`.
    """
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    client = TestClient(app)

    assert store.revoke(record["id"])
    assert store.has_any_keys() is True
    assert store.active_keys() == []

    assert client.get("/api/history").status_code == 401
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/history", headers={"X-API-Key": token}).status_code == 401


@pytest.mark.xfail(
    strict=True,
    reason=(
        "auth path redesign (C-01/C-02/C-07) is deferred: /api/results has no "
        "_require_api_key dependency, so a named-key store cannot close it"
    ),
)
def test_the_results_route_should_close_when_only_revoked_named_keys_exist(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    client = TestClient(app)

    assert store.revoke(record["id"])
    assert client.get("/api/results").status_code == 401


def test_a_corrupt_key_store_with_the_env_key_still_fails_closed(tmp_path, monkeypatch):
    """C-09: a broken store must not silently become "no keys configured".

    With ``API_KEY`` empty the corrupt store reports no keys at all, so the
    historical local-only fallback still applies — the documented current
    behaviour, safe only because the default bind is loopback. This test pins
    the direction that matters: when a bootstrap key IS configured, a broken
    store denies the request rather than opening the API.
    """
    (tmp_path / "api_keys.json").write_text("{not json", encoding="utf-8")
    store = _store(tmp_path)
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "secret")
    client = TestClient(app)

    assert store.has_any_keys() is False
    assert store.active_keys() == []
    assert client.get("/api/history").status_code == 401
    assert (
        client.get("/api/history", headers={"X-API-Key": "wrong"}).status_code
        == 401
    )
    # The env bootstrap key still works, so the store is not a single point of
    # failure for the operator.
    assert (
        client.get("/api/history", headers={"X-API-Key": "secret"}).status_code
        == 200
    )


def test_a_read_scope_key_cannot_reach_an_admin_or_mutation_route(tmp_path, monkeypatch):
    """C-09: the current scope policy, asserted rather than redesigned."""
    store = _store(tmp_path)
    token, _ = store.create("reader", ["read"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    monkeypatch.setattr(api, "_bookmaker_enabled", dict(api._bookmaker_enabled))
    before = dict(api._bookmaker_enabled)
    client = TestClient(app)
    headers = {"X-API-Key": token}

    # The read scope reaches read routes...
    assert client.get("/api/history", headers=headers).status_code == 200
    # ...but not key administration, a config toggle, shutdown or a scan.
    assert client.get("/api/keys", headers=headers).status_code == 403
    assert (
        client.post("/api/config/toggle/mozzartbet", headers=headers).status_code
        == 403
    )
    assert client.post("/api/shutdown", headers=headers).status_code == 403
    assert client.post("/api/scan", headers=headers).status_code == 403
    assert api._bookmaker_enabled == before
