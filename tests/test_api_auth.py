"""M1-1: one middleware closes every /api route except health, with scopes.

WHAT THESE TESTS PROVE
----------------------
With a bootstrap key configured, every `/api` route except `/api/health` needs a
key: the middleware checks it before any route runs, so a read route that has no
auth dependency of its own (results, status, config, groups, debug, bets, paper,
link-sweeps) cannot be served anonymously. A valid named key works beside a
bootstrap key (previously the middleware rejected it), a read key cannot write,
a scan key cannot read, and with nothing configured the documented local-only
mode stays open.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not prove a scope map that matches an operator's intent; they pin the
matrix the code ships. They do not exercise real scans: write routes are driven
to their scope/validation boundary, never into the scrape.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import api
from server import app as app_module
from server.auth import ApiKeyStore

API_PREFIX = "/api"


def _store(tmp_path: Path) -> ApiKeyStore:
    return ApiKeyStore(str(tmp_path / "api_keys.json"))


def _concrete(path: str) -> str:
    """A request path for a route template (any value satisfies the param)."""
    out = []
    for part in path.split("/"):
        out.append("x" if part.startswith("{") else part)
    return "/".join(out)


def _api_routes() -> list[tuple[str, str]]:
    """Every (method, path) the app serves under /api, minus health.

    FastAPI 0.1xx includes routers lazily, so the OpenAPI schema is the reliable
    route inventory (it also covers every method on a shared path).
    """
    routes: list[tuple[str, str]] = []
    for path, operations in app_module.app.openapi()["paths"].items():
        if not path.startswith(API_PREFIX) or path == "/api/health":
            continue
        for method in operations:
            routes.append((method.upper(), _concrete(path)))
    return routes


def test_every_api_route_except_health_requires_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "api_key_store", _store(tmp_path))
    monkeypatch.setattr(api, "API_KEY", "secret")
    client = TestClient(app_module.app)

    routes = _api_routes()
    assert len(routes) >= 30, "route discovery found too few routes"
    anonymous = [
        f"{method} {path}"
        for method, path in routes
        if client.request(method, path).status_code != 401
    ]
    assert not anonymous, anonymous


def test_health_stays_public_with_keys_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "api_key_store", _store(tmp_path))
    monkeypatch.setattr(api, "API_KEY", "secret")
    client = TestClient(app_module.app)

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers={"X-API-Key": "wrong"}).status_code == 200


def test_a_named_key_is_accepted_beside_a_bootstrap_key(tmp_path, monkeypatch):
    store = _store(tmp_path)
    token, _ = store.create("laptop", ["read", "scan"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "secret")
    client = TestClient(app_module.app)

    assert client.get("/api/results", headers={"X-API-Key": token}).status_code == 200
    assert client.get("/api/results", headers={"X-API-Key": "secret"}).status_code == 200


def test_a_read_key_cannot_write(tmp_path, monkeypatch):
    store = _store(tmp_path)
    token, _ = store.create("dashboard", ["read"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    client = TestClient(app_module.app, raise_server_exceptions=False)
    headers = {"X-API-Key": token}

    assert client.get("/api/results", headers=headers).status_code == 200
    assert client.post("/api/verify-links", headers=headers).status_code == 403
    assert client.post("/api/bets", headers=headers).status_code == 403
    assert client.post("/api/scan", headers=headers).status_code == 403
    assert client.post("/api/config/toggle/mdshop", headers=headers).status_code == 403


def test_a_scan_key_cannot_read(tmp_path, monkeypatch):
    store = _store(tmp_path)
    token, _ = store.create("scheduler", ["scan"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    client = TestClient(app_module.app)
    headers = {"X-API-Key": token}

    assert client.get("/api/results", headers=headers).status_code == 403
    assert client.get("/api/status", headers=headers).status_code == 403
    # The key is authenticated: the write route answers validation, not 401/403.
    assert client.post("/api/verify-links", headers=headers).status_code not in (
        401,
        403,
    )


def test_local_only_mode_stays_open_when_nothing_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "api_key_store", _store(tmp_path))
    monkeypatch.setattr(api, "API_KEY", "")
    client = TestClient(app_module.app)

    assert client.get("/api/results").status_code == 200
    assert client.get("/api/config").status_code == 200


def test_a_revoked_only_store_closes_the_read_routes(tmp_path, monkeypatch):
    store = _store(tmp_path)
    token, record = store.create("laptop", ["read", "scan"])
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "")
    client = TestClient(app_module.app)
    assert client.get("/api/results", headers={"X-API-Key": token}).status_code == 200

    assert store.revoke(record["id"])

    for path in ("/api/results", "/api/status", "/api/config", "/api/groups"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"X-API-Key": token}).status_code == 401, path


def test_the_bootstrap_key_cannot_be_replaced_by_its_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "api_key_store", _store(tmp_path))
    monkeypatch.setattr(api, "API_KEY", "secret")
    client = TestClient(app_module.app)

    for wrong in ("secre", "secrets", "Secret", ""):
        assert client.get("/api/results", headers={"X-API-Key": wrong}).status_code == 401


@pytest.mark.parametrize("method,path", [("GET", "/api/health")])
def test_the_route_table_matches_the_guard(method, path):
    """A reminder for a new route: the middleware covers it, health does not."""
    client = TestClient(app_module.app)
    assert client.request(method, path).status_code == 200
