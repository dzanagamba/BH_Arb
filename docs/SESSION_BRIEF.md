# Session brief

**Updated:** 2026-11-07
**Goal:** keep `ROADMAP.md` current without weakening the trust model.
**Current task:** none; SR1-1, SR1-2, SR1-3, SR2-1, SR2-2, SR2-3, SR2-4, SR2-5
and SR2-6 are done and pushed.
The roadmap is the single task list in `ROADMAP.md`; N2-4 stays deferred and
P1-6 stays waived until the operator says otherwise.
**Last task commit:** `a13229a` — per-book rate limit, scan deadlines and
circuit breaker (SR2-4, SR2-5, SR2-6).

## Project state

SR2-6 (2026-11-07, commit `a13229a`): the scheduled-scan backoff is now a real
per-book circuit breaker in `scrapers/breaker.py`, keyed by `(mode, book)`,
closed → open → half-open with one probe and an injected clock. `blocked`/`429`
open it on the first occurrence with twice a soft failure's cooldown, `empty`/
`timeout`/`transport`/`5xx` open it after `BOOK_BACKOFF_AFTER_FAILURES`, and a
parser error or schema drift never opens it. Cooldowns double per open up to
`BOOK_BACKOFF_MAX_MINUTES`. State, failures and the remaining cooldown are in
`/api/health` under `scheduler.breakers` and in `/api/metrics` as
`bh_book_breaker_state{failures,cooldown_seconds}`. Manual scans still ignore an
open breaker.

SR2-5 (2026-11-07, commit `a13229a`): a scan can no longer hang on one book. Each
adapter runs under `TransportPolicy.adapter_deadline`
(`SCRAPER_BOOK_TIMEOUT_SECONDS`, default 240 s, 2.4× the slowest recorded book),
and the whole scrape phase runs under `SCRAPER_SCAN_TIMEOUT_SECONDS` (600 s).
A book that overruns is `timeout` and missing from the scan; its browser is
closed and its browser slot released, and the books that already returned still
price. The scan deadline deliberately covers the scrape phase only, not the
local matching/pricing work after it (recorded under the task).

SR2-4 (2026-11-07, commit `a13229a`): `scrapers/ratelimit.py` adds one outgoing
limiter per bookmaker, acquired once per attempt inside `retry_call` (retries
included and the first attempt included). It is hand-rolled rather than adding
`aiolimiter`, because the timing test needs a clock/sleep seam and a
burst-free reservation model; two tests pin that and the queueing. The rate is
`SCRAPER_REQUESTS_PER_SECOND` (default 5/s, 0 disables), carried on every
`TransportPolicy` including the three browser books, so their `page.request`
calls are limited too. Against the recorded 2026-11-06 prematch scan (187
requests, busiest book 101 in 57 s) no book's modelled floor exceeds its
recorded wall time, so the measured scans do not get slower.

SR1-1, SR1-2, SR1-3, SR2-1, SR2-2 and SR2-3 (2026-11-07, commit `30b6632`): the
parser-contract equality check now uses a pinned reference date, so it no
longer turns red when a capture crosses the 120-day policy (the real-date
`refresh_fixtures.py --check` alarm is unchanged). The runtime-state guard
ignores SQLite `-shm`/`-wal` sidecars while still comparing the database file
and every other runtime file. CI already runs the suite in the two ledger modes
`check_test_isolation.py` orchestrates, so `AGENTS.md` and `docs/CI.md` now say
that rather than promising a separate step. `scrapers/errors.py` owns one
structural `ScrapeKind`; `run_scan` records it per book, health exposes it, and
`bh_book_kinds_total` reports it while the historical outcome metric is
unchanged. `settle()` returns that shared kind instead of swallowing failures.
`scrapers/transport.py` owns the per-book timeout/limit policy and one HTTP
client per book per scan, closed when the scraper gather returns.
`scrapers/retry.py` now applies full jitter, the attempt cap and total-time
budget, `Retry-After` and one-attempt 403/challenge blocking, with every attempt
counted; wwin's private retry loop is gone. The suite is **1,853 passed, 6
skipped, 1 xfailed** in both ledger modes.

