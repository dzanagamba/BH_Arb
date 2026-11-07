"""C-01: the FastAPI lifespan restores every persisted runtime store.

`_restore_state()` runs only inside the lifespan, so before this module no test
had ever executed its happy paths. Each test here writes a redirected state file
through the production writer (or the documented JSON shape), enters the
lifespan with `TestClient`, and asserts the store came back. The conftest
autouse fixture already redirects every path into ``tmp_path``; nothing here
touches ``config/generated`` or ``cache``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from models.schemas import ScanStatus
from server import api
from server import app as app_module
from server.app import app
from server.storage import Storage, default_storage_path


def _write_json(path: str, payload: object) -> None:
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def _now(offset_seconds: float = 0) -> str:
    value = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=offset_seconds)
    return value.isoformat()


def _fresh_matches_proof(event_id: str = "e1") -> dict:
    return {
        "verified": True,
        "checked_at": _now(),
        "url": f"https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/{event_id}",
    }


def test_the_lifespan_restores_bookmaker_and_market_toggles(monkeypatch):
    monkeypatch.setattr(
        api, "_bookmaker_enabled", {"mozzartbet": True, "mdshop": True}
    )
    monkeypatch.setattr(api, "_market_enabled", {"experimental_test_market": False})
    _write_json(
        api._BOOKMAKER_STATE_FILE,
        {"mozzartbet": False, "not_a_bookmaker": True},
    )
    _write_json(
        api._MARKET_STATE_FILE,
        {"experimental_test_market": True, "not_a_market": True},
    )

    with TestClient(app):
        assert api._bookmaker_enabled == {"mozzartbet": False, "mdshop": True}
        assert api._market_enabled == {"experimental_test_market": True}


def test_the_lifespan_restores_fresh_deep_link_proofs_and_decisions(monkeypatch):
    proofs: dict = {}
    decisions: dict = {}
    # `server.app` imported both stores by name, so both modules must point at
    # the object the restore updates.
    monkeypatch.setattr(api, "_deep_link_verifications", proofs)
    monkeypatch.setattr(app_module, "_deep_link_verifications", proofs)
    monkeypatch.setattr(api, "_deep_link_decisions", decisions)
    monkeypatch.setattr(app_module, "_deep_link_decisions", decisions)
    _write_json(
        api.DEEP_LINK_VERIFICATIONS_FILE,
        {
            "prematch": {
                "mozzartbet|e1": _fresh_matches_proof("e1"),
                # Past the 24-hour proof TTL: a restart must not revive it.
                "mozzartbet|old": {
                    "verified": True,
                    "checked_at": _now(-25 * 3600),
                    "url": "https://example.test/old",
                },
            }
        },
    )
    _write_json(
        api.DEEP_LINK_DECISIONS_FILE,
        {
            "prematch": {
                "mozzartbet|e2": {"checked_at": _now()},
                # Past the 6-hour decision TTL.
                "mozzartbet|old": {"checked_at": _now(-7 * 3600)},
            }
        },
    )

    with TestClient(app):
        assert set(api._deep_link_verifications["prematch"]) == {"mozzartbet|e1"}
        assert api._deep_link_verifications["prematch"]["mozzartbet|e1"]["verified"] is True
        assert api._decided_event_ids("prematch", "mozzartbet") == {"e2"}


def test_the_lifespan_restores_stale_price_state(monkeypatch):
    api._stale_price_store["prematch"]["mozzartbet|e1"] = {
        "home": 1.9,
        "away": 2.1,
    }
    api._stale_price_evidence["prematch"] = [
        {"bookmaker": "mozzartbet", "reason": "frozen"}
    ]
    api._stale_price_checked_at["prematch"] = "2026-11-06T10:00:00"
    # Write through the production writer, then forget the in-memory copy.
    api._save_stale_price_state()
    api._stale_price_store["prematch"].clear()
    api._stale_price_evidence["prematch"].clear()
    api._stale_price_checked_at["prematch"] = ""

    with TestClient(app):
        assert api._stale_price_store["prematch"] == {
            "mozzartbet|e1": {"home": 1.9, "away": 2.1}
        }
        assert api._stale_price_evidence["prematch"] == [
            {"bookmaker": "mozzartbet", "reason": "frozen"}
        ]
        assert api._stale_price_checked_at["prematch"] == "2026-11-06T10:00:00"


def test_the_lifespan_restores_scan_history_from_sqlite(monkeypatch):
    storage = Storage(default_storage_path())
    storage.initialize()
    storage.append_scan(
        {
            "mode": "prematch",
            "scan_time": _now(),
            "total_matches": 42,
            "match_groups": 7,
            "surebets_found": 2,
            "per_bookie": {"mozzartbet": 20},
            "errors": [],
            "candidate_queue": 3,
            "candidate_actionable": 1,
        }
    )
    monkeypatch.setattr(api, "_storage", None)
    monkeypatch.setattr(api, "scan_history", [])

    with TestClient(app):
        assert len(api.scan_history) == 1
        assert api.scan_history[0]["match_groups"] == 7
        assert api.scan_history[0]["surebets_found"] == 2
        assert api.scan_history[0]["per_bookie"] == {"mozzartbet": 20}
        assert api._storage is not None


def test_proofs_are_loaded_before_the_cache_restore_re_stamps_matches(monkeypatch):
    """A proof is applied to the restored match only when it was loaded first.

    This is the ordering the lifespan comment describes: `_load_cache` reads
    `_deep_link_verifications` through `_apply_deep_link_verifications`, so a
    cache restored before the proof file still carries
    ``deep_link_verified=False`` and every group reads ``link_unverified``.
    """
    proofs: dict = {}
    monkeypatch.setattr(api, "_deep_link_verifications", proofs)
    monkeypatch.setattr(app_module, "_deep_link_verifications", proofs)
    monkeypatch.setattr(api, "_deep_link_decisions", {})
    monkeypatch.setattr(app_module, "_deep_link_decisions", {})
    monkeypatch.setattr(api, "scan_status", ScanStatus())
    monkeypatch.setattr(api, "cached_surebets", [])
    monkeypatch.setattr(api, "cached_matches", [])
    monkeypatch.setattr(api, "cached_match_groups_report", [])
    monkeypatch.setattr(api, "_last_run_mode", dict(api._last_run_mode))
    monkeypatch.setattr(api, "_recorded_counts", dict(api._recorded_counts))
    _write_json(
        api._PREMATCH_CACHE_FILE,
        {
            "surebets": [],
            "matches": [
                {
                    "bookmaker": "mozzartbet",
                    "event_id": "e1",
                    "home_team": "Sarajevo",
                    "away_team": "Zrinjski",
                    "deep_link_verified": False,
                }
            ],
            "match_groups": [],
            "scan_time": _now(),
        },
    )

    # Control: no proof on disk, so the restored match stays unverified.
    with TestClient(app):
        assert api.cached_matches[0]["deep_link_verified"] is False

    _write_json(
        api.DEEP_LINK_VERIFICATIONS_FILE,
        {"prematch": {"mozzartbet|e1": _fresh_matches_proof("e1")}},
    )

    with TestClient(app):
        assert api.cached_matches[0]["deep_link_verified"] is True
