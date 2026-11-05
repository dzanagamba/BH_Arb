# BH_Arb — Next Development Roadmap

**Created:** 2026-11-05
**Repository:** `dzanagamba/BH_Arb` (`main`)
**Predecessor:** `PROJECT_ROADMAP.md` — finished 2026-11-05
**Status of this document:** new roadmap; no task has started.
**Excluded from this roadmap:** P1-6 (24-hour soak) remains waived by the
operator. Do not reopen it unless the operator explicitly un-waives it.

**Purpose:** improve the finished research platform in the areas that still
carry operational, evaluation, or product risk. This is not a rewrite and not a
reason to revisit the certainty gate, link proof, settlement identity, or
one-leg-per-book/price-source rules.

---

## 1. Current baseline

Verified on 2026-11-05:

| Check | Result |
|---|---|
| Offline suite | **1,511 passed**, 2 skipped, 1 warning, ~58 s (after N0-4) |
| Lint | `ruff check .` clean |
| Types | `mypy .` clean on 182 source files |
| Generated market doc | in sync |
| Cache after P0-1 | ~23.3 MB on the frozen 2026-11-03 nine-book cache (was 218.5 MB) |
| Scan-cache budget | 40 MB; `/api/health` reports current bytes |
| Runtime ledger | `config/generated/mapping_evidence.json` (gitignored) measured at ~41 MB locally |
| Smoke RSS | ~940 MB peak in the two-cycle P1-6 smoke, below the 1024 MB budget |
| Automated coverage | CI enforces an 80% floor; last recorded run 81.99% |

The system now has: a proof-carrying certainty gate, measured pairing evaluation,
reloadable declarations, runtime freshness and feed quarantine, opportunity-rate
telemetry, identical-feed detection, bounded evidence APIs, structured logs,
metrics, alerting, Docker/systemd deployment, manual bet log with CLV, advisory
stake limits and book-risk labels, and record-only/paper modes.

## 2. Residual findings

| # | Finding | Evidence | Impact |
|---|---|---|---|
| G1 | Tests still depend on local runtime state | The full suite fails when the gitignored 41 MB mapping ledger contains a claim that supersedes an allowlist proof in `tests/test_e2e_certified.py`; it passes with a clean ledger. | A local operator cannot trust “full suite passes” without also knowing runtime state. CI is clean only because its checkout is clean. |
| G2 | Freshness is fetch-time only | `Match.fetched_at` records when we collected a row, not when the book last moved it. `engine/live_feed.py` has a `source_updated_at` field, but the scan path does not populate or price on it. | A book can serve a frozen market with a fresh `fetched_at`; that is the classic phantom-arb source. |
| G3 | CSP still allows inline styles | `server/app.py` keeps `style-src 'unsafe-inline'`; `frontend/index.html` and `frontend/js/app.js` use `style=` for display toggles, colors and widths. | Script execution is closed, but style injection remains and the last documented CSP gap stays open. |
| G4 | CLV is manual-only | `POST /api/bets/{id}/closing` requires an operator to type closing odds. Scans already hold the last available prices. | The most valuable evaluation number is rarely populated, so “are the edges real?” remains under-measured. |
| G5 | Runtime stores grow without automatic retention | `Storage.prune_scans()` and `vacuum()` exist but nothing schedules them; `recorded_opportunities`, `paper_positions`, `bets`, `link_sweeps` and the generated ledger have no automated retention. | Long-running deployments silently accumulate rows/files; backup size and startup cost grow. |
| G6 | Coverage and mapping gaps do not alert | `coverage_budget` and `unmapped_markets` are exposed in health, but P1-5 alerts do not include them. | A whole feed or market family can disappear and only be noticed by opening Diagnostics. |
| G7 | Scan cost is not measured per book | Scheduler duration, browser slots and cache size are metrics, but not per-book request count, browser seconds, bytes or failure rate. | The research’s open question (“what does a full scan cost?”) still has no dashboard answer. |
| G8 | Paper mode is API-only and assumes full fills | P3-7 records and summarises paper positions, but there is no dashboard ledger, CSV export, retention view, rejection model or partial-acceptance model. | An operator can use paper mode only with curl, and its simulated ROI can look better than a realistic execution. |
| G9 | Candidate remediation is still mostly manual | Candidate blockers are classified, but there is no ranked alias/league suggestion or strict-miss trend, and the real queue still contains thousands of league-blocked pairs. | Operator attention stays diluted; recurring closeable pairs are not systematically surfaced. |
| G10 | No local multi-day opportunity baseline | The public 1.34% crossing reference is recorded, but the local 7-day baseline remains empty. | The project still cannot say whether its own crossing rate is normal, improving, or degraded. |
| G11 | Localization and accessibility are partial | Only a small set of labels use `data-i18n` (12 attributes at this audit); the Bosnian toggle does not translate most of the UI, and the accessibility pass is documented as manual. | The Bosnian UI is incomplete and regressions are not machine-checked. |
| G12 | Parser maintenance is reactive | Fixtures are frozen but there is no dated drift check that notices a book changing a selector, market id or response shape before a live scan fails. | The research’s “maintenance is the real failure mode” risk is only partly mitigated. |
| G13 | Release/supply-chain automation is incomplete | CI tests, audits and Bandit, but does not build the Docker image, emit an SBOM, or automate dependency updates. | Deployment and dependency drift are checked manually or not at all. |
| G14 | Pricing/identity invariants lack property-based coverage | Hand-written fixtures cover the known cases, but stake math, rounding and name-identity rules are not fuzzed against ranges. | Edge-case arithmetic or identity regressions can survive the fixed examples. |
| G15 | Market/sport admissibility is a one-off audit | `scripts/measure_sports.py` and the evidence docs are dated snapshots, not a scheduled re-audit with change detection. | A book adding or dropping a family can invalidate the evidence silently. |

## 3. Roadmap overview

`N` = next phase. Priorities follow the old roadmap: P0 is critical, P3 is
long-horizon.

| ID | Task | Priority | Effort | Depends on | Status |
|---|---|---|---|---|---|
| N0-1 | Hermetic tests independent of runtime state | P0 | S | — | Done |
| N0-2 | Source-updated timestamps and frozen-price quarantine | P0 | M | — | Done |
| N0-3 | CSP without inline styles | P0 | M | — | Done |
| N0-4 | Automatic closing-line capture for logged bets | P0 | M | N0-2 | Done |
| N1-1 | Retention and maintenance automation | P1 | M | — | Done |
| N1-2 | Coverage/mapping alerts and SLOs | P1 | S | — | Done |
| N1-3 | Per-book scan cost accounting | P1 | M | — | Done |
| N1-4 | Release hardening: Docker smoke, SBOM, dependency updates | P1 | S | — | Done |
| N2-1 | Paper ledger dashboard, CSV and retention view | P2 | M | N1-1 | Done |
| N2-2 | Realistic paper fills: rejection, partial acceptance, caps | P2 | M | N2-1 | Done |
| N2-3 | Candidate remediation and strict-miss trends | P2 | M | — | Done |
| N2-4 | Seven-day local opportunity baseline and drift gates | P2 | M | — | Deferred |
| N2-5 | Complete Bosnian localization and automated a11y checks | P2 | M | N0-3 | Done |
| N2-6 | Parser fixture refresh and drift detection | P2 | M | — | Done |
| N3-1 | Property-based pricing/identity tests and load budgets | P3 | M | N0-1 | Not started |
| N3-2 | Scheduled market/sport admissibility re-audit | P3 | M | N2-6 | Not started |

