# Task 3 Report — Integrate CertaintyGate into MatchMatcher

**Status:** DONE_WITH_CONCERNS  
**Commit:** `8e8246790e8cc577ec9819c5784f9970100011c6`  
**Branch:** `master` (worked in place; no worktree or branch created)  
**Date:** 2026-09-25

## What changed

### `engine/matcher.py`

- Loaded `config/league_equivalences.json` in `MatchMatcher.__init__` and passed the parsed pairs to `CertaintyGate`.
- Removed the `EUROPEAN_COMPATIBLE_LEAGUES` constant and every blanket European candidate/scorer exception.
- Added candidate buckets for only identical leagues, generic-league groups, and explicitly declared equivalence pairs.
- Kept `_calculate_confidence` as the cheap candidate-pruning step, but made it reject non-equivalent specific league pairs.
- Made the gate the final authority after candidate selection:
  - `verified` accepts the match and uses `gate_result.is_swapped` for orientation;
  - `suggested` or `rejected` does not append the match;
  - every non-verified gate result is logged at DEBUG with its reasons;
  - a rejected candidate is retained as a new singleton internally.
- New groups are explicitly `status="suggested"` and receive exactly the required initial `MatchEvidence(rule="rule_stage", source="rule", reason="new_group")` record.
- Groups are promoted to `verified` only after a second distinct bookmaker has passed the gate.
- The final filter now returns only `status == "verified"` groups with at least two distinct bookmakers.
- The matcher supplies the curated team mapping variations to the gate as reviewed aliases. This preserves the rule that unlisted fuzzy collisions are not accepted.

### `config/league_mappings.json`

- Removed `Argentina 2`, `ARGENTINA 2`, `Primera B Nacional`, and `Primera Nacional` from `argentine_primera`.
- Added `argentine_primera_b_nacional` with the exact requested variations.
- Added `bugarian_second_league` with the exact requested variations.
- Removed `Bundesliga 2` from `bundesliga_2`; it remains in `nemacka_2` as required.

### `config/league_equivalences.json`

Created with the exact requested shape:

```json
{
  "pairs": [
    ["europa_league", "conference_league"]
  ]
}
```

### `engine/certainty.py`

The supplied integration fixture contains reviewed team-name variants such as `Željezničar`/`Zeljeznicar` and `Sarajevo`/`FK Sarajevo`. Task 2 intentionally requires a different raw form to be explicitly allowlisted before fuzzy acceptance. To keep that security rule while allowing the curated mapping variants, the allowlisted fuzzy score now compares lossless surface-normalized spellings (diacritics removed). The raw-name equality and allowlist checks remain in force; unlisted fuzzy names are still unresolved. This is the one production change outside the task brief’s listed matcher/mapping files and is called out as a deviation/concern below.

### Tests

- Created `tests/test_matcher_certified.py` with the six tests from the brief.
- Updated `tests/test_matcher.py` fixtures and assertions as described below.
- Updated `tests/test_pipeline.py` as an additional fixture correction required for the full suite.

## TDD trace

### RED: required integration test before implementation

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py -v
```

Output before matcher/mapping implementation:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 6 items

tests\\test_matcher_certified.py F.F...                                   [100%]

================================== FAILURES ===================================
_________________ test_verified_group_returned_with_evidence __________________

    def test_verified_group_returned_with_evidence():
        a = _m("mdshop", "\u017deljezni\u010dar", "Sarajevo", "BiH - Premier Liga", event_id="1")
        b = _m("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", event_id="2")
        groups = MatchMatcher().group_matches([a, b])
        assert len(groups) == 1
>       assert groups[0].status == "verified"
E       AssertionError: assert 'suggested' == 'verified'

E         - verified
E         + suggested

tests\\test_matcher_certified.py:39: AssertionError
_________________ test_europa_conference_merge_only_via_declared_equivalence __________________

    def test_europa_conference_merge_only_via_declared_equivalence():
        a = _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="1")
        b = _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="2")
        import engine.matcher as matcher_mod

>       assert not hasattr(matcher_mod, "EUROPEAN_COMPATIBLE_LEAGUES"), (
            "blanket European merging must be removed"
        )
E       AssertionError: blanket European merging must be removed
E       assert not True
E        +  where True = hasattr(<module 'engine.matcher' from 'C:\\Users\\harun\\OneDrive\\Documenti\\surebetmuse12\\engine\\matcher.py'>, 'EUROPEAN_COMPATIBLE_LEAGUES')

tests\\test_matcher_certified.py:55: AssertionError
=========================== short test summary info ============================
FAILED tests/test_matcher_certified.py::test_verified_group_returned_with_evidence
FAILED tests/test_matcher_certified.py::test_europa_conference_merge_only_via_declared_equivalence
2 failed, 4 passed in 1.27s
```

