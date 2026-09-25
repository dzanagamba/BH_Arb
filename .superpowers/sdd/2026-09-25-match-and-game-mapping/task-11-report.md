# Task 11 report — captured-payload fixture tests for every bookmaker registry entry

**Status:** DONE_WITH_CONCERNS
**Date of capture:** 2026-09-25 (all fixtures), between roughly 16:45 and 19:20 UTC
**Branch:** `master`, in place. No worktree, no branch.

---

## 1. What was added

| Path | What it is |
|---|---|
| `tests/fixtures/markets/*.json` | 14 hand-trimmed payloads read out of live bookmaker HTTP responses |
| `tests/test_market_fixtures.py` | 58 tests that drive each book's real market-parsing entry point with those payloads |
| `scripts/capture_market_fixtures.py` | The capture script that produced (and can regenerate) every fixture, recording the endpoint and date in each file |

No scraper was modified. `config/bookmaker_markets.json` is byte-identical to `HEAD`
(verified with `git status` after the mutation experiment in §6).

---

## 2. Coverage: what was captured, and what was not

| Bookmaker | prematch | live | Note |
|---|---|---|---|
| MDShop | ✅ | ✅ | NSoft `getwebevents` |
| Admiralbet | ✅ | ✅ | NSoft `getwebevents` (own office id) |
| WWIN | ✅ | ✅ | `PrematchEvents/events` + `LiveEvents/headerBets` via Playwright |
| Premier Kladionica | ✅ | ✅ | PrSync full sync + delta sync, `dogTipK` rows |
| MBet | ✅ | ✅ | `events_cached` |
| SportPlus | ✅ | ✅ | `/api/v1/prematch/offer`, `/api/v1/live/offer` |
| Mozzartbet | ✅ | ✅ | `POST /betting/matches` via Playwright |
| **EVLBet** | ❌ **absent** | n/a | see below |
| betole | ❌ not attempted | — | disabled book, out of scope; see below |

### EVLBet — no fixture, and the reason changed during the session

Early in the session `sportapis.evlbet.com` refused every TLS connection
(`httpx` `ConnectError`, `curl`/schannel `failed to receive handshake`,
headless Chromium `net::ERR_CONNECTION_CLOSED`, and a remote browser
`ERR_CONNECTION_CLOSED`). I recorded it as unreachable.

**Later in the session the host started answering: HTTP 200.** But every variant of the
flat offer endpoint returns an empty list —

```
/matches/flat?SportIds=388&Limit=100&Offset=0          -> 200  []
/matches/flat?SportIds=388&Limit=100&Offset=0&Filter=all -> 200 []
/matches/flat?SportIds=1,388&Limit=100&Offset=0        -> 200  []
/matches/flat?Limit=20&Offset=0                        -> 200  []
/matches?SportIds=388&Limit=20&Offset=0                -> 200  []
/matches/live?SportIds=388&Limit=20&Offset=0           -> 200  []
/matches/flat                                          -> 200  []
```

`https://evlbet.com/` itself serves a normal Angular shell (HTTP 200), so the site is up;
the **offer API serves no data at all**. There is therefore nothing to capture, and
**no EVLBet fixture exists**. I did not fabricate one. This is recorded in three places:
`UNCOVERED_ROWS` in the test, `BOOKS_WITHOUT_FIXTURES` in the test, and the captor's
`SKIPPED` message.

Note that EVLBet's live registry section is `{}` (no markets), which matches
`scrapers/evlbet.py`'s documented "the live feed exposes no odds".

### betole — deliberately not in scope

`betole` is `enabled: False` in `config/settings.py` and is not in the brief's required
list. Its desk feed **is** reachable (I captured 1500 `esMatches` while investigating),
but no trim of a real payload can satisfy this layer's central invariant: in prematch
mode `_parse_betole_markets` emits the experimental `first_half_1x2` market
*unconditionally*, and that market has no registry row — so "emitted == declared registry
markets" can never hold for betole. Declared in `UNCOVERED_ROWS` /
`BOOKS_WITHOUT_FIXTURES` with that reason rather than papered over.

---

## 3. Registry rows the live feed could not supply

The captures cover **every declared core-market row except the following**, each of which
is declared in `UNCOVERED_ROWS` in the test with its reason. A new gap fails
`test_coverage_gaps_are_declared_rather_than_ignored`; a gap that becomes covered also
fails, so the list cannot rot.

| Row | Why it is not exercised |
|---|---|
| `evlbet/prematch/1x2` | The flat offer endpoint returns an empty list. |
| `mozzartbet/{prematch,live}/over_under_1_5` | Game 3 serves subgames `2+`, `3+`, `0-2` and no `0-1`. A totals market needs both legs (`min_legs: 2`), so 1.5 has one leg and cannot be emitted. |
| `mozzartbet/{prematch,live}/over_under_3_5` | Same: no `4+`/`0-3` pair anywhere on the feed. |
| `premier_kladionica/live/btts` | **Real registry/parser defect — see §5.** |
| `betole/prematch/*` (6 rows) | Disabled book; parser emits an unregistered market. |

Everything else is exercised: mdshop, admiralbet, wwin, premier_kladionica, mbet,
sportplus and mozzartbet all have captures covering all six core market rows
(mozzartbet and admiralbet-live excepted as above).

---

## 4. Fixture provenance

Every fixture records `bookmaker`, `mode`, `captured_at`, `endpoint`, `source`
(always `"live_api_response"`), `payload_kind`, `provenance` (a prose note),
`dropped_*_fields`, `excluded_ids_present`, `bets`, `expected_markets` and
`uncovered_registry_rows`. `test_fixture_records_its_provenance` enforces the presence
of all of these, so a future fixture that forgets where it came from fails the suite.

Payloads are **raw feed data, not parser output**. Per book:

| Book | What `bets` holds | Trim |
|---|---|---|
| mdshop, admiralbet | one event's `bets[]` from NSoft `getwebevents` | bet → `{betTypeId, sBV, betTypeName, betOutcomes[{name, odd, orderNo}]}` |
| wwin | one event's `bets[]` from `PrematchEvents/events` / `LiveEvents/headerBets` | bet → `{idBt, spec, odds[{t, va, isv}]}` |
| premier_kladionica | `dogTipK` rows for one event, **verbatim**, plus the `setTip`/`setTipVar`/`setTipTip` definition rows for exactly those setTip ids | none — PrSync is positional, so trimming a column would move the indices the parser reads |
| mbet | the event's `odds{}` dict | oddtype entry → `{value, market_key, oddtype_key, market_status, oddtype_status}` |
| sportplus | one match's `markets[]` | market → `{id, name, odds[{alias, value}]}` |
| mozzartbet | one item's `odds[]` | odd → `{game{id, shortName, name}, subgame{name}, value}` |
| evlbet | (absent) | — |

Two structural shells are filled in by the test, and only these: the two competitor
names MBet's `_parse_event` requires before it looks at any odd, and the
`{"odds": [...]}` wrapper Mozzartbet's `_parse_markets` takes. No market data is
synthesised.

