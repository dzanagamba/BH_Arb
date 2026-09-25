### Task 5: Add deep-link builders and per-book declaration

**Files:**
- Create: `config/bookmaker_deeplinks.json`
- Modify: `scrapers/common.py` (add `build_event_url(bookmaker, event_id, base_url, live)`), `config/settings.py` (add `DEEP_LINK_CONFIG` path)
- Modify: each scraper to set `Match.event_id` and `Match.deep_link_verified` (initially `False`, filled by the on-demand check)
- Test: `tests/test_deeplinks.py` (create)

**Interfaces:**
- Consumes: `Match.event_id`, `Match.deep_link_verified` from Task 1.
- Produces:
  - `config/bookmaker_deeplinks.json` shape: `{"mdshop": {"supports_event_id": true, "template": "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event={event_id}"}, "wwin": {"supports_event_id": false, "note": "no per-event URL exposed"}}`.
  - `build_event_url(bookmaker: str, event_id: str, base_url: str, live: bool = False) -> str` in `scrapers/common.py` — returns the templated per-event URL when `supports_event_id` is true, else the base URL.

- [ ] **Step 1: Write the failing test**

Create `tests/test_deeplinks.py`:

```python
"""Deep-link builders and per-book event-id declarations."""
import json

from scrapers.common import build_event_url


def test_mdshop_builds_per_event_url():
    url = build_event_url("mdshop", "12345", "https://www.mdshop.ba")
    assert "event=12345" in url
    assert url.startswith("https://www.mdshop.ba/")


def test_wwin_declares_no_per_event_support():
    url = build_event_url("wwin", "12345", "https://wwin.ba")
    assert url == "https://wwin.ba/kladjenje/"


def test_unknown_book_returns_base_url():
    url = build_event_url("unknownbook", "1", "https://example.test")
    assert url == "https://example.test/"


def test_deeplink_config_is_valid_json():
    with open("config/bookmaker_deeplinks.json", encoding="utf-8") as f:
        data = json.load(f)
    assert "mdshop" in data
    assert data["mdshop"]["supports_event_id"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_event_url'`.

- [ ] **Step 3: Create `config/bookmaker_deeplinks.json`**

```json
{
  "mdshop":       { "supports_event_id": true,  "template": "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event={event_id}" },
  "admiralbet":   { "supports_event_id": true,  "template": "https://www.admiralbet.ba/sport-prematch?sport=Fudbal&event={event_id}" },
  "wwin":         { "supports_event_id": false, "template": "https://wwin.ba/kladjenje/", "note": "Betradar feed exposes brid but no per-event route" },
  "mbet":         { "supports_event_id": false, "template": "https://www.mbet.ba/", "note": "SPA has no stable per-event URL" },
  "sportplus":    { "supports_event_id": false, "template": "https://www.sportplus.ba/prematch/betting", "note": "SPA uses in-page selection" },
  "evlbet":       { "supports_event_id": false, "template": "https://evlbet.com/", "note": "flat feed has Id but no public route" },
  "premier_kladionica": { "supports_event_id": false, "template": "https://www.premier-kladionica.com/ponuda/", "note": "no per-event route" },
  "betole":       { "supports_event_id": false, "template": "https://www.betole.ba/ba/sport/S", "note": "no per-event route" }
}
```

- [ ] **Step 4: Implement `build_event_url`**

Append to `scrapers/common.py`:

```python
_DEEPLINK_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_deeplinks.json")
_deeplink_cache: dict | None = None


def _load_deeplink_config() -> dict:
    global _deeplink_cache
    if _deeplink_cache is None:
        try:
            with open(_DEEPLINK_CONFIG_PATH, encoding="utf-8") as f:
                _deeplink_cache = json.load(f)
        except (OSError, ValueError):
            _deeplink_cache = {}
    return _deeplink_cache


def build_event_url(bookmaker: str, event_id: str, base_url: str, live: bool = False) -> str:
    """Build a per-event URL from the declared template, or the base URL if unsupported."""
    cfg = _load_deeplink_config().get(bookmaker, {})
    template = cfg.get("template", f"{base_url}/")
    if not cfg.get("supports_event_id") or not event_id:
        return template
    return template.format(event_id=event_id)
```

Add `import json` and `import os` to the top of `scrapers/common.py` (currently only `from datetime import UTC, datetime` is imported).

- [ ] **Step 5: Run tests**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_deeplinks.py tests/test_urls.py -v`
Expected: PASS for both files (the existing URL tests must keep passing because `_collect_match_urls` still uses `Match.url` / `MATCH_URL_TEMPLATES`).

- [ ] **Step 6: Commit**

```bash
git add config/bookmaker_deeplinks.json scrapers/common.py tests/test_deeplinks.py
git commit -m "feat(mapping): add per-book deep-link config and build_event_url"
```

---

