# Push-feed discovery and decision (P2-10)

## Method

`scripts/discover_push_feeds.py` loads a bookmaker page in headless Chromium and
records transport metadata for 15–30 seconds: WebSocket URLs, frame counts,
byte totals, text/binary opcode mix and inter-frame gaps, plus XHR/fetch URLs
and response sizes. It never stores odds payloads, cookies or headers. Raw
reports are `docs/evidence/2026-11-04-push-*.json`.

## Measured decisions (2026-11-04)

| Book | Transport observed | Frames / bytes | Decision |
|---|---|---|---|
| maxbet | no WebSocket; 8 XHR/fetch | — | **polling** |
| mozzartbet | `socket.io` WebSocket + 15 XHR | 4 frames / 108 B over 30 s; longest gap 25 s | **polling** — heartbeat only, not odds |
| wwin | no WebSocket; 21 XHR/fetch | — | **polling** |
| sportplus | `rabbit.sportplus.ba` WS + live-chat WS | 8 binary frames / 205 B over 15 s; live-chat separate | **polling for now** — no measured odds cadence or coverage gain |

No candidate measured materially fresher than the REST path, so **no WebSocket
adapter is enabled** and scan behavior is unchanged. A socket.io connection that
carries four tiny frames in 30 seconds is a heartbeat, not a price stream;
treating it as one would add a reconnect surface with no freshness benefit.

## What exists for a future adapter

`engine/live_feed.py` contains the feature-flagged state machine a future adapter
must use:

- sequence continuity (duplicates and gaps refuse the stream);
- snapshot/delta coalescing to the latest row per event/market/line/outcome;
- a bounded latest-row store (`max_rows`);
- explicit heartbeat staleness (`heartbeat_timeout_seconds`);
- `priceable()` is false while disabled, gapped, duplicated or stale.

`config.settings.LIVE_FEED_FLAGS` is off for every book by default. No path in
the scan calls the state machine, which is why enabling a flag cannot change
pricing until an adapter is deliberately wired.

`tests/test_live_feed.py` covers flag-off, snapshot, delta, gap, duplicate,
silence, the row bound and offline replay. `tests/test_live_mode.py` remains the
polling path's regression suite.

## Re-running a capture

```bash
python scripts/discover_push_feeds.py --bookmaker mozzartbet --seconds 30 \
  --out docs/evidence/2026-11-04-push-mozzartbet.json
```

A book qualifies for an adapter only after a capture shows odds-sized, frequent
frames and a measured improvement in time-to-first-price or update cadence over
the current REST path.

## Books outside the probe

- `premier_kladionica`: the event rows and market rows use different sport
  dimensions (see `docs/MULTISPORT_EVIDENCE.md`); a push adapter would need a
  proven non-football and football mapping first, so it was not probed.
- `betole`: disabled in `config/settings.py`; its desk feed is football-only and
  the public SPA rendered blank in the browser session. Polling remains the only
  path and the book is not enabled.
- `mbet`, `mdshop`, `admiralbet`: direct HTTP feeds already return the full
  prematch snapshot in one request; no browser push surface was observed.