**Each payload also deliberately retains one real excluded block** as a negative
control, and `test_ids_the_capture_excludes_are_excluded_on_purpose` asserts the
control really is in the payload *and* really is on the registry's `_excluded` list:

| Fixture | Excluded control kept in the payload |
|---|---|
| mdshop/admiralbet prematch | `betTypeId 148` "1.pol - 1X2" |
| mdshop/admiralbet live | `betTypeId 24` "Tačan rezultat" |
| wwin prematch/live | `idBt 7` (handicap) |
| premier prematch / live | setTip `1440` "HENDIKEP" / setTip `58` "LIVE - HENDIKEP (0:?)" |
| mbet prematch / live | `ofb:sh:1` (second-half result) / `lfb:tg1sth:over|0.5` |
| sportplus prematch / live | market `178` "POLUVRIJEME ILI KRAJ" / market `5` "Azijski hendikep" |
| mozzartbet prematch/live | game `141` "Mozzart kombinazzije" |

`admiralbet/live` additionally retains the `22`/`28` live totals, which admiralbet's
registry does **not** declare. `test_a_captured_unregistered_id_is_counted_not_dropped`
asserts that parsing the capture increments `engine.market_registry.unmapped_markets`
for them — the "counted, never silently dropped" global constraint, proven on real data.

### What the captures actually confirmed about the registry

The live payloads corroborate the IDs the registry declares:

* MDShop prematch 1X2 really is `135`, Admiralbet's really is `1639` — the two books
  share a feed shape but not the 1X2 id, and each book's payload contains only its own.
* NSoft O/U is id `137` with the line in **`sBV`** (capital `BV`); the feed serves
  `0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5`, of which only 1.5/2.5/3.5 are declared. `138`
  never appeared on the feed at all, so the registry's `ids: [137, 138]` is a superset.
* WWIN spells the totals line `total=2,5` (comma) prematch and `total=2.5` (dot) live.
* SportPlus splits the goal-range market across blocks `800` and `802`: `01/02/3+/4+`
  live in one and `2+/03` in the other, so O/U 1.5 and 3.5 only resolve when **both**
  blocks are present. Both are in the capture.
* MBet uses `ofb:` prematch and `lfb:` live, and suspends by `market_status`/`oddtype_status`.

---

## 5. Concern: premier_kladionica live BTTS is a wrong-but-consistent registry row

This is the defect the task was built to find, and it is real:

* The live feed names the market **`LIVE - OBA TIMA DAJU GOL`**.
* `scrapers/premier_kladionica.py` sets `NAME_BTTS = "OBA DAJU GOL"` and, after
  stripping the `LIVE - ` prefix, compares against that constant.
* `config/bookmaker_markets.json` declares `premier_kladionica/live/btts` with id
  `LIVE_OBA_DAJU_GOL`.

So the registry and the parser agree perfectly with each other and both disagree with
the feed. Premier's live BTTS market can never be emitted; the block falls through to
`record_unmapped(..., context="OBA TIMA DAJU GOL")` instead. The premise BTTS and the
first-half BTTS are distinct market names on the same book.

The prematch row is fine (`OBA DAJU GOL` exists verbatim for prematch), and the capture
covers it. I did **not** fix this: it is a registry/parser change belonging to the
tasks that own those files, and Task 11's contract is to surface it. It is recorded in
`UNCOVERED_ROWS` with the reason, and the fixture's own `provenance` string repeats it.

---

## 6. Scope decision on the brief's Step 4 — no scraper refactor

The brief proposed adding `parse_markets(bookmaker, mode, payload)` to every non-NSoft
scraper. **I did not do that**, and no scraper was touched.

Reason: the parsers already consult `engine.market_registry` through their private
`_`-prefixed resolvers (`_wwin_registered_spec`, `_nsoft_registered_spec`,
`mbet._registered_spec`, `sportplus._registered_spec`, `_evlbet_registered_spec`,
`_betole_registered_spec`, `premier_kladionica._registered_spec`). What the fixtures
need is *a way to call the existing entry point with a payload*, and every one of those
entry points already exists and is reachable:

| Book | Entry point used | Payload key |
|---|---|---|
| mdshop, admiralbet | `parse_nsoft_bets` / `parse_nsoft_live_bets` | `bets` |
| wwin | `_build_markets_from_bets(bets, mode=...)` | `bets` |
| premier | `PremierKladionicaScraper._build_markets(rows, set_tip, set_tip_var, set_tip_tip, live=...)` | `bets` + `lookup` |
| mbet | `MBetScraper._parse_event(event, ...)` | `context.id_sport` + `bets` |
| sportplus | `SportPlusScraper._parse_markets` / `._parse_live_markets` | `bets` |
| mozzartbet | `mozzartbet._parse_markets(event, mode, bookmaker)` | `bets` |
| evlbet | `EvlbetScraper._parse_event(event)` | `bets` |

Seven near-identical wrappers would add a second name for each of these, a second
signature to keep in step, and seven more places for the registry to be bypassed —
without adding a single assertion the fixtures do not already make. Worse, the brief's
sample adapter contains a `pytest.skip(f"no fixture parser adapter for {book} yet")`
fallback: a book whose wrapper is forgotten would *silently skip*, which is the exact
failure mode this task exists to prevent. Here the adapter raises
`AssertionError(f"no parser adapter for bookmaker {book!r}")` instead, and
`test_coverage_gaps_are_declared_rather_than_ignored` fails if a registry book has no
capture at all.

The one helper I did add is `tests/test_market_fixtures.py::_premier_lookups`, because
Premier is the only book whose payload needs a lookup table built from stored
definition rows. It lives in the test rather than in the scraper because it is
test-only plumbing, and if its column indices ever drift from the scraper's the test
fails loudly rather than passing quietly.

---

## 7. Commands and output

### The fixture suite

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_fixtures.py -p no:cacheprovider --no-header -W ignore -v
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 58 items

tests\test_market_fixtures.py .......................................... [ 72%]
................                                                         [100%]

============================= 58 passed in 0.94s =============================
```

**58 passed, 0 failed.** Breakdown: 14 fixtures × 4 parametrized assertions
(exact market set, registry label rule, provenance, excluded controls) = 56, plus
`test_coverage_gaps_are_declared_rather_than_ignored` and
`test_a_captured_unregistered_id_is_counted_not_dropped` = 58.

### The full suite (no regressions)

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/ -p no:cacheprovider --no-header -W ignore
401 passed in 14.28s
```

**401 passed, 0 failed** (343 pre-existing + 58 new).

