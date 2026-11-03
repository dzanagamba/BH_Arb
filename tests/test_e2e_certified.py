"""End-to-end: captured payloads -> parse -> registry -> normalise -> gate ->
group -> surebet -> served.

WHAT THESE TESTS ARE FOR
------------------------
Every other file in this suite proves one stage against a hand-made stand-in.
This one proves the *seams*, because that is where a chain silently rots: a
parser that reads the right market out of the right block but the matcher
relabels it, a gate that accepts a pair whose odds are then read in the wrong
frame, a server that groups correctly and then serves a stale cache.

The three books used here are driven through their **real** market-parsing entry
points and fed the **real** payloads in ``tests/fixtures/markets/``. The odds in
this file are therefore not invented -- they are the ones the books served on
2026-09-25, and the surebet asserted below is a genuine arbitrage between them.
That matters: an end-to-end test built from hand-made ``Market`` objects cannot
fail when a registry ID, a label order or a swap map is wrong in the same way
everywhere, which is exactly the class of bug that reached production.

WHAT IS REAL AND WHAT IS FILLED IN
----------------------------------
Real, straight from the capture: every market, every label, every decimal odds
value, and the books' own event ids. Filled in by this module, because three
different books' captures are three different real fixtures and the gate can
only judge a claim about *one* fixture: the two team names, the league string
and the kickoff. That is the same split ``tests/test_market_fixtures.py``
documents for MBet -- "the fixture supplies the odds verbatim and only the event
shell around them is filled in". Every team spelling used here is either
identical across books or covered by an entry in
``config/team_alias_allowlist.json``, so the pairing exercises the reviewed
alias path and nothing else.

The single fixture, and the frame the group ends up in
------------------------------------------------------
The real fixture is "Sarajevo vs Željezničar" in the BiH - Premier Liga. MBet
publishes it that way and therefore anchors the group. WWIN and SportPlus both
publish the same fixture **reversed**, which is why this file is about
orientation: the gate decides the frame, the matcher relabels the two reversed
books' 1X2 and Double Chance legs into it, and ``find_surebets`` then reads
those books' odds in the canonical frame.

That choice is load-bearing. The three captured 1X2 books also form an
arbitrage in their raw published frame, but a 24.1% one, which
``ArbitrageEngine`` rejects outright as a scraper error. Only once the two
reversed books are relabelled does the same three books produce a plausible
14.90% surebet whose leg-to-book mapping is exact. So a regression anywhere in
the swap path does not merely change a number -- it silently deletes the
surebet, and ``test_gate_orientation_is_what_makes_the_three_books_priceable``
asserts exactly that, using the unswapped group as its own control.

HONESTY NOTE ON LINKS
---------------------
Every scraper hardcodes ``deep_link_verified=False``, and Task 12 proved
MDShop's and Admiralbet's declared ``?event=`` routes are inert; only
Mozzartbet's verifies. What that means for the three books used here changed
when the gate was taught to read ``config/bookmaker_deeplinks.json``: **all
three declare ``supports_event_id: false``**, so for them the absence of a
per-event route is a declared fact rather than an unproven link, and they verify
as scraped. ``test_the_captured_books_verify_and_price_with_no_stored_proof`` is
that claim, end to end.

The inert routes are still a bookmaker-side fact about MDShop and Admiralbet and
this file does not contradict them: a book that declares a route must still have
it proven, and the negative cases below remove exactly one such proof and show the
surebet disappear. The assertions are about the gates being honoured, not about a
currently unreachable end state.

NOT COVERED HERE
----------------
* The live feed. Every capture is prematch, because arbitrage is a prematch
  question and a live group's odds expire mid-scan.
* The AI ranking path, which can only reorder the review queue and is owned by
  ``tests/test_scan_candidates.py``. ``api.MatchAI`` is replaced below by a stub
  that has no HTTP client, so no test in this file can reach the network, and
  the served tests assert the AI never even gets a say in a decision.
* That an UNREVIEWED fuzzy alias is refused. Every spelling in this file is
  either byte-identical across books or already on the allowlist, so the file
  cannot tell "the allowlist is required" from "any fuzzy pair will do". That
  rule is pinned by ``tests/test_certainty.py`` and
  ``tests/test_matcher_certified.py::test_unreviewed_mapping_variation_is_not_verified``,
  both of which fail when the allowlist requirement is removed.
* Launching a browser. ``scrapers/base.py`` imports Playwright at module scope and
  ``server/api.py`` imports the scrapers, so the import always happens; what
  must never happen is ``async_playwright().start()``. The only scrapers
  ``run_scan`` calls are the fakes installed by ``stubbed_scrapers`` -- every
  other book is switched off -- and the deep-link browser check
  (``_run_link_verification``) is on-demand, never part of a scan.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from config.settings import BOOKMAKERS, MAX_SUREBET_PROFIT_PERCENT, ODDS_TTL_SECONDS
from engine.arbitrage import ArbitrageEngine
from engine.market_registry import MarketRegistry
from engine.matcher import MatchMatcher
from models.schemas import MarketType, Match, MatchGroup, Surebet
from scrapers.common import BOOKMAKER_TZ, build_event_url, parse_nsoft_bets
from scrapers.mbet import MBetScraper
from scrapers.sportplus import SportPlusScraper
from scrapers.wwin import _build_markets_from_bets
from server import api


@pytest.fixture(autouse=True)
def _disable_price_guard(monkeypatch):
    """The certified captures are three different real fixtures, so a cross-book
    price comparison is meaningless here; the guard has its own unit tests."""
    monkeypatch.setattr(api, "PRICE_GUARD_ENABLED", False)

# Frozen copies of the 2026-09-25 captures. This test pins their prices (see
# EXPECTED_LEGS), so it must not follow tests/fixtures/markets/ when that is refreshed.
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "e2e_certified"

# Far enough out that neither the engine's expiry buffer nor its odds-TTL check
# can expire the group while the test runs.
KICKOFF = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=30)

# The one real fixture these captures are read against. MBet spells it this way;
# WWIN uses the two reviewed aliases, SportPlus reverses the sides.
HOME, AWAY = "Sarajevo", "Željezničar"
LEAGUE = "BiH - Premier Liga"

# Anchored in this order: the first book the matcher processes with a specific
# league becomes the group's canonical frame.
BOOKS = ("mbet", "wwin", "sportplus")
FLIPPED_BOOKS = ("wwin", "sportplus")

# The two books that DECLARE a per-event route, used where a link has to be
# load-bearing. Both prematch captures are the same real NSoft event.
ROUTE_BOOKS = ("mdshop", "admiralbet")
ROUTE_EVENT_ID = "6828117"

# The leg each book must win, and at which of its OWN captured prices. Spelled
# out rather than read back from the engine, so a relabelling regression is
# reported as "sportplus must supply leg 2" and not as a changed percentage.
#
# These three constants are tied to the prices in the captures as they stand
# today. Re-running scripts/capture_market_fixtures.py changes those prices, and
# EXPECTED_LEGS, EXPECTED_MARGIN, EXPECTED_PROFIT and UNSWAPPED_COMBINATIONS all
# have to be re-derived from the new 1X2 legs. That is intended coupling -- a new
# capture must break this test -- but it surfaces as a leg-mapping failure, not
# as "re-capture the fixtures".
EXPECTED_LEGS = {"1": ("mbet", 5.0), "X": ("wwin", 3.5), "2": ("sportplus", 2.6)}
# 1/5.00 + 1/3.50 + 1/2.60 == 0.87027. Written out rather than taken from the
# engine's own output, so the expectation and the measurement stay independent.
EXPECTED_MARGIN = 1 / 5.0 + 1 / 3.5 + 1 / 2.6
EXPECTED_PROFIT = (1 / EXPECTED_MARGIN - 1) * 100

# Read the same three books in their published frame, the best 1X2 combination
# is 0.80565 -- a 24.13% "surebet" the engine must refuse. Both candidate
# assignments are listed so the control below cannot quietly pick a flattering
# one: the engine searches permutations, and the minimum has to be the minimum.
UNSWAPPED_COMBINATIONS = (
    {"1": 5.0, "X": 4.33, "2": 1.45},  # all three books agree: mbet best on 1
    {"1": 5.0, "X": 3.5, "2": 2.55},
    {"1": 5.0, "X": 3.6, "2": 2.55},
    {"1": 5.0, "X": 3.6, "2": 3.05},
    {"1": 5.0, "X": 4.33, "2": 2.55},
    {"1": 5.0, "X": 4.33, "2": 3.05},
    {"1": 2.6, "X": 4.33, "2": 3.05},
    {"1": 2.55, "X": 4.33, "2": 3.05},
)

# Outcome labels whose meaning a home/away flip inverts. Everything else
# (Over/Under, GG/NG, the draw) is orientation-free by construction.
_FLIP = {"1": "2", "2": "1", "1X": "X2", "X2": "1X"}


def _capture(bookmaker: str) -> dict[str, Any]:
    """The real prematch payload for one book, verbatim from the capture."""
    return json.loads(
        (FIXTURE_DIR / f"{bookmaker}_prematch.json").read_text(encoding="utf-8")
    )


# --- the three real parse entry points ---------------------------------------


def _mbet_match() -> Match:
    """MBet's real event parser, fed its real capture.

    ``MBetScraper._parse_event`` returns a whole ``Match`` -- bookmaker, url,
    event id, kickoff and markets all come out of the parser -- so the only
    thing this module supplies is the event shell the capture trimmed away
    (``competitors`` and ``tournament``). ``odds``, ``id_sport`` and the event
    id are the captured values.
    """
    data = _capture("mbet")
    parsed = MBetScraper()._parse_event(
        {
            "id": "e:fb:van-ahl:0005",
            "id_sport": data["context"]["id_sport"],
            "utc_scheduled": KICKOFF.isoformat(),
            "competitors": [{"name": HOME}, {"name": AWAY}],
            "tournament": {"name": LEAGUE},
            "odds": data["bets"],
        },
        set(),
        live=False,
    )
    assert parsed is not None, "the captured MBet event produced no Match"
    return parsed


def _wwin_match() -> Match:
    """WWIN's real market builder, plus the ``Match`` its scraper builds around it.

    ``scrapers/wwin.py`` has no standalone event parser:
    ``_build_markets_from_bets`` is the whole market entry point, and the
    surrounding ``Match`` is assembled inline in ``fetch_and_parse``
    (wwin.py:321-334). This reproduces that construction field for field, so
    the markets are WWIN's and only the identity shell is this module's.

    WWIN is where the allowlist is exercised: it spells the same fixture
    "Zeljeznicar - FK Sarajevo", which needs both ``zeljeznicar|željezničar``
    and ``fk sarajevo|sarajevo`` from ``config/team_alias_allowlist.json``.
    """
    data = _capture("wwin")
    return Match(
        bookmaker="wwin",
        home_team="Zeljeznicar",
        away_team="FK Sarajevo",
        league="Premijer Liga BiH",
        kickoff=KICKOFF,
        markets=_build_markets_from_bets(data["bets"], mode="prematch"),
        url="https://wwin.ba/kladjenje/",
        match_code="4620444",
        event_id="4620444",
        deep_link_verified=False,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _sportplus_match() -> Match:
    """SportPlus's real event parser, fed its real capture.

    ``_parse_match`` returns a whole ``Match`` and ``markets`` is the capture's
    ``bets`` list verbatim, so the excluded block 178 ("POLUVRIJEME ILI KRAJ", a
    1X2-shaped block that is not a match result) travels in with the real one.
    """
    data = _capture("sportplus")
    parsed = SportPlusScraper()._parse_match(
        {
            "id": "3289374",
            "sportName": "NOGOMET",
            "competitors": f"{AWAY} - {HOME}",
            # SportPlus sends Sarajevo wall-clock time without an offset.
            "matchDate": KICKOFF.replace(tzinfo=UTC)
            .astimezone(BOOKMAKER_TZ)
            .replace(tzinfo=None)
            .isoformat(),
            "leagueName": LEAGUE,
            "countryName": "BiH",
            "markets": data["bets"],
        },
        set(),
    )
    assert parsed is not None, "the captured SportPlus event produced no Match"
    return parsed


_PARSERS = {"mbet": _mbet_match, "wwin": _wwin_match, "sportplus": _sportplus_match}


def _scraped() -> list[Match]:
    """The three books exactly as a scan receives them: links unproven.

    All three declare ``supports_event_id: false``, so the gate settles their
    link from the declaration and this state verifies -- which is the point of
    ``test_the_captured_books_verify_and_price_with_no_stored_proof``.
    """
    return [_PARSERS[book]() for book in BOOKS]


def _linked() -> list[Match]:
    """The same three books with their links proven, as the store would mark them.

    Kept because the store still applies and its proofs are still what a declared
    book would get; for these three the gate no longer needs them.
    """
    return [m.model_copy(update={"deep_link_verified": True}) for m in _scraped()]


# --- observation helpers ------------------------------------------------------


def _markets(match: Match) -> dict[str, dict[str, float]]:
    """Flatten a match's markets to ``{market_type: {label: odds}}``."""
    return {
        market.market_type.value: {odd.label: odd.value for odd in market.odds}
        for market in match.markets
    }


