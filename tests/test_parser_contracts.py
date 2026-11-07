"""N2-6: dated parser contracts and contract drift.

A fixture proves the parser reads a real payload. A contract records the parts of
that payload the parser depends on, so a feed change fails with a diff (the
source ids, labels and shape that moved) rather than a vague parse error.

These tests also pin the boundary: a changed id never enters the market registry
from here. Re-admission stays a human, evidence-backed step.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from config.settings import BOOKMAKERS
from engine import parser_contracts
from engine.market_registry import MarketRegistry
from scripts import refresh_fixtures
from server.app import app

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "markets"
CONTRACTS = FIXTURE_DIR / "contracts.json"
client = TestClient(app)

# SR1-1: the shipped contract test checks payload equality, not fixture age.
# Pinning the reference date keeps the suite green when a capture crosses the
# 120-day policy; CI's ``refresh_fixtures.py --check`` still reports staleness
# against the real clock.
REFERENCE_DATE = date(2026, 11, 7)


def _freeze_contract_clock(monkeypatch, frozen: date) -> None:
    """Make ``parser_contracts.date.today()`` return ``frozen`` for one test."""

    class FrozenDate(date):
        @classmethod
        def today(cls) -> FrozenDate:
            return cls(frozen.year, frozen.month, frozen.day)

    monkeypatch.setattr(parser_contracts, "date", FrozenDate)


def _copy_case(tmp_path: Path, stem: str = "maxbet_prematch") -> Path:
    fixture_dir = tmp_path / "markets"
    fixture_dir.mkdir()
    source = FIXTURE_DIR / f"{stem}.json"
    shutil.copy(source, fixture_dir / source.name)
    payload = parser_contracts.compute_all(fixture_dir)
    parser_contracts.save_contracts(payload, fixture_dir / "contracts.json")
    return fixture_dir / "contracts.json"


def _mutate(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_the_shipped_contracts_match_every_fixture():
    """The fixtures and their reviewed contracts are in sync.

    The reference date is pinned (SR1-1): this test verifies payload equality,
    while CI's ``refresh_fixtures.py --check`` owns the real-date age policy.
    """
    report = refresh_fixtures.build_report(today=REFERENCE_DATE)
    assert report["diff"] == {"added": [], "removed": [], "changed": {}}
    assert report["stale"] == []
    assert report["missing_books"] == []
    assert report["ok"] is True
    assert report["contracts"] == len(list(FIXTURE_DIR.glob("*.json"))) - 1


def test_the_contract_check_is_independent_of_the_wall_clock(monkeypatch):
    """SR1-1: the equality check stays green on 2027-03-01 and later."""
    _freeze_contract_clock(monkeypatch, date(2027, 3, 1))

    report = refresh_fixtures.build_report(today=REFERENCE_DATE)

    assert report["diff"] == {"added": [], "removed": [], "changed": {}}
    assert report["stale"] == []
    assert report["ok"] is True


def test_an_expired_contract_still_reports_stale_in_production(monkeypatch):
    """SR1-1: without an injected date the real-clock staleness check remains."""
    _freeze_contract_clock(monkeypatch, date(2027, 3, 1))
    contracts = {
        "maxbet_prematch": {
            "bookmaker": "maxbet",
            "mode": "prematch",
            "captured_at": "2026-10-20",
        }
    }

    stale = parser_contracts.stale_contracts(contracts, max_age_days=120)

    assert stale[0]["contract"] == "maxbet_prematch"
    assert stale[0]["age_days"] == 132
    assert stale[0]["age_days"] > stale[0]["max_age_days"]


def test_every_enabled_book_has_a_dated_contract():
    contracts = json.loads(CONTRACTS.read_text(encoding="utf-8"))["contracts"]
    covered = {contract["bookmaker"] for contract in contracts.values()}
    enabled = {book for book, config in BOOKMAKERS.items() if config.get("enabled")}
    assert enabled <= covered, f"enabled books without a fixture: {sorted(enabled - covered)}"
    for contract in contracts.values():
        assert date.fromisoformat(contract["captured_at"])  # raises on a bad date
        assert contract["fingerprint"]
        assert contract["market_ids"]
        assert contract["labels_fingerprint"]
        assert contract["structure_fingerprint"]


def test_every_fixture_keeps_the_required_top_level_keys():
    for fixture in sorted(FIXTURE_DIR.glob("*.json")):
        if fixture.name == "contracts.json":
            continue
        data = json.loads(fixture.read_text(encoding="utf-8"))
        missing = [
            key for key in parser_contracts.REQUIRED_TOP_LEVEL_KEYS if key not in data
        ]
        assert missing == [], f"{fixture.name} is missing {missing}"


def test_a_changed_market_id_fails_with_the_exact_diff(tmp_path):
    contracts_path = _copy_case(tmp_path)
    fixture = contracts_path.parent / "maxbet_prematch.json"

    def add_market(data):
        data["bets"].append({**data["bets"][0], "id": 99999, "name": "Synthetic new market"})

    _mutate(fixture, add_market)
    report = refresh_fixtures.build_report(contracts_path=contracts_path)

    assert report["ok"] is False
    change = report["diff"]["changed"]["maxbet_prematch"]
    assert "99999" in change["market_ids"]["added"]
    assert change["fingerprint"]["expected"] != change["fingerprint"]["actual"]
    assert refresh_fixtures.main(["--check", "--contracts", str(contracts_path)]) == 1


def test_a_changed_label_fails_with_the_exact_diff(tmp_path):
    contracts_path = _copy_case(tmp_path)
    fixture = contracts_path.parent / "maxbet_prematch.json"

    def rename(data):
        data["bets"][0]["name"] = "Renamed market label"

    _mutate(fixture, rename)
    report = refresh_fixtures.build_report(contracts_path=contracts_path)

    change = report["diff"]["changed"]["maxbet_prematch"]
    assert "Renamed market label" in change["labels"]["added"]
    assert change["fingerprint"]["expected"] != change["fingerprint"]["actual"]


def test_a_changed_structure_fails_with_the_exact_diff(tmp_path):
    contracts_path = _copy_case(tmp_path)
    fixture = contracts_path.parent / "maxbet_prematch.json"

    def reshape(data):
        data["bets"][0]["outcomes"][0]["newField"] = {"nested": True}

    _mutate(fixture, reshape)
    report = refresh_fixtures.build_report(contracts_path=contracts_path)

    change = report["diff"]["changed"]["maxbet_prematch"]
    assert any("newField" in path for path in change["structure"]["added"])


def test_an_expired_fixture_is_reported_with_its_age(tmp_path):
    contracts = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    contract = contracts["contracts"]["maxbet_prematch"]
    old = (date.today() - timedelta(days=365)).isoformat()
    contract["captured_at"] = old
    stale = parser_contracts.stale_contracts(
        contracts["contracts"], max_age_days=120, today=date.today()
    )
    assert stale[0]["contract"] == "maxbet_prematch"
    assert stale[0]["age_days"] == 365


def test_health_exposes_contract_coverage_and_staleness():
    body = client.get("/api/health").json()
    contracts = body["parser_contracts"]

    assert contracts["contracts"] >= 17
    assert contracts["missing_books"] == []
    assert contracts["max_age_days"] > 0
    assert "stale" in contracts and "oldest_capture" in contracts
    assert "checked_at" in contracts


def test_a_new_market_is_never_admitted_by_a_contract_refresh(tmp_path):
    """The diff is a prompt for a human, not a registry write."""
    registry = MarketRegistry()
    registry_path = Path(registry.path)
    before = registry_path.read_bytes()
    contracts_path = _copy_case(tmp_path)
    fixture = contracts_path.parent / "maxbet_prematch.json"

    def add_market(data):
        data["bets"].append({**data["bets"][0], "id": 88888, "name": "New market"})

    _mutate(fixture, add_market)
    refresh_fixtures.main(["--write", "--contracts", str(contracts_path)])

    assert registry_path.read_bytes() == before, "a contract refresh must not edit the registry"
    assert not registry.has_source_id("maxbet", "prematch", "88888")


def test_capture_failure_is_not_reported_as_feed_drift(monkeypatch):
    """A network failure is a capture failure, never a changed payload."""
    monkeypatch.setattr(
        refresh_fixtures,
        "capture",
        lambda books: {
            "status": "capture_failed",
            "returncode": 1,
            "command": "capture",
            "stdout_tail": "SKIPPED maxbet/prematch: host unreachable",
            "stderr_tail": "",
        },
    )
    code = refresh_fixtures.main(["--capture"])
    assert code == 1
