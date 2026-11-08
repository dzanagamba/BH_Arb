# HAR replay for the browser books (SR4-8)

The three browser adapters (admiralbet, mozzartbet, wwin) fetch their JSON from
inside the loaded page (SR4-8a), so Playwright's HAR record/replay covers them.
This document describes the committed fixtures and how to refresh them. It does
not change what reaches pricing: a replay is a test, never a data source.

## What is committed

```
tests/fixtures/har/<book>.har.gz     # scrubbed + trimmed transport recording
tests/fixtures/har/<book>.meta.json  # provenance and the verified replay output
```

A HAR is a **transport** recording, not a market fixture: the payloads are the
responses Chromium served, and the fixtures in `tests/fixtures/markets/` remain
the parser contracts. The files are gzipped because a raw capture is 9–88 MB;
the committed set is under 2 MB.

Each file keeps only:

* the page document (`_resourceType: document`), so `goto` establishes the
  origin the adapter fetches from, and
* that book's API calls, i.e. `REPLAY_PREFIXES` in `scrapers/har_fixtures.py`.

Analytics, chat widgets, images, fonts and JS bundles are dropped: a replay
aborts what is not in the file and the adapters need none of it.

`mozzartbet` keeps 30 per-event offer responses (`MAX_REPLAY_OFFERS`). Its full
offer is one request per event (677 requests, ~72 MB of bodies in the
2026-11-08 scan). The offers that are not kept abort during the replay and the
adapter keeps that event's list odds, which is its documented fallback, so the
replay covers the pagination, the parser and the offer path without the full
weight.

## Scrubbing

`scrapers/har_fixtures.scrub()` removes every `cookie`, `set-cookie`,
`authorization` and `proxy-authorization` header from the request and response
sides and empties the HAR's cookie jar. Odds payloads are data, not credentials,
and are kept. `tests/test_har_fixtures.py` fails if any committed file carries a
secret header, if a request body or cookie jar is not empty, or if the file
holds an entry that is neither the document nor one of the book's API calls.

## Refreshing a fixture

```bash
python scripts/capture_har.py --books all
# or one book, at a fixed scan time:
python scripts/capture_har.py --books wwin --scan-time 2026-11-08T18:30:00+00:00
```

The tool records a live HAR through the real adapter and browser pool, trims and
scrubs it, writes the `.har.gz` and the sidecar, then **replays the new file
offline through the same adapter** and records the verified `matches`/`markets`
in the sidecar. A capture that replays zero matches fails instead of writing a
fixture.

The `--scan-time` matters: the adapters build their request URLs from it
(admiralbet's `dateFrom`/`dateTo`, wwin's `tfrom`/`tto`). Capture and replay use
the sidecar's value, so the replay asks exactly the questions the capture
answered. When you re-capture, pass a new fixed time; the replay test reads it
back.

Refresh a HAR when an adapter changes its request shape, when a parser change
alters the expected output (the replay counts change and the test says so), or
when a Playwright bump changes the recorded format. There is no automatic age
alarm: unlike the market fixtures, a stale HAR cannot make the scanner price a
wrong bet, it can only make the replay less representative.

## Running the replay

```bash
BH_ARB_TEST_BROWSER=1 python -m pytest tests/test_browser_har_replay.py
```

Opt-in because it needs Chromium. Each book's file is written to a temporary
plain-JSON copy, served with `route_from_har(not_found="abort")`, and the real
`scrape()` runs with the sidecar's `scan_time`. The asserted counts are the
sidecar's `replay` block, so an adapter that starts asking a different question
(and therefore misses entries) fails the test instead of silently replaying
less. Nothing can reach the network: a missing entry aborts.

`.github/workflows/browser.yml` runs this file with the other Chromium checks,
on `workflow_dispatch` only, so the push CI stays fast.

## What a replay does not prove

It does not prove the live feed still looks like this (the SR4-9 canary does
that), and it does not exercise Cloudflare or the live transport. It proves the
adapter's request sequence, the parsers and the wire schemas against real
recorded bodies.