def _flipped(markets: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """The same markets as a home/away reversal would relabel them."""
    return {
        market_type: {_FLIP.get(label, label): value for label, value in legs.items()}
        for market_type, legs in markets.items()
    }


def _one_group(matches: list[Match]) -> MatchGroup:
    """The single verified group these three books must produce."""
    groups = MatchMatcher().group_matches(matches)
    assert len(groups) == 1, f"expected exactly one verified group, got {len(groups)}"
    group = groups[0]
    assert group.status == "verified"
    return group


def _match_result_surebet(groups: list[MatchGroup]) -> Surebet | None:
    """The one 1X2 arbitrage in these groups, if the chain produced one."""
    found = [
        surebet
        for surebet in ArbitrageEngine().find_surebets(groups, min_profit=0.0)
        if surebet.market_type is MarketType.MATCH_RESULT
    ]
    assert len(found) <= 1, f"a group has at most one best 1X2 combination, got {found}"
    return found[0] if found else None


# --- seam 1: captured payload -> registry -> verified group -------------------


def test_captured_markets_reach_the_verified_group_through_the_registry():
    """What the real parsers emitted is what the group carries, in the group's frame.

    Three claims, each of which fails loudly at the group boundary:

    1. Every market type a real parser emitted is one the registry declares for
       that book and mode, and the group carries exactly the captured market
       set. The set and the count both matter: SportPlus's excluded block 178 is
       itself 1X2-shaped, so a leak that merged or duplicated it would change
       what the group holds rather than pass quietly.
    2. MBet anchors the group, so its markets arrive byte-identical to its parse.
       Anything else means the group mutated the anchor's odds.
    3. WWIN and SportPlus arrive relabelled 1<->2 and 1X<->X2, with every
       decimal value and every orientation-free label untouched. That is the
       claim a broken swap map cannot fake: the values stay the books' own, only
       the legs move, and these are the odds the engine prices next.
    """
    captured = {book: _capture(book) for book in BOOKS}
    parsed = {m.bookmaker: m for m in _linked()}
    group = _one_group(list(parsed.values()))

    registry = MarketRegistry()
    for book, match in parsed.items():
        emitted = _markets(match)
        assert set(emitted) == set(captured[book]["expected_markets"]), (
            f"{book}: the real parse emitted {sorted(emitted)} but the capture "
            f"declares {sorted(captured[book]['expected_markets'])}"
        )
        for market_type in emitted:
            assert registry.ids_for(book, "prematch", MarketType(market_type)), (
                f"{book}/prematch/{market_type} reached the pipeline without being "
                "declared in the registry"
            )
        carried = _markets(next(m for m in group.matches if m.bookmaker == book))
        expected = _flipped(emitted) if book in FLIPPED_BOOKS else emitted
        assert carried == expected, f"{book}: the group does not carry this book's odds"

    assert (group.canonical_home, group.canonical_away) == ("fk_sarajevo", "fk_zeljeznicar")
    assert group.league == "premier_liga_bih"

    by_book = {m.bookmaker: m for m in group.matches}
    assert by_book["mbet"].is_swapped is False
    for book in FLIPPED_BOOKS:
        assert by_book[book].is_swapped is True, (
            f"{book} publishes the fixture reversed, so the group must record the flip"
        )

    # The gate's own evidence, not just the flag. Each accepted pairing appends
    # one `team_identity` record, and the gate attributes the allowlist to the
    # pairing that needed it: WWIN spells both teams differently, so its record
    # is `source="allowlist"` with `reason="swapped"`, while SportPlus's
    # byte-identical names are `source="rule"`. That attribution is the claim.
    # The entry list alone is NOT: `certainty.py` dumps the whole configured
    # allowlist into `allowlist_entries` for any allowlist-sourced record, so
    # naming an entry proves it is configured, not that it was consulted. So
    # this asserts which pairing used the allowlist, and separately that both
    # of WWIN's spellings are on the list the evidence names.
    team_evidence = [e for e in group.evidence if e.rule == "team_identity"]
    allowlist_evidence = [e for e in team_evidence if e.source == "allowlist"]
    rule_evidence = [e for e in team_evidence if e.source == "rule"]
    assert len(allowlist_evidence) == 1, (
        f"exactly one pairing here needs the reviewed aliases, but "
        f"{len(allowlist_evidence)} of {len(team_evidence)} records credit the allowlist"
    )
    assert len(rule_evidence) == len(team_evidence) - 1
    for evidence in rule_evidence:
        assert not evidence.allowlist_entries, (
            "a pairing whose raw names agree needs no alias, so the gate must not "
            "credit the allowlist for it"
        )
    assert allowlist_evidence[0].reason == "swapped"
    assert allowlist_evidence[0].confidence == 1.0
    for entry in ("zeljeznicar|željezničar", "fk sarajevo|sarajevo"):
        assert entry in allowlist_evidence[0].allowlist_entries, (
            f"{entry!r} is one of WWIN's two spellings and must be on the reviewed "
            "list the gate credited"
        )


# --- seam 2: the gate's orientation -> find_surebets --------------------------


def test_gate_orientation_is_what_makes_the_three_books_priceable():
    """The surebet is priced in the group's frame, and in no other frame.

    Without the swap the same three books imply 0.80565 -- a 24.13% "surebet"
    that ``ArbitrageEngine`` rejects outright as a scraper error. With it they
    imply ``EXPECTED_MARGIN``, a 14.90% one. The unswapped group below is
    therefore not a convenience control: it is the same three real payloads, the
    same parser output and the same engine, differing only in whether the gate's
    orientation was honoured, and it must yield no 1X2 surebet at all.
    """
    group = _one_group(_linked())

    surebet = _match_result_surebet([group])
    assert surebet is not None, (
        "the three captured books form a real 1X2 arbitrage once the two reversed "
        "ones are relabelled, so the chain must produce it"
    )
    assert surebet.total_margin == pytest.approx(EXPECTED_MARGIN, abs=1e-4)
    assert surebet.profit_percent == pytest.approx(EXPECTED_PROFIT, abs=0.01)
    assert (surebet.home_team, surebet.away_team) == ("fk_sarajevo", "fk_zeljeznicar")

    # The leg each book wins must be the leg that book's own capture supplied,
    # in the group's frame: MBet's raw "1" is leg 1, and SportPlus's raw "1" is
    # leg 2 because SportPlus publishes the fixture reversed.
    legs = {stake.outcome_label: (stake.bookmaker, stake.odds) for stake in surebet.stakes}
    assert legs == EXPECTED_LEGS
    assert len({stake.bookmaker for stake in surebet.stakes}) == 3

    # Equal return whichever outcome lands, from the one investment.
    assert len({stake.potential_return for stake in surebet.stakes}) == 1
    assert sum(stake.stake for stake in surebet.stakes) == pytest.approx(100.0, abs=0.05)

    # --- the control: the identical three books, relabelling undone ---
    unswapped = MatchGroup(
        canonical_home=group.canonical_home,
        canonical_away=group.canonical_away,
        league=group.league,
        kickoff=group.kickoff,
        matches=_scraped(),
        status="verified",
    )
    assert _match_result_surebet([unswapped]) is None, (
        "read in the books' published frame the implied total is 0.80565, a 24.13% "
        "'surebet' the engine must reject as a data error; a surebet here would "
        "mean the swap never happened and the engine priced mislabelled odds"
    )
    best_unswapped = min(
        sum(1 / odds for odds in combo.values()) for combo in UNSWAPPED_COMBINATIONS
    )
    assert (1 / best_unswapped - 1) * 100 > MAX_SUREBET_PROFIT_PERCENT, (
        "the control is only meaningful while the unswapped books imply a profit "
        "the engine's own sanity check refuses"
    )


# --- seam 3: the age the scrape recorded decides whether the engine prices it --


def test_odds_aged_past_the_ttl_are_not_priced():
    """The scrape stage's clock is the arbitrage stage's input, and it is honoured.

    ``run_scan`` stamps ``fetched_at`` when each book is scraped, and
    ``find_surebets`` refuses any group holding a leg older than
    ``ODDS_TTL_SECONDS``. That is a seam between two stages this file otherwise
    only meets through values, and nothing in the suite pins it: an arbitrage
    computed from yesterday's prices is worse than no arbitrage at all.

    Same three books, same captured prices, same verified group. The only
    difference is how long ago each book said it fetched them, so the negative
    cannot be an artefact of the fixtures.
    """
    assert _match_result_surebet([_one_group(_linked())]) is not None, (
        "the control must price freshly fetched odds"
    )

    aged_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=ODDS_TTL_SECONDS + 60)
    aged = [
        m.model_copy(update={"fetched_at": aged_at}) for m in _linked()
    ]
    # The gate knows nothing about odds age, so the group still forms ...
    group = _one_group(aged)
    assert {m.bookmaker for m in group.matches} == set(BOOKS)
    # ... and the engine still refuses to price it.
    assert _match_result_surebet([group]) is None, (
        "odds older than ODDS_TTL_SECONDS must not be priced, however profitable "
        "they look"
    )


