"""Deep-link verification: the checker criterion and the `/api/verify-links` endpoint.

`verified` means every part of the claim is proven, INCLUDING the link, so this
module is the only place in the product allowed to set `deep_link_verified`.
Four rules bind every test here:

* a book that declares no per-event route is SKIPPED, never failed — there is
  nothing to check, and "we never tried" must not read as "we proved it wrong",
* a link is verified only when the event id is found as a whole token in a
  book-owned payload or in rendered page text — a page that merely echoed our
  own query parameter back is NOT evidence,
* the checker is on-demand and never runs inside a scan, and
* it never touches the candidate queue or the team alias allowlist.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from models.schemas import Market, MarketType, Match, OddsValue
from scripts import verify_deeplinks
from scripts.verify_deeplinks import (
    LinkOutcome,
    LinkReport,
    LinkTarget,
    apply_report,
    book_owned_host,
    build_targets,
    json_event_paths,
    payload_evidence,
    rendered_text_evidence,
    whole_token_span,
)
from server import api
from server.app import app

client = TestClient(app)

KICKOFF = datetime(2026, 9, 25, 18, 0)
EVENT_ID = "9984468"
EVENT_URL = f"https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/{EVENT_ID}"


def run(coro):
    return asyncio.run(coro)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


def _match(
    bookmaker: str = "mozzartbet",
    event_id: str = EVENT_ID,
    deep_link_verified: bool = False,
    home_team: str = "Lech Poznan",
    away_team: str = "Thun",
    league: str = "Liga Evrope",
    kickoff: datetime = KICKOFF,
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team=home_team,
        away_team=away_team,
        league=league,
        kickoff=kickoff,
        event_id=event_id,
        deep_link_verified=deep_link_verified,
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


def _cached(*matches: Match) -> list[dict]:
    return [m.model_dump(mode="json") for m in matches]


def _report(
    bookmaker: str = "mozzartbet",
    outcomes: list[LinkOutcome] | None = None,
    available: int | None = None,
    duration: float = 12.5,
    mode: str = "prematch",
) -> LinkReport:
    """A report exactly as `verify_bookmaker` fills one in, errors included."""
    outcomes = list(outcomes or [])
    return LinkReport(
        bookmaker=bookmaker,
        mode=mode,
        status="checked",
        skip_reason="",
        available=len(outcomes) if available is None else available,
        checked=len(outcomes),
        verified=sum(1 for o in outcomes if o.verified),
        failed=sum(1 for o in outcomes if o.error == "" and not o.verified),
        errored=sum(1 for o in outcomes if o.error),
        duration_seconds=duration,
        outcomes=outcomes,
    )


def _verified_outcome(event_id: str = EVENT_ID, url: str = EVENT_URL) -> LinkOutcome:
    return LinkOutcome(
        event_id=event_id,
        url=url,
        verified=True,
        evidence=f'book payload https://www.mozzartbet.ba/betting/match/{event_id} contains "{event_id}"',
        error="",
    )


def _failed_outcome(event_id: str = EVENT_ID, url: str = EVENT_URL) -> LinkOutcome:
    return LinkOutcome(
        event_id=event_id,
        url=url,
        verified=False,
        evidence="no book-owned payload or rendered text carried the event id",
        error="",
    )


def _error_outcome(event_id: str = EVENT_ID, url: str = EVENT_URL) -> LinkOutcome:
    return LinkOutcome(
        event_id=event_id,
        url=url,
        verified=False,
        evidence="",
        error="Timeout 60000ms exceeded",
    )


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch, tmp_path):
    """Keep the global scan/cache/verification state out of other test modules."""
    snapshot = {
        "prematch": list(api.cached_matches),
        "live": list(api.cached_live_matches),
        "surebets": list(api.cached_surebets),
        "live_surebets": list(api.cached_live_surebets),
        "report": list(api.cached_match_groups_report),
        "live_report": list(api.cached_live_match_groups_report),
        "pending": dict(api.pending_candidates),
        "enabled": dict(api._bookmaker_enabled),
        "status": api.scan_status.model_dump(),
        "live_status": api.live_status.model_dump(),
        "verifications": api._deep_link_verifications,
    }
    monkeypatch.setattr(
        api, "DEEP_LINK_VERIFICATIONS_FILE", str(tmp_path / "deep_link_verifications.json")
    )
    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "ALLOWLIST_FILE", str(tmp_path / "team_alias_allowlist.json"))
    api._deep_link_verifications = {}
    api.cached_matches.clear()
    api.cached_live_matches.clear()
    api._verify_link_request_times.clear()
    api._scan_request_times.clear()
    yield
    api.cached_matches[:] = snapshot["prematch"]
    api.cached_live_matches[:] = snapshot["live"]
    api.cached_surebets[:] = snapshot["surebets"]
    api.cached_live_surebets[:] = snapshot["live_surebets"]
    api.cached_match_groups_report[:] = snapshot["report"]
    api.cached_live_match_groups_report[:] = snapshot["live_report"]
    api.pending_candidates.clear()
    api.pending_candidates.update(snapshot["pending"])
    api._bookmaker_enabled.clear()
    api._bookmaker_enabled.update(snapshot["enabled"])
    for key, value in snapshot["status"].items():
        setattr(api.scan_status, key, value)
    for key, value in snapshot["live_status"].items():
        setattr(api.live_status, key, value)
    api._deep_link_verifications = snapshot["verifications"]
    api._verify_link_request_times.clear()
    api._scan_request_times.clear()


def _install_checker(monkeypatch, report: LinkReport | None = None, outcome=None):
    """Replace the browser seam; it must never launch Chromium in a test."""
    calls: list[dict] = []
    result = report
    if result is None:
        result = _report(outcomes=[outcome] if outcome is not None else [])

    async def fake(bookmaker, matches, *, mode, live, limit):
        calls.append(
            {
                "bookmaker": bookmaker,
                "matches": len(matches),
                "mode": mode,
                "live": live,
                "limit": limit,
            }
        )
        return result

    monkeypatch.setattr(api, "_run_link_verification", fake)
    return calls


# ─── 1. Endpoint contract ──────────────────────────────────────────────────────


def test_verify_links_requires_bookmaker_param():
    r = client.post("/api/verify-links")
    assert r.status_code == 400


def test_verify_links_rejects_a_blank_bookmaker_param():
    r = client.post("/api/verify-links?bookmaker=%20%20")
    assert r.status_code == 400


def test_verify_links_unknown_bookmaker_404():
    r = client.post("/api/verify-links?bookmaker=nosuchbook")
    assert r.status_code == 404


def test_verify_links_rejects_an_unknown_mode():
    r = client.post("/api/verify-links?bookmaker=mozzartbet&mode=sidelined")
    assert r.status_code == 400


def test_verify_links_rejects_a_negative_limit():
    r = client.post("/api/verify-links?bookmaker=mozzartbet&limit=-1")
    assert r.status_code == 400


def test_verify_links_caps_an_oversized_limit(monkeypatch):
    calls = _install_checker(monkeypatch)
    api.cached_matches.extend(_cached(_match()))

    r = client.post("/api/verify-links?bookmaker=mozzartbet&limit=100000")

    assert r.status_code == 200
    assert calls[0]["limit"] == api.DEEP_LINK_VERIFY_MAX_LIMIT


# ─── 2. A book with no declared event route is skipped, not failed ────────────


def test_book_without_a_declared_event_route_is_skipped_not_failed(monkeypatch):
    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("the checker launched a browser for a book with no event route")

    monkeypatch.setattr(api, "_run_link_verification", explode)
    api.cached_matches.extend(_cached(_match("wwin", "1234")))

    r = client.post("/api/verify-links?bookmaker=wwin")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "skipped"
    assert "no declared event route" in body["skip_reason"]
    assert body["checked"] == 0
    assert body["verified"] == 0
    assert body["failed"] == 0
    assert body["details"] == []


def test_a_skipped_book_never_gets_a_link_flag(monkeypatch):
    monkeypatch.setattr(
        api, "_run_link_verification", lambda *a, **k: pytest.fail("checker ran")
    )
    api.cached_matches.extend(_cached(_match("mbet", "1234")))

    client.post("/api/verify-links?bookmaker=mbet")

    assert [m["deep_link_verified"] for m in api.cached_matches] == [False]


def test_every_book_that_declares_support_is_checkable():
    from scrapers.common import supports_event_id

    for bookmaker in ("mdshop", "admiralbet", "mozzartbet"):
        assert supports_event_id(bookmaker), bookmaker
    for bookmaker in ("wwin", "mbet", "sportplus", "evlbet", "premier_kladionica", "betole"):
        assert not supports_event_id(bookmaker), bookmaker


# ─── 3. What "verified" means — the criterion itself ──────────────────────────


def test_an_echo_of_our_own_url_is_not_evidence():
    """The shell echoing `?event=<id>` back is what a dead id also produces."""
    echo = (
        '<iframe src="https://www.mdshop.ba/sport-site/sr/#/betting/prematch'
        f'?language=sr&amp;eventId={EVENT_ID}"></iframe>'
    )
    assert payload_evidence([(EVENT_URL, "text/html", echo)], EVENT_URL, EVENT_ID) == []
    assert rendered_text_evidence(echo, EVENT_ID) is None


def test_a_url_echo_in_visible_text_is_not_evidence():
    assert rendered_text_evidence(f"Otvori utakmicu {EVENT_URL} za detalje", EVENT_ID) is None


def test_the_event_id_in_a_book_owned_payload_is_evidence():
    """MEASURED: the Mozzartbet SPA asks for THIS event and the server resolves it.

    `/betting/match/9984468` returns ~328 KB beginning `{"match":{"id":9984468`,
    while the same route for an id in no feed returns 14 bytes.
    """
    body = f'{{"match":{{"id":{EVENT_ID},"rank":100,"filter":{{"matchId":{EVENT_ID}}}}}}}'
    found = payload_evidence(
        [(f"https://www.mozzartbet.ba/betting/match/{EVENT_ID}", "application/json", body)],
        EVENT_URL,
        EVENT_ID,
    )
    assert len(found) >= 1
    assert "$.match.id = 9984468" in found[0]
    assert f"betting/match/{EVENT_ID}" in found[0]


def test_a_config_number_that_merely_contains_the_id_is_not_evidence():
    """MEASURED FALSE PASS: MDShop's businessModel has "maxTotalOdd":999999999999.00.

    A dead event id verified against that payload, which is exactly the soft pass
    this criterion must not be. A JSON float under a settings key names no event.
    """
    body = '{"settings":{"maxTotalOdd":999999999999.00,"maxStake":15000.00}}'
    assert payload_evidence(
        [("https://mdoffer.mdshop.ba/api/SlowCache/businessModel/1678",
          "application/json", body)],
        "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=999999999999",
        "999999999999",
    ) == []


def test_a_value_under_a_key_that_does_not_name_an_event_is_not_evidence():
    body = f'{{"settings":{{"displayNumberFormat":{EVENT_ID}}}}}'
    assert payload_evidence(
        [("https://www.mdshop.ba/api/x.json", "application/json", body)],
        EVENT_URL,
        EVENT_ID,
    ) == []


def test_an_event_key_with_a_different_value_is_not_evidence():
    body = '{"match":{"id":1234567,"eventName":"Lech - Thun"}}'
    assert payload_evidence(
        [("https://www.mozzartbet.ba/betting/match/1234567", "application/json", body)],
        EVENT_URL,
        EVENT_ID,
    ) == []


def test_a_nsoft_event_id_field_is_not_enough():
    """MEASURED FALSE PASS: Admiralbet's `bonus-tickets-with-details` payload.

    That 29 KB payload is fetched on EVERY page load, with and without
    `?event=`, and it happens to list the events that have a bonus ticket — so
    2 of 6 checks "verified" for a link that did nothing. The id in a payload
    the page fetches anyway says the id is in the feed, not that our link
    reached it, so an event-scoped request is required.
    """
    body = (
        '{"bonusTicketItems":[{"betTypeId":135,"betName":"Kona\\u010dan ishod","sbv":null,'
        f'"eventId":{EVENT_ID},"eventName":"Cambridge Utd - AFC Wimble"}}]}}'
    )
    assert payload_evidence(
        [("https://sport.admiralbet.ba/set-api-rs/api/webclient/bonus-tickets-with-details",
          "application/json", body)],
        EVENT_URL,
        EVENT_ID,
    ) == []


def test_a_dead_id_whose_own_endpoint_returns_nothing_is_not_evidence():
    """MEASURED: `/betting/match/<dead id>` answers HTTP 200 with 14 bytes."""
    assert payload_evidence(
        [("https://www.mozzartbet.ba/betting/match/999999999999", "application/json", "")],
        "https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/999999999999",
        "999999999999",
    ) == []


def test_a_body_that_is_not_json_is_never_payload_evidence():
    assert payload_evidence(
        [("https://www.mozzartbet.ba/betting/match/1", "application/json", f"id={EVENT_ID}")],
        EVENT_URL,
        EVENT_ID,
    ) == []


def test_a_longer_number_containing_the_id_is_not_evidence():
    body = '{"match":{"id":199844681}}'
    assert payload_evidence(
        [("https://www.mozzartbet.ba/betting/match/1", "application/json", body)],
        EVENT_URL,
        EVENT_ID,
    ) == []


def test_a_control_dead_id_never_verifies_on_the_nsoft_shell():
    """The end-to-end control: the id that is in no feed, checked as a payload."""
    body = (
        '{"businessModel":{"maxTotalOdd":999999999999.00,"maxEventsInCombination":20,'
        '"ticketTypes":[1,2,3]}}'
    )
    assert payload_evidence(
        [("https://mdoffer.mdshop.ba/api/SlowCache/businessModel/1678",
          "application/json", body)],
        "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=999999999999",
        "999999999999",
    ) == []


def test_a_third_party_host_is_never_evidence():
    body = f'{{"id":{EVENT_ID}}}'
    assert payload_evidence(
        [("https://bat.bing.com/bat.js", "application/javascript", body)],
        EVENT_URL,
        EVENT_ID,
    ) == []


def test_a_book_owned_subdomain_is_evidence():
    assert book_owned_host("https://mdoffer.mdshop.ba/api/x", "https://www.mdshop.ba")
    assert book_owned_host("https://www.mozzartbet.ba/betting/match/1", "https://www.mozzartbet.ba")
    assert not book_owned_host("https://bidswitch.net/sync", "https://www.admiralbet.ba")
    assert not book_owned_host("https://evil-mdshop.ba.attacker.test/x", "https://www.mdshop.ba")


def test_an_html_response_is_never_payload_evidence():
    """Only JSON answers count; an HTML document is where the echo lives."""
    body = f"<html><body>event {EVENT_ID}</body></html>"
    assert payload_evidence(
        [(EVENT_URL, "text/html; charset=utf-8", body)], EVENT_URL, EVENT_ID
    ) == []


def test_the_event_id_as_a_standalone_word_in_text_is_evidence():
    assert rendered_text_evidence(f"MATCH ID: {EVENT_ID}\nLech Poznan - Thun", EVENT_ID)


def test_whole_token_span_only_matches_standalone_occurrences():
    assert whole_token_span(f'{{"id":{EVENT_ID}}}', EVENT_ID) is not None
    assert whole_token_span(f'{{"id":{EVENT_ID}1}}', EVENT_ID) is None
    assert whole_token_span(f'{{"id":1{EVENT_ID}}}', EVENT_ID) is None


# ─── 4. The write-back: verified, cleared, and errors ──────────────────────────


def test_a_proven_link_marks_the_cached_match(monkeypatch):
    _install_checker(monkeypatch, _report(outcomes=[_verified_outcome()]))
    api.cached_matches.extend(_cached(_match()))

    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 200
    assert api.cached_matches[0]["deep_link_verified"] is True
    assert r.json()["verified"] == 1
    assert r.json()["failed"] == 0


def test_a_completed_check_that_finds_nothing_stays_unverified(monkeypatch):
    _install_checker(monkeypatch, _report(outcomes=[_failed_outcome()]))
    api.cached_matches.extend(_cached(_match()))

    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 200
    assert api.cached_matches[0]["deep_link_verified"] is False
    assert r.json()["failed"] == 1
    assert r.json()["verified"] == 0


def test_a_stale_verification_is_cleared_by_a_later_failed_check(monkeypatch):
    api.cached_matches.extend(_cached(_match(deep_link_verified=True)))
    _record(EVENT_ID, verified=True, age_seconds=60)
    assert api.cached_matches[0]["deep_link_verified"] is True

    _install_checker(monkeypatch, _report(outcomes=[_failed_outcome()]))
    client.post("/api/verify-links?bookmaker=mozzartbet")

    assert api.cached_matches[0]["deep_link_verified"] is False
    assert f"mozzartbet|{EVENT_ID}" not in api._deep_link_verifications["prematch"]


def test_a_navigation_error_is_not_a_failed_check(monkeypatch):
    """Absence of evidence is not evidence of absence: a timeout must not clear."""
    api.cached_matches.extend(_cached(_match(deep_link_verified=True)))
    _record(EVENT_ID, verified=True, age_seconds=60)

    _install_checker(monkeypatch, _report(outcomes=[_error_outcome()]))
    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 200
    assert api.cached_matches[0]["deep_link_verified"] is True
    assert f"mozzartbet|{EVENT_ID}" in api._deep_link_verifications["prematch"]
    assert r.json()["failed"] == 0
    assert r.json()["details"][0]["error"]


def test_apply_report_reports_how_many_matches_it_changed():
    matches = _cached(
        _match(), _match(event_id="1", deep_link_verified=True), _match(event_id="2")
    )
    outcomes = [_verified_outcome(), _failed_outcome(event_id="1", url="u1")]

    changed = apply_report(matches, _report(outcomes=outcomes, available=2))

    assert changed == 2
    assert [m["deep_link_verified"] for m in matches] == [True, False, False]


# ─── 5. The cost is visible, and the checker is not in the scan path ───────────


def test_the_response_shows_what_the_check_cost(monkeypatch):
    _install_checker(
        monkeypatch, _report(outcomes=[_verified_outcome()], available=3, duration=9.25)
    )
    api.cached_matches.extend(
        _cached(_match(), _match(event_id="1"), _match(event_id="2"))
    )

    body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=1").json()

    assert body["duration_seconds"] == 9.25
    assert body["available"] == 3
    assert body["checked"] == 1
    assert body["unchecked"] == 2
    assert body["criterion"] == verify_deeplinks.CRITERION


def test_the_checker_never_runs_inside_a_scan(monkeypatch):
    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("the deep-link checker ran inside run_scan")

    monkeypatch.setattr(api, "_run_link_verification", explode)
    _stub_scan(
        monkeypatch,
        {"mozzartbet": [_match("mozzartbet")], "mdshop": [_match("mdshop", "6828117")]},
    )

    run(api.run_scan("prematch"))

    assert api.cached_matches, "the scan itself still ran"
    assert all(m["deep_link_verified"] is False for m in api.cached_matches)


def test_a_stored_verification_reaches_the_next_scan(monkeypatch):
    _record("9984468", verified=True, age_seconds=120)
    _record("6828117", verified=True, age_seconds=120, bookmaker="mdshop")
    _stub_scan(
        monkeypatch,
        {"mozzartbet": [_match("mozzartbet")], "mdshop": [_match("mdshop", "6828117")]},
    )

    run(api.run_scan("prematch"))

    assert [m["deep_link_verified"] for m in api.cached_matches] == [True, True]


def test_a_stored_verification_unblocks_a_verified_group(monkeypatch):
    """The whole point: with links proven the gate can reach `verified`."""
    _record("9984468", verified=True, age_seconds=120)
    _record("6828117", verified=True, age_seconds=120, bookmaker="mdshop")
    _stub_scan(
        monkeypatch,
        {"mozzartbet": [_match("mozzartbet")], "mdshop": [_match("mdshop", "6828117")]},
    )

    run(api.run_scan("prematch"))

    assert api.cached_match_groups_report, "no group was produced"
    assert api.cached_match_groups_report[0]["status"] == "verified"


def test_an_expired_verification_is_ignored_and_dropped(monkeypatch):
    stale = timedelta(seconds=api.DEEP_LINK_VERIFICATION_TTL_SECONDS + 60)
    _record(EVENT_ID, verified=True, age_seconds=stale.total_seconds())
    api.cached_matches.extend(_cached(_match()))

    applied = api._apply_deep_link_verifications(api.cached_matches, "prematch")

    assert applied == 0
    assert api.cached_matches[0]["deep_link_verified"] is False
    assert f"mozzartbet|{EVENT_ID}" not in api._deep_link_verifications["prematch"]


def test_live_and_prematch_verifications_are_separate(monkeypatch):
    _record(EVENT_ID, verified=True, age_seconds=60, mode="live")
    api.cached_live_matches.extend(_cached(_match(deep_link_verified=False)))

    assert api._apply_deep_link_verifications(api.cached_live_matches, "live") == 1
    assert api._apply_deep_link_verifications(api.cached_matches, "prematch") == 0


def test_verification_survives_a_cache_reload(monkeypatch, tmp_path):
    """A restart must not silently demote every group back to link_unverified."""
    cache_file = tmp_path / "last_scan.json"
    cache_file.write_text(
        json.dumps(
            {
                "surebets": [],
                "matches": _cached(_match()),
                "scan_time": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "_PREMATCH_CACHE_FILE", str(cache_file))
    monkeypatch.setattr(api, "_LIVE_CACHE_FILE", str(tmp_path / "last_live_scan.json"))
    _record(EVENT_ID, verified=True, age_seconds=60)
    api.cached_matches.clear()

    api._load_cache()

    assert len(api.cached_matches) == 1
    assert api.cached_matches[0]["deep_link_verified"] is True


# ─── 6. The endpoint touches nothing it has no business touching ───────────────


def test_verifying_links_does_not_touch_the_candidate_queue_or_allowlist(monkeypatch):
    candidate = api.pending_candidates.get("x")
    api.pending_candidates["x"] = candidate if candidate is not None else object()  # type: ignore[assignment]
    api._suppressed_candidates["x"] = "rejected"
    monkeypatch.setattr(api, "_suppress_candidate", lambda *a, **k: None)
    with open(api.ALLOWLIST_FILE, "w", encoding="utf-8") as file:
        json.dump({"aliases": ["Lech P.|Lech Poznan"]}, file)
    _install_checker(monkeypatch, _report(outcomes=[_verified_outcome()]))
    api.cached_matches.extend(_cached(_match()))

    client.post("/api/verify-links?bookmaker=mozzartbet")

    assert set(api.pending_candidates) == {"x"}
    assert api._suppressed_candidates == {"x": "rejected"}
    with open(api.ALLOWLIST_FILE, encoding="utf-8") as file:
        assert json.load(file)["aliases"] == ["Lech P.|Lech Poznan"]


def test_verifying_links_is_refused_while_a_scan_runs(monkeypatch):
    _install_checker(monkeypatch)
    api.scan_status.is_scanning = True

    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 409


def test_only_the_matching_bookmaker_is_touched(monkeypatch):
    _install_checker(monkeypatch, _report(outcomes=[_verified_outcome()]))
    api.cached_matches.extend(_cached(_match("mozzartbet"), _match("mdshop", "6828117")))

    client.post("/api/verify-links?bookmaker=mozzartbet")

    assert api.cached_matches[0]["deep_link_verified"] is True
    assert api.cached_matches[1]["deep_link_verified"] is False


# ─── 7. Target building ───────────────────────────────────────────────────────


def test_targets_are_built_from_the_declared_template():
    targets = build_targets(_cached(_match()), "mozzartbet", "https://www.mozzartbet.ba")
    assert targets == [LinkTarget(event_id=EVENT_ID, url=EVENT_URL)]


def test_a_book_with_no_event_ids_never_launches_a_browser(monkeypatch):
    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("a browser was launched with nothing to check")

    monkeypatch.setattr("scrapers.base.launch_browser", explode)
    matches = _cached(_match(event_id=""), _match("mbet", "1"))

    report = run(verify_deeplinks.verify_bookmaker("mozzartbet", matches, limit=3))

    assert report.checked == 0
    assert report.available == 0
    assert report.status == "checked"


def test_a_book_with_no_declared_route_never_launches_a_browser(monkeypatch):
    def explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("a browser was launched for a book with no event route")

    monkeypatch.setattr("scrapers.base.launch_browser", explode)

    report = run(verify_deeplinks.verify_bookmaker("wwin", _cached(_match("wwin", "1"))))

    assert report.status == "skipped"
    assert "no declared event route" in report.skip_reason
    assert report.checked == 0


def test_targets_ignore_matches_without_an_event_id():
    targets = build_targets(
        _cached(_match(event_id=""), _match(event_id="42")), "mozzartbet", "https://x.test"
    )
    assert [t.event_id for t in targets] == ["42"]


def test_targets_are_capped_by_the_limit():
    matches = _cached(*[_match(event_id=str(i)) for i in range(30)])
    targets = build_targets(matches, "mozzartbet", "https://www.mozzartbet.ba", limit=4)
    assert len(targets) == 4


def test_the_live_template_is_used_for_a_live_check():
    targets = build_targets(
        _cached(_match("mdshop")),
        "mdshop",
        "https://www.mdshop.ba",
        live=True,
    )
    assert targets[0].url == f"https://www.mdshop.ba/sport-live?event={EVENT_ID}"


# ─── 8. The load-bearing assumption: SUBFRAMES are examined ─────────────────────
#
# The whole finding of this task is that the NSoft product renders inside an
# IFRAME and that the evidence for or against an event lives there, not in the
# shell. A check that only ever looked at the main frame would report "no
# evidence" for every event and would INVERT the conclusion. These tests make
# that regression unshippable: narrow `page.on("response")` to the main frame, or
# drop the `page.frames` loop, and they fail.


class FakeFrame:
    """A frame as `check_target` uses it: a url, and readable body text."""

    def __init__(self, url: str, text: str = ""):
        self.url = url
        self._text = text

    async def inner_text(self, selector: str) -> str:
        if not self._text:
            raise AssertionError("frame has no text to read")
        return self._text

    async def content(self) -> str:
        return self._text


class FakeResponse:
    """A captured response, tagged with the frame it came from."""

    def __init__(
        self,
        url: str,
        body: str,
        frame: FakeFrame,
        content_type: str = "application/json",
    ):
        self.url = url
        self._body = body
        self.frame = frame
        self.headers = {"content-type": content_type}
        self.status = 200

    async def text(self) -> str:
        return self._body


class FakePage:
    """The minimum Page surface `check_target` touches, with real frames."""

    def __init__(
        self,
        main_frame: FakeFrame,
        responses: list[FakeResponse] | None = None,
        subframes: list[FakeFrame] | None = None,
        fail_urls: set[str] | None = None,
    ):
        self.main_frame = main_frame
        self.frames = [main_frame, *(subframes or [])]
        self._responses = responses or []
        self._handlers: list = []
        self.goto_calls: list[str] = []
        self.fail_urls = fail_urls or set()
        self.closed = False

    def on(self, event: str, handler) -> None:
        if event == "response":
            self._handlers.append(handler)

    def remove_listener(self, event: str, handler) -> None:
        if event == "response" and handler in self._handlers:
            self._handlers.remove(handler)

    def set_default_navigation_timeout(self, ms: int) -> None:
        return None

    async def goto(
        self, url: str, wait_until: str = "load", timeout: int = 0
    ) -> FakeResponse:
        self.goto_calls.append(url)
        if url in self.fail_urls:
            raise TimeoutError(f"Timeout {timeout}ms exceeded")
        # Playwright's async event emitter schedules a coroutine handler, so the
        # fake does the same rather than calling it synchronously.
        scheduled = [
            asyncio.ensure_future(handler(response))
            for response in self._responses
            for handler in list(self._handlers)
        ]
        if scheduled:
            await asyncio.gather(*scheduled)
        return FakeResponse(url, "", self.main_frame, "text/html")

    async def wait_for_timeout(self, ms: int) -> None:
        return None


class FakeContext:
    def __init__(self, page: FakePage):
        self._page = page
        self.closed = False

    async def new_page(self) -> FakePage:
        return self._page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext):
        self._context = context
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _install_fake_browser(monkeypatch, page: FakePage) -> FakePlaywright:
    """Point `launch_browser` at a fake page so a real `verify_bookmaker` runs."""
    context = FakeContext(page)
    browser = FakeBrowser(context)
    playwright = FakePlaywright()

    async def fake_launch():
        return playwright, browser, context

    monkeypatch.setattr("scrapers.base.launch_browser", fake_launch)
    return playwright


def _check(page: FakePage, event_id: str = EVENT_ID, url: str = EVENT_URL, base: str | None = None):
    return run(
        verify_deeplinks.check_target(
            page, LinkTarget(event_id=event_id, url=url), base or "https://www.mozzartbet.ba"
        )
    )


def test_a_subframe_response_proves_the_link():
    """The evidence can arrive from an IFRAME, and it must count."""
    shell = FakeFrame("https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/9984468")
    product = FakeFrame("https://www.mozzartbet.ba/betting/#/match")
    body = f'{{"match":{{"id":{EVENT_ID},"eventName":"Lech Poznan - Thun"}}}}'
    response = FakeResponse(
        f"https://www.mozzartbet.ba/betting/match/{EVENT_ID}", body, product
    )
    page = FakePage(shell, [response], subframes=[product])

    outcome = _check(page)

    assert outcome.verified is True, outcome.evidence
    assert f"betting/match/{EVENT_ID}" in outcome.evidence


def test_a_main_frame_response_still_proves_the_link():
    shell = FakeFrame(EVENT_URL)
    body = f'{{"match":{{"id":{EVENT_ID}}}}}'
    response = FakeResponse(
        f"https://www.mozzartbet.ba/betting/match/{EVENT_ID}", body, shell
    )
    page = FakePage(shell, [response])

    assert _check(page).verified is True


def test_a_subframe_does_not_make_a_third_party_response_evidence():
    """Subframes are examined; the book-owned host rule still applies to them."""
    shell = FakeFrame(EVENT_URL)
    iframe = FakeFrame("https://ads.example/x")
    body = f'{{"match":{{"id":{EVENT_ID}}}}}'
    response = FakeResponse(f"https://ads.example/betting/match/{EVENT_ID}", body, iframe)
    page = FakePage(shell, [response], subframes=[iframe])

    assert _check(page).verified is False


def test_rendered_text_of_a_subframe_proves_the_link():
    shell = FakeFrame(EVENT_URL, text="Klađenje Uživo Slot Registracija")
    product = FakeFrame(
        "https://www.mozzartbet.ba/sport-site/#/betting",
        text=f"Cambridge Utd - AFC Wimbledon\nID utakmice: {EVENT_ID}\n1 2.10  X 3.30",
    )
    page = FakePage(shell, subframes=[product])

    outcome = _check(page)

    assert outcome.verified is True, outcome.evidence
    assert "rendered page text" in outcome.evidence


def test_rendered_text_of_the_main_frame_still_proves_the_link():
    page = FakePage(FakeFrame(EVENT_URL, text=f"Utakmica {EVENT_ID}"), [])
    assert _check(page).verified is True


def test_a_subframe_showing_our_own_url_is_not_evidence():
    """The echo lives in the shell's iframe src, and the NSoft iframe's own
    render never repeats the id — a subframe showing the URL proves nothing."""
    shell = FakeFrame(EVENT_URL, text="sport-prematch")
    product = FakeFrame(
        f"https://www.mdshop.ba/sport-site/sr/#/betting/prematch?eventId={EVENT_ID}",
        text="Fudbal 648 Košarka 184",
    )
    page = FakePage(shell, subframes=[product])

    outcome = _check(
        page,
        url=f"https://www.mdshop.ba/sport-prematch?sport=Fudbal&event={EVENT_ID}",
        base="https://www.mdshop.ba",
    )

    assert outcome.verified is False, outcome.evidence


# ─── 9. Throttling, browser concurrency, and the post-await re-check ──────────
#
# This endpoint launches a real browser against third-party bookmaker sites for
# minutes at a time, and `_require_api_key` is a no-op unless API_KEY is set, so
# it must throttle itself. A lock only SERIALISES: a flood would queue N full
# runs instead of being refused.


def test_verify_links_is_throttled_with_a_429(monkeypatch):
    _install_checker(monkeypatch)
    api.cached_matches.extend(_cached(_match()))

    for _ in range(api.DEEP_LINK_VERIFY_RATE_LIMIT):
        assert client.post("/api/verify-links?bookmaker=mozzartbet").status_code == 200

    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 429
    assert "Rate limit" in r.json()["detail"]


def test_a_throttled_call_does_not_run_the_checker(monkeypatch):
    calls = _install_checker(monkeypatch)
    api.cached_matches.extend(_cached(_match()))
    for _ in range(api.DEEP_LINK_VERIFY_RATE_LIMIT):
        client.post("/api/verify-links?bookmaker=mozzartbet")

    client.post("/api/verify-links?bookmaker=mozzartbet")

    assert len(calls) == api.DEEP_LINK_VERIFY_RATE_LIMIT


def test_the_scan_and_verify_link_budgets_are_separate(monkeypatch):
    """Reusing the window must not let a scan flood consume the check budget."""
    assert api._verify_link_request_times is not api._scan_request_times

    class FakeRequest:
        client = type("C", (), {"host": "10.0.0.9"})()

    for _ in range(3):
        api._enforce_sliding_window(
            FakeRequest(), api._scan_request_times, 3, "scans"  # type: ignore[arg-type]
        )
    with pytest.raises(HTTPException) as scan_blocked:
        api._enforce_sliding_window(
            FakeRequest(), api._scan_request_times, 3, "scans"  # type: ignore[arg-type]
        )
    assert scan_blocked.value.status_code == 429
    assert "scans" in scan_blocked.value.detail

    # The scan budget is spent; the check budget is untouched and still works.
    _install_checker(monkeypatch)
    api.cached_matches.extend(_cached(_match()))
    assert client.post("/api/verify-links?bookmaker=mozzartbet").status_code == 200

    with pytest.raises(HTTPException) as checks_blocked:
        for _ in range(10):
            api._enforce_sliding_window(
                FakeRequest(),
                api._verify_link_request_times,  # type: ignore[arg-type]
                api.DEEP_LINK_VERIFY_RATE_LIMIT,
                "verify-links checks",
            )
    assert checks_blocked.value.status_code == 429
    assert "verify-links" in checks_blocked.value.detail


def test_the_check_runs_inside_the_browser_semaphore(monkeypatch):
    """Browser concurrency must stay bounded by BROWSER_CONCURRENCY, like a scan."""
    held: list[int] = []

    class RecordingSemaphore:
        """Wraps the real semaphore so a test can see it was held, not just used."""

        def __init__(self, inner):
            self.inner = inner
            self.acquired = 0
            self.released = 0

        async def acquire(self) -> None:
            await self.inner.acquire()
            self.acquired += 1
            held.append(self.acquired)

        def release(self) -> None:
            self.released += 1
            self.inner.release()

        def locked(self) -> bool:
            return self.inner.locked()

        async def __aenter__(self) -> "RecordingSemaphore":
            await self.acquire()
            return self

        async def __aexit__(self, *exc_info) -> None:
            self.release()

    real_sem = api._browser_sem
    recorder = RecordingSemaphore(real_sem)
    monkeypatch.setattr(api, "_browser_sem", recorder)

    async def fake(bookmaker, matches, *, mode, live, limit):
        return _report(outcomes=[_verified_outcome()])

    monkeypatch.setattr(api, "_run_link_verification", fake)
    api.cached_matches.extend(_cached(_match()))

    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 200
    assert held == [1], "the check ran without holding the browser semaphore"
    assert recorder.released == 1, "the browser semaphore leaked"
    assert recorder.locked() is False
    # The real semaphore is back to BROWSER_CONCURRENCY free slots.
    assert real_sem._value == api.BROWSER_CONCURRENCY


def test_a_scan_that_starts_during_the_check_skips_the_cache_write(monkeypatch):
    saves: list[str] = []

    async def fake(bookmaker, matches, *, mode, live, limit):
        api.scan_status.is_scanning = True  # a scan starts while we navigate
        return _report(outcomes=[_verified_outcome()])

    monkeypatch.setattr(api, "_run_link_verification", fake)
    monkeypatch.setattr(api, "_save_cache", lambda mode="prematch": saves.append(mode))
    api.cached_matches.extend(_cached(_match()))

    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False
    assert "scan" in body["applied_note"]
    assert saves == [], "a concurrent scan must not be overwritten"
    assert api.cached_matches[0]["deep_link_verified"] is False


def test_the_proof_is_still_recorded_when_the_cache_write_is_skipped(monkeypatch):
    """Skipping the cache write must not throw the proof away: the store is
    per-event, TTL'd and written atomically, and the next scan will apply it."""

    async def fake(bookmaker, matches, *, mode, live, limit):
        api.scan_status.is_scanning = True
        return _report(outcomes=[_verified_outcome()])

    monkeypatch.setattr(api, "_run_link_verification", fake)
    api.cached_matches.extend(_cached(_match()))

    client.post("/api/verify-links?bookmaker=mozzartbet")

    assert f"mozzartbet|{EVENT_ID}" in api._deep_link_verifications["prematch"]


