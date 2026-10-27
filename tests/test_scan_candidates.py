"""run_scan populates candidate reviews for ambiguous pairs.

`run_scan` is the only producer of `pending_candidates`. Four rules bind every
test here:

* the queue is rebuilt from scratch on every scan,
* the AI only *ranks* a candidate — it can never approve or create one,
* a human approval grants a *team alias*; the deep-link gate stays a system
  check, and
* an already-decided candidate never comes back.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from rapidfuzz import fuzz

from config.settings import VERIFIED_KICKOFF_WINDOW_MINUTES
from engine import matcher as matcher_module
from engine.ai import PairProposal
from engine.certainty import CertaintyGate
from engine.matcher import MatchMatcher
from models.schemas import (
    CandidateReview,
    Market,
    MarketType,
    Match,
    MatchGroup,
    OddsValue,
    PairSide,
    TeamPositionPair,
)
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
    deep_link_verified: bool = False,
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
    """Same kickoff, both teams spelled differently, equivalent canonical leagues.

    Both spellings clear the reviewed-alias similarity, so writing the two
    aliases removes every blocker a human can remove.
    """
    return (
        _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1"),
        _match("mbet", "Lech P.", "FC Thun", "Liga Konferencija", "2"),
    )


def _second_pair(league: str) -> tuple[Match, Match]:
    """A second distinct fixture, so the two test pairs never cross-compare."""
    return (
        _match("mdshop", "Borac Banja Luka", "Sloboda", "Liga Evrope", "3"),
        _match("mbet", "Borac BL", "Sloboda Tuzla", league, "4"),
    )


def _league_blocked_pair() -> tuple[Match, Match]:
    """Same fixture, but the canonical leagues are neither equal nor equivalent."""
    return _second_pair("Premijer Liga")


def _fake_ai(monkeypatch, proposals, available=True, calls=None):
    """Install a fake MatchAI that records the pairs it is asked about."""
    holder = {"calls": calls if calls is not None else [], "shared_clients": 0}

    class FakeAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = holder["calls"]
            self.closed = False

        @property
        def available(self):
            return available

        def with_shared_client(self):
            holder["shared_clients"] += 1
            return self

        async def suggest_pairs(self, pairs):
            self.calls.append(pairs[0])
            return list(proposals)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(api, "MatchAI", FakeAI)
    return holder


@pytest.fixture(autouse=True)
def isolate_scan_state(monkeypatch, tmp_path):
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
        "suppressed": dict(api._suppressed_candidates),
        "premises": dict(api._suppressed_premises),
    }
    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "_append_history", lambda *a, **k: None)
    monkeypatch.setattr(api, "ALLOWLIST_FILE", str(tmp_path / "team_alias_allowlist.json"))
    monkeypatch.setattr(
        api, "SUPPRESSED_CANDIDATES_FILE", str(tmp_path / "suppressed_candidates.json")
    )
    api._suppressed_candidates.clear()
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
    api._suppressed_candidates.clear()
    api._suppressed_candidates.update(snapshot["suppressed"])
    api._suppressed_premises.clear()
    api._suppressed_premises.update(snapshot["premises"])
    for key, value in snapshot["status"].items():
        setattr(api.scan_status, key, value)


@pytest.fixture
def stub_scan_inputs(monkeypatch):
    """Two books, one plausible-but-unverifiable same-event pair.

    The fake matcher carries the real league equivalences: the pair's leagues
    ("Liga Evrope" / "Liga Konferencija") are equivalent in the shipped config,
    and an approval is only allowed when the gate says the aliases would clear
    the pair. A fake without them would model a different config.
    """
    equivalences = api.MatchMatcher()._equivalences

    class FakeMatcher:
        _equivalences = equivalences

        def group_matches(self, matches):
            return []

        def get_match_report(self, groups):
            return []

    monkeypatch.setattr(api, "MatchMatcher", FakeMatcher)

    class FakeScraper:
        async def scrape(self, live=False, scan_time=None):
            kickoff = datetime.now(UTC).replace(tzinfo=None)
            return [match.model_copy(update={"kickoff": kickoff})
                    for match in _ambiguous_pair()]

    monkeypatch.setitem(api.SCRAPERS, "mdshop", FakeScraper)
    monkeypatch.setitem(api.SCRAPERS, "mbet", FakeScraper)
    for bookie_id in api.BOOKMAKERS:
        api._bookmaker_enabled[bookie_id] = bookie_id in ("mdshop", "mbet")


def _collect(matches: list[Match]) -> dict:
    return run(api._collect_candidates(matches, MatchMatcher()))


def _one_candidate(matches: list[Match] | None = None) -> CandidateReview:
    out = _collect(list(matches or _ambiguous_pair()))
    assert len(out) == 1, out
    return next(iter(out.values()))


def _aliases_on_disk() -> set[str]:
    with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
        return set(json.load(file)["aliases"])


def _pure_similarity(left: Match, right: Match) -> float:
    """The brief's rule, with no cheap gate in front of it."""
    return max(
        fuzz.token_set_ratio(left.home_team_normalized, right.home_team_normalized),
        fuzz.token_set_ratio(left.home_team_normalized, right.away_team_normalized),
        fuzz.token_set_ratio(left.away_team_normalized, right.home_team_normalized),
        fuzz.token_set_ratio(left.away_team_normalized, right.away_team_normalized),
    )


