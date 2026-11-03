"""Raw labels become market types, or they become a counted gap."""

from __future__ import annotations

from engine.market_discovery import classify
from models.schemas import Market, MarketType, OddsValue


def test_1x2():
    result = classify(["1", "X", "2"])
    assert result is not None
    assert result.market_type is MarketType.MATCH_RESULT


def test_double_chance():
    result = classify(["1X", "12", "X2"])
    assert result is not None
    assert result.market_type is MarketType.DOUBLE_CHANCE


def test_btts_in_three_spellings():
    for labels in (["GG", "NG"], ["Yes", "No"], ["Da", "Ne"]):
        result = classify(labels)
        assert result is not None
        assert result.market_type is MarketType.BTTS


def test_over_under_line_from_labels():
    result = classify(["Over 2.5", "Under 2.5"])
    assert result is not None
    assert result.market_type is MarketType.OVER_UNDER_2_5
    assert result.line == 2.5


def test_over_under_bosnian_labels_use_the_line_argument():
    result = classify(["Više", "Manje"], line=3.5)
    assert result is not None
    assert result.market_type is MarketType.OVER_UNDER_3_5


def test_first_half_changes_the_type_not_the_line():
    result = classify(["1", "X", "2"], market_key="1. poluvreme")
    assert result is not None
    assert result.market_type is MarketType.FIRST_HALF_1X2
    assert result.period == "first_half"

    result = classify(["Over 2.5", "Under 2.5"], period="first_half")
    assert result is not None
    assert result.market_type is MarketType.FIRST_HALF_OU


def test_asian_handicap_needs_a_line():
    result = classify(["1 (-1.5)", "2 (+1.5)"], market_key="handicap")
    assert result is not None
    assert result.market_type is MarketType.ASIAN_HANDICAP
    assert result.line == -1.5


def test_a_two_way_market_is_not_1x2():
    assert classify(["1", "2"]) is None


def test_an_unknown_label_set_is_a_gap():
    assert classify(["Ide dalje", "Ne ide dalje"]) is None
    assert classify([]) is None


def test_classify_market_uses_the_parsed_labels():
    market = Market(
        market_type=MarketType.MATCH_RESULT,
        odds=[OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.0), OddsValue(label="2", value=4.0)],
    )
    result = classify([o.label for o in market.odds])
    assert result is not None and result.market_type is MarketType.MATCH_RESULT