**Recommended first session:** N0-1, then N0-3 (both small and immediately
verifiable). Then N0-2/N0-4, because source freshness and automatic CLV improve
the two numbers the project still needs to trust: “is this price current?” and
“did the edge survive?”

---

## 4. Task details

### N0-1 — Hermetic tests independent of runtime state

**Status:** Done
**Priority:** P0
**Effort:** S
**Depends on:** none

**Objective:** make the offline suite produce the same result on a clean checkout
and on an operator machine with a populated runtime cache, SQLite, generated
ledger and decision stores.

**Steps:**

1. Extend `tests/conftest.py` with a shared isolation fixture (or an autouse
   default with an explicit opt-in real-state marker) that redirects
   `engine.matcher.MAPPING_EVIDENCE_FILE`, `CACHE_DIR`, `STORAGE_PATH` and every
   generated JSON/SQLite path to `tmp_path`.
2. Audit tests that read module-level runtime state (`mapping_evidence.json`,
   `last_scan.json`, `feed_integrity.json`, `api_keys.json`, decision stores)
   and make the source explicit.
3. Make `tests/test_e2e_certified.py` assert the *gate behavior* without
   depending on whether a local ledger happens to supply the same claim; keep a
   clean-ledger and populated-ledger variant.
4. Add a CI/local check that runs the suite with a deliberately populated
   ledger and with no ledger.
5. Document the isolation rule in `docs/CI.md` and the test README section.

**Acceptance criteria:**

- [x] `pytest` passes with a populated `config/generated/mapping_evidence.json`.
- [x] `pytest` passes with no generated ledger and no cache files.
- [x] No test writes into the repository's `config/generated/`, `cache/`, or
      `config/bookmaker_*` files.
- [x] The test result no longer depends on the operator's last live scan.

**Tests:**

- Updated: `tests/conftest.py` isolation fixture.
- New: `tests/test_runtime_isolation.py`.
- Existing: `tests/test_e2e_certified.py`, `tests/test_storage_migration.py`,
  `tests/test_replay.py`.

**Notes / risks:** Do not “fix” this by deleting the operator's ledger. The test
harness must redirect it, not destroy it.

---

### N0-2 — Source-updated timestamps and frozen-price quarantine

**Status:** Done
**Priority:** P0
**Effort:** M
**Depends on:** none

**Objective:** separate “when we fetched the row” from “when the book last moved
the price,” and stop pricing a row that has been frozen while peers move.

**Steps:**

1. Add an optional `source_updated_at` to the normalized match/market/odds
   models; keep `fetched_at` as the collection time.
2. Populate it from each feed that publishes a timestamp; leave it empty when
   the feed does not. Never invent one from the scan clock.
3. Add a bounded per-book observation store keyed by event/market/outcome:
   last price, first seen unchanged, last changed scan.
4. Define a frozen-price rule: unchanged for N scans while at least one peer
   moved, or a feed-provided timestamp older than the book's budget. Mark the
   row `stale_price` and refuse it in pricing; do not change the certainty gate.
5. Expose the evidence in `/api/results`, `/api/health` and feed integrity;
   show “price frozen” next to a refused leg.
6. Add fixtures for: fresh timestamp, missing timestamp, feed-provided stale
   timestamp, unchanged-but-peer-unchanged, and a genuinely stable market.
7. Document the rule and its false-positive guard in `docs/FEED_STATUS.md` and
   README.

**Acceptance criteria:**

- [x] `fetched_at` and `source_updated_at` are distinct in served data.
- [x] A frozen book cannot supply a priced leg after the configured rule fires.
- [x] A missing source timestamp fails safe to the existing fetch-time TTL, not
      to “fresh.”
- [x] A stable market with no peer movement is not quarantined.
- [x] The certainty gate's identity decisions are untouched.

**Tests:**

- New: `tests/test_stale_price.py`.
- Existing: `tests/test_freshness_api.py`, `tests/test_feed_integrity.py`,
  `tests/test_price_guard.py`, `tests/test_live_feed.py`.

**Notes / risks:** This is a price-source restriction, not a trust-rule change.
Do not treat “price did not move” as proof of badness by itself; require the
peer-movement or feed-timestamp evidence.

---

### N0-3 — CSP without inline styles

**Status:** Done
**Priority:** P0
**Effort:** M
**Depends on:** none

**Objective:** remove the last `'unsafe-inline'` from the CSP and make style
injection a non-executable dead end.

**Steps:**

1. Inventory every `style=` in `frontend/index.html` and generated HTML in
   `frontend/js/app.js`.
2. Replace display toggles with a `[hidden]`/class pattern.
3. Replace per-row colors/widths with CSS custom properties written through a
   nonce'd stylesheet, classes, or safe `style.setProperty` on an element
   (not an inline attribute string).
4. Keep a per-request nonce for the dashboard's small style block if a class is
   not practical; add `style-src 'self' 'nonce-…'` and remove
   `'unsafe-inline'`.
5. Update `server/app.py`, `frontend/index.html`, `frontend/js/app.js`,
   `frontend/css/style.css` and the security-header tests.
6. Add a string/HTML test that rejects any shipped `style="..."` attribute.

**Acceptance criteria:**

- [x] CSP has no `style-src 'unsafe-inline'`.
- [x] No shipped HTML or generated HTML contains a `style="..."` attribute.
- [x] Dashboard layout, themes, counters and book colors are unchanged.
- [x] Existing XSS and CSP nonce tests pass.

**Tests:**

- New: `tests/test_csp_styles.py`.
- Existing: `tests/test_security_headers.py`, `tests/test_csp_nonce.py`,
  `tests/test_frontend_xss.py`, `tests/test_frontend_review.py`.

**Notes / risks:** Inline *style attributes* are the gap, not font loading. Do
not add a bundler for this.

---

### N0-4 — Automatic closing-line capture for logged bets

**Status:** Done
**Priority:** P0
**Effort:** M
**Depends on:** N0-2

**Objective:** populate CLV from the scanner's own last pre-kickoff prices
instead of requiring the operator to type closing odds.

**Steps:**

1. For every open logged bet, identify its event/market/outcome and kickoff.
2. On each scan, keep the latest available odds for that outcome before kickoff;
   freeze the closing record at kickoff (or at the configured cutoff).
3. Write the closing odds only when the event, market, line, settlement and
   outcome match exactly; otherwise record “not captured” with the reason.
4. Prefer a scan-derived closing line but allow the existing manual endpoint to
   override it; label the source (`scan` vs `manual`).
5. Expose a capture count/denominator in `/api/bets/summary` and the dashboard.
6. Add fixtures for: captured before kickoff, no matching price, wrong
   settlement, manual override, and a bet with no kickoff.

**Acceptance criteria:**

- [x] A logged bet gets a closing line only from a matching pre-kickoff scan.
- [x] A missing/mismatched price leaves CLV null and says why.
- [x] Manual closing entry still works and is labelled.
- [x] Summary reports how many legs have a closing source and which.
- [x] No result is inferred after settlement.

**Tests:**

- New: `tests/test_auto_clv.py`.
- Existing: `tests/test_clv.py`, `tests/test_bet_log.py`,
  `tests/test_scan_quality.py`.

**Notes / risks:** A closing price is a measurement, not a settlement. Do not
fabricate one from the next arbitrary scan or from a different market.

---

### N1-1 — Retention and maintenance automation

**Status:** Done
**Priority:** P1
**Effort:** M
**Depends on:** none

