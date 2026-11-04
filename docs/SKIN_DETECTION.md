# Identical-feed ("skin") detection

Two brands can be one price source. The shipped config already declares the
NSoft pair (`mdshop` = `admiralbet` = `nsoft`). P2-7 measures the rest from a
scan instead of adding another hardcoded guess.

## Rule

For every verified group, each book pair is compared only on the same event,
market type, settlement, period and line. An outcome is "shared" when both books
quote that label; it is "identical" when the decimal prices agree within `0.001`.

| Classification | Condition |
|---|---|
| `insufficient_data` | fewer than `MIN_SHARED_OUTCOMES` (200) shared outcomes |
| `twin` | shared >= 200 and identical rate >= 99% |
| `suspicious` | shared >= 200 and identical rate >= 95% |
| `independent` | shared >= 200 and identical rate < 95% |

`insufficient_data` is never treated as independent. A measured twin is
registered as one price source for the rest of the process, so the engine's
one-leg-per-source rule applies exactly as it does to NSoft.

## Measured on the 2026-11-04 prematch cache

The real cache (8,969 matches, 1,499 groups) produced one measured twin:

| Pair | Shared outcomes | Identical rate | Class |
|---|---:|---:|---|
| admiralbet / mdshop | 11,796 | 100.00% | **twin** |
| maxbet / mbet | 11,604 | 9.45% | independent |
| admiralbet / mbet | 11,320 | 7.46% | independent |
| maxbet / premier_kladionica | 11,066 | 8.97% | independent |
| maxbet / wwin | 10,106 | 7.95% | independent |

All 35 other pairs were independent; no pair fell below the 200-outcome floor.
The raw matrix is `docs/evidence/2026-11-04-skin-matrix.json`.

## Visibility

`/api/health` exposes `skin_detection` per feed:

- `matrix` — every pair with shared/identical counts, rate, minimum sample and
  classification;
- `summary` — counts per class;
- `warnings` — a config-declared twin (NSoft) that measured `independent` or
  `suspicious`;
- `new_twins` — pairs registered by the latest scan.

## Tests

`tests/test_skin_detection.py` covers identical, independent and
insufficient-data pairs, the one-source rule removing an otherwise valid arb,
and the config-declared warning. `tests/test_arbitrage.py` keeps the seeded
NSoft rule pinned.
