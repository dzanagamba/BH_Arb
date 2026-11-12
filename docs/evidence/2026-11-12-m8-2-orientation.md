# 2026-11-12 M8-2 / M8-3: the guard drop and the inverted wwin listing

## What the operator saw

After a prematch scan: `Some bookmakers failed: 7 surebet(s) dropped: a leg was
a price outlier`. No book had failed. The banner joins `status.errors` under a
bookmaker label, and the price guard's protective drop was written there.

The drop itself was real, and four of those seven were not a book's bad price:
the same `torque - racing club` surebet was dropped on every scan at 00:54,
00:57, 01:00, 01:38, 02:10 and 01:28.

## The inverted listing (M8-2)

wwin's own feed for event 4730375 is correctly oriented:

```
wwin   Montevideo City - RC Montevideo   1@1.84, X@3.4, 2@3.65
maxbet Torque          - Racing Club     1@1.82, X@3.4, 2@3.75   (same event)
mdshop Montevideo City - Racing Montevideo 1@1.84, X@3.51, 2@4.0
```

It is the matcher that flipped it. With a shared Betradar id the gate decided
orientation by summing two fuzzy name ratios, and `RC Montevideo` normalizes to
the bare city key `montevideo`, so against the alias-spelled maxbet anchor the
comparison was noise:

```
wwin vs maxbet:  direct=38.1  swapped=48.1   -> swapped (wrong)
wwin vs mdshop:  direct=200.0 swapped=181.2  -> direct, ledger alias proves it
maxbet vs mdshop: direct=99.2 swapped=49.2   -> direct, ledger alias proves it
```

The old refusal only fired when the two totals were exactly equal. Now the
same-provider-id branch asks `_teams_match_details` (ledger and allowlist proof)
first and requires `max(direct, swapped) >= 60` **and** a 20-point margin before
it flips anything; otherwise the pair is refused as `orientation_unresolved` and
splits. A split loses one group; a flip prices a 1 as a 2.

### Measured by replaying the stored scan

`cache/last_scan.json` from 01:10 (6,368 listings), replayed through
`MatchMatcher` + `server.pairing_audit.audit`, with `engine/certainty.py`
stashed for the "before" run:

| Metric | Before | After |
|---|---:|---:|
| Verified multi-book groups | 1,292 | **1,293** |
| Market comparisons | 5,971 | **5,976** |
| Price outliers | 18 | **12** |
| Ungrouped listings | 869 | **868** |
| Strict misses (rate) | 21 (0.33 %) | 21 (0.33 %) |
| Duplicate-book groups | 0 | 0 |
| wwin member, Torque group | `swapped=True`, `1@3.65` | `swapped=False`, `1@1.84` |

The four `torque - racing club` outlier rows disappear; the twelve that remain
are price disagreements, not orientation:

```
maxbet  btts GG/NG, double_chance 1X/12, 1x2 2   malawi - egypt
betole  btts GG/NG (x3), 1x2 2                   france - turkey, marko - zakynthos, ajax - thun, iberia - getafe
```

`python scripts/price_check.py` on the live rescan (new code):

```
groups with status ['verified']: 1297; market comparisons: 5966
outliers: 12
```

## The message (M8-3)

`ScanStatus.notes` now sits next to `errors`. The price-guard line and the
odds-age spread append to notes; a book that could not be read, a failed
learning/candidate/closing pass and a scan error stay errors. `/api/status` and
the diagnostics payload ship both; the dashboard shows `Scan finished with
problems: …` for errors and a toast for notes.

Measured on the live rescan:

```
GET /api/status?mode=prematch
errors = []
notes  = ['6 surebet(s) dropped: a leg was a price outlier']
matches 6367 surebets 19
```

## Tests and checks

- `tests/test_certainty.py` +3: noise is refused (`orientation_unresolved`, not
  swapped), a decisive reversal still swaps, ledger aliases settle it.
- `tests/test_scan_notes.py` (4): the model and `/api/status` carry notes, the
  guard/age lines target notes while book failures stay errors, and the
  dashboard reads notes without the old label (i18n key replaced).
- Full suite: `2465 passed, 12 skipped in 120.51s`; ruff clean; mypy clean;
  market doc / refresh_fixtures / audit_admissibility `--check` exit 0.
