# 07 — Roadmap migration inventory

Describes the repository before the 2026-11-07 roadmap migration.

Read-only investigation for the planned deletion of `PROJECT_ROADMAP.md` and
`PROJECT_ROADMAP_V2.md`, the move of `docs/research/scraper-map/*` to the repo
root, and the `AGENTS.md` rewrite. Written 2026-11-07.

## Files inspected

- `AGENTS.md` (95 lines, whole), `TODO.md` (92, whole)
- `PROJECT_ROADMAP_V2.md` (1,551 lines: 1-95, 550-609, 728-892, 1527-1551; headers + all `Follow-ups`)
- `PROJECT_ROADMAP.md` (2,387 lines: 1-30, 82-158, 250-290, 711-759, 1398-1437, 2338-2387; headers)
- `docs/SESSION_BRIEF.md` (76, whole), `docs/ACCEPTANCE.md` (1-20, 280-300, 470-485), `docs/CI.md` (75-95), `docs/SOAK.md` (1-12)
- `.github/workflows/ci.yml` (185, whole), `pyproject.toml` (1-60)
- `README.md` (414-435 + grep), `ScraperLogic.md`, `MARKET_MAPPING.md` (grep only)
- `docs/research/scraper-map/00_README.md` (whole), `SCRAPER_TODO.md` (headers), `03_fixtures_and_pain_points.md` (grep)
- Greps: `PROJECT_ROADMAP`, `ROADMAP` (case-insensitive), `\b(P[0-3]|N[0-3])-\d\b`, `docs/research`, roadmap/task IDs in `engine/ server/ scrapers/ models/ frontend/ scripts/ tests/ .github/ config/ deploy/ Dockerfile`

## Findings

### 1. References to the roadmap files

**No code, script, test or CI workflow reads, parses, globs or opens either
roadmap file.** A roadmap deletion cannot break the build, the suite or CI.
Every non-roadmap reference is prose (prose does not fail, but it dangles):

| Location | Text |
|---|---|
| `AGENTS.md:5` | `PROJECT_ROADMAP_V2.md` — current roadmap… |
| `AGENTS.md:10` | predecessor roadmap (`PROJECT_ROADMAP.md`) is finished |
| `TODO.md:3` | `PROJECT_ROADMAP_V2.md` is complete; N2-4 deferred |
| `docs/SESSION_BRIEF.md:4` | keep `PROJECT_ROADMAP_V2.md` complete |
| `docs/RESEARCH_ARBITRAGE_2026-11-04.md:9` | separate from `PROJECT_ROADMAP.md` |
| `docs/CI.md:84` | "the note in the roadmap" (80% floor rationale) |
| `docs/SOAK.md:6` | "The roadmap keeps P1-6 `In progress`" |
| `tests/test_deployment_assets.py:5` | docstring "deployment the roadmap promises" (comment only) |
| `docs/research/scraper-map/SCRAPER_TODO.md:4` | separate from `PROJECT_ROADMAP_V2.md` |
| `docs/research/scraper-map/03_fixtures_and_pain_points.md:27,196,198` | cites **line ranges** `44-56, 557-580, 635-675`, `:77, 557-564` |
| `PROJECT_ROADMAP_V2.md:5,838,890` | self-reference / predecessor |
| `PROJECT_ROADMAP.md:2269,2307,2334` | self-reference in its own log |

The only genuinely fragile citations are `03_fixtures_and_pain_points.md:27,196,198`:
they quote line numbers that disappear with the file. They must be rewritten to
a named task or a quoted sentence.

### 2. Task-ID references outside the roadmaps (labels only, nothing parses them)

`scripts/`: `refresh_fixtures.py:1` (N2-6), `discover_push_feeds.py:2` (P2-10),
`audit_admissibility.py:1` (N3-2), `docker_smoke.py:2` (P1-3),
`capture_market_fixtures.py:1196` (N2-6), `check_test_isolation.py:3` (N0-1),
`a11y_audit.py:1` (N2-5), `maintenance.py:2` (N1-1), `scan_cost.py:2` (N1-3),
`audit_deeplinks.py:2` (P2-2), `evaluate_matching.py:2` (P2-4),
`sweep_links.py:2` (P2-1); comments: `deploy/bh-arb.service:1`,
`Dockerfile:3` (both P1-3).

