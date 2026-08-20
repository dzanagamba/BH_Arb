"""Tests for team/league name normalization."""

from engine.normalizer import TeamNormalizer


def test_diacritics_normalized():
    n = TeamNormalizer()
    assert n.normalize_team("Željezničar") == "fk_zeljeznicar"
    assert n.normalize_team("Široki Brijeg") == "nk_siroki_brijeg"
    assert n.normalize_team("Velež Mostar") == "fk_velez"


def test_cyrillic_transliteration():
    n = TeamNormalizer()
    # Црвена Звезда → crvena zvezda → phonetic override → red star belgrade
    assert n.normalize_team("Црвена Звезда") == "red_star_belgrade"


def test_phonetic_overrides():
    n = TeamNormalizer()
    assert n.normalize_team("Čelzi") == "chelsea"
    assert n.normalize_team("Bajern Minhen") == "bayern_munich"
    assert n.normalize_team("Lajpcig") == "rb_leipzig"


def test_prefix_stripping():
    n = TeamNormalizer()
    assert n.normalize_team("FK Sarajevo") == "fk_sarajevo"
    assert n.normalize_team("FC Barcelona") == "barcelona"


def test_unknown_team_returns_cleaned():
    n = TeamNormalizer()
    result = n.normalize_team("Some Random Club FC")
    assert "some random club" in result


def test_league_normalization():
    n = TeamNormalizer()
    assert n.normalize_league("BiH - Premier Liga") == "premier_liga_bih"
    assert n.normalize_league("Premijer Liga BiH") == "premier_liga_bih"
    assert n.normalize_league("Engleska - Premier liga") == "premier_league"
