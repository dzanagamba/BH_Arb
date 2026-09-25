# Task 13 report — end-to-end regression guard for the mapping-certainty chain

**Commit:** `e29e1b072190f6700c56e02f3834f1e326754abd`
**File added:** `tests/test_e2e_certified.py` (9 tests)
**Status:** the whole chain was already correct, so the test passed on its first
run. Everything below is about how I established that it is not vacuous.

---

## 1. The fixture, and why these three books

The odds in the test are **not invented**. `tests/fixtures/markets/` holds 14
real payloads captured from live HTTP responses on 2026-09-25; this file drives
three of them through their books' **real** market-parsing entry points:

| Book | Real entry point | Real event id | 1X2 from the capture |
|---|---|---|---|
| mbet | `MBetScraper()._parse_event(event, seen, live=False)` — returns a whole `Match` | `e:fb:van-ahl:0005` | 1=5.00 X=4.33 2=1.45 |
| wwin | `_build_markets_from_bets(bets, mode="prematch")` (no standalone event parser exists) | `4620444` | 1=2.06 X=3.50 2=3.05 |
| sportplus | `SportPlusScraper()._parse_match(m, seen)` — returns a whole `Match` | `3289374` | 1=2.60 X=3.60 2=2.55 |

Real from the capture: every market, every label, every decimal value, the
books' own event ids. Filled in by the test, because three books' captures are
three different real fixtures and the gate can only judge a claim about *one*
fixture: the two team names, the league string, the kickoff. That is the split
`tests/test_market_fixtures.py` already documents for MBet ("the fixture
supplies the odds verbatim and only the event shell around them is filled in"),
so the precedent is established, not invented here.

### Why these three books and not others

I enumerated the 1X2 legs of all 14 captures and searched for a three-distinct-
bookmaker combination whose implied total falls inside
`(1/MAX_SUREBET_PROFIT_PERCENT, 1/MIN_PROFIT_PERCENT)`. `mbet + wwin +
sportplus` is the only prematch triple that lands in a plausible band, and it
lands there *only* when read in one particular orientation:

```
canonical frame   1 → mbet 5.00,  X → wwin 3.50,  2 → sportplus 2.60
                  implied 0.87027  →  14.90%  →  accepted
published frame   1 → mbet 5.00,  X → sportplus 3.60,  2 → wwin 3.05
                  implied 0.80565  →  24.13%  →  REJECTED as a scraper error
```

That is the whole reason the file is shaped the way it is. The fixture is
"Sarajevo vs Željezničar"; mbet publishes it that way and anchors the group;
wwin and sportplus both publish it **reversed**. So:

* a regression anywhere in the swap path does not change a number — it silently
  **deletes** the surebet, and the test says so in the failure message;
* the control for that claim is not a different fixture, it is the *same* three
  payloads with the relabelling undone.

WWIN's spelling ("Zeljeznicar - FK Sarajevo") also routes the pairing through
two reviewed aliases (`zeljeznicar|željezničar`, `fk sarajevo|sarajevo`), so
the allowlist seam is exercised by the positive path rather than asserted in
isolation. sportplus's capture carries the excluded 1X2-shaped block 178
("POLUVRIJEME ILI KRAJ"), so the excluded-block path rides along inside the
real payload.

---

## 2. The seams, and why these and not others

| Seam | Test | What a stage running in isolation would miss |
|---|---|---|
| **parse → registry → group** | `test_captured_markets_reach_the_verified_group_through_the_registry` | Whether what the parsers emitted is what the *group* carries, after the matcher has had its hands on it. |
| **group → `find_surebets`** | `test_gate_orientation_is_what_makes_the_three_books_priceable` | Whether the gate's `is_swapped` actually reaches the engine's leg mapping, rather than each side being individually correct. |
| **scrape clock → arbitrage** | `test_odds_aged_past_the_ttl_are_not_priced` | Whether the `fetched_at` the scrape stage recorded is honoured by the stage that prices it. |
| **any claim → gate** | `test_one_broken_claim_removes_the_pairing_and_the_surebet` (4 params) | That spoiling one book kills the three-book 1X2, and *which stage* killed it. |
| **scan → serve** | `test_scan_applies_stored_link_proofs_and_serves_the_surebet` | Every wiring step inside `run_scan` at once, including the one that matters most in production: stored link proofs being applied to freshly scraped matches. |
| **serve, negative** | `test_scan_refuses_a_link_proof_that_aged_out` | That the link gate is revocable — the positive test's claim is only worth anything if something can withdraw it. |

**Deliberately not covered**, and why:

* **The live feed.** Every capture is prematch. A live group's odds expire
  mid-scan and the live captures' books do not form a plausible band.
* **The AI ranking path.** It can only reorder the review queue; it cannot
  create or approve a pairing. Owned by `tests/test_scan_candidates.py`. Here
  `api.MatchAI` is replaced by a stub with no HTTP client, and the served tests
  assert `_AI_CONSTRUCTIONS == []` — the AI is never even *constructed* when
  every pairing is proven — and that no queued candidate ever carries an AI
  verdict. That is a positive statement of "AI never auto-approves", not just
  an absence of one.
* **The matcher's confidence scorer in isolation.** It is not a seam between
  two stages, and the four breaker cases do exercise it (see §4).

---

## 3. For each assertion, the regression it would catch

### `test_captured_markets_reach_the_verified_group_through_the_registry`
* `set(emitted) == set(capture["expected_markets"])` per book, asserted on the
  **group's** copy of the match, not the parser's. Catches a block that leaks or
  disappears between the parser and the group. Set **and** count both matter:
  sportplus's excluded block 178 is 1X2-shaped, so a merge that duplicated it
  changes what the group holds.
* `registry.ids_for(book, "prematch", MarketType(mt))` non-empty for every
  emitted type. Catches a market reaching the pipeline without a registry row.
* `carried == expected` where `expected` is the parse output relabelled
  1↔2 / 1X↔X2 for the two reversed books. Catches a wrong flip map, a
  flip applied to the anchor, a flip applied to an orientation-free label
  (Over/Under, GG/NG), and any value drift — the values must stay the books'
  own, byte for byte.
* `group.canonical_home/away == "fk_sarajevo"/"fk_zeljeznicar"`. Catches the
  frame being decided by the wrong book.
* `is_swapped` False for the anchor, True for the two reversed books. Catches
  the flag and the relabelling drifting apart.
* allowlist `team_identity` evidence exists **and names both entries**. Catches
  a silent fuzzy hit being reported as a rule hit.

> **SUPERSEDED — see §F.7(a).** This bullet overstated the assertion. Naming an
> entry proves only that it is *configured*, because `certainty.py` dumps the
> whole allowlist into `allowlist_entries`. The test now asserts the attribution
> (which pairing was credited to the allowlist) instead.

### `test_gate_orientation_is_what_makes_the_three_books_priceable`
* surebet is not None; `total_margin ≈ EXPECTED_MARGIN`;
  `profit_percent ≈ EXPECTED_PROFIT`. `EXPECTED_MARGIN` is written out as
  `1/5.0 + 1/3.5 + 1/2.6` in the test, not read back from the engine, so the
  expectation and the measurement stay independent.
* `legs == {"1": ("mbet", 5.0), "X": ("wwin", 3.5), "2": ("sportplus", 2.6)}`
  and three distinct bookmakers. This is the sharpest assertion in the file:
  sportplus's raw `"1"` must surface as leg **2**, because sportplus published
  the fixture reversed. A swapped leg fails here with a message naming the book.
* equal `potential_return` across all three stakes; stakes sum to the
  investment. Catches a stake calculation that no longer equalises returns.
* **the unswapped control**: the same three matches, same parser output, same
  engine, `status="verified"`, relabelling undone ⇒ **no** 1X2 surebet. Catches
  "the engine priced mislabelled odds".
* plus a guard on the guard: `min` over all eight one-book-per-leg assignments
  of the raw odds must itself exceed `MAX_SUREBET_PROFIT_PERCENT`, so the
  control cannot quietly become a flattering one.

### `test_odds_aged_past_the_ttl_are_not_priced`
* fresh group ⇒ priced; same group with `fetched_at = now - (TTL + 60s)` ⇒ not
  priced. Catches the scrape stage's clock becoming decorative, i.e. an
  arbitrage computed from prices an hour old being presented as actionable.

### `test_one_broken_claim_removes_the_pairing_and_the_surebet` (4 params)
Each parameter spoils **one** book and leaves the other two and every captured
price alone, then asserts three things: the spoiled book reaches no returned
group, every returned group is `verified`, and no 1X2 surebet exists.

| Param | Break | Gate reason asserted | Regression caught |
|---|---|---|---|
| `wrong_league` | mbet's league → "Prva Liga RS" (a real, *specifically named* different competition) | — (the scorer's league hard gate refuses first) | A foreign competition's team names grouping with a domestic fixture's. |
| `unnamed_league` | wwin's league → "Superliga" (a bare name the matcher treats as generic) | `league_mismatch` | **The gate's own league rule.** The scorer's hard gate deliberately skips generic names, so it proposes the pairing and the gate is the only thing that can refuse it. |
| `kickoff_16min` | mbet 16 minutes late | `kickoff_delta` | The gate's 15-minute verified window being replaced by the scorer's 120-minute candidate window. |
| `link_unverified` | mbet's link unproven | — | `verified` meaning "everything except the links". |