### Lint and types

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check tests/ scripts/
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" tests/test_market_fixtures.py scripts/capture_market_fixtures.py
Success: no issues found in 2 source files
```

### Recreating the fixtures

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" scripts/capture_market_fixtures.py
== mdshop
  wrote tests\fixtures\markets\mdshop_prematch.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
  wrote tests\fixtures\markets\mdshop_live.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
== admiralbet
  wrote tests\fixtures\markets\admiralbet_prematch.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
  wrote tests\fixtures\markets\admiralbet_live.json -> ['1x2', 'btts', 'double_chance']
== wwin
  wrote tests\fixtures\markets\wwin_prematch.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
  wrote tests\fixtures\markets\wwin_live.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
== premier_kladionica
  wrote tests\fixtures\markets\premier_kladionica_prematch.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
  wrote tests\fixtures\markets\premier_kladionica_live.json -> ['1x2', 'double_chance']
  NOTE declared rows the feed could not supply: ['btts']
== mbet
  wrote tests\fixtures\markets\mbet_prematch.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
  wrote tests\fixtures\markets\mbet_live.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
== sportplus
  wrote tests\fixtures\markets\sportplus_prematch.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
  wrote tests\fixtures\markets\sportplus_live.json -> ['1x2', 'btts', 'double_chance', 'over_under_1_5', 'over_under_2_5', 'over_under_3_5']
== mozzartbet
  wrote tests\fixtures\markets\mozzartbet_prematch.json -> ['1x2', 'btts', 'double_chance', 'over_under_2_5']
  NOTE declared rows the feed could not supply: ['over_under_1_5', 'over_under_3_5']
  wrote tests\fixtures\markets\mozzartbet_live.json -> ['1x2', 'btts', 'double_chance', 'over_under_2_5']
  NOTE declared rows the feed could not supply: ['over_under_1_5', 'over_under_3_5']
== evlbet
  SKIPPED evlbet/prematch: the flat offer feed answered 200 with an empty list (no
  matches for any SportIds/Limit/Offset) — the API is up but serves no offer right now,
  so there is nothing to capture
```

(Note: a `--books` subset was used for individual re-captures during development; the
block above is the full-book run as it stands, with the wwin/premier entries
re-captured in a later pass after two captor fixes.)

---

## 8. Does this layer actually catch a wrong ID?

The task's premise is that the two lower layers cannot catch a wrong-but-consistent ID.
I verified that rather than asserting it: I mutated `config/bookmaker_markets.json` one
row at a time, ran each layer, and restored the file. `git status` confirms the registry
is unmodified. `exit 0` = whole layer green.

| Mutation | `test_market_registry.py` | `test_market_registry_wiring.py` | `test_market_fixtures.py` (new) |
|---|---|---|---|
| mdshop prematch 1x2 `135 → 999` | exit 1 | exit 1 | exit 1 |
| mdshop prematch 1x2 `135 → 136` (Ide dalje) | exit 1 | exit 1 | exit 1 |
| mdshop prematch 1x2 `135 → 137` (totals) | exit 1 | exit 1 | exit 1 |
| admiralbet prematch 1x2 `1639 → 135` | exit 1 | exit 1 | exit 1 |
| wwin prematch 1x2 `95 → 96` | exit 0 | exit 1 | exit 1 |
| sportplus prematch 1x2 `1 → 2` | exit 0 | exit 1 | exit 1 |
| mbet prematch 1x2 `ofb:fs → ofb:fts` (excluded family) | exit 0 | exit 1 | exit 1 |
| **sportplus prematch btts `6 → 5`** | **exit 0** | **exit 0** | **exit 1** |
| **mozzartbet prematch btts `130 → 131`** | **exit 0** | **exit 0** | **exit 1** |
| **mbet prematch ou_2_5 `ofb:tg → ofb:ht`** | **exit 0** | **exit 0** | **exit 1** |

The fixture layer catches 10/10. The three bold rows are caught by **nothing else** —
they are the wrong-but-consistent IDs this task exists for, and the docstring of
`tests/test_market_fixtures.py` cites them by name.

(One correction to the brief's own example, which I found this way and fixed in my
docstring: the brief says mdshop's `135 → 999` "leaves every test green". It does not —
Task 9's wiring test hardcodes 135 as mdshop's dispatch code. The uncaught cases are the
ones above.)

---

## 9. Concerns

1. **EVLBet has no fixture at all.** Its offer API returns an empty list for every
   request I could construct, so its single registry row (`prematch/1x2` = `12005`) has
   **no live-payload coverage whatsoever**. EVLBet's ID is the least-verified entry in
   the registry. If the API resumes serving, re-run
   `python scripts/capture_market_fixtures.py --books evlbet` and the coverage test will
   tell you the row is now exercised (and will fail until `UNCOVERED_ROWS` is updated).

2. **`premier_kladionica/live/btts` is broken in the registry** (§5). Live BTTS is
   unreachable for that book today. This needs a registry/parser fix in the tasks that
   own those files.

3. **Two NSoft live feeds appear broken in production, not just in capture.** Both
   `MDShopScraper.fetch_and_parse` and `AdmiralbetScraper.fetch_and_parse` request the
   live feed with `dateFrom=now`. NSoft filters on kickoff, so **already-started in-play
   games fall outside the window**: with `dateFrom=now` the endpoint returned
   `{"events": []}` at 17:00 UTC on a Friday with 35 live football events available, and
   35 events the moment `dateFrom` was moved to `now - 12h`. Both books' live scraping
   is therefore very likely returning nothing in production. **I did not fix this** — it
   is outside Task 11's scope and would change scraper behaviour — but it is a
   significant find and the capture script documents the working window. Note this also
   means my mdshop/admiralbet live fixtures exist *only* because the capture script
   uses the correct window.

4. **Live coverage is inherently time-of-day dependent.** `mdshop/live`, `admiralbet/live`,
   `wwin/live`, `mbet/live`, `sportplus/live`, `mozzartbet/live` and
   `premier_kladionica/live` all need football actually in play. Re-capturing at 04:00
   UTC would legitimately produce fewer live fixtures. The committed fixtures are
   snapshots, so the suite stays deterministic — but a future refresh may need a retry
   loop, and `premier_kladionica/live` in particular took several attempts before an
   in-play event with `LIVE - ` setTips appeared.

5. **The `unmapped_markets` counter is process-global and not reset between tests.**
   `test_a_captured_unregistered_id_is_counted_not_dropped` snapshots before/after rather
   than asserting an absolute value, so it is order-independent. Other tests in the suite
   that assert on the counter could still be affected by this file's side effect.

6. **`premier_kladionica` is the only book whose fixture needs a lookup table**
   (`lookup.set_tip` / `set_tip_var` / `set_tip_tip`). The test rebuilds the three
   dicts with the scraper's own column indices. If those indices ever change in the
   scraper, this test fails rather than silently passing — the safe direction — but it
   will need updating in lockstep.

7. **betole's 6 registry rows have no capture**, for the reason in §2. Its desk feed is
   reachable, so this is a scope decision, not a technical blocker.

---

# Fix round 1

Both Important findings shared one root cause: a confirmed production defect that existed
only as prose in this (gitignored) report. Both are now recorded in the repo, where they
cannot rot. Nothing from round 0 was undone — the fixtures are still real feed data, the
Step 4 decision still stands, and `config/bookmaker_markets.json` is still untouched.

## 1. The premier live BTTS defect: a strict xfail, not a red build

As instructed, I did **not** leave a failing assertion. The mechanism:

**The evidence is now in the fixture.** `scripts/capture_market_fixtures.py` was changed
so the Premier captor keeps the plain both-teams-to-score block in **live** mode, where
the feed spells it `LIVE - OBA TIMA DAJU GOL` rather than the parser's `NAME_BTTS` of
`OBA DAJU GOL`. `premier_kladionica_live.json` now carries that block's real `setTip`,
`setTipVar`, `setTipTip` and `dogTipK` rows. Before this round the string existed only in
prose; now a parser fix has something to turn green.