This was the expected RED state: the matcher did not set verified status/evidence and still exported the blanket European compatibility set.

### Intermediate RED after the first matcher implementation

The first literal matcher integration removed the blanket set and wired the gate, but the supplied team-variant fixture remained `team_unresolved` because Task 2’s raw-name/allowlist policy correctly rejected the different raw forms. The focused run was:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher.py tests/test_matcher_certified.py -v
```

Relevant result:

```text
FAILED tests/test_matcher.py::test_same_match_groups_across_bookmakers
FAILED tests/test_matcher.py::test_home_away_swap_detection
FAILED tests/test_matcher_certified.py::test_verified_group_returned_with_evidence
3 failed, 10 passed in 1.67s
```

The failure was diagnosed as the intended raw alias policy, not a scorer or league-gate failure. I then supplied the curated team mappings as the matcher gate’s explicit alias allowlist and made only allowlisted score comparison insensitive to lossless diacritic spelling differences. An unlisted normalizer-fuzzy example (`Sarjevo` versus `Sarajevo`) was separately checked and remained unresolved.

### GREEN: focused certified suite

Final focused command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py -v
```

Full output:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\Users\harun\OneDrive\Documenti\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 6 items

tests\\test_matcher_certified.py ......                                   [100%]

============================== 6 passed in 0.90s =============================
```

## Test updates and rationale

### `tests/test_matcher.py`

1. **`_match()` helper** now sets:
   - `event_id=f"{bookmaker}-{home}"`;
   - `url=f"https://example.test/{bookmaker}"`;
   - `deep_link_verified=True`.

   Reason: the certainty gate correctly treats missing/unverified event links as `suggested`, so the old linkless fixtures could no longer produce returned multi-book groups.

2. **`test_same_match_groups_across_bookmakers`** now asserts `groups[0].status == "verified"` in addition to the existing length assertions.

   Reason: matcher output is now certified-only, and the test should pin that contract.

3. **`test_home_away_swap_detection`** now asserts `groups[0].status == "verified"` in addition to checking the canonical swap and odds-label behavior.

   Reason: the swap must be accepted through the gate, not merely by the legacy scorer.

The U21 and Women tests were left asserting `len(groups) == 0`, as requested. Their category mismatch behavior remains covered.

### `tests/test_pipeline.py`

The shared pipeline `_match()` helper was also updated to set an event ID, URL, and `deep_link_verified=True`. This was not named in the brief’s Step 5 list, but its fixtures also construct matcher inputs without links; without this correction the full suite could not remain green under the global verified-link requirement.

### `tests/test_matcher_certified.py`

Created with the six required integration cases: verified evidence, unresolved teams, explicit Europa/Conference equivalence, 16-minute kickoff rejection, three-hour rejection, and unverified-link non-verification.

## Final verification

All commands below were run after the final code changes and after the commit.

### Full test suite

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
```

Full output (exit code 0):

```text
........................................................................ [ 50%]
........................................................................ [100%]
```

There are 144 collected tests in the current suite. The repository’s `pyproject.toml` already supplies `-q`, so the second quiet flag suppresses the usual summary line.

### Ruff

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

### Mypy

Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 0):

```text
engine\\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 41 source files
```

The notes are pre-existing untyped-function notes; there are no type errors.

### Diff check and commit

Commands:

```text
git diff --cached --check
git commit -m "feat(mapping): integrate certainty gate into matcher, remove blanket European merging, fix wrong league entries"
```

Commit output:

```text
[master 8e82467] feat(mapping): integrate certainty gate into matcher, remove blanket European merging, fix wrong league entries
 7 files changed, 265 insertions(+), 66 deletions(-)
 create mode 100644 config/league_equivalences.json
 create mode 100644 tests/test_matcher_certified.py
```

Post-commit repository state:

```text
## master
8e82467 feat(mapping): integrate certainty gate into matcher, remove blanket European merging, fix wrong league entries
```

No unstaged or uncommitted files remained.

## Cache-based group-count comparison

