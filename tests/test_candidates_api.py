"""Candidates review endpoints and health diagnostics."""

import asyncio
import json
import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from config.settings import BOOKMAKERS
from engine.matcher import MatchMatcher
from models.schemas import CandidateReview, Match
from scrapers import common
from scrapers.common import declares_no_event_id, effective_deeplink_declarations
from server import api
from server.app import app

client = TestClient(app)

# Read through the loader the gate itself uses, so the expectation cannot drift
# from the declarations it is about and needs no second copy of the config.
def _route_books() -> set[str]:
    return {
        book
        for book, entry in effective_deeplink_declarations(BOOKMAKERS).items()
        if entry["supports_event_id"] is True
    }


@pytest.fixture(autouse=True)
def reset_candidate_state(monkeypatch, tmp_path):
    # The old review path is a migration tool, not a default trust source.
    monkeypatch.setattr(api, "HUMAN_MAPPING_ENABLED", True)
    original_pending = api.pending_candidates.copy()
    original_live_pending = api.pending_live_candidates.copy()
    original_reviews = api.candidate_reviews.copy()
    original_report = api.cached_match_groups_report.copy()
    original_matches = api.cached_matches.copy()
    original_unmapped = api.unmapped_markets.copy()
    original_suppressed = dict(api._suppressed_candidates)
    api.pending_candidates.clear()
    api.pending_live_candidates.clear()
    api.candidate_reviews.clear()
    api._suppressed_candidates.clear()
    monkeypatch.setattr(api, "ALLOWLIST_FILE", str(tmp_path / "team_alias_allowlist.json"))
    monkeypatch.setattr(
        api, "SUPPRESSED_CANDIDATES_FILE", str(tmp_path / "suppressed_candidates.json")
    )
    yield
    api.pending_candidates.clear()
    api.pending_candidates.update(original_pending)
    api.pending_live_candidates.clear()
    api.pending_live_candidates.update(original_live_pending)
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
    api.pending_live_candidates[candidate.id] = candidate

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
            {
                "bookmaker": "mdshop",
                "event_id": "verified",
                "deep_link_verified": True,
            },
            {
                "bookmaker": "mdshop",
                "event_id": "unverified",
                "deep_link_verified": False,
            },
            # A book that declares `supports_event_id: false` has no per-event
            # link to prove, so its unproven link is not what is holding a group
            # back. Counting it would report thousands of blockers that block
            # nothing.
            {
                "bookmaker": "wwin",
                "event_id": "no-route",
                "deep_link_verified": False,
            },
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
        "deep_link_declarations",
    ):
        assert key in body


def test_health_counts_an_undeclared_books_link_as_a_blocker(monkeypatch):
    """`unverified_links` must use the gate's predicate, not `supports_event_id`.

    The two agree for every book that has a declaration, which is every book
    today, so the wrong one looked right. They part company on a book with **no**
    declaration, and that is the case the diagnostic exists for: the gate fails
    safe and refuses every group holding it, so an operator needs to see the
    count. Under `supports_event_id` a removed declaration reports
    `unverified_links: 0` while the gate blocks everything — the diagnostic goes
    dark exactly when it is needed.

    Driven by emptying the config cache the process already holds, which is the
    shape of the accident: a declaration is removed from the JSON, the process is
    not restarted, and both the gate and this counter are answering from the same
    old map. `_deeplink_cache` is the one piece of state both read, so emptying it
    takes the real code path rather than replacing the predicate under test.
    """
    api.cached_matches[:] = [
        {"bookmaker": "mdshop", "event_id": "declared-route", "deep_link_verified": False},
        {"bookmaker": "wwin", "event_id": "declared-no-route", "deep_link_verified": False},
        {"bookmaker": "mdshop", "event_id": "already-proven", "deep_link_verified": True},
        {"bookmaker": "mdshop", "event_id": "", "deep_link_verified": False},
    ]
    body = client.get("/api/health").json()
    assert body["unverified_links"] == 1, (
        "with the config as shipped, mdshop's unproven link is the only real blocker: "
        "wwin declares no route and the gate settles it from that declaration"
    )

    monkeypatch.setattr(common, "_deeplink_cache", {})
    assert not declares_no_event_id("mdshop"), "the premise: no book declares anything now"
    dark = client.get("/api/health").json()
    assert dark["unverified_links"] == 2, (
        "with no declaration anywhere the gate blocks both unproven matches, so the count "
        f"must rise from 1 to 2 and not stay at {dark['unverified_links']}: reporting 1 "
        "here is the gate blocking everything while health says almost nothing is wrong"
    )


