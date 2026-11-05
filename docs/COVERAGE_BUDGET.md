# Silent-drop coverage budget

P2-9. The pairing audit asks "did we miss a pair?"; this budget asks "did we
miss a whole feed?".

Every completed scan records the count of market rows per
`bookmaker|sport|market`. A rolling median of the last 20 scans is the baseline.
A key is flagged only when peer books still populate the same sport/market:

| Flag | Condition |
|---|---|
| `silent_zero` | baseline >= 3 rows, current is 0, and at least one peer book has the same sport/market |
| `material_drop` | baseline >= 3 rows, current < 50% of baseline, the gap is at least 5 rows, and a peer is populated |

A night with no live games is legitimately empty: if every peer is also zero,
nothing is flagged. A key with fewer than 3 baseline rows is not judged.

## Exposure

`/api/health` returns `coverage_budget` per feed:

```json
{
  "flags": [{"bookmaker": "mbet", "sport": "football", "market": "btts",
             "kind": "silent_zero", "observed": 0, "baseline": 41.0,
             "peers_populated": true}],
  "flag_count": 1,
  "baseline_scans": 12,
  "min_baseline_rows": 3,
  "drop_ratio": 0.5,
  "drop_absolute": 5,
  "counts": {"mbet|football|btts": 0}
}
```

The dashboard health line adds `Coverage N flag(s)` and puts each flag in the
line's tooltip. The state is persisted to `cache/coverage_budget.json` so a
restart keeps the rolling baseline; the file is gitignored runtime state.

## Mapping coverage (N1-2)

The coverage budget asks whether a whole feed vanished. Mapping coverage asks
whether the rows that did arrive resolved to a known market. For one scan:

```
numerator   = market rows that resolved to a registry mapping
denominator = numerator + newly unmapped market rows in that scan
coverage    = numerator / denominator
```

`unmapped_markets` is a process-wide cumulative counter, so the per-scan
numerator uses the positive delta between the before/after snapshots. A row
counted twice in the same scan is counted twice, exactly as the parser saw it.
A small scan is not judged until `denominator >= MAPPING_COVERAGE_MIN_ROWS`; an
empty feed has no ratio (not zero) and cannot alert.

`/api/health.mapping_coverage.<mode>` reports the aggregate and every book:

```json
{
  "numerator": 1840,
  "denominator": 1900,
  "unmapped_total": 60,
  "coverage": 0.9684,
  "floor": 0.95,
  "min_rows": 20,
  "below_floor": false,
  "per_book": {
    "mbet": {"mapped": 400, "unmapped": 60, "total": 460,
             "coverage": 0.8696, "below_floor": true}
  }
}
```

A below-floor ratio is a warning, not a trust rule. No group is dropped or
merged because mapping coverage fell.

## Repeated zero results (N1-2)

`opportunity_metrics.zero_result_reason` already names why a scan priced
nothing. The two watched reasons are `stale_data` and `no_priced_boards`; one
quiet scan is not an incident. The scanner keeps a per-mode consecutive counter
and alerts only after `COVERAGE_ALERT_CONSECUTIVE_SCANS` (default 2) in a row.
Any other reason, including `no_crossing`, resets the counter.

## Settings and SLOs

| Variable | Default | Meaning |
|---|---:|---|
| `COVERAGE_FLAG_ALERT_THRESHOLD` | `1` | Minimum `coverage_budget.flag_count` before `coverage_drop` alerts. `0` disables that alert. |
| `MAPPING_COVERAGE_FLOOR` | `0.95` | Minimum mapped-row ratio before `mapping_coverage_low` alerts. |
| `MAPPING_COVERAGE_MIN_ROWS` | `20` | Denominator below which mapping coverage is not judged. |
| `COVERAGE_ALERT_CONSECUTIVE_SCANS` | `2` | Consecutive scans required for `zero_result_reason`. |

SLO denominators are explicit: coverage flags are counted per
`bookmaker|sport|market` key from the last 20 scans; mapping coverage is per
scan's mapped/unmapped market rows; repeated zero results are per mode and
reason. Alert delivery is deduped by mode + flag identity and stays off the scan
path.

## Alerts, metrics and the dashboard trend

`coverage_drop` is raised once per peer-populated flag (silent zero or material
drop). Its body names the peer evidence (`peer_books`, `peer_rows`) and the
`baseline_scans` count, so a legitimate all-zero seasonal feed stays quiet.
`mapping_coverage_low` carries the exact numerator/denominator and floor.
`zero_result_reason` carries the consecutive count and the group/board counts.

Prometheus gets `bh_coverage_flags`, `bh_coverage_flags_total`,
`bh_mapping_coverage_ratio` and `bh_unmapped_market_rows_total`, all labelled by
mode. `/api/health.coverage_trend.<mode>` keeps the last 30 compact points and
the Diagnostics tab draws them as two lines: coverage flags and unmapped rows.

## Baseline

The first real baseline is the next three completed scans on the deployment
host. Until then `/api/health` reports `baseline_scans` below 3 and the budget
does not flag anything. This is deliberate: a single short scan is not a
baseline. The soak report (`docs/SOAK.md`) records the same field.
