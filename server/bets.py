"""Manual bet log, bankroll and closing-line value (P3-2).

The scanner never places a bet. This store records what the operator says was
actually accepted, and only then computes P/L and CLV. A partial acceptance or a
missing leg is representable because every leg stores its own accepted stake and
odds, separate from the scan's plan.

Storage is the P3-1 SQLite database; one `bets` row keeps the JSON payload and
the settled profit, so the API can query a date window without reading a large
file.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BANKROLL_START = 1000.0


class BetStore:
    def __init__(self, path: str, *, bankroll_start: float = BANKROLL_START) -> None:
        self.path = path
        self.bankroll_start = bankroll_start

    def _connect(self) -> sqlite3.Connection:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS bets (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    settled_at TEXT,
                    status TEXT NOT NULL,
                    profit REAL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bets_created ON bets(created_at DESC);
                """
            )

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        bet_id = str(uuid.uuid4())[:12]
        now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        stored = {
            **payload,
            "id": bet_id,
            "created_at": now,
            "settled_at": None,
            "status": "open",
            "profit": None,
        }
        with self._connect() as connection:
            with connection:
                connection.execute(
                    "INSERT INTO bets(id, created_at, status, profit, payload) VALUES (?, ?, 'open', NULL, ?)",
                    (bet_id, now, json.dumps(stored, sort_keys=True)),
                )
        return stored

    def _row(self, connection: sqlite3.Connection, bet_id: str) -> sqlite3.Row | None:
        return connection.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()

    def get(self, bet_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = self._row(connection, bet_id)
        return json.loads(row["payload"]) if row else None

    def list_bets(self, *, days: int = 30, limit: int = 200) -> list[dict[str, Any]]:
        cutoff = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM bets WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
                (cutoff, max(1, min(limit, 1000))),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def settle(self, bet_id: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Settle every leg and compute the realized profit.

        A leg's `result` is ``won``, ``lost`` or ``void``. A void leg returns its
        accepted stake; a missing result leaves the bet open. Accepted odds/stake
        are used when present, otherwise the planned values.
        """
        with self._connect() as connection:
            row = self._row(connection, bet_id)
            if row is None:
                return None
            payload = json.loads(row["payload"])
            by_label = {item.get("outcome_label"): item for item in results}
            legs = payload.get("legs") or []
            if not legs or any(leg.get("outcome_label") not in by_label for leg in legs):
                return payload
            payout = 0.0
            staked = 0.0
            for leg in legs:
                result = by_label[leg["outcome_label"]]
                stake = float(leg.get("accepted_stake") or leg.get("stake") or 0)
                odds = float(leg.get("accepted_odds") or leg.get("odds") or 0)
                staked += stake
                if result.get("result") == "won":
                    payout += stake * odds
                elif result.get("result") == "void":
                    payout += stake
                leg["result"] = result.get("result")
            profit = round(payout - staked, 2)
            now = datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
            payload.update(
                {
                    "status": "settled",
                    "settled_at": now,
                    "profit": profit,
                    "staked": round(staked, 2),
                    "payout": round(payout, 2),
                    "legs": legs,
                }
            )
            with connection:
                connection.execute(
                    "UPDATE bets SET status='settled', settled_at=?, profit=?, payload=? WHERE id=?",
                    (now, profit, json.dumps(payload, sort_keys=True), bet_id),
                )
        return payload

    def set_closing(self, bet_id: str, closing: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Record the closing price per leg without settling the bet."""
        with self._connect() as connection:
            row = self._row(connection, bet_id)
            if row is None:
                return None
            payload = json.loads(row["payload"])
            by_label = {item.get("outcome_label"): item for item in closing}
            for leg in payload.get("legs") or []:
                item = by_label.get(leg.get("outcome_label"))
                if item and item.get("closing_odds") is not None:
                    leg["closing_odds"] = float(item["closing_odds"])
            with connection:
                connection.execute(
                    "UPDATE bets SET payload=? WHERE id=?",
                    (json.dumps(payload, sort_keys=True), bet_id),
                )
        return payload

    def summary(self, *, days: int = 30) -> dict[str, Any]:
        bets = self.list_bets(days=days, limit=1000)
        settled = [bet for bet in bets if bet.get("status") == "settled"]
        staked = sum(float(bet.get("staked") or 0) for bet in settled)
        profit = sum(float(bet.get("profit") or 0) for bet in settled)
        clv_values: list[tuple[float, float]] = []
        for bet in bets:
            for leg in bet.get("legs") or []:
                accepted = leg.get("accepted_odds")
                closing = leg.get("closing_odds")
                if accepted and closing and float(closing) > 1.0:
                    clv_values.append(
                        (
                            float(leg.get("accepted_stake") or leg.get("stake") or 1),
                            float(accepted) / float(closing) - 1.0,
                        )
                    )
        clv_weight = sum(weight for weight, _ in clv_values)
        clv = (
            sum(weight * value for weight, value in clv_values) / clv_weight
            if clv_weight
            else None
        )
        return {
            "days": days,
            "bets": len(bets),
            "settled_bets": len(settled),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi": round(profit / staked, 4) if staked else None,
            "bankroll_start": self.bankroll_start,
            "bankroll": round(self.bankroll_start + profit, 2),
            "clv": round(clv, 4) if clv is not None else None,
            "clv_legs": len(clv_values),
            "denominators": {
                "staked": "settled bets only",
                "roi": "profit / settled stake",
                "clv": "accepted-stake weighted, legs with a closing price",
            },
        }

    def export_csv(self, *, days: int = 30) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(
            [
                "bet_id",
                "created_at",
                "status",
                "home_team",
                "away_team",
                "market_type",
                "bookmaker",
                "outcome_label",
                "odds",
                "accepted_odds",
                "stake",
                "accepted_stake",
                "closing_odds",
                "result",
            ]
        )
        for bet in self.list_bets(days=days, limit=1000):
            for leg in bet.get("legs") or []:
                writer.writerow(
                    [
                        bet.get("id", ""),
                        bet.get("created_at", ""),
                        bet.get("status", ""),
                        bet.get("home_team", ""),
                        bet.get("away_team", ""),
                        bet.get("market_type", ""),
                        leg.get("bookmaker", ""),
                        leg.get("outcome_label", ""),
                        leg.get("odds", ""),
                        leg.get("accepted_odds") or "",
                        leg.get("stake", ""),
                        leg.get("accepted_stake") or "",
                        leg.get("closing_odds") or "",
                        leg.get("result") or "",
                    ]
                )
        return buffer.getvalue()