# --- seam 3: a broken claim stops at the gate ---------------------------------


def _break_league(matches: list[Match]) -> list[Match]:
    """Same fixture, same teams, a different -- and specifically named -- league."""
    return [m.model_copy(update={"league": "Prva Liga RS"}) if m.bookmaker == "mbet" else m
            for m in matches]


def _break_league_name(matches: list[Match]) -> list[Match]:
    """Same fixture, but the book no longer says which competition it is.

    "Superliga" is a bare competition name the matcher treats as generic, and
    books really do publish it that way. That is the case where the *gate's*
    league rule is the only thing standing: the scorer's league hard gate skips
    generic names, so it proposes the pairing and the gate is what has to
    refuse it. Without this case a matcher that consulted only its own scorer
    would look identical to a correctly gated one.
    """
    return [m.model_copy(update={"league": "Superliga"}) if m.bookmaker == "wwin" else m
            for m in matches]


def _break_kickoff(matches: list[Match]) -> list[Match]:
    """16 minutes late: inside the scorer's window, outside the gate's."""
    late = KICKOFF + timedelta(minutes=16)
    return [m.model_copy(update={"kickoff": late}) if m.bookmaker == "mbet" else m
            for m in matches]


def _break_link(matches: list[Match]) -> list[Match]:
    """A book that DECLARES a per-event route and has not proven it.

    This used to be "the state every scraped match is actually in", which was
    true of all three books until the gate was taught to read the declarations:
    all three declare ``supports_event_id: false``, so an unproven link among
    them settles nothing and costs no pairing. What still costs the pairing is a
    book that claims a route and does not prove it, so the breaker relabels one
    book onto a declared-route id. SportPlus, not MBet: MBet anchors the group, and
    with the anchor gone the scorer's own name-similarity tie-break leaves the
    other two too far apart to pair, which would make the case a claim about the
    scorer instead of about the gate. Only the declaration lookup and the
    bookmaker field read the relabelling -- every market, label and odd stays the
    captured one, and no surebet is ever priced from a group that holds this book.
    """
    return [
        m.model_copy(update={"bookmaker": "mdshop", "deep_link_verified": False})
        if m.bookmaker == "sportplus"
        else m
        for m in matches
    ]


