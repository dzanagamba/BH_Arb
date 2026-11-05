"""P2-9: a silent feed drop is flagged, a legitimate empty is not."""

from __future__ import annotations

from pathlib import Path

from engine.coverage_budget import evaluate, push_history, snapshot
from models.schemas import Market, MarketType, Match, OddsValue

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")


def _m(book: str, market: MarketType = MarketType.BTTS) -> Match:
    return Match(
        bookmaker=book,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        markets=[Market(market_type=market, odds=[OddsValue(label="GG", value=2.0)])],
    )


def _counts(**values: int) -> dict[str, int]:
    return dict(values)


def test_snapshot_counts_market_rows_per_book_sport_market():
    counts = snapshot([_m("mbet"), _m("mbet"), _m("wwin")])

    assert counts == {
        "mbet|football|btts": 2,
        "wwin|football|btts": 1,
    }


def test_a_90_percent_drop_with_peers_still_publishing_is_flagged():
    history = [{"mbet|football|btts": 10, "wwin|football|btts": 10}]
    current = _counts(**{"mbet|football|btts": 1, "wwin|football|btts": 10})

    report = evaluate(current, history)

    assert report["flag_count"] == 1
    assert report["flags"][0]["kind"] == "material_drop"
    assert report["flags"][0]["bookmaker"] == "mbet"


def test_zero_while_a_peer_is_populated_is_a_silent_zero():
    history = [{"mbet|football|btts": 10, "wwin|football|btts": 10}]
    current = _counts(**{"mbet|football|btts": 0, "wwin|football|btts": 12})

    report = evaluate(current, history)

    assert report["flag_count"] == 1
    assert report["flags"][0]["kind"] == "silent_zero"


def test_a_legitimate_empty_night_is_not_a_flag():
    history = [{"mbet|football|btts": 10, "wwin|football|btts": 10}]
    current = _counts(**{"mbet|football|btts": 0, "wwin|football|btts": 0})

    assert evaluate(current, history)["flag_count"] == 0


def test_a_short_baseline_is_not_enough_to_call_a_drop():
    history = [{"mbet|football|btts": 1}]
    current = _counts(**{"mbet|football|btts": 0})

    assert evaluate(current, history)["flag_count"] == 0


def test_history_is_bounded():
    history: list[dict[str, int]] = []
    for value in range(30):
        history = push_history(history, {"mbet|football|btts": value}, max_scans=20)

    assert len(history) == 20
    assert history[-1]["mbet|football|btts"] == 29


def test_dashboard_shows_the_coverage_flag_count():
    assert "coverage_budget" in JS
    assert "Coverage {count} flag(s)" in JS