def test_a_normal_run_reports_that_it_applied(monkeypatch):
    _install_checker(monkeypatch, _report(outcomes=[_verified_outcome()]))
    api.cached_matches.extend(_cached(_match()))

    body = client.post("/api/verify-links?bookmaker=mozzartbet").json()

    assert body["applied"] is True
    assert body["applied_note"] == ""


# `applied` has three states and they must be distinguishable: None = there was
# nothing to write, False = a write was suppressed, True = it happened.


def test_nothing_to_check_is_not_reported_as_a_suppressed_write(monkeypatch):
    """A skipped book did no work; that is not a write somebody suppressed."""
    monkeypatch.setattr(api, "_run_link_verification", lambda *a, **k: pytest.fail("ran"))
    api.cached_matches.extend(_cached(_match("wwin", "1")))

    body = client.post("/api/verify-links?bookmaker=wwin").json()

    assert body["status"] == "skipped"
    assert body["applied"] is None
    assert body["applied_note"] == ""


def test_an_empty_cache_is_not_reported_as_a_suppressed_write(monkeypatch):
    """Same for a declared book with no event ids in the cache: nothing to write."""
    monkeypatch.setattr(api, "_run_link_verification", lambda *a, **k: pytest.fail("ran"))
    api.cached_matches.extend(_cached(_match(event_id="")))

    body = client.post("/api/verify-links?bookmaker=mozzartbet").json()

    assert body["checked"] == 0
    assert body["applied"] is None


