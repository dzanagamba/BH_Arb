# Opportunity-rate baseline — 7-day target

**Generated:** 2026-11-04
**Status:** local baseline awaiting scan history; reference measurement recorded.
**Source:** `cache/opportunity_metrics.json` via
`python scripts/opportunity_baseline.py --days 7`.

## Why this report exists

A zero-surebet scan is not automatically a bug and not automatically a quiet
market. The dashboard used to report groups and surebets without the denominator,
so it could not distinguish:

- no board crossed;
- a board crossed but stayed below the profit floor;
- a crossing existed but a guard (price outlier, two-source cap, stale data)
  refused it;
- the feed priced only stale or unverified data.

The scanner now persists one compact aggregate row per completed scan and a
bounded crossing-key store. This is the first dated baseline slot for that data.

## Public reference

The strongest public board-log measurement found in
`docs/RESEARCH_ARBITRAGE_2026-11-04.md`:

| Metric | Value |
|---|---:|
| Odds boards recorded | 115,583 |
| Boards where a market crossed | 1,553 (**1.34%**) |
| Crossings actionable after profit/margin gates | 26 of 1,553 |
| Median margin, all boards | **−3.60%** |
| Median margin, when crossed | 0.21% |

Use this as a sanity range, not as BH_Arb's result. It comes from a different
book set, capture window, and gate.

## Local baseline

**No 7-day local window is available yet.** The report is intentionally not
filled with test-run or fixture numbers, because those are not live scans and
would look like a measured market result.

Once scheduled scans have run for a window, regenerate:

```bash
python scripts/opportunity_baseline.py --days 7 \
  --out docs/evidence/2026-11-04-opportunity-rate-baseline.md
```

The generated table reports, per mode and overall:

| Field | Meaning |
|---|---|
| `Scans` | Completed scans in the window |
| `Boards` | Market instances the engine actually priced |
| `Crossed` | Boards with implied sum below 1.0 |
| `Above floor` | Crossings at or above `DUST_PROFIT_PERCENT` (0.2%) |
| `Actionable` | Surebets kept after the price guard |
| `Crossing rate` | `crossed / boards` |
| `Floor crossing` | `crossed_above_floor / boards` |
| `Actionable rate` | `actionable / boards` |
| `p50` / `p90` lifetime | First crossing to disappearance, or to now if alive |

## Definition guardrails

- A board is counted from the same `ArbitrageEngine.find_surebets` pass that
  emits surebets. There is no second arb formula.
- A crossing is `sum(1/odds) < 1.0`, before the display filters.
- `actionable` is the post-price-guard count, so it can be lower than
  `crossed_above_floor`; that difference is the guarded population.
- Lifetime keys are `event + market + line + period + settlement`. The key store
  is capped at 5,000 records with a 7-day retention.
- A still-live crossing contributes its elapsed lifetime; a disappeared one stops
  at `disappeared_at`.
