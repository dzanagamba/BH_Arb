"""A cross-origin browser write is refused before it can act."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app


def test_a_cross_origin_post_is_refused():
    client = TestClient(app)
    response = client.post(
        "/api/scan?mode=prematch",
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert "Cross-origin" in response.json()["detail"]


def test_a_request_without_an_origin_is_unchanged():
    client = TestClient(app)
    # GET is not a state-changing method; the guard must not touch it.
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200
