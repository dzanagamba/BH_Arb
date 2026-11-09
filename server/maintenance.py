"""Bounded retention, vacuum, backup and store inventory (N1-1).

Every runtime store used to grow forever. This module applies the configured
retention windows, records the last successful run in the SQLite ``meta`` table,
and reports the size of each store for ``/api/health``.

The runner is deliberately synchronous and off the scan path. A process-wide
guard makes a new scan refuse to start while a prune or ``VACUUM`` is running,
and the scheduler passes the current scan state so a maintenance tick skips a
busy feed instead of waiting for it.

Bets are the longitudinal record: they are never deleted. Settled rows older
than ``RETENTION_BETS_ARCHIVE_DAYS`` are copied to a dated JSON archive file and
stay in the database.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import settings
from engine import matcher
from engine.mapping_evidence import MappingLedger
from server.bets import BetStore
from server.paper import PaperStore
from server.sqlite_store import connect_readonly as _sqlite_connect_readonly
from server.storage import Storage, default_storage_path
from server.timeutil import iso_seconds, utcnow

logger = logging.getLogger(__name__)

# The scan starter reads `maintenance_running()` and refuses a new scan while
# this is set. The lock makes the flag itself safe across threads.
_MAINTENANCE_LOCK = threading.Lock()
_MAINTENANCE_ACTIVE = threading.Event()

_TABLES = (
    "scans",
    "decisions",
    "link_sweeps",
    "bets",
    "recorded_opportunities",
    "paper_positions",
)
_PAYLOAD_TABLES = {
    "link_sweeps",
    "bets",
    "recorded_opportunities",
    "paper_positions",
}


def maintenance_running() -> bool:
    """True while a retention job holds the process-wide guard."""
    return _MAINTENANCE_ACTIVE.is_set()


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _db_bytes(path: Path) -> int:
    """SQLite file plus its WAL/SHM sidecars; the bytes a backup must carry."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        total += _file_bytes(Path(f"{path}{suffix}"))
    return total


def _log_paths(log_dir: Path) -> list[Path]:
    if not log_dir.is_dir():
        return []
    paths: list[Path] = []
    for path in log_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if path.suffix == ".log" or ".log." in name:
            paths.append(path)
    return sorted(paths)


def _log_bytes(log_dir: Path) -> int:
    return sum(_file_bytes(path) for path in _log_paths(log_dir))


def _readonly_connection(path: Path) -> sqlite3.Connection:
    return _sqlite_connect_readonly(path)


def _table_inventory(path: Path) -> tuple[dict[str, dict[str, int]], dict[str, Any] | None]:
    """Row/payload counts and the recorded maintenance report, read-only."""
    if not path.exists():
        return {}, None
    tables: dict[str, dict[str, int]] = {}
    last_maintenance: dict[str, Any] | None = None
    try:
        with _readonly_connection(path) as connection:
            names = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for name in _TABLES:
                if name not in names:
                    continue
                rows = int(
                    # name is a member of the fixed _TABLES allowlist above.
                    connection.execute(
                        f"SELECT COUNT(*) FROM {name}"  # nosec B608
                    ).fetchone()[0]
                    or 0
                )
                entry = {"rows": rows}
                if name in _PAYLOAD_TABLES:
                    entry["payload_bytes"] = int(
                        connection.execute(
                            # name is a member of the fixed _PAYLOAD_TABLES allowlist.
                            f"SELECT COALESCE(SUM(LENGTH(payload)), 0) FROM {name}"  # nosec B608
                        ).fetchone()[0]
                        or 0
                    )
                tables[name] = entry
            if "meta" in names:
                row = connection.execute(
                    "SELECT value FROM meta WHERE key = 'last_maintenance'"
                ).fetchone()
                if row is not None:
                    try:
                        loaded = json.loads(row["value"])
                    except (TypeError, ValueError):
                        loaded = None
                    if isinstance(loaded, dict):
                        last_maintenance = loaded
    except sqlite3.Error as exc:
        logger.warning("Store inventory failed for %s: %s", path, exc)
    return tables, last_maintenance


def _windows() -> dict[str, Any]:
    return {
        "scans_days": settings.RETENTION_SCANS_DAYS,
        "link_sweeps_days": settings.RETENTION_LINK_SWEEPS_DAYS,
        "paper_days": settings.RETENTION_PAPER_DAYS,
        "paper_max_rows": settings.RETENTION_PAPER_MAX_ROWS,
        "bets": "never deleted; settled rows older than "
        f"{settings.RETENTION_BETS_ARCHIVE_DAYS} days are archived only",
        "logs_days": settings.RETENTION_LOG_DAYS,
    }


