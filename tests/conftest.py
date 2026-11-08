"""Shared test setup.

Runtime state isolation (N0-1)
------------------------------
The suite must produce the same result on a clean checkout and on an operator
machine with a populated ``config/generated/mapping_evidence.json``, ``cache/``
and SQLite store. The autouse ``_isolated_runtime_state`` fixture redirects every
generated path into a per-test temporary directory before the test runs:

* ``engine.matcher.MAPPING_EVIDENCE_FILE`` and
  ``engine.mapping_evidence.DEFAULT_PATH`` (the generated ledger),
* ``config.settings.CACHE_DIR``, ``server.api.CACHE_DIR`` and every JSON cache
  file the server reads or writes,
* ``STORAGE_PATH`` and the lazily-created SQLite stores (history, bets, paper).

Config *inputs* (``config/bookmaker_markets.json``, the deeplink declarations,
the reviewed allowlist) are deliberately not redirected: they are the shipped
source of truth, not runtime state. The operator's real ledger and cache are
never deleted or rewritten by a test.

A test that intentionally reads the operator's runtime state opts out with
``pytest.mark.real_runtime_state`` and is skipped unless
``BH_ARB_TEST_RUNTIME_STATE=1`` is set. ``BH_ARB_TEST_RUNTIME_LEDGER=populated``
seeds the redirected ledger with one accepted claim, so CI can prove the suite
also passes with a populated ledger without touching the checkout.

Most gate tests need a book that *declares* a per-event route, so they can show
that an unproven link on such a book blocks `verified`. In the shipped config
only Mozzartbet declares one (MDShop and Admiralbet were set to
`supports_event_id: false` on 2026-10-20 after their `?event=` routes were found
inert). Rather than rewrite every fixture around one book, the tests keep MDShop
and Admiralbet as route-declaring example books through the same in-memory
declaration map the gate reads.

A module that checks the *real* shipped config opts out with
``pytestmark = pytest.mark.real_deeplinks``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scrapers import common, forensics
from scripts.check_test_isolation import runtime_state_snapshot

EXAMPLE_ROUTE_BOOKS = {
    "mdshop": {
        "supports_event_id": True,
        "template": "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event={event_id}",
        "template_live": "https://www.mdshop.ba/sport-live?event={event_id}",
    },
    "admiralbet": {
        "supports_event_id": True,
        "template": "https://www.admiralbet.ba/sport-prematch?sport=Fudbal&event={event_id}",
        "template_live": "https://www.admiralbet.ba/sport-live?event={event_id}",
    },
}

# Opt-in for tests that must read the operator's real runtime state.
REAL_STATE_ENV = "BH_ARB_TEST_RUNTIME_STATE"
# "empty" (default) or "populated": seed the redirected ledger with one claim.
RUNTIME_LEDGER_ENV = "BH_ARB_TEST_RUNTIME_LEDGER"

# The alias the certified end-to-end fixture needs ("FK Sarajevo" vs
# "Sarajevo"). A populated ledger carrying this claim is exactly the local state
# that used to supersede the allowlist proof in tests/test_e2e_certified.py.
POPULATED_LEDGER_ALIAS = ("FK Sarajevo", "Sarajevo")


@pytest.fixture(scope="session", autouse=True)
def _no_real_network():
    """Fail loudly if any test opens a real network connection (SR4-1).

    HTTP-level adapter tests serve their captures through ``respx``. Without a
    guard, one adapter that stops being mocked would quietly reach the live
    bookmaker, which is both a test flake and unsolicited traffic. Name
    resolution and connection setup are blocked at the ``socket`` module so a
    library that bypasses httpx (a raw socket, a future client) is caught too.
    """
    import socket

    loopback = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}

    def _is_loopback(value) -> bool:
        if isinstance(value, tuple) and value:
            return str(value[0]).lower() in loopback
        return isinstance(value, str) and value.lower() in loopback

    def _blocked(original):
        def guard(*args, **kwargs):
            # Local test servers (the opt-in Chromium audit serves the
            # dashboard from 127.0.0.1) are not the network this guard is
            # about.
            if any(_is_loopback(arg) for arg in args):
                return original(*args, **kwargs)
            target = next(
                (arg for arg in args if isinstance(arg, str | tuple)), ""
            )
            raise AssertionError(
                "a test tried a real network connection"
                f"{f' to {target!r}' if target else ''}; serve it with respx or "
                "a fake transport (SR4-1)"
            )

        return guard

    originals = {
        name: getattr(socket, name)
        for name in ("create_connection", "getaddrinfo")
    }
    originals["socket.connect"] = socket.socket.connect
    originals["socket.connect_ex"] = socket.socket.connect_ex

    socket.create_connection = _blocked(socket.create_connection)
    socket.getaddrinfo = _blocked(socket.getaddrinfo)
    socket.socket.connect = _blocked(socket.socket.connect)
    socket.socket.connect_ex = _blocked(socket.socket.connect_ex)
    try:
        yield
    finally:
        for name in ("create_connection", "getaddrinfo"):
            setattr(socket, name, originals[name])
        socket.socket.connect = originals["socket.connect"]
        socket.socket.connect_ex = originals["socket.connect_ex"]

# Every module-level JSON store the server owns. Names are the attributes on
# ``server.api``; values are the file names under the redirected cache.
_API_RUNTIME_FILES = {
    "_BOOKMAKER_STATE_FILE": "bookmaker_state.json",
    "_MARKET_STATE_FILE": "market_state.json",
    "SUPPRESSED_CANDIDATES_FILE": "suppressed_candidates.json",
    "_HISTORY_FILE": "scan_history.json",
    "_LINK_SWEEP_FILE": "link_sweeps.json",
    "_PREMATCH_CACHE_FILE": "last_scan.json",
    "_LIVE_CACHE_FILE": "last_live_scan.json",
    "_OPPORTUNITY_METRICS_FILE": "opportunity_metrics.json",
    "_FEED_INTEGRITY_FILE": "feed_integrity.json",
    "_COVERAGE_BUDGET_FILE": "coverage_budget.json",
    "_SCAN_COST_FILE": "scan_cost.json",
    "_STALE_PRICE_FILE": "stale_price_state.json",
    "DEEP_LINK_VERIFICATIONS_FILE": "deep_link_verifications.json",
    "DEEP_LINK_DECISIONS_FILE": "deep_link_decisions.json",
}


def _reset_deeplink_state() -> None:
    """Clear the declaration cache and the provenance of its last file read."""
    common._deeplink_cache = None
    common._deeplink_cache_signature = None
    common._deeplink_source_mtime = None
    common._deeplink_loaded_at = None
    common._deeplink_load_error = None


def write_populated_ledger(path: Path) -> Path:
    """Write one accepted alias claim, the shape an operator ledger may carry.

    The claim is narrow on purpose: it is the exact fixture alias the certified
    e2e test uses, so a test run can prove the gate reaches the same verdict
    whether the claim comes from the allowlist or from the ledger.
    """
    from engine.mapping_evidence import Evidence, MappingLedger, team_alias_key

    ledger = MappingLedger(path)
    ledger.accept(
        "team_alias",
        team_alias_key(*POPULATED_LEDGER_ALIAS),
        [
            Evidence(
                type="exact_shared_fixture",
                detail={"seed": "N0-1 runtime isolation"},
                scan="test-runtime-isolation",
                books=("mbet", "wwin"),
            )
        ],
        "N0-1 test seed",
    )
    ledger.save()
    return path


@pytest.fixture
def populated_ledger(tmp_path: Path) -> Path:
    """A ledger carrying the one claim an operator's local ledger may carry."""
    return write_populated_ledger(tmp_path / "populated-ledger" / "mapping_evidence.json")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_deeplinks: run against the shipped config/bookmaker_deeplinks.json"
    )
    config.addinivalue_line(
        "markers",
        "real_runtime_state: read the operator's runtime state; requires "
        f"{REAL_STATE_ENV}=1",
    )
    config.addinivalue_line(
        "markers",
        "slow: opt-in load budget; requires BH_ARB_TEST_SLOW=1",
    )


