# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4 and N1-1 through N1-3 are Done**.
First eligible task is **N1-4** (release hardening: Docker smoke, SBOM,
dependency updates).
**Last task commit:** `ccb4858` — N1-3 per-book scan cost accounting.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,542 passed, 2 skipped, 1 warning** in both ledger modes: with no generated
ledger and with a deliberately populated one. Ruff, MyPy (197 source files),
Node syntax check and the generated market doc are clean.

N1-3 measures each book's scan cost: wall time, browser-open time, HTTP request
count, readable response bytes and outcome (`success`, `empty`, `parse_error`,
`blocked`, `skipped`). Missing measurements are `null` with an explicit reason,
never zero. The last scan is in `/api/health.scan_cost.<mode>`, the Diagnostics
tab shows the table, and `cache/scan_cost.json` keeps a newest-first history of
500 scans. `scripts/scan_cost.py --days 7` prints the per-book table and the
cost/coverage ratios with scan/book/match denominators. Metrics:
`bh_book_seconds`, `bh_book_browser_seconds`, `bh_book_requests`,
`bh_book_bytes`, `bh_book_failure_rate`.

The first live baseline is still pending: this session ran no live scan, so
`docs/evidence/2026-11-05-scan-cost-baseline.md` records the harness as ready and
the numbers as not yet measured.

Earlier work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, a CSP with no inline styles, automatic closing-line capture,
bounded retention/maintenance, and coverage/mapping alerts with the Diagnostics
trend.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N1-4**: add a CI job that builds the Docker image and hits `/api/health`
inside it (optional/manual if build minutes matter), generate an SBOM
(`cyclonedx` or `pip-audit` JSON) from the same requirements files, add grouped
Dependabot/Renovate configuration, cache the Playwright browser layer with the
documented build time, and document the release checklist with the local
equivalent of each job.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
