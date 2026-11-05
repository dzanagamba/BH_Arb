"""N1-3: per-book scan cost is measured, bounded and reported."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scrapers.cost import (
    begin_book,
    build_scan_report,
    classify_exception,
    finish_book,
    record_browser_seconds,
    record_request,
)
from scripts.scan_cost import main as scan_cost_main
from server import api
from server.observability import metrics
from server.scan_cost import aggregate, book_failure_rates, load_history

JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
HTML = Path("frontend/index.html").read_text(encoding="utf-8")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def test_a_book_records_wall_browser_request_and_byte_fields():
    begin_book("mbet", "prematch", uses_browser=True)
    record_browser_seconds(1.25)
    record_request(100)
    record_request(50)

    record = finish_book("success", matches=3, markets=6)

    assert record is not None
    assert record["bookmaker"] == "mbet"
    assert record["outcome"] == "success"
    assert record["wall_seconds"] >= 0
    assert record["browser_seconds"] == 1.25
    assert record["requests"] == 2
    assert record["bytes"] == 150
    assert record["matches"] == 3
    assert record["markets"] == 6
    assert record["missing"] == []


def test_a_non_browser_book_reports_browser_time_as_not_measurable():
    begin_book("mdshop", "prematch", uses_browser=False)
    record_request(10)

    record = finish_book("empty")

    assert record is not None
    assert record["browser_seconds"] is None
    assert any("does not use a browser" in reason for reason in record["missing"])


def test_an_unreadable_response_size_is_null_not_zero():
    begin_book("wwin", "prematch", uses_browser=True)
    record_browser_seconds(0.5)
    record_request(None)

    record = finish_book("blocked")

    assert record is not None
    assert record["requests"] == 1
    assert record["bytes"] is None
    assert any("response size unavailable" in reason for reason in record["missing"])


def test_a_skipped_book_has_explicit_missing_reasons():
    begin_book("evlbet", "prematch", uses_browser=False)

    record = finish_book("skipped", note="disabled by runtime toggle")

    assert record is not None
    assert record["outcome"] == "skipped"
    assert record["requests"] is None
    assert record["bytes"] is None
    assert record["note"] == "disabled by runtime toggle"
    assert any("not attempted" in reason for reason in record["missing"])


def test_exception_classification_separates_blocked_from_parse_error():
    assert classify_exception(RuntimeError("HTTP 403 Forbidden")) == "blocked"
    assert classify_exception(RuntimeError("captcha challenge")) == "blocked"
    assert classify_exception(RuntimeError("net::ERR_TIMED_OUT")) == "blocked"
    assert classify_exception(ValueError("unexpected JSON shape")) == "parse_error"


def test_the_scan_report_keeps_outcomes_and_denominators_distinct():
    books = {
        "mbet": {
            "outcome": "success",
            "wall_seconds": 2.0,
            "browser_seconds": 0.5,
            "requests": 4,
            "bytes": 1000,
            "matches": 10,
            "markets": 20,
            "missing": [],
        },
        "wwin": {
            "outcome": "empty",
            "wall_seconds": 1.0,
            "browser_seconds": None,
            "requests": 2,
            "bytes": 500,
            "matches": 0,
            "markets": 0,
            "missing": ["browser_seconds: book does not use a browser"],
        },
        "sportplus": {
            "outcome": "blocked",
            "wall_seconds": 3.0,
            "browser_seconds": None,
            "requests": 1,
            "bytes": None,
            "matches": 0,
            "markets": 0,
            "missing": ["bytes: response size unavailable"],
        },
    }

    report = build_scan_report("prematch", _now(), books)

    assert report["totals"]["books"] == 3
    assert report["totals"]["success"] == 1
    assert report["totals"]["empty"] == 1
    assert report["totals"]["blocked"] == 1
    assert report["totals"]["wall_seconds"] == 6.0
    assert report["totals"]["requests"] == 7
    assert report["totals"]["bytes"] == 1500
    assert report["totals"]["matches"] == 10
    assert report["totals"]["seconds_per_match"] == 0.6
    assert report["totals"]["requests_per_match"] == 0.7


def _scan(
    mode: str,
    when: datetime,
    books: dict[str, dict],
) -> dict:
    return {
        "mode": mode,
        "scan_time": when.isoformat(timespec="seconds"),
        "books": books,
        "totals": {},
    }


def _book(outcome: str, wall: float, matches: int) -> dict:
    return {
        "outcome": outcome,
        "wall_seconds": wall,
        "browser_seconds": None,
        "requests": 2,
        "bytes": 100,
        "matches": matches,
        "markets": matches * 2,
        "missing": [],
    }


def test_history_aggregation_filters_by_mode_and_reports_rates():
    now = _now()
    history = [
        _scan("prematch", now - timedelta(days=1), {
            "mbet": _book("success", 2.0, 4),
            "wwin": _book("blocked", 1.0, 0),
        }),
        _scan("prematch", now - timedelta(days=2), {
            "mbet": _book("empty", 1.0, 0),
            "wwin": _book("success", 2.0, 2),
        }),
        _scan("live", now - timedelta(days=1), {
            "mbet": _book("success", 3.0, 6),
        }),
        _scan("prematch", now - timedelta(days=30), {
            "mbet": _book("success", 99.0, 1),
        }),
    ]

    report = aggregate(history, days=7, mode="prematch", now=now)

    assert report["scans"] == 2
    assert report["books"] == 2
    assert report["totals"]["matches"] == 6
    assert report["per_book"]["mbet"]["scans"] == 2
    assert report["per_book"]["mbet"]["wall_seconds"] == 3.0
    assert report["per_book"]["mbet"]["failure_rate"] == 0.0
    assert report["per_book"]["wwin"]["failure_rate"] == 0.5
    assert book_failure_rates(history, "prematch")["wwin"] == 0.5


def test_load_history_tolerates_a_missing_or_bad_file(tmp_path):
    assert load_history(tmp_path / "missing.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert load_history(bad) == []


def test_the_cli_prints_the_table_with_explicit_denominators(tmp_path, capsys):
    now = _now()
    path = tmp_path / "scan_cost.json"
    path.write_text(
        json.dumps(
            {
                "history": [
                    _scan("prematch", now - timedelta(days=1), {
                        "mbet": _book("success", 2.0, 4),
                    })
                ]
            }
        ),
        encoding="utf-8",
    )

    assert scan_cost_main(["--days", "7", "--file", str(path)]) == 0

    out = capsys.readouterr().out
    assert "Denominators: 1 scan(s), 1 book(s), 4 match(es)" in out
    assert "Cost/coverage:" in out
    assert "mbet" in out
    assert "s/match" in out


def test_scan_cost_metrics_skip_unmeasured_values(monkeypatch):
    metrics.reset_values()
    monkeypatch.setattr(
        api,
        "_scan_cost_history",
        [
            _scan("prematch", _now(), {
                "mbet": _book("blocked", 2.0, 0),
                "wwin": _book("success", 1.0, 2),
            })
        ],
    )
    report = build_scan_report(
        "prematch",
        _now(),
        {
            "mbet": {
                "outcome": "blocked",
                "wall_seconds": 2.0,
                "browser_seconds": None,
                "requests": 1,
                "bytes": None,
                "matches": 0,
                "markets": 0,
                "missing": [],
            },
            "wwin": {
                "outcome": "success",
                "wall_seconds": 1.0,
                "browser_seconds": 0.5,
                "requests": 2,
                "bytes": 100,
                "matches": 2,
                "markets": 4,
                "missing": [],
            },
        },
    )
    try:
        api._record_scan_cost_metrics(report)
        text = metrics.render()
    finally:
        metrics.reset_values()

    assert 'bh_book_seconds{book="mbet",mode="prematch"} 2' in text
    assert 'bh_book_requests{book="wwin",mode="prematch"} 2' in text
    assert 'bh_book_bytes{book="wwin",mode="prematch"} 100' in text
    assert 'bh_book_failure_rate{book="mbet",mode="prematch"} 1' in text
    assert 'bh_book_bytes{book="mbet",mode="prematch"}' not in text


def test_health_exposes_the_last_scan_cost_without_urls(monkeypatch):
    report = build_scan_report(
        "prematch",
        _now(),
        {
            "mbet": {
                "outcome": "success",
                "wall_seconds": 2.0,
                "browser_seconds": None,
                "requests": 4,
                "bytes": 1000,
                "matches": 10,
                "markets": 20,
                "missing": [],
            }
        },
    )
    monkeypatch.setattr(api, "_scan_cost", {"prematch": report, "live": {}})

    body = asyncio.run(api.health())

    assert body["scan_cost"]["prematch"]["totals"]["books"] == 1
    assert body["scan_cost"]["prematch"]["books"]["mbet"]["requests"] == 4
    serialized = json.dumps(body["scan_cost"])
    assert "http://" not in serialized and "https://" not in serialized
    assert "headers" not in serialized.lower()


def test_the_dashboard_has_a_cost_table_without_payload_fields():
    assert 'id="scan-cost"' in HTML
    assert 'id="scan-cost-body"' in HTML
    assert "renderScanCost" in JS
    assert "scan_cost" in JS
    assert "Cookies" not in HTML
