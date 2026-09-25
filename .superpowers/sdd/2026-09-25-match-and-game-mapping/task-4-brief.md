### Task 4: Create the per-book market registry and wire parsers to it

**Files:**
- Create: `config/bookmaker_markets.json`
- Create: `engine/market_registry.py`
- Modify: `scrapers/common.py:298-374` (`parse_nsoft_bets` reads the registry for NSoft books), `scrapers/mbet.py` (`_resolve_mbet_market`), `scrapers/wwin.py`, `scrapers/sportplus.py`, `scrapers/premier_kladionica.py`, `scrapers/evlbet.py`, `scrapers/mozzartbet.py`, `scrapers/betole.py` (each parser looks up IDs via the registry)
- Test: `tests/test_market_registry.py` (create)

**Interfaces:**
- Consumes: `config/bookmaker_markets.json` (new), existing `Market`, `MarketType`, `OddsValue`.
- Produces:
  - `class MarketRegistry` with `__init__(self, path: str = REGISTRY_PATH)`, `lookup(self, bookmaker: str, mode: str, source_id: int | str) -> MarketSpec | None`, `ids_for(self, bookmaker: str, mode: str, market_type: MarketType) -> set[int | str]`, `unmapped` counter.
  - `class MarketSpec` (dataclass): `bookmaker: str`, `mode: str`, `market_type: MarketType`, `ids: set[int | str]`, `labels: set[str]`, `min_legs: int = 3`, `line: float | None = None`, `settlement: str = "full_time"`.
  - Module-level `MARKET_REGISTRY = MarketRegistry()` for import.
  - `unmapped_markets: dict[str, int]` keyed by `f"{bookmaker}:{source_id}"`, incremented by `record_unmapped(bookmaker, source_id)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_market_registry.py`:

```python
"""Market registry: one source of truth for per-book market IDs."""
import json

import pytest

from engine.market_registry import MarketRegistry, record_unmapped, unmapped_markets
from models.schemas import MarketType


def test_registry_loads_and_looks_up_mdshop_1x2():
    r = MarketRegistry()
    spec = r.lookup("mdshop", "prematch", 135)
    assert spec is not None
    assert spec.market_type == MarketType.MATCH_RESULT
    assert spec.settlement == "full_time"


def test_registry_looks_up_admiralbet_bookmaker_specific_id():
    r = MarketRegistry()
    spec = r.lookup("admiralbet", "prematch", 1639)
    assert spec is not None
    assert spec.market_type == MarketType.MATCH_RESULT


def test_registry_distinguishes_prematch_from_live_ids():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 135) is not None
    assert r.lookup("mdshop", "live", 135) is None
    assert r.lookup("mdshop", "live", 6) is not None


def test_registry_rejects_unmapped_id():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 99999) is None


def test_every_enabled_book_has_prematch_and_live_1x2():
    from config.settings import BOOKMAKERS
    r = MarketRegistry()
    for bid, cfg in BOOKMAKERS.items():
        if not cfg.get("enabled"):
            continue
        for mode in ("prematch", "live"):
            spec = r.lookup(bid, mode, _first_id(r, bid, mode))
            if spec is None:
                pytest.fail(f"{bid}/{mode} has no 1X2 entry")


def _first_id(r, bid, mode):
    ids = r.ids_for(bid, mode, MarketType.MATCH_RESULT)
    assert ids, f"{bid}/{mode} missing 1X2"
    return sorted(ids)[0]


def test_unknown_id_is_recorded_not_silently_dropped():
    from engine.market_registry import record_unmapped
    record_unmapped("mdshop", 424242)
    assert "mdshop:424242" in unmapped_markets
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.market_registry'`.

- [ ] **Step 3: Create the registry file**

Create `config/bookmaker_markets.json` with the following content (only enabled books):

