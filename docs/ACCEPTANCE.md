# Acceptance record — 2026-11-03

This is the dated evidence behind the production-readiness claim. It is a
measurement, not a promise: every number below was produced by the command
named next to it.

## CI and replay

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest` | **1,177 passed** |
| Lint | `python -m ruff check .` | clean |
| Types | `python -m mypy .` | clean on 121 source files |
| Market doc | `python scripts/generate_market_mapping_doc.py --check` | in sync |
| Cold replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` | exit 0, fixed point |
| Seeded replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --seeded --check` | exit 0 |

The cold replay starts with an empty evidence ledger, learns from the frozen
corpus, and reaches a pass that adds no claim and changes no verdict. It has 0
false merges and 0 unresolved evidence-backed pairs.

## Cache payload (P0-1, 2026-11-04)

F1 was a pure payload bug: every `team_identity` record whose proof used the
alias allowlist persisted `sorted(alias_allowlist)` instead of the entry that
proved the pairing. The gate's decision was correct; the evidence was a copy of
configuration.

Measured on the frozen 2026-11-03 nine-book cache (`cache/last_scan.json`,
7,666 matches) by re-grouping the cached matches offline with the same gate:

| Metric | Before | After |
|---|---:|---:|
| Cache file | **218.5 MB** | **23.3 MB** |
| Match-group JSON (compact) | 127.8 MB | **7.3 MB** |
| Match-group JSON (indented) | 178.8 MB | 11.1 MB |
| Allowlist evidence records | 1,288 | 63 |
| Allowlist entries persisted | 4,292,904 | **118** |
| Largest record | 3,333 entries | **4 entries** |
| Cache parse time | 2.62 s | **0.58 s** |

The post-fix cache is written as compact JSON (it is a machine file, not
hand-edited config), so the group JSON occupies its 7.3 MB compact form. A
differential run with the previous evidence behavior produced the **same 1,237
group signatures and statuses**, so the gate's decisions did not change.

`/api/health` now reports `cache.prematch_bytes`, `cache.live_bytes`,
`cache.budget_bytes` (default 40 MB, `CACHE_SIZE_BUDGET_BYTES`) and
`cache.over_budget`; `_save_cache` logs a warning over budget.

Regression tests:
`tests/test_certainty.py::test_allowlist_evidence_records_only_the_proving_entry`
and `tests/test_cache_serialization.py::test_cached_group_payload_is_bounded`.


## Runtime freshness (P0-4, 2026-11-04)

F3 was a different failure from a stale cache file: the cache was bounded and
restored correctly, but a running server kept serving `last_scan.json` without a
hard stale state, so the dashboard could present hours-old prices as current.

The policy is now explicit and shared by the engine, the API and the dashboard:

- Prematch prices expire after `ODDS_TTL_SECONDS` (600 s); live prices after
  `LIVE_ODDS_TTL_SECONDS` (60 s).
- `/api/results` returns `freshness` with `mode`, `scan_time`, `age_sec`,
  `ttl_sec`, `stale`, `state`, `stale_books`, and a `per_book` map carrying each
  book's oldest/newest `fetched_at`, ages, missing-timestamp count and stale
  flag. `/api/health` exposes the same block for both feeds.
- A stale feed keeps its cached rows for diagnosis but is labelled historical.
  The dashboard shows an alert banner, marks rows as stale, and disables copy
  actions. **Re-check odds** stays enabled: `POST /api/verify` is still the only
  path that re-establishes a leg's current price.
- Each `SurebetStake` now carries its own `fetched_at`, so the slip can show the
  age of the exact leg being placed instead of only the group's oldest fetch.

A book with no timestamp, or a scan with no completed run, is treated as stale:
silence is not proof of freshness. The test matrix covers fresh, near-expiry,
past-TTL, one stale book among fresh ones, live's tighter TTL, never-scanned,
missing timestamps, and per-leg fetch times.

Tests: `tests/test_freshness_api.py`, `tests/test_frontend_freshness.py`.

## Reloadable deep-link declarations (P0-5, 2026-11-04)

F5 was an operator trap: `_deeplink_cache` was populated once and never
invalidated, so editing `config/bookmaker_deeplinks.json` had no effect until a
process restart, and the gate kept using the old declarations invisibly.

The loader now keeps the file's `(mtime_ns, size)` signature. It reloads on the
next declaration lookup when the signature changes, so a scan, a verify, or a
health call uses the edited map without a restart. The fallback direction is
unchanged: a missing or malformed file clears the cache, which makes every book
block rather than inherit trust from a stale map.

`/api/health` reports `deep_link_declaration_source` with `loaded_at`,
`source_mtime`, `current_mtime`, `source_size`, `stale` and `error`. Each entry
in `deep_link_declarations` also carries `loaded_at`, `source_mtime` and `stale`,
so the map the gate is using is distinguishable from the file on disk.

Tests: `tests/test_deeplinks.py` (change without restart, malformed fail-safe,
recovery after fixing the file, health reporting) and
`tests/test_candidates_api.py` (health source fields).

## Opportunity-rate and arb-lifetime telemetry (P0-6, 2026-11-04)

F13 was the missing denominator: the dashboard reported groups and surebets but
could not say whether a zero-surebet scan saw no crossing, saw crossings that
failed the gates, or priced only stale data.

`engine/opportunity_metrics.py` observes every board the real pricing pass
evaluates. A board is one event + market + line + period + settlement with the
best cross-book combination; the observation is taken before the display
filters, so a below-floor crossing and a price-guard drop are still counted.
`/api/results` and `/api/health` report:

| Field | Meaning |
|---|---|
| `boards` | Market instances the engine actually priced |
| `crossed` | Boards with implied sum below 1.0 |
| `crossed_above_floor` | Crossings at or above `DUST_PROFIT_PERCENT` (0.2%) |
| `actionable` | Surebets kept after the price guard |
| `crossing_rate_percent` | `crossed / boards` |
| `floor_crossing_rate_percent` | `crossed_above_floor / boards` |
| `actionable_rate_percent` | `actionable / boards` |
| `median_margin`, `best_margin` | Median/minimum implied sum across boards |
| `zero_result_reason` | `actionable`, `no_crossing`, `crossing_below_floor`, `crossing_guarded`, `stale_data`, `expired_data`, `unverified_data`, or `no_priced_boards` |
| `lifetime` | p50/p90 seconds, sample count and live count |

Crossing keys are `event + market + line + period + settlement`; each record
keeps `first_crossed_at`, `last_crossed_at`, `last_seen_at` and
`disappeared_at`. The store is bounded to 5,000 keys and a 7-day retention.
Only aggregates, the crossing-key map, and one compact aggregate row per scan
are persisted; the full board is not duplicated.

The dashboard adds a **Crossing rate** tile and shows the actionable count or
the zero-result reason beneath it. `scripts/opportunity_baseline.py --days 7`
renders the aggregate report; the dated baseline is
`docs/evidence/2026-11-04-opportunity-rate-baseline.md`.

Tests: `tests/test_opportunity_metrics.py` (no crossing, below-floor crossing,
above-floor actionable, stale group, disappearance, bounded keys, API exposure,
and aggregate-only persistence).

## Browser hardening

`server/app.py` sets `Content-Security-Policy` (`default-src 'self'`,
`object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`,
`connect-src 'self'`), `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` on the dashboard and
every API response. Every request gets a fresh CSP nonce; the dashboard's two
script tags (the pre-paint theme bootstrap and `/js/app.js`) are stamped with it
and `script-src` is `'self' 'nonce-…'` with no `'unsafe-inline'`.

The dashboard no longer ships or generates inline `on*` handlers or JSON inside
HTML attributes. Actions are `data-action` attributes read by one delegated
listener; copy buttons carry `data-copy`/`data-copy-message` values escaped for
attribute context. A scraped name such as
`O'Brien "X" <img src=x onerror=alert(1)>` stays text and its copy button passes
the exact string to the clipboard.

