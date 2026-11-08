# Live canary

`scripts/live_canary.py` is the SR4-9 canary. Offline fixtures and the replay
corpus cannot see a book change its site today, so once a day the operator host
runs every book once and writes a dated report.

**Decision (2026-11-08, operator):** this host, daily. It is not part of CI: a
failing canary never fails the main build. It never refreshes a fixture; the only
file it writes is the report under `cache/live_canary/` (or `--report-dir`).

## Running it

```bash
.venv/bin/python scripts/live_canary.py                 # every book, prematch
.venv/bin/python scripts/live_canary.py --live          # every book, live
.venv/bin/python scripts/live_canary.py --books mbet,mdshop
.venv/bin/python scripts/live_canary.py --strict        # exit 1 when a reason fires
```

Each book goes through its real adapter, so the shared transport policy applies:
per-book rate limit, retry budget, adapter deadline, no login, the same
user agent as the scanner. Books run one after another, never in parallel.

The default exit code is 0 even when a reason fires, so an installed timer does
not page on an ordinary feed gap. `--strict` returns 1 for a one-off shell run.

## Installing the daily run

Cron on the operator host, 06:17 local time:

```cron
17 6 * * * cd /home/nedim/BH_Arb && .venv/bin/python scripts/live_canary.py >> cache/live_canary/cron.log 2>&1
```

A systemd timer works the same way; the script is the whole job, no daemon.
The report directory is runtime state (`cache/` is gitignored), like the rest of
`cache/`.

## Report format

One JSON file per day, named `YYYY-MM-DD.json`:

```json
{
  "generated_at": "2026-11-09T06:17:04",
  "live": false,
  "alarms": 1,
  "previous": "2026-11-08T06:17:02",
  "books": [
    {
      "bookmaker": "mbet",
      "matches": 4,
      "markets": {"1x2": 8},
      "error": "",
      "duration_seconds": 12.4,
      "reasons": ["matches 20 -> 4", "1x2 40 -> 8"],
      "new_market_types": []
    }
  ]
}
```

`previous` is the `generated_at` of the newest other report in the directory,
`null` on the first run. A book that cannot be read says so in `error` and is a
reason, never an exception.

## What counts as a reason

The comparison is against the previous dated report, not an invented baseline:

| reason | when |
|---|---|
| `error: …` | the adapter raised, or the book has no registered scraper |
| `matches A -> B` | the book had at least 10 matches and now has less than half |
| `<market> A -> B` | a family had at least 5 markets and now has less than half |

A market family that appears for the first time is listed under
`new_market_types` and is **not** an alarm. Thresholds are `MIN_MATCHES` and
`MIN_MARKETS` in the script.

The raw-payload structural fingerprint is already checked inside every adapter
at its raw-JSON boundary (SR4-4); the canary's fingerprint is the set of market
families the parser emits plus their counts, which is the cross-run view of what
the book actually offers.

## Boundaries

- It never writes `tests/fixtures/`, a contract or `MARKET_MAPPING.md`.
- It never enables a disabled book and never logs in.
- One run is one request pass per book, at the scanner's rate; the daily cadence
  is the decision, not a licence to increase it.
