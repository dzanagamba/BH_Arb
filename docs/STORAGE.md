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

## Retention and maintenance (N1-1)

Every runtime store now has a configured window in `config/settings.py`:

| Store | Window | Behaviour |
|---|---|---|
| `scans` | `RETENTION_SCANS_DAYS` (90) | Rows older than the window are deleted. |
| `link_sweeps` | `RETENTION_LINK_SWEEPS_DAYS` (90) | Rows older than the window are deleted. |
| `recorded_opportunities` | `RETENTION_PAPER_DAYS` (180) | Old rows are deleted, then the newest `RETENTION_PAPER_MAX_ROWS` rows are kept. |
| `paper_positions` | `RETENTION_PAPER_DAYS` (180) | Same age and row-cap rule as recorded opportunities. |
| `bets` | never deleted | Settled rows older than `RETENTION_BETS_ARCHIVE_DAYS` (365) are copied to `cache/archives/bets-YYYY-MM-DD.json`; the database row stays. |
| mapping evidence | existing claim prune rule | `MappingLedger.prune()` keeps the strongest, newest evidence per claim. |
| generated logs | `RETENTION_LOG_DAYS` (30) | Only `*.log` / `*.log.*` files under `LOG_DIR` are removed; the default deployment logs to stdout. |

Run the job manually or from a daily task:

```bash
python scripts/maintenance.py --dry-run
python scripts/maintenance.py
python scripts/maintenance.py --vacuum --backup cache/backups
```

`--dry-run` reads through read-only SQLite connections and writes nothing: no
prune, archive, backup, vacuum or maintenance marker. The report is JSON with
the before/after counts, the rows pruned, the archive/backup paths and any budget
warnings.

The FastAPI lifespan starts `server.scheduler.maintenance_loop`, which waits
`MAINTENANCE_STARTUP_DELAY_SECONDS` (60), runs once, then repeats every
`MAINTENANCE_INTERVAL_HOURS` (24). Set `MAINTENANCE_ENABLED=false` to disable it.
The loop skips a tick while a feed is scanning. The runner also holds a
process-wide guard that makes `start_scan_if_idle` refuse a new scan, so a prune
or `VACUUM` cannot overlap a scan write.

`/api/health` exposes `retention`: SQLite bytes and table row/payload counts,
paper and bet row budgets, mapping-ledger bytes, log bytes, the configured
windows, the last maintenance time and a `warnings` list. Crossing a budget is a
warning; it never stops a scan.

## Backup and restore

```bash
# Consistent SQLite copy plus the generated ledger
python scripts/maintenance.py --backup cache/backups

# Restore into a stopped deployment
cp cache/backups/bh_arb-YYYYMMDDTHHMMSS.sqlite3 cache/bh_arb.sqlite3
cp cache/backups/mapping_evidence-YYYYMMDDTHHMMSS.json \
   config/generated/mapping_evidence.json
```

The SQLite copy is made with `sqlite3.Connection.backup`, not by copying a WAL
file mid-write. A restore drill is a row-count comparison: before restoring,
record `Storage.counts()`, the newest `scan_time` and the newest paper-position
id; after restoring, the same queries must return identical values. The test
suite performs this drill in `tests/test_maintenance.py`.

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
