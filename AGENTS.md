# BH_Arb — agent instructions

## Read first

1. `PROJECT_ROADMAP_V2.md` — current roadmap, task table, acceptance criteria.
2. `docs/SESSION_BRIEF.md` — current state and next action.
3. `TODO.md` — deferred maintenance, not roadmap tasks.
4. `docs/HANDOFF.md` only when historical context is needed.

The predecessor roadmap (`PROJECT_ROADMAP.md`) is finished. Do not reopen it.
Every V2 task is Done except N2-4, which the operator deferred; do not un-defer
it without an explicit instruction. P1-6 (24-hour soak) is waived and excluded.

## Task loop

1. Resume an `In progress` task. Otherwise pick the first `Not started` task
   whose dependencies are `Done`.
2. Change its status to `In progress` **before** coding.
3. Implement only that task, following its Objective, Steps and Acceptance.
4. Add or update the tests named in the task.
5. Verify:
   ```bash
   python -m pytest
   python -m ruff check .
   python -m mypy .
   python scripts/generate_market_mapping_doc.py --check
   ```
   plus any task-specific measurement or replay command.
6. Check the acceptance boxes, set the task `Done`, update the execution log,
   and update `docs/SESSION_BRIEF.md`.
7. Review the diff. Commit and push with a conventional message only when the
   operator explicitly asks; otherwise leave the working tree for review.
8. If blocked, record the blocker in the task and stop. Do not start a second
   task.

Use `.venv/bin/python` if `python` is not on `PATH`.

CI additionally runs `python scripts/check_test_isolation.py`,
`python scripts/refresh_fixtures.py --check` and
`python scripts/audit_admissibility.py --check`. Run the relevant ones when a
change touches tests, fixtures or sport/market admission.

## Maintenance work (non-roadmap)

When the operator asks for a cleanup, audit or review instead of a roadmap task,
do not invent a roadmap task or reopen a Done one. Keep changes in small,
file-disjoint bundles, update `docs/SESSION_BRIEF.md` and `TODO.md`, and do not
commit unless asked. A deferred finding stays in `TODO.md`; do not silently
start it in a later session without operator approval.

## Shared building blocks

- `engine/name_keys.raw_team_key()` is the only raw team-name key. The certainty
  gate, evidence ledger and review diagnostics delegate to it; do not copy a
  second NFKD/punctuation fold.
- `engine.market_consensus` owns complete-market, devig and outlier math.
  Operator scripts import it; do not reintroduce local market tables.
- `engine.market_registry.registered_spec()` is the shared per-book resolver.
  It keeps the `has_source_id` seam used by test fakes.
- `server/csv_export.csv_cell()` neutralises formula-leading cells in every CSV
  export. Use it rather than a local copy.
- Keep `engine/__init__.py` and `scrapers/__init__.py` lazy. Import submodules
  directly (`from engine.matcher import MatchMatcher`) instead of re-exporting
  eagerly.

The suite contains one strict `xfail` for the deferred named-key auth gap. Do
not delete it without fixing the gap; do not turn it into a skip.

## Trust invariants — never weaken

1. Only `verified` groups reach pricing.
2. `verified` means zero outstanding reasons, including the link half.
3. Only a browser check can set `deep_link_verified`; no human or AI action can.
4. A missing declaration fails safe.
5. A false merge is worse than a split; no fuzzy score alone confirms identity.
6. `sport` is a hard identity gate; no cross-sport pricing.
7. Settlement is part of market identity; regulation vs overtime never pair.
8. One leg per bookmaker and one leg per price source.
9. The scanner never logs in, places a bet, moves money, or evades account limits.
10. Never lower the certainty gate to increase the number of surebets.

## Session handoff

Keep `docs/SESSION_BRIEF.md` short and current: goal, task status, project
state, next action, last commit, blockers. Update it at the end of every task,
not only when the session ends. The next session starts from that file and the
roadmap, so it must be enough to resume without reading the whole history.

## Do not

- Do not delete `config/generated/mapping_evidence.json` or other operator
  runtime state to make a test pass; redirect tests instead.
- Do not change trust rules, accepted evidence semantics, or price-source
  identity as part of an unrelated task.
- Do not start from `cache/` contents; they are runtime state, not fixtures.
