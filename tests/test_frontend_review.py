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
