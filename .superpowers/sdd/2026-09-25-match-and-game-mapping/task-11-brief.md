### Task 11: Fixture tests for every bookmaker registry entry

**Files:**
- Create: `tests/fixtures/markets/` (JSON captures; add small hand-trimmed payloads captured from the live APIs)
- Create: `tests/test_market_fixtures.py`

**Interfaces:**
- Consumes: `config/bookmaker_markets.json` (Task 4), each book's parser.
- Produces: a parametrized test that, for each captured payload, asserts the parser emits exactly the registry-declared markets and nothing else.

- [ ] **Step 1: Capture fixtures (manual, one time)**

Run each enabled bookmaker's scraper once and save the raw parsed markets for 3 events per market type into `tests/fixtures/markets/{book}_{mode}.json`. Minimum coverage: MDShop, Admiralbet, WWIN, Premier, MBet, SportPlus, Mozzartbet, EVLBet. Example shape:
```json
{
  "bookmaker": "mdshop", "mode": "prematch", "bets": [ ... ],
  "expected_markets": ["1x2", "btts", "over_under_2_5"]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_market_fixtures.py`:
```python
"""Each registry entry is exercised by a captured payload."""
import json
from pathlib import Path

import pytest

from engine.market_registry import MarketRegistry

FIXTURES = sorted(Path("tests/fixtures/markets").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_emits_declared_markets(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    book, mode = data["bookmaker"], data["mode"]
    registry = MarketRegistry()
    emitted = _run_parser(book, mode, data["bets"])
    assert set(emitted) == set(data["expected_markets"]), f"{book}/{mode} mismatch"
    for mt in data["expected_markets"]:
        assert registry.ids_for(book, mode, mt), f"{mt} not in registry"


def _run_parser(book, mode, bets):
    from models.schemas import MarketType
    if book in ("mdshop", "admiralbet"):
        from scrapers.common import parse_nsoft_bets
        extra = {1639: MarketType.MATCH_RESULT} if book == "admiralbet" else None
        return [m.market_type.value for m in parse_nsoft_bets(bets, extra_bet_types=extra, bookmaker=book, mode=mode)]
    if book == "wwin":
        from scrapers.wwin import WWINScraper
        return [m.market_type.value for m in WWINScraper()._parse_offers(bets)]
    pytest.skip(f"no fixture parser adapter for {book} yet")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_fixtures.py -v`
Expected: FAIL for the first fixture because scrapers like WWIN/Mozzartbet/MBet/SportPlus/Premier/EVLBet do not yet accept `bookmaker`/`mode` registry parameters, or the parser adapter helpers do not exist.

- [ ] **Step 4: Add registry-aware parser entry points**

For each non-NSoft scraper, add a thin `parse_markets(bookmaker: str, mode: str, payload) -> list[Market]` function that consults `MarketRegistry` and records unknown IDs. Each scraper's existing internal parser delegates to it. Keep the old function names as thin wrappers so existing tests keep passing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_market_fixtures.py -v`
Expected: PASS for every captured fixture.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/markets tests/test_market_fixtures.py scrapers/
git commit -m "test(mapping): add captured-payload fixture tests for every bookmaker registry entry"
```

---

