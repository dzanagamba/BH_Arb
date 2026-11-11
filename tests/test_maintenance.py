"""N1-1: bounded retention, dry-run, backup/restore and health sizes."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import settings
from engine import matcher
from engine.mapping_evidence import Evidence, MappingLedger, team_alias_key
from models.schemas import Match
from server import api, scheduler
from server.app import app
from server.bets import BetStore
from server.maintenance import maintenance_running, retention_health, run_maintenance
from server.paper import PaperStore
from server.storage import Storage


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _scan(mode: str, when: datetime, matches: int = 10) -> dict:
    return {
        "mode": mode,
        "scan_time": when.isoformat(timespec="seconds"),
        "total_matches": matches,
        "match_groups": 5,
        "surebets_found": 1,
        "per_bookie": {"mbet": matches},
        "errors": [],
        "candidate_queue": 4,
        "candidate_actionable": 2,
    }


def _bet_payload(home: str) -> dict:
    return {
        "home_team": home,
        "away_team": "Away",
        "market_type": "1x2",
        "legs": [
            {
                "bookmaker": "mbet",
                "outcome_label": "1",
                "odds": 2.0,
                "stake": 10.0,
                "accepted_odds": 2.0,
                "accepted_stake": 10.0,
            }
        ],
    }


def _seed(path: Path, now: datetime) -> dict[str, str]:
    storage = Storage(str(path))
    storage.initialize()
    storage.append_scan(_scan("prematch", now - timedelta(days=120), matches=11))
    storage.append_scan(_scan("prematch", now - timedelta(days=10), matches=22))
    paper = PaperStore(str(path))
    paper.initialize()
    with paper._connect() as connection:
        with connection:
            for index, age in enumerate((200, 10)):
                recorded = (now - timedelta(days=age)).isoformat(timespec="seconds")
                connection.execute(
                    """
                    INSERT INTO recorded_opportunities(
                        id, key, recorded_at, feed_mode, run_mode, payload
                    ) VALUES (?, ?, ?, 'prematch', 'paper', ?)
                    """,
                    (f"opp-{index}", f"key-{index}", recorded, json.dumps({"id": f"opp-{index}"})),
                )
                connection.execute(
                    """
                    INSERT INTO paper_positions(
                        id, opportunity_id, key, opened_at, settled_at, status, payload
                    ) VALUES (?, ?, ?, ?, NULL, 'open', ?)
                    """,
                    (
                        f"pos-{index}",
                        f"opp-{index}",
                        f"key-{index}",
                        recorded,
                        json.dumps({"id": f"pos-{index}"}),
                    ),
                )

    bets = BetStore(str(path))
    bets.initialize()
    old = bets.create(_bet_payload("Old Home"))
    recent = bets.create(_bet_payload("Recent Home"))
    for bet in (old, recent):
        bets.settle(
            bet["id"],
            [{"outcome_label": "1", "result": "won"}],
        )
    with bets._connect() as connection:
        with connection:
            connection.execute(
                "UPDATE bets SET settled_at = ? WHERE id = ?",
                ((now - timedelta(days=400)).isoformat(timespec="seconds"), old["id"]),
            )
    return {"old_bet": old["id"], "recent_bet": recent["id"]}


def _ledger(path: Path) -> MappingLedger:
    ledger = MappingLedger(path)
    ledger.accept(
        "team_alias",
        team_alias_key("Alpha", "Beta"),
        [
            Evidence(
                type="exact_shared_fixture",
                detail={"seed": f"N1-1-{index}"},
                scan="maintenance-test",
                books=("mbet", "wwin"),
            )
            for index in range(12)
        ],
        "N1-1 retention test",
    )
    ledger.save()
    return ledger


def _log_files(log_dir: Path, now: datetime) -> tuple[Path, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    old = log_dir / "scanner.log.1"
    recent = log_dir / "scanner.log"
    old.write_text("old\n", encoding="utf-8")
    recent.write_text("recent\n", encoding="utf-8")
    stamp = (now - timedelta(days=60)).timestamp()
    os.utime(old, (stamp, stamp))
    return old, recent


def _row_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_old_rows_are_pruned_and_recent_rows_are_retained(tmp_path):
    now = _now()
    db_path = tmp_path / "bh_arb.sqlite3"
    ledger_path = tmp_path / "generated" / "mapping_evidence.json"
    log_dir = tmp_path / "logs"
    archive_dir = tmp_path / "archives"
    ids = _seed(db_path, now)
    _ledger(ledger_path)
    old_log, recent_log = _log_files(log_dir, now)

    report = run_maintenance(
        now=now,
        storage_path=db_path,
        ledger_path=ledger_path,
        log_dir=log_dir,
        archive_dir=archive_dir,
    )

    assert report["ok"] is True
    assert report["dry_run"] is False
    assert report["pruned"] == {"scans": 1}
    assert report["paper"]["recorded_opportunities"] == 1
    assert report["paper"]["paper_positions"] == 1
    assert _row_count(db_path, "scans") == 1
    assert _row_count(db_path, "recorded_opportunities") == 1
    assert _row_count(db_path, "paper_positions") == 1

    # Bets are the longitudinal record: both rows stay, the old settled one is
    # copied to an archive file.
    assert _row_count(db_path, "bets") == 2
    assert BetStore(str(db_path)).get(ids["old_bet"]) is not None
    assert report["bets"]["rows"] == 1
    archive_path = Path(report["bets"]["path"])
    assert archive_path.exists()
    archived = json.loads(archive_path.read_text(encoding="utf-8"))
    assert [bet["id"] for bet in archived["bets"]] == [ids["old_bet"]]

    # The existing evidence prune rule is applied, not replaced.
    assert report["mapping_evidence"]["claims"] == 1
    assert report["mapping_evidence"]["evidence_dropped"] == 4
    assert report["mapping_evidence"]["saved"] is True
    reloaded = MappingLedger(ledger_path).load()
    assert len(reloaded.claims) == 1
    assert len(next(iter(reloaded.claims.values())).evidence) == 8

    assert report["logs"]["removed"] == 1
    assert not old_log.exists()
    assert recent_log.exists()

    health = retention_health(
        storage_path=db_path, ledger_path=ledger_path, log_dir=log_dir
    )
    assert health["last_maintenance"]["finished_at"]
    assert health["tables"]["scans"]["rows"] == 1
    assert health["paper"]["rows"] == 2
    assert health["bets"]["rows"] == 2
    assert health["over_budget"] is False


def test_dry_run_changes_nothing_and_reports_the_counts(tmp_path):
    now = _now()
    db_path = tmp_path / "bh_arb.sqlite3"
    ledger_path = tmp_path / "generated" / "mapping_evidence.json"
    log_dir = tmp_path / "logs"
    archive_dir = tmp_path / "archives"
    backup_dir = tmp_path / "backups"
    _seed(db_path, now)
    _ledger(ledger_path)
    old_log, recent_log = _log_files(log_dir, now)

    before_bytes = db_path.stat().st_size
    before_mtime = db_path.stat().st_mtime_ns
    before_ledger = ledger_path.read_bytes()

    report = run_maintenance(
        dry_run=True,
        backup_dir=backup_dir,
        now=now,
        storage_path=db_path,
        ledger_path=ledger_path,
        log_dir=log_dir,
        archive_dir=archive_dir,
    )

    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["pruned"] == {"scans": 1}
    assert report["paper"]["recorded_opportunities"] == 1
    assert report["paper"]["paper_positions"] == 1
    assert report["bets"]["rows"] == 1
    assert report["backup"]["would_write"]

    # Nothing was pruned, archived, backed up, vacuumed or marked.
    assert _row_count(db_path, "scans") == 2
    assert _row_count(db_path, "recorded_opportunities") == 2
    assert _row_count(db_path, "paper_positions") == 2
    assert _row_count(db_path, "bets") == 2
    assert db_path.stat().st_size == before_bytes
    assert db_path.stat().st_mtime_ns == before_mtime
    assert ledger_path.read_bytes() == before_ledger
    assert old_log.exists() and recent_log.exists()
    assert not archive_dir.exists()
    assert not backup_dir.exists()
    assert Storage(str(db_path)).last_maintenance() is None


def test_a_backup_restores_identical_counts_and_the_newest_rows(tmp_path):
    now = _now()
    db_path = tmp_path / "bh_arb.sqlite3"
    ledger_path = tmp_path / "generated" / "mapping_evidence.json"
    log_dir = tmp_path / "logs"
    backup_dir = tmp_path / "backups"
    _seed(db_path, now)
    _ledger(ledger_path)
    _log_files(log_dir, now)

    report = run_maintenance(
        vacuum=True,
        backup_dir=backup_dir,
        now=now,
        storage_path=db_path,
        ledger_path=ledger_path,
        log_dir=log_dir,
        archive_dir=tmp_path / "archives",
    )
    assert report["vacuumed"] is True
    files = [Path(path) for path in report["backup"]["files"]]
    db_backup = next(path for path in files if path.suffix == ".sqlite3")
    ledger_backup = next(path for path in files if path.suffix == ".json")
    assert db_backup.exists() and ledger_backup.exists()

    original = Storage(str(db_path))
    original_counts = original.counts()
    original_newest_scan = original.list_scans(limit=1)[0]["scan_time"]
    original_newest_position = PaperStore(str(db_path)).list_positions(limit=1)[0]["id"]

    restored_path = tmp_path / "restored.sqlite3"
    shutil.copy2(db_backup, restored_path)
    restored = Storage(str(restored_path))
    restored_paper = PaperStore(str(restored_path))

    assert restored.counts() == original_counts
    assert restored.list_scans(limit=1)[0]["scan_time"] == original_newest_scan
    assert restored_paper.list_positions(limit=1)[0]["id"] == original_newest_position
    assert json.loads(ledger_backup.read_text(encoding="utf-8"))["claims"]


def test_paper_row_cap_keeps_the_newest_rows(tmp_path):
    now = _now()
    path = tmp_path / "paper.sqlite3"
    store = PaperStore(str(path))
    store.initialize()
    with store._connect() as connection:
        with connection:
            for index, age in enumerate((30, 20, 10)):
                connection.execute(
                    """
                    INSERT INTO recorded_opportunities(
                        id, key, recorded_at, feed_mode, run_mode, payload
                    ) VALUES (?, ?, ?, 'prematch', 'paper', ?)
                    """,
                    (
                        f"opp-{index}",
                        f"key-{index}",
                        (now - timedelta(days=age)).isoformat(timespec="seconds"),
                        json.dumps({"id": f"opp-{index}"}),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO paper_positions(
                        id, opportunity_id, key, opened_at, settled_at, status, payload
                    ) VALUES (?, ?, ?, ?, NULL, 'open', ?)
                    """,
                    (
                        f"pos-{index}",
                        f"opp-{index}",
                        f"key-{index}",
                        (now - timedelta(days=age)).isoformat(timespec="seconds"),
                        json.dumps({"id": f"pos-{index}"}),
                    ),
                )

    result = store.prune(days=180, max_rows=2, dry_run=False)

    assert result["recorded_opportunities_over_cap"] == 1
    assert result["paper_positions_over_cap"] == 1
    assert {row["id"] for row in store.list_opportunities(days=365)} == {
        "opp-1",
        "opp-2",
    }
    assert {row["id"] for row in store.list_positions(days=365)} == {
        "pos-1",
        "pos-2",
    }


