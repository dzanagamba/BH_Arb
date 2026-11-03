"""The evidence ledger: provenance, policy and durable decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from engine.mapping_evidence import (
    DEFAULT_TTL_DAYS,
    Evidence,
    MappingClaim,
    MappingLedger,
    claim_id,
    league_equivalence_key,
    market_mapping_key,
    team_alias_key,
)


def _evidence(kind: str = "betradar_shared_id", scan: str = "scan-1") -> Evidence:
    return Evidence(
        type=kind,
        detail={"id": "12345"},
        scan=scan,
        books=("mdshop", "wwin"),
        observed_at="2026-11-03T12:00:00",
    )


def _ledger(tmp_path: Path) -> MappingLedger:
    return MappingLedger(tmp_path / "evidence.json")


def test_round_trip_preserves_a_claim(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("Man. Utd", "Manchester United")
    ledger.accept("team_alias", key, [_evidence()], "same Betradar id")
    ledger.save()

    loaded = MappingLedger(tmp_path / "evidence.json").load()
    claim = loaded.get("team_alias", key)
    assert claim is not None
    assert claim.status == "accepted"
    assert claim.confidence == 1.0
    assert claim.evidence[0].type == "betradar_shared_id"
    assert claim.is_authoritative()


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.accept("team_alias", team_alias_key("A", "B"), [_evidence()])
    ledger.save()
    assert [p.name for p in tmp_path.iterdir()] == ["evidence.json"]


def test_a_corrupt_file_is_an_empty_ledger_with_an_error(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("{not json", encoding="utf-8")
    ledger = MappingLedger(path).load()
    assert ledger.claims == {}
    assert ledger.load_error


def test_an_unknown_schema_is_ignored(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"schema": 99, "claims": {}}), encoding="utf-8")
    ledger = MappingLedger(path).load()
    assert ledger.claims == {}
    assert "schema" in ledger.load_error


def test_an_unknown_claim_kind_is_ignored(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "claims": {
                    "not_a_kind:x": {
                        "kind": "not_a_kind",
                        "key": "x",
                        "status": "accepted",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    ledger = MappingLedger(path).load()
    assert ledger.claims == {}


def test_duplicate_evidence_is_merged(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    ledger.accept("team_alias", key, [_evidence()])
    ledger.accept("team_alias", key, [_evidence()])
    claim = ledger.get("team_alias", key)
    assert claim is not None
    assert len(claim.evidence) == 1

    ledger.accept("team_alias", key, [_evidence(scan="scan-2")])
    assert len(ledger.get("team_alias", key).evidence) == 2


def test_similarity_alone_cannot_accept(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    claim = ledger.accept("team_alias", key, [_evidence("similarity")])
    assert claim.status == "quarantined"
    assert not ledger.is_accepted("team_alias", key)


def test_legacy_review_alone_cannot_accept(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    claim = ledger.accept("team_alias", key, [_evidence("legacy_review")])
    assert claim.status == "quarantined"


def test_an_exact_fixture_accepts(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    claim = ledger.accept("team_alias", key, [_evidence("exact_shared_fixture")])
    assert claim.status == "accepted"


def test_revocation_is_durable_and_keeps_history(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    ledger.accept("team_alias", key, [_evidence()])
    ledger.revoke("team_alias", key, "opponent_contradiction")
    ledger.save()

    loaded = MappingLedger(tmp_path / "evidence.json").load()
    claim = loaded.get("team_alias", key)
    assert claim is not None
    assert claim.status == "rejected"
    assert "opponent_contradiction" in claim.contradictions
    assert claim.evidence, "the evidence that led to the claim is kept"
    assert not loaded.is_accepted("team_alias", key)


def test_a_stale_claim_stops_authorizing(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    ledger.accept("team_alias", key, [_evidence()])
    claim = ledger.get("team_alias", key)
    claim.last_seen = (
        datetime.now(UTC).replace(tzinfo=None) - timedelta(days=DEFAULT_TTL_DAYS + 1)
    ).isoformat(timespec="seconds")
    assert not claim.is_authoritative()
    assert not ledger.is_accepted("team_alias", key)


def test_diff_reports_added_changed_and_removed(tmp_path):
    previous = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    previous.accept("team_alias", key, [_evidence()])

    current = _ledger(tmp_path)
    current.accept("team_alias", key, [_evidence("similarity")])
    current.accept("team_alias", team_alias_key("C", "D"), [_evidence()])

    diff = current.diff(previous)
    assert claim_id("team_alias", team_alias_key("C", "D")) in diff["added"]
    assert claim_id("team_alias", key) in diff["changed"]
    assert diff["counts"]["accepted"] == 1
    assert diff["counts"]["quarantined"] == 1


def test_key_helpers_are_order_insensitive():
    assert team_alias_key("Man. Utd", "Manchester United") == team_alias_key(
        "Manchester United", "Man. Utd"
    )
    assert league_equivalence_key("England 1", "Premier League") == league_equivalence_key(
        "Premier League", "England 1"
    )
    assert market_mapping_key("mbet", "prematch", 5, ["1", "X", "2"]) == market_mapping_key(
        "mbet", "prematch", 5, ["2", "1", "X"]
    )


def test_accept_rejects_an_unknown_kind(tmp_path):
    ledger = _ledger(tmp_path)
    with pytest.raises(ValueError):
        ledger.accept("not_a_kind", "x", [_evidence()])


def test_from_dict_rejects_a_malformed_claim():
    assert MappingClaim.from_dict({"kind": "team_alias", "key": ""}) is None
    assert MappingClaim.from_dict({"kind": "team_alias", "key": "x", "status": "maybe"}) is None


def test_a_weak_observation_does_not_downgrade_an_accepted_claim(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    ledger.accept("team_alias", key, [_evidence("betradar_shared_id")], "proven")
    ledger.quarantine("team_alias", key, [_evidence("similarity", scan="s2")], "similarity_only")
    claim = ledger.get("team_alias", key)
    assert claim.status == "accepted"
    assert claim.confidence == 1.0


def test_force_quarantine_overrides_an_accepted_claim(tmp_path):
    ledger = _ledger(tmp_path)
    key = team_alias_key("A", "B")
    ledger.accept("team_alias", key, [_evidence("betradar_shared_id")], "proven")
    ledger.quarantine(
        "team_alias", key, [_evidence("similarity", scan="s2")], "ambiguous", force=True
    )
    assert ledger.get("team_alias", key).status == "quarantined"
