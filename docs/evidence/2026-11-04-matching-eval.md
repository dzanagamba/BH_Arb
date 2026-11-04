# Matching evaluation corpus (P2-4, 2026-11-04)

`python scripts/evaluate_matching.py --check` runs the real `MatchMatcher` over
the frozen corpus in `tests/fixtures/replay/` and compares its verified groups
with explicit label pairs.

## Corpus

| Day | Mode | Matches | Books | Labels same / different |
|---|---|---:|---|---:|
| 2026-09-25 | prematch | 3 | mbet, wwin, sportplus | 3 / 0 |
| 2026-11-03 | prematch | 3 | mbet, wwin, sportplus | 3 / 0 |
| 2026-11-04 | prematch | 79 | 9 books | 308 / 30 |
| 2026-11-04 | live | 52 | 9 books | 99 / 30 |

The 2026-09-25 extract is the reviewed end-to-end capture; 2026-11-03 is the
original replay scan; 2026-11-04 is a bounded extract from the real prematch and
live caches (complete verified groups only, plus cross-group negatives).

## Result

| Metric | Value |
|---|---:|
| Days | 3 |
| Scans | 4 |
| Modes | prematch, live |
| Same-label pairs | 413 |
| Different-label pairs | 60 |
| Precision | **100.00%** |
| Recall | **100.00%** |
| Strict miss rate | **0.00%** |
| False-merge rate | **0.00%** |

Thresholds enforced by `--check`: precision >= 99%, recall >= 80%, false-merge
rate 0%, at least 3 days, and both prematch and live present. The raw report is
`docs/evidence/2026-11-04-matching-eval.json`.

## What the labels cover, and what they do not

- The labels are **gate-reviewed**, not independently hand-labelled from
  scratch. On 2026-11-04 the positive pairs come from the verified groups in
  that scan; the negatives are cross-group pairs. This measures regression
  against a reviewed snapshot, not unsupervised accuracy.
- 2026-09-25 and 2026-11-03 contain one fixture each and therefore no
  independent negatives. Their value is recall and false-merge control on the
  reviewed fixture, not precision on a broad population.
- The corpus is bounded: 137 matches across four scans, not every row the books
  served. It does not cover every league, sport, doubleheader or postponed
  fixture; those are P2-8.
- A missed pair is cheaper than a false merge, which is why the false-merge
  threshold is zero rather than traded against recall.