# Each breaker spoils exactly one of the three claims and leaves the other two
# books, and every captured price, alone. ``group_books`` is the set the matcher
# is then expected to return; ``gate_reason`` is the deterministic reason the
# gate must give, or ``None`` when the scorer's own hard gates never propose the
# pairing and so the certainty gate is never asked.
#
# ``group_books`` is the exact set of bookmakers the matcher must then return,
# and is ``None`` for the one case where the exact answer would be an artefact
# rather than a claim: a link-blocked book is still a *candidate* for the other
# two, and which of them it pairs with depends on the matcher's strict
# `confidence > best_conf` tie-break and on input order. That case asserts the
# safety claim instead -- see the test body.
BREAKERS = [
    pytest.param(_break_league, "mbet", {"wwin", "sportplus"}, None, id="wrong_league"),
    pytest.param(_break_league_name, "wwin", {"mbet", "sportplus"}, "league_mismatch",
                 id="unnamed_league"),
    pytest.param(_break_kickoff, "mbet", {"wwin", "sportplus"}, "kickoff_delta",
                 id="kickoff_16min"),
    pytest.param(_break_link, "mdshop", None, "link_unverified", id="link_unverified"),
]


@pytest.mark.parametrize(
    ("break_it", "spoiled_book", "group_books", "gate_reason"), BREAKERS
)
def test_one_broken_claim_removes_the_pairing_and_the_surebet(
    break_it, spoiled_book: str, group_books: set[str] | None, gate_reason: str | None
):
    """One unsound part of one book's claim is enough to lose the surebet.

    Each case runs the same three captured books twice -- intact, then with one
    book spoiled -- so the closing ``is None`` is never vacuous: the intact run
    in the same test produces the 14.90% surebet and only the spoiled run does
    not. The claim is per-book and per-stage: a 1X2 market needs three distinct
    bookmakers, so losing one book's claim is enough whatever the remaining two
    can do between them.
    """
    intact = _match_result_surebet([_one_group(_linked())])
    assert intact is not None, "the control run must produce a surebet to lose"

    spoiled = break_it(_linked())
    groups = MatchMatcher().group_matches(spoiled)
    if group_books is None:
        # The safety claim, deliberately not an exact set: no returned group may
        # hold all three books, which is precisely why no 1X2 surebet can exist.
        for group in groups:
            assert len({m.bookmaker for m in group.matches}) < len(BOOKS), (
                f"{spoiled_book}: a book whose per-event link is unproven must keep "
                "its book out of every group that could be priced"
            )
    else:
        assert {m.bookmaker for g in groups for m in g.matches} == group_books, (
            "the spoiled book's claim must not reach a returned group"
        )
    assert all(g.status == "verified" for g in groups)
    assert _match_result_surebet(groups) is None, (
        "a 1X2 surebet out of a group that does not hold three proven books would "
        "mean the engine is pricing a claim the gate refused"
    )

    if gate_reason is None:
        # The scorer's own hard gates (a specific foreign league, a missing link
        # on a singleton) mean the certainty gate is never consulted for this
        # case. The claim above is still real -- the broken book reaches no
        # group and no surebet -- it is just a claim about the matcher.
        return

    # The remaining two cases are the ones the certainty gate alone decides, so
    # both halves are asserted: the matcher must still PROPOSE the pairing, and
    # the gate must refuse it. A scorer that rejected these outright would pass
    # the closing assertion above while never proving the gate does its job.
    broken = next(m for m in spoiled if m.bookmaker == spoiled_book)
    confidence, _ = MatchMatcher()._calculate_confidence(broken, groups[0])
    assert confidence > 0.0, (
        f"{spoiled_book}: this break is inside the scorer's candidate windows, so "
        "the matcher must propose the pairing and hand it to the gate"
    )
    result = MatchMatcher().gate.evaluate(broken, groups[0])
    assert gate_reason in result.reasons
    assert result.status != "verified"


