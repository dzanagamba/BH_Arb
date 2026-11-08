"""SR4-7: property-based mutation tests for the market parsers.

WHAT THESE TESTS PROVE
----------------------
The fixture, contract and snapshot suites prove the parsers against *known*
payloads. This suite mutates the captured ``bets`` payload (drops keys, nulls
values, swaps types, shuffles/duplicates/truncates arrays) and asserts the
invariants that must hold however the feed is malformed:

* the parser returns a list and never raises an unhandled exception;
* every emitted price is present, finite and positive (no missing or ``0``
  price, no ``NaN``);
* one book never contributes the same outcome label twice for the same
  ``(market_type, settlement, period)`` — that would become two legs for one
  book in a group;
* a mutation never introduces a sport/settlement combination the clean capture
  did not emit; malformed input may drop markets, never cross sport or
  settlement.

The mutations are seeded by Hypothesis, so a failure reproduces from the
printed example. The payload container (``bets`` list/dict) is kept intact,
and a mutation the book's wire schema (SR4-3) rejects is skipped: the real
pipeline validates the raw payload before any parser runs, so those examples
would test the schema's absence, not the parser.

KNOWN DEFECT FIXED (SR4-7a)
--------------------------
The first run found one production-reachable defect: a duplicated NSoft
``betOutcome`` was emitted twice in one market. `SR4-7a` fixed
`parse_nsoft_bets` to keep the first offered price per normalized label, and
``test_nsoft_duplicate_outcome_yields_one_leg`` pins it. The duplicate-label
check below is now enforced for every parser, so a future regression fails
here as well.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not prove the parser *should* emit a market for a given mutation; the
property is "safe, not richer". A bug found here is fixed in its own task row,
never folded into this one.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_market_fixtures import FIXTURES, _run_parser

from scrapers.errors import ScrapeError
from scrapers.wire_schemas import (
    validate_betole_offer_map,
    validate_bets,
    validate_maxbet_odds,
    validate_mbet_odds,
    validate_mozzart_odds,
    validate_premier_odds,
    validate_sportplus_markets,
    validate_wwin_bets,
)

CASES = [
    path
    for path in FIXTURES
    if json.loads(path.read_text(encoding="utf-8")).get("expected_markets")
]

_SETTINGS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.filter_too_much,
    ],
)


def _capture(fixture: Path) -> dict[str, Any]:
    return json.loads(fixture.read_text(encoding="utf-8"))


def _identity(market) -> tuple[str, str, str]:
    return (
        market.market_type.value,
        market.settlement,
        market.period,
    )


def _baseline(fixture: Path) -> set[tuple[str, str, str]]:
    return {_identity(market) for market in _run_parser(_capture(fixture))}


def _leaf(draw: Any) -> Any:
    return draw(st.sampled_from([None, "", 0, True]))


def _mutate(value: Any, draw: Any, depth: int = 0) -> Any:
    """Mutate one value in place and return it (bounded recursion)."""
    if depth >= 4:
        return _leaf(draw)
    if isinstance(value, dict) and value:
        action = draw(st.sampled_from(["child", "drop", "null", "add"]))
        keys = list(value)
        if action == "child":
            key = draw(st.sampled_from(keys))
            value[key] = _mutate(value[key], draw, depth + 1)
        elif action == "drop":
            value.pop(draw(st.sampled_from(keys)))
        elif action == "null":
            value[draw(st.sampled_from(keys))] = None
        else:
            value[f"mutation_{depth}"] = _leaf(draw)
        return value
    if isinstance(value, list) and value:
        action = draw(
            st.sampled_from(["child", "shuffle", "duplicate", "drop", "truncate"])
        )
        if action == "child":
            index = draw(st.integers(0, len(value) - 1))
            value[index] = _mutate(value[index], draw, depth + 1)
        elif action == "shuffle":
            index = draw(st.integers(0, len(value) - 1))
            value[:] = value[index:] + value[:index]
        elif action == "duplicate":
            index = draw(st.integers(0, len(value) - 1))
            value.insert(index, deepcopy(value[index]))
        elif action == "drop":
            value.pop(draw(st.integers(0, len(value) - 1)))
        else:
            del value[draw(st.integers(1, len(value))) :]
        return value
    return _leaf(draw)


def _mutated_bets(bets: Any, draw: Any) -> Any:
    """1-3 mutations inside the captured payload, container kept intact."""
    result = deepcopy(bets)
    for _ in range(draw(st.integers(1, 3))):
        if isinstance(result, list) and result:
            index = draw(st.integers(0, len(result) - 1))
            result[index] = _mutate(result[index], draw)
        elif isinstance(result, dict) and result:
            key = draw(st.sampled_from(list(result)))
            result[key] = _mutate(result[key], draw)
        else:
            break
    return result


_SCHEMA_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "mdshop": lambda bets: validate_bets(bets, book="mdshop"),
    "admiralbet": lambda bets: validate_bets(bets, book="admiralbet"),
    "mozzartbet": validate_mozzart_odds,
    "betole": validate_betole_offer_map,
    "mbet": validate_mbet_odds,
    "sportplus": validate_sportplus_markets,
    "premier_kladionica": validate_premier_odds,
    "wwin": validate_wwin_bets,
    "maxbet": validate_maxbet_odds,
}


def _schema_accepts(book: str, bets: Any) -> bool:
    """Whether the book's wire schema (SR4-3) would let this payload through.

    The real pipeline validates the raw payload before any parser runs, so a
    mutation the schema rejects cannot reach a parser in production. Filtering
    those examples keeps the property about the parser, not about a second
    schema implementation.
    """
    validator = _SCHEMA_VALIDATORS.get(book)
    if validator is None:
        return True
    try:
        validator(bets)
    except ScrapeError:
        return False
    return True


def _assert_safe(markets: list, baseline: set[tuple[str, str, str]]) -> None:
    labels: dict[tuple[str, str, str], set[str]] = {}
    for market in markets:
        identity = _identity(market)
        assert identity in baseline, (
            "a mutated payload emitted a sport/settlement the clean capture "
            f"did not: {identity}"
        )
        assert market.odds, f"market {identity} was emitted without a price"
        seen = labels.setdefault(identity, set())
        for odd in market.odds:
            assert isinstance(odd.value, float)
            assert math.isfinite(odd.value)
            assert odd.value > 0, f"{identity}/{odd.label} has a non-positive price"
            assert odd.label not in seen, (
                f"{identity} emitted label {odd.label!r} twice for the same book"
            )
            seen.add(odd.label)


@pytest.mark.parametrize("fixture", CASES, ids=[path.stem for path in CASES])
@_SETTINGS
@given(data=st.data())
def test_a_mutated_capture_never_breaks_a_parser(fixture: Path, data: st.DataObject):
    original = _capture(fixture)
    baseline = _baseline(fixture)

    mutated = deepcopy(original)
    mutated["bets"] = _mutated_bets(original["bets"], data.draw)
    if not _schema_accepts(original["bookmaker"], mutated["bets"]):
        return

    markets = _run_parser(mutated)

    assert isinstance(markets, list)
    _assert_safe(markets, baseline)


@pytest.mark.parametrize("fixture", CASES, ids=[path.stem for path in CASES])
def test_the_clean_capture_still_satisfies_the_same_invariants(fixture: Path):
    """The property is not vacuous: the unmutated capture passes it too."""
    markets = _run_parser(_capture(fixture))

    _assert_safe(markets, _baseline(fixture))


def test_the_schema_filter_keeps_an_accepted_mutation():
    """A shape the real pipeline accepts still reaches the parser."""
    capture = _capture(next(path for path in CASES if path.stem == "mdshop_prematch"))
    mutated = deepcopy(capture["bets"])
    mutated[0]["brandNewFeedField"] = 1

    assert _schema_accepts("mdshop", mutated)


def test_the_schema_filter_rejects_a_mutation_the_pipeline_drops():
    """A short Premier row cannot reach the parser in production, so it is skipped."""
    capture = _capture(
        next(path for path in CASES if path.stem == "premier_kladionica_prematch")
    )
    mutated = deepcopy(capture["bets"])
    mutated[0] = mutated[0][:3]

    assert not _schema_accepts("premier_kladionica", mutated)


# ─── SR4-7a regression pin (fixed in SR4-7a) ───────────────────────────────


def test_nsoft_duplicate_outcome_yields_one_leg():
    capture = _capture(next(path for path in CASES if path.stem == "mdshop_prematch"))
    bet = deepcopy(capture["bets"][0])
    duplicate = deepcopy(bet["betOutcomes"][0])
    duplicate["odd"] = 9.99  # a later duplicate must not replace the first price
    bet["betOutcomes"].append(duplicate)

    markets = _run_parser(
        {
            "bookmaker": "mdshop",
            "mode": "prematch",
            "bets": [bet],
        }
    )

    assert len(markets) == 1
    labels = [odd.label for odd in markets[0].odds]
    assert labels.count("1") == 1
    assert next(odd.value for odd in markets[0].odds if odd.label == "1") == 2.81
