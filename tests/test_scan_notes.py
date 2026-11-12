"""M8-3: a guard action is a scan note, not a bookmaker failure.

The operator's 2026-11-12 dashboard said "Some bookmakers failed: 7 surebet(s)
dropped: a leg was a price outlier" — nothing had failed, and the price guard
had done its job. The status now carries `notes` next to `errors`, the guard and
odds-age messages go to notes, and the banner only reports what actually failed.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from models.schemas import ScanStatus
from server import api
from server.app import app
from server.auth import ApiKeyStore

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
API_PY = (ROOT / "server" / "api.py").read_text(encoding="utf-8")


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(
        api, "api_key_store", ApiKeyStore(str(tmp_path / "api_keys.json"))
    )
    monkeypatch.setattr(api, "API_KEY", "")
    return TestClient(app)


def test_scan_status_ships_notes_next_to_errors():
    status = ScanStatus(errors=["SportPlus: blocked"], notes=["2 surebets dropped"])
    payload = status.model_dump(mode="json")
    assert payload["errors"] == ["SportPlus: blocked"]
    assert payload["notes"] == ["2 surebets dropped"]


def test_the_status_endpoint_exposes_notes(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "scan_status", ScanStatus(notes=["guard note"]))
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/status?mode=prematch").json()

    assert body["notes"] == ["guard note"]


def test_the_guard_and_age_messages_are_notes_and_book_failures_are_errors():
    """Source pin: the two protective messages must not fill the error list."""
    flat = " ".join(API_PY.split())

    assert 'status.notes.append(f"Odds age spread {spread:.0f}s' in flat
    guard_call = (
        'status.notes.append( f"{len(price_dropped)} surebet(s) dropped:'
        ' a leg was a price outlier" )'
    )
    assert guard_call in flat
    assert 'status.errors.append( f"{len(price_dropped)}' not in flat
    assert 'status.errors.append(f"Odds age spread' not in flat
    # A book that could not be read is still an error.
    assert "status.errors.append(error_msg)" in flat
    assert "status.notes = []" in flat


def test_the_dashboard_reads_notes_and_stops_calling_them_bookmaker_failures():
    assert "Some bookmakers failed" not in APP_JS
    assert "Some bookmakers failed" not in (
        ROOT / "frontend" / "js" / "i18n.js"
    ).read_text(encoding="utf-8")
    assert "status.notes" in APP_JS
    assert "Scan finished with problems: {items}" in APP_JS
