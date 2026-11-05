# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N2-3 and N2-5 are Done**. N2-4 was deferred by the
operator ("skip N2-4 for now") and must not be started until they un-defer it.
First eligible task is **N2-6** (parser fixture refresh and drift detection; no
dependencies).
**Last task commit:** N2-5 — Bosnian localization and automated accessibility
(see `git log -1`).

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,598 passed, 4 skipped, 1 warning** in both ledger modes. The four skips are
the two opt-in runtime-state checks plus the two Chromium tests unless
`BH_ARB_TEST_BROWSER=1`. Ruff, MyPy (205 source files), Node syntax checks and
the generated market doc are clean.

N2-5 makes the BS/EN UI real and the accessibility claims machine-checked. The
catalog is `frontend/js/i18n.js` (English source keys, Bosnian copy); `tr()`
and `refreshLocalizedViews()` translate static nodes, accessible attributes,
trusted HTML and all generated chrome, then repaint the tabs on a language
change. Scraped names, league labels and bookmaker names stay data and are never
translated. The no-surebet diagnostic table carries `title_bs`/`body_bs` for
every case. `tests/test_i18n_coverage.py` fails on a missing key, a lost
placeholder or English HTML chrome outside the catalog.

Accessibility is automated: `tests/test_accessibility_axe.py` checks landmarks,
accessible names, tab semantics, live regions, duplicate ids, focus order and
keyboard handlers. `scripts/a11y_audit.py` runs a live Chromium audit over all
six tabs and a synthetic slip, with optional axe-core
(`--axe node_modules/axe-core/axe.min.js`). The reviewed exception list is
empty; the live axe run is clean in light and dark. With
`BH_ARB_TEST_BROWSER=1` the suite also re-runs the keyboard-only path — scan,
filter, open slip, copy stake, Escape — in English and Bosnian.

Earlier work remains in place: hermetic tests, frozen-price quarantine, CSP with
no inline styles, automatic CLV capture, retention/maintenance, coverage alerts,
per-book scan cost, release hardening, paper ledger/fills and candidate
remediation. The first live scan-cost and seven-day opportunity baselines remain
unmeasured; N2-4 owns the latter and is deferred.

## Next action

Start **N2-6**: add a parser contract per enabled book (required top-level keys,
event count, market id set and a label/structure fingerprint from the frozen
fixture); add a dated re-capture command that prints a structured diff; fail CI
when a fixture is stale beyond policy or a contract changes without an updated
expectation; keep "feed changed" distinct from "capture failed"; never auto-admit
a new market from a drift signal. Tests: `tests/test_parser_contracts.py` and the
existing fixture/registry/mapping suites.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
