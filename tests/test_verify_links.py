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

# Captured before the autouse `isolate_state` fixture replaces it, so the tests
# that exercise the save/load round trip can put the real one back.
_REAL_SAVE_CACHE = api._save_cache

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
    url: str = "",
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team=home_team,
        away_team=away_team,
        league=league,
        kickoff=kickoff,
        event_id=event_id,
        url=url or EVENT_URL,
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
    next_offset: int = 0,
    remaining: int = 0,
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
        next_offset=next_offset,
        remaining=remaining,
        outcomes=outcomes,
    )


def _feed(count: int, bookmaker: str = "mozzartbet", start: int = 0) -> list[dict]:
    """`count` cached matches for one book with event ids `"start"`, `"start"+1`, …

    Target selection reads only `bookmaker` and `event_id`, so nothing else in the
    cached shape matters here — which is the point: the cursor is a property of
    the feed, not of the matcher.
    """
    return [
        {"bookmaker": bookmaker, "event_id": str(i), "deep_link_verified": False}
        for i in range(start, start + count)
    ]


def _ids(targets) -> list[str]:
    return [t.event_id for t in targets]


MOZ_BASE = "https://www.mozzartbet.ba"


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
        "decisions": api._deep_link_decisions,
    }
    monkeypatch.setattr(
        api, "DEEP_LINK_VERIFICATIONS_FILE", str(tmp_path / "deep_link_verifications.json")
    )
    monkeypatch.setattr(
        api, "DEEP_LINK_DECISIONS_FILE", str(tmp_path / "deep_link_decisions.json")
    )
    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "ALLOWLIST_FILE", str(tmp_path / "team_alias_allowlist.json"))
    api._deep_link_verifications = {}
    api._deep_link_decisions = {}
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
    api._deep_link_decisions = snapshot["decisions"]
    api._verify_link_request_times.clear()
    api._scan_request_times.clear()