The captor matches the block by **exact name** (`PREMIER_BTTS_NAMES = {"prematch":
"OBA DAJU GOL", "live": "OBA TIMA DAJU GOL"}`), not by substring. A substring match pulled
in a dozen half-time and combined variants that also contain `"DAJU GOL"` —
`1. POLUVRIJEME - OBA DAJU GOL`, `UTAKMICA I OBA DAJU GOL`, `DVOZNAK I OBA DAJU GOL` and
more — none of which is a registered market. The live fixture is 22 rows and four setTip
names instead of 42 rows and seven names.

**The defect is recorded in code as a strict xfail:**

```python
@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN DEFECT: the live feed's both-teams-to-score block is named "
        "'LIVE - OBA TIMA DAJU GOL' while the parser's NAME_BTTS is 'OBA DAJU GOL', "
        "so the registry's live LIVE_OBA_DAJU_GOL row is unreachable. The fix is to "
        "make NAME_BTTS mode-aware (prematch and live really do spell it "
        "differently), NOT to rename the registry row, which would break prematch. "
        "strict=True so that fixing the parser fails this test until the marker and "
        "the UNCOVERED_ROWS entry are removed together."
    ),
)
def test_premier_live_btts_is_emitted_once_name_btts_is_mode_aware():
    data = _load(_fixture_for("premier_kladionica", "live"))
    assert "btts" in _emitted(data)
```

The suite is GREEN with the marker in place. `strict=True` is the tripwire: the moment
`NAME_BTTS` is made mode-aware the test XPASSes, and pytest reports a strict XPASS as a
FAILURE. Nobody can fix the parser and leave the marker behind, and nobody can delete the
marker without fixing the parser.

**Verified, not assumed.** I temporarily patched `scrapers/premier_kladionica.py` to map
`OBA TIMA DAJU GOL` → `NAME_BTTS` in live mode (standing in for the real fix), ran the
suite, and got:

```
FAILED tests/test_market_fixtures.py::test_captured_payload_emits_exactly_the_declared_markets[premier_kladionica_live]
FAILED tests/test_market_fixtures.py::test_ids_the_capture_excludes_are_excluded_on_purpose[premier_kladionica_live]
FAILED tests/test_market_fixtures.py::test_premier_live_btts_is_emitted_once_name_btts_is_mode_aware
3 failed, 58 passed in 1.01s
```

The third failure is the strict XPASS. The first two are the exact-set assertions
correctly noticing that the fixture now under-declares: after the fix the fixture's
`expected_markets` must gain `btts`. So a real fix is forced to update the fixture and
the gap lists in the same change. The parser was restored afterwards
(`git diff` on it is empty).

The comment above the marker states the fix is a mode-aware `NAME_BTTS`, not a registry
rename, because that is the wrong-but-plausible fix and prematch really is `OBA DAJU GOL`.

Two supporting tests keep the evidence honest:

- `test_premier_live_fixture_carries_the_btts_block_the_defect_is_about` asserts the
  `LIVE - OBA TIMA DAJU GOL` block is still in the fixture and that `btts` is still
  *absent* from `expected_markets`. Without it the xfail could pass for the wrong reason.
- `test_a_declared_gap_is_not_just_listed_but_forgotten` closes the "listed and
  forgotten" hole (see below).

## 2. The "listed and forgotten" hole

`UNCOVERED_ROWS` used to be only checked for *presence*. A row could be declared a gap
and then left there forever while the fixture quietly proved otherwise. Two changes:

**The gap lists are split by kind.** `KNOWN_DEFECT_ROWS` now holds rows the feed *does*
serve but the code cannot reach, and each entry names the strict xfail guarding it. The
difference decides what the test asserts: a genuine feed gap carries no evidence in the
fixture, a code defect does.

**Every declared gap is re-proved against its payload.**
`test_a_declared_gap_is_not_just_listed_but_forgotten` loads the corresponding fixture and
asserts that a row declared as a feed gap does **not** carry the data it needs, and that
a row declared as a code defect **does**. So a gap cannot be declared and forgotten: if
the feed later serves the block, or a future capture includes it, the declaration is
stale and the test says so with the evidence in the message.

I verified this fails when it should. Injecting a real `0-1` subgame into
`mozzartbet_prematch.json` alongside the existing `2+`:

```
E  AssertionError: mozzartbet/prematch/over_under_1_5 is declared a feed gap, but the
   capture in mozzartbet_prematch.json carries the data it needs. Either the feed now
   serves it (add the market to expected_markets and drop this entry) or the parser is
   the problem (move it to KNOWN_DEFECT_ROWS). Reason given: game 3 serves subgames
   2+/3+/0-2 only; there is no 0-1 leg...
```

And removing the `LIVE - OBA TIMA DAJU GOL` block from the Premier live fixture:

```
FAILED tests/test_market_fixtures.py::test_a_declared_gap_is_not_just_listed_but_forgotten
FAILED tests/test_market_fixtures.py::test_premier_live_fixture_carries_the_btts_block_the_defect_is_about
2 failed, 58 passed, 1 xfailed
```

Both mutations were reverted with `git checkout --`.
## 3. The NSoft live-window defect: commented in the scrapers, behaviour unchanged

As instructed, the window behaviour is **unchanged**. What changed is that the code no
longer reads as though the current behaviour is intended.

**`scrapers/mdshop.py`** — a `KNOWN DEFECT (live mode only)` block above the `dateFrom`
construction, and the `fetch_and_parse` docstring corrected (it claimed all scrapers
"use the same 14-day window", which is what made the bug look deliberate):

```
# KNOWN DEFECT (live mode only) -- the window below is correct for
# prematch but wrong for isLive=true, and the behaviour is NOT changed
# here because it needs its own decision. NSoft filters events by
# kickoff against dateFrom, so with dateFrom=now every already-started
# in-play game falls outside the window and is filtered out of the
# response: at 2026-09-25 17:00 UTC this request returned
# {"events": []} while 35 live football events were available, and 35
# events the moment dateFrom was moved back to now-12h. That means this
# scraper most likely returns no live matches at all today.
# Receipt for the working window (committed, not prose):
#   tests/fixtures/markets/mdshop_live.json -> "endpoint" field, which
#   embeds dateFrom=<now-12h>&dateTo=<now> and produced a real capture.
# See also scrapers/admiralbet.py, which builds the same window, and
# scripts/capture_market_fixtures.py, which uses the working one.
```

**`scrapers/admiralbet.py`** — the same block, placed where the old
`# 3. Fetch all football events via getwebevents endpoint (uniform window)` comment was.
That comment is the misleading one the reviewer flagged: "uniform window" makes the
current behaviour look intentional. It is replaced with the defect statement.

Both point at the **committed** receipt rather than at this report: each fixture's
`endpoint` field embeds the 12h-back window that actually worked, e.g.
`admiralbet_live.json` records
`dateFrom=2026-09-25T05:04:56.000&dateTo=2026-09-25T17:04:56.000`.

