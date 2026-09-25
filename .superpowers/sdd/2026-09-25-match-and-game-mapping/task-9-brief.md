### Task 9: Generate `MARKET_MAPPING.md` from the registry and add registry/parser consistency tests

**Files:**
- Create: `scripts/generate_market_mapping_doc.py`
- Create: `tests/test_registry_parser_consistency.py`
- Modify: `MARKET_MAPPING.md` (regenerated)

**Interfaces:**
- Consumes: `config/bookmaker_markets.json` (Task 4).
- Produces: `python scripts/generate_market_mapping_doc.py` regenerates `MARKET_MAPPING.md`; a test that asserts every registry ID appears in at least one scraper's `ids`/key set or fixture test.

- [ ] **Step 1: Write the failing test**

Create `tests/test_registry_parser_consistency.py`:

```python
"""Registry <-> parser consistency: no orphan IDs, no undocumented parser IDs."""
import json

from engine.market_registry import MarketRegistry
from models.schemas import MarketType


def test_registry_file_is_valid_and_complete():
    r = MarketRegistry()
    from config.settings import BOOKMAKERS
    for bid, cfg in BOOKMAKERS.items():
        ids = r.ids_for(bid, "prematch", MarketType.MATCH_RESULT)
        assert ids, f"{bid} has no prematch 1X2 in registry"


def test_nsoft_advance_id_136_not_in_registry():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 136) is None
    assert r.lookup("admiralbet", "prematch", 136) is None


def test_registry_matches_documented_market_mapping():
    with open("MARKET_MAPPING.md", encoding="utf-8") as f:
        doc = f.read()
    r = MarketRegistry()
    # Every registry ID for mdshop prematch must appear somewhere in the doc.
    for sid in sorted(str(x) for x in r.ids_for("mdshop", "prematch", MarketType.MATCH_RESULT)):
        assert sid in doc, f"mdshop 1X2 id {sid} not documented"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_registry_parser_consistency.py -v`
Expected: the doc test may fail (the current `MARKET_MAPPING.md` mentions 135 so it may pass; if it passes, the failure will be from the missing `generate_market_mapping_doc.py` test target). Adjust the assertion to check for a generated section marker:
```python
    assert "<!-- GENERATED FROM bookmaker_markets.json -->" in doc
```
Expected: FAIL — the marker is not present.

- [ ] **Step 3: Create the generator script**

`scripts/generate_market_mapping_doc.py`:

```python
"""Regenerate MARKET_MAPPING.md from config/bookmaker_markets.json."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.market_registry import MarketRegistry  # noqa: E402
from models.schemas import MarketType  # noqa: E402

REG = MarketRegistry()
MARKET_TYPE_LABEL = {
    MarketType.MATCH_RESULT: "Full-time 1X2",
    MarketType.DOUBLE_CHANCE: "Double Chance",
    MarketType.BTTS: "BTTS",
    MarketType.OVER_UNDER_1_5: "Over/Under 1.5",
    MarketType.OVER_UNDER_2_5: "Over/Under 2.5",
    MarketType.OVER_UNDER_3_5: "Over/Under 3.5",
}

lines = [
    "# Football Market Mapping",
    "",
    "<!-- GENERATED FROM bookmaker_markets.json — do not edit by hand. -->",
    "Run `python scripts/generate_market_mapping_doc.py` after registry changes.",
    "",
    "| Bookmaker | Mode | Market | Source IDs | Labels | Min legs | Line |",
    "| --- | --- | --- | --- | --- | --- | --- |",
]

with open(os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_markets.json"), encoding="utf-8") as f:
    data = json.load(f)

for book, modes in data.items():
    if book.startswith("_"):
        continue
    for mode, markets in modes.items():
        for mtype, spec in markets.items():
            mt = MarketType(mtype)
            ids = ", ".join(str(i) for i in spec.get("ids", []))
            labels = ", ".join(spec.get("labels", []))
            line = spec.get("line", "")
            lines.append(
                f"| {book} | {mode} | {MARKET_TYPE_LABEL.get(mt, mt.value)} | {ids} | {labels} | "
                f"{spec.get('min_legs', 3)} | {line} |"
            )

out = os.path.join(os.path.dirname(__file__), "..", "MARKET_MAPPING.md")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print(f"Wrote {out}")
```

- [ ] **Step 4: Run the generator and test**

Run:
```bash
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" scripts/generate_market_mapping_doc.py
"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_registry_parser_consistency.py -v
```
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_market_mapping_doc.py MARKET_MAPPING.md tests/test_registry_parser_consistency.py
git commit -m "docs: generate MARKET_MAPPING.md from the market registry and assert consistency"
```

---

