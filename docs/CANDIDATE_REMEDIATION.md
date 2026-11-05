# Candidate remediation and strict-miss trends (N2-3)

The review queue answers "which pair did the certainty gate refuse, and why".
This report answers the next question only: **which of those pairs could a
mapping still close, and which recurring misses produce the queue?** It is a
diagnostic, not a trust path.

## What a proposal is

A proposal is the exact entry an *approval* would write, shown so a reviewer can
judge it:

* `team_alias` — `"raw spelling A|raw spelling B"`, the same form
  `config/team_alias_allowlist.json` and the evidence ledger use;
* `league_equivalence` — the gate's normalized league pair
  (`premier_league|serie_a`), because that is the form the ledger and
  `config/league_equivalences.json` compare.

Each proposal carries:

* `ledger_status`: `absent`, `quarantined`, `accepted` or `rejected`, plus the
  ledger confidence and evidence types already recorded;
* `proposal_only: true` and `applied: false`, always.

`accepted` means that exact mapping is already trusted. It does **not** mean the
candidate is verified: other gate reasons can still refuse the pair.

## The `action` field

| action | meaning |
|---|---|
| `alias` | granting the proposed team aliases would reach `verified` |
| `league` | granting the proposed league equivalence alone would reach `verified` |
| `alias+league` | both mappings are needed |
| `none` | no alias or league mapping clears the remaining reasons |

The alias answer reuses the existing `alias_actionable` evaluation. The league
answer runs the same hypothetical on a gate configured exactly as the scan's
gate (verified kickoff window, declared league equivalences), grants only the
proposed mapping, marks both links verified (the state the deep-link system
check produces), reads the verdict, and discards the gate state. That is why
`none` can appear for a pair the *candidate* gate queued: the candidate window
is wider (30 minutes) than the verified window (15 minutes), and no approval
moves a kickoff.

The link half is never part of a human proposal. If the pair is link-blocked, the
notes say so; only `scripts/verify_deeplinks.py` or `POST /api/verify-links` can
change it.

No code path here writes the allowlist, the evidence ledger or a candidate's
status. The dashboard has no approve/reject control, and the legacy approval
routes are absent unless `HUMAN_MAPPING_ENABLED` is explicitly set for a
migration.

## Recurring groups and denominators

The queue groups by `(action, book pair, league, exact gate reasons)`.
`share = count / queue total` for the same feed. A big queue is a diagnostic
fact, never evidence that coverage improved or regressed.

Strict misses are grouped in `scripts/pairing_audit.py` by
`(book pair, league, spelling pattern)`, where the spelling pattern is the
identity-normalized pair of each team slot. The report gives:

* `count` — misses in the group;
* `share = count / strict_misses` — the miss denominator;
* `match_share = count / matches` — the listing denominator.

`/api/health` exposes `candidate_remediation` (counts plus the top groups),
`candidate_blocker_trend` and `pairing_trend`. Each trend point carries its own
`matches` and `strict_misses`, so a quieter scan cannot be mistaken for an
improvement.

## Offline report

```bash
python scripts/candidate_remediation.py --top 20
python scripts/candidate_remediation.py --cache cache/last_scan.json --json out.json
```

The script reads the same cache the dashboard serves, rebuilds the queue with
the product's own collector (AI ranking disabled, no network), and prints the
closeable pairs with their proposals and ledger state. It never calls an
approve/reject path and never writes a mapping. With no cache it exits 2 and
says so rather than inventing a queue.

## Rules this does not change

* Only `verified` groups reach pricing.
* A suggestion cannot set `deep_link_verified` or `verified`.
* Settlement, sport and one-leg-per-book/price-source identity are untouched.
* A false merge is still worse than a split.