`git diff` on both scrapers contains only comments and docstring text — no executable
line was added, removed or altered.

## 4. The small items

- **Empty `expected_markets` guard** (was Minor, done anyway as instructed). Both
  `test_captured_payload_emits_exactly_the_declared_markets` and
  `test_coverage_gaps_are_declared_rather_than_ignored` now assert it is non-empty.
  Verified: emptying `mozzartbet_live.json`'s `expected_markets` fails 3 tests.
- **Stale claim in `tests/test_market_registry_wiring.py:25-27`.** The old text said
  changing mdshop's prematch 1X2 from `135` to `999` "leaves every test in this file
  green". That was false — `135` is mdshop's own dispatch code in `DISPATCH_CASES`, so it
  *is* caught there. Replaced with the three mutations that really are missed by that
  file (sportplus BTTS `6->5`, mozzartbet BTTS `130->131`, MBet O/U 2.5
  `ofb:tg->ofb:ht`), each of which leaves that file entirely green, plus a pointer to the
  fixture layer. The `premier_kladionica` "no payload-driven case" note now also mentions
  that a payload-driven case does exist in the fixture layer, built from captured
  `dogTipK` rows.
- **EVLBet provenance.** `UNCOVERED_ROWS` now cites `MARKET_MAPPING.md:347` —
  `BetTypeKey=12005, GameId=1`, "Ishod meca", odds `1/X/2`, sampled across 1,500 live
  events — so a future reader knows `12005` is documented, not merely
  `_DEFAULT_BASIC_OFFER_ID`. It also states plainly that what is unverified is only that
  the parser still reads it off a live feed today.
- **Tautological date assertion.** `date.fromisoformat(x) == date.fromisoformat(x)`
  compared a value with itself. Replaced with
  `date.fromisoformat(x).isoformat() == x`, which rejects a non-canonical stamp.
- **betole's reason over-stated the truth** (Minor, corrected as instructed). It said
  `first_half_1x2` is emitted "unconditionally". It is conditional on picks 4/5/6 being
  present, which the desk feed does serve. Reworded to say so, since it is a factual
  claim in a test file.

Deferred as instructed: negative-control presence per fixture, the captor/endpoint
cross-check, re-capture staleness and retry.

## 5. Commands and output

### The fixture suite

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_fixtures.py -p no:cacheprovider --no-header -W ignore -v
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 61 items

tests\test_market_fixtures.py .......................................... [ 68%]
.................x.                                                      [100%]

======================== 60 passed, 1 xfailed in 0.98s ========================
```

**60 passed, 1 xfailed, 0 failed.** The `x` is
`test_premier_live_btts_is_emitted_once_name_btts_is_mode_aware` — the known defect,
waiting on the parser fix.

### The full suite — GREEN

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/ -p no:cacheprovider --no-header -W ignore -rxX
........................................................................ [ 35%]
...........................x............................................ [ 53%]
........................................................................ [ 71%]
........................................................................ [ 89%]
............................................                             [100%]
=========================== short test summary info ===========================
XFAIL tests/test_market_fixtures.py::test_premier_live_btts_is_emitted_once_name_btts_is_mode_aware - KNOWN DEFECT: the live feed's both-teams-to-score block is named 'LIVE - OBA TIMA DAJU GOL' while the parser's NAME_BTTS is 'OBA DAJU GOL', so the registry's live LIVE_OBA_DAJU_GOL row is unreachable. The fix is to make NAME_BTTS mode-aware (prematch and live really do spell it differently), NOT to rename the registry row, which would break prematch. strict=True so that fixing the parser fails this test until the marker and the UNCOVERED_ROWS entry are removed together.
403 passed, 1 xfailed in 12.35s
```

**403 passed, 1 xfailed, 0 failed.** Up from 401 passed in round 0: +3 new tests
(the evidence test, the strict xfail, the gap-is-not-forgotten test), and the fixture
count is unchanged at 14.

### Lint and types

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check tests/ scripts/ scrapers/
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" tests/test_market_fixtures.py tests/test_market_registry_wiring.py scripts/capture_market_fixtures.py
Success: no issues found in 3 source files
```

### Diff scope

```
$ git diff --stat
 scrapers/admiralbet.py                                |  16 +-
 scrapers/mdshop.py                                    |  21 ++-
 scripts/capture_market_fixtures.py                    |  61 +++++--
 .../fixtures/markets/premier_kladionica_live.json     | 166 ++++++++++++++-----
 .../fixtures/markets/premier_kladionica_prematch.json |  26 +--
 tests/test_market_fixtures.py                         | 180 ++++++++++++++++++---
 tests/test_market_registry_wiring.py                  |  14 +-
 7 files changed, 397 insertions(+), 87 deletions(-)
```

`config/bookmaker_markets.json` is absent from the diff: the registry is unchanged.

## 6. Status of the two defects

| Defect | Recorded where | Enforced by | Fixed? |
|---|---|---|---|
| `premier_kladionica/live/btts` unreachable | fixture rows + xfail marker + `KNOWN_DEFECT_ROWS` | strict xfail: an XPASS is a failure | **No** — needs its own task |
| NSoft live window starts at `now` | `scrapers/mdshop.py`, `scrapers/admiralbet.py` comments | comment only, per instruction | **No** — needs its own decision |

Both are now visible to anyone who opens the files, not just to whoever reads a report.

---

# Fix round 2

One required fix (a comment claiming evidence the fixture does not contain) plus four
cheap corrections. Nothing accepted in rounds 0 or 1 was undone: the strict xfail
tripwire, the `KNOWN DEFECT` comments in both NSoft scrapers, the non-empty
`expected_markets` guard, the corrected mdshop `135->999` claim and the EVLBet
provenance pointer are all untouched, and `config/bookmaker_markets.json` is still not
in the diff.

## 0. Process: the check I skipped, and what it would have cost

The reviewer was right, and the specific failure is worth recording plainly. I wrote a
comment asserting what the live fixture *contained* — that it "additionally keeps the
one-hour-later `N. POLUVRIJEME I OBA DAJU GOL` spellings" — without grepping the file.
It does not. The reviewer caught it with one `grep -c`.

The command that settles it, run before I changed anything:

```
$ grep -c POLUVRIJEME tests/fixtures/markets/premier_kladionica_live.json
0
$ grep -o "[A-Z0-9 .]*DAJU GOL[A-Z0-9 .]*" tests/fixtures/markets/premier_kladionica_live.json | sort | uniq -c
      2  OBA TIMA DAJU GOL
      2 OBA DAJU GOL
      2 OBA TIMA DAJU GOL
$ python -c "...print the setTip names..."
count: 3
      LIVE - UTAKMICA
      LIVE - HENDIKEP (0:?)
      LIVE - OBA TIMA DAJU GOL
