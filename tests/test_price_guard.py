"""A surebet with an outlier leg is dropped, not shown."""

from __future__ import annotations

from types import SimpleNamespace

from engine.market_consensus import find_outliers
from engine.price_guard import filter_price_outliers
from models.schemas import Market, MarketType, Match, OddsValue


def _match(book: str, odds: tuple[float, float, float]) -> Match:
    return Match(
        bookmaker=book,
        home_team="Alpha",
        away_team="Beta",
        league="Test League",
        event_id=book,
        deep_link_verified=True,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label="1", value=odds[0]),
                    OddsValue(label="X", value=odds[1]),
                    OddsValue(label="2", value=odds[2]),
                ],
            )
        ],
    )


def _surebet(book: str) -> SimpleNamespace:
    return SimpleNamespace(
        home_team="alpha",
        away_team="beta",
        market_type=MarketType.MATCH_RESULT,
        stakes=[SimpleNamespace(bookmaker=book, outcome_label="1")],
    )


def test_an_outlier_leg_drops_the_surebet():
    group = SimpleNamespace(
        canonical_home="alpha",
        canonical_away="beta",
        league="test league",
        matches=[
            _match("mbet", (2.0, 3.4, 3.6)),
            _match("wwin", (2.05, 3.3, 3.5)),
            _match("sportplus", (1.2, 6.0, 12.0)),
        ],
    )
    outliers, _ = find_outliers([group], 0.10)
    assert outliers
    kept, dropped = filter_price_outliers([_surebet("sportplus")], [group])
    assert kept == []
    assert len(dropped) == 1
    assert dropped[0]["outlier"]["bookmaker"] == "sportplus"


def test_a_consistent_leg_is_kept():
    group = SimpleNamespace(
        canonical_home="alpha",
        canonical_away="beta",
        league="test league",
        matches=[
            _match("mbet", (2.0, 3.4, 3.6)),
            _match("wwin", (2.05, 3.3, 3.5)),
            _match("sportplus", (1.95, 3.5, 3.7)),
        ],
    )
    kept, dropped = filter_price_outliers([_surebet("mbet")], [group])
    assert len(kept) == 1
    assert dropped == []
