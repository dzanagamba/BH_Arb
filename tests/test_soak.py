"""The soak report fails on memory growth or a leaked browser."""

from __future__ import annotations

from scripts.soak import Sample, summarize


def _sample(rss: float, browsers: int = 0) -> Sample:
    return Sample("2026-11-03T00:00:00", 100, 10, 1, rss, browsers)


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
