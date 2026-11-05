# Parser fixtures and contracts (N2-6)

## What is frozen

`tests/fixtures/markets/<book>_<mode>.json` is one hand-trimmed payload read
from the book's live feed. Each file records its endpoint, capture date, source,
payload kind and provenance. `scripts/capture_market_fixtures.py` regenerates
them; a book that cannot be reached or serves no qualifying payload is reported
`SKIPPED` and gets no fixture. A fixture is never hand-written from the parser's
own constants.

`tests/fixtures/markets/contracts.json` is the dated **contract** for those
fixtures. For every capture it stores:

- the required top-level keys and the keys actually present;
- the source-id set the payload carries;
- the label set (market/outcome names and codes);
- a bounded nested-shape signature;
- counts and three SHA-256 fingerprints;
- the capture date and the policy `max_age_days`.

`engine/parser_contracts.py` computes all of it and produces the diff.

## The two failure kinds

| Signal | Means | Action |
|---|---|---|
| `capture_failed` | the host was unreachable or served no qualifying payload | retry later; **not** evidence that the feed changed |
| contract diff | the payload that *was* captured has different keys, ids, labels or shape | review the diff, re-capture, and re-run the admissibility evidence before changing a parser or registry row |

A contract diff never edits `config/bookmaker_markets.json`, a parser or a trust
rule. A new id is a prompt for the existing evidence path, not an admission.

## Refresh cadence

The contract policy is **120 days** (`max_age_days` in `contracts.json`). The
operator re-captures on the first of the following, whichever comes first:

1. `/api/health.parser_contracts.stale_count > 0` — a fixture crossed the
   policy;
2. a contract diff in CI or in a manual `--check`;
3. a book's live scan starts returning `parse_error`/`empty_feed` while peers
   still populate.

A re-capture is a dated event. Keep the capture date in the fixture, review the
printed diff, then update the contract in the same commit:

```bash
python scripts/refresh_fixtures.py --check
python scripts/refresh_fixtures.py --books maxbet,wwin --capture --write
python scripts/refresh_fixtures.py --write     # after a reviewed manual capture
```

`--capture` exits non-zero when the network capture fails and reports
`capture_failed`; it does not write a contract from a failed run. `--write`
prints the diff against the previous reviewed expectation.

CI runs `python scripts/refresh_fixtures.py --check`, so a fixture changing
without an updated contract, an enabled book losing its only fixture, or a
fixture older than the policy fails the build.

## Coverage today

- 8 books have at least one dated contract in both modes: Mozzartbet, MDShop,
  Admiralbet, MBet, SportPlus, Premier Kladionica, WWIN and MaxBet.
- Betole has a **prematch** contract. Its prematch desk feed serves 1X2, BTTS,
  the 2.5 total and the experimental first-half 1X2, but no double chance or
  1.5/3.5 totals; those registry rows are declared uncovered in
  `tests/test_market_fixtures.py`. The registry declares no live rows for
  Betole, so a live capture cannot satisfy the declared-market invariant without
  an admissibility decision, which this task does not make.
- EVLBet is disabled and its flat offer feed served an empty list, so it has no
  fixture.

`/api/health.parser_contracts` lists `missing_books`, `missing_modes`, `stale`
and the oldest/latest capture, so a gap is visible without reading the tests.

## Boundaries

- Do not guess a mapping from a changed payload.
- Do not hand-edit a fixture to make a contract pass.
- Do not add a registry row just because a diff shows a new id.
- The contract is a reminder and a diff, not a conclusion.