@pytest.fixture(scope="session", autouse=True)
def _repository_runtime_state_untouched():
    """Fail the run if any test wrote into the checkout's runtime directories.

    This is the end-to-end half of the isolation rule: the per-test fixture
    redirects the paths, and this guard proves nothing slipped past it. It
    compares names, sizes and mtimes; it never reads or rewrites the files.
    """
    before = runtime_state_snapshot()
    yield
    after = runtime_state_snapshot()
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        path for path in set(before) & set(after) if before[path] != after[path]
    )
    if added or removed or changed:
        pytest.fail(
            "the test suite changed repository runtime state; redirect the write "
            "to tmp_path instead (N0-1): "
            f"added={added} removed={removed} changed={changed}"
        )


@pytest.fixture(autouse=True)
def _isolated_runtime_state(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
):
    """Redirect every generated runtime path into a per-test temporary tree.

    The temporary tree is created through ``tmp_path_factory`` rather than
    ``tmp_path`` so a test that asserts the exact contents of its own
    ``tmp_path`` still sees only what it created.
    """
    if request.node.get_closest_marker("real_runtime_state"):
        if os.getenv(REAL_STATE_ENV) != "1":
            pytest.skip(
                "reads the operator's runtime state; set "
                f"{REAL_STATE_ENV}=1 to run it against this machine's data"
            )
        yield
        return

    from config import settings
    from engine import mapping_evidence, matcher, structural_drift
    from server import api

    runtime = tmp_path_factory.mktemp("runtime")
    generated = runtime / "config" / "generated"
    cache = runtime / "cache"
    generated.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    ledger_path = generated / "mapping_evidence.json"
    if os.getenv(RUNTIME_LEDGER_ENV, "empty") == "populated":
        write_populated_ledger(ledger_path)

    monkeypatch.setattr(matcher, "MAPPING_EVIDENCE_FILE", str(ledger_path))
    monkeypatch.setattr(mapping_evidence, "DEFAULT_PATH", ledger_path)
    monkeypatch.setattr(
        structural_drift, "DEFAULT_PATH", generated / "wire_fingerprints.json"
    )
    monkeypatch.setattr(settings, "CACHE_DIR", str(cache))
    # SR3-4: no forensics artefacts during the suite unless a test enables them.
    monkeypatch.setattr(forensics, "FORENSICS_DIR", cache / "forensics")
    monkeypatch.setattr(forensics, "FORENSICS_ENABLED", False)
    monkeypatch.setattr(api, "CACHE_DIR", str(cache))
    # M1-1: every test gets a private key store. The operator's
    # config/generated/api_keys.json must never decide whether the suite's API
    # requests are authenticated.
    from server.auth import ApiKeyStore, auth_failures

    monkeypatch.setattr(api, "api_key_store", ApiKeyStore(str(cache / "api_keys.json")))
    # M1-3: the failed-attempt budget is process-wide; a previous test's wrong
    # keys must not 429 this test's first request.
    auth_failures.reset()
    monkeypatch.setenv("STORAGE_PATH", str(cache / "bh_arb.sqlite3"))
    for attribute, filename in _API_RUNTIME_FILES.items():
        monkeypatch.setattr(api, attribute, str(cache / filename))
    # Lazily-created stores must be rebuilt against the redirected STORAGE_PATH.
    for attribute in ("_storage", "_bet_store", "_paper_store"):
        monkeypatch.setattr(api, attribute, None)
    # N0-2 runtime state is per-test too: a previous test's price observations
    # must not decide whether this test's rows are frozen.
    monkeypatch.setattr(api, "_stale_price_store", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_stale_price_evidence", {"prematch": [], "live": []})
    monkeypatch.setattr(api, "_stale_price_checked_at", {"prematch": "", "live": ""})
    monkeypatch.setattr(api, "_closing_capture", {"prematch": {}, "live": {}})
    # N1-2 coverage diagnostics are per-test too: a previous test's trend or
    # consecutive zero counter must not decide whether this test alerts.
    monkeypatch.setattr(api, "_coverage_budget", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_coverage_history", {"prematch": [], "live": []})
    monkeypatch.setattr(api, "_cardinality", {"prematch": {}, "live": {}})
    monkeypatch.setattr(
        api, "_cardinality_history", {"prematch": [], "live": []}
    )
    monkeypatch.setattr(api, "_mapping_coverage", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_coverage_trend", {"prematch": [], "live": []})
    monkeypatch.setattr(api, "_zero_result_streaks", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_scan_cost", {"prematch": {}, "live": {}})
    monkeypatch.setattr(api, "_scan_cost_history", [])
    # N2-3 trends are per-test: a previous test's queue must not appear in this
    # test's recurring-blocker panel or strict-miss trend.
    monkeypatch.setattr(api, "_pairing_summary", {})
    monkeypatch.setattr(api, "_pairing_trend", {"prematch": [], "live": []})
    monkeypatch.setattr(
        api, "_candidate_blocker_trend", {"prematch": [], "live": []}
    )

    # M2-3: the cached /api/health summary is per-test; a previous test's scan
    # data must not decide what this test's diagnostics say.
    monkeypatch.setattr(api, "_health_cache", None)

    # A module that copied CACHE_DIR at import time keeps its own reference.
    verify_module = sys.modules.get("scripts.verify_deeplinks")
    if verify_module is not None:
        monkeypatch.setattr(verify_module, "CACHE_DIR", str(cache))

    yield


@pytest.fixture(autouse=True)
def _example_route_books(request, monkeypatch):
    _reset_deeplink_state()
    if request.node.get_closest_marker("real_deeplinks"):
        yield
        _reset_deeplink_state()
        return
    declared = dict(common._load_deeplink_config())
    declared.update(EXAMPLE_ROUTE_BOOKS)
    # Inject a synthetic map; with loaded_at left unset the file cannot replace
    # it, which is the seam these tests rely on.
    monkeypatch.setattr(common, "_deeplink_cache", declared)
    yield
    _reset_deeplink_state()
