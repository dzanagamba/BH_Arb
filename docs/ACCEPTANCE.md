# Acceptance record — 2026-11-03

This is the dated evidence behind the production-readiness claim. It is a
measurement, not a promise: every number below was produced by the command
named next to it.

## CI and replay

| Check | Command | Result |
|---|---|---|
| Tests | `python -m pytest` | **1,150 passed** |
| Lint | `python -m ruff check .` | clean |
| Types | `python -m mypy .` | clean on 111 source files |
| Market doc | `python scripts/generate_market_mapping_doc.py --check` | in sync |
| Cold replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --cold --check` | exit 0, fixed point |
| Seeded replay | `python scripts/replay_mappings.py tests/fixtures/replay/2026-11-03 --seeded --check` | exit 0 |

The cold replay starts with an empty evidence ledger, learns from the frozen
corpus, and reaches a pass that adds no claim and changes no verdict. It has 0
false merges and 0 unresolved evidence-backed pairs.

## Real prematch scan

`python main.py`, then `POST /api/scan?mode=prematch` at **2026-11-03 03:44 UTC**.

| Metric | Value |
|---|---|
| Books returning matches | 9 / 9 enabled (Betole, MaxBet, MDShop, Admiralbet, MBet, SportPlus, Premier Kladionica, WWIN, Mozzartbet) |
| Matches | 6,503 |
| Verified groups | 1,039 |
| Listings in groups | 5,754 |
| Price comparisons | 4,481 |
| False merges (different Betradar ids in one group) | 0 |
| Price outliers | 3 (two dropped with their surebets) |
| Surebets shown | 8 |

Two outlier surebets were dropped: `boston utd – leicester u21` (MaxBet X2) and
`ael limassol – iraklis gerolakkou` (Betole GG, a 10.75% phantom). The eight shown
were re-checked with `POST /api/verify`; every one returned `still_profitable:
true` on a fresh scrape.

| Match | Market | Profit | Books |
|---|---|---:|---|
| kanazawa – parceiro n | 1X2 | 7.59% | mdshop / sportplus / mozzartbet |
| kanazawa – parceiro n | 1X2 + DC | 5.96% | mdshop / mozzartbet |
| nara – kusatsu | O/U 2.5 | 3.94% | mbet / mozzartbet |
| anaitasuna ft – alaves | BTTS | 1.69% | betole / maxbet |
| nara – kusatsu | BTTS | 0.54% | wwin / mozzartbet |
| fulham – newcastle | 1X2 | 0.49% (dust) | sportplus / mozzartbet / maxbet |
| atl madrid – bayern munich | draw / not-draw | 0.42% (dust) | mdshop / mozzartbet |
| roma – sassuolo | home / not-home | 0.42% (dust) | mbet / mozzartbet |

## Pairing coverage

The scan is a direct measurement of the naming problem:

| Ground truth | Fixtures | Grouped | Missed | Miss rate |
|---|---|---|---|---|
| Same non-empty Betradar id on >1 book | 736 | 711 | 25 | 3.4% |
| Identical raw teams + kickoff on >1 book | 1,032 | 986 | 46 | 4.5% |

The missed Betradar cases are almost all MaxBet; the missed exact-fixture cases
are MaxBet, Mozzartbet and the MDShop/Admiralbet pair, which is one NSoft price
source and is correctly not treated as two books.

## Betole

`BetoleScraper().scrape(live=False)` returns **1,239** matches. The scraper was
fixed to read `kickOffTime` and to keep `brMatchId` as a Betradar id. Betole is
now enabled; its first verified surebet was `anaitasuna ft – alaves` BTTS at
1.69%.

`EvlbetScraper().scrape(live=False)` returns **0** matches on the same date; EVLBet
remains disabled and is an evidence-backed absence, not a silent omission.

## Known gaps

* First-half over/under (`first_half_ou`) has no captured offer and remains
  experimental; eight of nine market types are enabled.
* Betole publishes several unregistered market codes; they are counted in
  `/api/health.unmapped_markets` and are not used for pricing.
* The legacy approve/reject HTTP routes are removed; the dashboard is read-only.
  The direct migration functions remain for legacy tests but are not reachable.
* Execution limits, partial acceptance, bankroll, a 24-hour soak and the paused
  security-hardening stash are not done.
* In-play remains deferred.

**Verdict:** the prematch scanner is working and finds real, re-verified
surebets across the nine scrapable books. It is ready for supervised prematch
use; it is not yet a fully unattended betting product.