M7-1 (2026-11-07, commit `9cd37d0`): presentation-only dashboard fixes — Unicode
name capitalisation, the re-check banner's escaped age markup, a worded
`unconfirmed` row badge, a quiet pre-scan freshness notice (full warning as
soon as a row is listed), book-tag contrast and phone slip totals. Assets are
now `?v=8`.

On 2026-11-07 the old roadmaps and the maintenance backlog were folded into
`ROADMAP.md` and deleted; the research briefs moved to `research/`. The
`P*`/`N*` IDs are now historical labels with a glossary in the `ROADMAP.md`
History section. P1-6 is waived and excluded. The suite runs
**1,853 passed, 6 skipped, 1 xfailed, 1 warning** in both ledger modes, with
**86.40%** coverage (floor 80%; 12,072 statements). The six skips are the two
opt-in runtime-state checks, the two Chromium tests unless
`BH_ARB_TEST_BROWSER=1`, and the two load budgets unless `BH_ARB_TEST_SLOW=1`.
Ruff, MyPy (231 source files), Node syntax checks and the generated market doc
are clean. The xfail documents the deferred named-key auth gap (see below).

### 2026-11-06 maintenance pass (`2e06756`)

A six-audit cleanup pass landed in `2e06756`.
It removed dead symbols and duplicate price/registry helpers, unified the team
key, fixed the stale-price cap, mapping coverage with cached dict rows,
non-finite bet inputs, `days` bounds, CSV formula escaping, per-book cache
restore and the verify rate limit; repaired the service worker, feed-mode
races, Bosnian wiring, mobile slip trap, settings-drawer focus and download
auth headers; and made the SBOM describe the resolved runtime, with workflow
permissions and Dependabot coverage. The full suite, Ruff, MyPy, the market doc
check, the isolation check and an end-to-end browser pass (service worker,
offline shell, all tabs, BS/EN, exports, a real 155 s scan producing 4 visible
surebets, and a live odds re-check) are green.

Deferred: auth middleware/scope redesign (the xfail), event-loop offload of scan
stages, `server/api.py` decomposition, constraints lock, Docker Chromium/CVE
checks, dependency bumps, legacy URL-map removal, `link_sweeps` storage decision,
approve/reject route decision, and branch-coverage gating. The full backlog is
in `ROADMAP.md` (the `M*` rows, each gated on operator approval).

N3-2 adds `engine/admissibility.py` and `scripts/audit_admissibility.py`. The
offline report has a stable schema and records, per book and sport, the measured
market families with their settlements; for every enabled football market it
records the dated evidence row, the per-book registry declarations and, for
0.5/4.5/5.5, the measured price sources. The dated baseline is
`docs/evidence/2026-11-05-admissibility-baseline.json`.

`python scripts/audit_admissibility.py --check` fails when an admitted sport or
market disappears, a previously measured family or price source disappears, a
qualifying book drops below three families, a settlement changes, an enabled
entry loses its evidence, or the fixed three-book/three-family rule is changed.
A new family, book, price source, sport or market is only a warning and never
changes an admitted flag; code remains the admission decision. CI runs the
check on every push; the live bookmaker probe stays a reviewed operator action
documented in `docs/ADMISSIBILITY_AUDIT.md`. `/api/health.admissibility_audit`
exposes the bounded status.

Earlier work remains in place: hermetic tests, frozen-price quarantine, CSP with
no inline styles, automatic CLV capture, retention/maintenance, coverage alerts,
per-book scan cost, release hardening, paper ledger/fills, candidate remediation,
the complete BS/EN UI with machine-checked accessibility, dated parser contracts
and the property-based pricing/identity suites and load budgets. The first live
scan-cost and seven-day opportunity baselines remain unmeasured; N2-4 owns the
latter and is deferred.

## Next action

Start **SR4-1** (transport-level tests with respx); it is the next ungated task,
now that SR2-3 is Done. The SR3 rows are still blocked on SR3-1 (gate SR0-1).
The four operator gates waiting for a decision are SR0-1, SR0-2, SR4-9 and
SR6-3. N2-4 stays deferred and P1-6 stays waived. Do not invent a task or
reopen a done one.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
