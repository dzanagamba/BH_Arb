"""The three shared enums are `StrEnum` (M4-5 U3).

Ruff 0.17's UP042 prefers `StrEnum` over `str, Enum`. The upgrade is text-only
for the API: Pydantic and JSON already wrote the value, and the metric labels,
cache keys and canary reports read `.value` or plain strings. These assertions
pin the value strings so a later enum change cannot quietly alter a payload.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from models.schemas import MarketType, Sport
from scrapers.errors import ScrapeKind


class _Payload(BaseModel):
    market: MarketType
    sport: Sport
    kind: ScrapeKind


def test_enum_values_are_the_persisted_strings():
    assert MarketType.MATCH_RESULT.value == "1x2"
    assert MarketType.OVER_UNDER_2_5.value == "over_under_2_5"
    assert Sport.FOOTBALL.value == "football"
    assert Sport.ICE_HOCKEY.value == "ice_hockey"
    assert ScrapeKind.OK.value == "ok"
    assert ScrapeKind.SCHEMA_DRIFT.value == "schema_drift"


def test_strenum_direct_formatting_matches_the_value():
    assert str(MarketType.OVER_UNDER_2_5) == "over_under_2_5"
    assert f"{Sport.ICE_HOCKEY}" == "ice_hockey"
    assert f"{ScrapeKind.RATE_LIMITED}" == "rate_limited"


def test_json_and_pydantic_keep_the_value_strings():
    payload = _Payload(
        market=MarketType.MATCH_RESULT,
        sport=Sport.TENNIS,
        kind=ScrapeKind.OK,
    )
    expected = {"market": "1x2", "sport": "tennis", "kind": "ok"}
    assert payload.model_dump() == expected
    assert payload.model_dump(mode="json") == expected
    assert json.loads(payload.model_dump_json()) == expected
    assert json.dumps({MarketType.MATCH_RESULT: 1}) == '{"1x2": 1}'