**Objective:** bound every runtime store and make backup/restore a repeatable
operation instead of a documented manual suggestion.

**Steps:**

1. Define retention windows in `config/settings.py`: scans (90 days), link
   sweeps (90 days), paper opportunities/positions (180 days or a row cap),
   bets (never delete by default; archive only), mapping evidence (existing
   prune rule), generated logs.
2. Add `scripts/maintenance.py` with `--dry-run`, `--vacuum` and `--backup DIR`.
3. Run the bounded prune/vacuum once per day from the scheduler or startup,
   never inside a scan's critical path.
4. Add `/api/health` sizes for the SQLite DB, paper tables, bet rows and
   generated ledger; warn when a budget is crossed.
5. Document a restore drill and test that a backup restores the same row counts.
6. Add a retention test with old and recent rows for every store.

**Acceptance criteria:**

- [x] Old rows are pruned and recent rows are retained.
- [x] `--dry-run` changes nothing and reports the counts.
- [x] A backup restores identical counts and the newest scan/position.
- [x] Health exposes each store's size and last maintenance time.
- [x] No retention job can run concurrently with a scan write.

**Tests:**

- New: `tests/test_maintenance.py`.
- Existing: `tests/test_storage_migration.py`, `tests/test_bet_log.py`,
  `tests/test_paper_bankroll.py`, `tests/test_soak.py`.

**Notes / risks:** Never delete settled bets by default; they are the longitudinal
record. Archive, do not silently truncate.

---

### N1-2 — Coverage/mapping alerts and SLOs

**Status:** Done
**Priority:** P1
**Effort:** S
**Depends on:** none

**Objective:** make silent feed/market loss and mapping-coverage decay produce an
alert, not just a hidden health field.

**Steps:**

1. Add settings for the coverage-budget flag count, mapping-coverage floor and
   consecutive-scan threshold.
2. Add AlertManager kinds for `coverage_drop`, `mapping_coverage_low` and
   repeated `zero_result_reason` (`stale_data`, `no_priced_boards`).
3. Include the peer-evidence and baseline-scan count in the alert body; never
   alert on a legitimate all-zero seasonal feed.
4. Add counters and a dashboard trend line for coverage flags and unmapped rows.
5. Write the SLO definitions and their denominators in `docs/COVERAGE_BUDGET.md`
   and `docs/ALERTING.md`.

**Acceptance criteria:**

- [x] A peer-populated silent zero raises one deduped alert.
- [x] A legitimate empty feed does not alert.
- [x] Mapping coverage below the floor is visible with its numerator/denominator.
- [x] Alert failures stay off the scan path.

**Tests:**

- New: `tests/test_coverage_alerts.py`.
- Existing: `tests/test_coverage_budget.py`, `tests/test_alerts.py`,
  `tests/test_metrics.py`.

**Notes / risks:** Coverage is a warning, not a trust rule. Never drop or merge a
group because a coverage alert fired.

---

### N1-3 — Per-book scan cost accounting

**Status:** Done
**Priority:** P1
**Effort:** M
**Depends on:** none

**Objective:** answer the research question “what does a full scan cost?” per
book, not with a global estimate.

**Steps:**

1. Instrument each scraper wrapper with wall time, browser-open time, HTTP
   request count, response bytes where available, and outcome
   (`success`, `empty`, `parse_error`, `blocked`).
2. Persist a bounded per-scan per-book summary; expose it in `/api/health` and
   the Dashboard Diagnostics table.
3. Add metrics: `bh_book_seconds`, `bh_book_bytes`, `bh_book_requests`,
   `bh_book_failure_rate`.
4. Report missing measurements as null, not zero.
5. Add a CLI `scripts/scan_cost.py --days 7` that prints the per-book table and
   a cost/coverage ratio.
6. Record the first real baseline under `docs/evidence/`.

**Acceptance criteria:**

- [x] Every enabled book has time, request, byte and outcome fields or an
      explicit “not measurable” reason.
- [x] A failed/blocked book is distinguishable from an empty one.
- [x] The dashboard shows the cost table without exposing URLs, headers or
      payloads.
- [x] The report has explicit scan and book denominators.

**Tests:**

- New: `tests/test_scan_cost.py`.
- Existing: `tests/test_metrics.py`, `tests/test_soak.py`,
  `tests/test_scraper_common.py`.

**Notes / risks:** Do not log cookies, headers or bodies. Only counts, durations,
sizes and outcomes.

---

### N1-4 — Release hardening: Docker smoke, SBOM, dependency updates

**Status:** Done
**Priority:** P1
**Effort:** S
**Depends on:** none

**Objective:** make a release build, dependency update and deployment smoke test
automatic.

**Steps:**

1. Add a CI job that builds the Docker image and hits `/api/health` inside it
   (can be optional/manual if build minutes are a concern).
2. Generate an SBOM (`cyclonedx` or `pip-audit` JSON) and upload it as an
   artifact.
3. Add Dependabot/Renovate configuration grouped by runtime and dev deps.
4. Cache/restore the Playwright browser layer with the documented build time.
5. Document the release checklist and the local equivalent of each job.

**Acceptance criteria:**

- [x] A PR can prove the image builds and serves `/api/health`.
- [x] The SBOM is produced from the same requirements files the image uses.
- [x] Dependency update PRs are grouped and run the full CI.
- [x] A failed Docker smoke fails the release workflow.

**Tests:** the workflow itself; no application-test changes required.

**Notes / risks:** Keep the image job optional if the repository has a build-minute
budget; the SBOM and dependency-update jobs should still run.

---

### N2-1 — Paper ledger dashboard, CSV and retention view

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** N1-1

**Objective:** make record-only and paper mode usable without curl.

**Steps:**

1. Add a Paper tab or Diagnostics section with summary tiles (recorded,
   positions, open/settled, ROI, hit rate, CLV) and explicit denominators.
2. List recorded opportunities and paper positions with filters, paging and the
   `no_bet_placed` label.
3. Add “settle” controls mirroring the manual bet log, and show the mark reason
   when a position is unavailable.
4. Add `GET /api/paper/export.csv` for opportunities and positions.
5. Show store size and retention state from N1-1.
6. Add frontend tests for empty, open, settled and unavailable states.

**Acceptance criteria:**

- [x] No paper number appears without its denominator or “no bet placed” label.
- [x] A position can be settled from the dashboard.
- [x] CSV export round-trips every displayed row.
- [x] Record-only mode never shows a live surebet or a copy action.

**Tests:**

- New: `tests/test_paper_ui.py`.
- Existing: `tests/test_paper_bankroll.py`, `tests/test_record_only.py`,
  `tests/test_frontend_review.py`.

**Notes / risks:** Keep the paper UI read-mostly and advisory. It must not look
like a live ticket.

---

### N2-2 — Realistic paper fills: rejection, partial acceptance, caps

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** N2-1

**Objective:** stop paper ROI from assuming every leg fills at the recorded
stake.

**Steps:**

1. Add configurable paper fill rules: per-book cap, probability-free
   deterministic rejection on price movement/disappearance, partial stake.
2. Reuse the advisory book limits and risk profiles; do not invent acceptance
   odds.
3. On mark, record `filled`, `partial`, `rejected`, `missing` per leg and the
   resulting worst case.
4. Compute execution-adjusted ROI only over positions with a complete fill
   record; keep the optimistic “if all filled” number separate and labelled.
