"""Every book's youth/reserve/women spelling reaches the matcher in one form.

The spellings below are taken verbatim from the 2026-10-20 prematch scan
(``cache/last_scan.json``); each group is the same real fixture as the books
listed it.
"""

from datetime import datetime

import pytest

from engine.arbitrage import _collect_listings
from engine.matcher import MatchMatcher
from engine.normalizer import canonical_team_name, canonicalize_fixture
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue

SAME_FIXTURE = [
    pytest.param(
        [
            ("Porto Y", "PSV J", "LIGA  ŠAMPIONA  MLADI"),          # mozzartbet
            ("Porto U19", "PSV U19", "Liga šampiona mladi"),         # mdshop
            ("ML/Porto", "PSV", "UEFA - LIGA MLADIH"),                # sportplus
            ("Porto/19", "PSV/19", "Medunarodne - Mladi - UEFA Omladinska liga"),  # wwin
        ],
        ("U19",),
        id="youth-league",
    ),
    pytest.param(
        [
            ("Millwall M21", "Sheffield Utd M21", "ENGLESKA  -  LIGA  KUP  M21"),
            ("Millwall U21", "Sheffield Utd U21", "ENGLAND Premier League Cup U21"),
            ("U21/Millwall", "Sheffield Utd", "ENGLESKA - PREMIER LIGA KUP U21 - GRUPA F"),
            ("21/Millwall", "Sheffield Utd", "ENGLESKI PREMIER LIGA KUP U21 - GRUPA F"),
            ("Millwall/21", "Sheffield Utd/21", "Engleska (Am.) - Premier Liga Kup"),
        ],
        ("U21",),
        id="u21-cup",
    ),
    pytest.param(
        [
            ("Wigan M21", "Bolton M21", "ENGLESKA  RAZVOJNA  LIGA"),
            ("ML/Wigan", "Bolton", "ENGLESKA - PROFESSIONAL DEVELOPMENT"),
            ("21/Wigan", "Bolton", "ENGLESKA PROF. DEVELOPMENT"),
        ],
        ("U21",),
        id="development-league",
    ),
    pytest.param(
        [
            ("Sturm Graz 2", "Ried", "Austrija 2"),
            ("Sturm Graz (Am)", "Ried", "AUSTRIA 2"),
            ("Sturm Graz (A)", "Ried", "Austrija - 2. Liga"),
            ("Sturm Graz II", "Ried", "Austrija - 2. Liga"),
        ],
        ("Reserve",),
        id="reserve-side",
    ),
    pytest.param(
        [
            ("Sarmiento 2", "Tigre 2", "Argentina Rezerve"),
            ("R/Sarmiento", "Tigre", "ARGENTINA - 1.LIGA - REZERVE"),
            ("RE/Sarmiento", "Tigre", "ARGENTINSKA 1.LIGA REZERVE - GRUPA B"),
            ("Sarmiento/Rez.", "Tigre/Rez.", "Argentina - Rezerve"),
        ],
        ("Reserve",),
        id="reserve-league",
    ),
    pytest.param(
        [
            ("Koge W", "Brondby W", "DANSKA  1  W"),
            ("Koge W", "Brondby W", "Danska 1 Ž"),
            ("NŽ/Koge", "Brondby", "DANSKA 1.LIGA (Ž)"),
            ("Koge/Ž", "Brondby/Ž", "Danska - Elitedivisionen (Ž)"),
            ("Koge (W)", "Brondby (W)", "Denmark 1 Women"),
        ],
        ("Women",),
        id="women",
    ),
    pytest.param(
        [
            ("Anstey Nomads", "Macclesfield", "ENGLESKA - FA KUP"),
            ("Anstey Nomads", "Macclesfield (1:1)", "ENGLESKA - FA KUP - KVALIFIKACIJE"),
            ("Anstey Nomads", "Macclesfield [1.ut.1:1]", "ENGLESKI FA KUP"),
        ],
        (),
        id="score-note",
    ),
    pytest.param(
        [("Feirense", "Benfica B", "Portugalija 2"), ("Feirense", "Benfica [B]", "PORTUGALSKA 2.LIGA")],
        (),
        id="bracketed-b-team",
    ),
    pytest.param(
        [("Istiklol", "Al Arabi", "AFC"), ("Istiklol", "Al Arabi (KW)", "AFC")],
        (),
        id="country-note",
    ),
]


@pytest.mark.parametrize(("listings", "tags"), SAME_FIXTURE)
def test_every_books_spelling_of_one_fixture_canonicalizes_alike(listings, tags):
    results = {canonicalize_fixture(home, away, league) for home, away, league in listings}
    assert len(results) == 1, sorted(results, key=str)
    assert next(iter(results)).tags == tags


@pytest.mark.parametrize(
    ("home", "away", "league", "expected"),
    [
        # A trailing "W" outside a women's league abbreviates the club's city.
        ("Legia W.", "Slask W", "POLJSKA 1.LIGA", ("Legia W.", "Slask W", ())),
        ("Sheffield W.", "Notts County", "ENGLESKA 3", ("Sheffield W.", "Notts County", ())),
        ("Havant & W", "Bath", "ENGLAND 7 Southern", ("Havant & W", "Bath", ())),
        # A bare "B" is Bratislava / Bialystok, not a B team.
        ("Roma", "Slovan B", "LIGA PRVAKA", ("Roma", "Slovan B", ())),
        ("Jagiellonia B", "Anderlecht", "EUROPSKA LIGA", ("Jagiellonia B", "Anderlecht", ())),
        # A slash inside a club's name is not a marker.
        ("Bodo/Glimt", "Valerenga", "NORWAY 1", ("Bodo/Glimt", "Valerenga", ())),
        # "Y" is Jujuy outside a youth competition.
        ("Gimnasia Y", "Ferro", "Argentina 2", ("Gimnasia Y", "Ferro", ())),
        # Senior clubs whose name ends in II keep it (and keep their old tag).
        ("Willem II", "Ajax", "Holandija 1", ("Willem II", "Ajax", ("Reserve",))),
    ],
)
def test_names_that_only_look_like_markers_are_left_alone(home, away, league, expected):
    result = canonicalize_fixture(home, away, league)
    assert (result.home, result.away, result.tags) == expected