# ─── The queue itself ────────────────────────────────────────────────────────────


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


def test_a_live_scan_leaves_the_prematch_queue_alone(stub_scan_inputs, monkeypatch):
    from models.schemas import ScanStatus

    # Fresh live state so the run touches nothing a later test reads.
    monkeypatch.setattr(api, "live_status", ScanStatus(mode="live"))
    for name in ("cached_live_surebets", "cached_live_matches", "cached_live_match_groups_report"):
        monkeypatch.setattr(api, name, [])
    monkeypatch.setattr(api, "cached_live_per_bookie", {})
    monkeypatch.setattr(api, "pending_live_candidates", {})

    api.pending_candidates.clear()
    run(api.run_scan("prematch"))
    prematch_queue = dict(api.pending_candidates)
    assert prematch_queue

    run(api.run_scan("live"))

    assert api.pending_candidates == prematch_queue
    assert api.pending_live_candidates


def test_a_book_that_returns_nothing_is_flagged_while_others_return_data(
    stub_scan_inputs, monkeypatch
):
    class EmptyScraper:
        async def scrape(self, live=False, scan_time=None):
            return []

    monkeypatch.setitem(api.SCRAPERS, "mbet", EmptyScraper)
    api.cached_per_bookie["wwin"] = 999  # a stale count from an earlier scan

    run(api.run_scan("prematch"))

    assert any(e.startswith("MBet: returned no matches") for e in api.scan_status.errors)
    assert not any(e.startswith("MDShop") for e in api.scan_status.errors)
    assert "wwin" not in api.cached_per_bookie, "a disabled book kept its old count"


def test_health_pending_count_matches_candidates():
    api.pending_candidates.clear()

    body = run(api.health())

    assert body["pending_candidates"] == 0
    assert body["suppressed_candidates"] == 0


def test_pending_candidates_are_rebuilt_not_appended_each_scan(stub_scan_inputs):
    api.pending_candidates.clear()
    api.pending_candidates["stale-candidate"] = _one_candidate()

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
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1",
                  deep_link_verified=True)
    right = _match("mbet", "Lech Poznan", "Thun", "Liga Evrope", "2",
                   deep_link_verified=True)

    assert _collect([left, right]) == {}


def test_pair_already_verified_by_the_matcher_is_not_requeued(monkeypatch):
    """The candidate gate has no alias allowlist, so an allowlist-verified pair
    looks unverified to it. Already-proven pairs must not re-enter the queue."""
    _fake_ai(monkeypatch, [], available=False)
    left, right = _ambiguous_pair()
    matcher = MatchMatcher()
    verified = MatchGroup(
        canonical_home="lech poznan",
        canonical_away="thun",
        league="europa_league",
        kickoff=KICKOFF,
        matches=[left, right],
        status="verified",
    )

    without_groups = _collect([left, right])
    with_groups = run(api._collect_candidates([left, right], matcher, [verified]))

    assert len(without_groups) == 1
    assert with_groups == {}


# ─── Both sides of the claim (Critical 1) ────────────────────────────────────────


def test_candidate_records_both_sides_of_the_claim(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)

    candidate = _one_candidate()

    assert candidate.side_a == PairSide(
        bookmaker="mdshop", event_ref="1",
        home_team="Lech Poznan", away_team="Thun", link_verified=False,
    )
    assert candidate.side_b == PairSide(
        bookmaker="mbet", event_ref="2",
        home_team="Lech P.", away_team="FC Thun", link_verified=False,
    )