No network was used. The local `cache/last_scan.json` contains 6,999 raw matches. I compared the legacy matcher from `HEAD` before this commit with the new matcher in a temporary, local-only script:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" "C:/Users/harun/AppData/Local/Temp/opencode/count_cache_groups.py"
```

Full output:

```text
raw_matches=6999
current_groups=0
legacy_groups=1134
legacy_multi_book_groups=1134
```

The zero current result is expected for this cache snapshot: its match records do not contain `event_id` or `deep_link_verified`, so the link gate correctly prevents every group from being certified. This is the intended correctness-over-yield reduction, not a network or scraper failure.

## Deviations from the brief

1. **`engine/certainty.py` was modified** even though the brief’s file list named matcher/config/tests. The supplied certified fixture uses reviewed diacritic/club-prefix variants, while Task 2’s final gate requires an explicit allowlist for differing raw forms. The matcher now derives that allowlist from the curated `team_mappings.json`, and allowlisted scoring ignores only lossless diacritic spelling differences. Unlisted fuzzy names remain unresolved.
2. **`tests/test_pipeline.py` was also updated**, although Step 5 only named `tests/test_matcher.py`. Its matcher fixtures otherwise fail the global verified-link requirement, so this was necessary to keep the full suite green.
3. The matcher’s JSON loader validates the top-level object and pair shape instead of blindly calling `.get()`/adding any two values. This is defensive behavior around the same equivalence configuration and does not change the requested file format.

## Concerns

- The extra `CertaintyGate` surface-normalization change should be reviewed alongside the later dedicated team-alias-allowlist work. It is intentionally gated by the curated mapping allowlist, but a future task may want to move that source to an explicit reviewed alias file rather than deriving it from all team mappings.
- Existing cached matches without link metadata now produce zero certified groups. Production scrapers must populate `event_id`/`deep_link_verified` before the reduction can be distinguished from a real data-quality issue.
- The legacy matcher’s 1,134 cached multi-book groups are not directly comparable to certified output: the cache predates the new link evidence fields, and the new gate intentionally rejects those records.

**Final commit:** `8e8246790e8cc577ec9819c5784f9970100011c6`

## Fix round 1 — review findings

**Base commit:** `8e8246790e8cc577ec9819c5784f9970100011c6`  
**Fix-round commit:** `4141848c19ba4149ed618d96e83ccb98b7c9e061`  
**Status:** DONE_WITH_CONCERNS

### Finding 1 — explicit alias approval registry

The previous implementation incorrectly derived pairwise fuzzy approvals from `config/team_mappings.json`. That file remains a normalization registry only. The matcher now reads `config/team_alias_allowlist.json`, and the file contains these deliberately enumerated, lower-case, `|`-joined sorted pairs:

```text
a. salzburg|austria salzburg
borac banja luka|borac bl
fk sarajevo|sarajevo
lech|lech p.
lech|lech poznan
lech p.|lech poznan
mjallby|mjallby aif
r.b. salzburg|salzburg
sloboda|sloboda tuzla
zeljeznicar|željezničar
```

Reasons for each seed:

- `zeljeznicar|željezničar` — required by the existing certified matcher fixture; this is the reviewed diacritic spelling pair.
- `fk sarajevo|sarajevo` — required by the existing certified matcher fixture and the same club appears under both raw forms in the local scrape corpus.
- `borac banja luka|borac bl` — present together in the local corpus and required by the pipeline fixture; both are the Banja Luka club with an explicit city abbreviation.
- `sloboda|sloboda tuzla` — required by the pipeline fixture as the same club with a city-qualified name; it is reviewed separately rather than inferred from the mapping registry.
- `lech|lech p.`, `lech|lech poznan`, and `lech p.|lech poznan` — the local corpus contains `Lech`, `Lech P.`, and `Lech Poznan` for the same European fixture. All three pairings are seeded because the first raw form encountered may become the group anchor, and each is a reviewed spelling/abbreviation of the same club.
- `a. salzburg|austria salzburg` — the local corpus contains both forms for the same Austrian fixture; the abbreviated dotted form is explicitly reviewed.
- `mjallby|mjallby aif` — a deliberately reviewed Swedish club-designator variant identified in the review findings; it is not generated from the mapping registry.
- `r.b. salzburg|salzburg` — a deliberately reviewed dotted club-prefix variant identified in the review findings; it is not generated from the mapping registry.

The negative regression test uses `Sporting` versus `Sporting CP`. Both normalize to the same canonical team through `team_mappings.json`, but that pair is intentionally absent from the approval file and must not become tradeable.

### Finding 2 — one reachable German tier-two canonical

`bundesliga_2` is the chosen canonical home for the qualified German tier-two names. The duplicate normalized values `2. Bundesliga` and `Njemacka - 2. Bundesliga` were removed from `nemacka_2`; `Bundesliga 2` remains in `nemacka_2` as required by the original mapping brief. The new test proves:

```python
TeamNormalizer().normalize_league("2. Bundesliga") == "bundesliga_2"
```

### Finding 3 — Bulgarian second-tier normalization

Only the `vtora liga` entry was removed from `TeamNormalizer.GENERIC_LEAGUE_RAW`; no other normalizer public behavior was changed. The exact reverse mapping now makes:

```python
TeamNormalizer().normalize_league("Vtora Liga") == "bugarian_second_league"
```

### Finding 4 — non-vacuous integration coverage

`tests/test_matcher_certified.py` now:

- requires the Europa/Conference group to exist, verifies it, and asserts the exact league-pair evidence;
- requires the 16-minute and unverified-link cases to return `[]`;
- proves an unapproved mapping variation (`Sporting`/`Sporting CP`) is not verified;
- proves a gate-rejected singleton cannot later pull a later match into the wrong returned group.

`tests/test_normalizer.py` now pins BiH Premier Liga, Portuguese Primeira Liga, German tier two, and Bulgarian second-tier canonical IDs.

Covering test files are `tests/test_matcher_certified.py`, `tests/test_normalizer.py`, the existing `tests/test_matcher.py`/`tests/test_pipeline.py` seed-path fixtures, and the existing direct alias tests in `tests/test_certainty.py`.

### Fix-round TDD RED

Tests were changed before the production fixes. Command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py tests/test_normalizer.py -v
```