`tests/` (all first-line docstrings unless noted): `test_feed_integrity.py:1`
(P0-7), `test_coverage_alerts.py:1` (N1-2), `test_frontend_review.py:183,271`
(N2-3), `test_certainty.py:498` (F1/P0-1), `test_identity_edge_cases.py:1`
(P2-8), `test_paper_bankroll.py:1` + `test_record_only.py:1` (P3-7),
`test_i18n_coverage.py:1` + `test_accessibility_axe.py:1` (N2-5),
`test_skin_detection.py:1` (P2-7), `test_maintenance.py:1` (N1-1),
`test_live_feed.py:1` (P2-10), `test_stale_price.py:1` (N0-2),
`test_frontend_empty_state.py:941` (N0-3), `test_groups_api.py:1` (P1-1),
`conftest.py:3,135,140,186,235,241,250` (N0-1/N0-2/N1-2/N2-3),
`test_storage_migration.py:1` (P3-1), `test_pwa_accessibility.py:1` (P3-4),
`test_auto_clv.py:1` (N0-4), `test_properties_pricing.py:1` (N3-1),
`test_csp_styles.py:1` (N0-3), `test_link_sweep.py:1` (P2-1),
`test_alerts.py:1` (P1-5), `test_e2e_certified.py:407` (P0-1),
`test_pricing_invariant.py:1` (P1-7), `test_freshness_api.py:1` (P0-4),
`test_metrics.py:1` + `test_request_id.py:1` (P1-2),
`test_opportunity_metrics.py:1` (P0-6), `test_frontend_evidence.py:1` (P1-1),
`test_ci_hardening.py:1` (P1-4), `test_scan_cost.py:1` (N1-3),
`test_parser_contracts.py:1` (N2-6), `test_coverage_budget.py:1` (P2-9),
`test_deployment_assets.py:1` (P1-3), `test_slip_partial_acceptance.py:1` (P3-3).

`docs/*.md` label their own subjects with roadmap IDs (these IDs are *defined*
only in the old roadmap): `ACCEPTANCE.md:22,56,84,105,145,186,210,262,284,293,325,355`;
`AUTH.md:1`; `BET_LOG.md:1,43,53,73`; `BOOK_RISK.md:1`; `COVERAGE_BUDGET.md:3,40,78`;
`ALERTING.md:3`; `PAPER_MODE.md:1,64,144,173`; `ACCESSIBILITY.md:1`;
`ADMISSIBILITY_AUDIT.md:1,10`; `CANDIDATE_REMEDIATION.md:1`;
`MULTISPORT_EVIDENCE.md:7,303`; `CI.md:3,19,57`; `FEED_STATUS.md:19`;
`DEPLOYMENT.md:163`; `PARSER_CONTRACTS.md:1`; `PROPERTY_TESTS.md:1`;
`RELEASE.md:1`; `SCAN_COST.md:1`; `SKIN_DETECTION.md:4`; `SOAK.md:1,6,88,95`;
`STORAGE.md:1,37`; `RESEARCH_ARBITRAGE_2026-11-04.md:366-373`;
`SESSION_BRIEF.md:5,6,8,13,41,63,70`.

`ScraperLogic.md` and `MARKET_MAPPING.md` contain **zero** roadmap or task-ID
references.

### 3. V2 content that must survive