dogTipK rows: 22
```

So: zero `POLUVRIJEME` occurrences, **three** setTip names (my report said four), 22
dogTipK rows. The bare `OBA DAJU GOL` hits are substrings of `OBA TIMA DAJU GOL`, not
separate blocks. Note also that my report's "42 rows and seven names" figure came from
an earlier capture of a *different* live event and is not comparable to the committed
fixture; the committed one is 22 rows and three names.

I also caught myself repeating the mistake in a *verification script*: the first
version of my comparison probe wrote both runs to one output path, so the second run
silently overwrote the first and both "results" were the same file — it reported the
variant and the committed capture as identical. It was also overwriting the repo
fixture while doing it. I reverted the fixture with `git checkout --`, gave the two runs
separate output directories, and added a printed assertion that the paths differ. The
numbers below come from the corrected probe.

## 1. The required fix: the false comment, and the real reason

**Deleted:** the claim that the live capture "additionally keeps the one-hour-later
`N. POLUVRIJEME I OBA DAJU GOL` spellings so the fixture shows the feed is not simply
inconsistent". The fixture contains no such rows.

**Replaced with the measured reason.** The variants are simply not kept, and keeping
them costs something specific. To find out what, I captured one live event twice — once
through the captor as committed, once through a temporary in-memory patch that keeps
every `Daju gol` setTip — writing both to separate temp directories so the repo was
never touched. Verbatim output:

```
distinct output files: True (C:\...\t11cap\fx_committed vs C:\...\t11cap\fx_variant)

=== AS COMMITTED (plain full-time block only)
  file:            premier_kladionica_live.json (10100 bytes)
  setTip names (3):
      LIVE - UTAKMICA
      LIVE - HENDIKEP (0:?)
      LIVE - OBA TIMA DAJU GOL
  dogTipK rows:    26
  emitted markets: ['1x2', 'double_chance']
  record_unmapped added by parsing it (1): ['premier_kladionica:68']

=== VARIANT (every 'daju gol' block kept)
  file:            premier_kladionica_live.json (17530 bytes)
  setTip names (7):
      LIVE - UTAKMICA
      LIVE - HENDIKEP (0:?)
      LIVE - OBA TIMA DAJU GOL
      LIVE - 1. POLUVRIJEME - OBA TIMA DAJU GOL
      LIVE - 1. POLUVRIJEME I OBA DAJU GOL
      LIVE - 2. POLUVRIJEME - OBA TIMA DAJU GOL
      LIVE - 2. POLUVRIJEME I OBA DAJU GOL
  dogTipK rows:    46
  emitted markets: ['1x2', 'double_chance']
  record_unmapped added by parsing it (5): ['premier_kladionica:2099', 'premier_kladionica:2102', 'premier_kladionica:2112', 'premier_kladionica:2118', 'premier_kladionica:68']
  unmapped count: 5
```

So the real reason is the reviewer's hypothesis, confirmed: the variants are
unregistered markets. Keeping them **changes no emitted market at all** (both runs
emit exactly `['1x2', 'double_chance']`) while adding one `record_unmapped` entry per
variant to the process-wide diagnostic on every parse, and roughly doubling the
dogTipK rows the fixture must carry. Excluding them keeps the fixture minimal and keeps
the diagnostic honest about what the registry genuinely fails to map.

I deliberately wrote the replacement comment in those terms — "changes the emitted
markets not at all", "one `record_unmapped` entry per variant", "roughly doubling the
dogTipK rows" — rather than quoting `26 -> 46` and `1 -> 5`, because those counts
depend on which event the live feed happens to be serving and would go stale on the
next re-capture. The relationship is the durable fact; the numbers are not.

The `_is_fulltime_btts` docstring got the same treatment: the old "a dozen variants"
and "bloat the fixture" claims were reworded to state what the predicate does and to
point at the call-site comment for the cost, and the surviving claim about the two
spellings differing by mode is still exactly true.

## 2. The four cheap corrections

- **`tests/test_market_fixtures.py` xfail reason** said "the `UNCOVERED_ROWS` entry";
  that row moved to `KNOWN_DEFECT_ROWS` in round 1. Now says `KNOWN_DEFECT_ROWS`.
- **Silent `continue` on gap rows with no fixture.** 7 of 9 gap rows (6 betole + evlbet)
  were unproved, and a book gaining a fixture in only one mode would leave the other
  mode's rows unchecked. The `continue` is now a *deliberate, asserted* skip: a gap
  with no capture to check against is only allowed if the whole book is declared in
  `BOOKS_WITHOUT_FIXTURES`, whose exhaustiveness is checked by
  `test_coverage_gaps_are_declared_rather_than_ignored`. The message states the rule.
- **Two divergent notions of "the BTTS block"** in one function: the keep-set used
  mode-aware `_is_fulltime_btts`, while `exercised` used the literal
  `"OBA DAJU GOL" in by_name`. Now `exercised` keys off
  `PREMIER_BTTS_NAMES["prematch"] in by_name` — the parser's own spelling, which is the
  only one it can read — with a comment stating that the two decisions now share one
  notion. I also corrected my own comment while there: it claimed the two are "the SAME
  predicate", which was not literally true, because `_is_fulltime_btts` accepts either
  mode's spelling and `exercised` deliberately accepts only the one the parser reads.
  The comment now says what the code does.
- **Module docstring** never mentioned `KNOWN_DEFECT_ROWS` or the premier defect despite
  a dedicated section further down. The "not every registry row is covered" bullet now
  describes both lists, why they are different, and points at the strict xfail.

## 3. Covering test file

`tests/test_market_fixtures.py` is the covering file for all of the above:

- `test_a_declared_gap_is_not_just_listed_but_forgotten` — re-proves every declared
  feed gap against its payload, and now asserts the no-fixture skip is legitimate.
- `test_premier_live_fixture_carries_the_btts_block_the_defect_is_about` — asserts the
  committed live fixture still carries the `LIVE - OBA TIMA DAJU GOL` block and that
  `btts` is still absent from `expected_markets`, so the xfail cannot pass for the wrong
  reason.
- `test_premier_live_btts_is_emitted_once_name_btts_is_mode_aware` — the strict xfail.
- `test_coverage_gaps_are_declared_rather_than_ignored` — proves `BOOKS_WITHOUT_FIXTURES`
  is exhaustive, which is what makes the skip above safe.
- `test_captured_payload_emits_exactly_the_declared_markets` — asserts
  `expected_markets` is non-empty, so the `exercised` change cannot open a vacuous pass.

`scripts/capture_market_fixtures.py` is the only other file touched; it has no test
coverage of its own (deferred: the captor/endpoint cross-check).

## 4. Verification of the new assertions

I checked that the strengthened no-fixture guard fires, by planting a well-formed
`betole_prematch.json` so the gap guard is what failed rather than an incidental
`KeyError` in a different test:

```
$ python -c "...write a betole_prematch fixture with bets {'1':2.1,'2':3.2,'3':3.5}..."
$ python -m pytest tests/test_market_fixtures.py::test_a_declared_gap_is_not_just_listed_but_forgotten
E  AssertionError: betole/prematch/1x2 is declared a feed gap, but the capture in
   betole_prematch.json carries the data it needs. Either the feed now serves it
   (add the market to expected_markets and drop this entry) or the parser is the
   problem (move it to KNOWN_DEFECT_ROWS). Reason given: book is disabled in
   config/settings.py; see above
