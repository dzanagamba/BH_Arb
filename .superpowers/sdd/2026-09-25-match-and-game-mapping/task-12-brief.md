### Task 12: On-demand deep-link verification endpoint

**Files:**
- Create: `scripts/verify_deeplinks.py`
- Modify: `server/api.py` (add `POST /api/verify-links` endpoint)
- Test: `tests/test_verify_links.py` (create)

**Interfaces:**
- Consumes: `build_event_url` (Task 5), `config/bookmaker_deeplinks.json`, Playwright.
- Produces: `POST /api/verify-links?bookmaker=<id>` → `{"bookmaker": "...", "checked": n, "verified": n, "failed": n, "details": [...]}`; updates `Match.deep_link_verified` in cached matches.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify_links.py`:

```python
"""Deep-link verification endpoint contract."""
from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


def test_verify_links_requires_bookmaker_param():
    r = client.post("/api/verify-links")
    assert r.status_code == 400


def test_verify_links_unknown_bookmaker_404():
    r = client.post("/api/verify-links?bookmaker=nosuchbook")
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py -v`
Expected: FAIL — route not found (405) or 404 for both cases.

- [ ] **Step 3: Implement the endpoint**

In `server/api.py`, add:
```python
@router.post("/verify-links")
async def verify_links(bookmaker: str, _auth: None = Depends(_require_api_key)):
    if bookmaker not in BOOKMAKERS:
        raise HTTPException(status_code=404, detail=f"Unknown bookmaker: {bookmaker}")
    from scrapers.common import build_event_url
    checked = verified = failed = 0
    details = []
    for m in cached_matches:
        if m.get("bookmaker") != bookmaker or not m.get("event_id"):
            continue
        url = build_event_url(bookmaker, m["event_id"], BOOKMAKERS[bookmaker]["base_url"])
        checked += 1
        # The actual Playwright navigation is done by scripts/verify_deeplinks.py;
        # this endpoint returns the URLs to check and records the result if already known.
        details.append({"event_id": m["event_id"], "url": url, "verified": m.get("deep_link_verified", False)})
        if m.get("deep_link_verified"):
            verified += 1
        else:
            failed += 1
    return {"bookmaker": bookmaker, "checked": checked, "verified": verified, "failed": failed, "details": details}
```

- [ ] **Step 4: Create the Playwright verification script**

`scripts/verify_deeplinks.py`:
```python
"""Open each per-event deep link and check the event ID appears in the page."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import BOOKMAKERS, USER_AGENT  # noqa: E402
from scrapers.base import launch_browser  # noqa: E402
from scrapers.common import build_event_url  # noqa: E402


async def verify(bookmaker: str) -> dict:
    p, browser, ctx = await launch_browser()
    page = await ctx.new_page()
    results = []
    try:
        with open(os.path.join("cache", "last_scan.json"), encoding="utf-8") as f:
            data = json.load(f)
        events = [m for m in data.get("matches", []) if m.get("bookmaker") == bookmaker and m.get("event_id")]
        for m in events[:20]:
            url = build_event_url(bookmaker, m["event_id"], BOOKMAKERS[bookmaker]["base_url"])
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(3000)
            body = await page.content()
            found = m["event_id"] in body
            results.append({"event_id": m["event_id"], "url": url, "found_in_page": found})
    finally:
        await browser.close()
        await p.stop()
    return {"bookmaker": bookmaker, "checked": len(results), "found": sum(1 for r in results if r["found_in_page"]), "results": results}


if __name__ == "__main__":
    books = sys.argv[1:] or list(BOOKMAKERS)
    for b in books:
        print(json.dumps(asyncio.run(verify(b)), ensure_ascii=False, indent=2))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_verify_links.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add server/api.py scripts/verify_deeplinks.py tests/test_verify_links.py
git commit -m "feat(mapping): add deep-link verification endpoint and Playwright checker"
```

---

