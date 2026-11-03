"""The raw-offer seam lets a new book be classified without a registry edit."""

from __future__ import annotations

from engine.market_discovery import classify
from models.schemas import MarketType, OddsValue, RawOffer


def test_a_raw_offer_carries_the_book_identifiers_and_labels():
    offer = RawOffer(
        bookmaker="newbook",
        mode="prematch",
        event_key="e1",
        market_key="m1",
        source_id="m1",
        labels=["Over 2.5", "Under 2.5"],
        line=2.5,
        odds=[OddsValue(label="Over 2.5", value=1.95), OddsValue(label="Under 2.5", value=1.9)],
    )
    assert offer.bookmaker == "newbook"
    assert offer.labels == ["Over 2.5", "Under 2.5"]
    assert offer.line == 2.5


def test_a_raw_offer_classifies_without_a_market_type_field():
    result = classify(["1", "X", "2"], market_key="match-result")
    assert result is not None
    assert result.market_type is MarketType.MATCH_RESULT


def test_a_raw_offer_with_an_unknown_label_set_is_a_gap():
    assert classify(["Home", "Away"], market_key="unknown") is None
