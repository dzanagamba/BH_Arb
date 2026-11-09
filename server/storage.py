"""SQLite storage v2 and JSON migration (P3-1).

Runtime state was a set of JSON files. This store moves the query-heavy parts
(scan history first, decision records as a mirror) into one transactional
database, with an explicit migration from the JSON files. The JSON files remain
compatibility exports: a rollback is "stop writing SQLite and keep the files".

The database is deliberately small: no ORM, no connection pool. SQLite's WAL
mode plus one short-lived connection per call is enough for one scanner process.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from server.sqlite_store import connect as _sqlite_connect
from server.sqlite_store import connect_readonly as _sqlite_connect_readonly
from server.timeutil import iso_now, utcnow

SCHEMA_VERSION = 1


class Storage:
    def __init__(self, path: str) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        return _sqlite_connect(self.path)

    def _connect_readonly(self) -> sqlite3.Connection:
        """Open without creating, migrating or touching WAL state.

        A dry run must be able to count what it *would* prune without changing
        the database file, so it never takes the write path above.
        """
        return _sqlite_connect_readonly(self.path)

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    scan_time TEXT NOT NULL,
                    total_matches INTEGER NOT NULL,
                    match_groups INTEGER NOT NULL,
                    surebets_found INTEGER NOT NULL,
                    per_bookie TEXT NOT NULL,
                    errors TEXT NOT NULL,
                    candidate_queue INTEGER NOT NULL DEFAULT 0,
                    candidate_actionable INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS scans_time ON scans(scan_time DESC);
                CREATE INDEX IF NOT EXISTS scans_mode_time ON scans(mode, scan_time DESC);
                CREATE TABLE IF NOT EXISTS decisions (
                    candidate_id TEXT PRIMARY KEY,
                    decision TEXT NOT NULL,
                    premise TEXT NOT NULL DEFAULT '',
                    decided_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS link_sweeps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bookmaker TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def _migrated(self, connection: sqlite3.Connection, key: str) -> bool:
        row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return bool(row and row["value"] == "1")

    def _mark_migrated(self, connection: sqlite3.Connection, key: str) -> None:
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, '1')", (key,)
        )

    def migrate_json(
        self,
        *,
        history_path: str,
        decisions_path: str,
    ) -> dict[str, int]:
        """Import the JSON stores once; return inserted row counts.

        The source files are never deleted. Re-running the migration is a no-op
        because each store is marked in `meta`.
        """
        counts = {"scans": 0, "decisions": 0}
        with self._connect() as connection:
            if not self._migrated(connection, "history_json"):
                try:
                    rows = json.loads(Path(history_path).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    rows = []
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            self._insert_scan(connection, row)
                            counts["scans"] += 1
                self._mark_migrated(connection, "history_json")

            if not self._migrated(connection, "decisions_json"):
                try:
                    data = json.loads(Path(decisions_path).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
                decisions = data.get("decisions") if isinstance(data, dict) else None
                premises = data.get("premises") if isinstance(data, dict) else None
                if not isinstance(decisions, dict):
                    decisions = data if isinstance(data, dict) else {}
                if not isinstance(premises, dict):
                    premises = {}
                for candidate_id, decision in decisions.items():
                    if isinstance(candidate_id, str) and decision in (
                        "approved",
                        "rejected",
                    ):
                        self._upsert_decision(
                            connection,
                            candidate_id,
                            decision,
                            str(premises.get(candidate_id, "")),
                        )
                        counts["decisions"] += 1
                self._mark_migrated(connection, "decisions_json")
        return counts

    def _insert_scan(self, connection: sqlite3.Connection, entry: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO scans(
                mode, scan_time, total_matches, match_groups, surebets_found,
                per_bookie, errors, candidate_queue, candidate_actionable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(entry.get("mode") or "prematch"),
                str(entry.get("scan_time") or datetime.now(UTC).isoformat()),
                int(entry.get("total_matches") or 0),
                int(entry.get("match_groups") or 0),
                int(entry.get("surebets_found") or 0),
                json.dumps(entry.get("per_bookie") or {}, sort_keys=True),
                json.dumps(entry.get("errors") or []),
                int(entry.get("candidate_queue") or 0),
                int(entry.get("candidate_actionable") or 0),
            ),
        )

    def append_scan(self, entry: dict[str, Any]) -> None:
        with self._connect() as connection:
            with connection:
                self._insert_scan(connection, entry)

    def list_scans(
        self,
        *,
        limit: int = 50,
        days: int | None = None,
        mode: str = "",
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM scans"
        clauses: list[str] = []
        params: list[Any] = []
        if days is not None:
            cutoff = utcnow() - timedelta(days=days)
            clauses.append("scan_time >= ?")
            params.append(cutoff.isoformat())
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY scan_time DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "mode": row["mode"],
                "scan_time": row["scan_time"],
                "total_matches": row["total_matches"],
                "match_groups": row["match_groups"],
                "surebets_found": row["surebets_found"],
                "per_bookie": json.loads(row["per_bookie"]),
                "errors": json.loads(row["errors"]),
                "candidate_queue": row["candidate_queue"],
                "candidate_actionable": row["candidate_actionable"],
            }
            for row in rows
        ]

    def _upsert_decision(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
        decision: str,
        premise: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO decisions(candidate_id, decision, premise, decided_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                decision = excluded.decision,
                premise = excluded.premise,
                decided_at = excluded.decided_at
            """,
            (
                candidate_id,
                decision,
                premise,
                iso_now(),
            ),
        )

    def upsert_decision(self, candidate_id: str, decision: str, premise: str = "") -> None:
        with self._connect() as connection:
            with connection:
                self._upsert_decision(connection, candidate_id, decision, premise)

    def decisions(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT candidate_id, decision FROM decisions").fetchall()
        return {row["candidate_id"]: row["decision"] for row in rows}

    def decision_premises(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT candidate_id, premise FROM decisions WHERE premise <> ''"
            ).fetchall()
        return {row["candidate_id"]: row["premise"] for row in rows}

    def append_link_sweep(self, report: dict[str, Any]) -> None:
        with self._connect() as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO link_sweeps(bookmaker, mode, ended_at, status, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(report.get("bookmaker") or ""),
                        str(report.get("mode") or "prematch"),
                        str(report.get("ended_at") or ""),
                        str(report.get("status") or ""),
                        json.dumps(report, sort_keys=True),
                    ),
                )

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM scans) AS scans, "
                "(SELECT COUNT(*) FROM decisions) AS decisions, "
                "(SELECT COUNT(*) FROM link_sweeps) AS link_sweeps"
            ).fetchone()
        return {
            "scans": int(row["scans"]),
            "decisions": int(row["decisions"]),
            "link_sweeps": int(row["link_sweeps"]),
        }

    def prune_scans(self, *, days: int = 90, dry_run: bool = False) -> int:
        """Delete scan rows older than ``days``; a dry run only counts them."""
        if not Path(self.path).exists():
            return 0
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        try:
            if dry_run:
                with self._connect_readonly() as connection:
                    row = connection.execute(
                        "SELECT COUNT(*) FROM scans WHERE scan_time < ?", (cutoff,)
                    ).fetchone()
                return int(row[0] or 0)
            with self._connect() as connection:
                with connection:
                    cursor = connection.execute(
                        "DELETE FROM scans WHERE scan_time < ?", (cutoff,)
                    )
                    return int(cursor.rowcount or 0)
        except sqlite3.Error:
            return 0

    def prune_link_sweeps(self, *, days: int = 90, dry_run: bool = False) -> int:
        """Delete link-sweep rows older than ``days``; a dry run only counts."""
        if not Path(self.path).exists():
            return 0
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        try:
            if dry_run:
                with self._connect_readonly() as connection:
                    row = connection.execute(
                        "SELECT COUNT(*) FROM link_sweeps WHERE ended_at < ?", (cutoff,)
                    ).fetchone()
                return int(row[0] or 0)
            with self._connect() as connection:
                with connection:
                    cursor = connection.execute(
                        "DELETE FROM link_sweeps WHERE ended_at < ?", (cutoff,)
                    )
                    return int(cursor.rowcount or 0)
        except sqlite3.Error:
            return 0

    def set_last_maintenance(self, payload: dict[str, Any]) -> None:
        """Record the newest successful maintenance run in ``meta``."""
        with self._connect() as connection:
            with connection:
                connection.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('last_maintenance', ?)",
                    (json.dumps(payload, sort_keys=True),),
                )

    def last_maintenance(self) -> dict[str, Any] | None:
        """Return the newest recorded maintenance report, if any."""
        if not Path(self.path).exists():
            return None
        try:
            with self._connect_readonly() as connection:
                row = connection.execute(
                    "SELECT value FROM meta WHERE key = 'last_maintenance'"
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            payload = json.loads(row["value"])
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def vacuum(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")

    def backup(self, target: str) -> None:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, sqlite3.connect(target) as destination:
            source.backup(destination)


def default_storage_path() -> str:
    return os.getenv(
        "STORAGE_PATH",
        str(Path(__file__).resolve().parent.parent / "cache" / "bh_arb.sqlite3"),
    )