# --- seam 4: the server serves what the chain produced ------------------------


# Every time the server considers consulting the AI, recorded so a test can
# assert it never had to.
_AI_CONSTRUCTIONS: list[Any] = []


class _NoAI:
    """A ``MatchAI`` stand-in with no HTTP client that records being built."""

    def __init__(self, **kwargs: Any) -> None:
        _AI_CONSTRUCTIONS.append(kwargs)

    @property
    def available(self) -> bool:
        return False

    def with_shared_client(self) -> _NoAI:
        raise AssertionError("with_shared_client must not be reached: available is False")

    async def suggest_pairs(self, pairs: list[Any]) -> list[Any]:
        raise AssertionError("no AI may be consulted in this file")

    async def aclose(self) -> None:
        return None


@pytest.fixture
def isolated_server_state(monkeypatch, tmp_path):
    """Keep the server's module-level scan state inside this file.

    ``run_scan`` writes the shared caches, the review queue and the durable
    deep-link store, all of which are process-wide. Every write is redirected or
    stubbed here and the previous state is restored on the way out, so this file
    can neither leak into nor be broken by another module.
    """
    snapshot = {
        "pending": dict(api.pending_candidates),
        "enabled": dict(api._bookmaker_enabled),
        "links": {mode: dict(entries) for mode, entries in api._deep_link_verifications.items()},
        "surebets": list(api.cached_surebets),
        "matches": list(api.cached_matches),
        "report": list(api.cached_match_groups_report),
        "per_bookie": dict(api.cached_per_bookie),
        "status": api.scan_status.model_dump(),
    }
    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "_append_history", lambda *a, **k: None)
    monkeypatch.setattr(api, "_save_deep_link_verifications", lambda *a, **k: None)
    monkeypatch.setattr(
        api, "DEEP_LINK_VERIFICATIONS_FILE", str(tmp_path / "deep_link_verifications.json")
    )
    monkeypatch.setattr(api, "MatchAI", _NoAI)
    for book in api.BOOKMAKERS:
        api._bookmaker_enabled[book] = book in BOOKS
    api.pending_candidates.clear()
    _AI_CONSTRUCTIONS.clear()
    yield
    api.pending_candidates.clear()
    api.pending_candidates.update(snapshot["pending"])
    api._bookmaker_enabled.clear()
    api._bookmaker_enabled.update(snapshot["enabled"])
    api._deep_link_verifications.clear()
    for mode, entries in snapshot["links"].items():
        api._deep_link_verifications[mode] = entries
    api.cached_surebets[:] = snapshot["surebets"]
    api.cached_matches[:] = snapshot["matches"]
    api.cached_match_groups_report[:] = snapshot["report"]
    api.cached_per_bookie.clear()
    api.cached_per_bookie.update(snapshot["per_bookie"])
    for key, value in snapshot["status"].items():
        setattr(api.scan_status, key, value)


