### Task 8: Add the frontend Review tab and status badges

**Files:**
- Modify: `frontend/index.html` (add Review tab markup)
- Modify: `frontend/js/app.js` (add `loadCandidates`, `renderCandidates`, status badges)
- Modify: `frontend/css/style.css` (status badge styles)
- Test: `tests/test_frontend_review.py` (create, static-asset smoke test)

**Interfaces:**
- Consumes: `GET /api/candidates`, `POST /api/candidates/{id}/approve|reject` from Task 7.
- Produces: Review tab rendering pending candidates with approve/reject buttons; surebet cards show a `verified`/`suggested` badge.

- [ ] **Step 1: Write the failing test**

Create `tests/test_frontend_review.py`:

```python
"""Static smoke test: Review tab markup and JS hooks exist."""
from pathlib import Path

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")


def test_index_has_review_tab():
    assert 'id="review-tab"' in HTML
    assert 'id="candidates-list"' in HTML


def test_js_has_candidate_hooks():
    assert "loadCandidates" in JS
    assert "renderCandidates" in JS
    assert "/api/candidates" in JS
    assert "approveCandidate" in JS
    assert "rejectCandidate" in JS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v`
Expected: FAIL — `id="review-tab"` not found.

- [ ] **Step 3: Add the Review tab to `frontend/index.html`**

Insert after the existing results tabs (near the dust tab) a new tab button and panel:
```html
<button class="tab-btn" id="review-tab" data-tab="review">Review <span id="review-count" class="tab-count">0</span></button>
...
<div id="review-panel" class="tab-panel">
  <div id="candidates-list" class="candidates-list"><p class="empty-state">No pending candidates.</p></div>
</div>
```

- [ ] **Step 4: Add the JS in `frontend/js/app.js`**

Append:
```javascript
async function loadCandidates() {
  try {
    const r = await fetch("/api/candidates");
    const d = await r.json();
    renderCandidates(d.candidates || []);
  } catch (e) { console.error("candidates load failed", e); }
}

function renderCandidates(candidates) {
  const el = document.getElementById("candidates-list");
  const cnt = document.getElementById("review-count");
  if (cnt) cnt.textContent = candidates.length;
  if (!candidates.length) { el.innerHTML = '<p class="empty-state">No pending candidates.</p>'; return; }
  el.innerHTML = candidates.map(c => `
    <div class="candidate-card" data-id="${c.id}">
      <div class="candidate-teams">${c.home_team} vs ${c.away_team}</div>
      <div class="candidate-meta">${c.league} · ${c.kickoff || "unknown"} · ${c.bookmakers.join(" / ")}</div>
      <div class="candidate-reasons">${(c.rule_rejections || []).join(", ")}</div>
      <div class="candidate-ai">AI confidence: ${(c.ai_confidence * 100).toFixed(0)}% — ${c.ai_reason || ""}</div>
      <div class="candidate-actions">
        <button class="btn-approve" onclick="approveCandidate('${c.id}')">Approve</button>
        <button class="btn-reject" onclick="rejectCandidate('${c.id}')">Reject</button>
      </div>
    </div>`).join("");
}

async function approveCandidate(id) {
  await fetch(`/api/candidates/${id}/approve`, { method: "POST" });
  loadCandidates();
}

async function rejectCandidate(id) {
  await fetch(`/api/candidates/${id}/reject`, { method: "POST" });
  loadCandidates();
}

document.addEventListener("DOMContentLoaded", () => { loadCandidates(); setInterval(loadCandidates, 30000); });
```

- [ ] **Step 5: Add badge styles in `frontend/css/style.css`**

```css
.candidate-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 10px; }
.candidate-actions { display: flex; gap: 8px; margin-top: 8px; }
.btn-approve { background: #16a34a; color: #fff; border: none; border-radius: 4px; padding: 6px 14px; cursor: pointer; }
.btn-reject { background: #b71c1c; color: #fff; border: none; border-radius: 4px; padding: 6px 14px; cursor: pointer; }
.status-verified { color: #16a34a; font-weight: 600; }
.status-suggested { color: #d97706; font-weight: 600; }
.status-rejected { color: #b71c1c; font-weight: 600; }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `"C:/Users/harun/OneDrive/Documenti/claudesurebet/venv/Scripts/python.exe" -m pytest tests/test_frontend_review.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/js/app.js frontend/css/style.css tests/test_frontend_review.py
git commit -m "feat(frontend): add Review tab for pending match candidates and status badges"
```

---

