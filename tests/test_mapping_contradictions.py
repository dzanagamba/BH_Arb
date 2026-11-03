"""Alias chains may not merge two clubs that are listed as opponents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.mapping_evidence import (
    DEFAULT_TTL_DAYS,
    Evidence,
    MappingLedger,
    team_alias_key,
)
from engine.team_resolver import (
    accepted_alias_edges,
    connected_components,
    revoke_contradictions,
)


def _ledger(tmp_path: Path) -> MappingLedger:
    return MappingLedger(tmp_path / "evidence.json")


def _accept(ledger: MappingLedger, left: str, right: str, kind: str = "betradar_shared_id"):
    ledger.accept(
        "team_alias",
        team_alias_key(left, right),
        [Evidence(type=kind, scan="s1", books=("a", "b"))],
        kind,
    )


def test_a_direct_opponent_pair_is_revoked(tmp_path):
    ledger = _ledger(tmp_path)
    _accept(ledger, "Alpha", "Beta")
    revoked = revoke_contradictions(ledger, {frozenset(("alpha", "beta"))})
    assert revoked == ["alpha|beta"]
    claim = ledger.get("team_alias", "alpha|beta")
    assert claim.status == "rejected"
    assert "opponent_contradiction" in claim.contradictions


def test_a_chain_is_split_at_its_weakest_edge(tmp_path):
    ledger = _ledger(tmp_path)
    _accept(ledger, "Alpha", "Beta", "exact_shared_fixture")  # 0.95
    _accept(ledger, "Beta", "Gamma", "betradar_shared_id")  # 1.00
    revoked = revoke_contradictions(ledger, {frozenset(("alpha", "gamma"))})
    assert revoked == ["alpha|beta"]
    assert ledger.get("team_alias", "alpha|beta").status == "rejected"
    assert ledger.get("team_alias", "beta|gamma").status == "accepted"
    edges = accepted_alias_edges(ledger)
    components = connected_components(edges)
    assert components.get("alpha") != components.get("gamma")


def test_a_stale_edge_does_not_connect_clusters(tmp_path):
    ledger = _ledger(tmp_path)
    _accept(ledger, "Alpha", "Beta")
    claim = ledger.get("team_alias", "alpha|beta")
    claim.last_seen = (
        datetime.now(UTC).replace(tzinfo=None) - timedelta(days=DEFAULT_TTL_DAYS + 1)
    ).isoformat(timespec="seconds")
    assert accepted_alias_edges(ledger) == []
    assert revoke_contradictions(ledger, {frozenset(("alpha", "beta"))}) == []


def test_a_revoked_contradiction_cannot_be_re_accepted(tmp_path):
    ledger = _ledger(tmp_path)
    _accept(ledger, "Alpha", "Beta")
    revoke_contradictions(ledger, {frozenset(("alpha", "beta"))})
    claim = ledger.accept(
        "team_alias",
        "alpha|beta",
        [Evidence(type="betradar_shared_id", scan="s2")],
        "new scan",
    )
    assert claim.status == "rejected"
    assert claim.reason == "revoked_opponent_contradiction"


def test_connected_components_are_shared_across_members(tmp_path):
    ledger = _ledger(tmp_path)
    _accept(ledger, "Alpha", "Beta")
    _accept(ledger, "Beta", "Gamma")
    components = connected_components(accepted_alias_edges(ledger))
    assert components["alpha"] == frozenset({"alpha", "beta", "gamma"})
