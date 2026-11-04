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

## Baseline

The first real baseline is the next three completed scans on the deployment
host. Until then `/api/health` reports `baseline_scans` below 3 and the budget
does not flag anything. This is deliberate: a single short scan is not a
baseline. The soak report (`docs/SOAK.md`) records the same field.
