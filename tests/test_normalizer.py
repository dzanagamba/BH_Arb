"""Tests for team/league name normalization."""

import json
from pathlib import Path

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
    assert n.normalize_league("Liga Portugal") == "primeira_liga"
    assert n.normalize_league("Engleska - Premier liga") == "premier_league"


def test_german_tier_two_has_one_reachable_canonical_id():
    n = TeamNormalizer()
    assert n.normalize_league("2. Bundesliga") == "bundesliga_2"


def test_bulgarian_second_league_is_not_treated_as_generic():
    n = TeamNormalizer()
    assert n.normalize_league("Vtora Liga") == "bugarian_second_league"


def test_league_mappings_have_no_cleaned_name_collisions():
    mapping_path = Path(__file__).parents[1] / "config" / "league_mappings.json"
    mappings = json.loads(mapping_path.read_text(encoding="utf-8"))
    normalizer = TeamNormalizer()
    owners_by_cleaned: dict[str, set[str]] = {}

    for canonical_id, variations in mappings.items():
        if canonical_id.startswith("_"):
            continue
        for variation in variations:
            cleaned = normalizer._full_clean(variation)
            owners_by_cleaned.setdefault(cleaned, set()).add(canonical_id)

    duplicates = {
        cleaned: sorted(canonical_ids)
        for cleaned, canonical_ids in owners_by_cleaned.items()
        if len(canonical_ids) > 1
    }
    assert not duplicates, f"cleaned league names map to multiple canonical ids: {duplicates}"
