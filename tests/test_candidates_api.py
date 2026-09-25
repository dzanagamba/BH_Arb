"""Candidates review endpoints and health diagnostics."""

import asyncio
import json
import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from engine import matcher as matcher_module
from engine.matcher import MatchMatcher
from models.schemas import CandidateReview, Match
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
    original_suppressed = dict(api._suppressed_candidates)
    api.pending_candidates.clear()
    api.candidate_reviews.clear()
    api._suppressed_candidates.clear()
    monkeypatch.setattr(api, "ALLOWLIST_FILE", str(tmp_path / "team_alias_allowlist.json"))
    monkeypatch.setattr(
        api, "SUPPRESSED_CANDIDATES_FILE", str(tmp_path / "suppressed_candidates.json")
    )
    yield
    api.pending_candidates.clear()
    api.pending_candidates.update(original_pending)
    api.candidate_reviews[:] = original_reviews
    api.cached_match_groups_report[:] = original_report
    api.cached_matches[:] = original_matches
    api.unmapped_markets.clear()
    api.unmapped_markets.update(original_unmapped)
    api._suppressed_candidates.clear()
    api._suppressed_candidates.update(original_suppressed)


def _candidate(
    candidate_id: str = "candidate-1",
    left_home: str = "Lech Poznan",
    left_away: str = "Thun",
    right_home: str = "Lech P.",
    right_away: str = "FC Thun",
) -> CandidateReview:
    """A candidate exactly as `run_scan` produces it: both sides, both spellings."""
    return _produced_candidate(candidate_id, left_home, left_away, right_home, right_away)


def _produced_candidate(
    candidate_id: str,
    left_home: str,
    left_away: str,
    right_home: str,
    right_away: str,
) -> CandidateReview:
    """Run the real producer so the endpoint tests never invent a shape."""
    matches = [
        _mapping_match("mdshop", left_home, left_away, "mdshop-1"),
        _mapping_match("mbet", right_home, right_away, "mbet-1"),
    ]
    produced = asyncio.run(api._collect_candidates(matches, MatchMatcher()))
    assert len(produced) == 1, produced
    candidate = next(iter(produced.values()))
    candidate.id = candidate_id
    return candidate