**N2-4 (lines 557-595), the only deferred task — carry verbatim:**
> **Status:** Deferred — operator deferred this task on 2026-11-05 ("skip N2-4
> for now"); it is not blocked, just intentionally out of order. Do not start it
> until the operator un-defers it. **Priority:** P2. **Effort:** M. **Depends on:** none.
> **Objective:** replace the public-reference placeholder with a local baseline
> and make a material regression visible.
> **Steps:** 1. Run the scanner for at least seven days (or import an existing
> recorded history) and generate `scripts/opportunity_baseline.py --days 7`.
> 2. Publish crossing rate, floor-crossing rate, actionable rate, median/best
> margin and p50/p90 lifetime with denominators. 3. Define per-mode drift bands
> and a `--check` failure for a material drop. 4. Add the baseline date, sample
> count and limitations to `docs/evidence/`. 5. Wire the report into CI as an
> optional data check, never a live-feed CI job.
> **Acceptance (all unchecked):** at least seven days and both modes; every rate
> prints numerator/denominator; a synthetic drop fails `--check` and a stable
> replay passes; the report states what the baseline cannot prove.
> **Tests:** new `tests/test_opportunity_baseline.py`; existing
> `test_opportunity_metrics.py`, `test_scan_quality.py`, `test_replay.py`.
> **Notes / risks:** do not tune filters until the baseline exists; a low number
> is a finding, not a threshold to lower.

`scripts/opportunity_baseline.py` exists (docstring at `:9`), so only the data,
the drift bands and the acceptance evidence are missing.

**P1-6 (waived, not done).** V2 header `:7-8` and old roadmap `:723-729`:
> Excluded from this roadmap: P1-6 (24-hour soak) remains waived by the operator.
> Do not reopen it unless the operator explicitly un-waives it.
>
> **Status:** Waived and excluded from roadmap completion — the operator skipped
> the 24-hour run on 2026-11-04. The harness, budget guard and two-cycle smoke
> evidence remain in `docs/SOAK.md`. The unchecked acceptance boxes are retained
> so the waiver is not mistaken for a passed 24-hour run.

Old-roadmap acceptance boxes `:748-751` (24 h run, no surviving browser; memory
plateaus below budget; no book silently absent; report reproducible) and the
6/10-cycle plateau evidence (`:470-480`: 592.8 → ~767 MB, plateau after cycle 7,
29.45% growth).

**Standing rules defined only in the roadmap:**
- V2 `:753-766` non-goals + the 10 trust invariants (duplicated in AGENTS.md,
  except invariant 1 in AGENTS says "reach pricing", roadmap says
  "reach `engine/arbitrage.py`").
- V2 `:768-782` Definition of done: acceptance checked; new/updated tests; full
  suite + Ruff + MyPy + market-doc check; **suite verified in both clean and
  populated-ledger modes**; docs updated; dated execution-log entry with commands,
  measured results and files changed; `docs/SESSION_BRIEF.md` updated; no trust
  rule weakened.
- V2 `:17-31` baseline table — stale: 1,511 tests, 182 MyPy files, 81.99%
  coverage, cache 23.3 MB, ledger 41 MB, smoke RSS 940 MB, 40 MB cache budget.
  Current numbers live in `docs/SESSION_BRIEF.md:14-19` (1,733 passed, 6 skipped,
  1 xfailed, 85.63%, 11,639 statements, 218 MyPy files) and `docs/CI.md:80-83`.
- V2 `:1529-1551` quick reference (4 commands + replay; where-to-look table).
- V2 `:83-86` recommended first session (now historical).
- Residual findings G1-G15 (`:39-57`) — G10 (no local baseline) and G12 (parser
  maintenance reactive) are the two that became deferred/backlog work.

**Execution log, newest 10 (lines 789-1300), each Done 2026-11-05:**

| Line | Task | Headline measured result |
|---|---|---|
| 789 | N3-2 admissibility re-audit | 1,645 passed / 6 skipped; 84.02%; 4 sports, 12 markets, 0 failures; MyPy 214 files |
| 846 | N3-1 property tests + load budgets | 1,629 passed / 6 skipped; matcher 600 listings 0.43 s (10 s), cache 2,000+500 0.16 s (5 s); MyPy 211 |
| 899 | N2-6 parser fixtures + drift | 1,613 passed / 4 skipped; MyPy 208 |
| 954 | N2-5 Bosnian + a11y | 1,598 passed / 4 skipped; MyPy 205; notes N2-4 deferred before this task |
| 1020 | N2-3 candidate remediation | 1,580 passed / 2 skipped; MyPy 202 |
| 1079 | N2-2 paper fills | 1,561 passed / 2 skipped; MyPy 199 |
| 1120 | N2-1 paper dashboard/CSV | 1,553 passed / 2 skipped; MyPy 198 |
| 1158 | N1-4 release hardening | 1,546 passed / 2 skipped; MyPy 197 |
| 1206 | N1-3 scan cost | 1,542 passed / 2 skipped; MyPy 197 |
| 1254 | N1-2 coverage alerts | 1,530 passed / 2 skipped; MyPy 193 |

Remaining (older): N1-1 `:1298`, N0-4 `:1345`, N0-3 `:1387`, N0-2 `:1433`,
N0-1 `:1481`; the file ends at `:1551`. The log's per-entry "Files changed"
lists are the only record of which files each task touched.

### 4. Old `PROJECT_ROADMAP.md` — unique content

- `:16-22` its own Definition of done (four bullets, no both-modes clause).
- `:82-105` "Verified baseline (2026-11-04)": 1,251 tests, 134 MyPy files,
  cache 7,666 matches / 1,231 groups / 11 surebets / 218.5 MB, groups JSON
  133.1 MB, parse 2.51 s, ledger 23.6 MB / 4,632 claims, 3,333 aliases.
  Historical only; nothing else carries the pre-P0-1 numbers.
- `:107-115` strengths worth preserving; `:117-140` findings F1-F19;
  `:133` the public **1.34% of 115,583 boards** / 26 of 1,553 actionable
  reference (also in `docs/RESEARCH_ARBITRAGE_2026-11-04.md:38` and
  `docs/evidence/2026-11-04-opportunity-rate-baseline.md:31`).
- `:141-151` "What is already fixed and should not be re-opened" (7 bullets:
  persisted evidence, order-insensitive grouping, converging `build_targets`,
  kickoff+2 min expiry, premier_kladionica/NSoft live regression tests,
  `orientation_unresolved` emitted+documented, approve/reject routes removed).
- `:250-283` the P0-1…P3-7 task table. **This is the only definition of those
  IDs**, which ~14 docs and ~30 test docstrings still cite.
- `:1400-1406` 5.1 non-goals (no bet placement/login; no gate lowering; no book
  or market without capture/dated-absence proof; no live-polling increase
  without a push/sub-10 s feed; AI never approves).
- `:1408-1419` 5.2 trust invariants (8; the 9th and 10th were added in V2/AGENTS).
- `:1421-1423` 5.3 measurement discipline ("run the command that proves it and
  paste the output"; update `docs/ACCEPTANCE.md`; regenerate `MARKET_MAPPING.md`,
  never hand-edit).
- `:1431-1443` "Roadmap closed" entry; `:2340-2387` quick reference (cache-shape
  snippet, `pairing_audit.py --check`, `record_scan.py`, where-to-look table
  including `engine/certainty.py`, `engine/matcher.py`, `engine/arbitrage.py`).

### 5. AGENTS.md — sections and every rule

Sections: Read first (5-12) · Task loop (14-41) · Maintenance work (43-49) ·
Shared building blocks (51-67) · Trust invariants (69-80) · Session handoff
(82-87) · Do not (89-95).

Rules, all still accurate unless marked:
1. Read order: roadmap V2 → `docs/SESSION_BRIEF.md` → `TODO.md` →
   `docs/HANDOFF.md` only for history (`:5-8`).
2. Predecessor roadmap finished, do not reopen (`:10`).
3. Every V2 task Done except N2-4; do not un-defer without instruction; P1-6
   waived and excluded (`:11-12`).
4. Resume `In progress`, else first `Not started` with deps Done; set `In
   progress` before coding; one task only; blocked → record and stop (`:16-19,33-34`).
5. Acceptance boxes, status `Done`, execution log, `SESSION_BRIEF.md` (`:29-30`).
6. Commit/push only when the operator asks (`:31-32`).
7. `.venv/bin/python` fallback (`:36`).
8. **STALE:** "CI additionally runs `check_test_isolation.py`" (`:38-41`).
   `.github/workflows/ci.yml` has jobs `quality` (`:11`), `tests` (`:41`),
   `security` (`:108`), `sbom` (`:133`) and no isolation step. `refresh_fixtures
   --check` (`:72`) and `audit_admissibility --check` (`:39`) do run.
   `docs/CI.md:43` and `README.md:445` list isolation as a **local** command;
   the scraper briefs already flag this (`03_…:86-87`, `SCRAPER_TODO.md:179`,
   task SR1-2).
9. Maintenance work: no invented roadmap task, small file-disjoint bundles,
   update brief + TODO, no commit, deferred stays in TODO (`:45-49`).
10. Shared building blocks (`:53-64`) — all verified to exist:
    `engine/name_keys.py:23` `raw_team_key`; `engine/market_consensus.py`;
    `engine/market_registry.py:327` `registered_spec` with the `has_source_id`
    seam (`:265`, `:342`); `server/csv_export.py:16` `csv_cell`; lazy
    `engine/__init__.py` and `scrapers/__init__.py` (both PEP 562).
11. "One strict xfail for the deferred named-key auth gap; not a skip" (`:66-67`)
    — true: `tests/test_auth_keys.py:131` is the only `pytest.mark.xfail`.
12. Ten trust invariants (`:71-80`). Only difference from the roadmaps: item 1
    says "reach pricing" instead of "reach `engine/arbitrage.py`".
13. Session handoff content list (`:84-87`).
14. Do not: delete `config/generated/mapping_evidence.json` or runtime state to
    pass a test (`:91-92`); change trust rules / evidence semantics /
    price-source identity in an unrelated task (`:93-94`); start from `cache/`
    (`:95`).

Not in AGENTS.md but in the roadmaps and worth preserving: the both-ledger test
requirement, "paste the measured output", the `MARKET_MAPPING.md` regeneration
rule, and the "roadmap tasks vs TODO" distinction (TODO.md:3-5 restates it).

### 6. `docs/research/` references outside `docs/research/`

None. Only internal references:
`docs/research/scraper-map/SCRAPER_TODO.md:7` (hard-codes
`docs/research/scraper-map/`) and `:636` (log row), and
`00_README.md:5` ("move it to the repo root if preferred"). No README, docs
index, test, script or workflow links to `docs/research/`. The move is
mechanically safe, but a root-level `SCRAPER_TODO.md` will sit beside `TODO.md`
and needs a one-line "which backlog" note in both.

### 7. TODO.md open items (all unchecked, `:13-92`)

Security/auth: named-key middleware+scopes redesign (remove the xfail);
`accepted_odds: 0` with stake → 422?; auth-failure rate limit / PBKDF2 cache.
Performance: move scan CPU/I/O off the event loop (~100 s `/api/status` block);
stop rewriting the ~55 MB cache on every `/api/verify-links`; cache `/api/health`;
cap the 14k-row candidate queue; review compact cache/ledger vs consumers.
Architecture: decompose `server/api.py`; move deep-link store out of
`scrapers/common.py` (breaks the engine↔scrapers cycle); one link-settled
predicate + parity test; unify datetime/SQLite helpers and `synchronous` policy;
route `MARKET_REGISTRY` lookups through `registered_spec()`; move
`scripts/pairing_audit.audit` + verifier into `server/`.
Supply chain/CI: lock file for Docker/CI/SBOM; Docker Chromium + OS/image CVE
scan; pin Actions by SHA and base image by digest; plan FastAPI/Starlette, MyPy
2.x, Ruff 0.17, Playwright 1.64, `httpx2` migration.
Product/config: remove/deprecate `Surebet.match_urls`, `Surebet.bet_urls`,
`Match.bet_url`, `MATCH_URL_TEMPLATES`; decide `link_sweeps` table; decide
approve/reject functions; decide `engine/raw_market_resolver.resolve_offers`;
finish PWA (192/512 icons, notification button); "zero matches" diagnostic +
run-mode-aware no-surebet state; feed-mode tab ARIA contract.
Tests/process: branch coverage floor in CI; pin `today=` in the parser-contract
test (turns red 2027-02-17); narrow the runtime-guard SQLite `-shm`/`-wal` false
positive; browser-enabled CI job for the Chromium a11y tests.

## Locations (claims that rest on files)

- `AGENTS.md:5,10,11,38-41,66,71-80`; `.github/workflows/ci.yml:11,39,41,72,108,133`
- `PROJECT_ROADMAP_V2.md:5,7-8,17-31,39-57,77,83-86,557-595,753-782,789-1300,1529-1551`
- `PROJECT_ROADMAP.md:16-22,82-105,133,141-151,250-283,723-755,1400-1423,1431-1443,2340-2387`
- `TODO.md:3-5,13-92`; `docs/SESSION_BRIEF.md:4-19,63,70`
- `docs/ACCEPTANCE.md:284,477-479`; `docs/SOAK.md:1,6,88`; `docs/CI.md:43,80-84`
- `tests/test_deployment_assets.py:5`; `tests/test_auth_keys.py:131`
- `docs/research/scraper-map/00_README.md:5`; `SCRAPER_TODO.md:4,7,179,636`;
  `03_fixtures_and_pain_points.md:27,86-87,196,198`
- Building blocks: `engine/name_keys.py:23`, `engine/market_registry.py:265,327,342`,
  `server/csv_export.py:16`, `engine/__init__.py:1-20`, `scrapers/__init__.py:1-20`

## Risks / uncertainties

1. **Contradiction on P1-6.** AGENTS.md:12, V2:7-8 and SESSION_BRIEF:13 say
   waived/excluded; `docs/ACCEPTANCE.md:284,477-479` still says "In progress"
   and `docs/SOAK.md:6` says "the roadmap keeps P1-6 In progress". I trust the
   operator's 2026-11-05 waiver and the roadmap's `Waived (excluded)` status;
   ACCEPTANCE/SOAK are stale wording. A new roadmap must not silently re-open it,
   and ACCEPTANCE/SOAK should be reworded at the same time.
2. Deleting the old roadmap deletes the **only definition** of P0-1…P3-7, which
   ~14 docs and ~30 test docstrings cite. Nothing breaks, but the labels become
   unresolvable. Either carry a one-line ID glossary into the new roadmap/AGENTS
   or add "P*/N* IDs are historical labels" to it.
3. Deleting V2 loses the only record of N2-4's steps and acceptance and the only
   per-task "Files changed" history. `git log` keeps the files but not the
   per-task mapping.
4. The two V2 baseline tables (grep-verified at `:17-31`) are superseded by
   SESSION_BRIEF:14-19; quoting them in a new roadmap would re-introduce stale
   numbers.
5. Moving `SCRAPER_TODO.md` to the root creates two backlog files (`TODO.md`,
   `SCRAPER_TODO.md`) and one stale path reference at `SCRAPER_TODO.md:7`.
   `00_README.md:5` already anticipates the move.
6. Not verified: whether `docs/superpowers/…` or `docs/HANDOFF.md` should be
   folded in — they are referenced by `test_matcher_order.py:6` (HANDOFF §4) and
   are outside this task's stated scope. Untouched by the plan.
7. Not verified: whether the operator wants `docs/RESEARCH_ARBITRAGE_2026-11-04.md:9`
   (its "separate from PROJECT_ROADMAP.md" sentence) reworded; it is prose only.

## Conclusions

1. **Nothing breaks.** No code, script, test or CI job reads either roadmap;
   the only fragile citations are line-number citations in
   `docs/research/scraper-map/03_fixtures_and_pain_points.md:27,196,198`.
2. Carry N2-4 verbatim (V2:557-595) as the sole deferred task, with its four
   unchecked acceptance boxes intact.
3. Record P1-6 as waived/excluded, keep its four unchecked acceptance boxes and
   link `docs/SOAK.md`; fix the ACCEPTANCE/SOAK "In progress" wording, which
   contradicts the waiver.
4. Keep the both-ledger test requirement, measurement discipline, both definition-
   of-done lists and the 10 invariants; they exist only in the roadmaps + AGENTS.
5. Preserve a short P*/N* ID glossary: ~14 docs and ~30 test docstrings cite IDs
   whose only definition is the deleted task tables.
6. AGENTS.md needs one correction (CI does **not** run `check_test_isolation.py`)
   and otherwise its rules can be carried across intact.
7. `docs/research/` is referenced nowhere outside itself; the move is safe, with
   `SCRAPER_TODO.md:7` and `00_README.md:5` needing a path touch-up.
8. Fold the TODO.md items into the new roadmap only by explicit decision; they
   are currently gated on operator approval (`TODO.md:4-5`).
