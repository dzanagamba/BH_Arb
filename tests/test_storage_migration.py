"""P3-1: JSON runtime state migrates to SQLite without losing rows."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from server.storage import Storage


def _scan(mode: str, scan_time: str, matches: int = 10) -> dict:
    return {
        "mode": mode,
        "scan_time": scan_time,
        "total_matches": matches,
        "match_groups": 5,
        "surebets_found": 1,
        "per_bookie": {"mbet": matches},
        "errors": [],
        "candidate_queue": 4,
        "candidate_actionable": 2,
    }


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_json_history_and_decisions_migrate_with_matching_counts(tmp_path):
    history = tmp_path / "scan_history.json"
    decisions = tmp_path / "suppressed_candidates.json"
    _write_json(
        history,
        [
            _scan("prematch", "2026-11-03T10:00:00"),
            _scan("live", "2026-11-04T10:00:00"),
            _scan("prematch", "2026-11-04T11:00:00"),
        ],
    )
    _write_json(
        decisions,
        {
            "decisions": {"a": "approved", "b": "rejected"},
            "premises": {"a": "link_unverified"},
        },
    )
    storage = Storage(str(tmp_path / "bh_arb.sqlite3"))
    storage.initialize()

    counts = storage.migrate_json(history_path=str(history), decisions_path=str(decisions))

    assert counts == {"scans": 3, "decisions": 2}
    assert storage.counts() == {"scans": 3, "decisions": 2, "link_sweeps": 0}
    assert storage.decisions() == {"a": "approved", "b": "rejected"}
    assert storage.decision_premises() == {"a": "link_unverified"}


def test_migration_is_idempotent(tmp_path):
    history = tmp_path / "scan_history.json"
    decisions = tmp_path / "suppressed_candidates.json"
    _write_json(history, [_scan("prematch", "2026-11-03T10:00:00")])
    _write_json(decisions, {"decisions": {"a": "approved"}, "premises": {}})
    storage = Storage(str(tmp_path / "bh_arb.sqlite3"))
    storage.initialize()

    storage.migrate_json(history_path=str(history), decisions_path=str(decisions))
    storage.migrate_json(history_path=str(history), decisions_path=str(decisions))

    assert storage.counts()["scans"] == 1
    assert storage.counts()["decisions"] == 1


def test_thirty_day_window_is_queryable_without_the_json_file(tmp_path):
    storage = Storage(str(tmp_path / "bh_arb.sqlite3"))
    storage.initialize()
    now = datetime.now(UTC).replace(tzinfo=None)
    storage.append_scan(_scan("prematch", now.isoformat()))
    storage.append_scan(_scan("prematch", (now - timedelta(days=45)).isoformat()))

    recent = storage.list_scans(days=30)

    assert len(recent) == 1
    assert recent[0]["mode"] == "prematch"
    assert storage.prune_scans(days=30) == 1
    assert len(storage.list_scans()) == 1


def test_a_scan_appends_transactionally_and_a_backup_restores_it(tmp_path):
    storage = Storage(str(tmp_path / "bh_arb.sqlite3"))
    storage.initialize()
    storage.append_scan(_scan("live", "2026-11-04T10:00:00", matches=22))

    backup = tmp_path / "backup.sqlite3"
    storage.backup(str(backup))

    with sqlite3.connect(backup) as connection:
        row = connection.execute("SELECT total_matches FROM scans").fetchone()
    assert row == (22,)
