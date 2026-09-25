"""CertaintyGate: hard gates for verified same-event claims."""

from datetime import UTC, datetime, timedelta, timezone

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


def test_aware_and_naive_kickoffs_compare_equal():
    gate = CertaintyGate()
    aware = K.replace(tzinfo=timezone(timedelta(hours=2))) + timedelta(hours=2)
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", kickoff=K, event_id="1")
    b = _m(
        "mbet",
        "Sarajevo",
        "Zeljeznicar",
        "Premijer Liga BiH",
        kickoff=aware.astimezone(UTC).replace(tzinfo=None),
        event_id="2",
    )
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "kickoff_delta" not in r.reasons


def test_missing_kickoff_never_verified():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=None, event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status != "verified"
    assert "kickoff_missing" in r.reasons


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


def test_kickoff_delta_over_15_minutes_rejected():
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
    assert r.status != "verified"
    assert "kickoff_delta" in r.reasons


def test_league_mismatch_rejected():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Arsenal", "Chelsea", "Engleska - Premier liga", event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "league_mismatch" in r.reasons


def test_category_mismatch_rejected():
    gate = CertaintyGate()
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", tags=[], event_id="1")
    b = _m("mbet", "Sarajevo U21", "Zeljeznicar U21", "Premijer Liga BiH", tags=["U21"], event_id="2")
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "category_mismatch" in r.reasons


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
    assert "link_unverified" in r.reasons


def test_missing_event_link_is_reported_separately():
    gate = CertaintyGate()
    a = _m("a", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", link_ok=False)
    b = _m("b", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", link_ok=False)
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert r.status == "suggested"
    assert "no_event_link" in r.reasons
    assert "link_unverified" not in r.reasons


def test_explicit_equivalence_allows_different_leagues():
    gate = CertaintyGate(league_equivalences={("europa_league", "conference_league")})
    a = _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="1")
    b = _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="2")
    a.league_normalized, b.league_normalized = "europa_league", "conference_league"
    gate.normalize([a, b])
    r = gate.evaluate_pair(a, b)
    assert "league_mismatch" not in r.reasons


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
    assert r2.status != "verified"
    assert "team_unresolved" in r2.reasons


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
    assert r.status != "verified"
    assert r.is_swapped is False
    assert "team_unresolved" in r.reasons
