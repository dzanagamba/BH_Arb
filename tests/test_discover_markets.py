"""Discovery writes a market claim only when the other books agree."""

from __future__ import annotations

from datetime import datetime

from engine.mapping_evidence import MappingLedger
from models.schemas import Market, MarketType, Match, OddsValue
from scripts.discover_markets import discover

K = datetime(2026, 11, 7, 18, 0)


def _match(book: str, odds: tuple[float, float, float]) -> Match:
    return Match(
        bookmaker=book,
        home_team="Alpha",
        away_team="Beta",
        league="Test League",
        kickoff=K,
        event_id=book,
        deep_link_verified=True,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                source_id="1",
                odds=[
                    OddsValue(label="1", value=odds[0]),
                    OddsValue(label="X", value=odds[1]),
                    OddsValue(label="2", value=odds[2]),
                ],
            )
        ],
    )


def test_consensus_creates_an_accepted_market_claim(tmp_path):
    ledger = MappingLedger(tmp_path / "evidence.json")
    matches = [
        _match("mbet", (2.0, 3.4, 3.6)),
        _match("wwin", (2.05, 3.3, 3.5)),
        _match("sportplus", (1.95, 3.5, 3.7)),
    ]
    counts = discover(matches, ledger, scan="s1")
    assert counts["accepted"] >= 1
    accepted = [
        claim for claim in ledger.claims.values()
        if claim.kind == "market_mapping" and claim.status == "accepted"
    ]
    assert accepted


def test_an_outlier_is_quarantined(tmp_path):
    ledger = MappingLedger(tmp_path / "evidence.json")
    matches = [
        _match("mbet", (1.2, 6.0, 12.0)),
        _match("wwin", (2.05, 3.3, 3.5)),
        _match("sportplus", (1.95, 3.5, 3.7)),
    ]
    counts = discover(matches, ledger, scan="s1")
    assert counts["quarantined"] >= 1