Full output before the fix:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\\Users\\harun\\OneDrive\\Documenti\\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 16 items

tests\\test_matcher_certified.py ......F.                                 [ 50%]
tests\\test_normalizer.py ......FF                                        [100%]

================================== FAILURES ===================================
______________ test_unreviewed_mapping_variation_is_not_verified ______________

    def test_unreviewed_mapping_variation_is_not_verified():
        a = _m("mdshop", "Sporting", "Alverca", "Primeira Liga", event_id="1")
        b = _m("mbet", "Sporting CP", "Alverca", "Liga Portugal", event_id="2")
        groups = MatchMatcher().group_matches([a, b])
>       assert groups == []
E       AssertionError: assert [MatchGroup(c...entries=[])])] == []
E
E         Left contains one more item: MatchGroup(canonical_home='sporting_cp', canonical_away='alverca', league='primeira_liga', kickoff=datetime.datetime(2...rce='rule', confidence=1.0, reason='verified_link', league_pair=[], kickoff_delta_minutes=None, allowlist_entries=[])])
E         Use -v to get more diff

tests\\test_matcher_certified.py:112: AssertionError
_________________ test_german_tier_two_has_one_reachable_canonical_id _________________

    def test_german_tier_two_has_one_reachable_canonical_id():
        n = TeamNormalizer()
>       assert n.normalize_league("2. Bundesliga") == "bundesliga_2"
E       AssertionError: assert 'nemacka_2' == 'bundesliga_2'

E         - bundesliga_2
E         + nemacka_2

tests\\test_normalizer.py:48: AssertionError
__________________ test_bulgarian_second_league_is_not_treated_as_generic __________________

    def test_bulgarian_second_league_is_not_treated_as_generic():
        n = TeamNormalizer()
>       assert n.normalize_league("Vtora Liga") == "bugarian_second_league"
E       AssertionError: assert 'vtora liga' == 'bugarian_second_league'

E         - bugarian_second_league
E         + vtora liga

tests\\test_normalizer.py:53: AssertionError
=========================== short test summary info ============================
FAILED tests/test_matcher_certified.py::test_unreviewed_mapping_variation_is_not_verified
FAILED tests/test_normalizer.py::test_german_tier_two_has_one_reachable_canonical_id
FAILED tests/test_normalizer.py::test_bulgarian_second_league_is_not_treated_as_generic
3 failed, 13 passed in 1.79s
```

These failures were for the intended reasons: generated mapping trust, last-write-wins league collision, and the generic short-name bypass.

### Fix-round GREEN and verification

Focused command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py tests/test_normalizer.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\\Users\\harun\\OneDrive\\Documenti\\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 16 items

tests\\test_matcher_certified.py ........                                 [ 50%]
tests\\test_normalizer.py ........                                        [100%]

============================= 16 passed in 1.25s =============================
```

