"""CertaintyGate: hard gates for verified same-event claims."""

from datetime import datetime, timedelta, timezone

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
    league_b = _m("b", "Sarajevo", "Zeljeznicar", "Other League", event_id="2")
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
    # Unknown league on the candidate is a hard reject even when the group is known
    c = _m("wwin", "Sarajevo", "Zeljeznicar", "Liga totally unknown", event_id="3")
    gate.normalize([c])
    r2 = gate.evaluate(c, g)
    assert r2.status == "rejected"
    assert "league_mismatch" in r2.reasons


def test_evaluate_records_group_league_mismatch_with_soft_pair_failure():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m(
        "mbet",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        url="https://bookmaker.test/match",
        link_ok=False,
    )
    gate.normalize([a, b])
    group = _g(a)
    group.league = "different_group_league"
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
