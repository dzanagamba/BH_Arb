# Session brief

**Updated:** 2026-11-05
**Goal:** implement `PROJECT_ROADMAP_V2.md` without weakening the trust model.
**Current task:** none — **N3-1 is Done**. N2-4 remains deferred by the operator
and must not be started until they un-defer it. First eligible task is **N3-2**
(scheduled market/sport admissibility re-audit; depends on N2-6, which is Done).
**Last task commit:** N3-1 — property-based pricing/identity tests and load
budgets (see `git log -1`).

## Project state

The predecessor roadmap is finished; P1-6 is waived and excluded. The suite runs
**1,629 passed, 6 skipped, 1 warning** in both ledger modes. The six skips are
the two opt-in runtime-state checks, the two Chromium tests unless
`BH_ARB_TEST_BROWSER=1`, and the two load budgets unless `BH_ARB_TEST_SLOW=1`.
Ruff, MyPy (211 source files), Node syntax checks and the generated market doc
are clean.

N3-1 adds Hypothesis (dev-only) and 16 property tests. Pricing asserts the
implied-sum/profit identity, the proportional split with one leg per bookmaker
and per price source, the served worst case, and a bounded rounding effect. The
funded (downward) split has a non-negative conservative loss; the signed
`rounding_loss` can be a small gain through round-half-even, and the minimized
`2.28/2.52` case is pinned as a normal regression instead of being asserted
away. Identity asserts sport as the outer hard gate, no mixed-sport matcher
group, settlement dominance, kickoff boundaries, marker/colour vetoes,
similarity symmetry, and that a fuzzy score alone never verifies. Two opt-in
load budgets pin 600 matcher listings under 10 s and a 2,000-match cache parse
under 5 s; CI runs them as a separate 3.11 step.

Earlier work remains in place: hermetic tests, frozen-price quarantine, CSP with
no inline styles, automatic CLV capture, retention/maintenance, coverage alerts,
per-book scan cost, release hardening, paper ledger/fills, candidate remediation,
the complete BS/EN UI with machine-checked accessibility, and dated parser
contracts. The first live scan-cost and seven-day opportunity baselines remain
unmeasured; N2-4 owns the latter and is deferred.

## Next action

Start **N3-2**: turn `scripts/measure_sports.py` and market-discovery
measurements into a repeatable report with a stable schema; add a dated re-audit
script/schedule and a change detector for per-book family/settlement coverage;
warn or fail when a previously admitted family disappears or a new family
appears without evidence; link every admitted market/sport to its dated evidence
row. Keep the three-book and same-settlement rules and never auto-admit.

## Rules

Read `AGENTS.md` for the task loop and trust invariants. Update this file at the
end of every task with the new task status, next action and last commit.
