"""N3-1: property-based checks for the pricing arithmetic.

These are a second net under the fixed fixtures, not a new trust rule. The
generators only produce inputs the engine already accepts (decimal odds above
1.0, a positive investment), then assert the identities the dashboard, the
recalculate endpoint and the slip all rely on:

* ``sum(1/odds)`` is the served margin and reproduces the profit percent;
* the proportional stake split has one leg per bookmaker and per price source;
* the served rounded stakes realise the reported worst case;
* rounding cannot move the result by more than one rounding step per leg, and
  a deliberately downward (funded) rounding never increases profit.

The signed ``rounding_loss`` may be negative when rounding happens to help
(``engine/pricing_invariant.py`` documents this); the property pins that sign
change to a bounded gain rather than pretending it cannot happen.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from config.settings import price_source
from engine.arbitrage import ArbitrageEngine
from engine.pricing_invariant import (
    exact_profit_percent,
    implied_sum,
    margin_from_served_stakes,
    round_stake,
    rounding_summary,
)
from models.schemas import Market, MarketType, Match, MatchGroup, OddsValue


def _group(rows: dict[str, tuple[float, float]], *, kickoff=None) -> MatchGroup:
    """A verified BTTS group; one book prices GG/NG per entry."""
    kickoff = kickoff or datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=2)
    matches = [
        Match(
            bookmaker=bookmaker,
            home_team="Sarajevo",
            away_team="Zeljeznicar",
            league="Premier Liga",
            kickoff=kickoff,
            markets=[
                Market(
                    market_type=MarketType.BTTS,
                    odds=[
                        OddsValue(label="GG", value=gg),
                        OddsValue(label="NG", value=ng),
                    ],
                )
            ],
        )
        for bookmaker, (gg, ng) in rows.items()
    ]
    return MatchGroup(
        status="verified",
        canonical_home="Sarajevo",
        canonical_away="Zeljeznicar",
        league="premier_liga",
        kickoff=kickoff,
        matches=matches,
    )


_ODDS = st.floats(
    min_value=1.01,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
)


@given(odds=st.lists(_ODDS, min_size=2, max_size=6))
@settings(max_examples=200, deadline=None)
def test_implied_sum_and_exact_profit_are_one_formula(odds: list[float]) -> None:
    margin = implied_sum(odds)

    assert math.isfinite(margin)
    assert margin > 0
    assert exact_profit_percent(odds) == pytest.approx(
        (1.0 / margin - 1.0) * 100.0, rel=1e-12, abs=1e-12
    )
    assert margin_from_served_stakes([{"odds": odd} for odd in odds]) == pytest.approx(
        margin, rel=1e-12, abs=1e-12
    )


@given(
    high=st.floats(
        min_value=2.02, max_value=2.15, allow_nan=False, allow_infinity=False
    ),
    low=st.floats(
        min_value=1.50, max_value=1.90, allow_nan=False, allow_infinity=False
    ),
    investment=st.floats(
        min_value=10.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_stake_split_has_equal_returns_and_reproduces_the_margin(
    high: float, low: float, investment: float
) -> None:
    # A plus B quote the same complementary pair on different feeds, so a
    # surebet always exists; C is a third independent source.
    group = _group(
        {
            "mbet": (high, low),
            "wwin": (low, high),
            "mozzartbet": (1.80, 1.95),
        }
    )
    surebets = ArbitrageEngine().find_surebets(
        [group], min_profit=0.1, investment=investment
    )

    assert len(surebets) == 1
    surebet = surebets[0]
    assert {stake.outcome_label for stake in surebet.stakes} == {"GG", "NG"}
    assert len({stake.bookmaker for stake in surebet.stakes}) == len(surebet.stakes)
    assert len({price_source(stake.bookmaker) for stake in surebet.stakes}) == len(
        surebet.stakes
    )

    served_margin = implied_sum([stake.odds for stake in surebet.stakes])
    assert served_margin == pytest.approx(surebet.raw_margin, rel=1e-12)
    assert round(served_margin, 4) == surebet.total_margin
    assert surebet.profit_percent == pytest.approx(
        round((1.0 / served_margin - 1.0) * 100.0, 2), abs=1e-9
    )

    # Proportional split: equal return on every outcome, rounded only to cents.
    returns = [stake.stake * stake.odds for stake in surebet.stakes]
    assert max(returns) - min(returns) <= 0.02
    assert sum(stake.stake for stake in surebet.stakes) == pytest.approx(
        investment, abs=0.01 * len(surebet.stakes)
    )

    # The served rounded stakes, not the exact split, are the realised worst case.
    worst_return = min(returns)
    assert surebet.realized is not None
    assert surebet.realized.worst_case_return == pytest.approx(worst_return, abs=0.01)
    assert surebet.realized.realized_profit == pytest.approx(
        worst_return - sum(stake.stake for stake in surebet.stakes), abs=0.02
    )


@given(
    high=st.floats(
        min_value=2.02, max_value=2.15, allow_nan=False, allow_infinity=False
    ),
    low=st.floats(
        min_value=1.50, max_value=1.90, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_two_books_on_one_feed_never_supply_both_legs(high: float, low: float) -> None:
    # MDShop and Admiralbet are both NSoft. Even when their two quotes would be
    # the best complementary pair, only one may price a leg; the independent
    # book is the other side.
    group = _group(
        {
            "mdshop": (high, low),
            "admiralbet": (low, high),
            "mbet": (low, high),
            "wwin": (high, low),
        }
    )
    surebets = ArbitrageEngine().find_surebets([group], min_profit=0.1, investment=100.0)

    assert surebets
    for surebet in surebets:
        books = [stake.bookmaker for stake in surebet.stakes]
        sources = [price_source(book) for book in books]
        assert len(set(books)) == len(books)
        assert len(set(sources)) == len(sources)
        assert not {"mdshop", "admiralbet"} <= set(books)


@given(
    value=st.floats(
        min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
    ),
    rounding=st.sampled_from(["exact", "1", "5"]),
)
@settings(max_examples=300, deadline=None)
def test_round_stake_is_finite_non_negative_and_lies_on_its_grid(
    value: float, rounding: str
) -> None:
    rounded = round_stake(value, rounding)

    assert math.isfinite(rounded)
    assert rounded >= 0
    if rounding == "1":
        assert rounded == pytest.approx(round(rounded), abs=1e-9)
    elif rounding == "5":
        assert rounded / 5.0 == pytest.approx(round(rounded / 5.0), abs=1e-9)
    else:
        assert rounded == pytest.approx(round(value, 2), abs=1e-12)


@given(
    odds=st.lists(
        st.floats(
            min_value=1.80, max_value=3.00, allow_nan=False, allow_infinity=False
        ),
        min_size=2,
        max_size=3,
    ),
    investment=st.floats(
        min_value=10.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
    rounding=st.sampled_from(["1", "5"]),
)
@settings(max_examples=200, deadline=None)
def test_rounding_is_bounded_and_downward_rounding_never_gains(
    odds: list[float], investment: float, rounding: str
) -> None:
    margin = implied_sum(odds)
    if margin >= 1.0:
        return
    step = 1.0 if rounding == "1" else 5.0
    rows = [
        {
            "odds": odd,
            "stake": round_stake(investment * (1.0 / odd) / margin, "exact"),
        }
        for odd in odds
    ]

    rounded_rows = [
        {"odds": row["odds"], "stake": round_stake(row["stake"], rounding)}
        for row in rows
    ]
    summary = rounding_summary(rounded_rows, investment=investment, rounding=rounding)
    loss = float(summary["rounding_loss"])
    exact = float(summary["exact_profit"])
    realized = float(summary["realized_profit"])

    # The signed number is exact minus realised, and may be a small gain when
    # the book rounds a leg down. It can never exceed one step per leg.
    assert loss == pytest.approx(exact - realized, abs=0.02)
    assert abs(loss) <= step * len(odds) + 0.02

    # A deliberately downward split is the conservative execution model. The
    # unspent cents stay in the bankroll, so profit is measured against the
    # whole investment: a floor can only lower the returned amount, never
    # invent profit. That conservative loss is non-negative.
    worst_funded_return = min(
        (math.floor(row["stake"] / step) * step) * row["odds"] for row in rows
    )
    exact_profit = investment / margin - investment
    funded_profit = worst_funded_return - investment
    assert exact_profit - funded_profit >= -1e-9
    assert funded_profit <= exact_profit + 1e-9


def test_a_minimized_rounding_case_is_pinned_as_a_normal_regression() -> None:
    """Odds 2.28/2.52 at 100 and round-to-1 is the smallest gain we found.

    Round-half-even turns 52.50000000000001/47.50000000000001 into 53/48, so
    the realised return is 0.14 above the exact one. The old claim "rounding
    loss is always >= 0" is false; this pins the documented bounded-gain
    behaviour instead.
    """
    odds = [2.28, 2.52]
    margin = implied_sum(odds)
    exact_stakes = [100.0 * (1.0 / odd) / margin for odd in odds]
    rows = [
        {"odds": odd, "stake": round_stake(stake, "1")}
        for odd, stake in zip(odds, exact_stakes, strict=True)
    ]

    summary = rounding_summary(rows, investment=100.0, rounding="1")
    loss = float(summary["rounding_loss"])

    assert [row["stake"] for row in rows] == [53.0, 48.0]
    assert loss == pytest.approx(-0.14, abs=0.01)
    assert abs(loss) <= 1.0 * len(odds)