`style-src` still admits `'unsafe-inline'`: generated rows set CSS custom
properties and widths (`style="--color:…"`), which a nonce cannot cover. This
is the remaining documented gap; script execution is closed.

Tests: `tests/test_csp_nonce.py`, `tests/test_frontend_xss.py`.

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
`--check`.

`python scripts/soak.py --cycles 6 --interval 5 --pid <server-pid> --check`
on the final code (punctuation, expiry and CSP included):

| Sample | Matches | Groups | Surebets | RSS | Browsers | Errors |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6,397 | 1,037 | 9 | 755.2 MB | 0 | 0 |
| 6 | 6,397 | 1,037 | 9 | 870.5 MB | 0 | 0 |

Memory grew **15.27%**, no browser process survived, all six scans returned the
same 1,037 groups and 9 surebets, and the run passed `--check`.

After removing the cache's double JSON serialization, a three-cycle run started
at **626.4 MB** and ended at **782.6 MB** (24.9%), with 0 surviving browsers and
9–10 surebets per scan. The absolute high-water mark fell from 875 MB to 783 MB.

A ten-cycle run on the final matching code produced this RSS curve:

`592.8 → 701.7 → 760.4 → 758.5 → 757.5 → 796.0 → 768.4 → 767.4 → 767.4 → 767.4 MB`