For the two with a `gate_reason`, the test additionally asserts
`_calculate_confidence(broken, group) > 0` **before** asserting the gate's
refusal. That is deliberate: without it, a matcher that refused the pairing in
its own scorer would pass the closing assertion while never proving the
certainty gate does its job at all.

Every parameter runs the **intact** chain first and asserts it produced the
14.90% surebet, so the closing `is None` is structurally non-vacuous — same
code, same inputs, one difference.

### `test_scan_applies_stored_link_proofs_and_serves_the_surebet`
Runs the real `run_scan("prematch")` with the three books' scrapers replaced by
their real parses carrying `deep_link_verified=False` (their genuine scraped
value) and every other book switched off. Link proofs are seeded into
`api._deep_link_verifications` the way a verification run would, and reach the
gate only through `_apply_deep_link_verifications` during the scan.

Asserts: `status.errors == []`; `total_matches == 3`; the AI was never
constructed; the review queue is empty (a proven pairing must not re-enter it);
each cached match carries its own event id, has `deep_link_verified is True`
and its own market count; the report has exactly one `verified` group with the
right canonical pair and `num_markets == [6, 6, 6]`; and `get_results` serves
`group_statuses == {"verified": 1}` and one 1X2 surebet whose leg→book→odds map
is exactly `EXPECTED_LEGS` at the expected profit.

`num_markets == [6, 6, 6]` is the report agreeing with the parsers: a wrong
registry ID drops a market and the report counts 5.

### `test_scan_refuses_a_link_proof_that_aged_out`
Runs the scan twice — fresh proof, then a proof older than
`DEEP_LINK_VERIFICATION_TTL_SECONDS`. Asserts the second run finds 0 surebets,
serves no group at all, still caches the three matches (unproven), and instead
queues every pair for review with `link_blocked is True`,
`"link_unverified" in rule_rejections`, and no AI verdict. The first
`assert surebets_found > 0` is the control: one TTL of age is the only
difference.

---

## 4. Did it pass on first run? Yes. Is it vacuous? No — 18 mutations

> **SUPERSEDED — see §F.5.** The table below mixes measurements from two states of
> the test file (some rows were taken when it had 7 tests, not 9) and its numbers
> are not a single measurement set. §F.5 re-runs all 21 mutations against the
> final file in one harness run and is the table to read. The original is kept
> below for the audit trail, not for its numbers.

`pytest tests/test_e2e_certified.py` passed 7/7 on the first execution (later
grown to 9). Passing immediately is expected: Tasks 1–12 already shipped the
behaviour. So the real work was proving the assertions can fail. I applied each
mutation to a tracked file, ran only this file, and reverted with
`git checkout -- .`.

| # | Mutation | Result |
|---|---|---|
| 1 | `engine/matcher.py:419` `FLIP_MAP` → identity (relabelling disabled) | **6 failed** |
| 2 | `engine/certainty.py:221` `_link_evidence` always returns `verified_link` | **2 failed** |
| 3 | `config/settings.py` `VERIFIED_KICKOFF_WINDOW_MINUTES` 15 → 30 | **1 failed** |
| 4 | `engine/matcher.py:279-284` drop the `status == "verified"` filter | 9 passed (see §6) |
| 5 | `engine/arbitrage.py:213` remove the `MAX_SUREBET_PROFIT_PERCENT` cap | **1 failed** |
| 6 | `server/api.py:388` `_apply_deep_link_verifications` never applies | **2 failed** |
| 7 | `server/api.py:321` deep-link TTL × 1000 | **1 failed** |
| 8 | `config/bookmaker_markets.json` sportplus prematch 1X2 `1` → `999999` | **6 failed** |
| 9 | `server/api.py:1079` `run_scan` never fills the match report | **1 failed** |
| 10 | `server/api.py:1097` `find_surebets` fed a group rebuilt from the raw, unswapped `all_matches` (label corrected in fix round 2) | **1 failed** |
| 11 | `engine/certainty.py:66` `_league_ok` accepts every pair | 9 passed → **fixed, see below** |
| 12 | `engine/certainty.py:124` any fuzzy pair treated as allowlisted | 9 passed (owned elsewhere) |
| 13 | `config/bookmaker_markets.json` mbet prematch 1X2 `ofb:fs` → `ofb:ft` | **6 failed** |
| 14 | `engine/arbitrage.py:135` remove the odds-TTL staleness check | 9 passed → **fixed, see below** |
| 15 | `engine/certainty.py:263` `kickoff_ok` widened to 120 | 9 passed (masked, see §6) |
| 16 | `config/team_alias_allowlist.json` drop this fixture's two aliases | **8 failed** |
| 17 | `server/api.py:1339` `get_results` drops the `group_statuses` tally | **1 failed** |
| 18 | Both gate kickoff checks widened to 120 together | **1 failed** |

### Two holes this found, and what I did about them

**Mutation 11 — the gate's league rule was untested.** With `_league_ok` neutered
everything stayed green, because the matcher's own scorer has a league hard gate
that fires first. The two layers are independent and the file only exercised one
of them. Fixed by adding a fourth breaker, `unnamed_league`: wwin's league
becomes "Superliga", a bare competition name in the matcher's `GENERIC_LEAGUES`
set. The scorer deliberately skips its league gate for generic names, so it
proposes the pairing (confidence 1.0) and the **gate** is the only thing that can
refuse it. Mutation 11 now fails that case:

```
FAILED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[unnamed_league]
E   AssertionError: the spoiled book's claim must not reach a returned group
E   assert {'mbet', 'sportplus', 'wwin'} == {'mbet', 'sportplus'}
```

This is a scope addition beyond the three breakers the brief named. I judged it
worth it because the brief's `wrong league` case alone leaves the gate's league
rule unobservable, which is precisely the "passes but proves nothing" outcome the
brief warns against.

**Mutation 14 — the odds-TTL check had no coverage anywhere.** Removing
`engine/arbitrage.py:135` left the **entire** suite green: 494 passed, 1 xfailed,
with every other test file deselected. `grep` confirms no test mentions
`ODDS_TTL`, `fetched_at` or staleness. That is a real gap in a rule the
arbitrage stage exists to enforce. Fixed by adding
`test_odds_aged_past_the_ttl_are_not_priced`, which now fails under mutation 14.
Also a scope addition, on the grounds that it is squarely on the scrape →
arbitrage seam in the chain I was asked to prove.

### Environment claims, verified not asserted

```
$ ... python.exe "…/no_net.py" tests/test_e2e_certified.py      # DNS + connect blocked
9 passed in 2.20s

$ ... python.exe "…/no_browser.py" tests/test_e2e_certified.py   # async_playwright().start() blocked
9 passed in 2.07s
```

No socket is opened, and no browser is started. `playwright` is *imported*
(module scope in `scrapers/base.py`, which `server/api.py` imports); the
launcher is what must never run, and it does not. Playwright must not launch —
confirmed, not assumed.

---

## 5. Commands and output

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_e2e_certified.py -p no:cacheprovider -rA --tb=no -o addopts=""
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 9 items

tests\test_e2e_certified.py .........                                    [100%]

=========================== short test summary info ===========================
PASSED tests/test_e2e_certified.py::test_captured_markets_reach_the_verified_group_through_the_registry
PASSED tests/test_e2e_certified.py::test_gate_orientation_is_what_makes_the_three_books_priceable
PASSED tests/test_e2e_certified.py::test_odds_aged_past_the_ttl_are_not_priced
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[wrong_league]
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[unnamed_league]
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[kickoff_16min]
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[link_unverified]
PASSED tests/test_e2e_certified.py::test_scan_applies_stored_link_proofs_and_serves_the_surebet
PASSED tests/test_e2e_certified.py::test_scan_refuses_a_link_proof_that_aged_out
============================== 9 passed in 2.24s ==============================
```

```
$ "…/python.exe" -m pytest
503 passed, 1 xfailed, 3 warnings in 18.03s        # 494 before this file
```

```
$ "…/ruff.exe" check .
All checks passed!