def test_a_scan_and_a_retention_job_cannot_overlap(tmp_path, monkeypatch):
    now = _now()
    db_path = tmp_path / "bh_arb.sqlite3"
    ledger_path = tmp_path / "generated" / "mapping_evidence.json"
    _seed(db_path, now)
    _ledger(ledger_path)

    skipped = run_maintenance(
        now=now,
        storage_path=db_path,
        ledger_path=ledger_path,
        log_dir=tmp_path / "logs",
        archive_dir=tmp_path / "archives",
        scan_active=lambda: True,
    )
    assert skipped["ok"] is False
    assert skipped["skipped"] == "scan_in_progress"
    assert _row_count(db_path, "scans") == 2

    status, _, _, _, _ = api._state_for("prematch")
    original = status.is_scanning
    status.is_scanning = False
    monkeypatch.setattr(api, "maintenance_running", lambda: True)
    try:
        assert asyncio.run(api.start_scan_if_idle("prematch")) is False
        assert status.is_scanning is False
    finally:
        status.is_scanning = original
    assert maintenance_running() is False


def test_health_exposes_store_sizes_and_the_last_run(tmp_path, monkeypatch):
    now = _now()
    db_path = tmp_path / "bh_arb.sqlite3"
    ledger_path = tmp_path / "generated" / "mapping_evidence.json"
    log_dir = tmp_path / "logs"
    _seed(db_path, now)
    _ledger(ledger_path)
    _log_files(log_dir, now)
    run_maintenance(
        now=now,
        storage_path=db_path,
        ledger_path=ledger_path,
        log_dir=log_dir,
        archive_dir=tmp_path / "archives",
    )

    monkeypatch.setenv("STORAGE_PATH", str(db_path))
    monkeypatch.setattr(matcher, "MAPPING_EVIDENCE_FILE", str(ledger_path))
    monkeypatch.setattr(settings, "LOG_DIR", str(log_dir))

    body = asyncio.run(api.health())

    retention = body["retention"]
    assert retention["sqlite"]["bytes"] > 0
    assert retention["sqlite"]["budget_bytes"] == settings.SQLITE_SIZE_BUDGET_BYTES
    assert retention["tables"]["scans"]["rows"] == 1
    assert retention["paper"]["rows"] == 2
    assert retention["bets"]["rows"] == 2
    assert retention["mapping_evidence"]["bytes"] > 0
    assert retention["logs"]["bytes"] > 0
    assert retention["last_maintenance"]["finished_at"]
    assert retention["windows"]["scans_days"] == settings.RETENTION_SCANS_DAYS


