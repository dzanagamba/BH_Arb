"""SR4-4: structural fingerprint and drift alarm.

WHAT THESE TESTS PROVE
----------------------
The wire schemas fail a book closed on a modelled change, but ``extra="allow"``
lets an unmodelled rename (a team field, a new envelope level) parse silently.
The structural fingerprint watches the whole raw payload instead:

* the same shape with different values has the same fingerprint;
* a renamed key, a type change or a removed level has a different one;
* numeric map keys (``{"<eventId>": bet}``) are collapsed to ``<id>``, so ids
  that change every request are not mistaken for renames;
* ``observe`` records the first informative shape, matches later ones, and on a
  change increments ``bh_wire_structure_drift_total``, logs the path diff and
  keeps the last good baseline (alert only, never a price change);
* the real MDShop scrape is wired: a value change is silent, an unmodelled new
  key raises the counter while the scrape still succeeds;
* the counter is rendered by ``/api/metrics``.

WHAT THESE TESTS DO NOT PROVE
-----------------------------
They do not prove the baseline is refreshed after a reviewed change; that is an
operator action (remove the entry from ``config/generated/wire_fingerprints.json``
or re-record it), as documented in the module.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from engine.structural_drift import (
    METRIC_STRUCTURE_DRIFT,
    baseline,
    fingerprint,
    observe,
    structural_paths,
)
from server.app import app
from server.observability import metrics

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "markets"


@pytest.fixture(autouse=True)
def _fresh_metrics():
    metrics.reset_values()
    yield
    metrics.reset_values()


def _capture(mode: str = "prematch") -> dict[str, Any]:
    path = FIXTURE_DIR / f"mdshop_{mode}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _envelope(bets: Any, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "id": 6917979,
        "name": "Home FC - Away FC",
        "dateTime": "2030-01-01T18:00:00",
        "sportId": 1,
        "competitionName": "Test League",
        "regionName": "Test Region",
        "isInOffer": True,
        "bets": bets,
    }
    event.update(extra or {})
    return {"events": [event]}


# ─── The fingerprint itself ─────────────────────────────────────────────────


def test_values_do_not_change_the_fingerprint():
    first = {"events": [{"id": 1, "home": "A", "price": 1.85, "live": False}]}
    second = {"events": [{"id": 2, "home": "B", "price": 9.99, "live": True}]}

    assert fingerprint(first) == fingerprint(second)


def test_a_renamed_key_changes_the_fingerprint():
    before = {"events": [{"id": 1, "home": "A"}]}
    after = {"events": [{"id": 1, "team": "A"}]}

    assert fingerprint(before) != fingerprint(after)
    assert "events[].home:string" in structural_paths(before)
    assert "events[].team:string" in structural_paths(after)


def test_a_type_change_changes_the_fingerprint():
    before = {"price": 1.85}
    after = {"price": "1.85"}

    assert fingerprint(before) != fingerprint(after)


def test_a_removed_level_changes_the_fingerprint():
    before = {"events": [{"bets": [{"price": 1.85}]}]}
    after = {"events": [{"bets": []}]}

    assert fingerprint(before) != fingerprint(after)


def test_numeric_map_keys_are_collapsed_to_an_id_placeholder():
    before = {"bets": [{"4680901": {"idBt": 95, "odds": []}}]}
    after = {"bets": [{"9999999": {"idBt": 95, "odds": []}}]}

    assert fingerprint(before) == fingerprint(after)
    assert "bets[].<id>.idBt:number" in structural_paths(before)


# ─── observe: baseline, match, alarm ────────────────────────────────────────


def test_the_first_informative_response_records_a_baseline(tmp_path):
    path = tmp_path / "wire_fingerprints.json"
    payload = {"events": [{"id": 1}]}

    result = observe("book", "endpoint", payload, path=path)

    assert result == "new"
    assert baseline(path)["book|endpoint"]["fingerprint"] == fingerprint(payload)
    assert path.exists()


def test_the_same_shape_matches_and_values_are_ignored(tmp_path):
    path = tmp_path / "wire_fingerprints.json"
    observe("book", "endpoint", {"events": [{"id": 1, "price": 1.5}]}, path=path)

    result = observe(
        "book", "endpoint", {"events": [{"id": 2, "price": 9.5}]}, path=path
    )

    assert result == "match"
    assert METRIC_STRUCTURE_DRIFT not in metrics.render()


def test_a_renamed_key_alerts_counters_and_keeps_the_last_good_baseline(
    tmp_path, caplog
):
    path = tmp_path / "wire_fingerprints.json"
    first = {"events": [{"id": 1, "home": "A"}]}
    observe("book", "endpoint", first, path=path)
    stored = baseline(path)["book|endpoint"]["fingerprint"]

    with caplog.at_level(logging.WARNING, logger="engine.structural_drift"):
        result = observe("book", "endpoint", {"events": [{"id": 1, "team": "A"}]}, path=path)

    assert result == "drift"
    assert (
        'bh_wire_structure_drift_total{book="book",endpoint="endpoint"} 1'
        in metrics.render()
    )
    assert "removed=events[].home:string" in caplog.text
    assert "added=events[].team:string" in caplog.text
    # The last good shape is kept: a second drifted run still alarms.
    assert baseline(path)["book|endpoint"]["fingerprint"] == stored
    assert observe("book", "endpoint", {"events": [{"id": 1, "team": "A"}]}, path=path) == "drift"


def test_an_empty_page_does_not_establish_a_baseline(tmp_path):
    path = tmp_path / "wire_fingerprints.json"

    assert observe("book", "endpoint", [], path=path) == "empty"
    assert observe("book", "endpoint", {"events": []}, path=path) == "empty"
    assert baseline(path) == {}


def test_an_unreadable_state_file_starts_from_an_empty_store(tmp_path):
    path = tmp_path / "wire_fingerprints.json"
    path.write_text("not json", encoding="utf-8")

    assert observe("book", "endpoint", {"events": [{"id": 1}]}, path=path) == "new"
    assert baseline(path)["book|endpoint"]


# ─── Adapter wiring and /api/metrics ────────────────────────────────────────


def _scrape_with(payload: Any):
    from scrapers.mdshop import MDShopScraper

    async def scenario():
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
            mock.get(
                url__startswith="https://mdoffer.mdshop.ba/api/offer/getwebevents"
            ).mock(return_value=httpx.Response(200, json=payload))
            return await MDShopScraper().scrape()

    return asyncio.run(scenario())


def test_the_real_scrape_ignores_a_value_change_and_alerts_on_a_new_key():
    capture = _capture()
    first = _scrape_with(_envelope(capture["bets"]))
    assert first

    # Same structure, different prices: no structural alarm.
    changed_values = json.loads(json.dumps(capture["bets"]))
    for bet in changed_values:
        for outcome in bet["betOutcomes"]:
            outcome["odd"] = outcome["odd"] + 1
    assert _scrape_with(_envelope(changed_values))

    assert METRIC_STRUCTURE_DRIFT not in metrics.render()

    # An unmodelled key parses (extra="allow") but is a structural change.
    assert _scrape_with(_envelope(changed_values, extra={"brandNewTeamField": "x"}))

    assert METRIC_STRUCTURE_DRIFT in metrics.render()


def test_the_api_metrics_endpoint_renders_the_drift_counter(tmp_path):
    path = tmp_path / "wire_fingerprints.json"
    observe("book", "endpoint", {"events": [{"id": 1}]}, path=path)
    observe("book", "endpoint", {"events": [{"id": 1, "new": True}]}, path=path)

    response = TestClient(app).get("/api/metrics")

    assert response.status_code == 200
    assert "bh_wire_structure_drift_total" in response.text