$ "…/mypy.exe" .
Success: no issues found in 58 source files
```

The 1 xfail is the pre-existing strict xfail for the known premier live BTTS
defect in `tests/test_market_fixtures.py`. Untouched by this task.

---

## 6. Defects found, NOT fixed

None are behavioural defects in the shipped chain — the chain is correct. Three
observations, none of which I changed, because doing so is not this task's call:

1. **`engine/matcher.py:279-284` — two conditions that cannot be told apart.**
   `g.status == "verified" and len({m.bookmaker for m in g.matches}) >= 2`:
   a group is born as a one-match `suggested` and only becomes `verified` when a
   second bookmaker is admitted by the gate, so a 2-book group is always
   `verified`. Mutation 4 (dropping the status clause) changes nothing
   observable, in this file or any other. It is a redundant guard, not a bug.
   Worth knowing because it means the `status == "verified"` clause is asserted
   by nothing and can be deleted silently.

2. **`engine/certainty.py:263` and `:432` — the kickoff window is checked twice.**
   `evaluate_pair` and `_group_kickoff_reason` both compare against
   `self.kickoff_window_minutes`. Neutering only `kickoff_ok` (mutation 15) is
   masked by the group-level check; neutering both (mutation 18) is caught. Both
   read the same setting, so the setting itself is pinned (mutation 3 caught).
   Same shape as (1): redundancy that no single-site mutation can reach.

3. **`engine/arbitrage.py:135` — the odds-TTL rule was uncovered until this
   task.** Reported under §4; now covered here.

Also worth recording, though it is documented state rather than a defect: with
`deep_link_verified` False for every scraped match, a production scan finds zero
`verified` groups and serves zero surebets, and
`test_scan_refuses_a_link_proof_that_aged_out` reproduces exactly that shape
(with expired rather than absent proofs). Nothing in this file asserts that
end state, so the tests will keep passing when the links are fixed — which is the
point.

---

## 7. Concerns

1. **The team names, league and kickoff are synthesised.** Everything else is
   real. The odds are the books' own, so a swap-map or registry-ID bug shows up
   as a *changed leg mapping* rather than a changed number — which is why the
   assertions are written as exact leg→book→odds maps instead of a profit
   percentage. If someone later swaps in a same-book pair of captures, or
   fabricates a payload, the test loses most of its value silently. The
   docstring and the `_capture` helper say so, but nothing enforces it. A
   provenance assertion on `expected_markets`/`source` (as
   `test_fixture_records_its_provenance` does) would close that; I left it out
   because `tests/test_market_fixtures.py` already pins provenance for all 14
   captures.

2. **`mdshop`, `admiralbet`, `premier_kladionica`, `mozzartbet`, `betole`,
   `evlbet` are not in the e2e chain.** They are covered at the parse layer by
   `tests/test_market_fixtures.py`. Extending the e2e to a second triple would
   need another plausible-arbitrage combination, and I could not find one in the
   remaining captures' numbers. This is a coverage limit, not a claim.

3. **The `_match_result_surebet` helper filters to `MarketType.MATCH_RESULT`.**
   The fixtures also produce 1.82% and 7.64% Over/Under surebets, and two
   cross-market ones the engine rejects at 26.7% and 36.5%. The tests ignore
   them. That is deliberate — 1X2 is the market that needs three distinct books,
   which is what makes the per-book negative cases bite — but it means a
   regression in `_check_line_market` or `_check_cross_market_dc` will not show
   up here.

4. **The expected profit is a hard-coded 14.90%, tied to odds captured on one
   day.** If `tests/fixtures/markets/*.json` is regenerated from a new capture,
   the 1X2 legs change and `EXPECTED_LEGS` / `EXPECTED_MARGIN` /
   `UNSWAPPED_COMBINATIONS` must be re-derived. That is the intended coupling —
   the test should break when the capture changes — but it will read as a test
   failure rather than as "re-capture the fixtures", and the module docstring
   does not say so explicitly. Worth a line if this file outlives the capture.
   **Fixed in fix round 1** — the note is now in the file.

5. **`KICKOFF = now + 30h` is evaluated at import.** A test session that sits
   idle for 30 hours between collection and the server tests would see an
   expired group. Not reachable in practice; noted for completeness.

---

# Fix round 1

The blocker was the omission, not the code. Two of the brief's four deliverables
were dropped and the report did not say so. Both are now written, the mutation
table is rebuilt from a single measurement set, and the three cheap corrections
are in. **A PROCESS ERROR OF MINE IS ALSO RECORDED HERE, in §F.4** — partway
through this round I destroyed a set of edits with a `git checkout -- .` in my own
mutation harness, and the evidence that it happened is part of the record.

## F.1 `README.md` — what was added

**1. A status callout at the top of the file**, above "What it does", because the
most likely reader never reaches the new section. It states that a surebet is
only ever shown for a `verified` group, that MDShop's and Admiralbet's
`?event=<id>` routes are inert, that **in production zero groups reach `verified`
and zero surebets are produced**, that only Mozzartbet's link verifies, and that
this is a bookmaker-side routing fact rather than a code bug.

**2. A `## Match & mapping certainty` section**, covering everything the brief's
Step 3 listed:

* **The two stages.** Stage 1 is the rule stage (`engine/certainty.py` used by
  `engine/matcher.py`): every gate appends a `MatchEvidence` record, and the
  status follows from the reasons left over. Stage 2 is the AI stage
  (`engine/ai.py` used by `server/api.py`), which may only **rank** queued
  pairings and can neither create nor approve one.
* **The three statuses**, with the real reason vocabulary read out of
  `certainty.py`: `verified` (zero reasons, links included), `suggested`
  (`kickoff_missing`, `kickoff_delta`, `team_unresolved`, `link_unverified`,
  `no_event_link`), `rejected` (`league_mismatch`, `category_mismatch`,
  `orientation_unresolved` — the `HARD_REJECT_REASONS` set).
* **The two rules that carry the invariant**: the reviewed alias allowlist is the
  only auto-accepted fuzzy path, and `deep_link_verified` is a machine fact a
  human approval may never set.
* **The review queue**, and the brief's "Review tab URL path" — answered
  accurately rather than inventively: **there is no URL path.** `server/app.py`
  serves the dashboard only at `/`, there is no `/review` route, and
  `frontend/js/app.js` has no hash or query routing, so the Review tab is
  reached by opening `http://localhost:8000` and clicking **Review**. Its data
  is `GET /api/candidates`; the endpoints are
  `POST /api/candidates/{candidate_id}/approve` and `.../reject` (verified
  against the `@router.post` list in `server/api.py:1496,1545`).
* **The three env vars** `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL`, with their
  real defaults (`https://api.openai.com/v1`, `gpt-4o-mini`) from
  `engine/ai.py:44-51`, and the fact that an unset `AI_API_KEY` means
  `MatchAI.available` is `False` so the AI stage is never entered at all.
* **The two scripts**, with real invocations:
  `python scripts/generate_market_mapping_doc.py [--check]` and
  `python scripts/verify_deeplinks.py <bookmaker> [--mode] [--limit]`.
* **The convergence caveat**: `build_targets` has no offset, no cursor and no
  skip-already-checked, so a repeated call re-checks the same first N events
  forever and a per-book sweep over 600+ events cannot converge today. The fix is
  a cursor, not a bigger `--limit`. Deep-link verification is explicitly *not*
  presented as a one-shot operation.
* **Both known defects with their tripwires**: `premier_kladionica/live/btts`
  (guarded by `xfail(strict=True)`, so fixing the parser produces an XPASS that
  pytest reports as a failure; the fix is mode-awareness, not a registry rename)
  and the NSoft live-window bug (a `KNOWN DEFECT` comment in
  `scrapers/mdshop.py`; `dateFrom=now` filters out every already-started in-play
  game, so both NSoft books most likely return no live matches at all today).

## F.2 `PLAN.md` — what was added

**1. A new status line** in the header block, dated 2026-09-25, recording that
Phase 4 shipped and repeating the headline: 13 tasks, 503 tests green, and the
scanner now produces zero surebets on purpose.

**2. `### Phase 4 — Mapping certainty (Done)`** as the last subsection of §3,
which is where the brief's Step 4 put it. It summarises the 13 shipped tasks,
states the invariant, states the headline result with the measurement behind it
(0 of 197 candidate groups verified on a real 1,592-match three-book feed), and
lists the three recorded-not-fixed items — the premier live BTTS defect, the
NSoft live window, and the missing cursor — each with the reason and, where one
exists, the tripwire.

## F.3 The mutation table — decision: re-run everything against the final file

I did not split the table. Every row was re-measured against the **final
9-test file**, all in one harness run, and §F.5 below replaces the original §4
table wholesale. Three rows changed materially:

| Row | Round 0 (as published) | Round 1 (re-measured) | Why |
|---|---|---|---|
| FLIP_MAP → identity | 6 failed | **8 failed** | The round-0 number was measured on the 7-test file. The two tests added afterwards (`odds_aged_past_the_ttl`, `unnamed_league`) both assert the 1X2. |
| sportplus 1X2 id, mbet 1X2 id, alias entries dropped | 6 / 6 / 8 failed | **8 / 8 / 8** | Same cause: earlier 7-test state. |
| `find_surebets` fed a group rebuilt from the raw `all_matches` | 1 failed | **1 failed** | Unchanged; the reviewer's static trace of 2 does not apply to the mutation I actually wrote — see §F.6. |

The original table's substantive claim — no mutation that matters goes uncaught —
survives, and is now backed by one consistent measurement set. Three new rows
(M18–M20) were added to justify the strengthened alias assertion.

## F.4 A process error I made, and its evidence

Partway through this round I ran `git checkout -- .` in the mutation harness
while `tests/test_e2e_certified.py` had **uncommitted** fix-round edits. Because
that file is tracked (committed in `e29e1b0`), the checkout silently reverted all
four of them. I noticed only because a strengthened assertion I had just written
failed to catch a mutation I had verified by hand — the harness was testing the
committed file, not the edited one.

The harness now reverts **only the file it mutated** (`git checkout -- "$file"`)
and never touches the test file. All four edits were redone and re-verified
afterwards. This is the same class of error the reviewer flagged in my review
history: a claim about an artefact that the artefact did not support. The
practical rule I am carrying forward is that a mutation harness must never revert
anything it did not mutate.

## F.5 The re-measured mutation table (final file, one run)

| # | Mutation | Failed / 9 |
|---|---|---|
| M1 | `engine/matcher.py` `FLIP_MAP` → identity (swap relabelling disabled) | **8** |
| M2 | `engine/matcher.py:279-284` drop the `status == "verified"` filter | 0 — see §F.7 |
| M3 | `config/settings.py` `VERIFIED_KICKOFF_WINDOW_MINUTES` 15 → 30 | **1** |
| M4 | `engine/arbitrage.py:213` remove the `MAX_SUREBET_PROFIT_PERCENT` cap | **1** |
| M5 | `engine/arbitrage.py:135` remove the odds-TTL staleness check | **1** |
| M6 | `engine/certainty.py:221` `_link_evidence` always returns `verified_link` | **2** |
| M7 | `engine/certainty.py:66` `_league_ok` accepts every pair | **1** |
| M8 | `engine/certainty.py:124` any fuzzy pair treated as allowlisted | 0 — owned elsewhere |
| M9 | `engine/certainty.py:263,432` **both** kickoff checks widened to 120 | **1** |
| M10 | `config/bookmaker_markets.json` sportplus prematch 1X2 `1` → `999999` | **8** |
| M11 | `config/bookmaker_markets.json` mbet prematch 1X2 `ofb:fs` → `ofb:ft` | **8** |
| M12 | `config/team_alias_allowlist.json` drop this fixture's two aliases | **8** |
| M13 | `server/api.py:388` `_apply_deep_link_verifications` never applies | **2** |
| M14 | `server/api.py:321` deep-link TTL × 1000 | **1** |
| M15 | `server/api.py:1079` `run_scan` never fills the match report | **1** |
| M16 | `server/api.py:1097` `find_surebets` fed a group rebuilt from the raw, unswapped `all_matches` instead of the gate's `groups` | **1** |
| M17 | `server/api.py:1339` `get_results` drops the `group_statuses` tally | **1** |
| M18 | `engine/certainty.py` credits the allowlist to byte-identical pairings | **1** |
| M19 | `engine/certainty.py` empties `allowlist_entries` | **1** |
| M20 | `engine/certainty.py:233` `_link_evidence` stops emitting `link_unverified`, so `evaluate_pair` never collects the reason (`:334` no longer matches — the collection is **disabled**, not renamed) | **2** |
| M21 | `engine/certainty.py` `HARD_REJECT_REASONS` never applies | 0 — owned elsewhere |

17 of 21 caught by this file. The four zeros are each accounted for:

* **M2** — `engine/matcher.py:279-284`'s two conditions (`status == "verified"`
  and `>= 2 bookmakers`) are equivalent for any group the matcher can build, so
  no black-box test can require the status clause. Redundant guard, not a defect.
* **M8** — the allowlist requirement is pinned by `tests/test_certainty.py` and
  `tests/test_matcher_certified.py`; removing it fails 11 tests there.
* **M21** — the `rejected` status is pinned by `tests/test_certainty.py`; removing
  `HARD_REJECT_REASONS` fails 4 tests there (`test_league_mismatch_is_rejected_with_exact_reason`,
  `test_category_mismatch_is_rejected_with_exact_reason`,
  `test_consistent_alias_swap_flag_survives_other_failed_gates`,
  `test_allowlisted_alias_does_not_bypass_hard_gates`). Verified by running the
  suite with this file deselected: `4 failed, 490 passed, 9 deselected, 1 xfailed`.
* **M2/M8/M21 are not gaps in this file's remit.** M21 is worth naming plainly
  though: this file never distinguishes `rejected` from `suggested`, because both
  are simply "not `verified`" to the matcher. That is a real limit of the e2e
  layer, and it is recorded here rather than papered over.

## F.6 Why M16 is 1 and not the 2 the reviewer's static trace predicted

The reviewer's trace assumed this mutation makes `find_surebets` raise
`AttributeError` because `Match` has no `.matches`. It does not: the mutation
replaces the argument with
`[MatchGroup(..., matches=[m for m in all_matches], ...) for g in groups[:1]]`,
and `all_matches` is a list of `Match`, so the `MatchGroup` constructs fine. What
changes is that the group then holds the **raw** matches, so the 1X2 is priced in
the published frame at 24.13% and the engine rejects it — the same mechanism as
the in-test unswapped control. `test_scan_applies_...` fails on
`assert len(served) == 1`. `test_scan_refuses_...` survives because its first
assertion is `surebets_found > 0`, and the two Over/Under surebets are still
found. So 1 is the correct number for the mutation I applied.

> **Corrected in fix round 2.** The row's original label — "fed `all_matches`, not
> `groups`" — is what sent the re-reviewer down the wrong path, exactly as the
> controller ruled: I was right on the number and the reviewer was wrong, but the
> label caused it. The label now says the group is *rebuilt from the raw,
> unswapped* `all_matches`, which is the mechanism. The same fix was applied to the
> round-0 table at `:216` and to the round-1 comparison row.

## F.7 Cheap corrections

**(a) `test:357-359`, the alias-evidence assertion — strengthened, and the
report claim corrected to match.** The reviewer is right that naming an entry
proves only that it is configured: `certainty.py:323-325` dumps the whole
allowlist into `allowlist_entries`. The old assertion therefore proved nothing
about *which* pairing used the allowlist. The test now asserts the attribution
itself — exactly one `team_identity` record is `source="allowlist"` with
`reason="swapped"` and `confidence=1.0` (WWIN's), the others are `source="rule"`
with **empty** `allowlist_entries` (SportPlus's byte-identical names) — and
separately that both of WWIN's spellings are on the named list. **M18 and M19
above are the proof it is not vacuous:** M18 makes the gate credit the allowlist
to the byte-identical pairing (1 failed), M19 empties `allowlist_entries`
(1 failed). The code comment now says explicitly that the entry list alone is not
the claim.

**(b) `test:501`, the over-specified `link_unverified` expectation — relaxed to
the safety claim.** The old `group_books == set()` held only via input order plus
the strict `confidence > best_conf` tie-break at `matcher.py:206-210`, so a benign
tie-break change would have failed the test while the safety claim still held.
`group_books` is now `set[str] | None`; for that one case the test asserts what it
actually means — **no returned group may hold all three books, which is precisely
why no 1X2 surebet can exist** — with a comment saying why the exact set is
deliberately not asserted. The other three cases keep their exact sets, which are
deterministic because the scorer's league and kickoff hard gates mean the spoiled
book is never even a candidate.

**(c) `test:779`, the comment that asserted nothing — deleted.** "which a human
approval explicitly cannot clear" was a claim about `approve_candidate`, which
this scan-level test cannot see. The clause is gone and the comment now points at
`tests/test_scan_candidates.py`, where that contract is actually asserted.

**(d) `EXPECTED_LEGS` re-derivation note — added** to the constant's comment:
`EXPECTED_LEGS`, `EXPECTED_MARGIN`, `EXPECTED_PROFIT` and
`UNSWAPPED_COMBINATIONS` are tied to the captured prices, re-running
`scripts/capture_market_fixtures.py` requires re-deriving all four, and that
coupling is intended.

## F.8 Covering files

| File | Change |
|---|---|
| `README.md` | Modified — status callout above "What it does"; new `## Match & mapping certainty` section. |
| `PLAN.md` | Modified — new 2026-09-25 status line; new `### Phase 4 — Mapping certainty (Done)` in §3. |
| `tests/test_e2e_certified.py` | Modified — the four cheap corrections. No test added, removed, or weakened. |
| `.superpowers/sdd/.../task-13-report.md` | This section. (Gitignored; the repo artefact is the other three.) |

No production file was changed. `engine/`, `server/`, `scrapers/`, `config/` and
`scripts/` are untouched — every mutation in §F.5 was reverted, and `git status`
shows only the three files above as modified.

## F.9 Commands and output

```
$ "…/python.exe" -m pytest tests/test_e2e_certified.py -p no:cacheprovider -rA --tb=no -o addopts=""
=========================== short test summary info ===========================
PASSED tests/test_e2e_certified.py::test_captured_markets_reach_the_verified_group_through_the_registry
PASSED tests/test_e2e_certified.py::test_gate_orientation_is_what_makes_the_three_books_priceable
PASSED tests/test_e2e_certified.py::test_odds_aged_past_the_ttl_are_not_priced
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[wrong_league]
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[unnamed_league]
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[kickoff_16min]
PASSED tests/test_e2e_certified.py::test_one_broken_claim_removes_the_pairing_and_the_surebet[link_unverified]
PASSED tests/test_e2e_certified.py::test_scan_applies_stored_link_proofs_and_serves_the_surebet
PASSED tests/test_e2e_certified.py::test_scan_refuses_a_link_proof_that_aged_out
============================== 9 passed in 2.28s ==============================
```

```
$ "…/python.exe" -m pytest
503 passed, 1 xfailed, 3 warnings in 14.91s
```

```
$ "…/ruff.exe" check .
All checks passed!

$ "…/mypy.exe" .
Success: no issues found in 58 source files
```

**SUPERSEDED — see §G.1 and §G.2.** The 42-assertion script described in this
paragraph was a one-off at `%TEMP%/opencode/e2e/verify_docs.py` and **no longer
exists**. It was replaced by **`tests/test_readme_claims.py`**, committed and in
the suite. Three of its checks were labelled doc-vs-code but only inspected the
code, so this run is not evidence of anything the current file does. It is kept
below verbatim for the audit trail — including the two rows that are precisely
why the file was replaced: `README's suggested reason 'no_event_link' exists in
certainty.py` and `README's suggested reason 'kickoff_delta' exists in
certainty.py` each confirm only that the string is present in the source, so a
README inventing a reason passed both. §G.2 replaces them with a bidirectional
comparison against the reasons the gate actually *emits*.

**The documentation is also checked against the code, not just written.** Given
that four claims in this plan were corrected for describing something other than
what the code or data did, I wrote a 42-assertion check that reads `README.md`
and `PLAN.md` and compares every checkable statement to its source: the two
`AI_*` defaults against `engine/ai.py:44-51`, the five `suggested` and three
`rejected` reason strings against `engine/certainty.py` and
`HARD_REJECT_REASONS`, the four endpoint paths against the `@router` route table
in `server/api.py`, `--mode`/`--limit` against `scripts/verify_deeplinks.py`'s
argparse, "only Mozzartbet's link verifies" against
`config/bookmaker_deeplinks.json` (the only three books declaring
`supports_event_id: true` are `admiralbet`, `mdshop`, `mozzartbet`), and the
NSoft live-window figures (35 live events, 12h) against the `KNOWN DEFECT`
comment in `scrapers/mdshop.py` that measured them. The script lives outside the
repo at `%TEMP%/opencode/e2e/verify_docs.py` — a one-off check, not a committed
test, and the reviewer may want it as `tests/test_readme_claims.py`.

```
$ "…/python.exe" "%TEMP%/opencode/e2e/verify_docs.py"     # DELETED FILE
PASS  README: states zero surebets in production
PASS  README: names mdshop + admiralbet routes inert
PASS  README: mozzartbet is the only verifying link
PASS  PLAN: states zero surebets in production
PASS  PLAN: names mdshop + admiralbet routes inert
PASS  PLAN: mozzartbet is the only verifying link
PASS  README contains 'AI_API_KEY'
PASS  README contains 'AI_BASE_URL'
PASS  README contains 'AI_MODEL'
PASS  README contains 'scripts/generate_market_mapping_doc.py'
PASS  README contains 'scripts/verify_deeplinks.py'
PASS  README contains 'verified'
PASS  README contains 'suggested'
PASS  README contains 'rejected'
PASS  README contains '## Match & mapping certainty'
PASS  README has the anchor link
PASS  README names the review queue endpoints
PASS  README says the review tab has no URL path
PASS  README says the sweep cannot converge
PASS  README names the premier live BTTS tripwire
PASS  README names the NSoft live window defect
PASS  README: allowlist grants identity only
PASS  PLAN has the Phase 4 heading
PASS  README's AI_BASE_URL default matches the code
PASS  README's AI_MODEL default matches the code
PASS  README's suggested reason 'kickoff_missing' exists in certainty.py
PASS  README's suggested reason 'kickoff_delta' exists in certainty.py
PASS  README's suggested reason 'team_unresolved' exists in certainty.py
PASS  README's suggested reason 'link_unverified' exists in certainty.py
PASS  README's suggested reason 'no_event_link' exists in certainty.py
PASS  README's rejected reason 'orientation_unresolved' is in HARD_REJECT_REASONS
PASS  README's rejected reason 'category_mismatch' is in HARD_REJECT_REASONS
PASS  README's rejected reason 'league_mismatch' is in HARD_REJECT_REASONS
PASS  endpoint GET /candidates exists
PASS  endpoint POST /candidates/{candidate_id}/approve exists
PASS  endpoint POST /candidates/{candidate_id}/reject exists
PASS  endpoint POST /verify-links exists
PASS  only mdshop/admiralbet/mozzartbet declare an event route
PASS  verify_deeplinks has --mode prematch|live
PASS  verify_deeplinks --limit defaults to 3
PASS  README's 35-live-events figure matches scrapers/mdshop.py
PASS  README's 12h working window matches the code comment

42/42 doc claims verified against the code                      # DELETED FILE
```

> **Read those two rows with the banner in mind.** `README's rejected reason
> 'orientation_unresolved' is in HARD_REJECT_REASONS` was **true and misleading**:
> it confirmed the string is in a set, not that the gate emits it. It never does.
> That gap is what produced a real error in the README (§G.3) and it is why
> `tests/test_readme_claims.py` runs the gate instead of grepping it.

## F.10 Concerns after this round

1. **The original report is still wrong in one place and I have not rewritten
   it.** §4's table is superseded by §F.5 and §3's alias bullet by §F.7(a); both
   now carry a SUPERSEDED banner at the point of use, so a reader who lands on
   them is told before reading the numbers. I appended rather than editing the
   numbers themselves so the correction history stays auditable — the remaining
   risk is only that the prose around each table still reads as current. If the
   reviewer would rather have them rewritten in place, say so and I will.
2. **The README's headline is a claim about production I cannot re-verify here.**
   The inert-route finding is Task 12's, measured on 2026-09-25; I restated it and
   did not re-run those 600+ browser navigations. If the books have changed their
   routing since, the callout is stale. It names the date and the source.
3. **`rejected` vs `suggested` is invisible to this layer** (§F.5, M21). The
   e2e file cannot tell them apart because the matcher only consumes `verified`.
   Adding that would mean asserting a status the pipeline never branches on, which
   belongs in `tests/test_certainty.py` — where it already is.
4. **Still only 3 books and only the 1X2 market** in the e2e chain, unchanged
   from round 0 and not revisited here.
5. **The e2e constants remain coupled to one capture** (F.7d). Now documented in
   the file, so a future failure will at least point at the right file.

---

# Fix round 2

The three open items shared one root cause, and the controller named it: the
doc-claim script existed to catch claims that do not match the code, and three of
its own checks were written so they never opened the document. A check that only
confirms the code still says what it said is a no-op occupying a test slot. So
this round is mostly about making the checks open the document, and proving each
one can fail.

**A finding of my own, first, because it is the load-bearing one: the new test
found two real errors in the documentation `c5fe4d5` shipped.** Both are recorded
in §G.3. That is the automation earning its place on its first run.

## G.1 The doc-claim script is committed

**Path: `tests/test_readme_claims.py`** — 25 tests, in the suite, not in `%TEMP%`.
It supersedes `%TEMP%/opencode/e2e/verify_docs.py`, which is a one-off and is now
deleted. Round 1's §F.9 still pointed at that `%TEMP%` path and printed its
42/42 run as current evidence, which made this paragraph's own claim that the file
"is no longer referenced anywhere" false on two counts. Fixed in fix round 3:
§F.9 is banner-superseded and the paragraph above it now names the committed
path. See §H.1.

The file is organised as **paired tests**. For every claim, a `*_problems(text)`
predicate plus two tests:

* `test_<claim>` — runs the predicate on the real `README.md`; it must find
  nothing.
* `test_<claim>_fails_<mutation>` — breaks the document exactly the way that
  claim is supposed to catch, and asserts the predicate notices.

Then one guard over the whole file:

* `test_every_doc_predicate_is_proven_capable_of_failing` — fails if any
  `*_problems` predicate reports a problem on the real README, **or** if any
  predicate has no `test_*_fails_*` companion. A new predicate added without a
  companion is how the second failure mode returns.
* `test_the_predicate_guard_would_notice_an_empty_predicate_set` — replaces every
  predicate with `None` and asserts the guard's own `assert predicates` fires, so
  a rename cannot silently empty the guard. This one exists because the guard is
  the load-bearing test and an untested guard is the thing it is looking for.

**Counts, derived from the file rather than asserted here — 25 tests: 10
predicates, 11 companions, 2 standalone, 2 guards.** Ten predicates, because ten
`README` claims are compared to an implementation; the eleventh claim, PLAN's
Phase 4 section, has no `_problems` predicate and is checked inline by
`test_plan_declares_phase_four_done_with_the_headline`, so it has no companion
either. `test_dead_hard_reject_vocabulary_is_documented_as_dead` is the second
standalone: it pins a code fact *and* the README note about it, which is one
claim with two sides rather than a predicate over a document. The eleventh
companion arrived in fix round 3, when the headline predicate gained a second
mutation to catch (§H.3) — it previously had one. The naming is mechanical on
purpose: `test_every_doc_predicate_is_proven_capable_of_failing` requires a
companion whose name contains the predicate's stem, so a mismatch between a
predicate and its companion is a failure rather than a silent gap.

> **Corrected in fix round 3.** This paragraph said "Eleven predicates, eleven
> companions". The real counts are **10 and 10** at `59b5186`; the eleventh test
> of each was the PLAN test and the dead-vocabulary test, which I had miscounted
> as a predicate/companion pair. A count error in the section whose subject is
> counts matching reality.

## G.2 The three mislabelled checks, and how each now reads the document

| Was | Now |
|---|---|
| `'"AI_BASE_URL", "https://api.openai.com/v1"' in src` — `engine/ai.py` only | `_env_problems` parses the code's `os.getenv` default with a regex over `inspect.getsource(MatchAI.__init__)`, finds the README's table row by its exact first cell (`` `AI_BASE_URL` ``), and requires the code's default to appear **in that row**. Both sides are read; either can move. |
| `f'"{reason}"' in ce` for the five `suggested` reasons — `certainty.py` only | `_observed_reasons()` **runs** `CertaintyGate.evaluate_pair` over seven broken claims, one per reason, and collects what the gate actually emits. `_vocabulary_problems` compares that live set against the README's reason cell **bidirectionally** — a reason the gate emits but the README omits, and a reason the README claims but the gate cannot produce. |
| `HARD_REJECT_REASONS` loop — already read the document | Kept, and generalised: the same bidirectional comparison now runs for `rejected` as well, using the gate's *observed* hard reasons. |

Two changes fell out of making the vocabulary check real, and both are §G.3:
the check now distinguishes reasons the gate **produces** from reasons merely
**declared**, and it reads only the reason cell rather than every cell.

## G.3 Two real documentation errors this test found on its first run

Both were in `c5fe4d5`, and both are the exact class the file exists to catch.

**1. `orientation_unresolved` is dead vocabulary.** `c5fe4d5`'s README listed it
in the `rejected` row. It appears in the whole repository exactly once —
`engine/certainty.py:20`, inside `HARD_REJECT_REASONS` — and nothing in that
module ever appends it. The unresolvable-orientation case is reported as
`team_unresolved` (`engine/certainty.py:195, 302, 316`). So the README told a
reader the gate rejects something it does not. Fixed: the row now lists the two
reasons the gate produces, plus a paragraph saying the third entry exists, is
never emitted, and what to do about it. `test_dead_hard_reject_vocabulary_is_documented_as_dead`
pins both sides, so implementing the reason or deleting the entry both fail until
the README's note is updated to match.

**2. A probe that could not see `no_event_link` — and the README was right.**
My first `_observed_reasons` probe built its no-link case with an empty
`url`/`event_id` but left `deep_link_verified=True`, and `_link_evidence` returns
`verified_link` before it ever reaches the `no_event_link` branch. The check
correctly reported the README as claiming an unreachable reason; the probe was
wrong. Fixed by adding `deep_link_verified=False` to that case. Worth recording
because the failure pointed at the documentation and the documentation was right
— the discipline that matters is running the check, not believing which side is
suspect.

## G.4 The weakest check, and the claim it guards

**The finding was correct and the check was close to worthless.** The old
predicate was `"never" in readme and "deep_link_verified" in readme`. `never`
occurs six times in the README and is tied to `deep_link_verified` in none of
them, so deleting "never by a human approval" — the one sentence the brief
singled out — left it green.

`_approval_problems` now works on **claims**, not paragraphs and not the file. A
claim is a blank-line-separated block *or a single list item with its
continuations* (`_claims`, which starts a new claim at every `*`/`-`/`1.`). That
granularity matters: the two stage-1 rules are adjacent bullets, so a
paragraph-scoped check let the neighbouring bullet's "never" stand in for the
prohibition. The predicate requires **one claim** containing `deep_link_verified`
*and* `human approval` *and* `never`, inside the `## Match & mapping certainty`
section — plus the section naming `team alias` and
`config/team_alias_allowlist.json`, which is where an approval's grant actually
lands.

Mutation **D3** in §G.6 is the finding's own example: it removes "never by a
human approval" from the README and the check fires, naming
`test_approval_boundary_is_stated_in_one_place` and
`test_approval_check_fails_when_the_prohibition_is_removed`.

## G.5 The other cross-checks added

| Check | Reads the document against |
|---|---|
| `test_headline_names_exactly_the_declared_but_inert_books` | Scoped to the **one callout claim** that says zero surebets are produced, and within it to the **sentence** containing "inert", which must name exactly `{mdshop, admiralbet}` — cross-checked against `config/bookmaker_deeplinks.json`. The callout also holds a re-check claim listing all three declared books, and the headline itself names Mozzartbet as the exception, so claim- or file-scoping credited the inertness to mentions meant for something else. Any fourth book declaring a route fails the test until the headline says something about it. |
| `test_review_tab_really_has_no_url_path` | The "no dedicated URL" sentence against `server/app.py`'s route table (a path containing "review", or the loss of `/`, fails it) and against `frontend/js/app.js` (`location.hash`, `URLSearchParams`, `pushState`, `replaceState`), plus the tab order in `frontend/index.html`. Mutation **C6** adds `location.hash` to the frontend and it fires. |
| `test_documented_script_flags_exist_in_those_scripts` | The README's `python scripts/…` lines against each script's real `add_argument` flags, read with `ast` — no execution, so no cache-file or network dependency. |
| `test_convergence_caveat_matches_build_targets` | The "cannot converge" warning against `build_targets`' actual AST: a new `offset`/`cursor`/`start_after`/`skip_verified` parameter fails the test. Mutation **C5** adds a `cursor` parameter and it fires. |
| `test_defect_pointer_matches_the_tripwires_in_repo` | `premier`/`XPASS`/`dateFrom=now` in the section against `tests/test_market_fixtures.py`'s strict xfail and the block name it guards, and the quoted measurements (35 live events, 12 hours) against the `KNOWN DEFECT` comment in `scrapers/mdshop.py` that measured them. The two sides use different literals, so each is checked against the file that actually carries it. |
| `test_plan_declares_phase_four_done_with_the_headline` | PLAN's `### Phase 4 — Mapping certainty (Done)` section, and that it states the headline. |

## G.6 The README pointer

The callout now carries a **Re-check this claim yourself** block, stating the
split plainly: the part the repo reproduces is *which books declare a per-event
route at all* — exactly three, with a one-line command against
`config/bookmaker_deeplinks.json` — and the inertness itself is a measurement
taken on 2026-09-25 by opening each route in a browser, attributable to
`scripts/verify_deeplinks.py` and `task-12-report.md`, costing one navigation
per event and not converging today. It also names
`tests/test_readme_claims.py`, so a reader knows these claims are machine-checked.
`test_readme_points_at_how_to_recheck_the_headline` requires all five pointers
inside the callout, and **D11** removes one and fires.

## G.7 The two mislabelled mutation rows

**M16.** `:521` said "fed `all_matches`, not `groups`", which is what sent the
re-reviewer to predict 2 failures. The label now says the group is **rebuilt from
the raw, unswapped `all_matches`** — the actual mechanism, and the thing that
makes 1 correct. The same correction is applied at `:216` (round-0 table) and
`:480` (round-1 comparison row), and §F.6 now records that the label, not the
number, was the defect.

**M20.** The harness label said "renames `link_unverified`". It renames the
literal at `engine/certainty.py:233` only; the collector at `:334` compares
against the old string, so it no longer matches and the link-reason collection at
`:330-338` is **disabled**, not renamed. That is why the count is 2 and not 1,
and the row now says so. Same shape of defect as the round-0 table: a label that
under-describes the mutation.

## G.8 Covering files

| File | Change |
|---|---|
| `tests/test_readme_claims.py` | **Added** — 25 tests: 10 predicates, 11 companions, 2 standalone, 2 guards. (Round 2 said 24/11/11; corrected in round 3, §H.4.) |
| `README.md` | Modified — the "Re-check this claim yourself" callout block; the `rejected` row corrected and the `HARD_REJECT_REASONS` wrinkle paragraph added; both candidate endpoints spelled out. |
| `.superpowers/sdd/.../task-13-report.md` | This section, plus the M16/M20 label corrections. (Gitignored; the repo artefact is the two files above.) |

**No production file is changed.** `engine/`, `server/`, `scrapers/`, `config/`,
`scripts/` and `frontend/` are byte-identical to HEAD — verified after all twenty
mutations by `git diff --stat` over those paths, which prints nothing.

## G.9 Non-vacuity: 20 mutations, 14 on the document and 6 on the code

The document mutations exist because the whole point is that a check which never
opens the document is a no-op. The code mutations exist because a check which
only reads the document proves nothing about the code. Every row fails.

| # | Mutation | Failed / 24 | Fails |
|---|---|---|---|
| D1 | README headline no longer says zero surebets are produced | 3 | headline, its companion, the guard |
| D2 | README headline calls the routes **active** | 3 | headline, its companion, the guard |
| D3 | README drops "never by a human approval" | 3 | **approval boundary**, its companion, the guard |
| D4 | README claims a `rejected` reason the gate cannot produce | 2 | vocabulary, the guard |
| D5 | README drops a reason the gate emits | 3 | vocabulary, its companion, the guard |
| D6 | README's `AI_BASE_URL` default is not the code's | 3 | env defaults, its companion, the guard |
| D7 | README claims the Review tab **has** a URL | 3 | review tab, its companion, the guard |
| D8 | README documents `--sweep-all`, a flag the script lacks | 3 | script flags, its companion, the guard |
| D9 | README drops the "cannot converge" warning | 3 | convergence, its companion, the guard |
| D10 | README stops naming the XPASS tripwire | 3 | defect pointers, its companion, the guard |
| D11 | README callout loses its source pointer | 3 | headline pointers, its companion, the guard |
| D12 | README names an endpoint that is not routed | 3 | endpoints, its companion, the guard |
| D13 | PLAN loses the "Phase 4 (Done)" heading | 1 | the PLAN test |
| D14 | PLAN's Phase 4 section drops the headline | 1 | the PLAN test |
| C1 | `engine/ai.py` changes the `AI_MODEL` default | 1 | env defaults |
| C2 | `engine/certainty.py` gains a reason the README omits | 3 | vocabulary, dead-vocabulary, the guard |
| C3 | `engine/certainty.py` starts emitting `orientation_unresolved` | 3 | vocabulary, dead-vocabulary, the guard |
| C4 | a fourth book declares an event route | 2 | headline, the guard |
| C5 | `build_targets` gains a `cursor` parameter | 2 | convergence, the guard |
| C6 | `frontend/js/app.js` grows `location.hash` routing | 2 | review tab, the guard |

20 of 20. D1–D12 each fail exactly the check that owns the claim plus that
check's companion plus the guard; D13/D14 fail only the PLAN test, which is
correct — a PLAN edit cannot falsify a README claim.

> **Round 3 added D15** for the widened headline check, so the table is now 21
> rows. See §H.3.

## G.10 Commands and output

```
$ "…/python.exe" -m pytest tests/test_readme_claims.py -p no:cacheprovider -o addopts=""
======================= 24 passed, 2 warnings in 1.36s ========================
                                       # 25 after round 3; see §H.6
```

```
$ "…/python.exe" -m pytest
527 passed, 1 xfailed, 3 warnings in 15.74s        # 503 before this round
```

```
$ "…/ruff.exe" check .
All checks passed!

$ "…/mypy.exe" .
Success: no issues found in 59 source files         # 58 before this round
```

## G.11 Concerns after this round

1. **I clobbered the round-2 README and PLAN edits the same way as round 1.**
   The doc-mutation harness used `git checkout -- README.md` to restore, which
   discards uncommitted work on a tracked file — the identical mistake, on the
   identical mechanism, three weeks of review apart. It cost the three README
   edits and the edits were redone and re-verified. The harness now backs the
   files up byte-wise and restores from the copy, and says so in a comment at the
   top so the next person does not reintroduce it. The lesson is not "be careful";
   it is that a mutation harness must never use a VCS operation as its undo.
2. **The self-guard is a naming convention, not a type.** It matches a predicate's
   stem against a companion's *name*. A companion that exists but exercises a
   different mutation would satisfy it. I mitigated that by making every companion
   assert the specific problem string it expects, and by the 20 rows of §G.9
   showing the companions do fire — but a wrong companion name would slip past.
   A registry mapping predicate → mutation string, checked for coverage, would be
   tighter; I did not build it because the 20-row table already demonstrates each
   one works.
3. **`orientation_unresolved` is a live defect I did not fix**, per the
   no-production-changes rule for this round. It has **two surfaces**, not one,
   and both were verified in round 3 rather than assumed:
   * **The gate.** `engine/certainty.py:20` declares it in `HARD_REJECT_REASONS`;
     nothing in the module appends it. The unresolvable-orientation case is
     reported as `team_unresolved` (`certainty.py:195, 302, 316`).
   * **The frontend.** `tests/test_frontend_review.py:56-57` folds
     `HARD_REJECT_REASONS` into its source-derived reason set, so the dead entry
     makes `orientation_unresolved` look producible there too — and
     `frontend/js/app.js:43` duly ships a user-facing label for it,
     `orientation_unresolved: 'Home/away order unclear'`, in `REASON_LABELS`.
     `tests/test_frontend_review.py:16` pins that label set, so the dead entry is
     currently load-bearing for a passing test.

   Nothing is broken by it today — a label for a reason that cannot appear is
   dead UI, not wrong UI — and the README says so. But it is not one dead string:
   a follow-up has to either implement the reason, or delete the entry from
   `HARD_REJECT_REASONS` **and** the label from `REASON_LABELS` **and** the entry
   from `KNOWN_REASON_CODES` in `tests/test_frontend_review.py`. Note that
   `test_readme_claims.py::test_dead_hard_reject_vocabulary_is_documented_as_dead`
   fails either way until the README's note is updated to match, so the dead entry
   cannot be removed silently.
4. **The doc-claim test is coupled to prose.** It checks meaning by matching
   strings, so rewording the README — legitimately — can fail it. Every failure
   message names the claim and the file, and the check reads claims and table
   cells rather than raw lines so rewrapping is safe, but a substantial rewrite of
   the section will need the predicates updated alongside. That is the intended
   coupling: the claims are pinned, not the prose.
5. **The headline remains a dated measurement.** The README now says so, points
   at the script, names the date, and distinguishes it from the repo-reproducible
   part. I did not re-run 600+ browser navigations; if the books have changed
   their routing, that is what would find out.

---

# Fix round 3

Four items, all the same class this plan has been about: an artifact describing
something the artifact does not support. Three were in the report, one was in the
test file's own docstring — which is the part I would rather not have shipped,
because that file exists to catch exactly that.

## H.1 §F.9 was stale, and its "fixed" claim was itself false

The finding was right on all three counts, and I verified each before editing.

* `§F.9` still said the script "lives outside the repo at
  `%TEMP%/opencode/e2e/verify_docs.py` — a one-off check, not a committed test,
  and the reviewer may want it as `tests/test_readme_claims.py`". The file does
  not exist; the committed path is `tests/test_readme_claims.py`.
* `§F.9` still printed the 42/42 run of that deleted file as current evidence,
  including the rows round 2 exists to eliminate.
* `§G.1` claimed the file "is no longer referenced anywhere" (it was referenced
  at two places) and that "the round-1 report's §F.9 block that printed its 42/42
  output now points here instead" (it was byte-identical to `c5fe4d5`).

Fixed three ways, following the banner convention round 1 established for §4 and
§3:

1. **A SUPERSEDED banner immediately above the paragraph**, naming the
   replacement path and saying the run is not evidence of anything the current
   file does. The paragraph itself is left verbatim, so the audit trail survives.
2. **The 42/42 block** is marked `# DELETED FILE` on both its command line and its
   result line, and a second banner calls out the one row that was *true and
   misleading* — `README's rejected reason 'orientation_unresolved' is in
   HARD_REJECT_REASONS` confirmed the string was in a set, not that the gate emits
   it. That row is the proximate cause of the README error in §G.3, so leaving it
   unannotated would have left the trap in place.
3. **§G.1's two false claims are now stated as the errors they were**, in the
   correction note rather than quietly deleted.

## H.2 The test file's docstring named a test that does not exist

`tests/test_readme_claims.py:26` cited
`test_this_file_checks_every_checkable_claim_it_claims_to_check` as the guard.
The guard is `test_every_doc_predicate_is_proven_capable_of_failing`; no function
by the cited name has ever existed. Fixed.

The sting is the file: its entire purpose is catching artifacts that describe
things they do not support, and its own docstring named a function it does not
contain — while its introspection over `*_problems` globals **structurally
cannot see it**, because a docstring is not a global the guard walks. So this one
was undetectable by the mechanism the file is built on, which is worth recording
as a limit: the file polices predicates, not prose about the file.

## H.3 The headline check could not see a route-less book named as inert

Confirmed before changing anything. `_headline_problems` computed

```python
named = {book for book in declaring if book.lower() in " ".join(inert).lower()}
```

over `declaring` — the books with `supports_event_id: true`. A book **outside**
that set can never enter `named`, so rewriting the sentence as "MDShop's,
Admiralbet's and **Betole's** `?event=<id>` routes are inert" produced `named ==
{"mdshop", "admiralbet"}` and passed. Betole declares
`supports_event_id: false` (`config/bookmaker_deeplinks.json`), so it has no
per-event route and there is nothing about it to be inert.

Widened, without weakening what round 2 established:

* `named` is now computed over **every book in the deep-link config**, via a new
  `_deeplink_config()` helper, with `_declaring_books()` derived from it. The
  existing equality check (`named == {"mdshop", "admiralbet"}`) is unchanged, so
  D2 — the round-2 requirement that the check cannot pass on a README calling the
  routes *active* — still holds, and the `unaccounted` check still uses
  `declaring`.
* A new companion, `test_headline_check_fails_when_a_route_less_book_is_called_inert`,
  drives exactly the mutation the finding describes, and first asserts that
  `betole` is in the config and **not** in `declaring` — so if Betole ever
  declares a route, the companion says it no longer tests what it claims instead
  of passing for the wrong reason.

The predicate is unchanged in what it accepts: the real README still yields
`named == {"mdshop", "admiralbet"}`, because the inertness sentence names neither
Mozzartbet nor any of the six route-less books.

## H.4 The predicate count was wrong

`§G.1` and `§G.8` said "Eleven predicates, eleven companions". The real counts at
`59b5186` are **10 and 10**. The 24 tests are 10 positive + 10 companion + 2
standalone + 2 guards, and I had counted the two standalone tests
(`test_dead_hard_reject_vocabulary_is_documented_as_dead` and
`test_plan_declares_phase_four_done_with_the_headline`) as a predicate/companion
pair.

Both places now state the breakdown **and why it is 10 rather than 11** — ten
README claims have a predicate; PLAN's Phase 4 section is checked inline and the
dead-vocabulary test pins a code fact together with the README note about it.
After §H.3 the totals are **25 tests: 10 predicates, 11 companions, 2
standalone, 2 guards**, with the eleventh companion being the new headline one.
Both corrected numbers are recorded in place with a note, not silently replaced.

## H.5 The follow-up note gained its second surface

`orientation_unresolved` is not one dead string, and the note said it was. Verified
rather than assumed:

* **The gate.** `engine/certainty.py:20` declares it in `HARD_REJECT_REASONS`;
  nothing in the module appends it. The unresolvable-orientation case is reported
  as `team_unresolved` (`certainty.py:195, 302, 316`).
* **The frontend.** `tests/test_frontend_review.py:56-57` folds
  `HARD_REJECT_REASONS` into its source-derived reason set, so the dead entry
  makes the reason look producible there too. `frontend/js/app.js:43` duly ships
  `orientation_unresolved: 'Home/away order unclear'` in `REASON_LABELS`, and
  `tests/test_frontend_review.py:16` pins that set — so the dead entry is
  currently load-bearing for a passing test.

The note now says a follow-up must either implement the reason, or delete all
**three** of `HARD_REJECT_REASONS`' entry, the `REASON_LABELS` entry, and the
`KNOWN_REASON_CODES` entry, and notes that
`test_dead_hard_reject_vocabulary_is_documented_as_dead` fails either way until the
README's note is updated, so it cannot be removed silently.

## H.6 Covering files

| File | Change |
|---|---|
| `tests/test_readme_claims.py` | Modified — docstring guard name corrected; `_deeplink_config()` added; `_headline_problems` widened to every book in the config; one companion added. 24 → 25 tests. |
| `.superpowers/sdd/.../task-13-report.md` | This section, plus the §F.9 banner, the `# DELETED FILE` markers, and the corrected counts in §G.1/§G.8/§G.9/§G.10. (Gitignored; the repo artefact is the one file above.) |

`README.md` and `PLAN.md` are **unchanged in this round** — every finding was about
the report or the test file. **No production file is changed**;
`engine/`, `server/`, `scrapers/`, `config/`, `scripts/` and `frontend/` are
byte-identical to `59b5186`, verified by `git status --porcelain` after all fifteen
document mutations and six code mutations.

## H.7 Non-vacuity: 21 mutations, 15 on the document and 6 on the code

Every row from §G.9 still fires unchanged, and one row is added.

| # | Mutation | Failed / 25 | Fails |
|---|---|---|---|
| D15 | README names Betole — which declares **no** per-event route — as having an inert one | 4 | headline, both companions, the guard |
| D1–D14 | unchanged from §G.9 | 1–3 | unchanged |

**21 of 21.** D15 fails both headline companions, which is the point of §H.3: the
new gap and the original gap are now caught by the same predicate from two
directions. The counts in §G.9's table are unchanged by this round except the
denominator (24 → 25).

## H.8 Commands and output

```
$ "…/python.exe" -m pytest tests/test_readme_claims.py -p no:cacheprovider -o addopts=""
======================= 25 passed, 2 warnings in 1.26s ========================
```

```
$ "…/python.exe" -m pytest
528 passed, 1 xfailed, 3 warnings in 14.68s     # 527 before this round
```

```
$ "…/ruff.exe" check .
All checks passed!

$ "…/mypy.exe" .
Success: no issues found in 59 source files
```

## H.9 Concerns after this round

1. **The report is the artefact that has now needed the most correction.** Round 1
   fixed two sections of it, round 2 introduced a new one, and round 3 found four
   more. The failures are always the same shape — a superseded section reading as
   current, or a count that drifted — and they are invisible to the suite because
   the file is gitignored. If this report is going to be read as an audit record,
   a check that banners superseded sections and re-derives its own counts would be
   worth more than another paragraph of prose. I did not build one, and that is the
   largest thing I would do differently.
2. **The doc-claim file cannot police its own docstring** (§H.2). Its guard walks
   `*_problems` globals and runs each against a broken document; nothing checks
   that the prose describing the file is true of the file. A test that asserted
   every `` ``test_*`` `` in the docstring resolves to a real function would close
   that specific hole, and would have caught this round's item 2. I did not add it
   because it is a new check rather than a correction, and the reviewer's remaining
   budget is better spent elsewhere.
3. **`orientation_unresolved` is now recorded on two surfaces** (§H.5), with the
   frontend one load-bearing for a passing test. That makes the follow-up slightly
   larger than §G.11 implied and slightly more interesting: deleting the dead entry
   is a three-site change, and `tests/test_frontend_review.py`'s
   `HARD_REJECT_REASONS` special case at line 56 is the reason it is three sites
   rather than one.
4. **The widened headline check is keyed on book names appearing in a sentence.**
   That is still prose coupling, of the kind §G.11 item 4 records and the review
   accepted. The widening made it stricter, not looser: a book outside the config
   entirely would still be invisible, though the README has no such book and the
   config lists all nine the scrapers declare.
5. **The headline remains a dated measurement** (§G.11 item 5, unchanged). Nothing
   in this round touches it, and nothing here can: it needs a browser.