def test_a_suppressed_write_says_what_it_defers(monkeypatch):
    """`applied: False` is a real suppression, and it is not symmetric.

    `_apply_deep_link_verifications` only ever SETS a flag, so skipping the write
    defers a positive verdict to the next scan (the record is durable) — but a
    completed-FAIL pops the record and leaves a stale `True` in the cache until a
    scan rebuilds the list from the scrapers. The note must say both.
    """

    async def fake(bookmaker, matches, *, mode, live, limit):
        api.scan_status.is_scanning = True
        return _report(outcomes=[_verified_outcome()])

    monkeypatch.setattr(api, "_run_link_verification", fake)
    api.cached_matches.extend(_cached(_match()))

    note = client.post("/api/verify-links?bookmaker=mozzartbet").json()["applied_note"]

    assert "next scan will apply it" in note
    assert "demote" in note, "the one-sided effect of a skipped write must be stated"


def test_a_zero_work_call_does_not_spend_the_throttle_budget(monkeypatch):
    """B4: `?bookmaker=wwin` costs nothing, so it must not burn the budget.

    A UI that probes which books are checkable would otherwise self-DoS.
    """
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 1)
    monkeypatch.setattr(api, "_run_link_verification", lambda *a, **k: pytest.fail("ran"))
    api.cached_matches.extend(_cached(_match("wwin", "1")))

    for _ in range(5):
        assert client.post("/api/verify-links?bookmaker=wwin").status_code == 200

    _install_checker(monkeypatch, _report(outcomes=[_verified_outcome()]))
    api.cached_matches.append(_cached(_match())[0])
    assert client.post("/api/verify-links?bookmaker=mozzartbet").status_code == 200