@pytest.fixture
def stubbed_scrapers(monkeypatch):
    """Replace the three books' scrapers with their real parses, links unproven.

    The returned matches carry ``deep_link_verified=False`` because that is what
    every scraper ships. All three books declare ``supports_event_id: false``, so
    the gate settles their link from the declaration; the store still applies, and
    ``test_scan_applies_stored_link_proofs_and_serves_the_surebet`` still pins
    that it does. Every other book is switched off by ``isolated_server_state``,
    so ``run_scan`` cannot reach a real scraper and no browser is launched.
    """

    def make(matches: list[Match]) -> type:
        class _Scraper:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._matches = matches

            async def scrape(self, live: bool = False, scan_time: Any = None) -> list[Match]:
                return [m.model_copy(deep=True) for m in self._matches]

        return _Scraper

    scraped = {m.bookmaker: m for m in _scraped()}
    for book in BOOKS:
        monkeypatch.setitem(api.SCRAPERS, book, make([scraped[book]]))
    return scraped


def _route_book_match(bookmaker: str) -> Match:
    """One DECLARED-ROUTE book's real captured markets, in the certified shell.

    The TTL case needs a book whose link is load-bearing, and none of ``BOOKS``
    is one: all three declare ``supports_event_id: false``, so a stale proof costs
    them nothing. These two are the real NSoft capture of one real event — both
    captures are event 6828117 — driven through the same registry parser the
    scrapers use. The event shell is filled in here for the reason the three
    parsers above document: three books' captures are three different real
    fixtures and the gate can only judge a claim about one.

    No surebet is ever claimed from this pair: a 1X2 market needs three distinct
    books, and these odds are used for nothing except "does this group exist".
    """
    data = _capture(bookmaker)
    return Match(
        bookmaker=bookmaker,
        home_team=HOME,
        away_team=AWAY,
        league=LEAGUE,
        kickoff=KICKOFF,
        markets=parse_nsoft_bets(data["bets"], bookmaker=bookmaker, mode="prematch"),
        # The real declared route for this book and this captured event id, built
        # by the same builder the scrapers use.
        url=build_event_url(bookmaker, ROUTE_EVENT_ID, str(BOOKMAKERS[bookmaker]["base_url"])),
        event_id=ROUTE_EVENT_ID,
        deep_link_verified=False,
        fetched_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _route_books() -> list[Match]:
    return [_route_book_match(book) for book in ROUTE_BOOKS]


@pytest.fixture
def stubbed_route_scrapers(monkeypatch):
    """The same fakes, over the two books whose declared link is load-bearing.

    The books ``isolated_server_state`` switched off are switched back on, and the
    three certified ones are switched off, so this scan is exactly these two.
    """

    def make(matches: list[Match]) -> type:
        class _Scraper:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._matches = matches

            async def scrape(self, live: bool = False, scan_time: Any = None) -> list[Match]:
                return [m.model_copy(deep=True) for m in self._matches]

        return _Scraper

    for book in ROUTE_BOOKS:
        api._bookmaker_enabled[book] = True
    for book in BOOKS:
        api._bookmaker_enabled[book] = False
    route = {m.bookmaker: m for m in _route_books()}
    for book in ROUTE_BOOKS:
        monkeypatch.setitem(api.SCRAPERS, book, make([route[book]]))
    return route


def _store_links(matches: list[Match], age_seconds: int = 0) -> None:
    """Seed the durable deep-link store the way a verification run would."""
    checked_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=age_seconds)
    api._deep_link_verifications.clear()
    api._deep_link_verifications["prematch"] = {
        f"{match.bookmaker}|{match.event_id}": {
            "verified": True,
            "checked_at": checked_at.isoformat(),
            "url": match.url,
        }
        for match in matches
    }


