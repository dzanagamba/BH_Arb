"""The pairing audit measures unpaired same-fixture offers, not raw counts."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.pairing_audit import audit, main

KICKOFF = "2026-11-07T18:00:00"


def _match(book: str, home: str, away: str, event_id: str, league: str = "league") -> dict:
    return {
        "bookmaker": book,
        "home_team": home,
        "away_team": away,
        "home_team_normalized": home.lower(),
        "away_team_normalized": away.lower(),
        "league_normalized": league,
        "kickoff": KICKOFF,
        "event_id": event_id,
    }


def _group(group_id: int, members: list[dict]) -> dict:
    return {
        "group_id": group_id,
        "canonical_match": f"{members[0]['home_team']} vs {members[0]['away_team']}",
        "league": members[0]["league_normalized"],
        "kickoff": KICKOFF,
        "status": "verified",
        "bookmakers": [
            {
                "bookmaker": member["bookmaker"],
                "event_id": member["event_id"],
                "home_team_raw": member["home_team"],
                "away_team_raw": member["away_team"],
                "league_normalized": member["league_normalized"],
            }
            for member in members
        ],
    }


def _cache(matches: list[dict], groups: list[dict]) -> dict:
    return {"matches": matches, "match_groups": groups, "scan_time": KICKOFF}


def test_a_same_fixture_offer_left_out_of_its_group_is_a_strict_miss():
    a = _match("a", "Alpha", "Beta", "1")
    b = _match("b", "Alpha", "Beta", "2")
    c = _match("c", "Alpha", "Beta", "3")
    cache = _cache([a, b, c], [_group(1, [a, b])])

    report = audit(cache)

    assert report["strict_misses"] == 1
    assert report["strict_miss_examples"][0]["bookmaker"] == "c"
    assert report["strict_miss_rate"] == round(1 / 3, 4)
    assert report["duplicate_book_groups"] == []


def test_a_second_listing_from_a_book_already_in_the_group_is_not_a_miss():
    a = _match("a", "Alpha", "Beta", "1")
    b = _match("b", "Alpha", "Beta", "2")
    a2 = _match("a", "Alpha", "Beta", "3")
    cache = _cache([a, b, a2], [_group(1, [a, b])])

    report = audit(cache)

    assert report["strict_misses"] == 0
    assert report["duplicate_listings"] == 1


def test_a_group_that_repeats_a_bookmaker_fails_the_check(tmp_path: Path):
    a = _match("a", "Alpha", "Beta", "1")
    a2 = _match("a", "Alpha", "Beta", "2")
    cache = _cache([a, a2], [_group(1, [a, a2])])
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(cache), encoding="utf-8")

    report = audit(cache)

    assert report["duplicate_book_groups"] == [1]
    assert main(["--cache", str(cache_path), "--check"]) == 1


def test_a_clean_scan_passes_the_check(tmp_path: Path):
    a = _match("a", "Alpha", "Beta", "1")
    b = _match("b", "Alpha", "Beta", "2")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(_cache([a, b], [_group(1, [a, b])])), encoding="utf-8")

    assert main(["--cache", str(cache_path), "--check"]) == 0
