# Soak and resource budget (P1-6)

The acceptance run is 24 hours of scheduled scans. **That run has not been
performed in this session.** Everything needed to perform and judge it is in
place, and a two-cycle smoke run is recorded below as partial evidence. The
roadmap keeps P1-6 `In progress` until the 24-hour run completes.

## What changed

`scripts/soak.py` now:

- treats `--cycles 0` (the default) as "scan until `--minutes`", so
  `--minutes 1440` no longer silently runs one scan and exits;
- records cache bytes and per-book feed states (`healthy`, `degraded`,
  `quarantined`) in every sample;
- fails if **any** sample has a live browser, not only the last one;
- fails if `pgrep` is unavailable instead of reporting zero browsers;
- fails if peak RSS exceeds `--rss-budget-mb` (default 1024) or RSS grows more
  than `--max-growth` (default 50%);
- reports `books_without_healthy`, the "silently absent for the whole run" case.

The scan path also queues soft alerts when the cache exceeds
`CACHE_SIZE_BUDGET_BYTES` or RSS exceeds `RSS_BUDGET_MB`. `/api/health` exposes
`memory.rss_mb`, `memory.budget_mb` and `memory.over_budget`.

## Twenty-four hour command

Run on the host that will host the scanner, against the real scheduled feed:

```bash
# Server: scheduled prematch scans every 10 minutes, live off.
AUTO_SCAN_PREMATCH_MINUTES=10 AUTO_SCAN_LIVE_MINUTES=0 \
  python main.py >/tmp/bh-arb-soak.log 2>&1 &
SERVER_PID=$!

python scripts/soak.py \
  --base-url http://127.0.0.1:8000 \
  --minutes 1440 \
  --interval 300 \
  --pid "$SERVER_PID" \
  --rss-budget-mb 1024 \
  --check \
  --out docs/evidence/2026-11-04-soak-24h.json
```

`--cycles` is deliberately omitted: zero means run until the 24-hour deadline.
Keep the server's own log; it carries per-book scrape errors the JSON summary
only counts.

Acceptance is met only when the report has `ok: true`, `browsers_max: 0`, a
peak RSS below the budget, and a plateau rather than a monotonic climb in
`rss_series`.

## Smoke run (2026-11-04, not acceptance)

Environment: Linux, Python 3.11.18, checkout at `3933ac4`, `HOST=127.0.0.1`,
`PORT=18080`, `AUTO_SCAN_PREMATCH_MINUTES=0`, `HEADLESS=true`. The server was
started from the existing runtime cache and scanned twice against the live
bookmaker feeds.

Command:

```bash
python scripts/soak.py --base-url http://127.0.0.1:18080 \
  --cycles 2 --interval 2 --pid <server-pid> \
  --rss-budget-mb 1024 --check --out /tmp/soak-smoke.json
```

| Sample (UTC) | Matches | Groups | Surebets | RSS | Browsers | Cache | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| 19:41:01 | 8,975 | 1,498 | 3 | 940.4 MB | 0 | 31.2 MB | 1 |
| 19:42:53 | 8,969 | 1,499 | 3 | 924.4 MB | 0 | 31.2 MB | 1 |

Result: `ok: true`, no problems, RSS change **-1.7%**, peak **940.4 MB** below
the 1024 MB budget, cache peak **31.2 MB** below the 40 MB budget, zero browser
processes at both samples. The raw report is
[`docs/evidence/2026-11-04-soak-smoke.json`](evidence/2026-11-04-soak-smoke.json).

Per-book feed states across the two samples:

- Healthy in both: `admiralbet`, `maxbet`, `mbet`, `mdshop`,
  `premier_kladionica`, `sportplus`, `wwin`.
- Degraded in both with `missing_markets`: `betole`, `mozzartbet`. They were
  named in the report and counted, not silently dropped.

This is a smoke test: 2 scans over 112 seconds cannot prove a day-long plateau.
The 940 MB sample is also above the older 767 MB ten-cycle plateau, which is
exactly why the 24-hour series is still required before calling P1-6 done.

The live scans also write learned aliases into the gitignored
`config/generated/mapping_evidence.json`. The full test suite is verified with a
clean ledger, as CI runs it; keep a copy of the learned ledger if those aliases
matter, and do not assume a populated runtime ledger is the test baseline.
