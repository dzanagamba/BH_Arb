# Per-book scan cost (N1-3)

The scan cost report answers "what does a full scan cost?" per book. It records
only counts, durations, sizes and outcome labels. It never records a URL, a
request header, a cookie or a response body.

## What is measured

Each book's `scrape()` call is wrapped once per scan. The shared helpers add to
the active book through a context variable:

| Field | Meaning |
|---|---|
| `wall_seconds` | Wall time from the wrapper's start to its finish. |
| `browser_seconds` | Playwright start + Chromium launch + context setup, or `null` with a "book does not use a browser" reason. |
| `requests` | HTTP requests made through `fetch_with_retry`, `page.goto`, `page.request.get/post`, or the Premier JSON-RPC call. |
| `bytes` | Sum of readable response bodies, or `null` when the size is unavailable. |
| `outcome` | `success`, `empty`, `parse_error`, `blocked` or `skipped`. |
| `matches`, `markets` | Rows the book returned, used for the cost/coverage ratio. |
| `missing` | Explicit reasons for every `null` measurement. |

`empty` is a book that answered with no matches; `blocked` is a bot wall,
403/429, CAPTCHA/Cloudflare or network timeout; `parse_error` is a data/shape
failure. A `skipped` book was disabled or backing off and says so. The split is
diagnostic only: it never changes pricing or the certainty gate.

## Storage and exposure

The last scan and a newest-first history of 500 scans are stored in
`cache/scan_cost.json`. The history is runtime state and is not a trust record.

`/api/health.scan_cost.<mode>` returns the last scan's per-book records and its
`totals`: books, outcome counts, wall/browser seconds, requests, bytes, matches,
markets, and the derived `seconds_per_match`, `requests_per_match` and
`bytes_per_match`. A `null` means "not measurable", never zero.

The Diagnostics tab renders the same table. It shows book, outcome, wall,
browser, requests, bytes, matches and seconds per match; the row tooltip carries
the `missing` reasons. No URL, header or payload field is served.

## Metrics

| Metric | Labels | Meaning |
|---|---|---|
| `bh_book_seconds` | `mode`, `book` | Wall seconds for the last scan. |
| `bh_book_browser_seconds` | `mode`, `book` | Browser-open seconds, when measured. |
| `bh_book_requests` | `mode`, `book` | HTTP requests in the last scan. |
| `bh_book_bytes` | `mode`, `book` | Readable response bytes in the last scan. |
| `bh_book_failure_rate` | `mode`, `book` | `(parse_error + blocked) / attempts` over the newest 20 scans. |

A metric is absent when its value is not measurable. That keeps a scrape from
reading an unmeasured `0` as "the book made no requests".

## CLI

```bash
python scripts/scan_cost.py --days 7
python scripts/scan_cost.py --days 7 --mode prematch
python scripts/scan_cost.py --days 7 --json
```

The table prints explicit denominators: scans, books, matches and market rows.
The cost/coverage ratio is `wall_seconds / matches` (plus requests and bytes per
match). Per-book failure rate is `(parse_error + blocked) / scans`; `n/a` means
the window has no measurement.

## Baseline

The first live baseline belongs under `docs/evidence/`. This session did not
run a live scan, so `docs/evidence/2026-11-05-scan-cost-baseline.md` records the
harness as ready and the baseline as pending rather than inventing a number.
After the next real scan, run the CLI and replace that file with the measured
table, its date, scan count and book count.

## Limitations

- Response bytes are only what the instrumented paths can read; a browser
  navigation that returns no readable body is reported as `null`, not `0`.
- Browser time measures opening, not the full browser lifetime; page work is in
  `wall_seconds`.
- The failure rate is a book-level operational signal, not a claim about price
  quality or certainty.
- The report measures cost, not coverage quality. A cheap book that returns
  nothing is still visible as `empty` or `blocked`.
