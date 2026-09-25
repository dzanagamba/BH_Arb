### Task 3: Integrate the gate into the matcher and tighten hard gates

**Files:**
- Modify: `engine/matcher.py:1-66` (remove `EUROPEAN_COMPATIBLE_LEAGUES` bridging, add gate import), `engine/matcher.py:104-209` (apply gate, set status/evidence)
- Modify: `config/league_mappings.json` (fix provably wrong entries: `argentine_primera` should not contain `Argentina 2`/`Primera B Nacional`; `bugarian_first_league` should not be the canonical for `Bugarska 2`; `bundesliga_2` vs `nemacka_2` overlap)
- Create: `config/league_equivalences.json`
- Test: `tests/test_matcher_certified.py` (create)

**Interfaces:**
- Consumes: `CertaintyGate`, `GateResult` from Task 2; `MatchEvidence` from Task 1.
- Produces: `MatchMatcher.group_matches` now returns groups with `status` and `evidence` set; groups that fail the gate are dropped (not returned as multi-book groups). `config/league_equivalences.json` shape: `{"pairs": [["europa_league","conference_league"]]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_matcher_certified.py`:

```python
"""Matcher integration: only gate-passing groups are returned."""
from datetime import datetime, timedelta

from engine.matcher import MatchMatcher
from models.schemas import Market, MarketType, Match, OddsValue

K = datetime(2026, 9, 25, 18, 0)


def _m(bookmaker, home, away, league, kickoff=K, event_id="", link_ok=True):
    return Match(
        bookmaker=bookmaker, home_team=home, away_team=away, league=league, kickoff=kickoff,
        url=f"https://example.test/{bookmaker}/{event_id}" if event_id else "",
        event_id=event_id, deep_link_verified=link_ok,
        markets=[Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0), OddsValue(label="X", value=3.0), OddsValue(label="2", value=3.0)])],
    )


def test_verified_group_returned_with_evidence():
    a = _m("mdshop", "Željezničar", "Sarajevo", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Zeljeznicar", "FK Sarajevo", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 1
    assert groups[0].status == "verified"
    assert any(e.rule == "team_identity" for e in groups[0].evidence)


def test_group_with_unresolved_team_is_not_returned():
    a = _m("mdshop", "Alpha FC", "Beta United", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Gamma SC", "Delta Club", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 0


def test_europa_conference_merge_only_via_declared_equivalence():
    a = _m("mdshop", "Midtjylland", "Rijeka", "Liga Evrope", event_id="1")
    b = _m("mbet", "Midtjylland", "Rijeka", "Liga Konferencija", event_id="2")
    import engine.matcher as matcher_mod
    assert not hasattr(matcher_mod, "EUROPEAN_COMPATIBLE_LEAGUES"), "blanket European merging must be removed"
    # With the shipped league_equivalences.json this may group, but only as `verified`
    # when every hard gate (kickoff, teams, link) also passes.
    groups = MatchMatcher().group_matches([a, b])
    for g in groups:
        assert g.status == "verified"
        assert any(e.rule == "league_identity" and e.league_pair for e in g.evidence)


def test_kickoff_gap_of_16_minutes_is_not_verified():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=K + timedelta(minutes=16), event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert all(g.status != "verified" for g in groups)


def test_same_teams_three_hours_apart_never_group():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1")
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", kickoff=K + timedelta(hours=3), event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    assert len(groups) == 0


def test_unverified_link_yields_suggested_or_dropped_not_verified():
    a = _m("mdshop", "Sarajevo", "Zeljeznicar", "BiH - Premier Liga", event_id="1", link_ok=False)
    b = _m("mbet", "Sarajevo", "Zeljeznicar", "Premijer Liga BiH", event_id="2")
    groups = MatchMatcher().group_matches([a, b])
    for g in groups:
        assert g.status != "verified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py -v`
Expected: FAIL — `test_verified_group_returned_with_evidence` fails because `MatchGroup` has no `status`/`evidence` set by the matcher (currently the group is `suggested` by default, and `test_group_with_unresolved_team_is_not_returned` may pass only by accident of fuzzy thresholds).