def test_an_empty_cache_call_does_not_spend_the_throttle_budget(monkeypatch):
    """B4 again, for the other zero-work early return."""
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 1)
    monkeypatch.setattr(api, "_run_link_verification", lambda *a, **k: pytest.fail("ran"))
    api.cached_matches.extend(_cached(_match(event_id="")))

    for _ in range(5):
        assert client.post("/api/verify-links?bookmaker=mozzartbet").status_code == 200


def test_a_zero_limit_disables_the_throttle(monkeypatch):
    """B8: `DEEP_LINK_VERIFY_RATE_LIMIT=0` is documented as disabling the limit,
    so the disabled path must actually work rather than 429 on the first call."""
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 0)
    calls = _install_checker(monkeypatch)
    api.cached_matches.extend(_cached(_match()))

    for _ in range(6):
        assert client.post("/api/verify-links?bookmaker=mozzartbet").status_code == 200

    assert len(calls) == 6


# ─── 10. The event-id key rule, and the arithmetic of the summary ─────────────


@pytest.mark.parametrize(
    "key",
    ["id", "ID", "eventId", "matchId", "event_id", "match_id", "gameId", "fixtureId",
     "originalEventId", "parentMatchId"],
)
def test_keys_that_name_an_event_are_accepted(key):
    assert json_event_paths(f'{{"{key}":{EVENT_ID}}}', EVENT_ID) != []