def _mapping_match(
    bookmaker: str,
    home_team: str,
    away_team: str,
    event_id: str,
) -> Match:
    kickoff = datetime(2026, 9, 25, 18, 0)
    return Match(
        bookmaker=bookmaker,
        home_team=home_team,
        away_team=away_team,
        league="Liga Evrope",
        kickoff=kickoff,
        event_id=event_id,
        url=f"https://example.test/{bookmaker}/{event_id}",
        deep_link_verified=True,
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
    matcher = MatchMatcher()
    groups = matcher.group_matches(
        [
            _mapping_match("mdshop", "Lech Poznan", "Opponent", "mdshop-1"),
            _mapping_match("mbet", "Lech P.", "Opponent", "mbet-1"),
        ]
    )
    report = matcher.get_match_report(groups)
    assert groups and groups[0].status == "verified"
    assert report and report[0]["status"] == "verified"
    api.cached_match_groups_report[:] = report
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


def test_reject_unknown_candidate_returns_404():
    r = client.post("/api/candidates/does-not-exist/reject")
    assert r.status_code == 404


def test_approve_candidate_writes_reviewed_alias_and_resolves_it():
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate

    r = client.post(f"/api/candidates/{candidate.id}/approve")

    assert r.status_code == 200
    body = r.json()
    # One entry per team slot the two books spell differently — never a pair of
    # the two halves of one fixture, which would alias a club to its opponent.
    assert body["status"] == "approved"
    assert body["allowlist_entries"] == ["FC Thun|Thun", "Lech P.|Lech Poznan"]
    assert body["link_state"] == "verified"
    with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
        saved = json.load(file)
    assert saved == {"aliases": ["FC Thun|Thun", "Lech P.|Lech Poznan"]}
    assert candidate.status == "approved"
    assert candidate.resolved_by == "human"
    assert candidate.resolved_at is not None
    assert candidate.resolved_at.tzinfo is None
    assert candidate.id not in api.pending_candidates
    assert api.candidate_reviews[0].id == candidate.id
    # A decided pair is not re-queued on the next scan.
    assert api._suppressed_candidates == {candidate.id: "approved"}


def test_approved_alias_is_loaded_by_real_matcher(monkeypatch):
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate
    monkeypatch.setattr(matcher_module, "_TEAM_ALIAS_FILE", api.ALLOWLIST_FILE)

    response = client.post(f"/api/candidates/{candidate.id}/approve")
    groups = MatchMatcher().group_matches(
        [
            _mapping_match("mdshop", "Lech Poznan", "Thun", "mdshop-1"),
            _mapping_match("mbet", "Lech P.", "FC Thun", "mbet-1"),
        ]
    )

    assert response.status_code == 200
    assert len(groups) == 1
    assert groups[0].status == "verified"


def test_duplicate_approval_returns_404():
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate

    first = client.post(f"/api/candidates/{candidate.id}/approve")
    second = client.post(f"/api/candidates/{candidate.id}/approve")

    assert first.status_code == 200
    assert second.status_code == 404


def test_allowlist_replace_is_atomic_for_concurrent_reader(monkeypatch):
    api._save_allowlist({"before"})
    original_dump = json.dump
    dump_started = threading.Event()
    release_dump = threading.Event()
    errors: list[BaseException] = []

    def paused_dump(payload, file, *args, **kwargs):
        file.flush()
        dump_started.set()
        release_dump.wait(5)
        return original_dump(payload, file, *args, **kwargs)

    monkeypatch.setattr(api.json, "dump", paused_dump)

    def write_allowlist():
        try:
            api._save_allowlist({"after"})
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    writer = threading.Thread(target=write_allowlist)
    writer.start()
    try:
        assert dump_started.wait(5)
        for _ in range(20):
            with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
                observed = json.load(file)
            assert observed == {"aliases": ["before"]}
    finally:
        release_dump.set()
        writer.join(5)

    assert not writer.is_alive()
    assert not errors
    with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
        assert json.load(file) == {"aliases": ["after"]}


def test_concurrent_approvals_preserve_both_aliases(monkeypatch):
    first_candidate = _candidate("candidate-1", "Alpha Town", "Beta", "Alpha", "Beta")
    second_candidate = _candidate("candidate-2", "Gamma Town", "Delta", "Gamma", "Delta")
    api.pending_candidates[first_candidate.id] = first_candidate
    api.pending_candidates[second_candidate.id] = second_candidate

    real_save = api._save_allowlist
    save_count = 0
    save_count_lock = threading.Lock()
    first_save_entered = threading.Event()
    release_first_save = threading.Event()
    errors: list[BaseException] = []

    def controlled_save(aliases):
        nonlocal save_count
        with save_count_lock:
            save_count += 1
            number = save_count
        if number == 1:
            first_save_entered.set()
            release_first_save.wait(1.0)
        elif number == 2:
            release_first_save.set()
        real_save(aliases)

    def approve(candidate_id: str):
        try:
            asyncio.run(api.approve_candidate(candidate_id, _auth=None))
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    monkeypatch.setattr(api, "_save_allowlist", controlled_save)
    first_thread = threading.Thread(target=approve, args=(first_candidate.id,))
    first_thread.start()
    assert first_save_entered.wait(5)

    second_thread = threading.Thread(target=approve, args=(second_candidate.id,))
    second_thread.start()
    first_thread.join(5)
    second_thread.join(5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors
    with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
        aliases = set(json.load(file)["aliases"])
    assert aliases == {"Alpha|Alpha Town", "Gamma|Gamma Town"}


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


def test_candidate_queue_read_requires_api_key_when_configured(monkeypatch):
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate
    monkeypatch.setattr(api, "API_KEY", "secret")

    assert client.get("/api/candidates").status_code == 401
    ok = client.get("/api/candidates", headers={"X-API-Key": "secret"})

    assert ok.status_code == 200
    assert ok.json()["total"] == 1


def test_candidate_queue_is_paginated_over_http():
    for index in range(3):
        candidate = _candidate(f"candidate-{index}")
        candidate.id = f"{index:016d}"
        api.pending_candidates[candidate.id] = candidate

    first = client.get("/api/candidates?limit=2&offset=0").json()
    rest = client.get("/api/candidates?limit=2&offset=2").json()

    assert first["total"] == 3 and first["count"] == 2 and first["limit"] == 2
    assert [c["id"] for c in first["candidates"]] == ["0000000000000000", "0000000000000001"]
    assert rest["offset"] == 2
    assert [c["id"] for c in rest["candidates"]] == ["0000000000000002"]


def test_candidate_payload_carries_both_sides_and_the_link_state():
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate

    body = client.get("/api/candidates").json()["candidates"][0]

    assert body["side_a"]["home_team"] == "Lech Poznan"
    assert body["side_b"]["home_team"] == "Lech P."
    assert body["team_positions"] == [
        {"position": "home", "team_a": "Lech Poznan", "team_b": "Lech P."},
        {"position": "away", "team_a": "Thun", "team_b": "FC Thun"},
    ]
    assert body["link_blocked"] is False  # _mapping_match sets deep_link_verified
    assert body["alias_actionable"] is True
