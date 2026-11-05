# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4, N1-1 through N1-4 and N2-1 are
Done**. First eligible task is **N2-2** (realistic paper fills; depends on
N2-1, which is Done).
**Last task commit:** `045ad96` — N2-1 paper ledger dashboard, CSV and settle.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,553 passed, 2 skipped, 1 warning** in both ledger modes: with no generated
ledger and with a deliberately populated one. Ruff, MyPy (198 source files),
Node syntax check and the generated market doc are clean.

N2-1 makes record-only/paper mode usable without curl: a Paper tab with summary
tiles and explicit denominators, run/feed/status filters, paged opportunities
and positions, per-leg settle controls, unavailable mark reasons, store
size/retention state, and a CSV export at `/api/paper/export.csv` covering both
stores. The pane is read-mostly, always says no bet was placed, and has no live
slip or copy action. `docs/PAPER_MODE.md` documents the UI, export and retention
view.

Earlier work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, a CSP with no inline styles, automatic closing-line capture,
bounded retention/maintenance, coverage/mapping alerts, per-book scan cost
accounting, and release hardening (SBOM, Docker smoke workflow, grouped
Dependabot). The first live scan-cost baseline is still pending (no live scan was
run); its dated evidence slot is ready.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N2-2**: add configurable paper fill rules (per-book cap, deterministic
rejection on price movement/disappearance, partial stake), reuse advisory book
limits/risk profiles, record `filled`/`partial`/`rejected`/`missing` per leg and
the worst case, compute execution-adjusted ROI only over complete fill records,
keep the optimistic “if all filled” number separate, document the model in
`docs/PAPER_MODE.md`, and add `tests/test_paper_fills.py` for full, partial,
rejected, disappeared and negative-worst-case positions.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
