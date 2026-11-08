# Scan-cost baseline — measured

**Date:** 2026-11-08
**Modes:** `live` and `prematch`
**Status:** measured (SR5-2). This replaces the 2026-11-05 pending slot; that
session ran no scan and deliberately claimed no numbers.
**Source:** one `api.run_scan(<mode>)` per mode on this host, then
`python scripts/scan_cost.py --days 1 --mode <mode>`. The raw reports are in
`cache/scan_cost.json` (`last.prematch`, `last.live`).

Both scans ran the same day within minutes of each other, so they are one
deployment snapshot, not a trend.

## Prematch

```text
Scan cost — last 1 day(s), mode=prematch
Denominators: 1 scan(s), 10 book(s), 6610 match(es), 45192 market row(s)

book                 scans   ok empty parse block   wall_s browser_s    req      MB matches  s/match  fail%
admiralbet               1    1     0     0     0    40.52      0.43      5   24.63     936    0.043    0.0
betole                   1    1     0     0     0    13.97       n/a     21    4.84     717    0.019    0.0
evlbet                   1    0     0     0     0     0.00       n/a    n/a     n/a       0      n/a    0.0
maxbet                   1    1     0     0     0     8.86       n/a      3    7.64     948    0.009    0.0
mbet                     1    1     0     0     0    25.74       n/a     16  122.24     897    0.029    0.0
mdshop                   1    1     0     0     0     8.06       n/a      3   24.58     936    0.009    0.0
mozzartbet               1    1     0     0     0    55.37      0.45    585  165.98     545    0.102    0.0
premier_kladionica       1    0     0     1     0    11.06       n/a      2   21.12       0      n/a  100.0
sportplus                1    1     0     0     0    10.60       n/a      1   18.46     738    0.014    0.0
wwin                     1    1     0     0     0    26.87      0.44     46    3.28     893    0.030    0.0
TOTAL                    1    8     0     1     0   201.06      1.32    682  392.77    6610    0.030

Cost/coverage: 0.030 s/match, 0.103 requests/match, 62307.17 bytes/match.
```

Observed wall time: **144.8 s**. `TOTAL wall_s` is the sum of per-book wall
times (201.06 s), not elapsed: books ran concurrently.

## Live

```text
Scan cost — last 1 day(s), mode=live
Denominators: 1 scan(s), 10 book(s), 653 match(es), 3548 market row(s)

book                 scans   ok empty parse block   wall_s browser_s    req      MB matches  s/match  fail%
admiralbet               1    1     0     0     0    16.17      0.48      5   13.42     115    0.141    0.0
betole                   1    0     1     0     0     8.94       n/a     18    5.34       0      n/a    0.0
evlbet                   1    0     0     0     0     0.00       n/a    n/a     n/a       0      n/a    0.0
maxbet                   1    1     0     0     0     3.01       n/a      3    0.93     111    0.027    0.0
mbet                     1    1     0     0     0    2.54       n/a      4   10.30     133    0.019    0.0
mdshop                   1    1     0     0     0    3.22       n/a      3   13.42     115    0.028    0.0
mozzartbet               1    0     1     0     0    12.89      0.49     30    4.58       0      n/a    0.0
premier_kladionica       1    0     0     1     0     5.54       n/a      2   21.26       0      n/a  100.0
sportplus                1    1     0     0     0    2.87       n/a      1    4.99      73    0.039    0.0
wwin                     1    1     0     0     0    11.35      0.48      4    0.50     106    0.107    0.0
TOTAL                    1    6     2     1     0    66.52      1.45     70   74.74     653    0.102

Cost/coverage: 0.102 s/match, 0.107 requests/match, 120023.32 bytes/match.
```

Observed wall time: **33.7 s**; the table's 66.52 s is summed book time.

The `MB` column is MiB (`bytes / 1024²`); the per-book figures follow the total
bytes in the JSON report.

## What was measured

- 10 configured books, 9 enabled; `evlbet` is config-disabled and skipped.
- Prematch: 682 requests, 411.9 MB (392.77 MiB) of bodies, 201.06 book-seconds,
  1.32 browser-seconds, 6,610 matches / 45,192 market rows, 0.030 s and about
  62 KB per match.
- Live: 70 requests, 78.4 MB (74.74 MiB) of bodies, 66.52 book-seconds,
  1.45 browser-seconds, 653 matches / 3,548 market rows, 0.102 s and about
  120 KB per match.
- The byte cost is dominated by `mozzartbet` (166-174 MiB per scan, 585 requests
  in prematch) and `mbet` (122 MiB prematch). Those are the first candidates if
  traffic or memory needs to come down.
- Empty feeds: none in prematch; `betole` and `mozzartbet` in live. No blocked
  books in either scan.
- `premier_kladionica` is the only `fail% 100` row in both modes: a delta sync
  odds row had 5 columns where the strict schema expects at least 9
  (`[0, '', 1794138522410, 4, 1308500813]`). It drops from both feeds. This is
  recorded as **SR4-13**; it is not fixed here. (SR4-13 was fixed the same day:
  see `2026-11-08-premier-delta-sections.md`.)

`n/a` is "not measured", never zero: a non-browser book has no browser time,
and a skipped book has no requests or bytes.

## What this does and does not prove

- It measures what one scan of each feed costs this deployment on 2026-11-08.
- It distinguishes a failed/blocked book from an empty one.
- It does not prove that a cheap book is a good book, and it changes no
  certainty gate or pricing rule.
- Two scans are a baseline, not a trend; the rolling table is in
  `docs/SCAN_COST.md`.