@pytest.mark.parametrize(
    "key", ["paid", "valid", "grid", "void", "uuid", "selectionId", "oddsId"]
)
def test_keys_that_merely_look_like_id_keys_are_not_accepted(key):
    """`paid`/`valid`/`grid`/`void`/`uuid` all end in "id" and none is an event."""
    assert json_event_paths(f'{{"{key}":{EVENT_ID}}}', EVENT_ID) == []


@pytest.mark.parametrize("key", ["maxTotalOdd", "displayNumberFormat", "maxStake"])
def test_settings_keys_are_not_accepted(key):
    """Neither of these ends in "id" either; the key rule rejected the measured
    `maxTotalOdd` control, not the float rule. See report §5."""
    assert json_event_paths(f'{{"settings":{{"{key}":{EVENT_ID}}}}}', EVENT_ID) == []


def test_the_key_sets_have_no_redundant_entries():
    """`EVENT_ID_KEYS` and `EVENT_ID_KEY_SUFFIXES` must not overlap: an entry in
    both is dead weight that reads as if it does something."""
    suffixes = set(verify_deeplinks.EVENT_ID_KEY_SUFFIXES)
    assert not (set(verify_deeplinks.EVENT_ID_KEYS) & suffixes)
    for entry in set(verify_deeplinks.EVENT_ID_KEYS) | suffixes:
        assert verify_deeplinks.is_event_id_key(entry), entry