def _install_checker(monkeypatch, report: LinkReport | None = None, outcome=None):
    """Replace the browser seam; it must never launch Chromium in a test."""
    calls: list[dict] = []
    result = report
    if result is None:
        result = _report(outcomes=[outcome] if outcome is not None else [])

    async def fake(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
        calls.append(
            {
                "bookmaker": bookmaker,
                "matches": len(matches),
                "mode": mode,
                "live": live,
                "limit": limit,
                "offset": offset,
                "settled": set(settled),
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


def test_a_restored_cache_keeps_the_verified_groups_the_scan_had(monkeypatch, tmp_path):
    """A restart must not report "no match group is verified" for a scan that had one.

    `run_scan` fills `cached_match_groups_report` and `_save_cache` persisted
    everything else the scan produced, but the report was not among it. So for as
    long as the cache file stayed inside its 30-minute TTL — 30 minutes in which
    the operator's dashboard said `match_groups: 0` and "no match group is
    verified" — the count read 0 even when groups had verified. The surebets and
    the odds behind them were on screen the whole time.

    The whole point is that the count is the SAME before and after a restart, so
    this asserts against a real scan's own output rather than a hand-written
    report: anything a scan cannot produce, a restore cannot be asked to produce.
    """
    monkeypatch.setattr(api, "_save_cache", _REAL_SAVE_CACHE)
    monkeypatch.setattr(api, "_PREMATCH_CACHE_FILE", str(tmp_path / "last_scan.json"))
    monkeypatch.setattr(api, "_LIVE_CACHE_FILE", str(tmp_path / "last_live_scan.json"))
    _record(EVENT_ID, verified=True, age_seconds=60)
    _record("6828117", verified=True, age_seconds=60, bookmaker="mdshop")
    _stub_scan(
        monkeypatch,
        {"mozzartbet": [_match("mozzartbet")], "mdshop": [_match("mdshop", "6828117")]},
    )

    run(api.run_scan("prematch"))

    before = [r["status"] for r in api.cached_match_groups_report]
    assert before == ["verified"], "the control scan verified nothing, so this proves nothing"
    assert run(api.get_results("prematch"))["match_groups"] == 1

    # A restart: the report is gone from memory, the cache file is all that is left.
    api.cached_match_groups_report.clear()
    api.cached_surebets.clear()
    api.cached_matches.clear()
    api._load_cache()

    after = run(api.get_results("prematch"))
    assert [r["status"] for r in api.cached_match_groups_report] == before, (
        "the report was written by the scan and not read back, so the operator saw "
        "zero match groups until the next scan"
    )
    assert after["match_groups"] == 1
    assert after["group_statuses"] == {"verified": 1}


def test_a_cache_file_written_before_the_report_was_persisted_restores_no_groups(
    monkeypatch, tmp_path
):
    """An older cache file has no `match_groups` key, and must restore 0 groups.

    The honest answer for a file that never carried the report is zero, not a
    guess: the scan's own output is gone, and `match_groups` is a count of what
    this process verified, not a number to be reconstructed from the odds. So
    this is a compatibility case, not a defect — a deployment upgrading with a
    warm cache reads 0 verified groups for one scan cycle and then reads the
    truth.
    """
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
    api.cached_match_groups_report.clear()
    api.cached_matches.clear()

    api._load_cache()

    assert len(api.cached_matches) == 1, "the matches must still restore"
    assert api.cached_match_groups_report == []
    assert run(api.get_results("prematch"))["match_groups"] == 0


def test_a_restored_group_keeps_a_leg_the_book_declares_no_link_for(
    monkeypatch, tmp_path
):
    """Six of the nine books declare no per-event route, and the restore must not
    demand a link proof of them.

    A declared absence is settled by the declaration itself — the gate's case 2,
    and the reason those books' groups verify on identity alone. There is no link
    for a check to have stored a proof of, so a restore that looked for one would
    drop every group six of the nine books are in, and the operator would read 0
    verified groups after a restart on a feed that had 201. This is checked on a
    THREE-book group for that reason: two books that declare a route and one that
    declares it does not.
    """
    from scrapers.common import declares_no_event_id

    assert declares_no_event_id("premier_kladionica"), (
        "the fixture book must declare no per-event route, or this test is about "
        "nothing"
    )
    monkeypatch.setattr(api, "_save_cache", _REAL_SAVE_CACHE)
    monkeypatch.setattr(api, "_PREMATCH_CACHE_FILE", str(tmp_path / "last_scan.json"))
    monkeypatch.setattr(api, "_LIVE_CACHE_FILE", str(tmp_path / "last_live_scan.json"))
    # No proof at all for the declaring book, and proofs for the other two.
    _record(EVENT_ID, verified=True, age_seconds=60)
    _record("6828117", verified=True, age_seconds=60, bookmaker="mdshop")
    _stub_scan(
        monkeypatch,
        {
            "mozzartbet": [_match("mozzartbet")],
            "mdshop": [_match("mdshop", "6828117")],
            "premier_kladionica": [
                _match("premier_kladionica", "9985188", url="https://www.premier-kladionica.com/ponuda/")
            ],
        },
    )
    run(api.run_scan("prematch"))
    before = api.cached_match_groups_report
    assert [r["status"] for r in before] == ["verified"]
    assert {b["bookmaker"] for b in before[0]["bookmakers"]} == {
        "mozzartbet",
        "mdshop",
        "premier_kladionica",
    }

    api.cached_match_groups_report.clear()
    api.cached_surebets.clear()
    api.cached_matches.clear()
    api._load_cache()

    assert [r["status"] for r in api.cached_match_groups_report] == ["verified"], (
        "a leg whose book declares no per-event route was dropped for want of a link "
        "proof, so every group containing one of the six such books disappears on a "
        "restart"
    )
    assert run(api.get_results("prematch"))["match_groups"] == 1


def test_a_restored_report_may_not_verify_a_link_the_store_no_longer_proves(
    monkeypatch, tmp_path
):
    """Restoring the report must not widen what the gate would accept.

    The report is a snapshot of a decision another process made, so it can be
    older than the store it rests on: a proof can have been cleared by a completed
    fail, or aged out, since the scan that wrote it. A restore that believed the
    snapshot unconditionally would put back a `verified` claim the store no
    longer supports — the exact failure the TTL exists to prevent, arriving by
    the back door.

    So a restored `verified` group survives only while every one of its legs still
    has a FRESH proof in the store — not while the cached match says
    `deep_link_verified`, because that flag is itself a snapshot: it is written by
    the scan, and `_apply_deep_link_verifications` only ever SETS a flag, so it
    outlives the proof that set it. Consulting it here would make the restore a
    copy of the very staleness the TTL exists to catch, and the check would pass
    for the wrong reason.

    An unsupported group is dropped rather than demoted to another status, because
    `group_matches` only ever returns accepted groups: a group whose links are
    unproven is not reported as a group at all, so a restore that reported one
    would be describing a state the matcher cannot be in.
    """
    monkeypatch.setattr(api, "_save_cache", _REAL_SAVE_CACHE)
    monkeypatch.setattr(api, "_PREMATCH_CACHE_FILE", str(tmp_path / "last_scan.json"))
    monkeypatch.setattr(api, "_LIVE_CACHE_FILE", str(tmp_path / "last_live_scan.json"))
    _record(EVENT_ID, verified=True, age_seconds=60)
    _record("6828117", verified=True, age_seconds=60, bookmaker="mdshop")
    _stub_scan(
        monkeypatch,
        {"mozzartbet": [_match("mozzartbet")], "mdshop": [_match("mdshop", "6828117")]},
    )
    run(api.run_scan("prematch"))
    assert [r["status"] for r in api.cached_match_groups_report] == ["verified"]

    # A completed check on mdshop's event found nothing: the proof is popped.
    api._deep_link_verifications["prematch"].pop("mdshop|6828117")
    api.cached_match_groups_report.clear()
    api.cached_surebets.clear()
    api.cached_matches.clear()

    api._load_cache()

    assert "mdshop|6828117" not in api._deep_link_verifications["prematch"], (
        "the store must still be the one thing that says the link is unproven"
    )
    assert api.cached_match_groups_report == [], (
        "a group was restored as verified on a link the store no longer proves"
    )
    body = run(api.get_results("prematch"))
    assert body["match_groups"] == 0
    assert body["group_statuses"] == {}
    # The match's own flag is NOT what decided this, and is still the scan's
    # snapshot: `_apply_deep_link_verifications` only ever sets a flag, so a
    # `True` here is pre-existing, documented asymmetry rather than a claim the
    # restore is entitled to make on the report's behalf.
    assert {m["bookmaker"]: m["deep_link_verified"] for m in api.cached_matches} == {
        "mozzartbet": True,
        "mdshop": True,
    }


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
    # Pinned, not read from the environment: these tests assert the THROTTLE's
    # behaviour, so they must not change meaning when a deployment sets
    # DEEP_LINK_VERIFY_RATE_LIMIT to something else (0 disables it entirely).
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 2)
    _install_checker(monkeypatch)
    api.cached_matches.extend(_cached(_match()))

    for _ in range(2):
        assert client.post("/api/verify-links?bookmaker=mozzartbet").status_code == 200

    r = client.post("/api/verify-links?bookmaker=mozzartbet")

    assert r.status_code == 429
    assert "Rate limit" in r.json()["detail"]


def test_a_throttled_call_does_not_run_the_checker(monkeypatch):
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 2)
    calls = _install_checker(monkeypatch)
    api.cached_matches.extend(_cached(_match()))
    for _ in range(2):
        client.post("/api/verify-links?bookmaker=mozzartbet")

    client.post("/api/verify-links?bookmaker=mozzartbet")

    assert len(calls) == 2


def test_the_scan_and_verify_link_budgets_are_separate(monkeypatch):
    """Reusing the window must not let a scan flood consume the check budget."""
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 2)
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
                2,
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

    async def fake(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
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

    async def fake(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
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

    async def fake(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
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

    async def fake(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
        api.scan_status.is_scanning = True
        return _report(outcomes=[_verified_outcome()])

    monkeypatch.setattr(api, "_run_link_verification", fake)
    api.cached_matches.extend(_cached(_match()))

    note = client.post("/api/verify-links?bookmaker=mozzartbet").json()["applied_note"]

    assert "next scan will apply it" in note
    assert "_apply_deep_link_verifications" in note, (
        "the note must name the line that only ever sets, not the store write"
    )
    assert "only ever SETS" in note


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
    """None of these ends in "id"; the KEY rule rejected the measured
    `maxTotalOdd` control, not the float rule. See report §5."""
    assert json_event_paths(f'{{"settings":{{"{key}":{EVENT_ID}}}}}', EVENT_ID) == []


def test_a_decimal_under_an_event_key_is_not_the_event():
    """The float clause, finally exercised by a shape that reaches it.

    `maxTotalOdd` is rejected by the key rule before the int/float comparison is
    ever reached, so the float clause had no test. A decimal under a genuinely
    event-named key is a real shape (Go/PHP backends serialise ids as floats), and
    `"id": 9984468.0` must not be read as the event 9984468.
    """
    assert json_event_paths(f'{{"match":{{"id":{EVENT_ID}.0}}}}', EVENT_ID) == []
    assert json_event_paths(f'{{"eventId":{EVENT_ID}.00,"betName":"x"}}', EVENT_ID) == []
    # The same payload with an INT under the same key is evidence, so this test is
    # about the decimal, not about rejecting everything.
    assert json_event_paths(f'{{"match":{{"id":{EVENT_ID}}}}}', EVENT_ID) != []


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
    from a shared setting, and the derivation is asserted absent. The literal is
    pinned so a deployment that sets the env var does not fail the suite.
    """
    import inspect

    import config.settings as settings

    # Both sides are pinned: the env-overridable value is the point, so a
    # deployment that sets it must not change what this test asserts.
    monkeypatch.setattr(api, "RATE_LIMIT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)

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


# ─── 11. The cursor: repeated calls must cover NEW events ──────────────────────
#
# MEASURED DEFECT. `build_targets` walked the feed in order and `break`ed at
# `limit`, so a second call re-checked the identical first N events, forever. On
# the 2026-09-25 feed mozzartbet published 608 events, `limit` is capped at 20,
# and covering the book would have needed 31 calls that each redid the same 20.
# A cursor is the fix; the rate limit is not.
#
# Two mechanisms, and they are NOT interchangeable:
#
# * `settled` — event ids the caller has already DECIDED. Idempotent, needs no
#   caller bookkeeping, and survives a feed that grows at the head. PRIMARY.
# * `offset` — a positional resume for a caller with no store (the CLI). It is a
#   position in the POST-SKIP ordering, so it is only comparable across calls
#   that skip the same set.
#
# THE RULE THAT MATTERS MOST, and the one an off-by-one would break silently: a
# COMPLETED check settles an event, an ERROR does not. A navigation that never
# completed is neither a proof nor a failure, and dropping it here would lose
# events that still need checking — invisibly, because the run would just look
# shorter.


def test_two_calls_with_the_first_calls_verdicts_cover_disjoint_events():
    """THE acceptance test, at the level the defect was measured at.

    `settled` is the first call's verdicts and nothing else — no saved cursor, no
    arithmetic — and the second call must land on the next events, not replay the
    first ones.
    """
    feed = _feed(30)

    first = build_targets(feed, "mozzartbet", MOZ_BASE, limit=5)
    settled = {t.event_id for t in first}
    second = build_targets(feed, "mozzartbet", MOZ_BASE, limit=5, settled=settled)

    assert _ids(first) == ["0", "1", "2", "3", "4"]
    assert _ids(second) == ["5", "6", "7", "8", "9"]
    assert not {t.event_id for t in first} & {t.event_id for t in second}


def test_a_settled_event_is_skipped_before_the_limit_is_counted():
    """The skip is not positional: a run must spend its whole budget on events
    nobody has decided, so `settled` is applied before the window is cut."""
    settled = {str(i) for i in range(10)}

    targets = build_targets(_feed(30), "mozzartbet", MOZ_BASE, limit=3, settled=settled)

    assert _ids(targets) == ["10", "11", "12"]


def test_a_sweep_visits_every_event_exactly_once():
    """608 events at 20 per call is the case that used to be impossible."""
    feed = _feed(23)
    seen: list[str] = []
    settled: set[str] = set()
    while True:
        window = build_targets(feed, "mozzartbet", MOZ_BASE, limit=5, settled=settled)
        if not window:
            break
        seen += _ids(window)
        settled |= {t.event_id for t in window}

    assert len(seen) == len(set(seen)) == 23


def test_the_offset_is_applied_after_the_settled_skip():
    """The composition order is load-bearing and is pinned here.

    Post-skip the order is 3, 4, 5, … so `offset=2` starts at 5. Skip-then-offset
    the other way round would start at 2 and re-check an undecided event.
    """
    targets = build_targets(
        _feed(30), "mozzartbet", MOZ_BASE, limit=2, offset=2, settled={"0", "1", "2"}
    )

    assert _ids(targets) == ["5", "6"]


def test_the_offset_alone_walks_a_stateless_caller_forward():
    feed = _feed(30)

    assert _ids(build_targets(feed, "mozzartbet", MOZ_BASE, limit=3, offset=9)) == [
        "9",
        "10",
        "11",
    ]
    assert build_targets(feed, "mozzartbet", MOZ_BASE, offset=30) == []


def test_a_negative_offset_is_treated_as_no_offset():
    """A negative cursor is clamped, not applied — otherwise Python's negative
    indexing would silently select from the END of the book."""
    feed = _feed(6)

    assert build_targets(feed, "mozzartbet", MOZ_BASE, offset=-3) == build_targets(
        feed, "mozzartbet", MOZ_BASE
    )


def test_settled_ids_the_feed_does_not_contain_change_nothing():
    """A stale decision (the book retired the event) must not shift the window."""
    feed = _feed(3)

    assert build_targets(feed, "mozzartbet", MOZ_BASE, settled={"999", "6828117"}) == (
        build_targets(feed, "mozzartbet", MOZ_BASE)
    )


class _BookPage(FakePage):
    """A page that answers each navigation with THAT event's own payload.

    `FakePage` replays one fixed response list for every navigation, which is
    right for the criterion tests and wrong here: a sweep navigates several
    different event ids and each has to see its own answer, or the selection
    under test is not what gets measured.
    """

    def __init__(self, dead_ids=(), error_ids=()):
        super().__init__(FakeFrame("https://www.mozzartbet.ba/"))
        self.dead_ids = set(dead_ids)
        self.error_ids = set(error_ids)

    async def goto(self, url: str, wait_until: str = "load", timeout: int = 0) -> FakeResponse:
        self.goto_calls.append(url)
        event_id = url.rsplit("/", 1)[-1]
        if event_id in self.error_ids:
            raise TimeoutError(f"Timeout {timeout}ms exceeded")
        if event_id in self.dead_ids:
            return FakeResponse(url, "", self.main_frame, "text/html")  # nothing at all
        response = FakeResponse(
            f"https://www.mozzartbet.ba/betting/match/{event_id}",
            f'{{"match":{{"id":{event_id}}}}}',
            self.main_frame,
        )
        for handler in list(self._handlers):
            await handler(response)
        return FakeResponse(url, "", self.main_frame, "text/html")


def test_the_report_says_where_to_resume_and_how_much_is_left(monkeypatch):
    """`next_offset` and `remaining` exist so a sweep can be driven from the
    report alone, and the arithmetic the summary asserts must still hold."""
    _install_fake_browser(monkeypatch, _BookPage())

    report = run(verify_deeplinks.verify_bookmaker("mozzartbet", _feed(6), limit=2))

    assert [o.event_id for o in report.outcomes] == ["0", "1"]
    assert report.available == 6
    assert report.next_offset == 2
    assert report.remaining == 4
    assert report.checked == report.verified + report.failed + report.errored == 2


def test_a_resumed_run_reports_the_position_it_resumed_from(monkeypatch):
    _install_fake_browser(monkeypatch, _BookPage())

    report = run(verify_deeplinks.verify_bookmaker("mozzartbet", _feed(6), limit=2, offset=2))

    assert [o.event_id for o in report.outcomes] == ["2", "3"]
    # `available` is what the run could have checked FROM the cursor, so
    # `remaining` and `unchecked` are the same number and both mean "did not reach".
    assert report.available == 4
    assert report.next_offset == 4
    assert report.remaining == report.unchecked == 2


def test_verify_bookmaker_honours_a_settled_set(monkeypatch):
    _install_fake_browser(monkeypatch, _BookPage())

    report = run(
        verify_deeplinks.verify_bookmaker("mozzartbet", _feed(6), limit=2, settled={"0", "1", "2"})
    )

    assert [o.event_id for o in report.outcomes] == ["3", "4"]
    assert report.next_offset == 2
    assert report.remaining == 1


def test_a_completed_check_settles_its_event_whatever_the_verdict(monkeypatch):
    """`verified=False` with no error is a verdict, so it settles too. If only
    proofs settled, a book whose links do not verify could never be swept: the
    store would hold nothing for it and every call would restart."""
    _install_fake_browser(monkeypatch, _BookPage(dead_ids={"0", "1"}))

    first = run(verify_deeplinks.verify_bookmaker("mozzartbet", _feed(4), limit=2))
    settled = {o.event_id for o in first.outcomes if o.completed}
    second = run(verify_deeplinks.verify_bookmaker("mozzartbet", _feed(4), limit=2, settled=settled))

    assert first.verified == 0 and first.failed == 2
    assert settled == {"0", "1"}
    assert [o.event_id for o in second.outcomes] == ["2", "3"]


def test_an_errored_check_settles_nothing_and_stays_eligible(monkeypatch):
    """The failure mode this whole mechanism could introduce: dropping an event
    whose navigation never completed. It must come back on the next run."""
    _install_fake_browser(monkeypatch, _BookPage(error_ids={"0"}))

    first = run(verify_deeplinks.verify_bookmaker("mozzartbet", _feed(2), limit=1))
    settled = {o.event_id for o in first.outcomes if o.completed}
    second = run(verify_deeplinks.verify_bookmaker("mozzartbet", _feed(2), limit=1, settled=settled))

    assert first.errored == 1
    assert settled == set()
    assert [o.event_id for o in second.outcomes] == ["0"], "an errored event was dropped"


def test_an_errored_event_is_not_counted_as_remaining(monkeypatch):
    """`remaining` counts what the run did not REACH, so an event it reached and
    could not complete is not in it — it is in `errored`, and the next run
    re-offers it. Stated here so the docstring's claim is executable."""
    _install_fake_browser(monkeypatch, _BookPage(error_ids={"0"}))

    report = run(verify_deeplinks.verify_bookmaker("mozzartbet", _feed(2), limit=1))

    assert report.errored == 1
    assert report.remaining == 1
    assert report.remaining != 2


def _install_sweeping_checker(monkeypatch, decide=None):
    """Stand in for the BROWSER only: select with the real `build_targets`, real
    cursor and real `settled`, then return a completed outcome per target.

    Selection is the thing under test, so it must not be faked; the navigation
    must be, because no test may launch Chromium. The report's counts and cursor
    are filled in the way `verify_bookmaker` fills them, so an endpoint assertion
    about them tests the pass-through rather than this fake's arithmetic — the
    arithmetic itself is asserted against the real function, on the fake page.
    `decide(event_id)` returns True/False for a verdict and the string
    `"error"` for a navigation that never completed.
    """
    calls: list[dict] = []

    async def fake(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
        book = base_url or str(api.BOOKMAKERS[bookmaker]["base_url"])
        undecided = build_targets(
            matches, bookmaker, book, live=live, offset=offset, settled=settled
        )
        window = undecided[:limit] if limit else undecided
        calls.append(
            {
                "bookmaker": bookmaker,
                "mode": mode,
                "limit": limit,
                "offset": offset,
                "settled": set(settled),
                "ids": _ids(window),
            }
        )
        outcomes = []
        for target in window:
            verdict = decide(target.event_id) if decide else True
            if verdict == "error":
                outcomes.append(_error_outcome(target.event_id, target.url))
            elif verdict:
                outcomes.append(_verified_outcome(target.event_id, target.url))
            else:
                outcomes.append(_failed_outcome(target.event_id, target.url))
        return _report(
            bookmaker=bookmaker,
            outcomes=outcomes,
            available=len(undecided),
            next_offset=max(0, offset) + len(window),
            remaining=max(0, len(undecided) - len(window)),
        )

    monkeypatch.setattr(api, "_run_link_verification", fake)
    return calls


def test_the_endpoint_sweeps_forward_across_calls(monkeypatch):
    """The measured failure, end to end: call the endpoint twice on one feed and
    the second call must not replay the first call's events."""
    _install_sweeping_checker(monkeypatch)
    api.cached_matches.extend(_feed(30))

    first = client.post("/api/verify-links?bookmaker=mozzartbet&limit=5").json()
    second = client.post("/api/verify-links?bookmaker=mozzartbet&limit=5").json()

    assert [d["event_id"] for d in first["details"]] == ["0", "1", "2", "3", "4"]
    assert [d["event_id"] for d in second["details"]] == ["5", "6", "7", "8", "9"]
    assert not {d["event_id"] for d in first["details"]} & {
        d["event_id"] for d in second["details"]
    }
    assert first["next_offset"] == 5 and first["remaining"] == 25
    # `next_offset` counts from the requested cursor, and the endpoint's own sweep
    # always requests 0 — so it is the number just decided, and the way to resume
    # is to call again with no `offset` at all.
    assert second["next_offset"] == 5 and second["remaining"] == 20


def test_a_failed_event_is_not_offered_to_the_next_call(monkeypatch):
    """A completed FAIL is a decision and must settle, or a book whose links do
    not verify can never advance past its first `limit` events."""
    calls = _install_sweeping_checker(monkeypatch, decide=lambda event_id: False)
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 0)
    api.cached_matches.extend(_feed(6))

    first = client.post("/api/verify-links?bookmaker=mozzartbet&limit=2").json()
    second = client.post("/api/verify-links?bookmaker=mozzartbet&limit=2").json()

    assert first["failed"] == 2 and first["verified"] == 0
    assert [d["event_id"] for d in second["details"]] == ["2", "3"]
    assert calls[1]["settled"] == {"0", "1"}


def test_an_errored_event_is_offered_to_the_next_call(monkeypatch):
    """And the counterpart: an event whose navigation never completed is NOT
    decided, so the next call spends a slot on it again."""
    _install_sweeping_checker(monkeypatch, decide=lambda e: "error" if e == "0" else True)
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 0)
    api.cached_matches.extend(_feed(4))

    first = client.post("/api/verify-links?bookmaker=mozzartbet&limit=2").json()
    second = client.post("/api/verify-links?bookmaker=mozzartbet&limit=2").json()

    assert first["errored"] == 1
    assert [d["event_id"] for d in second["details"]] == ["0", "2"], "an errored event was dropped"
    decided = api._deep_link_decisions.get("prematch", {})
    assert f"mozzartbet|{first['details'][0]['event_id']}" not in decided
    assert f"mozzartbet|{first['details'][1]['event_id']}" in decided


def test_a_book_with_nothing_left_to_decide_says_so_instead_of_rechecking(monkeypatch):
    """Convergence has to be visible, or a sweep loop cannot know when to stop —
    and the zero-work call must not spend the throttle budget (B4)."""
    calls = _install_sweeping_checker(monkeypatch)
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 1)
    api.cached_matches.extend(_feed(2))
    assert client.post("/api/verify-links?bookmaker=mozzartbet&limit=2").status_code == 200
    api._verify_link_request_times.clear()

    for _ in range(3):
        body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=2").json()
        assert body["checked"] == 0
        assert body["remaining"] == 0
        assert body["applied"] is None
        assert "already been decided" in body["skip_reason"]

    assert len(calls) == 1, "the checker ran again with nothing to check"
    assert api._verify_link_request_times == {}, "a zero-work call spent the budget"


def test_a_stale_cursor_on_top_of_a_grown_settled_set_skips_further_ahead(monkeypatch):
    """Documented, executable behaviour: `offset` is a position in the POST-SKIP
    order, so carrying one across calls whose `settled` grew skips events nobody
    decided. It is why the endpoint's own sweep leaves `offset` at 0 and lets
    `settled` do the work — and why the response echoes both numbers."""
    calls = _install_sweeping_checker(monkeypatch)
    api.cached_matches.extend(_feed(30))

    body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=2&offset=2").json()

    assert calls[0]["settled"] == set()
    assert [d["event_id"] for d in body["details"]] == ["2", "3"]
    assert body["offset"] == 2
    assert body["settled_count"] == 0
    assert body["next_offset"] == 4
    assert body["available"] == 28
    assert body["remaining"] == 26


def test_the_endpoint_rejects_a_negative_offset():
    r = client.post("/api/verify-links?bookmaker=mozzartbet&offset=-1")

    assert r.status_code == 400
    assert "offset" in r.json()["detail"]


def test_the_endpoint_passes_its_cursor_and_settled_set_to_the_checker(monkeypatch):
    calls = _install_sweeping_checker(monkeypatch)
    api.cached_matches.extend(_feed(10))

    body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=3&offset=4").json()

    assert calls[0]["offset"] == 4
    assert [d["event_id"] for d in body["details"]] == ["4", "5", "6"]
    assert body["next_offset"] == 7
    assert body["available"] == 6
    assert body["remaining"] == 3


def test_a_stored_proof_does_not_by_itself_settle_an_event(monkeypatch):
    """The proof store is NOT read for the cursor, and that is load-bearing.

    A link that has been proven can only stop unblocking a `verified` group by
    being checked again and failing. If a proof settled the event, the endpoint
    would refuse to check it again — which is exactly what
    `test_a_stale_verification_is_cleared_by_a_later_failed_check` needs it to do.
    """
    calls = _install_sweeping_checker(monkeypatch)
    _record(EVENT_ID, verified=True, age_seconds=60)
    api.cached_matches.extend(_cached(_match(event_id=EVENT_ID), _match(event_id="1")))

    body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=5").json()

    assert calls[0]["settled"] == set()
    assert [d["event_id"] for d in body["details"]] == [EVENT_ID, "1"]


def test_recheck_offers_an_event_that_has_already_been_decided(monkeypatch):
    """The way back: `recheck=1` ignores the decisions for one call, so a sweep
    can be paused and a single link re-proved without deleting the store."""
    _install_sweeping_checker(monkeypatch)
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 0)
    api.cached_matches.extend(_feed(4))
    assert client.post("/api/verify-links?bookmaker=mozzartbet&limit=4").json()["checked"] == 4

    body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=4&recheck=1").json()

    assert body["settled_count"] == 0
    assert [d["event_id"] for d in body["details"]] == ["0", "1", "2", "3"]


def test_a_decision_is_scoped_to_its_book_and_its_mode(monkeypatch):
    calls = _install_sweeping_checker(monkeypatch)
    _record_decision(EVENT_ID, age_seconds=60, bookmaker="mdshop")
    _record_decision(EVENT_ID, age_seconds=60, mode="live")
    api.cached_matches.extend(_cached(_match()))

    body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=5").json()

    assert calls[0]["settled"] == set()
    assert [d["event_id"] for d in body["details"]] == [EVENT_ID]


def test_an_expired_decision_is_not_a_decision(monkeypatch):
    """A decision is a statement about a moment, exactly like a proof: past its
    TTL the event is eligible again, so a book is re-walked rather than frozen."""
    stale = api.DEEP_LINK_DECISION_TTL_SECONDS + 60
    calls = _install_sweeping_checker(monkeypatch)
    _record_decision(EVENT_ID, age_seconds=stale)
    api.cached_matches.extend(_cached(_match()))

    body = client.post("/api/verify-links?bookmaker=mozzartbet&limit=5").json()

    assert calls[0]["settled"] == set()
    assert [d["event_id"] for d in body["details"]] == [EVENT_ID]


def test_a_decision_survives_a_restart(monkeypatch):
    """Otherwise every server restart restarts the sweep from the first event."""
    _install_sweeping_checker(monkeypatch)
    api.cached_matches.extend(_feed(2))
    client.post("/api/verify-links?bookmaker=mozzartbet&limit=2")

    api._deep_link_decisions = {}
    api._deep_link_decisions.update(api._load_deep_link_decisions())

    assert sorted(api._deep_link_decisions["prematch"]) == ["mozzartbet|0", "mozzartbet|1"]


def test_a_decision_is_recorded_even_when_the_cache_write_is_skipped(monkeypatch):
    """Same reasoning as the proof: a concurrent scan must not cost the sweep its
    place, or the next call re-checks what was just decided."""

    async def fake(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
        api.scan_status.is_scanning = True
        return _report(outcomes=[_verified_outcome()])

    monkeypatch.setattr(api, "_run_link_verification", fake)
    api.cached_matches.extend(_cached(_match()))

    client.post("/api/verify-links?bookmaker=mozzartbet")

    assert f"mozzartbet|{EVENT_ID}" in api._deep_link_decisions["prematch"]


def test_the_cli_accepts_an_offset_and_prints_the_resume_position(monkeypatch, capsys):
    """The flag has to reach `verify_bookmaker`, and the report it prints has to
    say where to resume — asserted, not assumed.

    Parsing the printed JSON is also the regression test for the print itself: it
    used to `json.dumps(report.__dict__)`, and a report's `outcomes` are
    `LinkOutcome`s, so the command in the module docstring raised TypeError on the
    first completed check.
    """
    seen: list[dict] = []

    async def fake(bookmaker, matches, *, mode, limit, offset=0, settled=()):
        seen.append({"bookmaker": bookmaker, "limit": limit, "offset": offset})
        return _report(
            bookmaker=bookmaker,
            outcomes=[_verified_outcome()],
            available=3,
            next_offset=offset + 1,
            remaining=2,
        )

    monkeypatch.setattr(verify_deeplinks, "verify_bookmaker", fake)
    monkeypatch.setattr(verify_deeplinks, "_load_cached_matches", lambda mode: _feed(3))

    assert verify_deeplinks.main(["mozzartbet", "--limit", "1", "--offset", "2"]) == 0

    assert seen == [{"bookmaker": "mozzartbet", "limit": 1, "offset": 2}]
    printed = json.loads(capsys.readouterr().out)
    assert printed["next_offset"] == 3
    assert printed["remaining"] == 2
    assert printed["outcomes"][0]["event_id"] == EVENT_ID

    # And the default is no cursor, so an existing invocation is unchanged.
    assert verify_deeplinks.main(["mozzartbet", "--limit", "1"]) == 0
    assert seen[-1]["offset"] == 0


# ─── 11. A sweep has to fit inside the lifetime of what it produces ─────────────
#
# The blocker this section exists for. A proof stamps `deep_link_verified` onto a
# cached match, and the gate needs that flag on every member book before a group
# can be `verified`, so a book cannot be trusted until a full pass over it has
# landed. When the pass took longer than the proof's lifetime, the first proof of
# a sweep was already dead before the last one was written, and nothing a sweep
# produced could ever be held all at once. Measured on the live system on
# 2026-09-26: 21 calls of 20 events over 35 minutes, 83.9s between one call's
# completion and the next, and at 02:44 the newest of 412 stored proofs was 75
# minutes old while the TTL was 60 — 0 of 4,260 cached matches carried
# `deep_link_verified`, so no group could verify and no surebet could exist.
#
# `SECONDS_PER_EVENT` is that measurement, pinned as a literal because a test
# must not read a cache file that the next sweep rewrites. The command that
# produces it from the store is in the fix report.

# The MEDIAN gap between calls on the live system, measured from
# `cache/deep_link_decisions.json`: 21 calls of exactly 20 events, gaps spanning
# 83.6s to 302.2s, median 89.6s. The median, not the mean, and not the fastest
# call: the mean is pulled up by two operator pauses (302s and 132s) and the
# fastest call flatters the TTLs. Observed range 83.6s-131.3s excluding the two
# pauses, so a caller can re-measure and expect to land near this.
MEASURED_SECONDS_PER_CALL = 89.6
# The cost controls state a floor the measurement has to clear: at most
# DEEP_LINK_VERIFY_MAX_LIMIT events per call, and at most
# DEEP_LINK_VERIFY_RATE_LIMIT calls per RATE_LIMIT_WINDOW_SECONDS. Raising either
# makes a pass cheaper, and these numbers follow, so the invariant below cannot
# be satisfied by freezing the cost controls.
THROTTLE_SECONDS_PER_EVENT = (
    api.RATE_LIMIT_WINDOW_SECONDS
    / max(1, api.DEEP_LINK_VERIFY_RATE_LIMIT)
    / api.DEEP_LINK_VERIFY_MAX_LIMIT
)
SECONDS_PER_EVENT = max(MEASURED_SECONDS_PER_CALL / api.DEEP_LINK_VERIFY_MAX_LIMIT, THROTTLE_SECONDS_PER_EVENT)
# Mozzartbet's published prematch feed on 2026-09-26: 1,236 events carrying a
# per-event id, the largest single book the sweep has to walk.
SWEEP_EVENTS = 1236


def _pass_seconds(events: int = SWEEP_EVENTS) -> float:
    """Wall-clock one full pass over `events` events costs, at the measured rate."""
    return events * SECONDS_PER_EVENT


def _age_both_stores_by(seconds: float) -> None:
    """Move every stored proof and decision `seconds` into the past.

    A pass is a wall-clock property, so a test about one has to move the clock.
    The records are rewritten in place rather than by faking `datetime`, so what
    is under test is still the real age arithmetic in
    `_deep_link_record_is_fresh`.
    """
    for store in (api._deep_link_verifications, api._deep_link_decisions):
        for entries in store.values():
            for record in entries.values():
                checked_at = datetime.fromisoformat(record["checked_at"])
                record["checked_at"] = (checked_at - timedelta(seconds=seconds)).isoformat()


def _seed_one_finished_pass(events: int = SWEEP_EVENTS, bookmaker: str = "mozzartbet"):
    """Seed the store the way one completed pass leaves it, and return the ages.

    One record per call's worth of events, spread evenly across the pass, so the
    newest proof is 0s old and the oldest is exactly one pass old. That is the
    state a sweep leaves behind, and it is the state the TTL has to survive: the
    first proof the sweep wrote is the one a group most needs to still be holding.
    """
    per_call = _pass_seconds() / max(1, -(-events // api.DEEP_LINK_VERIFY_MAX_LIMIT) - 1)
    ages = []
    for call, first in enumerate(range(0, events, api.DEEP_LINK_VERIFY_MAX_LIMIT)):
        age = call * per_call
        ages.append(age)
        api._deep_link_verifications.setdefault("prematch", {})[f"{bookmaker}|{first}"] = {
            "verified": True,
            "checked_at": _age_iso(age),
            "url": f"https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/{first}",
        }
    if os.path.exists(api.DEEP_LINK_VERIFICATIONS_FILE):
        os.unlink(api.DEEP_LINK_VERIFICATIONS_FILE)
    return ages


def _age_iso(age_seconds: float) -> str:
    return (
        datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=age_seconds)
    ).isoformat()


def test_one_pass_over_a_book_costs_longer_than_the_ttl_that_shipped():
    """The measurement itself, so the numbers below are not asserted on faith.

    A pass over one real book is 92 minutes. The TTL that shipped was 60. There
    is no reading of that in which the store could hold the result of a sweep:
    the first proof a pass writes is dead 32 minutes before the pass ends, and
    everything it wrote is dead 32 minutes after.
    """
    assert _pass_seconds() == pytest.approx(5539, abs=5), (
        "the measured per-event cost changed; re-measure the sweep before trusting "
        "the TTLs, and update this assertion with the measurement"
    )
    assert _pass_seconds() > 3600, (
        "a pass now fits inside the old TTL, so the bug this section guards is no "
        "longer reproducible; the TTLs may be revisited"
    )


def test_every_link_lifetime_outlives_a_full_pass_over_the_largest_book():
    """The invariant, stated once: one pass must fit inside what it produces.

    Both stores, because both are written by the same pass and both are read to
    decide whether the pass is finished. A lifetime shorter than a pass is not a
    conservative choice — it is a store that can never hold a complete set, and
    for the decision store it is worse than that: a book whose first decisions
    expire mid-pass is offered them again before the pass reaches its end, so the
    sweep walks in circles and never reports itself converged.

    And the two are ordered, because they are not the same kind of claim. A proof
    is a positive fact about a route and is trusted for as long as a bookmaker's
    routing can be expected to hold; a decision only says a check happened, and
    needs to outlive one pass and no more.
    """
    one_pass = _pass_seconds()

    assert api.DEEP_LINK_DECISION_TTL_SECONDS > one_pass, (
        f"a decision expires after {api.DEEP_LINK_DECISION_TTL_SECONDS}s but a pass "
        f"over {SWEEP_EVENTS} events costs {one_pass:.0f}s, so the sweep re-offers "
        "the events it started on and can never reach the end of the book"
    )
    assert api.DEEP_LINK_VERIFICATION_TTL_SECONDS > api.DEEP_LINK_DECISION_TTL_SECONDS, (
        "a proof is a positive fact and must outlive 'we looked at it', or a "
        "re-walk expires the evidence it was meant to refresh"
    )
    assert api.DEEP_LINK_VERIFICATION_TTL_SECONDS > one_pass


def test_a_group_verifies_from_proofs_that_span_a_whole_pass(monkeypatch):
    """The test this whole section is for: a complete set, from a real spread.

    The store is seeded exactly as one finished pass leaves it — 62 records whose
    ages run from 0 to a full pass — and the group is built from the two ENDS of
    that spread: the proof the pass wrote first, and a fresh one. So every leg the
    gate needs is proven, and the oldest proof it leans on is as old as the sweep
    that produced it. With a lifetime shorter than a pass this is 0 verified
    groups, which is the whole failure: correct pipeline, unreachable.
    """
    ages = _seed_one_finished_pass()
    assert ages[0] == 0.0
    assert max(ages) == pytest.approx(_pass_seconds(), rel=0.001), (
        "the seeded spread is not a full pass, so this test would pass on a TTL "
        "that cannot hold one"
    )
    # The group's mozzartbet leg is the LAST event of the pass, so it carries the
    # OLDEST proof in the store. mdshop's leg is proven fresh.
    oldest_event = str((SWEEP_EVENTS - 1) // api.DEEP_LINK_VERIFY_MAX_LIMIT * api.DEEP_LINK_VERIFY_MAX_LIMIT)
    _record("6828117", verified=True, age_seconds=0.0, bookmaker="mdshop")
    _stub_scan(
        monkeypatch,
        {
            "mozzartbet": [_match("mozzartbet", oldest_event)],
            "mdshop": [_match("mdshop", "6828117")],
        },
    )

    run(api.run_scan("prematch"))

    assert {m["bookmaker"]: m["deep_link_verified"] for m in api.cached_matches} == {
        "mozzartbet": True,
        "mdshop": True,
    }, "a proof from the start of a pass no longer counts, so no set can be held"
    assert [r["status"] for r in api.cached_match_groups_report] == ["verified"], (
        "every leg of this group is proven and the oldest proof is a whole pass "
        "old, so the group must verify — the sweep produced a complete set"
    )


def test_a_sweep_reaches_the_end_of_the_book_and_then_stops(monkeypatch):
    """The pass has to be able to FINISH, or nothing downstream of it ever runs.

    Driven through the endpoint with a stubbed checker that offers the same window
    `verify_bookmaker` would, so the only thing being simulated is elapsed time:
    after every call the store is aged by one call's measured cost, which is what
    a real sweep does. The throttle is opened for the test because its effect is
    already inside `SECONDS_PER_EVENT`; what is under test is the decision TTL
    against the length of a pass.

    A pass over 1,236 events is 62 calls, and the call after the last must report
    nothing left to check. Under a decision lifetime shorter than a pass this
    never terminates: the front of the book expires before the back is reached, so
    call 62 is still working on the events call 1 did.
    """
    calls_needed = -(-SWEEP_EVENTS // api.DEEP_LINK_VERIFY_MAX_LIMIT)  # ceil
    monkeypatch.setattr(api, "DEEP_LINK_VERIFY_RATE_LIMIT", 0)
    api.cached_matches.extend(_feed(SWEEP_EVENTS, "mozzartbet"))
    checked: list[str] = []

    async def sweep_checker(bookmaker, matches, *, mode, live, limit, base_url=None, offset=0, settled=()):
        available = build_targets(
            matches, bookmaker, base_url or "", live=live, offset=offset, settled=settled
        )
        window = available[:limit]
        checked.extend(t.event_id for t in window)
        return _report(
            outcomes=[_verified_outcome(t.event_id, t.url) for t in window],
            available=len(available),
        )

    monkeypatch.setattr(api, "_run_link_verification", sweep_checker)

    per_call = SECONDS_PER_EVENT * api.DEEP_LINK_VERIFY_MAX_LIMIT
    converged_at = None
    for call in range(1, calls_needed + 2):
        r = client.post(f"/api/verify-links?bookmaker=mozzartbet&limit={api.DEEP_LINK_VERIFY_MAX_LIMIT}")
        assert r.status_code == 200, r.text
        _age_both_stores_by(per_call)
        if r.json()["checked"] == 0:
            converged_at = call
            break

    assert converged_at == calls_needed + 1, (
        f"the sweep never reported itself converged within {calls_needed + 1} calls; "
        f"it had re-checked {len(checked)} events by then, so it is walking in "
        "circles on a book whose decisions expire before the pass reaches them"
    )
    assert len(set(checked)) == SWEEP_EVENTS, (
        "a pass must decide each event exactly once, or the store is not holding a "
        "full set and the sweep is buying the same evidence twice"
    )


# ─── helpers ──────────────────────────────────────────────────────────────────


def _record_decision(
    event_id: str,
    *,
    age_seconds: float,
    mode: str = "prematch",
    bookmaker: str = "mozzartbet",
):
    """A stored DECISION: "we looked at this event and reached a verdict"."""
    checked_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=age_seconds)
    api._deep_link_decisions.setdefault(mode, {})[f"{bookmaker}|{event_id}"] = {
        "checked_at": checked_at.isoformat()
    }
    if os.path.exists(api.DEEP_LINK_DECISIONS_FILE):
        os.unlink(api.DEEP_LINK_DECISIONS_FILE)


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
