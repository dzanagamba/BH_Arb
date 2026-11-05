# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N0-1, N0-2 and N0-3 are Done**. First eligible task is
**N0-4** (automatic closing-line capture for logged bets).
**Last task commit:** `f0f1f30` — N0-3 CSP without inline styles.

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite now
runs **1,499 passed, 2 skipped** in both ledger modes: with no generated ledger
and with a deliberately populated one. A throwaway copy with no
`config/generated/` and no `cache/` also passes in both modes. Ruff, MyPy and the
generated market doc are clean.

N0-3 closed the last CSP gap: `style-src` is `'self'` plus the Google Fonts
stylesheet origin, with no `'unsafe-inline'`. The dashboard sets colours and
progress widths through `style.setProperty` and uses `[hidden]` for display
toggles; no shipped HTML or generated HTML carries a `style="..."` attribute.
`tests/test_csp_styles.py` enforces both properties.

N0-2 remains in place: `source_updated_at` is separate from `fetched_at`, and a
row is refused as **price frozen** when the feed timestamp is past the mode TTL
or the price is unchanged while an independent peer moved.

The two suite skips are opt-in checks: `tests/test_deeplinks.py`'s captured-scan
corpus (`BH_ARB_TEST_RUNTIME_STATE=1`) and the `real_runtime_state` proof of the
opt-in path itself.

## Next action

Start **N0-4**: mark it `In progress`, then capture closing lines for open logged
bets from the scanner's last pre-kickoff prices. Match event, market, line,
settlement and outcome exactly; leave CLV null with a reason when no matching
price exists; keep the manual closing endpoint as an override and label the
source (`scan` vs `manual`). Build on the N0-2 source timestamps.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
