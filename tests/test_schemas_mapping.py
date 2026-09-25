"""Schemas for mapping certainty: statuses, evidence, deep-link metadata."""
from datetime import datetime

from models.schemas import CandidateReview, Match, MatchEvidence, MatchGroup


def test_match_group_defaults_to_suggested_with_empty_evidence():
    g = MatchGroup(canonical_home="a", canonical_away="b")
    assert g.status == "suggested"
    assert g.evidence == []


def test_match_group_accepts_verified_status_and_evidence():
    g = MatchGroup(
        canonical_home="a", canonical_away="b", status="verified",
        evidence=[MatchEvidence(rule="league_identity", source="rule", confidence=1.0)],
    )
    assert g.status == "verified"
    assert g.evidence[0].rule == "league_identity"
    assert g.evidence[0].source == "rule"


def test_match_exposes_deep_link_metadata():
    m = Match(bookmaker="mdshop", home_team="A", away_team="B", event_id="123", deep_link_verified=True)
    assert m.event_id == "123"
    assert m.deep_link_verified is True


def test_candidate_review_defaults_pending():
    c = CandidateReview(
        id="c1", home_team="A", away_team="B", league="L", kickoff=datetime(2026, 9, 25, 18, 0),
        bookmakers=["mdshop", "mbet"], created_at=datetime(2026, 9, 25, 12, 0),
    )
    assert c.status == "pending"
    assert c.ai_confidence == 0.0
    assert c.rule_rejections == []
