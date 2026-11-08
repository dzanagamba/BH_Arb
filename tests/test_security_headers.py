"""Browser hardening headers are present on the dashboard and the API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import api as api_module
from server.app import app


def test_security_headers_cover_the_dashboard_and_api():
    client = TestClient(app)
    for path in ("/", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        csp = response.headers["content-security-policy"]
        assert "object-src 'none'" in csp
        assert "base-uri 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "connect-src 'self'" in csp


def test_security_headers_survive_a_rejected_request(monkeypatch):
    monkeypatch.setattr(api_module, "API_KEY", "secret")
    response = TestClient(app).get("/api/results?mode=prematch")
    assert response.status_code == 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