def test_both_rate_limits_share_one_window_constant(monkeypatch):
    """B3: the SCAN window length must not be derived from a deep-link knob.

    The defect was `RATE_LIMIT_WINDOW_SECONDS = DEEP_LINK_VERIFY_RATE_WINDOW_SECONDS`,
    so tuning the check's window silently moved the scan's. The value now comes
    from a shared setting, and the derivation is asserted absent.
    """
    import inspect

    import config.settings as settings

    assert "RATE_LIMIT_WINDOW_SECONDS" in vars(settings)
    assert api.RATE_LIMIT_WINDOW_SECONDS == settings.RATE_LIMIT_WINDOW_SECONDS == 60
    assert (
        "RATE_LIMIT_WINDOW_SECONDS = DEEP_LINK_VERIFY_RATE_WINDOW_SECONDS"
        not in inspect.getsource(api)
    )


def test_errored_checks_are_counted_by_a_real_verify_bookmaker_run(monkeypatch):
    """The ONLY test of the line that computes `errored` in the browser path.

    It runs the real `verify_bookmaker` against the fake page — one link that
    serves the event and one whose navigation never completes — so deleting
    `report.errored = ...` from `verify_deeplinks.py` fails this test. The
    arithmetic is asserted on the object the function actually returned.
    """
    good = EVENT_URL
    bad = "https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/1"
    shell = FakeFrame(good)
    body = f'{{"match":{{"id":{EVENT_ID}}}}}'
    page = FakePage(
        shell,
        [FakeResponse(f"https://www.mozzartbet.ba/betting/match/{EVENT_ID}", body, shell)],
        fail_urls={bad},
    )
    playwright = _install_fake_browser(monkeypatch, page)
    matches = _cached(_match(), _match(event_id="1"))

    report = run(verify_deeplinks.verify_bookmaker("mozzartbet", matches, limit=2))

    assert report.checked == 2
    assert report.verified == 1
    assert report.failed == 0
    assert report.errored == 1, "the navigation error was not counted as errored"
    assert report.checked == report.verified + report.failed + report.errored
    assert [o.error for o in report.outcomes if o.error]  # the reason is reported
    assert playwright.stopped is True, "the browser was not shut down"