Full suite command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
```

Full output (exit code 0):

```text
........................................................................ [ 48%]
........................................................................ [ 97%]
....                                                                     [100%]
```

Ruff command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

Mypy command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 0):

```text
engine\\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 41 source files
```

Explicit allowlist assertion command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -c "from engine.matcher import MatchMatcher; a=MatchMatcher().gate.alias_allowlist; expected={'a. salzburg|austria salzburg','borac banja luka|borac bl','fk sarajevo|sarajevo','lech|lech p.','lech|lech poznan','lech p.|lech poznan','mjallby|mjallby aif','r.b. salzburg|salzburg','sloboda|sloboda tuzla','zeljeznicar|željezničar'}; assert a==expected, sorted(a); assert 'sporting|sporting cp' not in a; print('explicit alias allowlist assertions passed:', len(a), 'entries')"
```

Full output (exit code 0):

```text
explicit alias allowlist assertions passed: 10 entries
```

### Fix-round commit

```text
[master 4141848] fix(mapping): separate reviewed team aliases and repair league canonicals
 6 files changed, 81 insertions(+), 21 deletions(-)
 create mode 100644 config/team_alias_allowlist.json
```

**Fix-round commit:** `4141848c19ba4149ed618d96e83ccb98b7c9e061`

### Fix-round concerns

- The seed list is intentionally narrow. New fuzzy team spellings must be explicitly reviewed and added to `team_alias_allowlist.json`; they must not be inferred from `team_mappings.json`.
- `bundesliga_2` is the chosen canonical for `2. Bundesliga`; the report deliberately preserves `Bundesliga 2` under `nemacka_2` to honor the earlier mapping requirement.
- The pre-existing Mypy untyped-function notes remain informational; Mypy reports no issues.

## Fix round 2 — consolidated German tier-two mapping

**Base commit:** `4141848c19ba4149ed618d96e83ccb98b7c9e061`  
**Status:** DONE_WITH_CONCERNS

### Final state of the two keys

`config/league_mappings.json` now has one canonical owner for every German tier-two variation:

```json
"bundesliga_2": [
    "Bundesliga 2",
    "2. Bundesliga",
    "Germany 2",
    "Njemacka 2",
    "Njemačka 2",
    "Nemacka 2",
    "Njemacka - 2. Bundesliga",
    "Njemačka - 2. Bundesliga"
]
```

The `nemacka_2` key is deleted. No German tier-two name remains under a second canonical ID. The ambiguous raw short name `Premijer Liga` was removed from both `premier_liga_bih` and `premier_league`; the existing normalizer generic bypass continues to classify that short name as `premijer liga` rather than assigning it to either country.

### Duplicates found and fixed

The required whole-file regression scan was added to `tests/test_normalizer.py`. Before the mapping edits, its RED output found this cleaned-name collision:

```text
'premijer liga': ['premier_league', 'premier_liga_bih']
```

That collision was fixed by removing the ambiguous short mapping entry from both canonical lists. The review-identified German tier-two overlap was also consolidated completely; the following cleaned/raw variation families now belong only to `bundesliga_2`:

```text
bundesliga 2
2. bundesliga
germany 2
njemacka 2
njemačka 2
njemacka - 2. bundesliga
njemačka - 2. bundesliga
```

After the fixes, the same scan reports:

```text
duplicates={}
```

No other cleaned league name maps to multiple canonical IDs.

### Covering test file

`tests/test_normalizer.py` now includes:

- `test_german_tier_two_has_one_reachable_canonical_id`, asserting `2. Bundesliga -> bundesliga_2`;
- `test_league_mappings_have_no_cleaned_name_collisions`, which reads `config/league_mappings.json`, applies the normalizer’s cleaning function to every variation, and fails if any cleaned name has more than one canonical owner.

The existing BiH Premier Liga, Portuguese Primera Liga, and Vtora Liga tests remain in the same file and continue to pass.

### Fix-round TDD RED

