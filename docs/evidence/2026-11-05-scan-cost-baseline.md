# Scan-cost baseline — pending live scan

**Date:** 2026-11-05
**Status:** harness ready; **no live scan was run in this session**, so no cost
numbers are claimed.
**Source:** `cache/scan_cost.json` via `python scripts/scan_cost.py --days 7`.

## Why this file exists

N1-3 added per-book wall time, browser-open time, request count, response bytes
and outcome. This is the dated slot for the first real measurement. It is
deliberately empty rather than filled with an offline fixture or an estimate.

## How to record the first baseline

After a real deployment scan (prematch and live where available):

```bash
python scripts/scan_cost.py --days 7 --json > /tmp/scan-cost.json
python scripts/scan_cost.py --days 7
```

Copy the table and JSON into this file, then record:

- the date and mode(s);
- the scan denominator and the book denominator;
- the wall, browser, request and byte totals;
- the cost/coverage ratio (`seconds per match`, `requests per match`,
  `bytes per match`);
- every `n/a` with its `missing` reason.

## What this baseline will and will not prove

- It will measure what a scan costs this deployment on the recorded days.
- It will distinguish a failed/blocked book from an empty one.
- It will not prove that a cheap book is a good book, and it will not change
  the certainty gate or any pricing rule.
- A missing measurement stays `null`/`n/a`; it is never reported as zero.