```json
{
  "mdshop": {
    "prematch": {
      "1x2":            { "ids": [135],       "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [152],       "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [151],       "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [137,138],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [137,138],   "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [137,138],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": [6],         "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": [18,42],     "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": [995],       "labels": ["GG","NG"], "min_legs": 2 },
      "over_under_1_5": { "ids": [22,28],     "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [22,28],     "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [22,28],     "line": 3.5, "min_legs": 2 }
    }
  },
  "admiralbet": {
    "prematch": {
      "1x2":            { "ids": [1639],      "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [152],       "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [151],       "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [137,138],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [137,138],   "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [137,138],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": [6],         "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": [18,42],     "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": [995],       "labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "wwin": {
    "prematch": {
      "1x2":            { "ids": [95],        "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [6],         "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [3],         "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [11],        "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [11],        "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [11],        "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": [95],        "labels": ["1","X","2"], "min_legs": 3 }
    }
  },
  "premier_kladionica": {
    "prematch": {
      "1x2":            { "ids": ["UTAKMICA_1X2"], "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": ["UTAKMICA_DC"],  "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": ["OBA_DAJU_GOL"],  "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": ["ZBROJ_GOLOVA"], "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": ["ZBROJ_GOLOVA"], "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": ["ZBROJ_GOLOVA"], "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": ["LIVE_UTAKMICA"], "labels": ["1","X","2"], "min_legs": 3 },
      "btts":           { "ids": ["LIVE_OBA_DAJU_GOL"], "labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "mbet": {
    "prematch": {
      "1x2":            { "ids": ["ofb:fs"],   "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": ["ofb:dc"],   "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": ["ofb:gg"],   "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": ["ofb:tg"],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": ["ofb:tg"],   "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": ["ofb:tg"],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": ["lfb:ft"],   "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": ["lfb:dc"],   "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": ["lfb:bttsny"],"labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "sportplus": {
    "prematch": {
      "1x2":            { "ids": [1],         "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [1],         "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [6],         "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [800,802],   "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [768,800,802], "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [800,802],   "line": 3.5, "min_legs": 2 }
    },
    "live": {
      "1x2":            { "ids": ["POBJEDNIK"], "labels": ["1","X","2"], "min_legs": 3 },
      "double_chance":  { "ids": ["DVOSTRUKA_PRILIKA"], "labels": ["1X","12","X2"], "min_legs": 2 },
      "btts":           { "ids": ["OBA_DAJU_GOL"], "labels": ["GG","NG"], "min_legs": 2 }
    }
  },
  "evlbet": {
    "prematch": {
      "1x2":            { "ids": ["12005"],    "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" }
    },
    "live": {}
  },
  "betole": {
    "prematch": {
      "1x2":            { "ids": [1,2,3],     "labels": ["1","X","2"], "min_legs": 3, "settlement": "full_time" },
      "double_chance":  { "ids": [7,8,9],     "labels": ["1X","12","X2"], "min_legs": 2, "settlement": "full_time" },
      "btts":           { "ids": [272,273],   "labels": ["GG","NG"], "min_legs": 2, "settlement": "full_time" },
      "over_under_1_5": { "ids": [242,21],    "line": 1.5, "min_legs": 2 },
      "over_under_2_5": { "ids": [24,22],     "line": 2.5, "min_legs": 2 },
      "over_under_3_5": { "ids": [25,219],    "line": 3.5, "min_legs": 2 }
    },
    "live": {}
  }
}
```

- [ ] **Step 4: Implement `engine/market_registry.py`**

```python
"""Per-bookmaker market registry — the single source of truth for market IDs."""

import json
import os
from dataclasses import dataclass, field

from models.schemas import MarketType

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_markets.json")
unmapped_markets: dict[str, int] = {}


def record_unmapped(bookmaker: str, source_id: int | str) -> None:
    key = f"{bookmaker}:{source_id}"
    unmapped_markets[key] = unmapped_markets.get(key, 0) + 1


@dataclass
class MarketSpec:
    bookmaker: str
    mode: str
    market_type: MarketType
    ids: set[int | str] = field(default_factory=set)
    labels: set[str] = field(default_factory=set)
    min_legs: int = 3
    line: float | None = None
    settlement: str = "full_time"


class MarketRegistry:
    def __init__(self, path: str = REGISTRY_PATH) -> None:
        self._index: dict[tuple[str, str, str], MarketSpec] = {}
        self._by_type: dict[tuple[str, str, str], set[int | str]] = {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for bookmaker, modes in data.items():
            if bookmaker.startswith("_"):
                continue
            for mode, markets in modes.items():
                for mtype_value, spec in markets.items():
                    mtype = MarketType(mtype_value)
                    ms = MarketSpec(
                        bookmaker=bookmaker, mode=mode, market_type=mtype,
                        ids=set(spec.get("ids", [])),
                        labels=set(spec.get("labels", [])),
                        min_legs=int(spec.get("min_legs", 3)),
                        line=spec.get("line"),
                        settlement=spec.get("settlement", "full_time"),
                    )
                    for sid in ms.ids:
                        self._index[(bookmaker, mode, str(sid))] = ms
                    self._by_type[(bookmaker, mode, mtype.value)] = ms.ids

    def lookup(self, bookmaker: str, mode: str, source_id: int | str) -> MarketSpec | None:
        return self._index.get((bookmaker, mode, str(source_id)))

    def ids_for(self, bookmaker: str, mode: str, market_type: MarketType) -> set[int | str]:
        return self._by_type.get((bookmaker, mode, market_type.value), set())
```

- [ ] **Step 5: Wire `parse_nsoft_bets` to the registry**

In `scrapers/common.py`, add a module-level lazy registry accessor and extend the signature:

```python
from engine.market_registry import MarketRegistry, record_unmapped

_NSOFT_REGISTRY: MarketRegistry | None = None


def _nsoft_registry() -> MarketRegistry:
    global _NSOFT_REGISTRY
    if _NSOFT_REGISTRY is None:
        _NSOFT_REGISTRY = MarketRegistry()
    return _NSOFT_REGISTRY


def parse_nsoft_bets(
    bets: list,
    extra_bet_types: dict[int, MarketType] | None = None,
    extra_ou_bet_ids: set[int] | None = None,
    base_bet_type_map: dict[int, MarketType] | None = None,
    base_ou_bet_ids: set[int] | None = None,
    bookmaker: str = "mdshop",
    mode: str = "prematch",
) -> list[Market]:
    registry = _nsoft_registry()
    # Registry-first resolution; fall back to the legacy maps only when the book
    # has no registry entry for this mode at all (keeps direct-call tests working).
    has_registry = bool(registry.ids_for(bookmaker, mode, MarketType.MATCH_RESULT))
    bet_type_map = {**(base_bet_type_map or NSOFT_BET_TYPE_MAP), **(extra_bet_types or {})}
    ou_bet_ids = (base_ou_bet_ids if base_ou_bet_ids is not None else NSOFT_OU_BET_IDS) | (extra_ou_bet_ids or set())
    markets: list[Market] = []
    for bet in bets:
        if not isinstance(bet, dict):
            continue
        btid = bet.get("betTypeId")
        if btid is None:
            continue
        raw_sbv = bet.get("sbv") or bet.get("sBV")
        sbv_val = None
        if raw_sbv is not None:
            try:
                sbv_val = float(raw_sbv)
            except (ValueError, TypeError):
                pass

        market_type: MarketType | None = None
        expected_labels: set[str] = set()
        required_line: float | None = None
        if has_registry:
            spec = registry.lookup(bookmaker, mode, btid)
            if spec is None:
                record_unmapped(bookmaker, btid)
                continue
            market_type = spec.market_type
            expected_labels = set(spec.labels)
            required_line = spec.line
            if required_line is not None and sbv_val != required_line:
                continue
        else:
            market_type = bet_type_map.get(btid)
            if market_type is None and btid in ou_bet_ids and sbv_val is not None:
                market_type = {
                    1.5: MarketType.OVER_UNDER_1_5,
                    2.5: MarketType.OVER_UNDER_2_5,
                    3.5: MarketType.OVER_UNDER_3_5,
                }.get(sbv_val)
            if market_type is None:
                continue
            expected_labels = _MARKET_LABEL_SETS.get(market_type, set())

        outcomes = bet.get("betOutcomes", [])
        if not outcomes:
            continue
        odds_values: list[OddsValue] = []
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            lbl = str(outcome.get("name") or outcome.get("outcomeName") or "")
            odd_raw = outcome.get("odd") or outcome.get("odds") or outcome.get("value")
            if not lbl:
                continue
            try:
                odd_val = float(odd_raw) if odd_raw is not None else 0.0
            except (ValueError, TypeError):
                continue
            if odd_val < 1.01:
                continue
            norm_label = normalize_outcome(lbl, market_type)
            if norm_label in expected_labels:
                odds_values.append(OddsValue(label=norm_label, value=odd_val))

        actual = {o.label for o in odds_values}
        min_legs = 2 if market_type == MarketType.DOUBLE_CHANCE else len(expected_labels)
        valid = len(actual) >= min_legs and actual.issubset(expected_labels)
        if valid:
            markets.append(Market(market_type=market_type, odds=odds_values))
    return markets
```

Callers pass their own bookmaker: `mdshop.py:164` uses `parse_nsoft_bets(bets, bookmaker="mdshop", mode="live" if live else "prematch")`; `admiralbet.py:62` uses `parse_nsoft_bets(bets, bookmaker="admiralbet", mode="live" if live else "prematch")` and no longer needs `extra_bet_types={1639: ...}` because the registry already carries `1639` for Admiralbet.

- [ ] **Step 6: Run tests to verify**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_registry.py tests/test_market_mapping.py -v`
Expected: PASS for both files. The existing `test_market_mapping.py` tests that call `parse_nsoft_bets(bets)` with the default `bookmaker="mdshop"` must still pass because `135/136/148/...` resolve correctly through the registry (and the excluded IDs are absent from it, producing no markets).

- [ ] **Step 7: Commit**

```bash
git add config/bookmaker_markets.json engine/market_registry.py scrapers/common.py scrapers/mdshop.py scrapers/admiralbet.py tests/test_market_registry.py
git commit -m "feat(mapping): add per-book market registry as single source of truth, record unmapped IDs"
```

---