5. Document the model and its limitations in `docs/PAPER_MODE.md`.
6. Add tests for full fill, partial fill, rejection, disappearance and a
   negative worst case.

**Acceptance criteria:**

- [x] The default summary never calls an unfilled position profitable.
- [x] Partial and rejected legs are representable per leg.
- [x] Execution-adjusted and optimistic ROI use different labels and
      denominators.
- [x] No cash or account effect is simulated.

**Tests:**

- New: `tests/test_paper_fills.py`.
- Existing: `tests/test_paper_bankroll.py`, `tests/test_slip_partial_acceptance.py`,
  `tests/test_book_risk_profiles.py`.

**Notes / risks:** A paper fill is still a simulation. Do not claim it proves a
real acceptance.

---

### N2-3 — Candidate remediation and strict-miss trends

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** none

**Objective:** turn the candidate queue and strict-miss list into ranked,
reviewable work without lowering the gate.

**Steps:**

1. For each candidate, compute suggested alias/league actions from evidence
   already in the ledger and the raw spellings; label suggestions as
   proposals, never approvals.
2. Group repeated strict misses by book pair, league and spelling pattern; add a
   trend series.
3. Add a dashboard “top recurring blockers” panel with the evidence and the
   exact gate reason.
4. Add a CLI report under `scripts/` that prints the top N closeable pairs.
5. Ensure no default path can approve or apply a suggestion automatically.

**Acceptance criteria:**

- [x] A reviewer sees which candidates are closeable by an alias or league
      mapping and which are not.
- [x] Suggestions cannot alter `verified` status.
- [x] Recurring strict misses are tracked over time with denominators.
- [x] The queue size does not become a coverage-progress claim.

**Tests:**

- New: `tests/test_candidate_remediation.py`.
- Existing: `tests/test_candidate_quality.py`, `tests/test_pairing_audit.py`,
  `tests/test_candidates_api.py`.

**Notes / risks:** Keep the human/AI boundary: a suggestion is a ranked
diagnostic, not a trust decision.

---

### N2-4 — Seven-day local opportunity baseline and drift gates

