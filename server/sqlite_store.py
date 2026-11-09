"""One SQLite connection policy for the runtime database.

`Storage`, `BetStore`, `PaperStore` and the maintenance runner all open
`cache/bh_arb.sqlite3`. They used to each spell out the connection: every one
set `journal_mode=WAL`, but only `Storage` also set `synchronous=NORMAL`, so the
same file was opened under two durability policies depending on which store
happened to run. This module is the one place that decides.

The policy is WAL with `synchronous=NORMAL` (docs/STORAGE.md): durable across an
application crash, not a power-loss guarantee, and the right trade for a single
scanner process whose data is reproducible from feeds. WAL mode persists in the
database file; `synchronous` is per connection, which is why setting it on one
store's connection did not cover the others.

Read-only connections deliberately do not touch WAL state or the pragmas: a dry
run must be able to count what it would prune without changing the file.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Busy timeout for every connection. A maintenance job holds its own handle
#: while the scanner appends history, so a lock is expected, not exceptional.
SQLITE_TIMEOUT_SECONDS = 30


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the shared database read-write under the one connection policy."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=SQLITE_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def connect_readonly(path: str | Path) -> sqlite3.Connection:
    """Open an existing database without creating, migrating or touching WAL."""
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=SQLITE_TIMEOUT_SECONDS)
    connection.row_factory = sqlite3.Row
    return connection
