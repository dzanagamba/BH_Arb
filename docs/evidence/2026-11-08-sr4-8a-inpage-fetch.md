# SR4-8a route A — in-page fetch for the browser books

**Date:** 2026-11-08
**Decision:** route A (in-page `fetch`), recorded by the operator.
**Scope:** `scrapers/base.py` only. No book, market, gate or pricing change.

## Why A

The three browser adapters read JSON through `page.request`, which is an
`APIRequestContext`: Playwright's `context.route`, `record_har_*` and
`route_from_har` never see those requests (measured in SR4-8: a route on
`**/probe` never fired, and a real admiralbet capture held only analytics). A
request issued by the document itself is page-initiated, so routing and HAR
cover it. Route A moves the call into the page and keeps the response surface
the adapters already used.

## What changed

- `measured_api_get` / `measured_api_post` (`scrapers/base.py`) now run
  `fetch` inside the loaded document; they still take `headers`, `params` and
  `data`, still count the request and its bytes, and still return an object
  with `status`/`status_code`, `headers`, `body()`, `json()` and `content`.
- A dict/list `data` is JSON-serialised and gets `application/json` when the
  caller did not set a content type, and a string body is sent unchanged —
  the same rules Playwright's `data` used, so the two POST endpoints keep their
  request shape.
- `credentials: "include"`, so the browser's own cookies and its Cloudflare
  clearance go with the call.
- The timeout moved to Python (`PAGE_FETCH_TIMEOUT_SECONDS`, 30 s, the old
  `APIRequestContext` default): an overrun is the shared `timeout` kind, not a
  text-matched JS error. The adapter and scan deadlines (SR2-5) are unchanged.
- No adapter calls `page.request` any more (pinned by
  `tests/test_page_fetch.py::test_no_adapter_calls_page_request`).

## Measurement plan (the row's requirement)

One live prematch pass per browser book, sequential, one shared Chromium, the
real adapter and the real transport policy — requests, bytes and wall from the
per-book cost collector; Cloudflare pass and the SR2-1 kind reported per book.
Control: the same pass with the adapters' imported `measured_api_*` patched back
to `page.request` in-process (no source change), minutes later on the same
offer, so the transport is the only difference.

## Measured (2026-11-08, prematch, operator host)

In-page fetch (route A):

| book | requests | bytes | wall | matches | markets | kind |
|---|---|---|---|---|---|---|
| admiralbet | 3 | 4,709,910 | 13.2 s | 121 | 961 | `ok` |
| mozzartbet | 234 | 72,274,801 | 25.5 s (19.2 s on an earlier pass) | 215 | 1,705 | `ok` |
| wwin | 46 | 2,027,476 | 13.2 s (11.7 s earlier) | 459 | 2,690 | `ok` |

Control, `page.request`:

| book | requests | bytes | wall | matches | markets | kind |
|---|---|---|---|---|---|---|
| admiralbet | 3 | 4,710,584 | 10.3 s | 121 | 962 | `ok` |
| mozzartbet | 233 | 71,946,697 | 37.0 s | 215 | 1,701 | `ok` |
| wwin | 46 | 2,027,472 | 12.1 s | 459 | 2,690 | `ok` |

Reading:

- **Cloudflare passed on every book, including cross-origin admiralbet**
  (`www.admiralbet.ba` page → `bihoffer.admiralbet.ba`): zero `blocked`, zero
  `transport`, three `ok`.
- Requests match within one (mozzartbet 234 vs 233 — the offer moved by an event
  between the two passes), bytes within 0.5 % on all three, and the parsed
  output is identical modulo that movement (admiralbet 961 vs 962 markets, 121
  matches both), so the in-page path reads the same feed with the same cost.
- Wall is not worse; mozzartbet's 675-request full offer is the only long book
  and it was faster here (19.2–25.5 s vs 37.0 s). One pass each, so the wall is
  indicative, not a benchmark.
- The run logged SR4-4 structural-drift alerts for optional per-item keys
  (`match.competitionComment`, `events[].bets[]` variants). They are alert-only,
  come from the stored live baseline, and fired for day windows that carry
  different optional keys; they are not caused by this transport and change no
  price.

## Boundaries

- Public prematch pages and odds endpoints only; no login, no bet, no account
  action, and the per-book rate limit and retry policy were in force.
- The live feeds were not re-probed; they use the same helper, and the same
  `credentials: "include"` and timeout apply.
- This makes the browser books replayable; it does not build the HAR fixtures.
  `SR4-8` now owns the scrubbed capture tool and the `route_from_har` replay
  test per book. `tests/test_page_fetch_browser.py` (opt-in,
  `BH_ARB_TEST_BROWSER=1`) proves with real Chromium that `context.route` sees
  both the document and the in-page API call, and that a POST body arrives
  intact.
