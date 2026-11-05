# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4 and N1-1 through N1-4 are Done**.
First eligible task is **N2-1** (paper ledger dashboard, CSV and retention view;
depends on N1-1, which is Done).
**Last task commit:** `05a8f8d` — N1-4 release hardening.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,546 passed, 2 skipped, 1 warning** in both ledger modes: with no generated
ledger and with a deliberately populated one. Ruff, MyPy (197 source files),
YAML parsing, Node syntax check and the generated market doc are clean.

N1-4 makes release proof automatic: CI has a `sbom` job that generates
CycloneDX JSON from `requirements.txt` and uploads it; the Docker workflow uses
Buildx with a GitHub Actions layer cache for the Chromium layer; a `Release`
workflow runs the SBOM and Docker smoke on `v*` tags/manual dispatch and fails
on a smoke failure; Dependabot groups runtime, dev and GitHub Actions updates.
`docs/RELEASE.md` has the checklist and local equivalents. The local Docker
smoke could not run here because the user is not in the `docker` group
(`/var/run/docker.sock` permission denied); CI is the execution gate.

Earlier work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, a CSP with no inline styles, automatic closing-line capture,
bounded retention/maintenance, coverage/mapping alerts, and per-book scan cost
accounting with the Diagnostics table. The first live scan-cost baseline is
still pending (no live scan was run); its dated evidence slot is ready.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N2-1**: add a Paper tab or Diagnostics section with summary tiles
(recorded, positions, open/settled, ROI, hit rate, CLV) and explicit
denominators; list recorded opportunities and paper positions with filters,
paging and the `no_bet_placed` label; add settle controls mirroring the manual
bet log and show the mark reason when unavailable; add
`GET /api/paper/export.csv`; show store size/retention state from N1-1; and add
frontend tests for empty, open, settled and unavailable states.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