Command run immediately after adding the collision test:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_normalizer.py::test_league_mappings_have_no_cleaned_name_collisions -v
```

Full output before the mapping fix:

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\\Users\\harun\\OneDrive\\Documenti\\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 1 item

tests\\test_normalizer.py F                                               [100%]

================================== FAILURES ===================================
_____________ test_league_mappings_have_no_cleaned_name_collisions _____________

    def test_league_mappings_have_no_cleaned_name_collisions():
        mapping_path = Path(__file__).parents[1] / "config" / "league_mappings.json"
        mappings = json.loads(mapping_path.read_text(encoding="utf-8"))
        normalizer = TeamNormalizer()
        owners_by_cleaned: dict[str, set[str]] = {}

        for canonical_id, variations in mappings.items():
            if canonical_id.startswith("_"):
                continue
            for variation in variations:
                cleaned = normalizer._full_clean(variation)
                owners_by_cleaned.setdefault(cleaned, set()).add(canonical_id)

        duplicates = {
            cleaned: sorted(canonical_ids)
            for cleaned, canonical_ids in owners_by_cleaned.items()
            if len(canonical_ids) > 1
        }
>       assert not duplicates, f"cleaned league names map to multiple canonical ids: {duplicates}"
E       AssertionError: cleaned league names map to multiple canonical ids: {'premijer liga': ['premier_league', 'premier_liga_bih']}
E
E         assert not {'premijer liga': ['premier_league', 'premier_liga_bih']}

tests\\test_normalizer.py:77: AssertionError
=========================== short test summary info ============================
FAILED tests/test_normalizer.py::test_league_mappings_have_no_cleaned_name_collisions
1 failed in 0.86s
```

### Fix-round final verification

Focused normalizer command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_normalizer.py -v
```

Full output (exit code 0):

```text
============================= test session starts =============================
platform win32 -- Python 3.11.15, pytest-8.4.1, pluggy-1.6.0
rootdir: C:\\Users\\harun\\OneDrive\\Documenti\\surebetmuse12
configfile: pyproject.toml
plugins: anyio-4.14.2
collected 9 items

tests\\test_normalizer.py .........                                       [100%]

============================== 9 passed in 0.84s ==============================
```

Full suite command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q
```

Full output (exit code 0):

```text
........................................................................ [ 48%]
........................................................................ [ 96%]
.....                                                                    [100%]
```

Ruff command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/ruff.exe" check .
```

Full output (exit code 0):

```text
All checks passed!
```

Mypy command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/mypy.exe" .
```

Full output (exit code 0):

```text
engine\\normalizer.py:132: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:133: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:134: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:135: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
engine\\normalizer.py:136: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\\test_normalizer.py:63: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\\base.py:109: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
scrapers\\base.py:110: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
tests\\test_scraper_common.py:68: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 41 source files
```

The Mypy notes are informational untyped-function notes; there are no type errors.

Final state inspection command:

```text
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -c "import json; from engine.normalizer import TeamNormalizer; d=json.load(open('config/league_mappings.json',encoding='utf-8')); n=TeamNormalizer(); owners={}; [owners.setdefault(n._full_clean(v),set()).add(k) for k,vs in d.items() if not k.startswith('_') for v in vs]; dup={k:sorted(v) for k,v in owners.items() if len(v)>1}; print('bundesliga_2='+json.dumps(d['bundesliga_2'],ensure_ascii=True)); print('nemacka_2_present='+str('nemacka_2' in d)); print('duplicates='+json.dumps(dup,ensure_ascii=True,sort_keys=True))"
```

Full output (exit code 0):

```text
bundesliga_2=["Bundesliga 2", "2. Bundesliga", "Germany 2", "Njemacka 2", "Njema\\u010dka 2", "Nemacka 2", "Njemacka - 2. Bundesliga", "Njema\\u010dka - 2. Bundesliga"]
nemacka_2_present=False
duplicates={}
```

### Fix-round 2 concerns

- `bundesliga_2` is now the sole canonical owner of all German tier-two variants; callers that previously expected the `nemacka_2` ID must use the corrected canonical.
- The regression test intentionally uses the normalizer’s internal cleaning routine so it detects collisions before the last-write-wins reverse map can hide them.

### Fix-round 2 commit

Commands:

```text
git add config/league_mappings.json tests/test_normalizer.py
git diff --cached --check
git commit -m "fix(mapping): consolidate German tier-two league mappings"
```

Commit output:

```text
[master c7c2f25] fix(mapping): consolidate German tier-two league mappings
 2 files changed, 32 insertions(+), 12 deletions(-)
```

**Fix-round 2 commit:** `c7c2f25f8336f0e4e8088aa86927b7823adc3382`

This supersedes the round-1 statement that `Bundesliga 2` remained under `nemacka_2`; the final state is now the single `bundesliga_2` owner shown above.

