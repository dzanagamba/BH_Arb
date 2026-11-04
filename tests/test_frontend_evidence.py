"""P1-1: the dashboard's bounded evidence drill-down is present and wired."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
JS = (REPO_ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
CSS = (REPO_ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")


def test_evidence_tab_and_panel_are_in_the_dashboard():
    assert 'id="evidence-tab"' in HTML
    assert 'data-tab="evidence"' in HTML
    assert 'data-tab-panel="evidence"' in HTML
    assert 'id="evidence-list"' in HTML
    assert 'id="evidence-detail"' in HTML


def test_evidence_list_uses_the_bounded_endpoints():
    assert "/api/groups?" in JS
    assert "/api/groups/${encodeURIComponent(groupId)}" in JS
    assert "EVIDENCE_PAGE_SIZE" in JS
    assert "data-action=\"evidence-open\"" in JS
    assert "data-action=\"evidence-close\"" in JS
    assert "evidence-prev" in JS and "evidence-next" in JS


def test_evidence_filter_changes_reload_the_first_page():
    assert "element.id === 'evidence-search'" in JS
    assert "element.id === 'evidence-status' || element.id === 'evidence-sport'" in JS
    assert "loadEvidence(true)" in JS


def test_evidence_layout_wraps_on_narrow_screens():
    assert ".evidence-head { display: flex" in CSS
    assert "flex-wrap: wrap" in CSS
    assert ".evidence-row" in CSS
