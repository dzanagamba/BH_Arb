"""Per-sport reporting survives the cache/API boundary."""

from __future__ import annotations

from server.api import _sport_summary


def test_sport_summary_counts_matches_groups_and_surebets():
    matches = [
        {"sport": "football", "bookmaker": "a"},
        {"sport": "basketball", "bookmaker": "b"},
    ]
    report = [
        {"sport": "football", "status": "verified"},
        {"sport": "basketball", "status": "verified"},
        {"sport": "tennis", "status": "suggested"},
    ]
    surebets = [{"sport": "basketball"}, {"sport": "football"}]
    summary = _sport_summary(matches, report, surebets)
    assert summary["football"] == {
        "matches": 1, "groups": 1, "verified_groups": 1, "surebets": 1
    }
    assert summary["basketball"] == {
        "matches": 1, "groups": 1, "verified_groups": 1, "surebets": 1
    }
    assert summary["tennis"] == {
        "matches": 0, "groups": 1, "verified_groups": 0, "surebets": 0
    }


def test_old_cache_rows_default_to_football():
    summary = _sport_summary([{"bookmaker": "a"}], [{"status": "verified"}], [{}])
    assert summary["football"]["matches"] == 1
    assert summary["football"]["surebets"] == 1