@pytest.mark.parametrize(
    ("home", "away", "league"),
    [
        ("U21/Millwall", "Sheffield Utd.", "PREMIER LIGA KUP U21"),
        ("Brisbane Roar/Ž", "Perth/Ž", "Australija"),
        ("Porto Y", "PSV J", "LIGA ŠAMPIONA MLADI"),
        ("ML/Wigan", "Bolton", "nothing about age"),
        ("Benfica [B]", "Austria Wien (A)", "x"),
    ],
)
def test_canonicalization_is_idempotent(home, away, league):
    once = canonicalize_fixture(home, away, league)
    assert canonicalize_fixture(once.home, once.away, league) == once


def test_allowlist_entries_are_read_in_canonical_form():
    assert canonical_team_name("Rapid Vienna (Am)") == "Rapid Vienna II"
    assert canonical_team_name("Benfica [B]") == "Benfica B"
    assert canonical_team_name("Brisbane Roar/Ž") == "Brisbane Roar (W)"
    assert canonical_team_name("Fluminense [1.ut.2:1]") == "Fluminense"


def _match(book: str, home: str, away: str, league: str, event_id: str) -> Match:
    return Match(
        bookmaker=book,
        home_team=home,
        away_team=away,
        league=league,
        kickoff=datetime(2026, 10, 20, 12, 0),
        event_id=event_id,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0),
            OddsValue(label="X", value=3.4),
            OddsValue(label="2", value=3.6),
        ])],
    )


def test_marker_spellings_group_across_books_and_keep_the_books_spelling():
    """Three route-less books, three spellings of one U21 fixture: one group.

    (conftest.py makes MDShop declare a route, so it is not used here.)
    """
    matcher = MatchMatcher()
    groups = matcher.group_matches([
        _match("mbet", "Wigan U21", "Bolton U21", "ENGLAND Development League U21", "1"),
        _match("sportplus", "ML/Wigan", "Bolton", "ENGLESKA - PROFESSIONAL DEVELOPMENT", "2"),
        _match("wwin", "Wigan/21", "Bolton/21", "Engleska (Am.) - Profesionalna Razvojna Liga", "3"),
    ])
    assert len(groups) == 1
    group = groups[0]
    assert {m.bookmaker for m in group.matches} == {"mbet", "sportplus", "wwin"}
    assert {m.home_team for m in group.matches} == {"Wigan U21"}
    assert all(m.category_tags == ["U21"] for m in group.matches)

    listings = _collect_listings(group)
    assert listings["sportplus"]["home"] == "ML/Wigan"
    assert listings["wwin"]["away"] == "Bolton/21"
    assert listings["mbet"]["home"] == "Wigan U21"


def test_normalize_matches_runs_from_the_books_spelling_every_time():
    matcher = MatchMatcher()
    match = _match("sportplus", "U21/Millwall", "Sheffield Utd.", "LIGA KUP U21", "1")
    matcher.normalize_matches([match])
    matcher.normalize_matches([match])
    assert (match.home_team, match.away_team) == ("Millwall U21", "Sheffield Utd. U21")
    assert (match.home_team_source, match.away_team_source) == ("U21/Millwall", "Sheffield Utd.")


def test_a_reviewed_club_alias_holds_for_the_same_side_of_both_clubs():
    """'AEK|AEK Atena' is a reviewed alias; their U19 sides are the same pair."""
    matcher = MatchMatcher()
    matcher._alias_partners = {}
    matcher._alias_allowlist.add("AEK Testklub|AEK Testklub Atena")
    key = matcher.gate._raw_team_key
    matcher._alias_partners[key("AEK Testklub")] = {"AEK Testklub Atena"}
    matcher._alias_partners[key("AEK Testklub Atena")] = {"AEK Testklub"}

    groups = matcher.group_matches([
        _match("sportplus", "ML/Man City", "AEK Testklub", "UEFA - LIGA MLADIH", "1"),
        _match("premier_kladionica", "ML/Man City", "AEK Testklub Atena", "UEFA LIGA MLADI", "2"),
    ])
    assert len(groups) == 1
    assert "AEK Testklub U19|AEK Testklub Atena U19" in matcher._alias_allowlist
    # The senior pairing is not what the U19 one is accepted on.
    assert matcher.gate._is_allowlisted("AEK Testklub U19", "AEK Testklub Atena U19")


def test_a_senior_side_never_pairs_with_its_youth_side():
    matcher = MatchMatcher()
    groups = matcher.group_matches([
        _match("mbet", "Wigan", "Bolton", "ENGLAND 3", "1"),
        _match("sportplus", "ML/Wigan", "Bolton", "ENGLESKA - PROFESSIONAL DEVELOPMENT", "2"),
    ])
    assert groups == []


def test_listings_fall_back_to_the_canonical_name_when_nothing_changed():
    group = MatchGroup(canonical_home="a", canonical_away="b", matches=[
        _match("mbet", "Sarajevo", "Zeljeznicar", "BiH 1", "1"),
    ])
    assert _collect_listings(group)["mbet"]["home"] == "Sarajevo"
