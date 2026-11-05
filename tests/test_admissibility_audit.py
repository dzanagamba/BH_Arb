"""N3-2: the dated sport/market admissibility re-audit.

The audit automates the report and the change detector. It must never lower the
three-book/three-family rule, never auto-admit a new family, and never enable a
sport or market from a changed measurement alone.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import ENABLED_MARKETS, ENABLED_SPORTS
from engine import sports
from engine.admissibility import (
    DEFAULT_BASELINE,
    FOOTBALL_LINES_EVIDENCE,
    MIN_BOOKS,
    MIN_FAMILIES,
    PREMATCH_EVIDENCE,
    SCHEMA_VERSION,
    AuditResult,
    build_report,
    detect_changes,
    health_summary,
    load_baseline,
    validate_evidence,
)
from server.app import app

REPO = Path(__file__).resolve().parents[1]
FIXED_TIME = "2026-11-05T00:00:00+00:00"


def _report() -> dict:
    return build_report(generated_at=FIXED_TIME)


def _baseline() -> dict:
    return load_baseline()


def _codes(result: dict) -> set[str]:
    return {item["kind"] for item in result["failures"]}


def _warning_codes(result: dict) -> set[str]:
    return {item["kind"] for item in result["warnings"]}


def test_the_report_has_a_stable_schema() -> None:
    report = _report()

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["rule"] == {
        "min_books": 3,
        "min_families": 3,
        "same_settlement": True,
        "auto_admit": False,
    }
    assert set(report["sports"]) == set(sports.SPORT_SPECS) | {sports.FOOTBALL}
    assert report["enabled_sports"] == ENABLED_SPORTS
    for sport, entry in report["sports"].items():
        assert entry["sport"] == sport
        assert "enabled" in entry and "admitted" in entry and "admissible" in entry
        assert "books" in entry and "evidence" in entry
        assert "family_settlements" in entry
    for market, entry in report["markets"].items():
        assert entry["market"] == market
        assert "enabled" in entry and "admitted" in entry
        assert "settlement" in entry and "evidence" in entry


def test_every_enabled_family_and_sport_has_a_dated_evidence_row() -> None:
    report = _report()

    for sport in report["enabled_sports"]:
        evidence = report["sports"][sport]["evidence"]
        assert evidence["available"] is True
        assert evidence["observed_at"]
        assert (REPO / evidence["path"]).is_file()

    for market, entry in report["markets"].items():
        if entry["enabled"]:
            evidence = entry["evidence"]
            assert evidence["available"] is True, market
            assert evidence["observed_at"], market
            assert (REPO / evidence["path"]).is_file(), market

    covered = set(report["markets"])
    for entry in report["sports"].values():
        covered |= set(entry["family_settlements"])
    assert set(ENABLED_MARKETS) <= covered


def test_the_three_book_and_three_family_rule_is_unchanged() -> None:
    report = _report()

    assert MIN_BOOKS == 3
    assert MIN_FAMILIES == 3
    assert report["sports"]["basketball"]["admissible"] is True
    assert report["sports"]["tennis"]["admissible"] is True
    assert len(report["sports"]["basketball"]["qualifying_books"]) >= 3
    assert len(report["sports"]["tennis"]["qualifying_books"]) >= 3
    assert report["sports"]["ice_hockey"]["admissible"] is False
    assert report["sports"]["ice_hockey"]["admitted"] is False
    assert report["sports"]["ice_hockey"]["enabled"] is False
    assert "ice_hockey" not in ENABLED_SPORTS


def test_a_new_qualifying_family_does_not_admit_a_disabled_sport(tmp_path: Path) -> None:
    evidence = {
        "generated_at": "2026-11-05T00:00:00+00:00",
        "sports": {
            "ice_hockey": {
                "books": [
                    {
                        "book": book,
                        "matches": 10,
                        "markets": {"moneyline": 1, "handicap": 1, "total": 1},
                    }
                    for book in ("alpha", "beta", "gamma")
                ]
            }
        },
    }
    path = tmp_path / "sport-discovery.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")

    report = build_report(
        sport_evidence=str(path),
        football_lines_evidence=str(REPO / FOOTBALL_LINES_EVIDENCE),
        prematch_evidence=str(REPO / PREMATCH_EVIDENCE),
        generated_at=FIXED_TIME,
    )
    hockey = report["sports"]["ice_hockey"]
    baseline = _baseline()
    baseline["sports"] = {
        "ice_hockey": {
            **baseline["sports"]["ice_hockey"],
            "books": {},
            "qualifying_books": [],
        }
    }
    baseline["markets"] = {}
    result = detect_changes(report, baseline).as_dict()

    assert hockey["admissible"] is True
    assert hockey["enabled"] is False
    assert hockey["admitted"] is False
    assert hockey["status"] == "not_enabled"
    assert result["status"] == "warning"
    assert "new_book_without_evidence" in _warning_codes(result)
    assert "admitted_sport_lost" not in _codes(result)


def test_a_disappeared_admitted_family_fails_the_check() -> None:
    from engine.admissibility import _qualifying_books

    report = _report()
    basketball = report["sports"]["basketball"]
    del basketball["books"]["mdshop"]["families"]["total"]
    del basketball["books"]["mbet"]["families"]["total"]
    basketball["qualifying_books"] = _qualifying_books(
        "basketball", basketball["books"]
    )
    basketball["admissible"] = len(basketball["qualifying_books"]) >= MIN_BOOKS

    result = detect_changes(report, _baseline()).as_dict()

    assert result["status"] == "fail"
    assert "admitted_family_disappeared" in _codes(result)
    assert "qualifying_book_disappeared" in _codes(result)
    assert "sport_became_inadmissible" in _codes(result)


def test_a_changed_settlement_fails_the_check() -> None:
    report = _report()
    report["sports"]["basketball"]["family_settlements"]["total"] = "full_time_incl_ot"

    result = detect_changes(report, _baseline()).as_dict()

    assert result["status"] == "fail"
    assert "sport_settlement_changed" in _codes(result)


def test_a_lowered_threshold_in_the_baseline_fails_the_check() -> None:
    baseline = _baseline()
    baseline["rule"]["min_books"] = 2

    result = detect_changes(_report(), baseline).as_dict()

    assert result["status"] == "fail"
    assert "threshold_lowered" in _codes(result)


def test_a_new_family_is_a_warning_not_an_admission() -> None:
    report = _report()
    report["sports"]["basketball"]["books"]["mbet"]["families"]["spread"] = 1
    report["sports"]["basketball"]["books"]["mbet"]["settlements"]["spread"] = "regulation"

    result = detect_changes(report, _baseline()).as_dict()

    assert result["status"] == "warning"
    assert "new_family_without_evidence" in _warning_codes(result)
    assert report["sports"]["basketball"]["admitted"] is True


def test_a_new_market_is_a_warning_not_an_admission() -> None:
    report = _report()
    report["markets"]["new_market"] = copy.deepcopy(report["markets"]["1x2"])
    report["markets"]["new_market"]["market"] = "new_market"

    result = detect_changes(report, _baseline()).as_dict()

    assert result["status"] == "warning"
    assert "new_market_without_evidence" in _warning_codes(result)


def test_missing_evidence_fails_validation() -> None:
    report = build_report(
        sport_evidence="docs/evidence/does-not-exist.json",
        generated_at=FIXED_TIME,
    )
    audit = AuditResult()
    validate_evidence(report, audit)

    assert audit.status == "fail"
    assert "missing_sport_evidence" in {item["kind"] for item in audit.failures}


def test_the_shipped_baseline_passes_the_audit() -> None:
    report = _report()
    result = detect_changes(report, _baseline()).as_dict()

    assert result["status"] == "ok"
    assert result["failures"] == []
    assert result["checked"]["sports"] == 4
    assert result["checked"]["markets"] == 12


def test_the_cli_check_passes_on_the_shipped_baseline(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.audit_admissibility import main

    assert main(["--check"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"


def test_the_cli_check_fails_on_a_lowered_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.audit_admissibility import main

    baseline = _baseline()
    baseline["rule"]["min_books"] = 2
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline), encoding="utf-8")

    assert main(["--check", "--baseline", str(path)]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert "threshold_lowered" in {item["kind"] for item in payload["failures"]}


def test_health_exposes_the_admissibility_audit() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    block = response.json()["admissibility_audit"]
    assert block["status"] == "ok"
    assert block["failure_count"] == 0
    assert block["sports"]["basketball"]["admitted"] is True
    assert block["markets"]["1x2"]["admitted"] is True


def test_health_summary_is_bounded() -> None:
    summary = health_summary()

    assert summary["schema_version"] == SCHEMA_VERSION
    assert summary["status"] == "ok"
    assert len(summary["sports"]) == 4
    assert len(summary["markets"]) == 12
    assert "books" not in summary["sports"]["basketball"]


def test_the_default_baseline_is_the_dated_snapshot() -> None:
    assert DEFAULT_BASELINE.endswith("2026-11-05-admissibility-baseline.json")
    assert (REPO / DEFAULT_BASELINE).is_file()
