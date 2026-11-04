"""The atomic cache writer serialises stray datetimes without a round-trip."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.certainty import CertaintyGate
from models.schemas import Match, MatchGroup
from server.api import _atomic_write_json


def _match(bookmaker: str, home: str, away: str, home_n: str) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        home_team_normalized=home_n,
        away_team_normalized="bravo",
        league="League",
        league_normalized="league",
        kickoff=datetime(2026, 11, 3, 18, 0),
        event_id=f"{bookmaker}-1",
        deep_link_verified=True,
    )


def test_cached_group_payload_is_bounded(tmp_path: Path):
    """A nine-book group must not carry a copy of the alias allowlist.

    The gate used to write ``sorted(self.alias_allowlist)`` into every
    allowlist-sourced record. That is duplicate configuration, not evidence,
    and it made a real nine-book cache 218 MB. Each record must instead name
    only the entry that proved its pair.
    """
    proving = "alpha united|alpha"
    allowlist = {f"unrelated {i}|other {i}" for i in range(3_000)}
    allowlist.add(proving)
    gate = CertaintyGate(alias_allowlist=allowlist)

    anchor = _match("anchor", "Alpha United", "Bravo", "alpha united")
    group = MatchGroup(
        canonical_home="alpha united",
        canonical_away="bravo",
        league="league",
        kickoff=anchor.kickoff,
        status="verified",
        matches=[anchor],
    )

    for index in range(8):
        candidate = _match(f"book{index}", "Alpha", "Bravo", "alpha")
        result = gate.evaluate(candidate, group)
        assert result.status == "verified", result.reasons
        group.matches.append(candidate)
        group.evidence.extend(result.evidence)

    payload = json.dumps(group.model_dump(mode="json"), ensure_ascii=False)
    serialized = tmp_path / "group.json"
    serialized.write_text(payload, encoding="utf-8")

    assert proving in payload
    assert "unrelated 0|other 0" not in payload
    assert len(payload) < 50_000, "the group payload is not bounded by its own data"
    assert serialized.stat().st_size == len(payload.encode("utf-8"))

    allowlist_evidence = [e for e in group.evidence if e.source == "allowlist"]
    assert allowlist_evidence, "the group must still carry its allowlist proof"
    for evidence in allowlist_evidence:
        assert evidence.allowlist_entries == [proving]
        assert len(evidence.allowlist_entries) < len(allowlist)


def test_atomic_write_serializes_a_datetime(tmp_path: Path):
    path = tmp_path / "cache.json"
    _atomic_write_json(
        str(path),
        {"scan_time": datetime(2026, 11, 3, 5, 30), "matches": []},
        "cache",
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["scan_time"] == "2026-11-03 05:30:00"
    assert saved["matches"] == []


def test_health_reports_the_cache_size_budget(monkeypatch, tmp_path: Path):
    """The guard is visible in health, so a payload regression is not silent."""
    from fastapi.testclient import TestClient

    from server import api
    from server.app import app

    prematch = tmp_path / "last_scan.json"
    prematch.write_bytes(b"x" * 10)
    monkeypatch.setattr(api, "_PREMATCH_CACHE_FILE", str(prematch))
    monkeypatch.setattr(api, "_LIVE_CACHE_FILE", str(tmp_path / "last_live_scan.json"))
    monkeypatch.setattr(api, "CACHE_SIZE_BUDGET_BYTES", 5)

    body = TestClient(app).get("/api/health").json()

    assert body["cache"]["prematch_bytes"] == 10
    assert body["cache"]["live_bytes"] == 0
    assert body["cache"]["budget_bytes"] == 5
    assert body["cache"]["over_budget"] is True
