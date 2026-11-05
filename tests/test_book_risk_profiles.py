"""P3-6: advisory book risk profiles never enter the trust or pricing path."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from config.settings import (
    BOOK_RISK_PROFILES,
    BOOKMAKERS,
    load_book_risk_profiles,
    price_source,
)
from engine.certainty import CertaintyGate
from models.schemas import Market, MarketType, Match, OddsValue
from server.app import app

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
CSS = Path("frontend/css/style.css").read_text(encoding="utf-8")
RISK_JSON = json.loads(Path("config/bookmaker_risk.json").read_text(encoding="utf-8"))
RISK_DOC = Path("docs/BOOK_RISK.md").read_text(encoding="utf-8")
K = datetime(2026, 11, 5, 18, 0)


def _match(bookmaker: str, event_id: str) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team="Sarajevo",
        away_team="Zeljeznicar",
        league="BiH - Premier Liga",
        kickoff=K,
        home_team_normalized="sarajevo",
        away_team_normalized="zeljeznicar",
        event_id=event_id,
        deep_link_verified=True,
        markets=[
            Market(
                market_type=MarketType.MATCH_RESULT,
                odds=[
                    OddsValue(label="1", value=2.0),
                    OddsValue(label="X", value=3.0),
                    OddsValue(label="2", value=3.0),
                ],
            )
        ],
    )


def test_every_enabled_book_has_a_profile_and_limit_notes():
    body = TestClient(app).get("/api/config").json()
    allowed = {"sharp", "soft", "exchange", "unknown"}

    for book, config in BOOKMAKERS.items():
        exposed = body["bookmakers"][book]
        assert exposed["risk_profile"] in allowed
        assert exposed["typical_max_stake_note"]
        assert exposed["limit_risk"]
        assert exposed["max_stake"] > 0
        if config["enabled"]:
            assert exposed["risk_profile"] != ""

    assert set(RISK_JSON["books"]) == set(BOOKMAKERS)
    assert all(entry["profile"] in allowed for entry in RISK_JSON["books"].values())


def test_a_missing_or_malformed_profile_file_fails_safe_to_unknown(tmp_path: Path):
    missing = load_book_risk_profiles(str(tmp_path / "missing.json"))
    assert missing["mbet"]["profile"] == "unknown"
    assert missing["mbet"]["advisory_max_stake"] == 500

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    assert load_book_risk_profiles(str(malformed))["mbet"]["profile"] == "unknown"

    bad_profile = tmp_path / "bad_profile.json"
    bad_profile.write_text(
        json.dumps({"books": {"mbet": {"profile": "guaranteed", "advisory_max_stake": "x"}}}),
        encoding="utf-8",
    )
    loaded = load_book_risk_profiles(str(bad_profile))
    assert loaded["mbet"]["profile"] == "unknown"
    assert loaded["mbet"]["advisory_max_stake"] == 500


def test_the_dashboard_shows_profiles_and_flags_a_soft_book_high_stake():
    assert "function bookRisk" in JS
    assert "function riskProfileLabel" in JS
    assert 'data-risk-profile="${escapeHtml(risk.profile)}"' in JS
    assert "typical_max_stake_note" in JS
    assert "limit_risk" in JS
    assert 'data-risk-warning="soft-book-stake"' in JS
    assert "High stake at a soft book" in JS
    assert ".risk-badge" in CSS


def test_a_profile_cannot_change_the_certainty_gate_or_the_price_source(monkeypatch):
    gate = CertaintyGate()
    left = _match("mdshop", "1")
    right = _match("mbet", "2")
    gate.normalize([left, right])
    baseline = gate.evaluate_pair(left, right)

    baseline_sources = {book: price_source(book) for book in BOOKMAKERS}
    monkeypatch.setitem(
        BOOK_RISK_PROFILES,
        "mbet",
        {
            "profile": "exchange",
            "advisory_max_stake": 1,
            "typical_max_stake_note": "changed for the test",
            "limit_risk": "changed for the test",
        },
    )

    after = gate.evaluate_pair(left, right)
    assert after.status == baseline.status == "verified"
    assert after.reasons == baseline.reasons
    assert {book: price_source(book) for book in BOOKMAKERS} == baseline_sources

    for source in (
        Path("engine/certainty.py"),
        Path("engine/matcher.py"),
        Path("engine/arbitrage.py"),
    ):
        text = source.read_text(encoding="utf-8")
        assert "BOOK_RISK_PROFILES" not in text
        assert "risk_profile" not in text


def test_the_policy_stays_advisory_without_evasion_or_auto_placement():
    assert "placeBet" not in JS
    lowered = RISK_DOC.lower()
    assert "never places a bet" in lowered
    assert "stake jitter" in lowered
    assert "multi-account" in lowered
    assert "auto-placement" in lowered