def retention_health(
    *,
    storage_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    log_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Sizes, row counts, budgets and the last run for ``/api/health``.

    This is a read-only view: it never creates a missing database and never
    writes a maintenance marker.
    """
    db_path = Path(storage_path or default_storage_path())
    ledger = Path(ledger_path or matcher.MAPPING_EVIDENCE_FILE)
    logs = Path(log_dir or settings.LOG_DIR)

    tables, last_maintenance = _table_inventory(db_path)
    paper_rows = int(tables.get("recorded_opportunities", {}).get("rows", 0)) + int(
        tables.get("paper_positions", {}).get("rows", 0)
    )
    bet_rows = int(tables.get("bets", {}).get("rows", 0))

    sqlite_bytes = _db_bytes(db_path)
    ledger_bytes = _file_bytes(ledger)
    logs_bytes = _log_bytes(logs)

    warnings: list[str] = []

    def budget(label: str, value: int, limit: int) -> dict[str, Any]:
        over = value > limit
        if over:
            warnings.append(f"{label} over budget: {value} > {limit}")
        return {"value": value, "budget": limit, "over_budget": over}

    sqlite_budget = budget("sqlite", sqlite_bytes, settings.SQLITE_SIZE_BUDGET_BYTES)
    paper_budget = budget("paper rows", paper_rows, settings.PAPER_ROWS_BUDGET)
    bet_budget = budget("bet rows", bet_rows, settings.BETS_ROWS_BUDGET)
    ledger_budget = budget(
        "mapping ledger", ledger_bytes, settings.MAPPING_LEDGER_BUDGET_BYTES
    )
    log_budget = budget("logs", logs_bytes, settings.LOG_SIZE_BUDGET_BYTES)

    return {
        "windows": _windows(),
        "sqlite": {
            "path": str(db_path),
            "bytes": sqlite_bytes,
            "budget_bytes": sqlite_budget["budget"],
            "over_budget": sqlite_budget["over_budget"],
        },
        "tables": tables,
        "paper": {
            "rows": paper_rows,
            "budget_rows": paper_budget["budget"],
            "over_budget": paper_budget["over_budget"],
        },
        "bets": {
            "rows": bet_rows,
            "budget_rows": bet_budget["budget"],
            "over_budget": bet_budget["over_budget"],
        },
        "mapping_evidence": {
            "path": str(ledger),
            "bytes": ledger_bytes,
            "budget_bytes": ledger_budget["budget"],
            "over_budget": ledger_budget["over_budget"],
        },
        "logs": {
            "dir": str(logs),
            "bytes": logs_bytes,
            "budget_bytes": log_budget["budget"],
            "over_budget": log_budget["over_budget"],
        },
        "last_maintenance": last_maintenance,
        "over_budget": bool(warnings),
        "warnings": warnings,
    }


def _prune_logs(
    log_dir: Path, *, days: int, now: datetime, dry_run: bool
) -> dict[str, Any]:
    cutoff = (now - timedelta(days=days)).timestamp()
    report: dict[str, Any] = {
        "dir": str(log_dir),
        "removed": 0,
        "bytes": 0,
        "skipped": "",
    }
    if not log_dir.is_dir():
        report["skipped"] = "log directory does not exist"
        return report
    for path in _log_paths(log_dir):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            continue
        report["removed"] += 1
        report["bytes"] += stat.st_size
        if not dry_run:
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not remove old log %s: %s", path, exc)
    return report


def _archive_bets(
    bets: BetStore,
    *,
    now: datetime,
    archive_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    cutoff = (
        now - timedelta(days=settings.RETENTION_BETS_ARCHIVE_DAYS)
    ).isoformat(timespec="seconds")
    rows = bets.settled_before(cutoff)
    report: dict[str, Any] = {
        "rows": len(rows),
        "path": None,
        "bytes": 0,
        "cutoff": cutoff,
    }
    if not rows:
        return report
    archive_path = archive_dir / f"bets-{now.date().isoformat()}.json"
    if dry_run:
        report["would_write"] = str(archive_path)
        return report
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "archived_at": iso_seconds(now),
        "cutoff": cutoff,
        "count": len(rows),
        "note": "Archive copy only; the bets remain in the SQLite store.",
        "bets": rows,
    }
    archive_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report["path"] = str(archive_path)
    report["bytes"] = _file_bytes(archive_path)
    return report


def _backup(
    *,
    storage_path: Path,
    ledger_path: Path,
    backup_dir: Path,
    now: datetime,
    dry_run: bool,
) -> dict[str, Any]:
    stamp = now.strftime("%Y%m%dT%H%M%S")
    db_target = backup_dir / f"bh_arb-{stamp}.sqlite3"
    ledger_target = backup_dir / f"mapping_evidence-{stamp}.json"
    report: dict[str, Any] = {
        "dir": str(backup_dir),
        "files": [],
        "bytes": 0,
    }
    if dry_run:
        report["would_write"] = [
            path
            for path, exists in (
                (str(db_target), storage_path.exists()),
                (str(ledger_target), ledger_path.exists()),
            )
            if exists
        ]
        return report
    backup_dir.mkdir(parents=True, exist_ok=True)
    if storage_path.exists():
        Storage(str(storage_path)).backup(str(db_target))
        report["files"].append(str(db_target))
        report["bytes"] += _file_bytes(db_target)
    if ledger_path.exists():
        shutil.copy2(ledger_path, ledger_target)
        report["files"].append(str(ledger_target))
        report["bytes"] += _file_bytes(ledger_target)
    return report


def run_maintenance(
    *,
    dry_run: bool = False,
    vacuum: bool = False,
    backup_dir: str | Path | None = None,
    now: datetime | None = None,
    storage_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
    log_dir: str | Path | None = None,
    archive_dir: str | Path | None = None,
    paper_store: PaperStore | None = None,
    bet_store: BetStore | None = None,
    scan_active: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Apply retention once and return a report.

    ``dry_run`` reads counts through read-only connections and writes nothing:
    no prune, no archive, no backup, no vacuum and no maintenance marker.
    ``scan_active`` is the caller's live scan check; when it returns true the
    job returns ``skipped`` without touching a store.
    """
    started = now or utcnow()
    if not _MAINTENANCE_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "skipped": "maintenance_already_running",
            "dry_run": dry_run,
            "started_at": iso_seconds(started),
        }
    _MAINTENANCE_ACTIVE.set()
    try:
        if scan_active is not None and scan_active():
            return {
                "ok": False,
                "skipped": "scan_in_progress",
                "dry_run": dry_run,
                "started_at": iso_seconds(started),
            }

        db_path = Path(storage_path or default_storage_path())
        ledger = Path(ledger_path or matcher.MAPPING_EVIDENCE_FILE)
        logs = Path(log_dir or settings.LOG_DIR)
        archives = Path(archive_dir or (Path(settings.CACHE_DIR) / "archives"))

        before = retention_health(
            storage_path=db_path, ledger_path=ledger, log_dir=logs
        )

        storage = Storage(str(db_path))
        paper = paper_store or PaperStore(str(db_path))
        bets = bet_store or BetStore(str(db_path))
        if not dry_run:
            storage.initialize()
            paper.initialize()
            bets.initialize()

        pruned = {
            "scans": storage.prune_scans(
                days=settings.RETENTION_SCANS_DAYS, dry_run=dry_run
            ),
            "link_sweeps": storage.prune_link_sweeps(
                days=settings.RETENTION_LINK_SWEEPS_DAYS, dry_run=dry_run
            ),
        }
        paper_pruned = paper.prune(
            days=settings.RETENTION_PAPER_DAYS,
            max_rows=settings.RETENTION_PAPER_MAX_ROWS,
            dry_run=dry_run,
        )
        bets_archive = _archive_bets(
            bets, now=started, archive_dir=archives, dry_run=dry_run
        )

        mapping = MappingLedger(str(ledger)).load()
        claims = len(mapping.claims)
        evidence_dropped = mapping.prune()
        mapping_saved = False
        if not dry_run and evidence_dropped:
            mapping.save()
            mapping_saved = True
        mapping_report = {
            "path": str(ledger),
            "claims": claims,
            "evidence_dropped": evidence_dropped,
            "saved": mapping_saved,
        }

        logs_report = _prune_logs(
            logs, days=settings.RETENTION_LOG_DAYS, now=started, dry_run=dry_run
        )

        vacuumed = False
        if vacuum and not dry_run:
            storage.vacuum()
            vacuumed = True

        backup_report = None
        if backup_dir is not None:
            backup_report = _backup(
                storage_path=db_path,
                ledger_path=ledger,
                backup_dir=Path(backup_dir),
                now=started,
                dry_run=dry_run,
            )

        finished = utcnow()
        after = retention_health(
            storage_path=db_path, ledger_path=ledger, log_dir=logs
        )
        report: dict[str, Any] = {
            "ok": True,
            "dry_run": dry_run,
            "started_at": iso_seconds(started),
            "finished_at": iso_seconds(finished),
            "windows": _windows(),
            "pruned": pruned,
            "paper": paper_pruned,
            "bets": bets_archive,
            "mapping_evidence": mapping_report,
            "logs": logs_report,
            "vacuumed": vacuumed,
            "backup": backup_report,
            "before": before,
            "after": after,
        }
        if not dry_run:
            record = {
                "finished_at": iso_seconds(finished),
                "dry_run": False,
                "pruned": pruned,
                "paper": paper_pruned,
                "bets_archived": bets_archive["rows"],
                "vacuumed": vacuumed,
            }
            storage.set_last_maintenance(record)
            report["last_maintenance"] = record
        return report
    finally:
        _MAINTENANCE_ACTIVE.clear()
        _MAINTENANCE_LOCK.release()