def test_the_daily_loop_runs_one_bounded_job_off_the_scan_path(monkeypatch):
    calls: list[dict] = []

    async def fake_sleep(_seconds: float) -> None:
        if calls:
            raise asyncio.CancelledError

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "pruned": {}, "paper": {}, "vacuumed": True}

    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "run_maintenance", fake_run)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            scheduler.maintenance_loop(
                interval_hours=24, startup_delay_seconds=0
            )
        )

    assert len(calls) == 1
    assert calls[0]["vacuum"] is True
    assert callable(calls[0]["scan_active"])


def test_a_cache_reload_restores_the_per_bookie_counts(monkeypatch, tmp_path):
    now = _now()
    matches = [
        Match(bookmaker="mbet", home_team="A", away_team="B"),
        Match(bookmaker="mbet", home_team="C", away_team="D"),
        Match(bookmaker="wwin", home_team="A", away_team="B"),
    ]
    cache_file = tmp_path / "last_scan.json"
    cache_file.write_text(
        json.dumps(
            {
                "scan_time": now.isoformat(timespec="seconds"),
                "surebets": [],
                "matches": [match.model_dump(mode="json") for match in matches],
                "match_groups": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "_PREMATCH_CACHE_FILE", str(cache_file))
    monkeypatch.setattr(api, "_LIVE_CACHE_FILE", str(tmp_path / "last_live_scan.json"))
    monkeypatch.setattr(api, "cached_matches", [])
    monkeypatch.setattr(api, "cached_per_bookie", {})
    monkeypatch.setattr(api, "cached_live_per_bookie", {})

    api._load_cache()

    assert api.cached_per_bookie == {"mbet": 2, "wwin": 1}
    body = TestClient(app).get("/api/health").json()
    assert body["prematch"]["per_bookie"] == {"mbet": 2, "wwin": 1}


def test_a_cache_reload_keeps_a_book_that_returned_zero_matches(monkeypatch, tmp_path):
    now = _now()
    cache_file = tmp_path / "last_scan.json"
    cache_file.write_text(
        json.dumps(
            {
                "scan_time": now.isoformat(timespec="seconds"),
                "surebets": [],
                "matches": [
                    Match(bookmaker="mbet", home_team="A", away_team="B").model_dump(
                        mode="json"
                    )
                ],
                "match_groups": [],
                "per_bookie": {"mbet": 1, "emptybook": 0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "_PREMATCH_CACHE_FILE", str(cache_file))
    monkeypatch.setattr(api, "_LIVE_CACHE_FILE", str(tmp_path / "last_live_scan.json"))
    monkeypatch.setattr(api, "cached_matches", [])
    monkeypatch.setattr(api, "cached_per_bookie", {})
    monkeypatch.setattr(api, "cached_live_per_bookie", {})

    api._load_cache()

    assert api.cached_per_bookie == {"mbet": 1, "emptybook": 0}


def test_the_daily_loop_skips_a_busy_scan(monkeypatch):
    calls: list[dict] = []
    sleeps = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    status, _, _, _, _ = api._state_for("prematch")
    original = status.is_scanning
    status.is_scanning = True
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(scheduler, "run_maintenance", fake_run)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                scheduler.maintenance_loop(
                    interval_hours=24, startup_delay_seconds=0
                )
            )
    finally:
        status.is_scanning = original

    assert sleeps == 2
    assert calls == []
