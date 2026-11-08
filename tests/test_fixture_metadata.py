"""SR4-2: fixture metadata header, scrub gate and unchanged age policy.

Each capture in ``tests/fixtures/markets/`` carries a metadata header next to
its payload: the book, feed mode, reviewed capture date, the provenance
timestamp with the source it came from, the endpoint and request method, the
HTTP status and the capture-tool version. ``scripts/refresh_fixtures.py
--check`` fails when a header is incomplete, and the capture tool scrubs any
credential-shaped key before writing.

The 120-day age policy is deliberately unchanged: it still reads
``captured_at`` (the reviewed date), never ``recorded_at`` (provenance, which
for older captures is backfilled from the commit that added the fixture).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from engine import parser_contracts
from scripts import refresh_fixtures

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"
FIXTURES = sorted(
    path for path in FIXTURE_DIR.glob("*.json") if path.name != "contracts.json"
)
METADATA_KEYS = (
    "recorded_at",
    "recorded_at_source",
    "http_method",
    "http_status",
    "capture_tool_version",
)
REFERENCE_DATE = date(2026, 11, 7)


def _capture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: path.stem)
def test_every_capture_carries_complete_metadata(path):
    data = _capture(path)

    assert parser_contracts.metadata_issues(data) == []
    assert data["bookmaker"] == path.stem.rsplit("_", 1)[0]
    assert data["recorded_at_source"] in parser_contracts.RECORDED_AT_SOURCES


def test_metadata_validation_names_every_missing_field(tmp_path):
    data = _capture(FIXTURE_DIR / "maxbet_prematch.json")
    for key in METADATA_KEYS:
        data.pop(key)

    issues = parser_contracts.metadata_issues(data)

    missing = next(issue for issue in issues if issue.startswith("missing metadata"))
    for key in METADATA_KEYS:
        assert key in missing


def test_the_shipped_metadata_gate_passes():
    report = refresh_fixtures.build_report(today=REFERENCE_DATE)

    assert report["metadata"]["ok"] is True
    assert report["metadata"]["checked"] == len(FIXTURES)
    assert report["metadata"]["issues"] == {}
    assert report["ok"] is True


def test_check_fails_on_a_fixture_without_metadata(tmp_path, monkeypatch):
    """A payload with a missing header fails ``--check`` even when it matches.

    The contracts are recomputed from the stripped fixture, so a contract diff
    cannot be the reason for the failure; the metadata gate itself must fail.
    """
    fixture_dir = tmp_path / "markets"
    fixture_dir.mkdir()
    data = _capture(FIXTURE_DIR / "maxbet_prematch.json")
    data.pop("recorded_at")
    fixture = fixture_dir / "maxbet_prematch.json"
    fixture.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    contracts_path = fixture_dir / "contracts.json"
    parser_contracts.save_contracts(
        parser_contracts.compute_all(fixture_dir), contracts_path
    )
    monkeypatch.setattr(refresh_fixtures, "_missing_books", lambda contracts: [])

    report = refresh_fixtures.build_report(contracts_path=contracts_path)

    assert report["diff"] == {"added": [], "removed": [], "changed": {}}
    assert report["metadata"]["ok"] is False
    assert "maxbet_prematch" in report["metadata"]["issues"]
    assert any(
        "recorded_at" in issue
        for issue in report["metadata"]["issues"]["maxbet_prematch"]
    )
    assert report["ok"] is False
    assert refresh_fixtures.main(["--check", "--contracts", str(contracts_path)]) == 1


def test_backfill_marks_a_git_timestamp_and_never_rewrites_the_capture_date(
    tmp_path, monkeypatch
):
    fixture_dir = tmp_path / "markets"
    fixture_dir.mkdir()
    source = FIXTURE_DIR / "maxbet_prematch.json"
    data = _capture(source)
    for key in (*METADATA_KEYS, "recorded_at_commit", "metadata_backfilled"):
        data.pop(key)
    fixture = fixture_dir / source.name
    fixture.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        refresh_fixtures,
        "_git_recorded_at",
        lambda path: ("2026-11-04T12:59:55+01:00", "842d65a"),
    )

    report = refresh_fixtures.backfill_fixtures(fixture_dir)

    assert report == {"changed": ["maxbet_prematch"], "count": 1, "failed": []}
    updated = _capture(fixture)
    assert updated["captured_at"] == data["captured_at"]
    assert updated["recorded_at"] == "2026-11-04T12:59:55+01:00"
    assert updated["recorded_at_source"] == "git_commit"
    assert updated["recorded_at_commit"] == "842d65a"
    assert updated["http_method"] == "GET"
    assert updated["http_status"] == 200
    assert updated["capture_tool_version"] == parser_contracts.LEGACY_CAPTURE_TOOL_VERSION
    assert updated["metadata_backfilled"] is True
    assert parser_contracts.metadata_issues(updated) == []


def test_backfill_uses_the_capture_date_when_git_is_unavailable(tmp_path, monkeypatch):
    fixture_dir = tmp_path / "markets"
    fixture_dir.mkdir()
    source = FIXTURE_DIR / "maxbet_prematch.json"
    data = _capture(source)
    for key in (*METADATA_KEYS, "recorded_at_commit", "metadata_backfilled"):
        data.pop(key)
    fixture = fixture_dir / source.name
    fixture.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(refresh_fixtures, "_git_recorded_at", lambda path: ("", ""))

    refresh_fixtures.backfill_fixtures(fixture_dir)

    updated = _capture(fixture)
    assert updated["recorded_at"] == f"{updated['captured_at']}T00:00:00+00:00"
    assert updated["recorded_at_source"] == "captured_at"
    assert "recorded_at_commit" not in updated
    assert parser_contracts.metadata_issues(updated) == []


def test_credential_shaped_keys_are_reported_and_scrubbed():
    data = _capture(FIXTURE_DIR / "maxbet_prematch.json")
    data["headers"] = {"Cookie": "session=1", "Authorization": "Bearer secret"}
    data["nested"] = {"access_token": "secret", "note": "keep"}

    issues = parser_contracts.metadata_issues(data)

    assert sum(issue.startswith("secret-bearing metadata") for issue in issues) == 3
    clean = parser_contracts.scrub_secrets(data)
    assert clean["headers"] == {}
    assert clean["nested"] == {"note": "keep"}


def test_event_id_tokens_in_endpoints_are_not_mistaken_for_credentials():
    """Betole's ``matchIdsToken`` is an event-id list, not a secret."""
    data = _capture(FIXTURE_DIR / "betole_prematch.json")

    assert "matchIdsToken" in data["endpoint"]
    assert parser_contracts.metadata_issues(data) == []


def test_the_age_policy_still_reads_the_capture_date():
    """``recorded_at`` is provenance; the reviewed date drives staleness."""
    contracts = {
        "maxbet_prematch": {
            "bookmaker": "maxbet",
            "mode": "prematch",
            "captured_at": "2026-01-01",
            "recorded_at": "2026-12-31T00:00:00+00:00",
        }
    }

    stale = parser_contracts.stale_contracts(
        contracts, max_age_days=120, today=date(2026, 11, 8)
    )

    assert stale[0]["age_days"] == 311
    assert stale[0]["age_days"] > stale[0]["max_age_days"]
