"""Record-only and paper-trading stores (P3-7).

The scanner never places a bet. These two modes make that explicit:

* **record-only** stores a compact snapshot of every verified opportunity a scan
  priced. It never writes a live surebet.
* **paper** does the same and keeps a virtual position per opportunity, marked
  against the next scan's available prices. A paper position can be settled by
  the operator, but nothing here touches a bookmaker.

A row is deliberately compact: event identity, market, line, timestamp, the
gate's verdict, and one leg per best price. The full scan cache stays where it
already is; this store is the queryable paper ledger.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config.settings import (
    BOOK_STAKE_LIMITS,
    PAPER_FILL_ENABLED,
    PAPER_FILL_PARTIAL_ENABLED,
    PAPER_FILL_PRICE_TOLERANCE,
)
from models.schemas import Surebet
from server.csv_export import csv_cell
from server.sqlite_store import connect as _sqlite_connect
from server.sqlite_store import connect_readonly as _sqlite_connect_readonly
from server.timeutil import iso_now, utcnow

PAPER_BANKROLL_START = 1000.0


def _write_csv_row(writer: Any, values: list[Any]) -> None:
    writer.writerow([csv_cell(cell) for cell in values])
PAPER_STAKE = 100.0
PAPER_DISCLAIMER = (
    "Paper simulation only. No bet was placed, no money moved, and no bookmaker "
    "account was used."
)


def opportunity_key(surebet: Surebet) -> str:
    """A stable key for one market instance of one event across scans."""
    line = next((stake.line for stake in surebet.stakes if stake.line), "")
    kickoff = surebet.kickoff.isoformat(timespec="minutes") if surebet.kickoff else ""
    return "|".join(
        (
            surebet.sport,
            surebet.home_team,
            surebet.away_team,
            surebet.league,
            kickoff,
            surebet.market_type.value,
            line,
        )
    )


def compact_opportunity(
    surebet: Surebet,
    *,
    feed_mode: str,
    run_mode: str,
    scan_time: datetime,
) -> dict[str, Any]:
    """One bounded, JSON-safe snapshot of a verified opportunity."""
    legs = [
        {
            "bookmaker": stake.bookmaker,
            "outcome_label": stake.outcome_label,
            "odds": float(stake.odds),
            "line": stake.line,
            "selection": stake.selection,
        }
        for stake in surebet.stakes
    ]
    best_stake = max(surebet.stakes, key=lambda stake: stake.odds) if surebet.stakes else None
    key = opportunity_key(surebet)
    scan_iso = scan_time.isoformat(timespec="seconds")
    digest = hashlib.sha256(
        f"{run_mode}|{feed_mode}|{scan_iso}|{key}".encode()
    ).hexdigest()[:16]
    return {
        "id": digest,
        "key": key,
        "recorded_at": scan_iso,
        "feed_mode": feed_mode,
        "run_mode": run_mode,
        "sport": surebet.sport,
        "home_team": surebet.home_team,
        "away_team": surebet.away_team,
        "league": surebet.league,
        "kickoff": kickoff_iso(surebet),
        "market_type": surebet.market_type.value,
        "line": next((stake.line for stake in surebet.stakes if stake.line), ""),
        "profit_percent": float(surebet.profit_percent),
        "total_margin": float(surebet.raw_margin or surebet.total_margin),
        "gate_verdict": "verified",
        "best_odds": float(best_stake.odds) if best_stake else None,
        "best_book": best_stake.bookmaker if best_stake else "",
        "legs": legs,
    }


def kickoff_iso(surebet: Surebet) -> str:
    return surebet.kickoff.isoformat() if surebet.kickoff else ""


def _simulated_entry(
    legs: list[dict[str, Any]], stake: float
) -> tuple[list[dict[str, Any]], float, float]:
    """Split a paper stake on the recorded odds and return its exact edge."""
    odds = [float(leg["odds"]) for leg in legs]
    margin = sum(1.0 / value for value in odds)
    staked_legs: list[dict[str, Any]] = []
    returns: list[float] = []
    for leg, value in zip(legs, odds, strict=True):
        leg_stake = round(stake * (1.0 / value) / margin, 2)
        staked_legs.append({**leg, "stake": leg_stake})
        returns.append(leg_stake * value)
    profit = round(min(returns) - stake, 2) if returns else 0.0
    return staked_legs, round(margin, 6), profit


def _mark_reason(matched: int, total: int) -> str:
    if total <= 0:
        return "no entry legs to mark"
    if matched == total:
        return ""
    if matched == 0:
        return "no entry leg is still quoted"
    return f"{total - matched} of {total} entry legs are no longer quoted"


def _fill_reason(fills: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for fill in fills:
        status = str(fill.get("status") or "")
        counts[status] = counts.get(status, 0) + 1
    parts = [
        f"{counts[status]} {status}"
        for status in ("rejected", "missing", "partial")
        if counts.get(status)
    ]
    return ", ".join(parts)


def _fill_complete(fills: list[dict[str, Any]]) -> bool:
    return bool(fills) and all(
        fill.get("status") in {"filled", "partial"} for fill in fills
    )


def _fill_worst_case(fills: list[dict[str, Any]]) -> float | None:
    """Worst outcome with the simulated filled stakes, or None with no fill."""
    total = sum(float(fill.get("filled_stake") or 0) for fill in fills)
    if total <= 0:
        return None
    payouts = [
        float(fill.get("filled_stake") or 0) * float(fill.get("entry_odds") or 0)
        for fill in fills
    ]
    return round(min(payouts) - total, 2)


class PaperStore:
    """SQLite ledger for recorded opportunities and paper positions."""

    def __init__(
        self,
        path: str,
        *,
        bankroll_start: float = PAPER_BANKROLL_START,
        default_stake: float = PAPER_STAKE,
        fill_enabled: bool = PAPER_FILL_ENABLED,
        price_tolerance: float = PAPER_FILL_PRICE_TOLERANCE,
        partial_enabled: bool = PAPER_FILL_PARTIAL_ENABLED,
        book_caps: dict[str, int] | None = None,
    ) -> None:
        self.path = path
        self.bankroll_start = bankroll_start
        self.default_stake = default_stake
        self.fill_enabled = fill_enabled
        self.price_tolerance = max(0.0, float(price_tolerance))
        self.partial_enabled = partial_enabled
        self.book_caps = dict(book_caps if book_caps is not None else BOOK_STAKE_LIMITS)

    def _connect(self) -> sqlite3.Connection:
        return _sqlite_connect(self.path)

    def _connect_readonly(self) -> sqlite3.Connection:
        return _sqlite_connect_readonly(self.path)

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS recorded_opportunities (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    feed_mode TEXT NOT NULL,
                    run_mode TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS recorded_key_time
                    ON recorded_opportunities(key, recorded_at DESC);
                CREATE INDEX IF NOT EXISTS recorded_time
                    ON recorded_opportunities(recorded_at DESC);

                CREATE TABLE IF NOT EXISTS paper_positions (
                    id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    settled_at TEXT,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS paper_status_time
                    ON paper_positions(status, opened_at DESC);
                CREATE INDEX IF NOT EXISTS paper_key
                    ON paper_positions(key, status);
                """
            )

    def record_opportunities(
        self,
        surebets: list[Surebet],
        *,
        feed_mode: str,
        run_mode: str,
        scan_time: datetime,
    ) -> list[dict[str, Any]]:
        """Store one compact row per verified opportunity from the scan."""
        records = [
            compact_opportunity(
                surebet,
                feed_mode=feed_mode,
                run_mode=run_mode,
                scan_time=scan_time,
            )
            for surebet in surebets
        ]
        with self._connect() as connection:
            with connection:
                for record in records:
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO recorded_opportunities(
                            id, key, recorded_at, feed_mode, run_mode, payload
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record["id"],
                            record["key"],
                            record["recorded_at"],
                            record["feed_mode"],
                            record["run_mode"],
                            json.dumps(record, sort_keys=True),
                        ),
                    )
        return records

    def list_opportunities(
        self,
        *,
        days: int = 30,
        limit: int = 200,
        run_mode: str = "",
        feed_mode: str = "",
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        query = "SELECT payload FROM recorded_opportunities WHERE recorded_at >= ?"
        params: list[Any] = [cutoff]
        if run_mode:
            query += " AND run_mode = ?"
            params.append(run_mode)
        if feed_mode:
            query += " AND feed_mode = ?"
            params.append(feed_mode)
        query += " ORDER BY recorded_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(limit, 5000)), max(0, offset)])
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def count_opportunities(
        self, *, days: int = 30, run_mode: str = "", feed_mode: str = ""
    ) -> int:
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        query = "SELECT COUNT(*) FROM recorded_opportunities WHERE recorded_at >= ?"
        params: list[Any] = [cutoff]
        if run_mode:
            query += " AND run_mode = ?"
            params.append(run_mode)
        if feed_mode:
            query += " AND feed_mode = ?"
            params.append(feed_mode)
        with self._connect() as connection:
            return int(connection.execute(query, params).fetchone()[0])

    def open_positions_from_scan(
        self,
        records: list[dict[str, Any]],
        *,
        scan_time: datetime,
        stake: float | None = None,
    ) -> dict[str, int]:
        """Open one paper position per new key and mark every existing one.

        Opening uses the recorded odds. Marking compares the entry legs with the
        same key's current record, so a leg that disappeared makes the position
        not available rather than silently rewriting its entry price.
        """
        paper_stake = float(stake or self.default_stake)
        now = scan_time.isoformat(timespec="seconds")
        current = {record["key"]: record for record in records}
        opened = marked = disappeared = 0
        with self._connect() as connection:
            with connection:
                for record in records:
                    row = connection.execute(
                        """
                        SELECT id, payload FROM paper_positions
                        WHERE key = ? AND status = 'open'
                        ORDER BY opened_at DESC LIMIT 1
                        """,
                        (record["key"],),
                    ).fetchone()
                    if row is None:
                        position = self._new_position(record, paper_stake, now)
                        connection.execute(
                            """
                            INSERT INTO paper_positions(
                                id, opportunity_id, key, opened_at, status, payload
                            ) VALUES (?, ?, ?, ?, 'open', ?)
                            """,
                            (
                                position["id"],
                                position["opportunity_id"],
                                position["key"],
                                position["opened_at"],
                                json.dumps(position, sort_keys=True),
                            ),
                        )
                        opened += 1
                        continue
                    payload = json.loads(row["payload"])
                    payload = self._mark_position(payload, record, now)
                    connection.execute(
                        "UPDATE paper_positions SET payload = ? WHERE id = ?",
                        (json.dumps(payload, sort_keys=True), payload["id"]),
                    )
                    marked += 1

                rows = connection.execute(
                    "SELECT id, key, payload FROM paper_positions WHERE status = 'open'"
                ).fetchall()
                for row in rows:
                    if row["key"] in current:
                        continue
                    payload = json.loads(row["payload"])
                    if (payload.get("mark") or {}).get("disappeared_at"):
                        continue
                    entry_legs = payload.get("entry_legs") or []
                    fills: list[dict[str, Any]] = [
                        {
                            "bookmaker": str(leg.get("bookmaker") or ""),
                            "outcome_label": str(leg.get("outcome_label") or ""),
                            "status": "missing",
                            "planned_stake": round(float(leg.get("stake") or 0), 2),
                            "filled_stake": 0.0,
                            "entry_odds": float(leg.get("odds") or 0),
                            "current_odds": None,
                            "reason": "opportunity disappeared from the next scan",
                        }
                        for leg in entry_legs
                    ]
                    payload["mark"] = {
                        "marked_at": now,
                        "available": False,
                        "matched_legs": 0,
                        "total_legs": len(entry_legs),
                        "clv": None,
                        "current": [],
                        "disappeared_at": now,
                        "reason": "opportunity disappeared from the next scan",
                        "fills": fills,
                        "fill_complete": False,
                        "planned_stake": round(
                            sum(fill["planned_stake"] for fill in fills), 2
                        ),
                        "filled_stake": 0.0,
                        "worst_case_profit": None,
                    }
                    connection.execute(
                        "UPDATE paper_positions SET payload = ? WHERE id = ?",
                        (json.dumps(payload, sort_keys=True), row["id"]),
                    )
                    disappeared += 1
        return {"opened": opened, "marked": marked, "disappeared": disappeared}

    def _new_position(
        self, record: dict[str, Any], stake: float, now: str
    ) -> dict[str, Any]:
        entry_legs, margin, simulated_profit = _simulated_entry(record["legs"], stake)
        position_id = hashlib.sha256(
            f"{record['id']}|{now}|paper".encode()
        ).hexdigest()[:16]
        return {
            "id": position_id,
            "opportunity_id": record["id"],
            "key": record["key"],
            "feed_mode": record["feed_mode"],
            "home_team": record["home_team"],
            "away_team": record["away_team"],
            "league": record["league"],
            "market_type": record["market_type"],
            "line": record.get("line", ""),
            "kickoff": record.get("kickoff", ""),
            "opened_at": now,
            "settled_at": None,
            "status": "open",
            "stake": round(stake, 2),
            "entry_margin": margin,
            "simulated_profit": simulated_profit,
            "simulated_roi": round(simulated_profit / stake, 4) if stake else None,
            "entry_legs": entry_legs,
            "mark": None,
            "realized_profit": None,
            "disclaimer": PAPER_DISCLAIMER,
        }

    def _mark_position(
        self,
        payload: dict[str, Any],
        record: dict[str, Any],
        now: str,
    ) -> dict[str, Any]:
        entry_legs = payload.get("entry_legs") or []
        current = {
            (leg["bookmaker"], leg["outcome_label"]): leg
            for leg in record.get("legs") or []
        }
        matched: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        weighted = 0.0
        weight = 0.0
        for leg in entry_legs:
            bookmaker = str(leg.get("bookmaker") or "")
            label = str(leg.get("outcome_label") or "")
            entry_odds = float(leg.get("odds") or 0)
            planned_stake = float(leg.get("stake") or 0)
            now_leg = current.get((bookmaker, label))
            current_odds = (
                float(now_leg.get("odds") or 0) if now_leg is not None else None
            )
            if current_odds is None or current_odds <= 1.0:
                fills.append(
                    {
                        "bookmaker": bookmaker,
                        "outcome_label": label,
                        "status": "missing",
                        "planned_stake": round(planned_stake, 2),
                        "filled_stake": 0.0,
                        "entry_odds": entry_odds,
                        "current_odds": None,
                        "reason": "no current price",
                    }
                )
                continue

            clv = entry_odds / current_odds - 1.0
            matched.append(
                {
                    "bookmaker": bookmaker,
                    "outcome_label": label,
                    "entry_odds": entry_odds,
                    "current_odds": current_odds,
                    "clv": round(clv, 6),
                }
            )
            weight_leg = planned_stake
            weighted += weight_leg * clv
            weight += weight_leg

            move = abs(current_odds - entry_odds) / entry_odds if entry_odds else 0.0
            cap = self.book_caps.get(bookmaker)
            if self.fill_enabled and move > self.price_tolerance:
                status = "rejected"
                filled_stake = 0.0
                reason = f"price moved from {entry_odds:g} to {current_odds:g}"
            elif (
                self.fill_enabled
                and self.partial_enabled
                and cap is not None
                and planned_stake > float(cap)
            ):
                status = "partial"
                filled_stake = float(cap)
                reason = f"book cap {float(cap):g} KM"
            else:
                status = "filled"
                filled_stake = planned_stake
                reason = ""
            fills.append(
                {
                    "bookmaker": bookmaker,
                    "outcome_label": label,
                    "status": status,
                    "planned_stake": round(planned_stake, 2),
                    "filled_stake": round(filled_stake, 2),
                    "entry_odds": entry_odds,
                    "current_odds": current_odds,
                    "reason": reason,
                }
            )

        fill_reason = _fill_reason(fills)
        payload["mark"] = {
            "marked_at": now,
            "available": len(matched) == len(entry_legs) and bool(entry_legs),
            "matched_legs": len(matched),
            "total_legs": len(entry_legs),
            "clv": round(weighted / weight, 6) if weight else None,
            "current": matched,
            "disappeared_at": None,
            "reason": _mark_reason(len(matched), len(entry_legs)) or fill_reason,
            "fills": fills,
            "fill_complete": _fill_complete(fills),
            "planned_stake": round(
                sum(float(fill.get("planned_stake") or 0) for fill in fills), 2
            ),
            "filled_stake": round(
                sum(float(fill.get("filled_stake") or 0) for fill in fills), 2
            ),
            "worst_case_profit": _fill_worst_case(fills),
        }
        return payload

    def list_positions(
        self,
        *,
        days: int = 30,
        limit: int = 200,
        status: str = "",
        feed_mode: str = "",
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        query = "SELECT payload FROM paper_positions WHERE opened_at >= ?"
        params: list[Any] = [cutoff]
        if status:
            query += " AND status = ?"
            params.append(status)
        if feed_mode:
            query += " AND json_extract(payload, '$.feed_mode') = ?"
            params.append(feed_mode)
        query += " ORDER BY opened_at DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(limit, 5000)), max(0, offset)])
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def count_positions(
        self, *, days: int = 30, status: str = "", feed_mode: str = ""
    ) -> int:
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        query = "SELECT COUNT(*) FROM paper_positions WHERE opened_at >= ?"
        params: list[Any] = [cutoff]
        if status:
            query += " AND status = ?"
            params.append(status)
        if feed_mode:
            query += " AND json_extract(payload, '$.feed_mode') = ?"
            params.append(feed_mode)
        with self._connect() as connection:
            return int(connection.execute(query, params).fetchone()[0])

    def export_csv(
        self,
        *,
        days: int = 30,
        run_mode: str = "",
        feed_mode: str = "",
        status: str = "",
    ) -> str:
        """One CSV covering both paper stores; every displayed row round-trips."""
        opportunities = self.list_opportunities(
            days=days,
            limit=5000,
            run_mode=run_mode,
            feed_mode=feed_mode,
        )
        positions = self.list_positions(
            days=days,
            limit=5000,
            status=status,
            feed_mode=feed_mode,
        )
        columns = [
            "kind",
            "id",
            "key",
            "recorded_at",
            "opened_at",
            "settled_at",
            "status",
            "feed_mode",
            "run_mode",
            "sport",
            "home_team",
            "away_team",
            "league",
            "kickoff",
            "market_type",
            "line",
            "profit_percent",
            "total_margin",
            "gate_verdict",
            "best_odds",
            "best_book",
            "stake",
            "entry_margin",
            "simulated_profit",
            "simulated_roi",
            "realized_profit",
            "mark_available",
            "mark_matched_legs",
            "mark_total_legs",
            "mark_clv",
            "mark_reason",
            "fill_complete",
            "planned_stake",
            "filled_stake",
            "worst_case_profit",
            "fills_json",
            "legs_json",
            "disclaimer",
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        for row in opportunities:
            _write_csv_row(
                writer,
                [
                    "opportunity",
                    row.get("id", ""),
                    row.get("key", ""),
                    row.get("recorded_at", ""),
                    "",
                    "",
                    "recorded",
                    row.get("feed_mode", ""),
                    row.get("run_mode", ""),
                    row.get("sport", ""),
                    row.get("home_team", ""),
                    row.get("away_team", ""),
                    row.get("league", ""),
                    row.get("kickoff", ""),
                    row.get("market_type", ""),
                    row.get("line", ""),
                    row.get("profit_percent", ""),
                    row.get("total_margin", ""),
                    row.get("gate_verdict", ""),
                    row.get("best_odds", ""),
                    row.get("best_book", ""),
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    json.dumps(row.get("legs") or [], sort_keys=True),
                    row.get("disclaimer", ""),
                ],
            )
        for row in positions:
            mark = row.get("mark") or {}
            _write_csv_row(
                writer,
                [
                    "position",
                    row.get("id", ""),
                    row.get("key", ""),
                    "",
                    row.get("opened_at", ""),
                    row.get("settled_at") or "",
                    row.get("status", ""),
                    row.get("feed_mode", ""),
                    "",
                    "",
                    row.get("home_team", ""),
                    row.get("away_team", ""),
                    row.get("league", ""),
                    row.get("kickoff", ""),
                    row.get("market_type", ""),
                    row.get("line", ""),
                    "",
                    "",
                    "",
                    "",
                    "",
                    row.get("stake", ""),
                    row.get("entry_margin", ""),
                    row.get("simulated_profit", ""),
                    row.get("simulated_roi", ""),
                    row.get("realized_profit", ""),
                    mark.get("available", ""),
                    mark.get("matched_legs", ""),
                    mark.get("total_legs", ""),
                    mark.get("clv", ""),
                    mark.get("reason", ""),
                    mark.get("fill_complete", ""),
                    mark.get("planned_stake", ""),
                    mark.get("filled_stake", ""),
                    mark.get("worst_case_profit", ""),
                    json.dumps(mark.get("fills") or [], sort_keys=True),
                    json.dumps(row.get("entry_legs") or [], sort_keys=True),
                    row.get("disclaimer", ""),
                ],
            )
        return buffer.getvalue()

    def prune(
        self,
        *,
        days: int = 180,
        max_rows: int = 200000,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Bound the paper ledger by age and then by newest-row cap.

        A dry run counts what would be removed and never opens the database for
        writing. Open positions are not special: a position older than the
        window is no longer a usable paper record.
        """
        result = {
            "recorded_opportunities": 0,
            "paper_positions": 0,
            "recorded_opportunities_over_cap": 0,
            "paper_positions_over_cap": 0,
        }
        if not Path(self.path).exists():
            return result
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        cap = max(0, int(max_rows))
        try:
            if dry_run:
                with self._connect_readonly() as connection:
                    result["recorded_opportunities"] = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM recorded_opportunities WHERE recorded_at < ?",
                            (cutoff,),
                        ).fetchone()[0]
                    )
                    result["paper_positions"] = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM paper_positions WHERE opened_at < ?",
                            (cutoff,),
                        ).fetchone()[0]
                    )
                    if cap:
                        remaining = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM recorded_opportunities WHERE recorded_at >= ?",
                                (cutoff,),
                            ).fetchone()[0]
                        )
                        result["recorded_opportunities_over_cap"] = max(0, remaining - cap)
                        remaining = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM paper_positions WHERE opened_at >= ?",
                                (cutoff,),
                            ).fetchone()[0]
                        )
                        result["paper_positions_over_cap"] = max(0, remaining - cap)
                return result

            with self._connect() as connection:
                with connection:
                    result["recorded_opportunities"] = int(
                        connection.execute(
                            "DELETE FROM recorded_opportunities WHERE recorded_at < ?",
                            (cutoff,),
                        ).rowcount
                        or 0
                    )
                    result["paper_positions"] = int(
                        connection.execute(
                            "DELETE FROM paper_positions WHERE opened_at < ?",
                            (cutoff,),
                        ).rowcount
                        or 0
                    )
                    if cap:
                        before = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM recorded_opportunities"
                            ).fetchone()[0]
                        )
                        connection.execute(
                            """
                            DELETE FROM recorded_opportunities
                            WHERE id NOT IN (
                                SELECT id FROM recorded_opportunities
                                ORDER BY recorded_at DESC LIMIT ?
                            )
                            """,
                            (cap,),
                        )
                        after = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM recorded_opportunities"
                            ).fetchone()[0]
                        )
                        result["recorded_opportunities_over_cap"] = max(0, before - after)

                        before = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM paper_positions"
                            ).fetchone()[0]
                        )
                        connection.execute(
                            """
                            DELETE FROM paper_positions
                            WHERE id NOT IN (
                                SELECT id FROM paper_positions
                                ORDER BY opened_at DESC LIMIT ?
                            )
                            """,
                            (cap,),
                        )
                        after = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM paper_positions"
                            ).fetchone()[0]
                        )
                        result["paper_positions_over_cap"] = max(0, before - after)
        except sqlite3.Error:
            return result
        return result

    def settle(
        self, position_id: str, results: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """Settle a paper position from operator-entered leg results.

        Nothing is inferred from a match outcome feed: a missing result leaves
        the position open. A void leg returns its paper stake.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM paper_positions WHERE id = ?", (position_id,)
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload"])
            by_label = {item.get("outcome_label"): item for item in results}
            legs = payload.get("entry_legs") or []
            if not legs or any(leg.get("outcome_label") not in by_label for leg in legs):
                return payload
            mark = payload.get("mark") or {}
            fills: dict[str, dict[str, Any]] = {}
            for fill in mark.get("fills") or []:
                if isinstance(fill, dict):
                    fills[str(fill.get("outcome_label"))] = fill
            payout = 0.0
            staked = 0.0
            for leg in legs:
                result = by_label[leg["outcome_label"]]
                fill = fills.get(leg["outcome_label"])
                raw_stake = (
                    fill.get("filled_stake") if fill is not None else leg.get("stake")
                )
                stake = float(raw_stake or 0)
                odds = float(leg.get("odds") or 0)
                staked += stake
                if result.get("result") == "won":
                    payout += stake * odds
                elif result.get("result") == "void":
                    payout += stake
                leg["result"] = result.get("result")
            profit = round(payout - staked, 2)
            now = iso_now()
            payload.update(
                {
                    "status": "settled",
                    "settled_at": now,
                    "staked": round(staked, 2),
                    "payout": round(payout, 2),
                    "realized_profit": profit,
                    "settled_fill_complete": mark.get("fill_complete"),
                    "entry_legs": legs,
                }
            )
            with connection:
                connection.execute(
                    """
                    UPDATE paper_positions
                    SET status = 'settled', settled_at = ?, payload = ?
                    WHERE id = ?
                    """,
                    (now, json.dumps(payload, sort_keys=True), position_id),
                )
        return payload

    def summary(self, *, days: int = 30) -> dict[str, Any]:
        opportunities = self.list_opportunities(days=days, limit=5000)
        positions = self.list_positions(days=days, limit=5000)
        settled = [position for position in positions if position.get("status") == "settled"]
        open_positions = [position for position in positions if position.get("status") == "open"]
        staked = sum(float(position.get("staked") or 0) for position in settled)
        profit = sum(float(position.get("realized_profit") or 0) for position in settled)
        open_stake = sum(float(position.get("stake") or 0) for position in open_positions)
        open_profit = sum(
            float(position.get("simulated_profit") or 0) for position in open_positions
        )
        marked = [position for position in positions if position.get("mark")]
        available = [
            position for position in marked if position["mark"].get("available") is True
        ]
        execution_positions = [
            position
            for position in open_positions
            if (position.get("mark") or {}).get("fill_complete") is True
        ]
        execution_stake = sum(
            float((position.get("mark") or {}).get("filled_stake") or 0)
            for position in execution_positions
        )
        execution_worst = sum(
            float((position.get("mark") or {}).get("worst_case_profit") or 0)
            for position in execution_positions
        )
        incomplete_positions = [
            position
            for position in open_positions
            if position.get("mark") and not (position.get("mark") or {}).get("fill_complete")
        ]
        unmarked_positions = [
            position for position in open_positions if not position.get("mark")
        ]
        clv_values = [
            (float(position.get("stake") or 0), float(position["mark"]["clv"]))
            for position in marked
            if position["mark"].get("clv") is not None
        ]
        clv_weight = sum(weight for weight, _ in clv_values)
        return {
            "days": days,
            "run_mode": "paper",
            "no_bet_placed": True,
            "opportunities_recorded": len(opportunities),
            "positions": len(positions),
            "open_positions": len(open_positions),
            "settled_positions": len(settled),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi": round(profit / staked, 4) if staked else None,
            "bankroll_start": self.bankroll_start,
            "bankroll": round(self.bankroll_start + profit, 2),
            "simulated_open": {
                "positions": len(open_positions),
                "stake": round(open_stake, 2),
                "profit_if_all_filled": round(open_profit, 2),
                "roi_if_all_filled": (
                    round(open_profit / open_stake, 4) if open_stake else None
                ),
                "label": "optimistic: every leg fills at the recorded entry odds",
                "denominator": "open paper positions in the window",
            },
            "execution_adjusted": {
                "positions": len(execution_positions),
                "filled_stake": round(execution_stake, 2),
                "worst_case_profit": (
                    round(execution_worst, 2) if execution_positions else None
                ),
                "roi": (
                    round(execution_worst / execution_stake, 4)
                    if execution_stake
                    else None
                ),
                "incomplete_positions": len(incomplete_positions),
                "unmarked_positions": len(unmarked_positions),
                "label": "execution-adjusted worst case at the simulated fills",
                "denominator": (
                    "open positions with every leg filled or partially filled"
                ),
            },
            "fill_rules": {
                "enabled": self.fill_enabled,
                "price_tolerance": self.price_tolerance,
                "partial_enabled": self.partial_enabled,
            },
            "hit_rate": round(len(available) / len(marked), 4) if marked else None,
            "hit_rate_positions": len(marked),
            "clv": round(sum(weight * value for weight, value in clv_values) / clv_weight, 6)
            if clv_weight
            else None,
            "clv_legs": sum(
                len(position["mark"].get("current") or []) for position in marked
            ),
            "denominators": {
                "roi": "settled paper positions only",
                "hit_rate": "marked positions whose entry legs were all still quoted",
                "clv": "entry stake weighted, legs with a next-scan price",
                "simulated_open": "open positions at their entry odds, if every leg filled",
                "execution_adjusted": (
                    "open positions with every leg filled or partially filled"
                ),
            },
            "disclaimer": PAPER_DISCLAIMER,
        }
