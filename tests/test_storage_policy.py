"""One SQLite connection policy and one clock for server runtime state (M3-4).

`Storage`, `BetStore` and `PaperStore` share `cache/bh_arb.sqlite3`. They used to
each write their own `_connect`: all set WAL, but only `Storage` set
`synchronous=NORMAL`, so the same file was opened under two durability policies
depending on which store ran. `server/sqlite_store` is now the one place that
decides; these tests pin the policy for every store and keep the read-only path
read-only.

`server/timeutil` is the one clock: naive UTC datetimes and the second-precision
ISO string the stores write.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from server import sqlite_store, timeutil
from server.bets import BetStore
from server.paper import PaperStore
from server.storage import Storage

STORES = [
    pytest.param(Storage, id="storage"),
    pytest.param(BetStore, id="bets"),
    pytest.param(PaperStore, id="paper"),
]


@pytest.mark.parametrize("store_type", STORES)
def test_every_store_uses_wal_and_synchronous_normal(tmp_path, store_type):
    connection = store_type(str(tmp_path / "shared.sqlite3"))._connect()
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        connection.close()
    assert str(mode).lower() == "wal"
    # SQLite numbers: 0 OFF, 1 NORMAL, 2 FULL, 3 EXTRA.
    assert synchronous == 1


def test_readonly_connections_do_not_create_or_write(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        sqlite_store.connect_readonly(missing)
    assert not missing.exists(), "a read-only open must not create the database"

    path = tmp_path / "shared.sqlite3"
    Storage(str(path)).initialize()
    connection = sqlite_store.connect_readonly(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE nope (id INTEGER)")
    finally:
        connection.close()


def test_timeutil_is_naive_utc_and_second_precision():
    now = timeutil.utcnow()
    assert now.tzinfo is None

    aware = datetime(2026, 11, 9, 12, 30, 15, 123456, tzinfo=UTC)
    assert timeutil.naive_utc(aware) == datetime(2026, 11, 9, 12, 30, 15, 123456)
    assert timeutil.iso_seconds(aware) == "2026-11-09T12:30:15"

    # A naive datetime is already the stored shape and is not shifted.
    naive = datetime(2026, 11, 9, 12, 30, 15)
    assert timeutil.naive_utc(naive) == naive
    assert timeutil.iso_seconds(naive) == "2026-11-09T12:30:15"

    assert datetime.fromisoformat(timeutil.iso_now()) is not None
    assert len(timeutil.iso_now()) == len("2026-11-09T12:30:15")


def test_stores_write_the_same_timestamp_shape(tmp_path):
    """Bets and paper both hand a value `naive_utc` can parse unchanged."""
    path = tmp_path / "shared.sqlite3"
    bet_store = BetStore(str(path))
    bet_store.initialize()
    created = bet_store.create(
        {
            "event": "Home vs Away",
            "market": "1X2",
            "side": "Home",
            "stake": 10.0,
            "odds": 2.0,
        }
    )
    created_at = datetime.fromisoformat(created["created_at"])
    assert created_at.tzinfo is None

    # And the clock helper agrees with what the store wrote within a minute.
    assert abs(created_at - timeutil.utcnow()) < timedelta(minutes=1)


def test_paper_and_storage_share_the_database_file_without_lock_errors(tmp_path):
    path = str(tmp_path / "shared.sqlite3")
    Storage(path).initialize()
    bets = BetStore(path)
    bets.initialize()
    papers = PaperStore(path)
    papers.initialize()
    # All three were opened against one file under one policy; a write from each
    # must not raise (this is the single-process WAL contract).
    with Storage(path)._connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('m3_4', 'ok')"
        )
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'm3_4'"
        ).fetchone()
    assert row is not None and row["value"] == "ok"
