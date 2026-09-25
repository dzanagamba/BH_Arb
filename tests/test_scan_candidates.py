"""run_scan populates candidate reviews for ambiguous pairs.

`run_scan` is the only producer of `pending_candidates`. Two rules bind every
test here:

* the queue is rebuilt from scratch on every scan, and
* the AI only *ranks* a candidate — it can never approve or create one.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from engine.ai import PairProposal
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from server import api

KICKOFF = datetime(2026, 9, 25, 18, 0)


def run(coro):
    return asyncio.run(coro)


def _match(
    bookmaker: str,
    home_team: str,
    away_team: str,
    league: str,
    event_id: str,
    kickoff: datetime = KICKOFF,
    deep_link_verified: bool = True,
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team=home_team,
        away_team=away_team,
        league=league,
        kickoff=kickoff,
        event_id=event_id,
        deep_link_verified=deep_link_verified,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label="1", value=2.0),
                    OddsValue(label="X", value=3.0),
                    OddsValue(label="2", value=3.0),
                ],
            )
        ],
    )


def _ambiguous_pair() -> tuple[Match, Match]:
    """Same kickoff, 70%+ team overlap, mismatched canonical leagues."""
    return (
        _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1"),
        _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2"),
    )


def _one_ambiguous_pair() -> dict:
    return run(api._collect_candidates(list(_ambiguous_pair()), MatchMatcher()))


def _fake_ai(monkeypatch, proposals, available=True, calls=None):
    """Install a fake MatchAI that records the pairs it is asked about."""
    recorded = calls if calls is not None else []

    class FakeAI:
        def __init__(self):
            self.calls = recorded
            self.closed = False

        @property
        def available(self):
            return available

        async def suggest_pairs(self, pairs):
            self.calls.append(pairs[0])
            return list(proposals)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(api, "MatchAI", FakeAI)
    return recorded


@pytest.fixture(autouse=True)
def isolate_scan_state(monkeypatch):
    """Keep the global scan state out of every other test module."""
    snapshot = {
        "pending": dict(api.pending_candidates),
        "reviews": list(api.candidate_reviews),
        "enabled": dict(api._bookmaker_enabled),
        "history": list(api.scan_history),
        "surebets": list(api.cached_surebets),
        "matches": list(api.cached_matches),
        "report": list(api.cached_match_groups_report),
        "per_bookie": dict(api.cached_per_bookie),
        "status": api.scan_status.model_dump(),
    }
    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "_append_history", lambda *a, **k: None)
    yield
    api.pending_candidates.clear()
    api.pending_candidates.update(snapshot["pending"])
    api.candidate_reviews[:] = snapshot["reviews"]
    api._bookmaker_enabled.clear()
    api._bookmaker_enabled.update(snapshot["enabled"])
    api.scan_history[:] = snapshot["history"]
    api.cached_surebets[:] = snapshot["surebets"]
    api.cached_matches[:] = snapshot["matches"]
    api.cached_match_groups_report[:] = snapshot["report"]
    api.cached_per_bookie.clear()
    api.cached_per_bookie.update(snapshot["per_bookie"])
    for key, value in snapshot["status"].items():
        setattr(api.scan_status, key, value)


@pytest.fixture
def stub_scan_inputs(monkeypatch):
    """Two books, one plausible-but-unverifiable same-event pair."""
    class FakeMatcher:
        def group_matches(self, matches):
            return []

        def get_match_report(self, groups):
            return []

    monkeypatch.setattr(api, "MatchMatcher", FakeMatcher)

    class FakeScraper:
        async def scrape(self, live=False, scan_time=None):
            kickoff = datetime.now(UTC).replace(tzinfo=None)
            return [
                _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1", kickoff=kickoff),
                _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2", kickoff=kickoff),
            ]

    monkeypatch.setitem(api.SCRAPERS, "mdshop", FakeScraper)
    monkeypatch.setitem(api.SCRAPERS, "mbet", FakeScraper)
    for bookie_id in api.BOOKMAKERS:
        api._bookmaker_enabled[bookie_id] = bookie_id in ("mdshop", "mbet")


def test_run_scan_creates_pending_candidate_for_gate_failure(stub_scan_inputs):
    api.pending_candidates.clear()

    run(api.run_scan("prematch"))

    assert len(api.pending_candidates) >= 1
    reasons = {r for c in api.pending_candidates.values() for r in c.rule_rejections}
    assert reasons  # the candidate records why the gate refused
    candidate = next(iter(api.pending_candidates.values()))
    assert candidate.status == "pending"
    assert candidate.bookmakers == ["mbet", "mdshop"]
    assert candidate.created_at.tzinfo is None


def test_health_pending_count_matches_candidates():
    api.pending_candidates.clear()

    body = run(api.health())

    assert body["pending_candidates"] == 0


def test_pending_candidates_are_rebuilt_not_appended_each_scan(stub_scan_inputs):
    api.pending_candidates.clear()
    stale = next(iter(_one_ambiguous_pair().values()))
    api.pending_candidates["stale-candidate"] = stale

    run(api.run_scan("prematch"))

    assert "stale-candidate" not in api.pending_candidates
    assert api.pending_candidates


def test_candidate_ids_are_deterministic_across_rescans(stub_scan_inputs):
    api.pending_candidates.clear()
    run(api.run_scan("prematch"))
    first = {c.id: c for c in api.pending_candidates.values()}

    api.pending_candidates.clear()
    run(api.run_scan("prematch"))
    second = {c.id: c for c in api.pending_candidates.values()}

    assert first and set(first) == set(second)
    assert all(len(candidate_id) == 16 for candidate_id in first)
    for candidate_id, candidate in first.items():
        assert (candidate.home_team, candidate.away_team) == (
            second[candidate_id].home_team,
            second[candidate_id].away_team,
        )


def test_fully_proven_pair_is_never_queued(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1")
    right = _match("mbet", "Lech Poznan", "Thun", "Liga Evrope", "2")

    out = run(api._collect_candidates([left, right], MatchMatcher()))

    assert out == {}


def test_pair_already_verified_by_the_matcher_is_not_requeued(monkeypatch):
    """The candidate gate has no alias allowlist, so an allowlist-verified pair
    looks unverified to it. Already-proven pairs must not re-enter the queue."""
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1")
    right = _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2")
    matcher = MatchMatcher()
    verified = MatchGroup(
        canonical_home="lech poznan",
        canonical_away="thun",
        league="europa_league",
        kickoff=KICKOFF,
        matches=[left, right],
        status="verified",
    )

    without_groups = run(api._collect_candidates([left, right], matcher))
    with_groups = run(api._collect_candidates([left, right], matcher, [verified]))

    assert len(without_groups) == 1
    assert with_groups == {}


def test_fixture_without_team_names_is_never_queued(monkeypatch):
    """A nameless fixture cannot be compared, so it must not reach the queue
    where approving it would write an empty alias into the allowlist."""
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "", "", "Liga Evrope", "1")
    right = _match("mbet", "", "", "Liga Konferencija", "2")

    out = run(api._collect_candidates([left, right], MatchMatcher()))

    assert out == {}


def test_ai_proposal_for_a_pair_we_never_submitted_is_discarded(monkeypatch):
    hallucination = PairProposal(
        match_a_book="betole",
        match_b_book="wwin",
        same_event=True,
        confidence=0.97,
        reason="both look like the same fixture",
    )
    _fake_ai(monkeypatch, [hallucination])
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1")
    right = _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2")

    out = run(api._collect_candidates([left, right], MatchMatcher()))

    assert len(out) == 1
    candidate = next(iter(out.values()))
    assert candidate.ai_confidence == 0.0
    assert candidate.ai_reason == ""


def test_ai_confidence_never_approves_a_candidate(monkeypatch):
    certain = PairProposal(
        match_a_book="mdshop",
        match_b_book="mbet",
        same_event=True,
        confidence=0.99,
        reason="identical fixture strings",
    )
    _fake_ai(monkeypatch, [certain])
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1")
    right = _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2")

    out = run(api._collect_candidates([left, right], MatchMatcher()))

    assert len(out) == 1
    candidate = next(iter(out.values()))
    assert candidate.ai_confidence == pytest.approx(0.99)
    assert candidate.status == "pending"
    assert candidate.rule_rejections


def test_ai_is_not_consulted_when_it_is_unavailable(monkeypatch):
    calls = _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1")
    right = _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2")

    out = run(api._collect_candidates([left, right], MatchMatcher()))

    assert calls == []
    assert len(out) == 1


def test_ai_cap_ranks_the_most_plausible_candidates_first(monkeypatch, caplog):
    calls = _fake_ai(
        monkeypatch,
        [
            PairProposal(
                match_a_book="mdshop",
                match_b_book="mbet",
                same_event=True,
                confidence=0.8,
                reason="plausible",
            )
        ],
    )
    matches = [
        _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1"),
        _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2"),
        # 20 minutes apart: same kickoff bucket neighbourhood, still a review item.
        _match("mdshop", "Borac Banja Luka", "Sloboda", "Liga Evrope", "3",
               kickoff=KICKOFF + timedelta(minutes=20)),
        _match("mbet", "Borac BL", "Sloboda Tuzla", "Liga Konferencija", "4",
               kickoff=KICKOFF + timedelta(minutes=20)),
        # 45 minutes apart: the kickoff gate refuses it, a human still reviews it.
        _match("mdshop", "Zrinjski", "Rudar", "Liga Evrope", "5",
               kickoff=KICKOFF + timedelta(minutes=45)),
        _match("mbet", "Zrinjski Mostar", "Rudar Prijedor", "Liga Konferencija", "6",
               kickoff=KICKOFF + timedelta(minutes=45)),
    ]
    monkeypatch.setattr(api, "AI_CANDIDATE_RANK_CAP", 2)

    with caplog.at_level("WARNING"):
        out = run(api._collect_candidates(matches, MatchMatcher()))

    assert len(out) == 3
    assert len(calls) == 2
    assert {call["a_event"] for call in calls} == {"1", "3"}
    assert all(call["a"] == "mdshop" and call["b"] == "mbet" for call in calls)
    assert "AI ranking capped" in caplog.text


def test_collect_candidates_orders_the_queue_by_plausibility(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    matches = [
        _match("mdshop", "Zrinjski", "Rudar", "Liga Evrope", "5",
               kickoff=KICKOFF + timedelta(minutes=45)),
        _match("mbet", "Zrinjski Mostar", "Rudar Prijedor", "Liga Konferencija", "6",
               kickoff=KICKOFF + timedelta(minutes=45)),
        _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1"),
        _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2"),
    ]

    out = run(api._collect_candidates(matches, MatchMatcher()))

    assert [candidate.home_team for candidate in out.values()] == [
        "Lech Poznan",
        "Zrinjski",
    ]


def test_get_results_reports_group_statuses():
    api.cached_match_groups_report[:] = [
        {"group_id": 1, "status": "verified"},
        {"group_id": 2, "status": "verified"},
        {"group_id": 3, "status": "suggested"},
    ]

    body = run(api.get_results("prematch"))

    assert body["match_groups"] == 3
    assert body["group_statuses"] == {"verified": 2, "suggested": 1}