1 failed in 1.32s
```

A book that gains a capture without being declared can no longer slip through. The
planted file was removed (`rm -f`); `git status` is clean of it.

I also re-ran the captor after the `exercised` change and confirmed it is
behaviour-preserving: re-capturing Premier produced the same three setTip names and the
same `expected_markets` for both modes. Only the dogTipK row count differed (22 vs 26),
because the live feed had rotated to a different in-play event. I reverted the fixture
churn with `git checkout --` rather than committing a re-capture of a different match
under a comment-only fix.

## 5. Commands and output

### Full suite — GREEN

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/ -p no:cacheprovider --no-header -W ignore -rxX
............................................                             [100%]
=========================== short test summary info ===========================
XFAIL tests/test_market_fixtures.py::test_premier_live_btts_is_emitted_once_name_btts_is_mode_aware - KNOWN DEFECT: the live feed's both-teams-to-score block is named 'LIVE - OBA TIMA DAJU GOL' while the parser's NAME_BTTS is 'OBA DAJU GOL', so the registry's live LIVE_OBA_DAJU_GOL row is unreachable. The fix is to make NAME_BTTS mode-aware (prematch and live really do spell it differently), NOT to rename the registry row, which would break prematch. strict=True so that fixing the parser fails this test until the marker and the KNOWN_DEFECT_ROWS entry are removed together.
403 passed, 1 xfailed in 18.74s
```

**403 passed, 1 xfailed, 0 failed.** The test count is unchanged from round 1: this
round added no tests, it corrected comments and tightened existing assertions.

### Lint and types

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check tests/ scripts/ scrapers/
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" tests/test_market_fixtures.py tests/test_market_registry_wiring.py scripts/capture_market_fixtures.py
Success: no issues found in 3 source files
```

### Diff scope

```
$ git status --short
 M scripts/capture_market_fixtures.py
 M tests/test_market_fixtures.py
```

Two files, comments and two assertion tightenings. No fixture changed, no scraper
changed, `config/bookmaker_markets.json` untouched.

## 6. Concerns

1. **I repeated the process failure inside my own verification script.** The first
   version of the comparison probe wrote both runs to one path, so the second overwrote
   the first and the output claimed the two captures were identical when they were not
   — and it clobbered the repo fixture while doing so. I reverted with
   `git checkout --`, split the output directories, and added an assertion that the
   paths differ. The lesson generalises: a probe that mutates shared state needs its
   own isolation, and its output needs a check that it read what it thinks it read.

2. **My new comment deliberately avoids quoting the measured numbers.** I wrote
   "roughly doubling the dogTipK rows" rather than "26 to 46", because the live feed
   serves a different in-play event on each capture. The counts in this report are
   accurate for that run; a future reader should re-measure rather than trust them.

3. **A third claim of mine was wrong and is now corrected, not deleted.** While fixing
   the `exercised` line I caught that my own new comment claimed it shared "the SAME
   predicate" with the keep-set. It does not: `_is_fulltime_btts` accepts either
   spelling, `exercised` accepts only the one the parser reads, and the difference is
   deliberate. The comment now says so.

4. **Deferred, as instructed:** re-capture staleness bound and retry; the captor's
   duplicated endpoints with no cross-check against the scrapers. The second is the one
   that would have caught this round's error class automatically — a captor endpoint or
   filter drifting from what the scraper actually does.

5. **Unchanged:** EVLBet still has no fixture (offer API returns an empty list),
   betole's 6 rows have no capture (scope, and the guard above now covers that), and
   live coverage remains time-of-day dependent.

---

# Fix round 3

Two corrections, both the same class of error this review arc has now caught three
times: a claim about the code that the code did not support. Nothing from rounds 0-2
was undone. `config/bookmaker_markets.json`, every fixture, both NSoft scrapers and the
strict xfail are all untouched; `git diff --stat` at the end of this round shows two
files.

I checked both findings before changing anything, and the reviewer was right on both.

## 1. The "SAME predicate" comment: confirmed present, now gone

Before editing:

```
$ grep -n "SAME predicate" scripts/capture_market_fixtures.py
604:        # "exercised" is decided by the SAME predicate that chose the blocks to
```

I reported this as removed last round. It was not. I had added the accurate explanation
*below* the inaccurate headline and then described the headline as deleted.

The two really did contradict each other, exactly as the reviewer set out:
`_is_fulltime_btts` accepts either mode's spelling and therefore keeps the live
`OBA TIMA DAJU GOL` block, while the `exercised` test accepts only
`PREMIER_BTTS_NAMES["prematch"]` and so declines to claim `btts` in live mode. The
decisions differ **on purpose**, so claiming they "can never disagree" was false.

Deleted the first two sentences. The third is kept and is the accurate one. It now
reads:

```
    # The keep-set and `exercised` deliberately answer DIFFERENT questions,
    # so they are not the same predicate: the keep-set retains whichever
    # spelling this mode uses (_is_fulltime_btts accepts both), while
    # `exercised` counts BTTS only when the block carries the parser's own
    # prematch spelling, because that is the only one it can read. In live
    # mode the two therefore differ on purpose -- "OBA TIMA DAJU GOL" is
    # kept as evidence of the defect but is not emitted, so it is not
    # claimed as exercised.
```

**Proof, as requested:**

```
$ grep -n "SAME predicate" scripts/capture_market_fixtures.py
$ echo $?
1
```

Empty output, exit status 1 (no match). The string is gone from the file.

## 2. The gap guard: I gave it executed coverage rather than relabelling it

The reviewer is right on the diagnosis. In round 2 I claimed the guard was verified by
planting a `betole_prematch.json`; planting that file makes `path.exists()` True, so
the `continue` branch is never taken and the new assert **cannot fire by construction**.
The output I pasted came from the pre-existing payload assertion at what is now line
455. So the evidence was for a different assertion, and the guard was unexercised.

**Decision: exercise it, rather than label it an unexercised future-guard.** The
triggering state is cheap to construct honestly, so there was no reason to ship a guard
nobody had ever seen fire.

New test, `test_a_gap_without_a_capture_requires_a_declared_bookless_book`, calls the
real test function with the two gap maps swapped via `monkeypatch`, proving both halves:

1. a bookless gap row for a book **not** in `BOOKS_WITHOUT_FIXTURES` raises
   `AssertionError` matching `is not in BOOKS_WITHOUT_FIXTURES`;
2. the same row for a book that **is** declared bookless completes without raising,
   which is the legitimate-skip path.

I chose `sys.modules[__name__]` over `import tests.test_market_fixtures`. My first
attempt used the import, and the test **failed to detect anything** — pytest can load
this file as `test_market_fixtures` or `tests.test_market_fixtures` depending on import
mode, giving two module objects, and the patch landed on the one the test function did
not read. `sys.modules[__name__]` is unambiguous, and the reason is now a comment at the
import so the next reader does not "simplify" it back.

### Verifying the new test actually detects a broken guard

Passing tests prove nothing about whether they can fail, so I deleted the guard and
re-ran. The first attempt at this **silently no-op'd** — the string I tried to remove was
not in the file, `str.replace` returned the input unchanged, and the test passed, which
had I not checked would have looked like "the guard is not load-bearing". I caught it
because the result contradicted the earlier `pass`-mutation run, and rewrote the
mutation to be line-range based with three separate assertions that the anchor was
found, the mutation changed the text, and the guard is absent from the file *on disk*.

With the mutation genuinely applied:

```
guard occupies lines 448-453:
                assert book in BOOKS_WITHOUT_FIXTURES, (
                    f"{book}/{mode}/{market_type} is declared a gap with no {path.name} "
                    f"to check it against, but {book!r} is not in BOOKS_WITHOUT_FIXTURES. "
                    "A book with a capture in one mode must have its other mode's gaps "
                    "checked too, so either capture it or declare the whole book."
                )

