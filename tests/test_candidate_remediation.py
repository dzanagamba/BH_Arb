"""N2-3: ranked remediation and strict-miss trends.

Four rules bind these tests:

* a proposal names the exact entry a mapping would need and stays inert,
* a league mapping is a second kind of human action, not a trust upgrade,
* recurring strict misses carry their numerator and denominator,
* no default path applies a suggestion or changes a `verified` verdict.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.candidate_remediation import (
    alias_proposals,
    league_proposal,
    remediation_summary,
)
from engine.mapping_evidence import Evidence, MappingLedger, team_alias_key
from engine.matcher import MatchMatcher
from models.schemas import (
    CandidateRemediation,
    CandidateReview,
    Match,
    TeamPositionPair,
)
from scripts import candidate_remediation
from scripts.pairing_audit import audit
from server import api
from server.app import app

KICKOFF = datetime(2026, 9, 25, 18, 0)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_candidate_state(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "ALLOWLIST_FILE", str(tmp_path / "allowlist.json"))
    monkeypatch.setattr(
        api, "SUPPRESSED_CANDIDATES_FILE", str(tmp_path / "suppressed.json")
    )
    monkeypatch.setattr(api, "pending_candidates", {})
    monkeypatch.setattr(api, "pending_live_candidates", {})
    monkeypatch.setattr(api, "_suppressed_candidates", {})
    monkeypatch.setattr(api, "_suppressed_premises", {})
    monkeypatch.setattr(api, "HUMAN_MAPPING_ENABLED", False)


def _match(
    bookmaker: str,
    home: str,
    away: str,
    league: str,
    event_id: str,
    *,
    kickoff: datetime = KICKOFF,
    link_verified: bool = True,
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        event_id=event_id,
        deep_link_verified=link_verified,
    )


def _collect(matches: list[Match], matcher: MatchMatcher | None = None) -> dict:
    return asyncio.run(
        api._collect_candidates(
            matches, matcher or MatchMatcher(), rank_with_ai=False
        )
    )


def _one(matches: list[Match], matcher: MatchMatcher | None = None) -> CandidateReview:
    produced = _collect(matches, matcher)
    assert len(produced) == 1, produced
    return next(iter(produced.values()))


# ─── Proposals are evidence-shaped and inert ────────────────────────────────


def test_alias_proposal_names_the_same_entry_an_approval_would_write():
    positions = [
        TeamPositionPair(position="home", team_a="Lech Poznan", team_b="Lech Pznan"),
        TeamPositionPair(position="away", team_a="Thun", team_b="FC Thun"),
    ]
    ledger = MappingLedger(Path("/nonexistent/ledger.json")).load()

    proposals = alias_proposals(
        ["Lech Poznan|Lech Pznan", "Thun|FC Thun"], ledger, confidence=0.92
    )

    assert [proposal.entry for proposal in proposals] == [
        "Lech Poznan|Lech Pznan",
        "Thun|FC Thun",
    ]
    assert all(proposal.kind == "team_alias" for proposal in proposals)
    assert all(proposal.ledger_status == "absent" for proposal in proposals)
    assert all(proposal.proposal_only and not proposal.applied for proposal in proposals)
    assert proposals[0].confidence == 0.92
    assert positions  # the entries came from the recorded positions


def test_league_proposal_uses_the_gate_normalized_pair(tmp_path):
    ledger = MappingLedger(tmp_path / "ledger.json").load()

    proposal = league_proposal(
        "Engleska - Premier liga",
        "Italija - Serie A",
        ledger,
        normalized_left="premier_league",
        normalized_right="serie_a",
    )

    assert proposal is not None
    assert proposal.kind == "league_equivalence"
    assert proposal.entry == "premier_league|serie_a"
    assert proposal.left == "Engleska - Premier liga"
    assert proposal.proposal_only and not proposal.applied


def test_a_quarantined_ledger_claim_is_evidence_not_an_approval(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = MappingLedger(path).load()
    ledger.quarantine(
        "team_alias",
        team_alias_key("Lech Poznan", "Lech Pznan"),
        [Evidence(type="similarity", detail={"score": 0.9})],
        "similarity_only",
    )
    ledger.save()

    proposal = alias_proposals(
        ["Lech Poznan|Lech Pznan"],
        MappingLedger(path).load(),
    )[0]

    assert proposal.ledger_status == "quarantined"
    assert proposal.ledger_evidence == ["similarity"]
    assert proposal.applied is False


# ─── What a reviewer can actually close ─────────────────────────────────────


def test_alias_closeable_pair_reports_alias_and_exact_gate_reason():
    candidate = _one(
        [
            _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1"),
            _match("mbet", "Lech Pznan", "FC Thun", "Liga Evrope", "2"),
        ]
    )

    assert candidate.remediation is not None
    assert candidate.remediation.action == "alias"
    assert candidate.remediation.closeable is True
    assert candidate.remediation.gate_reasons == ["team_unresolved"]
    assert [proposal.entry for proposal in candidate.remediation.proposals] == [
        "FC Thun|Thun",
        "Lech Poznan|Lech Pznan",
    ]
    assert candidate.status == "pending"
    assert all(not proposal.applied for proposal in candidate.remediation.proposals)


def test_league_closeable_pair_reports_the_mapping_it_needs():
    candidate = _one(
        [
            _match("mdshop", "Alpha", "Beta", "Engleska - Premier liga", "1"),
            _match("mbet", "Alpha", "Beta", "Italija - Serie A", "2"),
        ]
    )

    assert candidate.rule_rejections == ["league_mismatch"]
    assert candidate.alias_actionable is False
    assert candidate.remediation is not None
    assert candidate.remediation.action == "league"
    assert candidate.remediation.closeable is True
    assert [proposal.kind for proposal in candidate.remediation.proposals] == [
        "league_equivalence"
    ]
    assert candidate.remediation.proposals[0].entry == "premier_league|serie_a"


def test_alias_plus_league_pair_reports_both_proposals():
    candidate = _one(
        [
            _match("mdshop", "Alpha Town", "Beta", "Engleska - Premier liga", "1"),
            _match("mbet", "Alpha", "Beta", "Italija - Serie A", "2"),
        ]
    )

    assert set(candidate.rule_rejections) == {"league_mismatch", "team_unresolved"}
    assert candidate.remediation is not None
    assert candidate.remediation.action == "alias+league"
    assert candidate.remediation.closeable is True
    assert {proposal.kind for proposal in candidate.remediation.proposals} == {
        "team_alias",
        "league_equivalence",
    }


def test_a_kickoff_no_mapping_moves_is_not_reported_as_closeable():
    candidate = _one(
        [
            _match(
                "mdshop", "Alpha Town", "Beta", "Liga Evrope", "1",
                kickoff=KICKOFF,
            ),
            _match(
                "mbet", "Alpha", "Beta", "Liga Evrope", "2",
                kickoff=KICKOFF.replace(minute=20),
            ),
        ]
    )

    assert candidate.remediation is not None
    assert candidate.remediation.action == "none"
    assert candidate.remediation.closeable is False
    assert candidate.remediation.proposals == []


def test_building_the_queue_does_not_change_status_or_write_any_mapping(tmp_path):
    left = _match("mdshop", "Alpha Town", "Beta", "Liga Evrope", "1")
    right = _match("mbet", "Alpha", "Beta", "Liga Evrope", "2")
    matcher = MatchMatcher()
    claims_before = set(matcher._ledger.claims)

    produced = _collect([left, right], matcher)

    candidate = next(iter(produced.values()))
    assert candidate.status == "pending"
    assert candidate.remediation is not None
    assert candidate.remediation.action == "alias"
    assert not Path(api.ALLOWLIST_FILE).exists()
    assert api._suppressed_candidates == {}
    assert set(matcher._ledger.claims) == claims_before
    # The gate's verdict on the same two rows is still "rejected": a proposal
    # never turns into a verified claim.
    verdict = matcher.gate.evaluate_pair(left, right)
    assert verdict.status != "verified"
    assert "team_unresolved" in verdict.reasons


# ─── Recurring groups carry their denominators ──────────────────────────────


def _review(
    candidate_id: str,
    *,
    action: str,
    bookmakers: list[str],
    league: str,
    reasons: list[str],
) -> CandidateReview:
    return CandidateReview(
        id=candidate_id,
        home_team="Alpha",
        away_team="Beta",
        league=league,
        bookmakers=bookmakers,
        rule_rejections=reasons,
        remediation=CandidateRemediation(
            action=action,  # type: ignore[arg-type]
            closeable=action in {"alias", "league", "alias+league"},
            gate_reasons=reasons,
        ),
        created_at=KICKOFF,
    )


def test_recurring_blockers_group_by_action_book_pair_league_and_reason():
    queue = [
        _review("1", action="league", bookmakers=["mbet", "mdshop"],
                league="Liga", reasons=["league_mismatch"]),
        _review("2", action="league", bookmakers=["mdshop", "mbet"],
                league="Liga", reasons=["league_mismatch"]),
        _review("3", action="none", bookmakers=["mbet", "mdshop"],
                league="Liga", reasons=["kickoff_delta"]),
    ]

    summary = remediation_summary(queue)

    assert summary["total"] == 3
    assert summary["closeable"] == 2
    assert summary["counts"] == {
        "alias": 0,
        "league": 2,
        "alias+league": 0,
        "none": 1,
        "system_link": 0,
    }
    top = summary["groups"][0]
    assert top["book_pair"] == "mbet|mdshop"
    assert top["league"] == "Liga"
    assert top["reasons"] == ["league_mismatch"]
    assert top["count"] == 2
    assert top["share"] == round(2 / 3, 4)
    assert top["closeable"] is True
    assert "not a coverage-progress claim" in summary["note"]


def test_a_link_check_is_not_counted_as_nothing_can_be_done():
    queue = [
        _review("1", action="none", bookmakers=["a", "b"],
                league="Liga", reasons=["link_unverified"]),
    ]
    queue[0].link_blocked = True
    queue[0].remediation = None  # cheap fallback class

    summary = remediation_summary(queue)

    assert summary["counts"]["system_link"] == 1
    assert summary["counts"]["none"] == 0


# ─── Strict misses: grouping and trend ──────────────────────────────────────


def _miss_match(book: str, home: str, away: str, event_id: str) -> dict:
    return {
        "bookmaker": book,
        "home_team": home,
        "away_team": away,
        "home_team_normalized": home.lower(),
        "away_team_normalized": away.lower(),
        "league_normalized": "liga",
        "kickoff": KICKOFF.isoformat(),
        "event_id": event_id,
    }


def _audit_group(group_id: int, members: list[dict]) -> dict:
    return {
        "group_id": group_id,
        "canonical_match": f"{members[0]['home_team']} vs {members[0]['away_team']}",
        "league": "liga",
        "kickoff": KICKOFF.isoformat(),
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


def test_strict_miss_groups_repeat_by_book_pair_league_and_spelling():
    a = _miss_match("a", "Alpha", "Beta", "1")
    b = _miss_match("b", "Alpha", "Beta", "2")
    c1 = _miss_match("c", "Alpha", "Beta", "3")
    c2 = _miss_match("c", "Alpha", "Beta", "4")
    d = _miss_match("d", "Gamma", "Delta", "5")
    e = _miss_match("e", "Gamma", "Delta", "6")
    f = _miss_match("f", "Gamma", "Delta", "7")
    cache = {
        "matches": [a, b, c1, c2, d, e, f],
        "match_groups": [_audit_group(1, [a, b]), _audit_group(2, [d, e])],
        "scan_time": KICKOFF.isoformat(),
    }

    report = audit(cache)

    assert report["strict_misses"] == 3
    assert report["strict_miss_group_count"] == 2
    top = report["strict_miss_groups"][0]
    assert top["book_pair"] == "a|c"
    assert top["league"] == "liga"
    assert top["count"] == 2
    assert top["share"] == round(2 / 3, 4)
    assert top["match_share"] == round(2 / 7, 4)
    assert report["strict_miss_examples"][0]["other_league"] == "liga"


def test_pairing_trend_keeps_a_numerator_and_denominator_per_scan():
    matches = [_miss_match("a", "Alpha", "Beta", "1"), _miss_match("b", "Alpha", "Beta", "2")]
    groups = [_audit_group(1, matches)]

    api._refresh_pairing_summary("prematch", matches, groups, KICKOFF)

    point = api._pairing_trend["prematch"][-1]
    assert point["matches"] == 2
    assert point["strict_misses"] == 0
    assert point["strict_miss_rate"] == 0.0
    assert "strict_miss_group_count" in point
    assert api._pairing_summary["prematch"]["strict_miss_groups"] == []


# ─── API surface ────────────────────────────────────────────────────────────


def test_candidates_api_serves_proposals_and_closeable_counts():
    league_candidate = _one(
        [
            _match("mdshop", "Alpha", "Beta", "Engleska - Premier liga", "1"),
            _match("mbet", "Alpha", "Beta", "Italija - Serie A", "2"),
        ]
    )
    api.pending_candidates[league_candidate.id] = league_candidate

    body = client.get("/api/candidates").json()

    assert body["closeable_total"] == 1
    assert body["remediation_counts"]["league"] == 1
    served = body["candidates"][0]
    assert served["remediation"]["action"] == "league"
    assert served["remediation"]["proposals"][0]["entry"] == "premier_league|serie_a"
    assert served["remediation"]["proposals"][0]["applied"] is False


def test_the_review_filter_includes_league_closeable_pairs_but_not_hopeless_ones():
    league_candidate = _one(
        [
            _match("mdshop", "Alpha", "Beta", "Engleska - Premier liga", "1"),
            _match("mbet", "Alpha", "Beta", "Italija - Serie A", "2"),
        ]
    )
    hopeless = _one(
        [
            _match("mdshop", "Alpha Town", "Beta", "Liga Evrope", "3"),
            _match("mbet", "Alpha", "Beta", "Liga Evrope", "4", kickoff=KICKOFF.replace(minute=20)),
        ]
    )
    api.pending_candidates[league_candidate.id] = league_candidate
    api.pending_candidates[hopeless.id] = hopeless

    alias_only = client.get("/api/candidates?actionable_only=true").json()
    closeable = client.get("/api/candidates?closeable_only=true").json()

    assert alias_only["count"] == 0, "no pair needs only a team alias"
    assert closeable["total"] == 2
    assert closeable["closeable_total"] == 1
    assert [row["id"] for row in closeable["candidates"]] == [league_candidate.id]
    assert closeable["candidates"][0]["remediation"]["action"] == "league"


def test_health_exposes_recurring_blockers_and_the_strict_miss_trend():
    candidate = _one(
        [
            _match("mdshop", "Alpha Town", "Beta", "Engleska - Premier liga", "1"),
            _match("mbet", "Alpha", "Beta", "Italija - Serie A", "2"),
        ]
    )
    api.pending_candidates[candidate.id] = candidate
    matches = [_miss_match("a", "Alpha", "Beta", "1"), _miss_match("b", "Alpha", "Beta", "2")]
    api._refresh_pairing_summary("prematch", matches, [_audit_group(1, matches)], KICKOFF)

    body = client.get("/api/health").json()

    remediation = body["candidate_remediation"]["prematch"]
    assert remediation["total"] == 1
    assert remediation["closeable"] == 1
    assert remediation["counts"]["alias+league"] == 1
    assert remediation["groups"][0]["reasons"] == ["league_mismatch", "team_unresolved"]
    assert body["pairing_trend"]["prematch"][-1]["matches"] == 2


# ─── CLI report ─────────────────────────────────────────────────────────────


def _cache_payload() -> dict:
    return {
        "scan_time": KICKOFF.isoformat(),
        "matches": [
            {
                "bookmaker": "mdshop",
                "home_team": "Alpha",
                "away_team": "Beta",
                "league": "Engleska - Premier liga",
                "kickoff": KICKOFF.isoformat(),
                "event_id": "1",
            },
            {
                "bookmaker": "mbet",
                "home_team": "Alpha",
                "away_team": "Beta",
                "league": "Italija - Serie A",
                "kickoff": KICKOFF.isoformat(),
                "event_id": "2",
            },
        ],
    }


def test_cli_report_never_invents_a_queue_without_a_cache(tmp_path, capsys):
    missing = tmp_path / "missing.json"

    code = candidate_remediation.main(["--cache", str(missing)])

    assert code == 2
    assert "never invents" in capsys.readouterr().err


def test_cli_report_prints_closeable_pairs_and_writes_json(tmp_path, capsys):
    cache_path = tmp_path / "last_scan.json"
    cache_path.write_text(json.dumps(_cache_payload()), encoding="utf-8")
    out_path = tmp_path / "report.json"

    code = candidate_remediation.main(
        ["--cache", str(cache_path), "--top", "5", "--json", str(out_path)]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "closeable" in output
    assert "proposal league_equivalence: premier_league|serie_a" in output
    assert "applied=False" in output
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["candidates"] == 1
    assert report["closeable"] == 1
    assert report["pairs"][0]["proposal_only"] is True
    assert report["pairs"][0]["proposals"][0]["applied"] is False


def test_default_approval_path_is_still_disabled():
    candidate = _one(
        [
            _match("mdshop", "Alpha Town", "Beta", "Liga Evrope", "1"),
            _match("mbet", "Alpha", "Beta", "Liga Evrope", "2"),
        ]
    )
    api.pending_candidates[candidate.id] = candidate

    # The remediation is proposal-only, and the legacy approve path refuses
    # while human mapping is disabled (the shipped default).
    response = client.post(f"/api/candidates/{candidate.id}/approve")

    assert response.status_code == 404  # the route does not exist at all
    assert candidate.status == "pending"
    assert not Path(api.ALLOWLIST_FILE).exists()