def test_team_positions_pair_the_two_books_by_orientation(monkeypatch):
    """A bookmaker that publishes the fixture flipped is recorded swapped."""
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1")
    flipped = _match("mbet", "FC Thun", "Lech P.", "Liga Konferencija", "2")

    candidate = _one_candidate([left, flipped])

    assert candidate.team_positions == [
        TeamPositionPair(position="home", team_a="Lech Poznan", team_b="Lech P."),
        TeamPositionPair(position="away", team_a="Thun", team_b="FC Thun"),
    ]


# ─── Approval grants a team alias, never a link (Critical 2) ─────────────────────


def test_approval_writes_the_cross_bookmaker_team_alias(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    candidate = _one_candidate()
    api.pending_candidates[candidate.id] = candidate

    body = run(api.approve_candidate(candidate.id, _auth=None))

    assert body["status"] == "approved"
    # Entries keep the two spellings the reviewer saw, one per team slot.
    assert body["allowlist_entries"] == ["FC Thun|Thun", "Lech P.|Lech Poznan"]
    assert _aliases_on_disk() == {"FC Thun|Thun", "Lech P.|Lech Poznan"}
    # The two halves of ONE fixture are different clubs, never an alias pair.
    assert "Lech Poznan|Thun" not in _aliases_on_disk()


def test_approval_writes_one_entry_per_differing_team(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "A. Salzburg", "Kapfenberg", "Liga Evrope", "1")
    right = _match("mbet", "Austria Salzburg", "Kapfenberg SV", "Liga Konferencija", "2")
    candidate = _one_candidate([left, right])
    api.pending_candidates[candidate.id] = candidate

    run(api.approve_candidate(candidate.id, _auth=None))

    assert _aliases_on_disk() == {
        "A. Salzburg|Austria Salzburg",
        "Kapfenberg|Kapfenberg SV",
    }


def test_approval_skips_a_position_whose_two_spellings_already_agree(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1")
    right = _match("mbet", "Lech P.", "Thun", "Liga Konferencija", "2")
    candidate = _one_candidate([left, right])
    api.pending_candidates[candidate.id] = candidate

    run(api.approve_candidate(candidate.id, _auth=None))

    assert _aliases_on_disk() == {"Lech P.|Lech Poznan"}


def test_written_alias_is_honoured_by_the_real_certainty_gate(monkeypatch):
    """The gate — not the endpoint — decides whether an alias is usable."""
    _fake_ai(monkeypatch, [], available=False)
    left, right = _ambiguous_pair()
    candidate = _one_candidate([left, right])
    api.pending_candidates[candidate.id] = candidate
    run(api.approve_candidate(candidate.id, _auth=None))

    gate = CertaintyGate(league_equivalences=MatchMatcher()._equivalences)
    gate.normalize([left, right])
    gate.alias_allowlist = set(_aliases_on_disk())
    result = gate.evaluate_pair(left, right)

    assert "team_unresolved" not in result.reasons
    # The link gate is a system check and still refuses: approval is not a link proof.
    assert result.reasons == ["link_unverified"]
    assert result.status == "suggested"


def test_approval_reports_that_the_link_gate_is_still_open(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    candidate = _one_candidate()
    api.pending_candidates[candidate.id] = candidate

    body = run(api.approve_candidate(candidate.id, _auth=None))

    assert body["link_verified"] is False
    assert body["link_state"] == "pending_system_check"
    assert "link" in body["note"].lower()


def test_candidate_reports_the_link_state_of_both_sides(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    identical = (
        _match("mdshop", "Lech Poznan", "Thun", "Liga Evrope", "1"),
        _match("mbet", "Lech Poznan", "Thun", "Liga Konferencija", "2"),
    )

    unlinked = _one_candidate(list(identical))
    assert unlinked.link_blocked is True
    assert unlinked.side_a.link_verified is False
    assert unlinked.side_b.link_verified is False

    # Both links proven by the system check: the pair is no longer a review item.
    linked = [match.model_copy(update={"deep_link_verified": True}) for match in identical]
    assert _collect(linked) == {}


def test_approval_refuses_a_candidate_without_cross_bookmaker_names(monkeypatch):
    legacy = CandidateReview(
        id="legacy-candidate",
        home_team="Lech Poznan",
        away_team="Thun",
        league="Liga Evrope",
        kickoff=KICKOFF,
        bookmakers=["mbet", "mdshop"],
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    api.pending_candidates[legacy.id] = legacy

    with pytest.raises(api.HTTPException) as excinfo:
        run(api.approve_candidate(legacy.id, _auth=None))

    assert excinfo.value.status_code == 400
    assert "cross-bookmaker" in excinfo.value.detail
    assert not os.path.exists(api.ALLOWLIST_FILE)
    assert legacy.id in api.pending_candidates


# ─── Suppression: a decided candidate never comes back ──────────────────────────


def test_approved_candidate_is_suppressed_on_the_next_scan(stub_scan_inputs):
    api.pending_candidates.clear()
    run(api.run_scan("prematch"))
    candidate = next(iter(api.pending_candidates.values()))

    run(api.approve_candidate(candidate.id, _auth=None))
    api.pending_candidates.clear()
    run(api.run_scan("prematch"))

    assert api.pending_candidates == {}


def test_rejected_candidate_is_suppressed_on_the_next_scan(stub_scan_inputs):
    api.pending_candidates.clear()
    run(api.run_scan("prematch"))
    candidate = next(iter(api.pending_candidates.values()))

    run(api.reject_candidate(candidate.id, _auth=None))
    api.pending_candidates.clear()
    run(api.run_scan("prematch"))

    assert api.pending_candidates == {}


def test_suppression_is_persisted_and_reloaded_from_disk(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    candidate = _one_candidate()
    api.pending_candidates[candidate.id] = candidate
    run(api.approve_candidate(candidate.id, _auth=None))

    api._suppressed_candidates.clear()
    reloaded = api._load_suppressed_candidates()

    assert reloaded == {candidate.id: "approved"}


def test_a_decision_recorded_with_its_premise_survives_a_restart(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    candidate = _one_candidate()
    api.pending_candidates[candidate.id] = candidate
    run(api.reject_candidate(candidate.id, _auth=None))

    api._suppressed_candidates.clear()
    api._suppressed_premises.clear()
    api._suppressed_candidates.update(api._load_suppressed_candidates())
    api._suppressed_premises.update(api._load_suppressed_premises())

    # Still link-blocked, so the decision it was made on is still the case.
    assert api._decision_still_stands(candidate.id, True) is True
    assert _collect(list(_ambiguous_pair())) == {}


def test_a_suppression_file_written_before_premises_still_loads(monkeypatch):
    """The deployed cache is a flat id -> decision map; it must not be discarded."""
    _fake_ai(monkeypatch, [], available=False)
    with open(api.SUPPRESSED_CANDIDATES_FILE, "w", encoding="utf-8") as file:
        json.dump({"legacy-id": "rejected"}, file)

    assert api._load_suppressed_candidates() == {"legacy-id": "rejected"}
    assert api._load_suppressed_premises() == {}
    # A record with no premise is honoured exactly as written.
    assert api._decision_still_stands("legacy-id", True) is True
    assert api._decision_still_stands("legacy-id", False) is True


def test_suppression_does_not_hide_a_pair_under_a_new_bookmaker_event_id(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    left, right = _ambiguous_pair()
    candidate = _one_candidate([left, right])
    api.pending_candidates[candidate.id] = candidate
    run(api.approve_candidate(candidate.id, _auth=None))

    # The same fixture, but the bookmaker now publishes it under a new event id.
    out = _collect([left, right.model_copy(update={"event_id": "99"})])

    assert len(out) == 1
    assert candidate.id not in out


# ─── A decision is a decision about the claim it was made on ───────────────────
# Suppression is durable and id-keyed, so anything the system learns after the
# decision would otherwise be lost for good. Only state the system changes on its
# own belongs in the premise a decision is held against.


def test_a_decision_does_not_outlive_the_deep_link_result_it_was_made_on(monkeypatch):
    """A pair rejected while its link was unproven returns once the link is proven.

    `deep_link_verified` is moved by the per-book deep-link system check, with no
    human involved. A decision recorded against its old value was taken on a claim
    that no longer holds, and the pair is now one an approval genuinely clears.
    """
    _fake_ai(monkeypatch, [], available=False)
    left, right = _ambiguous_pair()
    candidate = _one_candidate([left, right])
    assert candidate.link_blocked is True
    api.pending_candidates[candidate.id] = candidate
    run(api.reject_candidate(candidate.id, _auth=None))

    proven = [m.model_copy(update={"deep_link_verified": True}) for m in (left, right)]
    out = _collect(proven)

    assert list(out) == [candidate.id]  # same id, so suppression is what let it go
    assert out[candidate.id].alias_actionable is True
    assert out[candidate.id].link_blocked is False


def test_an_approval_does_not_contradict_its_own_record(monkeypatch):
    """The premise must ignore the facts the decision itself changed.

    An approval grants the aliases, which clears `team_unresolved` from the next
    scan's reason list. If that counted as the premise moving, every approval
    would re-queue the pair it had just resolved and the review loop would never
    converge — so `link_blocked` is the premise, and it has not moved here.
    """
    _fake_ai(monkeypatch, [], available=False)
    monkeypatch.setattr(matcher_module, "_TEAM_ALIAS_FILE", api.ALLOWLIST_FILE)
    left, right = _ambiguous_pair()
    candidate = _one_candidate([left, right])
    api.pending_candidates[candidate.id] = candidate
    run(api.approve_candidate(candidate.id, _auth=None))
    assert "team_unresolved" in candidate.rule_rejections

    out = _collect([left, right])

    assert out == {}  # the granted aliases cleared the team reason; the link did not


# ─── Actionability decides what the reviewer sees first (Important 4) ────────────


def test_alias_actionable_candidate_outranks_a_league_blocked_one(monkeypatch):
    holder = _fake_ai(monkeypatch, [
        PairProposal(match_a_book="mdshop", match_b_book="mbet",
                     same_event=True, confidence=0.8, reason="plausible")
    ])
    monkeypatch.setattr(api, "AI_CANDIDATE_RANK_CAP", 1)
    actionable, other_side = _ambiguous_pair()
    blocked_left, blocked_right = _league_blocked_pair()

    out = _collect([blocked_left, blocked_right, actionable, other_side])

    ordered = list(out.values())
    assert [c.alias_actionable for c in ordered] == [True, False]
    assert ordered[0].side_a.home_team == "Lech Poznan"
    # The capped AI budget is spent on the pair a reviewer can actually close.
    assert [call["a_event"] for call in holder["calls"]] == ["1"]


def test_candidate_reports_why_it_is_not_alias_actionable(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)

    candidate = _one_candidate(list(_league_blocked_pair()))

    assert "league_mismatch" in candidate.rule_rejections
    assert candidate.alias_actionable is False
    assert candidate.link_blocked is True


def test_alias_actionable_is_false_when_the_gate_would_refuse_the_alias(monkeypatch):
    """A home pair the reviewed-alias similarity cannot carry is not actionable."""
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Manchester City", "Arsenal", "Liga Evrope", "1")
    right = _match("mbet", "Manchester United", "Arsenal", "Liga Evrope", "2")

    candidate = _one_candidate([left, right])

    assert candidate.rule_rejections == ["team_unresolved", "link_unverified"]
    assert candidate.alias_actionable is False


# ─── Actionability is judged with the gate that decides `verified` ──────────────
# An approval grants the team aliases and nothing else, so it cannot move a
# kickoff. The candidate window is deliberately wider than the verified window so
# a near-miss reaches the queue; that wider window must never be the yardstick
# for "an approval clears this", because the gate that produces `verified` — and
# therefore the only gate whose verdict the reviewer will ever live with — uses
# the narrower one.


def _band_pair(minutes: int) -> tuple[Match, Match]:
    """A distinct fixture whose two books' kickoffs are `minutes` apart.

    Distinct teams and event ids on purpose: `_canonical_pair_key` covers
    bookmakers, event refs and team names but not the kickoff, so a shifted copy
    of another fixture's two books would collapse into the same candidate and one
    of the two would be swallowed by `seen_pairs`.
    """
    return (
        _match("mdshop", "Zrinjski", "Rudar", "Liga Evrope", "5",
               kickoff=KICKOFF + timedelta(minutes=minutes)),
        _match("mbet", "Zrinjski Mostar", "Rudar Prijedor", "Liga Konferencija", "6"),
    )


def _verdict_after_approval(left: Match, right: Match) -> tuple[str, list[str]]:
    """Ask the gate that produces `verified` groups, in the state an approval leaves.

    Built the way the scan builds it — a real `MatchMatcher`, so the real gate and
    its verified kickoff window — then the candidate's own aliases granted and
    both links marked verified, which is the state the per-book deep-link system
    check produces. This is the promise `_alias_actionable` has to keep.
    """
    matcher = MatchMatcher()
    matcher.normalize_matches([left, right])
    matcher.gate.alias_allowlist = set(
        api._alias_entries(api._team_positions(left, right))
    )
    linked = [match.model_copy(update={"deep_link_verified": True}) for match in (left, right)]
    result = matcher.gate.evaluate_pair(*linked)
    return result.status, list(result.reasons)


def test_an_approval_cannot_clear_a_kickoff_delta_the_verified_window_refuses(monkeypatch):
    """The (verified, candidate] band is queued for review and called unfixable.

    `CANDIDATE_KICKOFF_WINDOW_MIN` is 30 and the verified window is 15, so a
    16-to-30-minute delta is found and refused by the real gate alike. Nothing a
    human approves changes a kickoff, so the card must not promise otherwise.
    """
    _fake_ai(monkeypatch, [], available=False)
    left, right = _band_pair(20)

    candidate = _one_candidate([left, right])  # the wider window still queues it

    assert candidate.alias_actionable is False
    assert _verdict_after_approval(left, right)[0] != "verified"


@pytest.mark.parametrize("minutes", [16, 20, 25, 30])
def test_the_whole_band_above_the_verified_window_is_not_actionable(monkeypatch, minutes):
    _fake_ai(monkeypatch, [], available=False)

    candidate = _one_candidate(list(_band_pair(minutes)))

    assert candidate.alias_actionable is False


def test_the_verified_kickoff_window_is_the_exact_edge_of_actionability(monkeypatch):
    """15 minutes still clears; one minute more does not."""
    _fake_ai(monkeypatch, [], available=False)
    at_edge = _band_pair(VERIFIED_KICKOFF_WINDOW_MINUTES)
    past_edge = _band_pair(VERIFIED_KICKOFF_WINDOW_MINUTES + 1)

    assert _one_candidate(list(at_edge)).alias_actionable is True
    assert _one_candidate(list(past_edge)).alias_actionable is False


def test_every_actionable_candidate_is_one_an_approval_actually_verifies(monkeypatch):
    """The promise as a property of the whole queue, not of one hand-picked pair.

    `alias_actionable` is what puts a card on top of the review order, so the set
    the queue advertises must be exactly the set the real gate verifies once the
    human has approved it.
    """
    _fake_ai(monkeypatch, [], available=False)
    band = _band_pair(20)
    tight = _ambiguous_pair()
    league_blocked = _league_blocked_pair()
    out = _collect([*league_blocked, *tight, *band])

    verified = {
        api._candidate_id(api._canonical_pair_key(left, right))
        for left, right in (league_blocked, tight, band)
        if _verdict_after_approval(left, right)[0] == "verified"
    }
    # Sanity: the fixture really is one an approval would clear, were the kickoff
    # not in the way — otherwise this test would pass for the wrong reason.
    assert len(verified) == 1
    assert {c.id for c in out.values() if c.alias_actionable} == verified
    assert len(out) == 3  # all three pairs still reach the review queue
    # The only pair the queue advertises is the one an approval really clears.
    assert [c.alias_actionable for c in out.values()] == [True, False, False]


def test_a_candidate_never_inherits_another_candidate_s_approved_aliases(monkeypatch):
    """The two gates are separate instances, and this is what keeps them that way.

    `_alias_actionable` writes the candidate's aliases onto the gate it is handed.
    Were that the collection gate, the next pair spelling the same two clubs would
    be judged with those aliases already granted: its recorded reasons would lose
    `team_unresolved`, and once the deep-link check has passed it would verify
    itself and never reach the queue at all.
    """
    _fake_ai(monkeypatch, [], available=False)
    left, right = _ambiguous_pair()
    # The same two clubs, republished under fresh event ids, links now proven.
    republished = (
        left.model_copy(update={"event_id": "7", "deep_link_verified": True}),
        right.model_copy(update={"event_id": "8", "deep_link_verified": True}),
    )

    out = _collect([*_ambiguous_pair(), *republished])

    by_id = {c.id: c for c in out.values()}
    republished_id = api._candidate_id(api._canonical_pair_key(*republished))
    assert republished_id in by_id  # reached a human
    assert by_id[republished_id].rule_rejections == ["team_unresolved"]
    assert by_id[republished_id].alias_actionable is True


# ─── The AI ranks, it never approves, and a negative verdict is not confidence ────


def test_ai_proposal_for_a_pair_we_never_submitted_is_discarded(monkeypatch):
    hallucination = PairProposal(
        match_a_book="betole",
        match_b_book="wwin",
        same_event=True,
        confidence=0.97,
        reason="both look like the same fixture",
    )
    _fake_ai(monkeypatch, [hallucination])

    candidate = _one_candidate()

    assert candidate.ai_confidence == 0.0
    assert candidate.ai_reason == ""
    assert candidate.ai_same_event is None


def test_ai_confidence_never_approves_a_candidate(monkeypatch):
    certain = PairProposal(
        match_a_book="mdshop",
        match_b_book="mbet",
        same_event=True,
        confidence=0.99,
        reason="identical fixture strings",
    )
    _fake_ai(monkeypatch, [certain])

    candidate = _one_candidate()

    assert candidate.ai_confidence == pytest.approx(0.99)
    assert candidate.ai_same_event is True
    assert candidate.status == "pending"
    assert candidate.rule_rejections


def test_ai_negative_verdict_is_not_presented_as_confidence(monkeypatch):
    negative = PairProposal(
        match_a_book="mdshop",
        match_b_book="mbet",
        same_event=False,
        confidence=0.9,
        reason="different competitions, not the same fixture",
    )
    _fake_ai(monkeypatch, [negative])

    candidate = _one_candidate()

    assert candidate.ai_same_event is False
    assert candidate.ai_confidence == 0.0
    assert "not the same event" in candidate.ai_reason


def test_ai_is_not_consulted_when_it_is_unavailable(monkeypatch):
    holder = _fake_ai(monkeypatch, [], available=False)

    candidate = _one_candidate()

    assert holder["calls"] == []
    assert candidate.ai_same_event is None


def test_ai_calls_share_one_http_client(monkeypatch):
    holder = _fake_ai(monkeypatch, [
        PairProposal(match_a_book="mdshop", match_b_book="mbet",
                     same_event=True, confidence=0.5, reason="ok")
    ])

    out = _collect([*_ambiguous_pair(), *_second_pair("Liga Konferencija")])

    assert len(holder["calls"]) == 2
    # One adapter, one shared client, for every AI call of the scan — not one
    # TLS handshake per candidate.
    assert holder["shared_clients"] == 1
    assert len(out) == 2


def test_no_http_client_is_built_when_the_ai_is_unavailable(monkeypatch):
    holder = _fake_ai(monkeypatch, [], available=False)

    _collect(list(_ambiguous_pair()))

    assert holder["shared_clients"] == 0


def test_ai_cap_ranks_the_most_actionable_candidates_first(monkeypatch, caplog):
    holder = _fake_ai(monkeypatch, [
        PairProposal(match_a_book="mdshop", match_b_book="mbet",
                     same_event=True, confidence=0.8, reason="plausible")
    ])
    late_blocked = (
        _match("mdshop", "Zrinjski", "Rudar", "Liga Evrope", "5",
               kickoff=KICKOFF + timedelta(minutes=45)),
        _match("mbet", "Zrinjski Mostar", "Rudar Prijedor", "Premijer Liga", "6",
               kickoff=KICKOFF + timedelta(minutes=45)),
    )
    monkeypatch.setattr(api, "AI_CANDIDATE_RANK_CAP", 1)

    with caplog.at_level("WARNING"):
        out = _collect([*late_blocked, *_second_pair("Liga Konferencija"),
                        *_ambiguous_pair()])

    ranked = list(out.values())
    assert len(ranked) == 3
    assert [candidate.alias_actionable for candidate in ranked] == [True, True, False]
    # One call, spent on a pair a reviewer can actually close — not on the
    # tightest-kickoff pair, which the old kickoff-first ordering would pick.
    assert len(holder["calls"]) == 1
    assert [call["a_event"] for call in holder["calls"]] in (["1"], ["3"])
    assert all(call["a"] == "mdshop" and call["b"] == "mbet" for call in holder["calls"])
    assert "AI ranking capped" in caplog.text


def test_collect_candidates_orders_the_queue_by_actionability(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)

    out = _collect([*_league_blocked_pair(), *_ambiguous_pair()])

    assert [candidate.alias_actionable for candidate in out.values()] == [True, False]


# ─── The prefilter must never veto what the brief's rule would admit ─────────────


def test_typo_pair_from_the_review_reaches_the_queue(monkeypatch):
    """The reviewer's motivating example: no shared token, only bigrams."""
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Aguilas", "Millionarios", "Liga Evrope", "1")
    right = _match("mbet", "Rionegro", "Millonarios", "Liga Konferencija", "2")

    candidate = _one_candidate([left, right])

    assert candidate.rule_rejections == ["team_unresolved", "link_unverified"]


@pytest.mark.parametrize(
    ("left_home", "left_away", "right_home", "right_away"),
    [
        ("Aguilas", "Millionarios", "Rionegro", "Millonarios"),
        ("Lech Poznan", "Thun", "Lech P.", "FC Thun"),
        ("Bury Town", "Leamington", "Leicester", "Burton"),
        ("Real Madrid", "Barcelona", "Aguilas", "Millonarios"),
    ],
)
def test_cheap_prefilter_never_vetoes_the_fuzzy_rule(
    monkeypatch, left_home, left_away, right_home, right_away
):
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", left_home, left_away, "Liga Evrope", "1")
    right = _match("mbet", right_home, right_away, "Liga Konferencija", "2")
    CertaintyGate(league_equivalences=MatchMatcher()._equivalences).normalize([left, right])
    left_tokens, right_tokens = api._TeamTokens.of(left), api._TeamTokens.of(right)

    pure = _pure_similarity(left, right)
    shipped = api._team_similarity(left_tokens, right_tokens)

    if api._shares_any_signal(left_tokens, right_tokens):
        # Admitted by the cheap gate: the fuzzy rule decides, unaltered.
        assert shipped == pytest.approx(pure, abs=1e-9)
    else:
        # Rejected by the cheap gate: only sound if the rule would reject it too.
        assert pure < api.CANDIDATE_TEAM_SIM_MIN
    assert (shipped >= api.CANDIDATE_TEAM_SIM_MIN) == (pure >= api.CANDIDATE_TEAM_SIM_MIN)


def test_unrelated_fixtures_never_reach_the_candidate_gate(monkeypatch):
    _fake_ai(monkeypatch, [], available=False)
    left = _match("mdshop", "Real Madrid", "Barcelona", "Liga Evrope", "1")
    right = _match("mbet", "Aguilas", "Millonarios", "Liga Konferencija", "2")

    assert _collect([left, right]) == {}


# ─── Endpoint contracts ──────────────────────────────────────────────────────────


def test_candidates_endpoint_returns_a_bounded_page():
    api.pending_candidates.clear()
    for index in range(5):
        candidate = _one_candidate()
        candidate.id = f"{index:016d}"
        api.pending_candidates[candidate.id] = candidate

    first = run(api.get_candidates(limit=2, offset=0))
    second = run(api.get_candidates(limit=2, offset=2))

    assert first["total"] == 5
    assert first["count"] == 2
    assert first["limit"] == 2
    assert first["offset"] == 0
    assert [c["id"] for c in first["candidates"]] == [
        "0000000000000000",
        "0000000000000001",
    ]
    assert [c["id"] for c in second["candidates"]] == [
        "0000000000000002",
        "0000000000000003",
    ]


def test_candidates_endpoint_caps_an_absurd_limit():
    api.pending_candidates.clear()
    api.pending_candidates["a"] = _one_candidate()

    body = run(api.get_candidates(limit=10_000))

    assert body["limit"] == api.CANDIDATE_PAGE_MAX


def test_candidates_endpoint_defaults_to_a_bounded_page():
    api.pending_candidates.clear()
    api.pending_candidates["a"] = _one_candidate()

    body = run(api.get_candidates())

    assert body["limit"] == api.CANDIDATE_PAGE_SIZE
    assert body["offset"] == 0


def test_get_results_reports_group_statuses():
    api.cached_match_groups_report[:] = [
        {"group_id": 1, "status": "verified"},
        {"group_id": 2, "status": "verified"},
        {"group_id": 3, "status": "suggested"},
    ]

    body = run(api.get_results("prematch"))

    assert body["match_groups"] == 3
    assert body["group_statuses"] == {"verified": 2, "suggested": 1}


def test_candidate_review_history_is_bounded(monkeypatch):
    monkeypatch.setattr(api, "CANDIDATE_REVIEW_HISTORY_MAX", 3)
    api.pending_candidates.clear()
    for index in range(5):
        candidate = _one_candidate()
        candidate.id = f"{index:016d}"
        api.pending_candidates[candidate.id] = candidate
        run(api.reject_candidate(candidate.id, _auth=None))

    assert [review.id for review in api.candidate_reviews] == [
        "0000000000000004",
        "0000000000000003",
        "0000000000000002",
    ]
