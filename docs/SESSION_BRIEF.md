# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 and N0-2 are Done**. First eligible task is
**N0-3** (CSP without inline styles); N0-4 (automatic CLV) now also has its
N0-2 dependency.
**Last task commit:** `pending` — N0-2 frozen-price quarantine.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite now
runs **1,494 passed, 2 skipped** in both ledger modes: with no generated ledger
and with a deliberately populated one. A throwaway copy with no
`config/generated/` and no `cache/` also passes in both modes. Ruff, MyPy and the
generated market doc are clean.

N0-2 added `source_updated_at` (the book's own update time) beside `fetched_at`
(our collection time). A row is refused as **price frozen** when the feed
timestamp is older than the mode's TTL, or when its price has not moved for
`STALE_PRICE_UNCHANGED_SCANS` scans while an independent price source moved. A
stable market with stable peers is never refused, and a missing timestamp falls
back to the existing fetch-time TTL. Evidence is in `stale_prices` on
`/api/results` and `/api/health`, `stale_price_rows` in feed integrity, and a
**price frozen** badge on the dashboard. The certainty gate is untouched.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N0-3**: mark it `In progress`, inventory every `style=` in
`frontend/index.html` and generated HTML in `frontend/js/app.js`, replace display
toggles with `[hidden]`/classes and per-row colors with CSS custom properties or
classes, then remove `style-src 'unsafe-inline'` from `server/app.py`. Keep the
existing CSP nonce and XSS tests passing.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
