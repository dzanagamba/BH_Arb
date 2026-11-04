"""P1-1: bounded, filtered group-evidence API.

`/api/debug/report` used to return every group and every evidence record. The
new list endpoint returns summaries in pages; the detail endpoint returns one
group's full evidence. The old path stays as a low-limit compatibility alias.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server import api
from server.app import app

client = TestClient(app)


def _row(
    group_id: int,
    *,
    status: str = "verified",
    sport: str = "football",
    evidence_count: int = 1,
) -> dict:
    return {
        "group_id": group_id,
        "sport": sport,
        "canonical_match": f"home {group_id} vs away {group_id}",
        "league": "premier_liga_bih",
        "kickoff": "2026-11-04T18:00:00",
        "status": status,
        "bookmakers": [
            {
                "bookmaker": "mbet",
                "event_id": f"event-{group_id}",
                "num_markets": 6,
                "home_team_raw": "Home",
                "away_team_raw": "Away",
                "home_normalized": "home",
                "away_normalized": "away",
                "league_raw": "Premijer Liga",
                "league_normalized": "premier_liga_bih",
            }
        ],
        "evidence": [
            {
                "rule": "team_identity",
                "source": "rule",
                "confidence": 1.0,
                "reason": "exact" if index % 2 == 0 else "swapped",
                "league_pair": [],
                "kickoff_delta_minutes": 0.0,
                "allowlist_entries": [],
                "evidence_keys": [],
            }
            for index in range(evidence_count)
        ],
    }


@pytest.fixture(autouse=True)
def restore_reports():
    saved = list(api.cached_match_groups_report)
    saved_live = list(api.cached_live_match_groups_report)
    api.cached_match_groups_report.clear()
    api.cached_live_match_groups_report.clear()
    yield
    api.cached_match_groups_report[:] = saved
    api.cached_live_match_groups_report[:] = saved_live


def test_default_list_is_bounded_and_paginated():
    api.cached_match_groups_report[:] = [_row(index) for index in range(1, 121)]

    body = client.get("/api/groups").json()

    assert body["total"] == 120
    assert body["limit"] == 50
    assert body["count"] == 50
    assert body["offset"] == 0
    assert body["has_more"] is True
    assert [group["group_id"] for group in body["groups"]] == list(range(1, 51))


def test_list_filters_and_offset():
    rows = [_row(index) for index in range(1, 21)]
    for index in range(5, 10):
        rows[index - 1]["status"] = "suggested"
    rows[2]["sport"] = "basketball"
    api.cached_match_groups_report[:] = rows

    suggested = client.get("/api/groups?status=suggested&limit=3&offset=1").json()
    assert suggested["total"] == 5
    assert suggested["count"] == 3
    assert suggested["offset"] == 1
    assert [group["group_id"] for group in suggested["groups"]] == [6, 7, 8]

    basketball = client.get("/api/groups?sport=basketball").json()
    assert basketball["total"] == 1
    assert basketball["groups"][0]["group_id"] == 3

    searched = client.get("/api/groups?search=home 12").json()
    assert searched["total"] == 1
    assert searched["groups"][0]["group_id"] == 12


def test_detail_returns_exactly_one_group_and_404s_unknown():
    api.cached_match_groups_report[:] = [_row(1), _row(2)]

    body = client.get("/api/groups/2").json()
    assert body["group"]["group_id"] == 2
    assert body["group"]["evidence"][0]["rule"] == "team_identity"

    missing = client.get("/api/groups/999")
    assert missing.status_code == 404


def test_summaries_strip_the_evidence_and_stay_small():
    api.cached_match_groups_report[:] = [
        _row(index, evidence_count=40) for index in range(1, 101)
    ]

    response = client.get("/api/groups?limit=100")
    body = response.json()

    assert body["count"] == 100
    assert "evidence" not in body["groups"][0]
    assert body["groups"][0]["evidence_count"] == 40
    assert len(response.content) < 100_000, (
        "the list endpoint must not carry the full evidence trail"
    )


def test_debug_report_is_a_low_limit_compatibility_alias():
    api.cached_match_groups_report[:] = [_row(index) for index in range(1, 121)]

    body = client.get("/api/debug/report").json()

    assert body["total_groups"] == 120
    assert body["count"] == 50
    assert body["has_more"] is True
    assert "deprecated" in body
    assert len(body["groups"]) == 50


def test_live_mode_reads_the_live_report():
    api.cached_live_match_groups_report[:] = [_row(7, sport="tennis")]

    body = client.get("/api/groups?mode=live").json()

    assert body["mode"] == "live"
    assert body["total"] == 1
    assert body["groups"][0]["sport"] == "tennis"
