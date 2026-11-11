"""A new book's labels classify without a hand-written registry row."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from engine.market_discovery import classify
from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue, RawOffer

REPO_ROOT = Path(__file__).parents[1]
CONFIG_FILES = (
    REPO_ROOT / "config" / "team_mappings.json",
    REPO_ROOT / "config" / "league_mappings.json",
    REPO_ROOT / "config" / "bookmaker_markets.json",
    REPO_ROOT / "config" / "team_alias_allowlist.json",
)
K = datetime(2026, 11, 7, 18, 0)


def _ref(market_type: MarketType, labels: tuple[str, str, str] | tuple[str, str]) -> Market:
    values = (2.0, 3.4, 3.6) if len(labels) == 3 else (1.95, 1.90)
    return Market(
        market_type=market_type,
        odds=[OddsValue(label=label, value=value) for label, value in zip(labels, values, strict=True)],
    )


def _references() -> list[Market]:
    return [
        _ref(MarketType.MATCH_RESULT, ("1", "X", "2")),
        _ref(MarketType.OVER_UNDER_2_5, ("Over 2.5", "Under 2.5")),
        _ref(MarketType.BTTS, ("GG", "NG")),
    ]


def _offers() -> list[RawOffer]:
    return [
        RawOffer(
            bookmaker="syntheticbook",
            event_key="e1",
            market_key="unknown-match-result",
            source_id="9001",
            labels=["1", "X", "2"],
            odds=[OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.4), OddsValue(label="2", value=3.6)],
        ),
        RawOffer(
            bookmaker="syntheticbook",
            event_key="e1",
            market_key="unknown-total",
            source_id="9002",
            labels=["Over 2.5", "Under 2.5"],
            line=2.5,
            odds=[OddsValue(label="Over 2.5", value=1.95), OddsValue(label="Under 2.5", value=1.9)],
        ),
        RawOffer(
            bookmaker="syntheticbook",
            event_key="e1",
            market_key="unknown-btts",
            source_id="9003",
            labels=["GG", "NG"],
            odds=[OddsValue(label="GG", value=1.8), OddsValue(label="NG", value=1.95)],
        ),
        RawOffer(
            bookmaker="syntheticbook",
            event_key="e1",
            market_key="unknown-two-way",
            source_id="9004",
            labels=["Home", "Away"],
            odds=[OddsValue(label="Home", value=1.5), OddsValue(label="Away", value=2.5)],
        ),
    ]


def _match(book: str, markets: list[Market]) -> Match:
    return Match(
        bookmaker=book,
        home_team="Synthetic FC",
        away_team="Test United",
        league="Synthetic League",
        kickoff=K,
        event_id=book,
        deep_link_verified=True,
        markets=markets,
    )


def _classify(offer: RawOffer):
    return classify(
        offer.labels,
        line=offer.line,
        period=offer.period,
        market_key=offer.market_key,
    )


def test_a_synthetic_book_resolves_and_groups_with_no_config_edits():
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in CONFIG_FILES}
    classified = {offer.market_key: _classify(offer) for offer in _offers()}
    assert classified["unknown-match-result"] is not None
    assert classified["unknown-total"] is not None
    assert classified["unknown-btts"] is not None
    assert classified["unknown-two-way"] is None

    synthetic_markets = [
        Market(
            market_type=classification.market_type,
            odds=list(offer.odds),
            source_id=offer.source_id,
        )
        for offer in _offers()
        if (classification := _classify(offer)) is not None
    ]
    matches = [
        _match("syntheticbook", synthetic_markets),
        _match("mbet", _references()),
        _match("wwin", _references()),
        _match("sportplus", _references()),
    ]
    groups = MatchMatcher().group_matches(matches)
    assert len(groups) == 1
    assert "syntheticbook" in {m.bookmaker for m in groups[0].matches}

    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in CONFIG_FILES}
    assert before == after, "onboarding must not edit a hand-written mapping file"


def test_an_ambiguous_offer_is_a_gap_not_a_guess():
    offer = RawOffer(bookmaker="syntheticbook", labels=["Home", "Away"])
    assert _classify(offer) is None
