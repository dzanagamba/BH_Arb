"""The cross-book price check flags a swapped label and stays quiet on honest odds."""

from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue
from scripts.price_check import devigged, find_outliers


def _match(book: str, one: float, draw: float, two: float) -> Match:
    return Match(
        bookmaker=book,
        home_team="A",
        away_team="B",
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label="1", value=one),
                    OddsValue(label="X", value=draw),
                    OddsValue(label="2", value=two),
                ],
            )
        ],
    )


def _group(*matches: Match) -> MatchGroup:
    return MatchGroup(
        canonical_home="A", canonical_away="B", matches=list(matches), status="verified"
    )


def test_devigged_sums_to_one_and_double_chance_to_two():
    p = devigged(MarketType.MATCH_RESULT, {"1": 2.0, "X": 3.5, "2": 4.0})
    assert p is not None and abs(sum(p.values()) - 1) < 1e-9
    dc = devigged(MarketType.DOUBLE_CHANCE, {"1X": 1.3, "12": 1.4, "X2": 2.2})
    assert dc is not None and abs(sum(dc.values()) - 2) < 1e-9


def test_incomplete_or_dead_set_is_not_compared():
    assert devigged(MarketType.MATCH_RESULT, {"1": 2.0, "X": 3.5}) is None
    assert devigged(MarketType.BTTS, {"GG": 1.0, "NG": 1.9}) is None


def test_agreeing_books_have_no_outlier():
    group = _group(
        _match("a", 2.0, 3.4, 3.9), _match("b", 2.05, 3.3, 3.8), _match("c", 1.95, 3.5, 4.0)
    )
    assert find_outliers([group], 0.10)[0] == []


def test_swapped_home_away_is_flagged():
    group = _group(
        _match("a", 1.5, 4.0, 6.0),
        _match("b", 1.48, 4.1, 6.2),
        _match("c", 1.52, 3.9, 5.8),
        _match("d", 6.0, 4.0, 1.5),
    )
    outliers, compared = find_outliers([group], 0.10)
    assert compared == 1
    assert {o["bookmaker"] for o in outliers} == {"d"}


def test_two_books_are_not_enough_to_judge():
    group = _group(_match("a", 1.5, 4.0, 6.0), _match("b", 6.0, 4.0, 1.5))
    assert find_outliers([group], 0.10) == ([], 0)


def test_books_on_one_feed_vote_once():
    # mdshop and admiralbet quote identical NSoft prices; as two votes they would
    # outweigh two honest independent books.
    group = _group(
        _match("mdshop", 6.0, 4.0, 1.5),
        _match("admiralbet", 6.0, 4.0, 1.5),
        _match("a", 1.5, 4.0, 6.0),
        _match("b", 1.48, 4.1, 6.2),
        _match("c", 1.52, 3.9, 5.8),
    )
    outliers, _ = find_outliers([group], 0.10)
    assert {o["bookmaker"] for o in outliers} == {"mdshop+admiralbet"}
