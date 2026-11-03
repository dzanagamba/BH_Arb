"""A market mapping is accepted only when the other books agree on its price."""

from __future__ import annotations

from engine.market_consensus import compare
from models.schemas import Market, MarketType, OddsValue


def _m(one: float, x: float, two: float) -> Market:
    return Market(
        market_type=MarketType.MATCH_RESULT,
        odds=[OddsValue(label="1", value=one), OddsValue(label="X", value=x), OddsValue(label="2", value=two)],
    )


def test_a_correct_mapping_passes():
    result = compare(_m(2.0, 3.4, 3.6), [_m(2.05, 3.3, 3.5), _m(1.95, 3.5, 3.7)])
    assert result.status == "accepted"
    assert result.compared_books == 2


def test_a_shifted_line_is_an_outlier():
    result = compare(_m(1.2, 6.0, 12.0), [_m(2.0, 3.4, 3.6), _m(2.05, 3.3, 3.5)])
    assert result.status == "outlier"
    assert result.gaps


def test_one_other_book_is_not_enough():
    result = compare(_m(2.0, 3.4, 3.6), [_m(2.0, 3.4, 3.6)])
    assert result.status == "insufficient_evidence"


def test_an_incomplete_candidate_is_not_compared():
    market = Market(market_type=MarketType.MATCH_RESULT, odds=[OddsValue(label="1", value=2.0)])
    assert compare(market, [_m(2.0, 3.4, 3.6), _m(2.0, 3.4, 3.6)]).status == "insufficient_evidence"


def test_a_two_way_market_has_no_reference_set():
    market = Market(market_type=MarketType.MATCH_RESULT, odds=[OddsValue(label="1", value=2.0), OddsValue(label="2", value=3.0)])
    assert compare(market, [_m(2.0, 3.4, 3.6), _m(2.0, 3.4, 3.6)]).status == "insufficient_evidence"
