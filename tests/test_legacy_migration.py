"""The human-reviewed file migrates to quarantined ledger evidence."""

from __future__ import annotations

import json
from pathlib import Path

from engine.mapping_evidence import Evidence, MappingLedger, team_alias_key
from scripts.migrate_reviewed import migrate


def _reviewed(tmp_path: Path, approved: list[dict], rejected: list[dict] | None = None) -> Path:
    path = tmp_path / "reviewed.json"
    path.write_text(
        json.dumps(
            {
                "reviewed_at": "2026-10-27",
                "approved": approved,
                "rejected": rejected or [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_an_approved_pair_becomes_quarantined(tmp_path):
    path = _reviewed(tmp_path, [{"alias": "Man.Utd|Manchester United", "evidence": [{"fixture": "x"}]}])
    ledger = MappingLedger(tmp_path / "evidence.json")
    report = migrate(path, ledger)

    key = team_alias_key("Man.Utd", "Manchester United")
    claim = ledger.get("team_alias", key)
    assert claim is not None
    assert claim.status == "quarantined"
    assert claim.reason == "legacy_review_needs_corroboration"
    assert claim.evidence[0].type == "legacy_review"
    assert report["counts"]["imported"] == 1


def test_an_already_accepted_claim_is_not_downgraded(tmp_path):
    path = _reviewed(tmp_path, [{"alias": "Man.Utd|Manchester United"}])
    ledger = MappingLedger(tmp_path / "evidence.json")
    key = team_alias_key("Man.Utd", "Manchester United")
    ledger.accept(
        "team_alias",
        key,
        [Evidence(type="betradar_shared_id", scan="s1")],
        "proven",
    )
    report = migrate(path, ledger)
    assert ledger.get("team_alias", key).status == "accepted"
    assert report["counts"]["kept"] == 1


def test_migration_is_idempotent(tmp_path):
    path = _reviewed(tmp_path, [{"alias": "A|B"}])
    ledger = MappingLedger(tmp_path / "evidence.json")
    migrate(path, ledger)
    migrate(path, ledger)
    claim = ledger.get("team_alias", team_alias_key("A", "B"))
    assert claim.status == "quarantined"
    assert len(claim.evidence) == 1


def test_rejections_are_counted_not_trusted(tmp_path):
    path = _reviewed(
        tmp_path,
        [{"alias": "A|B"}],
        [{"alias": "C|D", "reason": "different clubs"}],
    )
    ledger = MappingLedger(tmp_path / "evidence.json")
    report = migrate(path, ledger)
    assert report["rejected_total"] == 1
    assert ledger.get("team_alias", team_alias_key("C", "D")) is None