def test_the_response_reports_errored_checks(monkeypatch):
    _install_checker(
        monkeypatch, _report(outcomes=[_verified_outcome(), _error_outcome(event_id="1", url="u1")])
    )
    api.cached_matches.extend(_cached(_match(), _match(event_id="1")))

    body = client.post("/api/verify-links?bookmaker=mozzartbet").json()

    assert body["checked"] == 2
    assert body["errored"] == 1
    assert body["checked"] == body["verified"] + body["failed"] + body["errored"]


# ─── helpers ──────────────────────────────────────────────────────────────────


def _record(
    event_id: str,
    *,
    verified: bool,
    age_seconds: float,
    mode: str = "prematch",
    bookmaker: str = "mozzartbet",
):
    checked_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=age_seconds)
    api._deep_link_verifications.setdefault(mode, {})[f"{bookmaker}|{event_id}"] = {
        "verified": verified,
        "checked_at": checked_at.isoformat(),
        "url": EVENT_URL,
    }
    if os.path.exists(api.DEEP_LINK_VERIFICATIONS_FILE):
        os.unlink(api.DEEP_LINK_VERIFICATIONS_FILE)


def _stub_scan(monkeypatch, per_book: dict[str, list[Match]]):
    """Register a fake scraper per bookmaker so a scan produces exactly `per_book`."""

    class FakeScraper:
        def __init__(self, matches=None):
            self._matches = matches or []

        async def scrape(self, live=False, scan_time=None):
            kickoff = datetime.now(UTC).replace(tzinfo=None)
            return [m.model_copy(update={"kickoff": kickoff}) for m in self._matches]

    for bookmaker, matches in per_book.items():
        monkeypatch.setitem(api.SCRAPERS, bookmaker, lambda m=matches: FakeScraper(m))
    for bookie_id in api.BOOKMAKERS:
        api._bookmaker_enabled[bookie_id] = bookie_id in per_book