def test_health_echoes_the_declaration_map_the_gate_is_using():
    """The operative configuration has to be observable, not just the file on disk.

    `scrapers.common._deeplink_cache` is populated on first use and never
    invalidated, and it is now load-bearing for a safety gate. Editing
    `config/bookmaker_deeplinks.json` therefore needs a process restart — which
    used to be nowhere stated and nowhere visible. The map below is built from the
    same cache the gate reads, so an operator can see the value in force.

    Each entry carries three fields, and the third is the reason there are three:
    `supports_event_id` and `declared_no_event_id` are not complements, because a
    book that declares neither must fail safe — and `declared_no_event_id` alone
    cannot express "unconfigured", which is the state a removed declaration puts
    a book in.
    """
    body = client.get("/api/health").json()
    declarations = body["deep_link_declarations"]

    assert set(declarations) == set(BOOKMAKERS), (
        "health must report every configured book, including one the config does not "
        "cover, or a removed declaration is invisible"
    )
    for bookmaker, entry in declarations.items():
        assert set(entry) == {"configured", "supports_event_id", "declared_no_event_id"}, entry
        assert entry["configured"] is True, f"{bookmaker} is configured and must say so"
        assert entry["supports_event_id"] in (True, False, None)
        if entry["supports_event_id"] is True:
            assert entry["declared_no_event_id"] is False
        else:
            assert entry["declared_no_event_id"] is (entry["supports_event_id"] is False)

    # The gate is reading the same thing, which is the only reason this is useful.
    for bookmaker, entry in declarations.items():
        assert entry["declared_no_event_id"] == declares_no_event_id(bookmaker), bookmaker
        assert entry["supports_event_id"] is (bookmaker in _route_books()), bookmaker

    # And the effective map, not the file: a book the gate cannot see is reported
    # as unconfigured rather than silently omitted.
    unseen = effective_deeplink_declarations(["never-declared-book"])
    assert unseen["never-declared-book"] == {
        "configured": False,
        "supports_event_id": None,
        "declared_no_event_id": False,
    }


def test_approve_unknown_candidate_returns_404():
    r = client.post("/api/candidates/does-not-exist/approve")
    assert r.status_code == 404


def test_reject_unknown_candidate_returns_404():
    r = client.post("/api/candidates/does-not-exist/reject")
    assert r.status_code == 404






def test_candidates_carry_a_name_score_for_ranking():
    api.pending_candidates["c-1"] = _candidate("c-1")
    body = client.get("/api/candidates").json()
    assert 0 < body["candidates"][0]["name_score"] <= 100






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




def test_legacy_candidate_mutation_routes_are_gone():
    candidate = _candidate()
    api.pending_candidates[candidate.id] = candidate
    assert client.post(f"/api/candidates/{candidate.id}/approve").status_code == 404
    assert client.post(f"/api/candidates/{candidate.id}/reject").status_code == 404
    assert client.post("/api/candidates/approve-bulk", json={"ids": []}).status_code == 404


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


def test_candidate_queue_can_be_filtered_to_pairs_an_approval_clears():
    """The Review tab asks for this filter, and the counts must describe it.

    A full scan queues thousands of pairs and most are refused for a reason no
    human decision moves (a league gap, a kickoff no approval can shift, a name
    pair below the reviewed-alias floor). Showing those cards with an Approve
    button promises a fix that does not exist: approving writes an alias the gate
    will not honour and suppresses the pair forever. The filter is what makes the
    tab's sentence true, so the endpoint has to serve it and say how much of the
    queue it is not showing.
    """
    actionable = _candidate("actionable")
    unclosable = _candidate("unclosable").model_copy(
        update={
            "alias_actionable": False,
            "rule_rejections": ["league_mismatch", "kickoff_delta", "team_unresolved"],
        }
    )
    api.pending_candidates[actionable.id] = actionable
    api.pending_candidates[unclosable.id] = unclosable

    full = client.get("/api/candidates").json()
    filtered = client.get("/api/candidates?actionable_only=true").json()

    assert full["total"] == 2
    assert full["actionable_total"] == 1
    assert {c["id"] for c in full["candidates"]} == {"actionable", "unclosable"}

    assert filtered["total"] == 2, "the queue size is the same fact either way"
    assert filtered["actionable_total"] == 1
    assert [c["id"] for c in filtered["candidates"]] == ["actionable"]
    assert filtered["actionable_only"] is True




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


def test_live_and_prematch_queues_are_separate():
    prematch = _candidate()
    live = _candidate().model_copy(update={"id": "live-only-candidate"})
    api.pending_candidates[prematch.id] = prematch
    api.pending_live_candidates[live.id] = live
    try:
        prematch_ids = {c["id"] for c in client.get("/api/candidates").json()["candidates"]}
        live_body = client.get("/api/candidates?mode=live").json()
        assert prematch.id in prematch_ids and live.id not in prematch_ids
        assert live_body["mode"] == "live"
        assert [c["id"] for c in live_body["candidates"]] == [live.id]
        assert prematch.id in api.pending_candidates
    finally:
        api.pending_live_candidates.pop(live.id, None)
        api._suppressed_candidates.pop(live.id, None)
        api._suppressed_premises.pop(live.id, None)


def test_legacy_approval_routes_are_absent():
    assert client.post("/api/candidates/does-not-exist/approve").status_code == 404
    assert client.post("/api/candidates/does-not-exist/reject").status_code == 404
    assert client.post("/api/candidates/approve-bulk", json={"ids": []}).status_code == 404
