# Property-based pricing and identity tests (N3-1)

The fixed fixtures in `tests/test_certainty.py`, `tests/test_identity_edge_cases.py`
and `tests/test_pricing_invariant.py` cover the cases we have seen. The property
suites are a second net: they generate many valid inputs around the same rules
and assert that the rule, not the example, is what holds.

They are not a new trust rule and they never write a mapping, an allowlist, a
ledger claim or a deep-link proof. The generators only produce inputs the
scanner already accepts (decimal odds above 1.0, positive stakes, real sports,
the existing settlement vocabulary).

## Files

| File | Covers |
|---|---|
| `tests/test_properties_pricing.py` | `sum(1/odds)` / profit identity, proportional stake split, one leg per bookmaker and per price source, served worst case, rounding bounds and the funded-rounding loss. |
| `tests/test_properties_identity.py` | sport as a hard gate, no mixed-sport group, settlement never paired across, name-marker vetoes, similarity symmetry, kickoff boundaries, no `verified` from a fuzzy score alone. |
| `tests/test_perf_budgets.py` | bounded matcher and cache-parse load budgets, marked `slow`. |

## Running locally

The property suites run in the normal fast suite:

```bash
python -m pytest tests/test_properties_pricing.py tests/test_properties_identity.py
```

The load budgets are opt-in because they intentionally use a large fixture:

```bash
BH_ARB_TEST_SLOW=1 python -m pytest tests/test_perf_budgets.py
```

CI runs the same command as a separate 3.11 step. Without
`BH_ARB_TEST_SLOW=1` the two budget tests are skipped, so the normal suite keeps
its runtime.

## What the invariants say

* **Implied sum / profit identity.** `implied_sum` is exactly `sum(1/odds)`;
  `exact_profit_percent` is derived only from that margin; the served
  `total_margin` is its four-decimal form and `raw_margin` is the exact value.
* **Stake split worst case.** For a verified group, the best combination uses
  distinct bookmakers and distinct price sources, and the proportional split
  gives every outcome the same return before cent rounding. The realised
  worst case is recomputed from the rounded stakes that are actually served,
  not from the exact split.
* **One leg per book / source.** `mdshop` and `admiralbet` are one NSoft feed;
  no surebet may take both complementary legs from that feed, and no book may
  supply two legs.
* **Settlement.** A market's settlement is part of its identity. When listings
  disagree, the engine prices the settlement most distinct books agree on and
  drops the rest; a generated group never yields a leg from the minority
  settlement.
* **Sport.** A cross-sport pair is rejected before any name, league or provider
  id can be considered, and a matcher run never returns a group with two
  sports.
* **Names.** A differing marker (`academy`, `youth`, `women`, `reserve`, `II`,
  `U21`, `GC`, a one-sided colour) is a veto, not a similarity penalty. A high
  fuzzy score alone never produces `verified`:
  `Manchester United` / `Manchester City` is the pinned example.
* **Kickoff.** Inside the verified 15-minute window is `verified`; outside it
  is `suggested` with `kickoff_delta` (a delta is a gap, not a hard identity
  contradiction). A missing kickoff is `kickoff_missing`.

## Rounding loss can be negative

`engine/pricing_invariant.py` defines `rounding_loss = exact_profit -
realized_profit`. Python's `round()` can round a stake up, so the signed value
may be a small gain. The property test pins the honest behaviour:

* the signed loss equals `exact - realized` and is bounded by one rounding step
  per leg (`1` or `5` currency units);
* a deliberately downward split, with the unspent cents left in the bankroll,
  can only lower the returned amount: that conservative loss is non-negative.

The minimized case `2.28 / 2.52` at `100` with round-to-`1` is kept as a normal
regression test instead of being asserted away (it gains `0.14` through
round-half-even).

## Load budgets

The budgets are order-of-magnitude guards, not a benchmark:

| Operation | Input | Budget |
|---|---|---|
| `MatchMatcher.group_matches` | 4 books × 150 fixtures (600 listings) | 10 s |
| cache parse (`json.loads` + `Match`/`Surebet` validation) | 2,000 matches + 500 surebets | 5 s |

Local measurements on 2026-11-05 were about 1.3 s and 0.04 s respectively. The
budgets leave roughly 8–100× headroom for a slow shared runner while still
failing on a quadratic matcher or a per-row I/O step in the cache path.

## Adding a counterexample

When Hypothesis finds a failure, shrink it first (the failure output names the
minimal example), then either fix the production rule or, if the behaviour is
intended, add the minimized input as a normal regression test next to the
property. Do not widen the property until it stops finding the case. Never
weaken a certainty, settlement, price-source or one-leg-per-book rule to make a
generated case pass.
