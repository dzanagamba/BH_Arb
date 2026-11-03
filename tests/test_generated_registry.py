"""A machine-proven registry row can override a hand-written one."""

from __future__ import annotations

import json
from pathlib import Path

from engine.mapping_evidence import Evidence, MappingLedger, market_mapping_key
from engine.market_registry import MarketRegistry
from models.schemas import MarketType

HAND = {
    "mbet": {
        "prematch": {
            "over_under_2_5": {
                "ids": [5],
                "labels": ["Over 2.5", "Under 2.5"],
            }
        }
    }
}


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_generated_row_with_provenance_overrides(tmp_path):
    hand = _write(tmp_path / "hand.json", HAND)
    generated = _write(
        tmp_path / "generated.json",
        {
            "mbet": {
                "prematch": {
                    "over_under_2_5": {
                        "ids": [5],
                        "labels": ["Over 2.5", "Under 2.5"],
                        "line": 2.5,
                        "_provenance": {"status": "accepted", "claim": "x"},
                    }
                }
            }
        },
    )
    registry = MarketRegistry(str(hand), str(generated))
    spec = registry.lookup("mbet", "prematch", 5)
    assert spec is not None
    assert spec.generated is True
    assert spec.line == 2.5
    assert "mbet/prematch/5" in registry.generated_rows


def test_a_generated_row_without_provenance_is_ignored(tmp_path):
    hand = _write(tmp_path / "hand.json", HAND)
    generated = _write(
        tmp_path / "generated.json",
        {
            "mbet": {
                "prematch": {
                    "over_under_2_5": {
                        "ids": [5],
                        "labels": ["Over 2.5", "Under 2.5"],
                    }
                }
            }
        },
    )
    registry = MarketRegistry(str(hand), str(generated))
    spec = registry.lookup("mbet", "prematch", 5)
    assert spec is not None
    assert spec.generated is False


def test_the_generator_reads_accepted_claims(tmp_path):
    from scripts.generate_market_registry import build_registry

    ledger = MappingLedger(tmp_path / "evidence.json")
    key = market_mapping_key("mbet", "prematch", "5", ["Over 2.5", "Under 2.5"])
    ledger.accept(
        "market_mapping",
        key,
        [
            Evidence(
                type="cross_book_price",
                detail={
                    "bookmaker": "mbet",
                    "mode": "prematch",
                    "market_type": MarketType.OVER_UNDER_2_5.value,
                    "source_id": "5",
                    "labels": ["Over 2.5", "Under 2.5"],
                    "line": 2.5,
                },
            )
        ],
        "consensus",
    )
    registry = build_registry(ledger)
    row = registry["mbet"]["prematch"]["over_under_2_5"]
    assert row["ids"] == [5]
    assert row["_provenance"]["status"] == "accepted"
