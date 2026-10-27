"""CertaintyGate: hard gates for verified same-event claims."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.certainty import CertaintyGate
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

K = datetime(2026, 9, 25, 18, 0)


def _m(
    bookmaker,
    home,
    away,
    league,
    kickoff=K,
    home_n=None,
    away_n=None,
    tags=None,
    url="",
    event_id="",
    link_ok=True,
):
    m = Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=kickoff,
        home_team_normalized=home_n or home.lower(),
        away_team_normalized=away_n or away.lower(),
        category_tags=tags or [],
        url=url,
        event_id=event_id,
        deep_link_verified=link_ok,
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
    return m


def _g(match, league="premier_liga_bih"):
    return MatchGroup(
        canonical_home=match.home_team_normalized,
        canonical_away=match.away_team_normalized,
        league=league,
        kickoff=match.kickoff,
        matches=[match],
    )


def test_verified_when_all_gates_pass():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1", link_ok=True)
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=True)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert r.reasons == []
    assert any(e.rule == "league_identity" for e in r.evidence)
    assert any(e.rule == "kickoff" for e in r.evidence)
    assert any(e.rule == "team_identity" for e in r.evidence)


def test_aware_and_naive_kickoffs_compare_equal_in_both_orders():
    gate = CertaintyGate()
    aware = K.replace(tzinfo=timezone(timedelta(hours=2))) + timedelta(hours=2)
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", kickoff=K, event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=aware, event_id="2")
    gate.normalize([a, b])

    r_naive_aware = gate.evaluate_pair(a, b)
    assert r_naive_aware.status == "verified"
    assert r_naive_aware.reasons == []

    r_aware_naive = gate.evaluate_pair(b, a)
    assert r_aware_naive.status == "verified"
    assert r_aware_naive.reasons == []


def test_missing_kickoff_is_suggested_with_exact_reason():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=None, event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["kickoff_missing"]


def test_verified_kickoff_window_boundary_is_inclusive():
    gate = CertaintyGate()
    a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    at_limit = _m(
        "b",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        kickoff=K + timedelta(minutes=15),
        event_id="2",
    )
    gate.normalize([a, at_limit])
    result = gate.evaluate_pair(a, at_limit)
    assert "kickoff_delta" not in result.reasons

    over_limit = at_limit.model_copy(update={"kickoff": K + timedelta(minutes=15, seconds=1)})
    over_result = gate.evaluate_pair(a, over_limit)
    assert "kickoff_delta" in over_result.reasons


def test_kickoff_delta_over_15_minutes_is_suggested_with_exact_reason():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m(
        "mbet",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        kickoff=K + timedelta(minutes=45),
        event_id="2",
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["kickoff_delta"]


def test_league_mismatch_is_rejected_with_exact_reason():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Engleska - Premier liga", event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "rejected"
    assert r.reasons == ["league_mismatch"]


def test_category_mismatch_is_rejected_with_exact_reason():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", tags=[], event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", tags=["U21"], event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "rejected"
    assert r.reasons == ["category_mismatch"]


def test_home_away_swap_is_provable():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Zeljeznicar", "Sarajevo", "Premijer Liga BiH", event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert r.is_swapped is True


def test_link_unverified_blocks_verified():
    gate = CertaintyGate()
    a = _m(
        "mdshop",
        "Sarajevo",
        "Zeljeznicar",
        "BiH - Premier Liga",
        url="https://bookmaker.test/sarajevo-zeljeznicar",
        event_id="",
        link_ok=False,
    )
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=True)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["link_unverified"]


def test_team_unresolved_is_suggested_with_exact_reason():
    gate = CertaintyGate()
    a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("b", "Arsenal", "Chelsea", "Premijer Liga BiH", event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["team_unresolved"]


def test_reason_vocabulary_except_orientation_is_reachable():
    gate = CertaintyGate()

    league_a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    # Both leagues mapped and different: a real contradiction. (An unmapped name
    # with exact teams is settled by the fixture — see the next tests.)
    league_b = _m("b", "Sarajevo", "Zeljeznicar", "Serie A", event_id="2")
    missing_a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    missing_b = _m(
        "b", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=None, event_id="2"
    )
    delta_a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    delta_b = _m(
        "b",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        kickoff=K + timedelta(minutes=45),
        event_id="2",
    )
    category_a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    category_b = _m(
        "b", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", tags=["U21"], event_id="2"
    )
    team_a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    team_b = _m("b", "Arsenal", "Chelsea", "Premijer Liga BiH", event_id="2")
    link_a = _m(
        "a",
        "Sarajevo",
        "Zeljeznicar",
        "BiH - Premier Liga",
        url="https://bookmaker.test/match",
        link_ok=False,
    )
    link_b = _m("b", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    no_link_a = _m(
        "a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", link_ok=False
    )
    no_link_b = _m("b", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", link_ok=False)

    results = []
    for left, right in (
        (league_a, league_b),
        (missing_a, missing_b),
        (delta_a, delta_b),
        (category_a, category_b),
        (team_a, team_b),
        (link_a, link_b),
        (no_link_a, no_link_b),
    ):
        gate.normalize([left, right])
        results.append(gate.evaluate_pair(left, right))

    observed = {reason for result in results for reason in result.reasons}
    assert observed == {
        "league_mismatch",
        "kickoff_missing",
        "kickoff_delta",
        "category_mismatch",
        "team_unresolved",
        "link_unverified",
        "no_event_link",
    }
    assert "orientation_unresolved" not in observed


def test_missing_event_link_is_reported_separately():
    gate = CertaintyGate()
    a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", link_ok=False)
    b = _m("b", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["no_event_link"]


def test_explicit_equivalence_allows_different_leagues():
    gate = CertaintyGate(league_equivalences={("europa_league", "conference_league")})
    a = _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="1")
    b = _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="2")
    a.league_normalized, b.league_normalized = "europa_league", "conference_league"
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "league_mismatch" not in r.reasons


def test_fuzzy_normalizer_result_requires_raw_allowlist():
    a = _m("a", "Sarajevo", "Thun", "Liga Evrope", event_id="1")
    b = _m("b", "Sarjevo", "Thun", "Liga Evrope", event_id="2")
    a.home_team_normalized = a.away_team_normalized = ""
    b.home_team_normalized = b.away_team_normalized = ""

    gate = CertaintyGate()
    gate.normalize([a, b])
    assert a.home_team_normalized == b.home_team_normalized
    without_allowlist = gate.evaluate_pair(a, b)
    assert without_allowlist.status == "suggested"
    assert without_allowlist.reasons == ["team_unresolved"]

    allowed_gate = CertaintyGate(alias_allowlist={"sarjevo|sarajevo"})
    with_allowlist = allowed_gate.evaluate_pair(a, b)
    assert with_allowlist.status == "verified"
    team_evidence = next(e for e in with_allowlist.evidence if e.rule == "team_identity")
    assert team_evidence.source == "allowlist"
    assert team_evidence.reason == "allowlisted_alias"


def test_allowlisted_alias_is_accepted_but_unlisted_fuzzy_is_not():
    # "lech p" is a reviewed alias of "lech poznan" (written as "lech p|lech poznan")
    gate = CertaintyGate(alias_allowlist={"lech p|lech poznan"})
    a = _m("mdshop", "Lech Poznan", "Thun", "Liga Evrope", event_id="1")
    b = _m("mbet", "Lech P.", "Thun", "Liga Evrope", event_id="2")
    gate.normalize([a, b])
    b.home_team_normalized = "lech p"  # force the alias form (normalizer may have stripped it)
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert any(e.rule == "team_identity" and e.source == "allowlist" for e in r.evidence)

    gate2 = CertaintyGate()  # no allowlist
    r2 = gate2.evaluate_pair(a, b)
    assert r2.status == "suggested"
    assert r2.reasons == ["team_unresolved"]


def test_group_canonical_fuzzy_name_requires_allowlist():
    gate = CertaintyGate()
    a = _m("a", "Sarajevo", "Thun", "Liga Evrope", event_id="1")
    b = _m("b", "Sarajevo", "Thun", "Liga Evrope", event_id="2")
    a.home_team_normalized = a.away_team_normalized = ""
    b.home_team_normalized = b.away_team_normalized = ""
    gate.normalize([a, b])
    group = _g(a, league=a.league_normalized)
    group.canonical_home = "Sarjevo"

    without_allowlist = gate.evaluate(b, group)
    assert without_allowlist.status == "suggested"
    assert without_allowlist.reasons == ["team_unresolved"]

    allowed_gate = CertaintyGate(alias_allowlist={"sarjevo|sarajevo"})
    with_allowlist = allowed_gate.evaluate(b, group)
    assert with_allowlist.status == "verified"
    assert with_allowlist.is_swapped is False


def test_allowlisted_alias_passes_pair_and_group_evaluation():
    gate = CertaintyGate(alias_allowlist={"lech p|lech poznan"})
    a = _m("mdshop", "Lech Poznan", "Thun", "Liga Evrope", event_id="1")
    b = _m("mbet", "Lech P.", "Thun", "Liga Evrope", event_id="2")
    gate.normalize([a, b])
    b.home_team_normalized = "lech p"
    group = _g(a, league=a.league_normalized)

    pair_result = gate.evaluate_pair(b, a)
    group_result = gate.evaluate(b, group)
    assert pair_result.status == "verified"
    assert group_result.status == "verified"
    assert group_result.is_swapped is False


def test_allowlisted_alias_swap_requires_both_team_pairs():
    gate = CertaintyGate(alias_allowlist={"alpha united|alpha"})
    a = _m(
        "a",
        "Alpha United",
        "Bravo United",
        "League",
        home_n="alpha united",
        away_n="bravo united",
        event_id="1",
    )
    b = _m(
        "b",
        "Bravo United",
        "Alpha",
        "League",
        home_n="bravo united",
        away_n="alpha",
        event_id="2",
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert r.is_swapped is True


def test_exact_swap_is_rule_evidence_even_when_alias_allowlist_contains_teams():
    gate = CertaintyGate(alias_allowlist={"alpha|alpha beta"})
    a = _m(
        "a",
        "Alpha",
        "Alpha Beta",
        "League",
        home_n="alpha",
        away_n="alpha beta",
        event_id="1",
    )
    b = _m(
        "b",
        "Alpha Beta",
        "Alpha",
        "League",
        home_n="alpha beta",
        away_n="alpha",
        event_id="2",
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    team_evidence = next(e for e in r.evidence if e.rule == "team_identity")
    assert team_evidence.source == "rule"
    assert team_evidence.reason == "swapped"


def test_consistent_alias_swap_flag_survives_other_failed_gates():
    gate = CertaintyGate(alias_allowlist={"alpha united|alpha"})
    a = _m(
        "a",
        "Alpha United",
        "Bravo United",
        "League A",
        home_n="alpha united",
        away_n="bravo united",
        event_id="1",
    )
    b = _m(
        "b",
        "Bravo United",
        "Alpha",
        "League B",
        home_n="bravo united",
        away_n="alpha",
        event_id="2",
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "rejected"
    assert r.is_swapped is True


def test_allowlisted_alias_does_not_bypass_hard_gates():
    gate = CertaintyGate(alias_allowlist={"alpha united|alpha"})
    a = _m(
        "a",
        "Alpha United",
        "Bravo United",
        "League A",
        home_n="alpha united",
        away_n="bravo united",
        event_id="1",
    )
    b = _m(
        "b",
        "Alpha",
        "Bravo United",
        "League B",
        home_n="alpha",
        away_n="bravo united",
        event_id="2",
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "rejected"
    assert not any(
        evidence.rule == "team_identity" and evidence.source == "allowlist"
        for evidence in r.evidence
    )


def test_evaluate_against_group_uses_group_as_canonical():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    gate.normalize([a, b])
    g = _g(a)
    r = gate.evaluate(b, g)
    assert r.status == "verified"
    # An unmapped league name on the candidate is settled by the fixture itself
    # when both teams match exactly, and the acceptance is recorded as evidence.
    c = _m("wwin", "Sarajevo", "Zeljeznicar", "Liga totally unknown", event_id="3")
    gate.normalize([c])
    r2 = gate.evaluate(c, g)
    assert r2.status == "verified"
    assert any(e.reason == "league_unmapped_teams_exact" for e in r2.evidence)
    # ...but not when a team spelling differs: then the league is a hard reject.
    d = _m("wwin", "Sarajevo", "Zeljo", "Liga totally unknown", event_id="4")
    gate.normalize([d])
    r3 = gate.evaluate(d, g)
    assert r3.status == "rejected"
    assert "league_mismatch" in r3.reasons


def test_evaluate_records_group_league_mismatch_with_soft_pair_failure():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    # Admiralbet, not mbet: this test is about a soft failure that the group's
    # own league then turns into a hard reject, and only a book that declares a
    # per-event route still fails softly on an unproven link.
    b = _m(
        "admiralbet",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        url="https://bookmaker.test/match",
        link_ok=False,
    )
    gate.normalize([a, b])
    group = _g(a)
    group.league = "serie_a"  # a mapped league that contradicts both matches
    r = gate.evaluate(b, group)
    assert r.status == "rejected"
    assert r.reasons == ["link_unverified", "league_mismatch"]


def test_evaluate_checks_group_canonical_team_fields():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    gate.normalize([a, b])
    group = _g(a)
    group.canonical_home = "different_home"
    group.canonical_away = "different_away"
    r = gate.evaluate(b, group)
    assert r.status == "suggested"
    assert r.reasons == ["team_unresolved"]


def test_evaluate_checks_group_kickoff():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    gate.normalize([a, b])
    group = _g(a)
    group.kickoff = K + timedelta(minutes=45)
    r = gate.evaluate(b, group)
    assert r.status == "suggested"
    assert r.reasons == ["kickoff_delta"]


def test_evaluate_swap_flag_uses_group_canonical_orientation():
    gate = CertaintyGate()
    a = _m("a", "Alpha", "Bravo", "BiH - Premier Liga", event_id="1")
    b = _m("b", "Bravo", "Alpha", "BiH - Premier Liga", event_id="2")
    gate.normalize([a, b])
    group = _g(a, league=a.league_normalized)
    group.canonical_home = a.away_team_normalized
    group.canonical_away = a.home_team_normalized

    pair_result = gate.evaluate_pair(b, a)
    group_result = gate.evaluate(b, group)
    assert pair_result.is_swapped is True
    assert group_result.status == "verified"
    assert group_result.is_swapped is False


def test_fuzzy_swap_flag_requires_both_teams_to_line_up():
    gate = CertaintyGate(alias_allowlist={"alpha united|alpha"})
    a = _m(
        "a",
        "Alpha United",
        "Bravo United",
        "League",
        home_n="alpha united",
        away_n="bravo united",
        event_id="1",
    )
    b = _m(
        "b",
        "Gamma United",
        "Alpha",
        "League",
        home_n="gamma united",
        away_n="alpha",
        event_id="2",
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.is_swapped is False
    assert r.reasons == ["team_unresolved"]


# ---------------------------------------------------------------------------
# The link gate and `config/bookmaker_deeplinks.json`
#
# The design spec's clarified link policy: a book with a per-event URL that has
# not been verified is `link_unverified`; a book that genuinely offers no
# per-event URL must SAY SO with `supports_event_id: false` and is accepted with
# a `no_event_link` evidence note. A book that has said nothing is not accepted:
# silence is not a declaration.
# ---------------------------------------------------------------------------


def _boom(*args: object, **kwargs: object) -> None:
    raise OSError("config unreadable")


def _deeplink_config() -> dict:
    return json.loads(Path("config/bookmaker_deeplinks.json").read_text(encoding="utf-8"))


def test_a_book_that_declares_no_per_event_route_is_accepted():
    gate = CertaintyGate()
    a = _m("mbet", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1", link_ok=False)
    b = _m("wwin", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified", (
        "two books that both declare `supports_event_id: false` leave no link to "
        f"prove, which is the spec's accepted case; reasons were {r.reasons}"
    )
    assert r.reasons == []


def test_a_declared_no_link_book_is_accepted_even_with_a_url_and_an_event_id():
    """The state every scraped match is actually in: a feed id and a fallback URL.

    This is the shape the defect hid behind. ``wwin`` publishes a Betradar event
    id and a site URL, neither of which is a per-event route, and its own
    declaration says so. A gate that reads "there is an id" as "there is an
    unproven link" cannot tell a route from a feed id, so it refuses every book
    in the configuration except the three that declare a route.
    """
    gate = CertaintyGate()
    a = _m(
        "mbet",
        "Sarajevo",
        "Zeljeznicar",
        "BiH - Premier Liga",
        url="https://www.mbet.ba/",
        event_id="918273",
        link_ok=False,
    )
    b = _m(
        "wwin",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        url="https://wwin.ba/kladjenje/",
        event_id="4620444",
        link_ok=False,
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified", f"reasons were {r.reasons}"
    assert r.reasons == []


def test_the_accepted_no_link_note_is_a_well_formed_evidence_record():
    """`verified` includes links, so the record that a link is absent is evidence.

    Not a reason and not a comment: a `MatchEvidence` row on the result, one per
    side, naming the deliberate absence.
    """
    gate = CertaintyGate()
    a = _m("mbet", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1", link_ok=False)
    b = _m("wwin", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    notes = [e for e in r.evidence if e.reason == "no_event_link"]
    assert len(notes) == 2
    for note in notes:
        assert note.rule == "link_evidence"
        assert note.source == "rule"
        assert note.confidence == 1.0, (
            "a declared absence is as certain as a proven link; 0.0 would read as "
            "an unproven claim in the evidence trail"
        )


def test_a_book_that_declares_a_route_still_needs_it_proven():
    gate = CertaintyGate()
    a = _m(
        "mdshop",
        "Sarajevo",
        "Zeljeznicar",
        "BiH - Premier Liga",
        url="https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=1",
        event_id="1",
        link_ok=False,
    )
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["link_unverified"]


def test_a_declared_route_book_with_no_captured_url_is_link_unverified():
    """An empty URL is a capture gap for a book that has a route, not an absence.

    Reporting it as `no_event_link` would claim the book has no per-event page,
    which its own declaration contradicts, and it would tell the next engineer
    that emptying the URL is a way to unblock a group. It is not.
    """
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", link_ok=False)
    b = _m("admiralbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["link_unverified"]


def test_a_book_with_no_declaration_fails_safe():
    """No declaration is silence, and silence is not proof of absence."""
    gate = CertaintyGate()
    a = _m("nosuchbook", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", link_ok=False)
    b = _m("alsonotabook", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["no_event_link"]
    notes = [e for e in r.evidence if e.reason == "no_event_link"]
    assert notes and all(note.confidence == 0.0 for note in notes), (
        "an undeclared book is the blocking case, so its evidence must not claim "
        "the same certainty as a declared absence"
    )


def test_an_undeclared_book_with_a_url_is_link_unverified_not_accepted():
    gate = CertaintyGate()
    a = _m(
        "nosuchbook",
        "Sarajevo",
        "Zeljeznicar",
        "BiH - Premier Liga",
        url="https://nosuchbook.test/match",
        link_ok=False,
    )
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["link_unverified"]


def test_a_malformed_declaration_does_not_grant_trust(monkeypatch):
    """Only an explicit boolean ``false`` is a declaration of absence.

    A missing key, a string, or a null must all fail safe. A typo in the JSON
    must never be able to grant a book the trust that ``false`` grants.
    """
    from scrapers import common as scraper_common

    monkeypatch.setattr(
        scraper_common,
        "_deeplink_cache",
        {
            "missingkey": {"template": "https://example.test/"},
            "stringy": {"supports_event_id": "false", "template": "https://x.test/"},
            "nulled": {"supports_event_id": None, "template": "https://x.test/"},
            "declared": {"supports_event_id": False, "template": "https://x.test/"},
        },
    )
    gate = CertaintyGate()
    for bookmaker, blocks in (
        ("missingkey", True),
        ("stringy", True),
        ("nulled", True),
        ("declared", False),
    ):
        a = _m(bookmaker, "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", link_ok=False)
        # The partner is one of the declared-false books, so it contributes no
        # reason of its own and every reason below comes from the book under test.
        b = _m("declared", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2",
               link_ok=False)
        gate.normalize([a, b])
        r = gate.evaluate_pair(a, b)
        if blocks:
            assert r.status == "suggested", bookmaker
            assert r.reasons == ["no_event_link"], f"{bookmaker}: {r.reasons}"
        else:
            assert r.status == "verified", f"{bookmaker} declares false: {r.reasons}"


def test_an_unreadable_deep_link_config_fails_safe(monkeypatch):
    """An unreadable config is the worst case: it must refuse, not accept."""
    from scrapers import common as scraper_common

    monkeypatch.setattr(scraper_common, "_deeplink_cache", None)
    monkeypatch.setattr(scraper_common, "open", _boom, raising=False)
    assert scraper_common._load_deeplink_config() == {}
    gate = CertaintyGate()
    a = _m("mbet", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", link_ok=False)
    b = _m("wwin", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert r.reasons == ["no_event_link"]


@pytest.mark.real_deeplinks
def test_every_declared_route_book_blocks_and_every_other_book_is_accepted():
    """Driven from the JSON, so flipping a declaration is a reviewed diff.

    This is what the six ``supports_event_id: false`` books are worth: nothing
    blocks them, so a group of them verifies on identity alone. It is
    deliberately parameterised over the config rather than pinned to a literal
    list, so an operator who flips a declaration has to see this fail.
    """
    raw = _deeplink_config()
    declared = {book for book, cfg in raw.items() if cfg.get("supports_event_id") is True}
    assert declared == {"mozzartbet", "maxbet"}, (
        "the declared-route set changed; the spec's inert-route claim and the "
        "README headline both name these books, so revisit them before trusting "
        "this test"
    )
    gate = CertaintyGate()
    for bookmaker in raw:
        a = _m(bookmaker, "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1",
              link_ok=False)
        b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2",
               link_ok=False)
        gate.normalize([a, b])
        r = gate.evaluate_pair(a, b)
        if bookmaker in declared:
            assert r.reasons == ["link_unverified"], f"{bookmaker}: {r.reasons}"
        else:
            assert r.reasons == [], f"{bookmaker} declares no route: {r.reasons}"


def test_a_verified_link_still_wins_over_the_declaration():
    """`deep_link_verified` is the browser check; nothing may pre-empt it."""
    gate = CertaintyGate()
    a = _m("mbet", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1", link_ok=True)
    b = _m("wwin", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2", link_ok=True)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "verified"
    assert [e.reason for e in r.evidence if e.rule == "link_evidence"] == [
        "verified_link",
        "verified_link",
    ]


@pytest.mark.parametrize("bookmaker", ["mbet", "wwin", "sportplus", "betole"])
def test_evaluating_against_a_group_accepts_a_declared_no_link_book(bookmaker):
    """The path the matcher actually uses, not only `evaluate_pair`."""
    gate = CertaintyGate()
    anchor = _m("mbet", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1",
                link_ok=False)
    other = _m(bookmaker, "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2",
               link_ok=False)
    gate.normalize([anchor, other])
    group = _g(anchor, league=anchor.league_normalized)
    r = gate.evaluate(other, group)
    assert r.status == "verified", f"{bookmaker}: {r.reasons}"
    assert r.reasons == []