def test_scan_applies_stored_link_proofs_and_serves_the_surebet(
    isolated_server_state, stubbed_scrapers
):
    """The whole chain, through the server, ending at the served payload.

    This is the only place ``run_scan`` itself runs, so it is the only test here
    that can catch a wiring regression between the stages the other tests drive
    by hand: a scan that stops applying stored link proofs, stops serialising
    the matches, stops grouping, or serves a cache the matcher never filled.

    The links are NOT set on the scraped matches -- they come from the store, at
    the moment the scan reads it, which is how a real deployment gets them for a
    book that has a per-event route. For these three books it is no longer what
    makes the group verify; see the next test, which drops the store entirely.
    """
    _store_links(_scraped())

    asyncio.run(api.run_scan("prematch"))

    assert api.scan_status.errors == [], "the scan reported an error"
    assert api.scan_status.total_matches == 3
    assert not _AI_CONSTRUCTIONS, (
        "three fully proven pairings need no review candidate, so no AI adapter "
        "should have been built at all"
    )
    assert api.pending_candidates == {}, (
        "a pairing the matcher already verified must never re-enter the review queue"
    )

    # Every scraped match carries its own event id and left the scan proven.
    served_matches = {m["bookmaker"]: m for m in api.cached_matches}
    assert set(served_matches) == set(BOOKS)
    for book, match in served_matches.items():
        assert match["event_id"] == stubbed_scrapers[book].event_id
        assert match["deep_link_verified"] is True, (
            f"{book}: the scan did not apply the stored link proof, so the store is "
            "not doing what a deployment relies on it for"
        )
        assert len(match["markets"]) == len(stubbed_scrapers[book].markets)

    # The match report is the diagnostic the UI reads, and it must describe the
    # group the matcher actually verified -- not a count, not a stale cache.
    assert len(api.cached_match_groups_report) == 1
    report = api.cached_match_groups_report[0]
    assert report["status"] == "verified"
    assert report["canonical_match"] == "fk_sarajevo vs fk_zeljeznicar"
    assert {b["bookmaker"] for b in report["bookmakers"]} == set(BOOKS)
    assert [b["num_markets"] for b in report["bookmakers"]] == [6, 6, 6]

    body = asyncio.run(api.get_results("prematch"))
    assert body["total_matches"] == 3
    assert body["match_groups"] == 1
    assert body["group_statuses"] == {"verified": 1}
    served = [s for s in body["surebets"] if s["market_type"] == "1x2"]
    assert len(served) == 1
    assert served[0]["profit_percent"] == pytest.approx(EXPECTED_PROFIT, abs=0.01)
    assert {
        stake["outcome_label"]: (stake["bookmaker"], stake["odds"])
        for stake in served[0]["stakes"]
    } == EXPECTED_LEGS

    # Every served leg carries a destination, and the label is the one the
    # recorded coverage supports. These three books have no ticket route, so a
    # served leg may be a match page or a competition fallback — never a ticket.
    for stake in served[0]["stakes"]:
        destination = stake.get("destination")
        assert destination, f"{stake['bookmaker']} leg has no destination"
        assert destination["kind"] in {"ticket_filled", "match_page", "search", "competition"}
        assert destination["label"]
        assert destination["kind"] != "ticket_filled", (
            f"{stake['bookmaker']} has no recorded ticket proof, so its label must not be a ticket"
        )
        if destination["kind"] == "match_page":
            assert destination["url"], "a match-page label needs a URL"
            assert destination["proof_checked_at"] == "2026-11-03"
        if destination["kind"] in {"search", "competition"}:
            assert destination["search_text"], "a fallback needs the book's own spelling"
            assert "ticket" not in destination["label"].lower()