It **plateaued at about 767 MB after cycle 7**, with 29.45% growth from the first
sample (limit 50%), 0 surviving browsers, 0 errors and 10–12 surebets per cycle.
The plateau is the important result: growth is not linear. The 24-hour run
remains open. On the six-cycle soak's nine surebets, seven
re-verified at a fresh price (Najran–Jubbah, Anaitasuna–Alaves,
Zakynthos–Niki Volou, Manchester United–Roma, Roma–Sassuolo, Villarreal–PSG and
Mainz–Bayern); the two Boston United–Leicester U21 legs were gone on re-check and
are reported as gone.

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
fixture that only paired after the anchor fix. The latest scan at **07:54 UTC** found **6,624 matches, 1,074 verified groups
and 11 surebets**. Pairing quality is now in the health payload: `/api/health`
and `/api/results` carry the same `pairing` summary the audit computes. The
06:30 verified sample had 10 surebets; eight re-verified at a fresh price and
the two Boston United–Leicester U21 legs were gone.

## Pairing coverage

`python scripts/pairing_audit.py --check` reads the same cache the dashboard
serves and exits non-zero when a same-fixture offer is left unpaired or a group
repeats a bookmaker.

| Metric | Value |
|---|---:|
| Matches | 6,624 |
| Verified multi-book groups | 1,074 |
| Listings in groups | 5,987 |
| Ungrouped listings | 637 |
| Duplicate listings from a book already in the group | 305 |
| Strict misses (same league, ±15 min, both teams ≥80% alike) | 22 |
| Strict miss rate | **0.33%** |
| Groups repeating a bookmaker | 0 |

Per-book grouping, including duplicate listings:

| Book | Grouped / matches | Rate |
|---|---:|---:|
| MDShop | 627 / 638 | 98.3% |
| Admiralbet | 627 / 638 | 98.3% |
| MBet | 634 / 659 | 96.2% |
| WWIN | 733 / 763 | 96.1% |
| SportPlus | 735 / 750 | 98.0% |
| Premier Kladionica | 767 / 855 | 89.7% |
| MaxBet | 759 / 839 | 90.5% |
| Betole | 843 / 1,147 | 73.5% |
| Mozzartbet | 262 / 335 | 78.2% |

The low Betole/Mozzartbet rates are mostly duplicate listings and leagues no
other book carries, not same-fixture misses: only 22 offers in the whole scan
have a strict counterpart in another book that the matcher failed to pair. The
remaining examples are abbreviations, transliterations and one-sided qualifiers
the veto correctly keeps apart, such as `Hamburger` / `Hamburger SV`,
`Enppi` / `Asyut Petrol`, `Chindia T.` / `Chindia Tar.`, and
`AFC Emley` / `Emley`.

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
5. **Canonical punctuation is lossless.** `shimizu s-pulse` and
   `shimizu s pulse` were different canonical ids even though their raw names
   were equal. Comparing canonical ids with the same punctuation folding fixed
   MBet/Admiralbet fixtures in Japan, Korea, Norway and Saudi Arabia; MBet's
   grouping rate rose from 97.3% to 98.7%.
6. **One-sided qualifiers are accepted only when unambiguous.** `Werder` /
   `Werder Bremen`, `Central Coast` / `Central Coast Mariners` and
   `Slatina CSM` / `CSM Slatina` pair. Extra tokens that can name a different
   club (`City`, `United`, `Inter`, `Real`, `Atletico`, `Deportivo`) are
   vetoed, and so are ambiguous shared names such as `Sporting` /
   `Sporting CP`.
7. **Processing order uses the same open-league definition as candidates.**
   Betole's unmapped `germany, bundesliga` no longer sorts as a specific league
   ahead of Mozzart's `bundesliga`, so Mozzart anchors and Betole joins through
   the resolver instead of one of them becoming a singleton.
8. **Pairing quality is a health metric.** Every scan stores the audit result in
   `_pairing_summary`; `/api/health` exposes `pairing`/`live_pairing` and
   `/api/results` exposes `pairing`. The number cannot drift from the cached
   rows because it is computed from them, and it is recomputed after a cache
   restore so a restart does not lose it.
9. **Prematch expiry is real.** A group is dropped once the latest kickoff any
   book claims is more than two minutes past. Live mode still prices started
   matches; the old 15-minute prematch grace kept pricing fixtures that had
   already begun.

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
* `script-src` is nonce-based with no `'unsafe-inline'`; `style-src` still admits
  inline styles because generated rows set CSS custom properties and widths.
* In-play remains deferred.

**Verdict:** the prematch scanner is working and finds real, re-verified
surebets across the nine scrapable books. It is ready for supervised prematch
use; it is not yet a fully unattended betting product.
