"""P3-4: installable shell, static-only cache, language toggle and a11y hooks."""

from __future__ import annotations

import json
from pathlib import Path

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
SW = Path("frontend/sw.js").read_text(encoding="utf-8")
MANIFEST = json.loads(Path("frontend/manifest.webmanifest").read_text(encoding="utf-8"))
CSS = Path("frontend/css/style.css").read_text(encoding="utf-8")


def test_manifest_makes_the_app_installable():
    assert MANIFEST["name"]
    assert MANIFEST["start_url"] == "/"
    assert MANIFEST["display"] == "standalone"
    assert 'rel="manifest"' in HTML
    assert 'name="theme-color"' in HTML


def test_the_service_worker_never_caches_api_or_odds():
    assert "startsWith('/api/')" in SW
    assert "/api" not in " ".join(
        line for line in SW.splitlines() if "SHELL" in line or "addAll" in line
    )
    assert "network only" in SW.lower()


def test_offline_shell_does_not_become_a_stale_odds_layer():
    assert "caches.match('/index.html')" in SW
    assert "fetch(event.request)" in SW
    assert "stale" in SW.lower()


def test_main_regions_have_labels_and_live_regions():
    assert 'class="skip-link"' in HTML
    assert 'id="main"' in HTML
    assert 'aria-live="polite"' in HTML
    assert 'role="status"' in HTML
    assert ".skip-link:focus" in CSS


def test_the_language_toggle_persists_and_covers_main_labels():
    i18n = Path("frontend/js/i18n.js").read_text(encoding="utf-8")
    assert 'id="filter-language"' in HTML
    assert 'data-i18n="Surebets"' in HTML
    assert 'data-i18n="Scan now"' in HTML
    assert "window.I18N = {" in i18n
    assert '"Scan now": "Skeniraj sada"' in i18n
    assert "localStorage.setItem('language'" in JS
    assert "function applyLanguage" in JS
    assert "function tr(" in JS


def test_browser_alerts_are_permission_gated():
    assert 'data-action="enable-notifications"' in HTML
    assert "Notification.requestPermission" in JS
    assert "enableNotifications" in JS


def test_the_service_worker_is_registered_without_a_bundler():
    assert "navigator.serviceWorker.register('/sw.js')" in JS
    assert Path("frontend/sw.js").exists()


def test_the_server_serves_the_manifest_and_service_worker():
    """The files existed but were not routed, so the browser got a 404."""
    from fastapi.testclient import TestClient

    from server.app import app

    client = TestClient(app)
    manifest = client.get("/manifest.webmanifest")
    worker = client.get("/sw.js")

    assert manifest.status_code == 200
    assert manifest.json()["name"] == MANIFEST["name"]
    assert worker.status_code == 200
    assert worker.text == SW
    assert worker.headers["service-worker-allowed"] == "/"