def test_scan_verifies_a_declared_no_link_book_with_no_stored_proof_at_all(
    isolated_server_state, stubbed_scrapers
):
    """The declared absence, end to end, with the store empty.

    ``BOOKS`` are three books that all declare ``supports_event_id: false``. Their
    scanned matches carry a feed id and a site URL and no link proof, which is
    every scraped match in production. Before the gate read
    ``config/bookmaker_deeplinks.json`` that state was ``link_unverified`` for
    every one of them, so no group was ever ``verified`` and no surebet was ever
    produced -- and the reason was the code, not the books' routing.

    So: the store holds nothing at all, and the scan must still verify the group
    and price the surebet. If this ever fails, the six declared-false books have
    gone back to being structurally unpriceable.
    """
    assert api._deep_link_verifications == {} or all(
        not entries for entries in api._deep_link_verifications.values()
    ), "the store must start empty for this claim to be about the declaration"

    asyncio.run(api.run_scan("prematch"))

    assert api.scan_status.errors == [], "the scan reported an error"
    assert all(m["deep_link_verified"] is False for m in api.cached_matches), (
        "no proof was stored, so nothing may claim one"
    )
    assert len(api.cached_match_groups_report) == 1
    report = api.cached_match_groups_report[0]
    assert report["status"] == "verified", (
        "three books that each declare `supports_event_id: false` leave no link to "
        "prove; the group is verified on identity alone"
    )
    assert {b["bookmaker"] for b in report["bookmakers"]} == set(BOOKS)

    body = asyncio.run(api.get_results("prematch"))
    assert body["group_statuses"] == {"verified": 1}
    served = [s for s in body["surebets"] if s["market_type"] == "1x2"]
    assert len(served) == 1
    assert served[0]["profit_percent"] == pytest.approx(EXPECTED_PROFIT, abs=0.01)


def test_a_verified_group_records_the_declared_absence_as_evidence(
    isolated_server_state, stubbed_scrapers
):
    """`verified` means every part of the claim is proven, links included.

    So the statement that a link is deliberately absent has to be *in* the
    evidence trail rather than in a comment: a `link_evidence` row per gate
    evaluation, reading `no_event_link` with full confidence. A group that
    verified with no such row would be a group whose link half was never
    accounted for, and the only remaining trace of the decision would be the
    absence of a complaint.
    """
    assert not _AI_CONSTRUCTIONS  # the AI never gets a say in a decision

    groups = MatchMatcher().group_matches(_scraped())
    assert len(groups) == 1
    group = groups[0]
    assert group.status == "verified"

    links = [e for e in group.evidence if e.rule == "link_evidence"]
    assert links, "a verified group must record what it decided about its links"
    assert {e.reason for e in links} == {"no_event_link"}, (
        f"unexpected link evidence: {sorted({e.reason for e in links})}"
    )
    assert {e.source for e in links} == {"rule"}
    assert {e.confidence for e in links} == {1.0}, (
        "a declared absence is as certain as a proven link; 0.0 would read as an "
        "unproven claim in the trail"
    )


def test_scan_refuses_a_link_proof_that_aged_out(
    isolated_server_state, stubbed_route_scrapers, monkeypatch
):
    """A link proof past its TTL stops unblocking the gate, for a book that has a route.

    A bookmaker can retire an event at any time, so a stored proof must not be
    allowed to unblock ``verified`` forever. Without this the positive claims
    above would be claims about a flag nothing can revoke.

    The books are ``ROUTE_BOOKS``, not ``BOOKS``, and that is the point of the
    rewrite. All three certified books declare ``supports_event_id: false``, so
    their link is settled by the declaration and a stale proof costs them
    nothing: this case is no longer demonstrable on them at all, and pretending
    otherwise would assert a mechanism that no longer exists. These two books
    declare a per-event route, so the proof is the only thing that can verify
    them.

    The pair is two books, so a 1X2 surebet is impossible either way and the
    assertions are about the group and the review queue — the two things a scan
    actually decides here. The intact run is repeated first, same books and same
    store with one TTL of age difference, so ``match_groups == 0`` cannot be a
    property of the fixtures. The store-level TTL is pinned independently by
    ``tests/test_verify_links.py::test_an_expired_verification_is_ignored_and_dropped``.
    """
    route = _route_books()
    # This case is about link-proof expiry, not price sources: ROUTE_BOOKS are
    # both NSoft, so without this the pair is correctly refused as one source.
    monkeypatch.setattr("engine.matcher.price_source", lambda book: book)
    _store_links(route)
    asyncio.run(api.run_scan("prematch"))
    assert [r["status"] for r in api.cached_match_groups_report] == ["verified"], (
        "the control scan must verify the pair, or the aged-out run proves nothing"
    )
    assert len(api.cached_match_groups_report[0]["bookmakers"]) == 2

    _store_links(route, age_seconds=api.DEEP_LINK_VERIFICATION_TTL_SECONDS + 60)
    asyncio.run(api.run_scan("prematch"))

    assert api.scan_status.surebets_found == 0
    assert api.cached_surebets == []
    assert api.cached_match_groups_report == [], (
        "a group whose only members have unproven links must not be reported as a "
        "match group at all"
    )
    assert len(api.cached_matches) == 2, "the matches are still cached, just not grouped"
    assert all(m["deep_link_verified"] is False for m in api.cached_matches)

    body = asyncio.run(api.get_results("prematch"))
    assert body["surebets"] == []
    assert body["match_groups"] == 0
    assert body["group_statuses"] == {}

    # What the server does instead of dropping the pairing silently: queue it for
    # review, blocked on the link. (That an approval cannot clear the link is
    # `approve_candidate`'s own contract, asserted in
    # tests/test_scan_candidates.py -- not something a scan-level test can see.)
    assert api.pending_candidates, "an unproven pair must be queued for review"
    for candidate in api.pending_candidates.values():
        assert candidate.status == "pending"
        assert candidate.link_blocked is True
        assert "link_unverified" in candidate.rule_rejections
        # The AI ranks a queue entry; it can never decide one.
        assert candidate.ai_same_event is None
        assert candidate.ai_confidence == 0.0
