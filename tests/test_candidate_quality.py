"""P2-6: the queue reports what can actually be closed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from models.schemas import CandidateReview
from server import api
from server.app import app

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
HTML = Path("frontend/index.html").read_text(encoding="utf-8")


def _candidate(
    candidate_id: str,
    *,
    alias_actionable: bool = False,
    link_blocked: bool = False,
    reasons: list[str] | None = None,
) -> CandidateReview:
    return CandidateReview(
        id=candidate_id,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="Premier Liga",
        bookmakers=["mbet", "mdshop"],
        alias_actionable=alias_actionable,
        link_blocked=link_blocked,
        rule_rejections=reasons or [],
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


def test_candidates_are_classified_by_what_can_close_them():
    queue = [
        _candidate("alias", alias_actionable=True, reasons=["link_unverified"]),
        _candidate("league", reasons=["league_mismatch"]),
        _candidate("link", link_blocked=True, reasons=["link_unverified"]),
        _candidate("other", reasons=["kickoff_delta"]),
    ]

    assert [api._candidate_blocker(row) for row in queue] == [
        "alias",
        "league",
        "link",
        "other",
    ]
    assert api._candidate_breakdown(queue) == {
        "alias": 1,
        "league": 1,
        "link": 1,
        "other": 1,
    }


def test_candidates_api_reports_blocker_counts_even_when_filtered(monkeypatch):
    monkeypatch.setattr(
        api,
        "pending_candidates",
        {
            "alias": _candidate("alias", alias_actionable=True),
            "league": _candidate("league", reasons=["league_mismatch"]),
            "link": _candidate("link", link_blocked=True, reasons=["link_unverified"]),
        },
    )
    client = TestClient(app)

    payload = client.get("/api/candidates?actionable_only=true").json()

    assert payload["total"] == 3
    assert payload["actionable_total"] == 1
    assert payload["count"] == 1
    assert payload["blocker_counts"] == {"alias": 1, "league": 1, "link": 1, "other": 0}


def test_health_reports_candidate_blockers_per_feed(monkeypatch):
    monkeypatch.setattr(
        api,
        "pending_candidates",
        {"league": _candidate("league", reasons=["league_mismatch"])},
    )
    monkeypatch.setattr(api, "pending_live_candidates", {})

    body = TestClient(app).get("/api/health").json()

    assert body["candidate_blockers"]["prematch"]["league"] == 1
    assert body["candidate_blockers"]["live"] == {
        "alias": 0,
        "league": 0,
        "link": 0,
        "other": 0,
    }


def test_history_records_the_queue_and_actionable_counts(monkeypatch):
    monkeypatch.setattr(
        api,
        "pending_candidates",
        {
            "alias": _candidate("alias", alias_actionable=True),
            "other": _candidate("other", reasons=["kickoff_delta"]),
        },
    )
    monkeypatch.setattr(api, "scan_history", [])
    monkeypatch.setattr(api, "_save_history", lambda *args, **kwargs: None)
    monkeypatch.setattr(api.scan_status, "total_matches", 10)
    monkeypatch.setattr(api.scan_status, "surebets_found", 2)
    monkeypatch.setattr(api.scan_status, "last_scan_time", None)

    api._append_history(4, "prematch")

    entry = api.scan_history[0]
    assert entry["candidate_queue"] == 2
    assert entry["candidate_actionable"] == 1


def test_dashboard_shows_the_blocker_breakdown_and_queue_trend():
    assert "blocker_counts" in JS
    assert "league-blocked" in JS
    assert "link-pending" in JS
    assert "candidate_actionable" in JS
    assert "candidate_queue" in JS
    assert "Queue:" in JS
    assert "<th>Queue</th>" in HTML
