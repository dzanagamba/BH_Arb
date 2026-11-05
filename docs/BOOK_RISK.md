# Book risk profiles and advisory pacing (P3-6)

A leg is a price at a bookmaker, and bookmakers are not interchangeable: a
retail ("soft") book may cut a stake, limit an account, or void a palpable
error after repeated arbitrage. This feature tells the operator what kind of
book a leg is at and whether the planned stake is realistic. It is **advisory
only**.

## What a profile contains

`config/bookmaker_risk.json` holds one entry per configured book:

```json
"mbet": {
  "profile": "soft",
  "advisory_max_stake": 500,
  "typical_max_stake_note": "Retail book; a few hundred KM per bet is a realistic first order.",
  "limit_risk": "Repeated arbitrage can lead to stake cuts or account limits."
}
```

- `profile` is `sharp`, `soft`, `exchange` or `unknown`.
- `advisory_max_stake` seeds the per-book ceiling. The existing
  `BOOK_MAX_STAKE_<BOOK>` environment variable still overrides it.
- `typical_max_stake_note` is shown under the leg in the slip.
- `limit_risk` explains the account risk in the badge tooltip.

A missing, malformed, or partially readable file fails safe: the affected books
become `unknown`, keep the 500 KM default ceiling, and say that no profile was
recorded. The scanner never guesses a profile from a name.

## Where it appears

`/api/config` exposes `risk_profile`, `typical_max_stake_note`, `limit_risk`
and `max_stake` for every book. The dashboard shows:

- a profile badge next to each slip leg and in the bookmaker chip tooltip;
- the typical-stake note under the leg;
- a normal "above the advisory book limit" warning for non-soft books;
- a stronger **High stake at a soft book** warning when a planned stake is above
  a soft book's advisory ceiling.

Every profile is visible without opening a separate report, and a high stake at
a soft book is visually distinct from an ordinary limit warning.

## What it must never do

The profile is metadata, not a trust or pricing input. It cannot:

- change the certainty gate, the matcher, the price-source rule, or the stake
  math;
- add or remove a book from a scan;
- place a bet, log in, or move money;
- implement stake jitter, "mug betting", multi-account rotation, or any other
  account-longevity evasion.

Auto-placement is a stated non-goal. **The scanner never places a bet.** The
operator remains responsible for the stake, the account, and the book's rules.

## Changing a profile

Edit `config/bookmaker_risk.json` and restart the process. Profiles are loaded
once at import, like the rest of `config/settings.py`; a bad edit falls back to
`unknown` rather than blocking a scan. Tests in
`tests/test_book_risk_profiles.py` pin the config exposure, the fail-safe
loader, the dashboard hooks, and the rule that a profile cannot change the gate
or the price source.

## Limits of this policy

The research on account limits is descriptive, not a playbook: books differ,
markets differ, and a profile is a conservative label rather than a measured
account history. A `soft` label does not mean a stake will be accepted, and an
`unknown` label does not mean the book is safe. Check the book's own limits and
the current price before placing anything.
