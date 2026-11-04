"""P2-1: the link sweep converges and keeps partial failures visible."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.sweep_links import RateLimited, append_report, sweep
from server import api
from server.app import app

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
HTML = Path("frontend/index.html").read_text(encoding="utf-8")


class FakePost:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str, api_key: str) -> dict:
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _body(**overrides) -> dict:
    body = {
        "status": "checked",
        "available": 4,
        "checked": 1,
        "verified": 1,
        "failed": 0,
        "errored": 0,
        "unchecked": 0,
        "remaining": 3,
        "next_offset": 1,
    }
    body.update(overrides)
    return body


def test_a_sweep_converges_when_remaining_reaches_zero():
    post = FakePost(
        [
            _body(remaining=2, verified=1, failed=0),
            _body(remaining=1, verified=0, failed=1),
            _body(remaining=0, verified=0, failed=0, errored=1),
        ]
    )

    report = sweep(
        "http://scanner", "mozzartbet", post=post, sleep=lambda _: None
    )

    assert report["status"] == "converged"
    assert report["calls"] == 3
    assert report["checked"] == 3
    assert report["verified"] == 1
    assert report["failed"] == 1
    assert report["errored"] == 1
    assert report["remaining"] == 0
    assert all("bookmaker=mozzartbet" in url for url in post.urls)


def test_an_errored_event_does_not_stop_the_next_call():
    post = FakePost(
        [
            _body(remaining=1, errored=1, verified=0),
            _body(remaining=0, errored=0, verified=1),
        ]
    )

    report = sweep(
        "http://scanner", "maxbet", post=post, sleep=lambda _: None
    )

    assert report["status"] == "converged"
    assert report["calls"] == 2
    assert report["errored"] == 1
    assert report["verified"] == 1


def test_the_call_budget_stops_a_sweep_that_never_converges():
    post = FakePost([_body(remaining=1), _body(remaining=1)])

    report = sweep(
        "http://scanner",
        "maxbet",
        max_calls=2,
        post=post,
        sleep=lambda _: None,
    )

    assert report["status"] == "budget_exhausted"
    assert report["calls"] == 2
    assert report["remaining"] == 1


def test_a_rate_limit_is_waited_out_not_bypassed():
    sleeps: list[float] = []
    post = FakePost([RateLimited(2.5), _body(remaining=0)])

    report = sweep(
        "http://scanner",
        "maxbet",
        post=post,
        sleep=sleeps.append,
    )

    assert report["status"] == "converged"
    assert report["rate_limit_waits"] == 1
    assert sleeps == [2.5]
    assert report["calls"] == 1


def test_a_whole_request_failure_is_reported():
    post = FakePost([RuntimeError("connection refused")])

    report = sweep(
        "http://scanner", "maxbet", post=post, sleep=lambda _: None
    )

    assert report["status"] == "request_failed"
    assert report["http_error"] == "RuntimeError"


def test_reports_are_appended_to_one_file(tmp_path):
    path = tmp_path / "link_sweeps.json"
    append_report(path, {"bookmaker": "maxbet", "status": "converged"})
    append_report(path, {"bookmaker": "mozzartbet", "status": "skipped"})

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert [row["bookmaker"] for row in payload["sweeps"]] == [
        "maxbet",
        "mozzartbet",
    ]


def test_the_server_persists_and_reads_a_sweep_report(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_LINK_SWEEP_FILE", str(tmp_path / "link_sweeps.json"))
    client = TestClient(app)
    report = {
        "bookmaker": "maxbet",
        "mode": "prematch",
        "status": "converged",
        "calls": 2,
        "checked": 2,
        "verified": 1,
        "failed": 1,
        "errored": 0,
        "unchecked": 0,
        "remaining": 0,
    }

    saved = client.post("/api/link-sweeps", json=report)
    read = client.get("/api/link-sweeps?bookmaker=maxbet")

    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert read.status_code == 200
    assert read.json()["count"] == 1
    assert read.json()["sweeps"][0]["status"] == "converged"


def test_the_dashboard_control_loops_verify_links_and_saves_the_report():
    assert 'data-action="sweep-links"' in HTML
    assert 'id="sweep-book"' in HTML
    assert 'id="sweep-status"' in HTML
    assert "SWEEP_MAX_CALLS" in JS
    assert "totals.remaining === 0" in JS
    assert "/api/verify-links?" in JS
    assert "/api/link-sweeps" in JS
    assert "response.status === 429" in JS
