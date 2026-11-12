# 2026-11-12 SR8-5: SportPlus dropped out on a blank 200 body

## What the scan log showed

Operator's prematch scan (`POST /api/scan?mode=prematch`), request `6215445f…`:

```
00:26:57 | WARNING | scrapers.retry | https://www.sportplus.ba/api/v1/prematch/offer: ReadError:  (attempt 1/3), retrying in 0.27s
00:27:04 | WARNING | scrapers.retry | https://www.sportplus.ba/api/v1/prematch/offer: ReadError:  (attempt 2/3), retrying in 0.84s
00:27:36 | INFO    | httpx | HTTP Request: GET https://www.sportplus.ba/api/v1/prematch/offer "HTTP/1.1 200 OK"
00:27:36 | ERROR   | server.api | ❌ Scrape error — SportPlus: sportplus response is not JSON: Expecting value: line 3 column 1 (char 4)
...
00:28:35 | WARNING | server.api | Quarantined from pricing: sportplus
```

`Expecting value: line 3 column 1 (char 4)` is what CPython's decoder reports
for a document of exactly four whitespace bytes: it skips `\r\n\r\n`, lands at
`char 4` on line 3 and finds no value. So the third attempt was a `200` carrying
no payload at all — not a changed feed.

## The endpoint was healthy minutes later

Probe through the same `scrapers.transport` client and headers the adapter uses
(`/tmp/opencode/probe_sportplus.py`, `probe_sportplus_loop.py`, 2026-11-12
00:42–00:45), five requests on one pooled client:

```
[0] status=200 bytes=21134995 ctype='application/json; charset=utf-8' secs=3.4 head=b'"{\\"liveBooked\\":...'
[1] status=200 bytes=21134995 ... secs=3.1
[2] status=200 bytes=21134995 ... secs=3.0
[3] status=200 bytes=21134995 ... secs=2.9
[4] status=200 bytes=21134995 ... secs=2.6
```

5/5 valid, 21 MB double-serialised JSON (1.76 MB gzipped) in ~3 s. Nothing on
our side was wrong: no shape change, no block, no auth wall.

## What changed

| Before | After |
|---|---|
| a 2xx with a whitespace-only body reached `resp.json()`, raised `schema_drift` and ended the book's scrape | `scrapers.errors.EmptyBodyError` classifies it `transport` |
| the blank body consumed the *last* attempt after two `ReadError`s and read like a parser bug | `fetch_with_retry(..., require_body=True)` raises it inside `send`, so the existing attempt cap, time budget and rate limiter retry it |
| `sportplus response is not JSON: <decoder error>` | `sportplus response is not JSON (HTTP 200, text/html; charset=utf-8, 37 bytes, head=b'<html>…'): <decoder error>` |

No budget, rate or timeout was raised, and a book that never returns a body
still fails closed and drops out of the scan. With this incident's log the book
would still have dropped out — the two `ReadError`s had already spent the three
attempts — but the scan would have reported `transport` ("empty body") instead
of a schema change.

## Measurement

```
python -m pytest tests/test_sportplus_transport.py tests/test_retry.py
python -m pytest
```

- `tests/test_sportplus_transport.py` (new, 4): blank 200 → retried → the real
  offer parses (598 matches on the live feed); blank bodies only → `transport`
  after exactly 3 attempts; HTML body → `schema_drift` with status, content
  type, size and head in the message; a live blank body is retried too.
- `tests/test_retry.py` +1: without the flag a blank 200 is returned untouched
  in one attempt; with it, three attempts and a `transport` `ScrapeError`.
- Full suite: `2458 passed, 12 skipped in 120.30s`.

## After the change, on the running server

Three prematch scans through the dashboard API
(`POST /api/scan?mode=prematch`, 2026-11-12 00:51–01:00):

```
✅ SportPlus: 737 prematch matches scraped     (scan 1)
✅ SportPlus: 737 prematch matches scraped     (scan 2)
✅ SportPlus: 737 prematch matches scraped     (scan 3)
```

No `Scrape error`, no `not JSON` and, in the third scan, no `Quarantined from
pricing: sportplus`. Scans 1–2 did log the quarantine, with reason `recovering`:
the feed-integrity guard needs three clean scans after the 23:28 UTC failure, and
scan 3 restored `state = healthy` (`consecutive_healthy_scans = 3`, 737 matches).
The last scan served 6,327 matches / 1,266 groups / 22 surebets with all nine
books present.
