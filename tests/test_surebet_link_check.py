"""SR9-3: the on-demand leg-link check and its `/api/surebets/{id}/check-links` route.

The browser is a seam here: the judge is exercised against text captured from the
real pages (tests/fixtures/link_check/), and the route against a stubbed
`api._run_leg_link_check`, so no test launches Chromium or touches a bookmaker.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import api, leg_link_check
from server.app import app
from server.auth import ApiKeyStore
from server.leg_link_check import (
    LegTarget,
    build_targets,
    check_target,
    judge,
    page_text,
    skip_reason,
)

FIXTURES = Path(__file__).parent / "fixtures" / "link_check"

MAXBET_TICKET = LegTarget(
    bookmaker="maxbet",
    kind="ticket_filled",
    url="https://www.maxbet.ba/ba/sportsbook/match/1027619?outcome=147294305",
    home="CD Universitario",
    away="Herrera FC",
    pick="1",
)
NSOFT_TICKET = LegTarget(
    bookmaker="mdshop",
    kind="ticket_filled",
    url="https://www.mdshop.ba/sport-site/sr/#/betting/prematch?ticketItems=x",
    home="Manchester City",
    away="Fulham",
    pick="1",
)


def _page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ─── The judge, against captured page text ────────────────────────────────────


def test_a_filled_maxbet_ticket_opens_the_fixture_and_shows_the_pick():
    check = judge(_page("maxbet_ticket.txt"), MAXBET_TICKET)
    assert check.status == "ok"
    assert check.opens_fixture is True
    assert check.ticket_has_selection is True
    assert check.failed is False


def test_a_filled_nsoft_ticket_passes_the_same_way():
    check = judge(_page("nsoft_ticket.txt"), NSOFT_TICKET)
    assert check.status == "ok"
    assert check.opens_fixture is True
    assert check.ticket_has_selection is True
    assert check.failed is False


def test_an_empty_slip_opens_the_fixture_but_fails_the_ticket():
    check = judge(_page("maxbet_empty_slip.txt"), MAXBET_TICKET)
    assert check.opens_fixture is True
    assert check.ticket_has_selection is False
    assert check.status == "ticket_empty"
    assert check.failed is True
    assert "slip" in check.evidence


def test_a_generic_page_fails_the_fixture_check():
    check = judge(_page("maxbet_home.txt"), MAXBET_TICKET)
    assert check.opens_fixture is False
    assert check.status == "fixture_not_found"
    assert check.failed is True
    assert "CD Universitario" in check.evidence


def test_a_match_page_rung_does_not_need_a_slip():
    target = replace(MAXBET_TICKET, kind="match_page")
    check = judge(_page("maxbet_empty_slip.txt"), target)
    assert check.status == "ok"
    assert check.opens_fixture is True
    assert check.ticket_has_selection is False
    assert check.failed is False


def test_a_line_market_needs_its_side_and_its_line():
    text = (
        "Tiket 1 Selekcije Manchester City Fulham Ukupno golova vise 2.5 1.90 "
        "Ulog 10 Ukupna kvota 1.90"
    )
    over = LegTarget(
        bookmaker="mdshop",
        kind="ticket_filled",
        url="https://www.mdshop.ba/x",
        home="Manchester City",
        away="Fulham",
        pick="Over 2.5",
        line="2.5",
    )
    assert judge(text, over).ticket_has_selection is True
    assert judge(text, replace(over, pick="Under 2.5")).status == "ticket_empty"


def test_a_ticket_page_without_any_slip_word_fails():
    text = "Manchester City Fulham Konacan ishod 1 1.43"
    check = judge(text, NSOFT_TICKET)
    assert check.opens_fixture is True
    assert check.status == "ticket_empty"
    assert check.failed is True
    assert "no slip" in check.evidence


def test_a_book_spelling_too_short_to_search_is_skipped_not_failed():
    target = replace(NSOFT_TICKET, home="A")
    check = judge(_page("nsoft_ticket.txt"), target)
    assert check.status == "skipped"
    assert check.failed is False
    assert check.opens_fixture is False


# ─── The browser page, without a browser ──────────────────────────────────────

class _Frame:
    def __init__(self, text: str = "", *, aria_error: bool = False) -> None:
        self._text = text
        self._aria_error = aria_error

    def locator(self, _selector: str):
        return self

    async def aria_snapshot(self, timeout=None):
        if self._aria_error:
            raise RuntimeError("no accessibility snapshot")
        return self._text

    async def inner_text(self, _selector: str):
        return self._text


class _Page:
    """A page whose frames serve one text per read, in order."""

    def __init__(self, texts: list[str], *, goto_error: Exception | None = None) -> None:
        self._texts = texts
        self._goto_error = goto_error
        self.waited = 0

    @property
    def frames(self):
        return [_Frame(self._texts.pop(0) if len(self._texts) > 1 else self._texts[0])]

    async def goto(self, *_args, **_kwargs):
        if self._goto_error is not None:
            raise self._goto_error
        return object()

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.waited += milliseconds


def test_page_text_reads_the_accessibility_tree_and_falls_back_to_inner_text():
    class _MixedPage:
        @property
        def frames(self):
            return [_Frame("<fixture>"), _Frame("plain text", aria_error=True)]

    text = asyncio.run(page_text(_MixedPage()))
    assert "<fixture>" in text
    assert "plain text" in text


def test_check_target_polls_until_the_fixture_appears(monkeypatch):
    monkeypatch.setattr(leg_link_check, "SETTLE_TIMEOUT_MS", 1500)
    monkeypatch.setattr(leg_link_check, "POLL_INTERVAL_MS", 500)
    page = _Page(["", _page("maxbet_ticket.txt")])

    check = asyncio.run(check_target(page, MAXBET_TICKET))

    assert check.status == "ok"
    assert check.ticket_has_selection is True
    assert page.waited == 500


def test_check_target_stops_at_the_settle_window(monkeypatch):
    monkeypatch.setattr(leg_link_check, "SETTLE_TIMEOUT_MS", 0)
    page = _Page(["nothing here"])

    check = asyncio.run(check_target(page, MAXBET_TICKET))

    assert check.status == "fixture_not_found"
    assert check.failed is True
    assert page.waited == 0


def test_a_navigation_that_never_completes_is_an_error_not_a_dead_link():
    page = _Page(["x"], goto_error=TimeoutError("navigation timeout"))

    check = asyncio.run(check_target(page, MAXBET_TICKET))

    assert check.status == "error"
    assert check.failed is True
    assert "navigation timeout" in check.error


# ─── Targets ──────────────────────────────────────────────────────────────────


def _surebet() -> dict:
    return {
        "id": "abc12345",
        "home_team": "Canonical Home",
        "away_team": "Canonical Away",
        "listings": {"maxbet": {"home": "Book Home", "away": "Book Away"}},
        "stakes": [
            {
                "bookmaker": "maxbet",
                "outcome_label": "1",
                "destination": {
                    "kind": "ticket_filled",
                    "url": "https://www.maxbet.ba/ba/sportsbook/match/1?outcome=2",
                    "selection": "1",
                    "line": "",
                },
            },
            {
                "bookmaker": "mdshop",
                "outcome_label": "2",
                "destination": {
                    "kind": "match_page",
                    "url": "https://www.mdshop.ba/sport-site/sr/#/betting/prematch?event=1",
                    "selection": "2",
                    "line": "",
                },
            },
            {
                "bookmaker": "sportplus",
                "outcome_label": "X",
                "destination": {"kind": "competition", "url": ""},
            },
        ],
    }


def test_only_per_fixture_rungs_become_targets():
    targets = build_targets(_surebet())
    assert [(t.bookmaker, t.kind) for t in targets] == [
        ("maxbet", "ticket_filled"),
        ("mdshop", "match_page"),
    ]


def test_the_book_spelling_wins_and_falls_back_to_the_match_names():
    targets = build_targets(_surebet())
    assert (targets[0].home, targets[0].away) == ("Book Home", "Book Away")
    # mdshop has no listing entry, so the surebet's own names are used.
    assert (targets[1].home, targets[1].away) == ("Canonical Home", "Canonical Away")


def test_the_pick_and_line_come_from_the_destination():
    surebet = _surebet()
    surebet["stakes"][0]["destination"]["selection"] = "Over 2.5"
    surebet["stakes"][0]["destination"]["line"] = "2.5"
    [target] = build_targets(surebet)[:1]
    assert (target.pick, target.line) == ("Over 2.5", "2.5")


def test_a_surebet_without_a_per_fixture_rung_says_what_it_has():
    surebet = _surebet()
    surebet["stakes"] = [surebet["stakes"][2]]
    assert build_targets(surebet) == []
    assert "competition" in skip_reason(surebet)


# ─── The route ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolate_state(monkeypatch):
    """Keep the cached surebets, the rate window and the browser seam local."""
    surebets = list(api.cached_surebets)
    live_surebets = list(api.cached_live_surebets)
    matches = list(api.cached_matches)
    times = dict(api._surebet_link_check_times)
    api.cached_surebets.clear()
    api.cached_live_surebets.clear()
    api._surebet_link_check_times.clear()
    monkeypatch.setattr(api, "_save_cache", lambda *a, **k: None)
    yield
    api.cached_surebets[:] = surebets
    api.cached_live_surebets[:] = live_surebets
    api.cached_matches[:] = matches
    api._surebet_link_check_times.clear()
    api._surebet_link_check_times.update(times)


def _install_checker(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake(surebet, mode):
        calls.append((str(surebet.get("id")), mode))
        return {
            "surebet_id": str(surebet.get("id")),
            "mode": mode,
            "status": "checked",
            "skip_reason": "",
            "checked_at": "2026-11-11T17:00:00",
            "duration_seconds": 3.5,
            "legs": [],
            "summary": {"legs": 0, "opened": 0, "tickets": 0, "failed": 0, "skipped": 0},
        }

    monkeypatch.setattr(api, "_run_leg_link_check", fake)
    return calls


def _client_with_key(tmp_path, monkeypatch, scopes: list[str]) -> tuple[TestClient, str]:
    store = ApiKeyStore(str(tmp_path / "api_keys.json"))
    monkeypatch.setattr(api, "api_key_store", store)
    monkeypatch.setattr(api, "API_KEY", "bootstrap")
    token, _ = store.create("phone", scopes)
    return TestClient(app), token


def test_the_route_requires_the_scan_scope(tmp_path, monkeypatch):
    client, token = _client_with_key(tmp_path, monkeypatch, ["read"])
    api.cached_surebets.append(_surebet())

    response = client.post(
        "/api/surebets/abc12345/check-links", headers={"X-API-Key": token}
    )

    assert response.status_code == 403


def test_a_scan_scoped_key_reaches_the_checker(tmp_path, monkeypatch):
    calls = _install_checker(monkeypatch)
    client, token = _client_with_key(tmp_path, monkeypatch, ["scan"])
    api.cached_surebets.append(_surebet())

    response = client.post(
        "/api/surebets/abc12345/check-links?mode=prematch",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 200
    assert calls == [("abc12345", "prematch")]
    assert response.json()["status"] == "checked"


def test_an_unknown_surebet_is_404(monkeypatch):
    _install_checker(monkeypatch)
    client = TestClient(app)
    assert client.post("/api/surebets/nope/check-links").status_code == 404


def test_an_unknown_mode_is_400(monkeypatch):
    _install_checker(monkeypatch)
    client = TestClient(app)
    response = client.post("/api/surebets/abc12345/check-links?mode=sidelined")
    assert response.status_code == 400


def test_a_surebet_with_no_per_fixture_rung_skips_without_a_browser(monkeypatch):
    async def explode(*_args, **_kwargs):
        raise AssertionError("the browser seam must not run for a skipped surebet")

    monkeypatch.setattr(api, "_run_leg_link_check", explode)
    surebet = _surebet()
    surebet["stakes"] = [surebet["stakes"][2]]
    api.cached_surebets.append(surebet)

    response = client_post("/api/surebets/abc12345/check-links")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["legs"] == []
    assert "competition" in body["skip_reason"]


def test_a_scan_in_progress_is_refused(monkeypatch):
    _install_checker(monkeypatch)
    api.cached_surebets.append(_surebet())
    api._state_for("prematch").status.is_scanning = True
    try:
        assert client_post("/api/surebets/abc12345/check-links").status_code == 409
    finally:
        api._state_for("prematch").status.is_scanning = False


def test_the_rate_limit_is_per_surebet(monkeypatch):
    calls = _install_checker(monkeypatch)
    monkeypatch.setattr(api, "SUREBET_LINK_CHECK_MIN_INTERVAL_SECONDS", 30.0)
    api.cached_surebets.extend([_surebet(), {**_surebet(), "id": "def67890"}])

    first = client_post("/api/surebets/abc12345/check-links")
    second = client_post("/api/surebets/abc12345/check-links")
    other = client_post("/api/surebets/def67890/check-links")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"].isdigit()
    assert other.status_code == 200
    assert calls == [("abc12345", "prematch"), ("def67890", "prematch")]


def test_the_check_never_sets_a_link_proof_or_a_group_status(monkeypatch):
    _install_checker(monkeypatch)
    api.cached_surebets.append(_surebet())
    match = {"bookmaker": "maxbet", "event_id": "1027619", "deep_link_verified": False}
    api.cached_matches[:] = [match]
    verifications = dict(api._deep_link_verifications)

    response = client_post("/api/surebets/abc12345/check-links")

    assert response.status_code == 200
    assert match["deep_link_verified"] is False
    assert api._deep_link_verifications == verifications


def client_post(path: str):
    """A POST as the open local API (no key configured in these tests)."""
    return TestClient(app).post(path)


def test_the_checker_is_the_only_browser_path(monkeypatch):
    """The route calls the seam; the seam calls `check_surebet`."""
    calls = _install_checker(monkeypatch)
    api.cached_surebets.append(_surebet())

    client_post("/api/surebets/abc12345/check-links")

    assert calls
    # The real seam exists and is what the route calls (not `check_surebet`
    # directly), so a test or a future caller can replace it.
    assert asyncio.iscoroutinefunction(api._run_leg_link_check)


def test_the_real_seam_delegates_to_check_surebet(monkeypatch):
    seen: list[tuple[str, str]] = []

    async def fake(surebet, mode="prematch"):
        seen.append((str(surebet["id"]), mode))
        return {"status": "checked"}

    monkeypatch.setattr(leg_link_check, "check_surebet", fake)

    result = asyncio.run(api._run_leg_link_check({"id": "abc12345"}, "live"))

    assert result == {"status": "checked"}
    assert seen == [("abc12345", "live")]