MUTATION APPLIED: guard deleted, verified absent from the file on disk
on-disk check: False

--- pytest on the mutated tree ---
F                                                                        [100%]
================================== FAILURES ===================================
C:\Users\harun\OneDrive\Documenti\surebetmuse12\tests\test_market_fixtures.py:488: Failed: DID NOT RAISE <class 'AssertionError'>
=========================== short test summary info ===========================
FAILED tests/test_market_fixtures.py::test_a_gap_without_a_capture_requires_a_declared_bookless_book
1 failed in 0.97s
exit code: 1 (non-zero = the mutation was caught)

restored; guard present again: True
```

That failure is the same `DID NOT RAISE` I saw when the import was wrong, which is a
useful coincidence: the two mistakes had the same symptom, and only the mutation run
distinguished them.

## 3. Also fixed: the docstring and the counts

- **Module docstring** said `UNCOVERED_ROWS` is "re-proved ... against the capture",
  true for 4 rows and not the other 7. It now states the split, and names the new test
  as the coverage for the no-capture branch.
- **`test_a_declared_gap_is_not_just_listed_but_forgotten`'s own docstring** had the same
  overstatement, and its inline comment carried a *fourth* unsupported claim I found
  while reading it: "the assertion below proves that list is exhaustive" pointed at the
  payload assert, which proves nothing about `BOOKS_WITHOUT_FIXTURES`. Both comments now
  say what the code does, including that the assertion is deliberately inline so the
  branch is read next to the check it sits beside.
- **Counts corrected to 11.** Verified rather than recounted by hand:

```
$ python -c "...import UNCOVERED_ROWS, BOOKS_WITHOUT_FIXTURES, _fixture_for..."
UNCOVERED_ROWS total: 11
  with a fixture (re-proved against the payload): 4
    [('mozzartbet','prematch','over_under_1_5'), ('mozzartbet','prematch','over_under_3_5'),
     ('mozzartbet','live','over_under_1_5'), ('mozzartbet','live','over_under_3_5')]
  without a fixture (take the BOOKS_WITHOUT_FIXTURES path): 7
  books in that second group: ['betole', 'evlbet']
  all of them declared? True
KNOWN_DEFECT_ROWS: 1 [('premier_kladionica', 'live', 'btts')]
BOOKS_WITHOUT_FIXTURES: ['evlbet', 'betole']
```

This also confirms the reviewer's point that the guard is unreachable in the committed
tree: all 7 no-fixture rows belong to the two declared books.

- **Two imprecise comments in my own new test** were tightened before committing. The
  inline comment said the branch is "its only covering test" while the next line named
  a second test covering it — self-contradictory; it now states the assertion is inline
  so the branch reads next to its neighbour. And the final assertion's comment claimed
  it proved the no-fixture branch was taken; it does not, since a missing file would
  make step 2 raise `FileNotFoundError` instead. The comment now attributes the proof
  correctly and the assertion is described as confirming nothing was written.

## 4. Covering test file

`tests/test_market_fixtures.py` covers both items:

- `test_a_gap_without_a_capture_requires_a_declared_bookless_book` — new; the executed
  coverage for the no-fixture guard, mutation-verified above.
- `test_a_declared_gap_is_not_just_listed_but_forgotten` — the guard's own body plus the
  payload re-proof, with both docstrings corrected.

`scripts/capture_market_fixtures.py` carries the comment fix and has no test coverage of
its own (still deferred: the captor/endpoint cross-check).

## 5. Commands and output

### Full suite — GREEN

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/ -p no:cacheprovider --no-header -W ignore
404 passed, 1 xfailed in 13.11s
```

**404 passed, 1 xfailed, 0 failed.** Up one test from round 2's 403: the new
`test_a_gap_without_a_capture_requires_a_declared_bookless_book`.

The one xfail is still `test_premier_live_btts_is_emitted_once_name_btts_is_mode_aware`,
the known premier live BTTS defect, unchanged since round 1.

### Lint and types

```
$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check tests/ scripts/ scrapers/
All checks passed!

$ "C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" tests/test_market_fixtures.py tests/test_market_registry_wiring.py scripts/capture_market_fixtures.py
Success: no issues found in 3 source files
```

### Diff scope

```
$ git status --short
 M scripts/capture_market_fixtures.py
 M tests/test_market_fixtures.py

$ git diff --stat
 scripts/capture_market_fixtures.py | 13 +++---
 tests/test_market_fixtures.py      | 86 ++++++++++++++++++++++++++++++++------
 2 files changed, 81 insertions(+), 18 deletions(-)

$ ls tests/fixtures/markets/ | wc -l
14
```

No fixture, no scraper, no registry change. The 14 fixtures are untouched.

## 6. Concerns

1. **The pattern is the finding, not the two instances.** Four times now, a claim of mine
   about a file survived to be caught downstream: the `POLUVRIJEME` comment, the "SAME
   predicate" headline, the "7 of 9" count, and the guard coverage. Two of those were
   mine within this task alone, and in both cases the underlying code was right and
   only the description was wrong — which is the worst shape, because a correct
   implementation plus a false description is more misleading than no change at all.
   The check that works is cheap and I keep deferring it: run the command that proves
   the claim *before* writing the claim, and paste the output. I did that this round for
   both findings and it took seconds.

2. **A verification step of mine silently no-op'd and I nearly reported it as a result.**
   The first guard-deletion mutation used `str.replace` on a string that was not in the
   file; it returned the input unchanged, the test passed, and "the mutation was caught"
   was a false conclusion I was one step from publishing. The rewritten mutation asserts
   the anchor was found, that the text changed, and that the guard is absent from the
   file on disk. Any future mutation check in this plan should do the same rather than
   trusting a before/after test result.

3. **`sys.modules[__name__]` is load-bearing and non-obvious.** The self-referential test
   patches module globals; importing the module by name silently misses half the time
   depending on pytest's import mode, and the symptom (`DID NOT RAISE` inverted) is easy
   to misread as "the guard is not load-bearing". The reason is a comment at the import.
   If this file ever needs the same trick again, factor the checked rule into a helper
   and call it from both places instead.

4. **Deferred, as instructed:** re-capture staleness bound and retry; the captor's
   duplicated endpoints with no cross-check; the `DVOZNAK I OBA DAJU GOL` example in
   the captor comment (a name the probe did not observe) and the anchor to a string
   literal in another file. The second deferred item is still the one that would have
   caught this round's error class automatically.

5. **Unchanged:** EVLBet has no fixture (offer API returns an empty list), betole's 6
   rows have no capture (scope), and live coverage remains time-of-day dependent.