- [ ] **Step 3: Write minimal implementation**

First, fix the provably wrong league mappings. In `config/league_mappings.json`:
- Remove `"Argentina 2"`, `"ARGENTINA 2"`, and `"Primera B Nacional"` from `argentine_primera` and add a new key:
```json
    "argentine_primera_b_nacional": [
        "Argentina 2", "ARGENTINA 2", "Primera B Nacional", "Primera Nacional"
    ],
```
- Remove `"Bugarska 2"`-style entries: the current `bugarian_first_league` contains only tier-1 names. Add:
```json
    "bugarian_second_league": [
        "Bugarska 2", "BULGARIA 2", "bulgaria 2", "Vtora Liga", "vtora liga"
    ],
```
- `bundesliga_2` currently lists `Bundesliga 2` which is the same as `nemacka_2`. Keep `bundesliga_2` for German `2. Bundesliga` and add `"Bundesliga 2"` to `nemacka_2` only (already present), removing it from `bundesliga_2`.

Then create `config/league_equivalences.json`:
```json
{
  "pairs": [
    ["europa_league", "conference_league"]
  ]
}
```

Now modify `engine/matcher.py`:
1. Remove the `EUROPEAN_COMPATIBLE_LEAGUES` constant and its use (lines 58-63, 145-149, 237-239).
2. Add at the top of the imports: `from engine.certainty import CertaintyGate, GateResult`.
3. In `MatchMatcher.__init__`, load equivalences and build a gate:
```python
import json, os
_LEAGUE_EQUIV_FILE = os.path.join(os.path.dirname(__file__), "..", "config", "league_equivalences.json")

def __init__(self):
    self.normalizer = TeamNormalizer()
    self._equivalences: set[tuple[str, str]] = set()
    try:
        with open(_LEAGUE_EQUIV_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for pair in data.get("pairs", []):
            if len(pair) == 2:
                self._equivalences.add((pair[0], pair[1]))
    except (OSError, ValueError):
        logger.warning("league_equivalences.json not found or invalid — no cross-league merging")
    self.gate = CertaintyGate(league_equivalences=self._equivalences)
```
4. In `group_matches`, after computing `best_group` and before appending, apply the gate. Replace the confidence check at line 164 with:
```python
            if best_group and best_conf >= GROUP_MIN_CONFIDENCE:
                gate_result = self.gate.evaluate(match, best_group)
                if gate_result.status == "verified":
                    match_to_add = swap_match_teams_and_odds(match) if gate_result.is_swapped else match
                    best_group.matches.append(match_to_add)
                    best_group.evidence.extend(gate_result.evidence)
                    ... existing generic-league upgrade and kickoff upgrade ...
                else:
                    logger.debug(
                        f"⛔ GATE REJECTED [{match.bookmaker}] '{match.home_team}' vs '{match.away_team}' "
                        f"→ reasons={gate_result.reasons}"
                    )
                    # do not append; the match stays a singleton
```
5. When a new group is created, set `status="suggested"` and seed `evidence` with a rule-stage note. When a group reaches 2+ verified bookmakers, set `status="verified"`.
6. In the final multi-book filter, only keep groups with `status == "verified"` and ≥2 distinct bookmakers.

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_matcher_certified.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Run the full suite**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest -q`
Expected: `tests/test_matcher.py` will need updates because several of its fixtures build matches with **no `event_id` and no `url`**, which the gate flags `no_event_link` → `suggested`, so those groups are no longer returned. Update the shared `_match()` helper in `tests/test_matcher.py` to accept and set `event_id` + `deep_link_verified=True` (e.g. `event_id=f"{bookmaker}-{home}"`, `url=f"https://example.test/{bookmaker}"`), then assert `groups[0].status == "verified"` in the grouping tests and keep the U21/Women tests asserting `len(groups) == 0`. All tests must pass.

- [ ] **Step 6: Commit**

```bash
git add engine/matcher.py config/league_mappings.json config/league_equivalences.json tests/test_matcher_certified.py tests/test_matcher.py
git commit -m "feat(mapping): integrate certainty gate into matcher, remove blanket European merging, fix wrong league entries"
```

---

