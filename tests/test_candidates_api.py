"""Candidates review endpoints and health diagnostics."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from models.schemas import CandidateReview
from server import api
from server.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_candidate_state(monkeypatch, tmp_path):
    original_pending = api.pending_candidates.copy()
    original_reviews = api.candidate_reviews.copy()
    original_report = api.cached_match_groups_report.copy()
    original_matches = api.cached_matches.copy()
    original_unmapped = api.unmapped_markets.copy()
    api.pending_candidates.clear()
    api.candidate_reviews.clear()
    monkeypatch.setattr(api, "ALLOWLIST_FILE", str(tmp_path / "team_alias_allowlist.json"))
    yield
    api.pending_candidates.clear()
    api.pending_candidates.update(original_pending)
    api.candidate_reviews[:] = original_reviews
    api.cached_match_groups_report[:] = original_report
    api.cached_matches[:] = original_matches
    api.unmapped_markets.clear()
    api.unmapped_markets.update(original_unmapped)


def _candidate(candidate_id: str = "candidate-1") -> CandidateReview:
    return CandidateReview(
        id=candidate_id,
        home_team="Lech Poznan",
        away_team="Lech P.",
        league="Liga Evrope",
        kickoff=datetime(2026, 9, 25, 18, 0),
        bookmakers=["mdshop", "mbet"],
        created_at=datetime(2026, 9, 25, 12, 0),
    )


def test_candidates_list_empty_initially():
    r = client.get("/api/candidates")
    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["candidates"] == []


def test_candidates_list_serializes_pending_candidates():
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate

    r = client.get("/api/candidates?mode=live")

    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["candidates"][0]["id"] == candidate.id
    assert body["candidates"][0]["status"] == "pending"


def test_health_includes_new_diagnostics():
    api.cached_match_groups_report.extend([{"status": "verified"}, {"status": "suggested"}])
    api.cached_matches.extend(
        [
            {"event_id": "verified", "deep_link_verified": True},
            {"event_id": "unverified", "deep_link_verified": False},
        ]
    )
    api.unmapped_markets["mdshop:424242"] = 2

    r = client.get("/api/health")

    assert r.status_code == 200
    body = r.json()
    assert body["verified_groups"] == 1
    assert body["unverified_links"] == 1
    assert body["unmapped_markets"] == {"mdshop:424242": 2}
    assert body["pending_candidates"] == 0
    assert "ai_available" in body
    for key in (
        "status",
        "scanning",
        "surebets_cached",
        "matches_cached",
        "live_surebets_cached",
        "live_matches_cached",
        "prematch",
        "live",
        "odds_ttl_sec",
    ):
        assert key in body


def test_approve_unknown_candidate_returns_404():
    r = client.post("/api/candidates/does-not-exist/approve")
    assert r.status_code == 404


def test_approve_candidate_writes_reviewed_alias_and_resolves_it():
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate

    r = client.post(f"/api/candidates/{candidate.id}/approve")

    assert r.status_code == 200
    assert r.json() == {
        "status": "approved",
        "allowlist_entries": ["Lech P.|Lech Poznan"],
    }
    assert candidate.status == "approved"
    assert candidate.resolved_by == "human"
    assert candidate.resolved_at is not None
    assert candidate.resolved_at.tzinfo is None
    assert candidate.id not in api.pending_candidates
    assert api.candidate_reviews[0].id == candidate.id
    with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
        saved = json.load(file)
    assert saved == {"aliases": ["Lech P.|Lech Poznan"]}


def test_reject_candidate_records_human_rejection():
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate

    r = client.post(f"/api/candidates/{candidate.id}/reject")

    assert r.status_code == 200
    assert r.json() == {"status": "rejected"}
    assert candidate.status == "rejected"
    assert candidate.resolved_by == "human"
    assert candidate.resolved_at is not None
    assert candidate.resolved_at.tzinfo is None
    assert candidate.id not in api.pending_candidates
    assert api.candidate_reviews[0].id == candidate.id


def test_candidate_mutations_require_api_key_when_configured(monkeypatch):
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate
    monkeypatch.setattr(api, "API_KEY", "secret")

    assert client.post(f"/api/candidates/{candidate.id}/approve").status_code == 401
    assert client.post(
        f"/api/candidates/{candidate.id}/approve", headers={"X-API-Key": "secret"}
    ).status_code == 200
