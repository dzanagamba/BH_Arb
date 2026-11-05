"""N0-1: the offline suite is independent of the operator's runtime state.

The suite used to fail when ``config/generated/mapping_evidence.json`` held a
claim that superseded an allowlist proof in the certified end-to-end test. These
tests pin the fix: every generated path is redirected into a temporary tree,
writes land there, and the checkout's runtime directories are left untouched.

The session-scoped guard in ``tests/conftest.py`` is the suite-wide half; these
tests are the direct, readable proof of the same rule.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import settings
from engine import mapping_evidence, matcher
from server import api
from server.storage import Storage, default_storage_path

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = REPO_ROOT / "config" / "generated"
CACHE_DIR = REPO_ROOT / "cache"
RUNTIME_LEDGER_ENV = "BH_ARB_TEST_RUNTIME_LEDGER"
POPULATED_LEDGER_ALIAS = ("FK Sarajevo", "Sarajevo")


def _is_in_checkout(path: str | Path) -> bool:
    return Path(path).resolve().is_relative_to(REPO_ROOT)


def _checkout_runtime_snapshot() -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for directory in (GENERATED_DIR, CACHE_DIR):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[str(path.relative_to(REPO_ROOT))] = (
                    stat.st_mtime_ns,
                    stat.st_size,
                )
    return snapshot


def test_generated_runtime_paths_live_outside_the_checkout():
    paths = {
        "engine.matcher.MAPPING_EVIDENCE_FILE": matcher.MAPPING_EVIDENCE_FILE,
        "engine.mapping_evidence.DEFAULT_PATH": mapping_evidence.DEFAULT_PATH,
        "config.settings.CACHE_DIR": settings.CACHE_DIR,
        "server.api.CACHE_DIR": api.CACHE_DIR,
        "server.storage.default_storage_path": default_storage_path(),
        "server.api.SUPPRESSED_CANDIDATES_FILE": api.SUPPRESSED_CANDIDATES_FILE,
        "server.api._HISTORY_FILE": api._HISTORY_FILE,
        "server.api._PREMATCH_CACHE_FILE": api._PREMATCH_CACHE_FILE,
        "server.api._LIVE_CACHE_FILE": api._LIVE_CACHE_FILE,
        "server.api._FEED_INTEGRITY_FILE": api._FEED_INTEGRITY_FILE,
        "server.api._COVERAGE_BUDGET_FILE": api._COVERAGE_BUDGET_FILE,
        "server.api.DEEP_LINK_VERIFICATIONS_FILE": api.DEEP_LINK_VERIFICATIONS_FILE,
        "server.api.DEEP_LINK_DECISIONS_FILE": api.DEEP_LINK_DECISIONS_FILE,
    }
    for label, path in paths.items():
        assert not _is_in_checkout(path), f"{label} still points into the checkout: {path}"

    assert Path(matcher.MAPPING_EVIDENCE_FILE) == Path(mapping_evidence.DEFAULT_PATH), (
        "the matcher and the ledger must agree on the redirected ledger path"
    )


def test_writes_land_in_the_temporary_runtime_and_not_the_checkout(monkeypatch):
    from engine.mapping_evidence import Evidence, MappingLedger, team_alias_key

    monkeypatch.setattr(api, "_suppressed_candidates", {})
    monkeypatch.setattr(api, "_suppressed_premises", {})
    before = _checkout_runtime_snapshot()

    api._save_suppressed_candidates()
    api._save_bookmaker_state()
    api._save_market_state()
    api._save_history()
    api._save_opportunity_metrics()
    api._save_feed_integrity()
    api._save_coverage_budget()

    ledger = MappingLedger()
    ledger.accept(
        "team_alias",
        team_alias_key(*POPULATED_LEDGER_ALIAS),
        [Evidence(type="exact_shared_fixture", scan="n0-1")],
        "N0-1 write check",
    )
    ledger.save()

    for label, path in {
        "decisions": api.SUPPRESSED_CANDIDATES_FILE,
        "bookmaker state": api._BOOKMAKER_STATE_FILE,
        "market state": api._MARKET_STATE_FILE,
        "history": api._HISTORY_FILE,
        "opportunity metrics": api._OPPORTUNITY_METRICS_FILE,
        "feed integrity": api._FEED_INTEGRITY_FILE,
        "coverage budget": api._COVERAGE_BUDGET_FILE,
        "mapping ledger": mapping_evidence.DEFAULT_PATH,
    }.items():
        written = Path(path)
        assert written.exists(), f"{label} was not written to the redirected path"
        assert not _is_in_checkout(written), f"{label} was written into the checkout: {written}"

    assert _checkout_runtime_snapshot() == before, (
        "a write reached the checkout's config/generated or cache directory"
    )


def test_the_redirected_ledger_matches_the_requested_runtime_mode():
    """The CI switch must actually produce the state it claims to produce."""
    expected_populated = os.getenv(RUNTIME_LEDGER_ENV, "empty") == "populated"
    from engine.mapping_evidence import MappingLedger, team_alias_key

    ledger = MappingLedger().load()
    assert (
        ledger.is_accepted("team_alias", team_alias_key(*POPULATED_LEDGER_ALIAS))
        is expected_populated
    ), (
        f"{RUNTIME_LEDGER_ENV}={os.getenv(RUNTIME_LEDGER_ENV, 'empty')!r} did not "
        "produce the matching redirected ledger"
    )


def test_the_default_sqlite_store_is_redirected(monkeypatch):
    monkeypatch.setattr(api, "_suppressed_candidates", {})
    monkeypatch.setattr(api, "_suppressed_premises", {})
    path = Path(default_storage_path())
    assert not _is_in_checkout(path)

    storage = Storage(str(path))
    storage.initialize()
    monkeypatch.setattr(api, "_storage", storage)
    assert api._using_default_decision_store(), (
        "with both the store and the decision file redirected, the server must "
        "still recognise its default decision store"
    )

    api._suppress_candidate("candidate-1", "approved", "link_unverified")
    assert storage.decisions() == {"candidate-1": "approved"}
    assert storage.decision_premises() == {"candidate-1": "link_unverified"}
    assert Path(api.SUPPRESSED_CANDIDATES_FILE).exists()
    assert not _is_in_checkout(api.SUPPRESSED_CANDIDATES_FILE)


def test_the_populated_ledger_fixture_carries_the_certified_claim(populated_ledger):
    from engine.mapping_evidence import MappingLedger, team_alias_key

    ledger = MappingLedger(populated_ledger).load()
    assert ledger.is_accepted("team_alias", team_alias_key(*POPULATED_LEDGER_ALIAS))
    assert not _is_in_checkout(populated_ledger)


@pytest.mark.real_runtime_state
def test_the_opt_in_marker_exposes_the_real_paths():
    """Only an explicit opt-in may read the operator's ledger and cache."""
    expected_ledger = GENERATED_DIR / "mapping_evidence.json"
    assert Path(matcher.MAPPING_EVIDENCE_FILE).resolve() == expected_ledger.resolve()
    assert Path(settings.CACHE_DIR).resolve() == CACHE_DIR.resolve()
