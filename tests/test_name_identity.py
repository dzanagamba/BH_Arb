"""Identity rules: initialisms match, roster markers veto, org noise does not."""

from __future__ import annotations

from engine.name_identity import normalize, similarity


def test_org_noise_is_removed():
    assert normalize("PaiN Gaming") == "pain"
    assert similarity("PaiN", "PaiN Gaming") >= 0.95


def test_an_initialism_matches_the_full_name():
    assert similarity("LAL", "Los Angeles Lakers") == 1.0
    assert similarity("BC", "Boston Celtics") == 1.0


def test_a_differing_roster_marker_is_a_veto():
    assert similarity("Evil Geniuses", "Evil Geniuses GC") == 0.0
    assert similarity("Sarajevo", "Sarajevo U21") == 0.0
    assert similarity("Sarajevo", "Sarajevo Women") == 0.0


def test_a_one_sided_colour_addition_is_a_veto():
    assert similarity("Red Star", "Red Star Blue") == 0.0


def test_a_plain_spelling_variation_still_scores():
    assert similarity("Manchester United", "Man United") >= 0.7


def test_unrelated_names_score_low():
    assert similarity("Arsenal", "Chelsea") < 0.5
