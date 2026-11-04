"""The soak report fails on memory growth or a leaked browser."""

from __future__ import annotations

from scripts.soak import Sample, cycle_limit, summarize


def _sample(
    rss: float,
    browsers: int = 0,
    *,
    cache_bytes: int = 0,
    books: dict | None = None,
) -> Sample:
    return Sample(
        "2026-11-03T00:00:00",
        100,
        10,
        1,
        rss,
        browsers,
        cache_bytes=cache_bytes,
        books=books or {},
    )


def test_stable_samples_pass():
    report = summarize([_sample(500), _sample(520)])
    assert report["ok"] is True
    assert report["memory_growth"] == 0.04
    assert report["rss_series"] == [500, 520]
    assert [sample["rss_mb"] for sample in report["history"]] == [500, 520]


def test_memory_growth_over_the_limit_fails():
    report = summarize([_sample(500), _sample(800)])
    assert report["ok"] is False
    assert any("memory grew" in problem for problem in report["problems"])


def test_a_browser_left_alive_fails():
    report = summarize([_sample(500, browsers=2)])
    assert report["ok"] is False
    assert any("browser" in problem for problem in report["problems"])


def test_no_samples_fails():
    assert summarize([])["ok"] is False


def test_any_sample_with_a_live_browser_fails_not_only_the_last():
    report = summarize(
        [_sample(500, browsers=2), _sample(520, browsers=0)]
    )

    assert report["ok"] is False
    assert report["browsers_max"] == 2
    assert any("browser" in problem for problem in report["problems"])


def test_an_unavailable_browser_probe_is_not_reported_as_zero():
    report = summarize([_sample(500, browsers=-1)])

    assert report["ok"] is False
    assert any("probe unavailable" in problem for problem in report["problems"])


def test_peak_rss_over_the_budget_fails():
    report = summarize(
        [_sample(500), _sample(1100), _sample(700)],
        rss_budget_mb=1024,
    )

    assert report["ok"] is False
    assert report["rss_max_mb"] == 1100
    assert any("over budget" in problem for problem in report["problems"])


def test_report_records_cache_and_per_book_states():
    books = {
        "mbet": {"state": "healthy", "reasons": []},
        "mdshop": {"state": "quarantined", "reasons": ["empty_feed"]},
    }
    report = summarize(
        [
            _sample(500, cache_bytes=1000, books=books),
            _sample(520, cache_bytes=1200, books=books),
        ]
    )

    assert report["cache_bytes_max"] == 1200
    assert report["cache_bytes_last"] == 1200
    assert report["book_states"]["mbet"]["healthy"] == 2
    assert report["book_states"]["mdshop"]["quarantined"] == 2
    assert report["books_without_healthy"] == ["mdshop"]


def test_zero_cycles_runs_until_the_wall_clock_budget():
    assert cycle_limit(0, 1440) == 0
    assert cycle_limit(0, 0) == 1
    assert cycle_limit(10, 1440) == 10
