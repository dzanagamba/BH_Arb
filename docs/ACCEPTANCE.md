# Acceptance record — 2026-11-03

This is the dated evidence behind the production-readiness claim. It is a
measurement, not a promise: every number below was produced by the command
named next to it.

## CI and replay

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest` | **1,168 passed** |
| Lint | `python -m ruff check .` | clean |
| Types | `python -m mypy .` | clean on 119 source files |
| Market doc | `python scripts/generate_market_mapping_doc.py --check` | in sync |
| Cold replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` | exit 0, fixed point |
| Seeded replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --seeded --check` | exit 0 |

The cold replay starts with an empty evidence ledger, learns from the frozen
corpus, and reaches a pass that adds no claim and changes no verdict. It has 0
false merges and 0 unresolved evidence-backed pairs.

## Browser hardening

`server/app.py` sets `Content-Security-Policy` (`default-src 'self'`,
`object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`,
`connect-src 'self'`), `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` on the dashboard and
every API response. The dashboard still uses inline handlers, so `script-src`
includes `'unsafe-inline'`; replacing those handlers with listeners and a nonce
CSP remains open.

## Soak

`python scripts/soak.py --cycles 10 --interval 5 --pid <server-pid> --check`:

| Sample | Matches | Groups | Surebets | RSS | Browsers | Errors |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6,497 | 1,046 | 5 | 726.4 MB | 0 | 1 |
| 10 | 6,493 | 1,046 | 5 | 897.9 MB | 0 | 1 |

Memory grew **23.6%** (limit 50%), no browser process survived a scan, and the
run passed `--check`.

`python scripts/soak.py --cycles 3 --interval 5 --pid <server-pid> --check`
on the final gate (including the pairing and CSP changes):

| Sample | Matches | Groups | Surebets | RSS | Browsers | Errors |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6,501 | 1,044 | 12 | 779.9 MB | 0 | 1 |
| 3 | 6,500 | 1,044 | 12 | 888.7 MB | 0 | 1 |

Memory grew **13.95%**, no browser process survived, and the run passed
`--check`. The 24-hour run is still open.

## Real prematch scan (verified sample)

`python main.py`, then `POST /api/scan?mode=prematch` at **2026-11-03 04:39 UTC**.

| Metric | Value |
|---|---|
| Books returning matches | 9 / 9 enabled (Betole, MaxBet, MDShop, Admiralbet, MBet, SportPlus, Premier Kladionica, WWIN, Mozzartbet) |
| Matches | 6,492 |
| Verified groups | 1,043 |
| Listings in groups | 5,805 |
| Groups with all nine books | 126 |
| False merges (different Betradar ids in one group) | 0 |
| Price outliers | 3 (dropped with their surebets) |
| Surebets shown | 9 |

The price guard dropped three outlier legs: Kitakyushu–Reilac Shiga (MaxBet X2,
SportPlus 1) and Kanazawa–Parceiro N (SportPlus 1). The nine shown were
re-checked with `POST /api/verify`:

| Match | Market | Profit | Books | Re-check |
|---|---|---:|---|---|
| kanazawa – parceiro n | double chance | 8.28% | mdshop / mozzartbet | not found on fresh data |
| anaitasuna ft – alaves | BTTS | 1.69% | betole / maxbet | still profitable |
| boston united – leicester u21 | double chance | 1.52% | sportplus / wwin | not found on fresh data |
| villarreal – psg | 1X2 | 1.20% | mdshop / mozzartbet / wwin | still profitable |
| tochigi – fukushima | double chance | 0.51% | mdshop / mozzartbet | still profitable |
| bodo/glimt – lille | double chance | 0.49% | betole / maxbet | still profitable |
| atl madrid – bayern munich | double chance | 0.42% | mdshop / mozzartbet | still profitable |
| roma – sassuolo | double chance | 0.42% | mbet / mozzartbet | still profitable |
| tochigi – fukushima | 1X2 | 0.33% | mdshop / mozzartbet | still profitable |

Seven of nine re-verified at a fresh price; two disappeared before the re-check
and are reported as gone rather than as confirmed arbs.

The final-gate soak scan at **04:54 UTC** found **6,500 matches, 1,044 verified
groups and 12 surebets**, including `mainz – bayern munich` 1X2 at 0.27%, a
fixture that only paired after the anchor fix. A later scan at **05:08 UTC**,
after the abbreviation and punctuation rules, found **6,377 matches, 1,030
verified groups and 6 surebets** as the feed shrank toward kickoff. These later
counts are scan-level measurements and were not individually re-verified.

## Pairing coverage

`python scripts/pairing_audit.py --check` reads the same cache the dashboard
serves and exits non-zero when a same-fixture offer is left unpaired or a group
repeats a bookmaker.

| Metric | Value |
|---|---:|
| Matches | 6,377 |
| Verified multi-book groups | 1,030 |
| Listings in groups | 5,712 |
| Ungrouped listings | 665 |
| Duplicate listings from a book already in the group | 312 |
| Strict misses (same league, ±15 min, both teams ≥80% alike) | 31 |
| Strict miss rate | **0.49%** |
| Groups repeating a bookmaker | 0 |

Per-book grouping, including duplicate listings:

| Book | Grouped / matches | Rate |
|---|---:|---:|
| MDShop | 523 / 525 | 99.6% |
| Admiralbet | 523 / 525 | 99.6% |
| MBet | 585 / 601 | 97.3% |
| WWIN | 711 / 740 | 96.1% |
| SportPlus | 717 / 750 | 95.6% |
| MaxBet | 734 / 826 | 88.9% |
| Premier Kladionica | 734 / 831 | 88.3% |
| Betole | 930 / 1,239 | 75.1% |
| Mozzartbet | 255 / 340 | 75.0% |

The low Betole/Mozzartbet rates are mostly duplicate listings and leagues no
other book carries, not same-fixture misses: only 31 offers in the whole scan
have a strict counterpart in another book that the matcher failed to pair. The
remaining examples are abbreviations and city-qualified spellings such as
`Qingdao H` / `Qingdao Hainiu`, `Dynamo D` / `Dynamo Dresden`, and
`Central Coast (W)` / `Central Coast Mariners (W)`.

### Gate fixes that produced this measurement

1. **The anchor is not the group.** A candidate was compared only with the
   group's first member, so a valid listing was rejected when that member used
   a different league spelling (`germany, bundesliga` beside seven
   `bundesliga` listings). The gate now checks the group's canonical league and
   every member's league, and clears an anchor-only mismatch when the group
   proves it.
2. **A group member can prove a team.** The same anchor-only problem hid a
   team spelling another member could prove (`A. Salzburg` beside
   `Austria Salzburg`). Orientation is now accepted from any member while a
   member supports the canonical fields.
3. **Club designators are not aliases.** `FC Liefering` / `Liefering` and
   `SV Austria Salzburg` / `Austria Salzburg` are accepted without a learned
   alias, but only when the canonical ids and the remaining spelling agree.
   `Atletico Madrid` / `Madrid` is explicitly not such a pair.
4. **Generic leagues get fingerprints.** `bundesliga` is too vague for a hard
   league id but its team set is what resolves it against
   `germany, bundesliga`. The learner now records generic fingerprints and the
   resolver compares canonical team ids, so `Mainz – Bayern` pairs across all
   nine books.

## Betole and EVLBet

`BetoleScraper().scrape(live=False)` returns **1,239** matches. The scraper was
fixed to read `kickOffTime` and to keep `brMatchId` as a Betradar id. Betole is
enabled; its first verified surebet was `anaitasuna ft – alaves` BTTS at 1.69%.

`python scripts/probe_feeds.py --books evlbet,betole` returns **0** matches for
EVLBet and **1,239** for Betole; the dated report is `docs/FEED_STATUS.md`.
EVLBet remains disabled and is an evidence-backed absence, not a silent omission.

## Known gaps

* First-half over/under (`first_half_ou`) is enabled but had no offer in the
  scan; the price guard applies if a book starts publishing it.
* Betole publishes several unregistered market codes; they are counted in
  `/api/health.unmapped_markets` and are not used for pricing.
* The legacy approve/reject HTTP routes are removed; the dashboard is read-only.
  The direct migration functions remain for legacy tests but are not reachable.
* Execution limits, bankroll and the 24-hour soak are not done.
* The CSP admits inline handlers; a nonce-based strict CSP remains open.
* In-play remains deferred.

**Verdict:** the prematch scanner is working and finds real, re-verified
surebets across the nine scrapable books. It is ready for supervised prematch
use; it is not yet a fully unattended betting product.
