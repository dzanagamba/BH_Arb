# SQLite storage v2 (P3-1)

Runtime state used to be a set of JSON files. `cache/bh_arb.sqlite3` is now the
query store for scan history and the decision mirror; the JSON files remain
compatibility exports and the rollback path.

## Schema

| Table | Purpose |
|---|---|
| `meta` | Schema version and one-shot migration markers. |
| `scans` | One row per completed scan: mode, time, matches, groups, surebets, per-book counts, errors, candidate queue/actionable counts. Indexed by `scan_time` and `(mode, scan_time)`. |
| `decisions` | Candidate id, decision, premise, decided time. |
| `link_sweeps` | Completed sweep reports (payload JSON) for later history queries. |

SQLite runs in WAL mode with `synchronous=NORMAL`. Each call uses a short-lived
connection; a scan's history append is one transaction.

## Migration

On startup `_load_history()` creates the database and calls
`Storage.migrate_json()` once:

1. `cache/scan_history.json` → `scans`;
2. `cache/suppressed_candidates.json` → `decisions`.

Migration is idempotent: each source is marked in `meta`. Source files are
**never deleted**. A count check is in `tests/test_storage_migration.py`:
inserted rows must equal the JSON source counts.

## Query

`GET /api/history?days=30` reads the SQLite window, optionally filtered by
`mode`; no large JSON file is loaded. `days=0` returns the in-memory recent
list. The dashboard's History tab still uses the default 30-day query.

## Retention and vacuum

`Storage.prune_scans(days=90)` deletes rows older than the window;
`Storage.vacuum()` checkpoints WAL and vacuums. Call them from an operator
script or a future scheduler; the default inspectable history is 50 rows in the
API, with the database keeping the longer window.

## Backup and restore

```bash
# Consistent SQLite copy (do not copy a WAL file mid-write)
python - <<'PY'
from server.storage import Storage, default_storage_path
Storage(default_storage_path()).backup("cache/bh_arb-backup.sqlite3")
PY

# Restore into a stopped deployment
cp cache/bh_arb-backup.sqlite3 cache/bh_arb.sqlite3
```

The JSON exports (`cache/scan_history.json`,
`cache/suppressed_candidates.json`) are still written and can be used for a
manual comparison.

## Rollback

Stop the scanner, keep the SQLite file for audit, and start the previous build.
The JSON exports are still valid; the old code reads them. No migration flag is
reversed, and the old build ignores the database.

## Concurrency

One scanner process is assumed, as in the rest of this project. WAL covers a
reader (health/dashboard) during a write. Do not run two writers against the
same database file.
