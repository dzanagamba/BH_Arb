# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1 through N0-4, N1-1 through N1-4 and N2-1 through
N2-3 are Done**. First eligible task is **N2-4** (seven-day local opportunity
baseline and drift gates; no dependencies).
**Last task commit:** N2-3 — candidate remediation and strict-miss trends (see
`git log -1`).

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,580 passed, 2 skipped, 1 warning** in both ledger modes: with no generated
ledger and with a deliberately populated one. Ruff, MyPy (202 source files),
Node syntax check and the generated market doc are clean.

N2-3 turns the review queue into ranked, proposal-only work. Every candidate
carries a `remediation` block: `action` is `alias`, `league`, `alias+league` or
`none`, the exact gate reasons are kept verbatim, and each proposed
`team_alias`/`league_equivalence` entry shows the evidence ledger's own status
and confidence. A proposal is always `proposal_only`/`applied=False`: it cannot
write the allowlist or ledger, cannot change `deep_link_verified`, and cannot
make a candidate verified. The league verdict is a hypothetical run of the
scan's own gate, discarded immediately. `scripts/pairing_audit.py` groups
repeated strict misses by book pair, league and spelling pattern with miss and
listing denominators; `/api/health` exposes `candidate_remediation`,
`candidate_blocker_trend` and `pairing_trend`. The Diagnostics tab has a "Top
recurring blockers" panel with the strict-miss sparkline, and
`scripts/candidate_remediation.py` prints the top N closeable pairs offline.
The queue size is stated as a diagnostic, never coverage progress.

Earlier work remains in place: hermetic tests, frozen-price quarantine with
`source_updated_at`, a CSP with no inline styles, automatic closing-line capture,
bounded retention/maintenance, coverage/mapping alerts, per-book scan cost
accounting, release hardening (SBOM, Docker smoke workflow, grouped
Dependabot), paper ledger/CSV/retention and realistic paper fills. The first
live scan-cost baseline is still pending (no live scan was run); its evidence
slot is ready.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N2-4**: generate `scripts/opportunity_baseline.py --days 7` from a real
seven-day history (or import an existing recorded history), publish crossing /
floor-crossing / actionable rates plus median and best margin and p50/p90
lifetime with explicit denominators, define per-mode drift bands with a
`--check` failure for a material drop, record the baseline and its limitations
under `docs/evidence/`, and wire the report into CI as an optional data check
only (never a live-feed job). Do not tune filters until the baseline exists.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
