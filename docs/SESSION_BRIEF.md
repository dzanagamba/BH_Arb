# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4, N1-1 and N1-2 are Done**. First
eligible task is **N1-3** (per-book scan cost accounting).
**Last task commit:** `bc4bf3e` — N1-2 coverage/mapping alerts and SLOs.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,530 passed, 2 skipped, 1 warning** in both ledger modes: with no generated
ledger and with a deliberately populated one. Ruff, MyPy (193 source files),
Node syntax check and the generated market doc are clean.

N1-2 adds evidence-backed coverage alerts without changing the gate:
`coverage_drop` fires once per peer-populated silent zero or material drop and
names `peer_books`, `peer_rows` and `baseline_scans`; `mapping_coverage_low`
carries the mapped-row numerator/denominator and floor; `zero_result_reason`
fires only after the configured consecutive `stale_data` / `no_priced_boards`
scans. A legitimate empty feed has no mapping ratio and does not alert.
`/api/health` exposes `mapping_coverage`, `coverage_trend`, `zero_result_streaks`
and `coverage_slo`; Prometheus has `bh_coverage_flags`,
`bh_coverage_flags_total`, `bh_mapping_coverage_ratio` and
`bh_unmapped_market_rows_total`. The Diagnostics tab draws the flags/unmapped
trend.

Earlier work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, a CSP with no inline styles, automatic closing-line capture,
and bounded retention/maintenance with `/api/health.retention`.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N1-3**: instrument each scraper wrapper with wall time, browser-open
time, HTTP request count, response bytes and outcome (`success`, `empty`,
`parse_error`, `blocked`); persist a bounded per-scan per-book summary and expose
it in `/api/health` and the Diagnostics table; add `bh_book_seconds`,
`bh_book_bytes`, `bh_book_requests` and `bh_book_failure_rate`; report missing
measurements as null; add `scripts/scan_cost.py --days 7`; record a real baseline
under `docs/evidence/`. Do not log cookies, headers or bodies.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