**Status:** Deferred — operator deferred this task on 2026-11-05 ("skip N2-4
for now"); it is not blocked, just intentionally out of order. Do not start it
until the operator un-defers it.
**Priority:** P2
**Effort:** M
**Depends on:** none

**Objective:** replace the public-reference placeholder with a local baseline and
make a material regression visible.

**Steps:**

1. Run the scanner for at least seven days (or import an existing recorded
   history) and generate `scripts/opportunity_baseline.py --days 7`.
2. Publish crossing rate, floor-crossing rate, actionable rate, median/best
   margin and p50/p90 lifetime with denominators.
3. Define per-mode drift bands and a `--check` failure for a material drop.
4. Add the baseline date, sample count and limitations to
   `docs/evidence/`.
5. Wire the report into CI as an optional data check, never a live-feed CI job.

**Acceptance criteria:**

- [ ] The baseline has at least seven days and both modes where available.
- [ ] Every rate prints its numerator/denominator.
- [ ] A synthetic drop fails `--check`; a stable replay passes.
- [ ] The report states what the baseline cannot prove.

**Tests:**

- New: `tests/test_opportunity_baseline.py` (extend if present).
- Existing: `tests/test_opportunity_metrics.py`, `tests/test_scan_quality.py`,
  `tests/test_replay.py`.

**Notes / risks:** Do not tune filters until the baseline exists; a low number is
a finding, not a threshold to lower.

---

### N2-5 — Complete Bosnian localization and automated accessibility checks

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** N0-3

**Objective:** finish the BS/EN UI and make the accessibility claims machine-checked.

**Steps:**

1. Inventory every user-facing string in `frontend/index.html` and generated HTML
   in `frontend/js/app.js`; move them into the dictionary.
2. Add Bosnian translations and a key-coverage test that fails on a missing key.
3. Add focus-order, label, landmark and live-region assertions.
4. Add an automated accessibility runner (axe-core via Playwright/Node) for the
   main tabs and slip, with a documented allowlist for any accepted issue.
5. Re-run the keyboard-only path: scan, filter, open slip, copy stake, close.

**Acceptance criteria:**

- [x] No user-facing English string remains outside the dictionary except
      bookmaker names and data.
- [x] A missing translation fails a test.
- [x] Automated a11y checks cover the main tabs and slip.
- [x] Keyboard-only navigation still works in both languages.

**Tests:**

- New: `tests/test_i18n_coverage.py`, `tests/test_accessibility_axe.py`.
- Existing: `tests/test_pwa_accessibility.py`, `tests/test_frontend_review.py`.

**Notes / risks:** Do not translate bookmaker names or scraped team/league
labels. Those are data, not UI chrome.

---

### N2-6 — Parser fixture refresh and drift detection

**Status:** Done
**Priority:** P2
**Effort:** M
**Depends on:** none

**Objective:** notice a book's feed changing before a live scan silently loses a
market or event shape.

**Steps:**

1. Add a parser contract test per book: required top-level keys, event count,
   market id set and a small label/structure fingerprint from the frozen
   fixture.
2. Add a dated refresh command that re-captures fixtures and prints a structured
   diff (new/removed market ids, changed labels, changed shape).
3. Fail CI when a fixture is stale beyond the policy or a contract changes
   without an updated expectation.
4. Keep the distinction between “feed changed” and “capture failed,” and never
   auto-admit a new market from a drift signal.
5. Document the operator re-capture cadence and the dated evidence trail.

**Acceptance criteria:**

- [x] Every enabled book has a dated fixture and a contract fingerprint.
- [x] A changed market id set fails with a diff, not a vague parse error.
- [x] An expired fixture is visible via a script/health field.
- [x] A new market still needs the existing admissibility evidence.

**Tests:**

- New: `tests/test_parser_contracts.py`, `scripts/refresh_fixtures.py`.
- Existing: `tests/test_market_fixtures.py`,
  `tests/test_registry_parser_consistency.py`, `tests/test_market_mapping.py`.

**Notes / risks:** This automates the reminder and the diff, not the conclusion.
Do not guess a mapping from a changed payload.

---

### N3-1 — Property-based pricing/identity tests and load budgets

**Status:** Not started
**Priority:** P3
**Effort:** M
**Depends on:** N0-1

**Objective:** fuzz the arithmetic and identity invariants that fixed fixtures
cannot cover exhaustively.

**Steps:**

1. Add Hypothesis (dev-only) and generators for valid odds sets, stakes,
   rounding modes, team spellings and kickoff boundaries.
2. Assert: implied sum/profit identity, stake split worst-case, rounding loss
   non-negative, one-leg-per-book/source, no cross-sport/settlement pairing.
3. Add bounded performance tests for matcher/cache parse on generated fixture
   sizes (marked as slow, run in CI separately).
4. Keep failing cases as minimized regression fixtures.
5. Document how to run the property suite locally.

**Acceptance criteria:**

- [ ] Property tests cover the pricing and identity invariants above.
- [ ] A minimized failure becomes a normal regression test.
- [ ] Load budgets are explicit and fail on a material regression.
- [ ] The normal fast suite remains fast; slow tests are opt-in/CI-only.

**Tests:**

- New: `tests/test_properties_pricing.py`, `tests/test_properties_identity.py`,
  `tests/test_perf_budgets.py`.

**Notes / risks:** Property tests are not a replacement for the certainty-gate
fixtures. They are a second net, not a new trust rule.

---

### N3-2 — Scheduled market/sport admissibility re-audit

**Status:** Not started
**Priority:** P3
**Effort:** M
**Depends on:** N2-6

**Objective:** keep the dated admissibility evidence current instead of treating
one audit as permanent.

**Steps:**

1. Turn `scripts/measure_sports.py` and market-discovery measurements into a
   repeatable report with a stable schema.
2. Add a dated re-audit script/schedule and a change detector for per-book
   family/settlement coverage.
3. Fail or warn when a previously admitted family disappears or a newly seen
   family appears without evidence.
4. Link every admitted market/sport to its dated evidence row.
5. Keep the three-book and same-settlement rules unchanged.

**Acceptance criteria:**

- [ ] A scheduled report records per-book family and settlement coverage.
- [ ] A disappeared admitted family is visible; a new one is not auto-admitted.
- [ ] Every enabled family/sport has a dated evidence entry.
- [ ] No threshold is lowered to make a sport fit.

**Tests:**

- New: `tests/test_admissibility_audit.py`.
- Existing: `tests/test_sports.py`, `tests/test_multisport_arbitrage.py`,
  `tests/test_market_fixtures.py`.

**Notes / risks:** Admissibility remains evidence-first; this task automates the
report, not the decision.

---

## 5. Non-goals and invariants

These remain unchanged and must not be weakened by any N-task:

1. Only `verified` groups reach pricing.
2. `verified` means zero outstanding reasons, including the link half.
3. A human or AI action cannot set `deep_link_verified`; only a browser check can.
4. A missing declaration fails safe.
5. A false merge is worse than a split; no fuzzy score alone confirms identity.
6. `sport` is a hard identity gate; no cross-sport pricing.
7. Settlement is part of market identity; regulation vs overtime never pair.
8. One leg per bookmaker and one leg per price source.
9. The scanner never logs in, places a bet, moves money, or evades account limits.
10. No task may lower the certainty gate to increase the number of surebets.

## 6. Definition of done

For every task:

- Acceptance criteria are met and checked off.
- New/updated tests pass; the full offline suite, Ruff, MyPy and the generated
  market-doc check pass.
- The suite is verified both with a clean runtime state and with a populated
  generated ledger (N0-1 makes this true for every later task).
- User-facing or operator-facing docs are updated.
- The execution log below has a dated entry with commands, measured results and
  files changed.
- `docs/SESSION_BRIEF.md` is updated with the task status, next action, last
  commit and any blocker, so the next session can resume from it.
- No trust rule is weakened to make a number look better.

## 7. Execution log

Newest first. Each entry: date, task, status, commands, measured result, files
changed, follow-ups.

### 2026-11-05 — N2-6 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_parser_contracts.py tests/test_market_fixtures.py
python scripts/refresh_fixtures.py --check
python scripts/refresh_fixtures.py --write
python scripts/capture_market_fixtures.py --books betole
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
```

**Measured result**

- Operator checkout: **1,613 passed, 4 skipped, 1 warning** in 71.36 s;
  populated-ledger mode: **1,613 passed, 4 skipped, 1 warning** in 71.51 s.
- `tests/test_parser_contracts.py`: **10 passed** — real contracts match, every
  enabled book has a dated fingerprint, required keys hold, a changed market id
  / label / nested shape fails with an exact diff, an expired capture is aged,
  health exposes coverage/staleness, a contract refresh leaves the registry
  untouched, and a capture failure is not reported as drift.
- `scripts/refresh_fixtures.py --check`: **17 contracts, 0 missing books, 0
  stale**, exit 0.
- Captured a dated Betole prematch fixture (2026-11-05): 1X2, BTTS, 2.5 total
  and the experimental first-half 1X2; the prematch desk serves no double chance
  or 1.5/3.5 totals, so those rows stay declared uncovered. The registry has no
  live rows for Betole, so a live capture would require an admissibility
  decision this task must not make; health reports the missing mode.
- Ruff clean, MyPy clean on **208 source files**, Node syntax checks clean and
  the generated market doc in sync.

**Files changed**

- `engine/parser_contracts.py` — contract computation, fingerprints, structured
  diff, staleness, coverage and health block.
- `scripts/refresh_fixtures.py` — `--check`, `--write`, `--capture`, distinct
  capture-failure status, no network in the CI form.
- `scripts/capture_market_fixtures.py` — Betole prematch capturer.
- `tests/fixtures/markets/contracts.json`, `betole_prematch.json` — 17 dated
  contracts and the new capture.
- `tests/test_parser_contracts.py`, `tests/test_market_fixtures.py` — contract
  and experimental-market coverage.
- `server/api.py` — `/api/health.parser_contracts`.
- `.github/workflows/ci.yml`, `docs/CI.md`, `docs/PARSER_CONTRACTS.md`,
  `README.md`.

**Follow-ups:** N3-1 (property-based pricing/identity tests and load budgets) is
the next eligible task. N2-6 automates the reminder and the diff, never an
admission: a new id still needs the existing admissibility evidence. N2-4
remains deferred by the operator.

### 2026-11-05 — N2-5 — Done

N2-4 was deferred by the operator before this task started ("skip N2-4 for
now"); it is marked **Deferred**, not blocked, in the table above.

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
BH_ARB_TEST_BROWSER=1 python -m pytest tests/test_accessibility_axe.py
python -m pytest tests/test_i18n_coverage.py
python scripts/a11y_audit.py --axe /tmp/opencode/axe/node_modules/axe-core/axe.min.js
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
node --check frontend/js/app.js
node --check frontend/js/i18n.js
```

**Measured result**

- Operator checkout: **1,598 passed, 4 skipped, 1 warning** in 60.72 s;
  populated-ledger mode: **1,598 passed, 4 skipped, 1 warning** in 60.44 s. The
  four skips are the two opt-in runtime-state checks plus the two Chromium tests
  when `BH_ARB_TEST_BROWSER` is unset.
- `tests/test_i18n_coverage.py`: **12 passed** — every `data-i18n`/`tr()` key has
  Bosnian copy, placeholders are preserved, the reason table has `*_bs` for every
  case, no shipped HTML text or accessible attribute is outside the catalog, and
  the language switch repaints generated views.
- `tests/test_accessibility_axe.py` (browser mode): **8 passed** — static
  landmark/name/tab/duplicate-id/focus-order checks, the axe runner contract, the
  live audit over all six tabs plus the synthetic slip, and the keyboard-only
  path (scan → filter → open slip → copy stake → close) in English and Bosnian.
- Live axe run: **0 violations** over the six tabs and the slip; light and dark
  schemes both clean. The reviewed allowlist is empty.
- Ruff clean, MyPy clean on **205 source files**, Node syntax checks clean and
  the generated market doc in sync.

**Files changed**

- `frontend/js/i18n.js` — Bosnian catalog, gettext-style English keys and
  placeholder copy.
- `frontend/js/no-surebet-reasons.json` — `title_bs`/`body_bs` and live variants
  for every diagnostic case.
- `frontend/js/app.js` — `tr()`, attribute/HTML translation, localized generated
  chrome, `refreshLocalizedViews()`, translated diagnostics, Escape closes the
  slip, `h1`/heading fixes.
- `frontend/index.html`, `frontend/css/style.css` — catalog hooks on every static
  string and accessible attribute, skip/landmark/slip semantics, readable
  contrast tokens, `sr-only` helper, brand `h1`.
- `frontend/sw.js` — cache `i18n.js`; shell version bumped.
- `scripts/a11y_audit.py` — Playwright audit for tabs and slip, optional
  axe-core, built-in DOM rules, empty documented allowlist.
- `tests/test_i18n_coverage.py`, `tests/test_accessibility_axe.py`,
  `tests/test_pwa_accessibility.py`, `tests/test_frontend_empty_state.py`,
  `tests/test_paper_ui.py`, `tests/test_slip_partial_acceptance.py`,
  `tests/test_coverage_budget.py`, `tests/test_candidate_quality.py`,
  `tests/test_csp_nonce.py`.
- `docs/ACCESSIBILITY.md`, `docs/PWA_ACCESSIBILITY.md`, `README.md`.

**Follow-ups:** N2-6 (parser fixture refresh and drift detection) is the next
eligible task once the deferred N2-4 is left out of order. Localization does not
translate scraped data, and no trust rule, pricing rule or price-source identity
changed.

### 2026-11-05 — N2-3 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_candidate_remediation.py
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/candidate_remediation.py --top 5
node --check frontend/js/app.js
```

**Measured result**

- Operator checkout: **1,580 passed, 2 skipped, 1 warning** in 92.23 s;
  populated-ledger mode: **1,580 passed, 2 skipped, 1 warning** in 83.35 s.
- `tests/test_candidate_remediation.py`: **18 passed** — alias/league/
  alias+league/none actions, exact gate reasons, quarantined-ledger evidence,
  proposal-only guarantees, recurring grouping with queue denominators, strict
  miss grouping (book pair, league, spelling), the per-scan trend, the API and
  health payloads, and the offline CLI (including the no-cache exit).
- Real cached scan (`cache/last_scan.json`, 8,844 listings): the CLI rebuilt
  **8,622 candidates**, of which **2,633** are closeable by a proposed mapping
  (alias 1,065, league 1,098, alias+league 470) and 5,989 are not; it printed
  the top proposals with ledger state and `applied=False`. No runtime file was
  written.
- Ruff clean, MyPy clean on **202 source files**, Node syntax check clean and
  the generated market doc in sync.

**Files changed**

- `engine/candidate_remediation.py` — proposal builders, ledger evidence,
  closeable/action classification, queue grouping and denominator-carrying
  summary. No trust write path.
- `models/schemas.py` — `PairSide.league`/`league_normalized`,
  `RemediationProposal`, `CandidateRemediation`, `CandidateReview.remediation`.
- `server/api.py` — hypothetical alias/league verdicts (discarded immediately),
  per-candidate remediation, `/api/candidates` closeable counts,
  `/api/health.candidate_remediation` and `pairing_trend`, bounded
  strict-miss and blocker trends.
- `scripts/pairing_audit.py` — `strict_miss_groups` by book pair, league and
  spelling pattern with miss and listing denominators.
- `scripts/candidate_remediation.py` — offline top-N closeable report
  (`--cache`, `--top`, `--json`), AI ranking disabled, no network.
- `frontend/index.html`, `frontend/js/app.js`, `frontend/css/style.css` —
  "Top recurring blockers" panel, strict-miss sparkline, per-card proposal
  block with ledger state and gate reasons.
- `tests/test_candidate_remediation.py`, `tests/test_frontend_review.py`,
  `tests/test_scan_candidates.py`, `tests/conftest.py`.
- `docs/CANDIDATE_REMEDIATION.md`, `README.md`.

**Follow-ups:** N2-4 (seven-day local opportunity baseline and drift gates) is
the next eligible task. A proposal is a ranked diagnostic: it cannot change
`verified`, the ledger, the allowlist or a candidate's status, and the link half
remains a machine check.

### 2026-11-05 — N2-2 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_paper_fills.py
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
node --check frontend/js/app.js
```

**Measured result**

- Operator checkout: **1,561 passed, 2 skipped, 1 warning** in 59.19 s;
  populated-ledger mode: **1,561 passed, 2 skipped, 1 warning** in 59.23 s.
- `tests/test_paper_fills.py`: **8 passed** — full fill, per-book partial cap,
  moved-price rejection, negative worst case, disappearance/missing, price
  tolerance, disabled fills, filled-stake settlement and CSV fill columns.
- Ruff clean, MyPy clean on **199 source files**, Node syntax check clean and
  the generated market doc in sync.

**Files changed**

- `config/settings.py` — `PAPER_FILL_ENABLED`,
  `PAPER_FILL_PRICE_TOLERANCE`, `PAPER_FILL_PARTIAL_ENABLED`.
- `server/paper.py` — per-leg fill statuses and reasons, filled/planned stake,
  worst case, execution-adjusted summary, filled-stake settlement and CSV fill
  fields.
- `frontend/index.html`, `frontend/js/app.js` — execution-adjusted vs optimistic
  summary and fill details in the mark cell.
- `tests/test_paper_fills.py`, `tests/test_paper_ui.py`,
  `docs/PAPER_MODE.md`.

**Follow-ups:** N2-3 (candidate remediation and strict-miss trends) is the next
eligible task. A paper fill remains a deterministic simulation: no account,
cash, acceptance or limit effect is modelled, and no certainty-gate or pricing
rule changed.

### 2026-11-05 — N2-1 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_paper_ui.py
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
node --check frontend/js/app.js
```

**Measured result**

- Operator checkout: **1,553 passed, 2 skipped, 1 warning** in 58.64 s;
  populated-ledger mode: **1,553 passed, 2 skipped, 1 warning** in 58.84 s.
- `tests/test_paper_ui.py`: **7 passed** — paging/totals, filters, CSV
  round-trip, API settle, unavailable reason, read-only paper tab and a
  Node-driven empty/open/settled/unavailable render check.
- Ruff clean, MyPy clean on **198 source files**, Node syntax check clean and
  the generated market doc in sync.

**Files changed**

- `server/paper.py` — offset/filter paging, counts, CSV export, mark reasons.
- `server/api.py` — paged paper endpoints, CSV endpoint, store/retention block.
- `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js` —
  Paper tab, summary tiles with denominators, filters/paging, settle controls,
  unavailable reason, export link.
- `tests/test_paper_ui.py`, `tests/test_other_sports_frontend.py`,
  `tests/test_frontend_xss.py`, `docs/PAPER_MODE.md`.

**Follow-ups:** N2-2 (realistic paper fills) is the next eligible task. No
certainty-gate, link-proof, settlement, price-source or one-leg-per-book rule
changed; the paper UI remains read-mostly and never places a bet.

### 2026-11-05 — N1-4 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_deployment_assets.py
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python - <<'PY'  # YAML parse of every workflow and Dependabot config
PY
cyclonedx-py requirements requirements.txt --of JSON --output-reproducible -o sbom.cdx.json
python scripts/docker_smoke.py --image bh-arb:n14-smoke --port 18000
```

**Measured result**

- Operator checkout: **1,546 passed, 2 skipped, 1 warning** in 58.19 s;
  populated-ledger mode: **1,546 passed, 2 skipped, 1 warning** in 58.82 s.
- `tests/test_deployment_assets.py`: **14 passed**, including the Docker cache,
  SBOM, Dependabot grouping and release-workflow assertions.
- SBOM generation locally produced **8 components** with CycloneDX spec **1.6**
  from `requirements.txt`; all workflow/Dependabot YAML parsed.
- Ruff clean, MyPy clean on **197 source files**, generated market doc in sync.
- **Local Docker smoke blocked:** this machine's user is not in the `docker`
  group, so `docker build` cannot reach `/var/run/docker.sock` (`permission
  denied`). The workflow itself is the PR/release gate and is structurally
  validated; a CI runner with Docker access will execute it.

**Files changed**

- `requirements-dev.txt` — `cyclonedx-bom==8.0.1` for the SBOM job.
- `.github/workflows/ci.yml` — new `sbom` job and artifact upload.
- `.github/workflows/docker.yml` — Buildx + GHA layer cache.
- `.github/workflows/release.yml` — tag/manual SBOM + Docker smoke; smoke
  failure fails the release.
- `.github/dependabot.yml` — grouped runtime, dev and GitHub Actions updates.
- `Dockerfile` — separate pip and Chromium layers with the documented build
  time; `.gitignore`/`.dockerignore` exclude SBOM artifacts.
- `docs/RELEASE.md`, `docs/CI.md`, `docs/DEPLOYMENT.md`, `README.md`.
- `tests/test_deployment_assets.py`.

**Follow-ups:** N2-1 (paper ledger dashboard, CSV and retention view) is the next
eligible task. The local Docker smoke remains an environment limitation, not a
repository blocker.

### 2026-11-05 — N1-3 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_scan_cost.py
python scripts/scan_cost.py --days 7
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
node --check frontend/js/app.js
```

**Measured result**

- Operator checkout: **1,542 passed, 2 skipped, 1 warning** in 58.72 s;
  populated-ledger mode: **1,542 passed, 2 skipped, 1 warning** in 58.76 s.
- `tests/test_scan_cost.py`: **12 passed** — wall/browser/request/byte fields,
  null `n/a` reasons, blocked vs parse error vs empty, report totals, bounded
  aggregation, failure rate, CLI denominators, metrics and health.
- `scripts/scan_cost.py --days 7` ran cleanly; this session had no live scan, so
  it correctly reported **0 scans / 0 books** rather than inventing a cost.
- Ruff clean, MyPy clean on **197 source files**, Node syntax check clean and
  the generated market doc in sync.

**Files changed**

- `scrapers/cost.py` — context collector, browser/request/byte instrumentation,
  outcome classification and scan report.
- `scrapers/base.py`, `scrapers/admiralbet.py`, `scrapers/mozzartbet.py`,
  `scrapers/wwin.py`, `scrapers/premier_kladionica.py` — measured browser
  navigation and HTTP paths.
- `server/scan_cost.py` — bounded history aggregation and failure rates.
- `server/api.py` — per-scan records, `/api/health.scan_cost`, cost metrics and
  save/restore.
- `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js` —
  Diagnostics cost table.
- `scripts/scan_cost.py`, `tests/test_scan_cost.py`, `tests/conftest.py`.
- `docs/SCAN_COST.md`,
  `docs/evidence/2026-11-05-scan-cost-baseline.md`.

**Follow-up:** the first live baseline is still pending because this session ran
no live scan; the dated evidence slot and CLI are ready. N1-4 (release
hardening) is the next eligible task. No certainty-gate, link-proof,
settlement, price-source or one-leg-per-book rule changed.

### 2026-11-05 — N1-2 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_coverage_alerts.py
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
node --check frontend/js/app.js
```

**Measured result**

- Operator checkout: **1,530 passed, 2 skipped, 1 warning** in 59.56 s;
  populated-ledger mode: **1,530 passed, 2 skipped, 1 warning** in 58.93 s.
- `tests/test_coverage_alerts.py`: **11 passed** — numerator/denominator,
  per-scan delta, legitimate empty feed, peer/baseline evidence, deduped silent
  zero, mapping floor, consecutive zero threshold, health exposure, metrics and
  the dashboard trend.
- Ruff clean, MyPy clean on **193 source files**, Node syntax check clean and
  the generated market doc in sync.

**Files changed**

- `config/settings.py` — coverage flag threshold, mapping-coverage floor and
  minimum denominator, consecutive-scan threshold.
- `engine/coverage_budget.py` — peer row/book evidence and the per-scan mapping
  coverage numerator/denominator.
- `server/alerts.py` — `coverage_drop`, `mapping_coverage_low` and
  `zero_result_reason` builders.
- `server/api.py` — per-scan coverage state, trend, consecutive counters,
  metrics, health fields and alert wiring.
- `frontend/index.html`, `frontend/css/style.css`, `frontend/js/app.js` —
  Diagnostics coverage trend line.
- `tests/test_coverage_alerts.py`, `tests/conftest.py`.
- `docs/COVERAGE_BUDGET.md`, `docs/ALERTING.md`.

**Follow-ups:** N1-3 (per-book scan cost accounting) is the next eligible task.
Coverage remains a warning: no certainty-gate, link-proof, settlement,
price-source or one-leg-per-book rule changed.

### 2026-11-05 — N1-1 — Done

**Commands**

```bash
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m pytest tests/test_maintenance.py
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/maintenance.py --dry-run
```

**Measured result**

- Operator checkout: **1,519 passed, 2 skipped, 1 warning** in 58.15 s;
  populated-ledger mode: **1,519 passed, 2 skipped, 1 warning** in 58.50 s.
- `tests/test_maintenance.py`: **8 passed** — old/recent rows for every store,
  dry-run no-write, backup/restore counts and newest rows, paper row cap,
  scan/maintenance overlap guard, health sizes/last run and both scheduler
  paths.
- Operator dry run: scans/link sweeps/paper/bets pruned 0, ledger 7,292 claims
  with 0 evidence dropped, SQLite 86,016 bytes, no budget warnings; the
  checkout's runtime state was unchanged.
- Ruff clean, MyPy clean on **192 source files**, generated market doc in sync.

**Files changed**

- `config/settings.py` — retention windows, daily schedule, archive window and
  soft size/row budgets.
- `server/maintenance.py` — bounded runner, dry-run, archive, vacuum, backup,
  process-wide guard and read-only store inventory.
- `server/storage.py` — dry-run counts, link-sweep prune, maintenance marker.
- `server/paper.py` — age and newest-row cap for recorded opportunities and
  paper positions.
- `server/bets.py` — settled-bet archive query; no delete path.
- `server/scheduler.py`, `server/app.py` — daily maintenance loop in the
  lifespan, off the scan path.
- `server/api.py` — `/api/health.retention` and the scan-start guard.
- `scripts/maintenance.py` — `--dry-run`, `--vacuum`, `--backup DIR`.
- `tests/test_maintenance.py`, `docs/STORAGE.md`, `docs/DEPLOYMENT.md`.

**Follow-ups:** N1-2 (coverage/mapping alerts and SLOs) is the next eligible
task. No certainty-gate, link-proof, settlement, price-source or
one-leg-per-book rule changed.

### 2026-11-05 — N0-4 — Done

**Commands**

```bash
python -m pytest                                      # empty ledger
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest # populated ledger
python -m pytest                                       # clean copy, no config/generated or cache
node --check frontend/js/app.js
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
```

**Measured result**

- Operator checkout: **1,511 passed, 2 skipped** in both ledger modes.
- Throwaway copy with no `config/generated/` and no `cache/`: **1,511 passed,
  2 skipped** in both ledger modes.
- `tests/test_auto_clv.py` covers pre-kickoff capture, missing price, wrong
  settlement, line mismatch, missing book, missing kickoff, post-kickoff freeze,
  settled bets, manual override and the summary sources.
- Ruff, MyPy (189 files), Node syntax check and the generated market doc are
  clean.

**Files changed**

- `engine/closing_line.py` — exact event/market/line/settlement/outcome
  matching, pre-kickoff capture, freeze and reason codes.
- `server/bets.py` — open-bet scan, capture write, manual source labelling,
  closing summary and CSV source/reason columns.
- `server/api.py` — bet identity enrichment, scan capture, `/api/bets/summary`
  and `/api/health` capture counts.
- `engine/arbitrage.py`, `engine/destinations.py`, `models/schemas.py` —
  `event_key` and per-leg settlement/period on served surebets.
- `frontend/js/app.js` — log the identity fields; show closing coverage on the
  bet-log line.
- `config/settings.py` — `CLOSING_CAPTURE_CUTOFF_MINUTES`.
- `tests/test_auto_clv.py`, `docs/BET_LOG.md`.

**Follow-ups:** none. N1-1 (retention/maintenance) is the next eligible task.

### 2026-11-05 — N0-3 — Done

**Commands**

```bash
python -m pytest                                      # empty ledger
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest # populated ledger
python -m pytest                                       # clean copy, no config/generated or cache
node --check frontend/js/app.js
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
```

**Measured result**

- Operator checkout: **1,499 passed, 2 skipped** in both ledger modes.
- Throwaway copy with no `config/generated/` and no `cache/`: **1,499 passed,
  2 skipped** in both ledger modes.
- `style-src` is now `'self' https://fonts.googleapis.com` with no
  `'unsafe-inline'`; no shipped HTML or generated HTML carries a style
  attribute. The dashboard uses `[hidden]`, CSS classes and CSSOM custom
  properties for colours and progress widths.
- Ruff, MyPy (187 files), Node syntax check and the generated market doc are
  clean.

**Files changed**

- `server/app.py` — removed `style-src 'unsafe-inline'` and updated the policy
  rationale.
- `frontend/index.html` — five `style="display:none"` toggles replaced with
  `hidden`.
- `frontend/js/app.js` — display toggles use `hidden`; book colours and progress
  widths use `style.setProperty` on generated elements; no style attribute
  templates remain.
- `frontend/css/style.css` — progress widths driven by `--progress` and
  `--scan-progress`; existing `[hidden] { display:none !important; }` rule is
  now the single display toggle.
- `tests/test_csp_styles.py` — CSP, no-inline-style and CSSOM checks.
- `tests/test_frontend_empty_state.py` — bookmaker-wall predicate updated for the
  `[hidden]` rule instead of inline `style.display`.
- `docs/ACCEPTANCE.md`, `docs/PRODUCTION_READINESS.md` — CSP gap marked closed.

**Follow-ups:** none. Dashboard layout, themes, counters and book colours are
unchanged; only the mechanism that sets them changed.

### 2026-11-05 — N0-2 — Done

**Commands**

```bash
python -m pytest                                      # empty ledger
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest # populated ledger
python -m pytest                                       # clean copy, no config/generated or cache
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
```

**Measured result**

- Operator checkout: **1,494 passed, 2 skipped** in both ledger modes.
- Throwaway copy with no `config/generated/` and no `cache/`: **1,494 passed,
  2 skipped** in both ledger modes.
- `tests/test_stale_price.py` covers a fresh feed timestamp, a missing timestamp,
  a feed timestamp past the budget, an unchanged price with stable peers, an
  unchanged price while an independent peer moves, a changed-price reset, the
  bounded store, the served clocks, MaxBet timestamp parsing, and the API/feed
  evidence.
- Ruff, MyPy (186 files) and the generated market doc are clean.

**Files changed**

- `models/schemas.py` — `source_updated_at` on `Match`, `Market`, `OddsValue`,
  `SurebetStake` and `Surebet`; per-row stale flags.
- `engine/stale_price.py` — bounded observation store, two refusal rules, peer
  movement by independent price source, evidence rows.
- `engine/arbitrage.py` — stale markets are never priced; served stakes carry
  both `fetched_at` and `source_updated_at`.
- `engine/feed_integrity.py` — per-book `stale_price_rows`.
- `engine/live_feed.py` — frame `source_updated_at` propagated to rows without
  one.
- `scrapers/maxbet.py` — parse per-outcome `updateDate`/`providerTimestamp`.
- `server/api.py`, `server/app.py` — scan/verify integration, persistence,
  `/api/results`, `/api/health` and feed-integrity evidence.
- `frontend/js/app.js` — **price frozen** badge in the feed-integrity strip.
- `config/settings.py` — threshold, row cap and retention settings.
- `tests/test_stale_price.py`, `tests/test_live_feed.py`, `tests/conftest.py`.
- `docs/FEED_STATUS.md`, `README.md`.

**Follow-ups:** N0-4 can build on the source timestamps and the observation
store. No trust rule changed; the certainty gate, settlement identity and
one-leg-per-book/source rules are untouched.

### 2026-11-05 — N0-1 — Done

**Commands**

```bash
python -m pytest                                      # empty ledger
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest # populated ledger
python scripts/check_test_isolation.py --pytest-args "tests/test_runtime_isolation.py tests/test_e2e_certified.py tests/test_replay.py -q"
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
```

**Measured result**

- Operator checkout with the 41 MB populated ledger: **1,481 passed, 2 skipped**
  (was 1 failed / 1,475 passed before the fix). The 2 skips are the opt-in
  `real_runtime_state` corpus check and its deeplink-config sibling.
- Same checkout with `BH_ARB_TEST_RUNTIME_LEDGER=populated`: **1,481 passed,
  2 skipped**.
- Throwaway copy with no `config/generated/` and no `cache/`: **1,481 passed,
  2 skipped** in both ledger modes.
- The session guard reported no changes to the checkout's `config/generated/` or
  `cache/`.
- Ruff, MyPy (184 files) and the generated market doc are clean.

**Files changed**

- `tests/conftest.py` — autouse runtime-state redirect, populated-ledger seed,
  `real_runtime_state` marker and a session guard against repo writes.
- `tests/test_runtime_isolation.py` — new direct proofs of the redirect, writes,
  SQLite store and env modes.
- `tests/test_e2e_certified.py` — explicit clean-ledger fixture and a
  populated-ledger variant of the gate claim.
- `tests/test_replay.py`, `scripts/replay_mappings.py` — replay takes an explicit
  `--ledger`, so it no longer reads the operator's generated evidence.
- `tests/test_deeplinks.py` — the captured-scan corpus check is now opt-in.
- `scripts/check_test_isolation.py`, `.github/workflows/ci.yml` — local and CI
  checks for both ledger modes.
- `docs/CI.md`, `README.md` — isolation rule and commands.

**Follow-ups:** none. N3-1 (property tests) can now rely on the shared isolation
fixture. N0-2 is the next eligible task.

*(No earlier task has started.)*

---

## 8. Quick reference

```bash
python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check
python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check
```

Useful starting points:

| Concern | File |
|---|---|
| Test isolation | `tests/conftest.py`, `tests/test_e2e_certified.py` |
| Freshness / feed integrity | `engine/feed_integrity.py`, `server/api.py` |
| CSP and headers | `server/app.py` |
| Bet log / CLV | `server/bets.py`, `docs/BET_LOG.md` |
| Paper mode | `server/paper.py`, `docs/PAPER_MODE.md` |
| Retention / backup | `server/storage.py`, `docs/STORAGE.md` |
| Coverage / alerts | `engine/coverage_budget.py`, `server/alerts.py` |
| Metrics | `server/observability.py`, `server/api.py` |
| Parsers / fixtures | `scrapers/`, `tests/fixtures/markets/`, `scripts/capture_market_fixtures.py` |
