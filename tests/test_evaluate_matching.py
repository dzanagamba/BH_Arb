"""P2-4: the frozen corpus is multi-day and the evaluation gate is real."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.evaluate_matching import load_corpus, main, summarize

# The corpus is a frozen real scan, so it must run against the shipped
# declarations, not conftest's synthetic route-declaring MDShop/Admiralbet.
pytestmark = pytest.mark.real_deeplinks

ROOT = Path("tests/fixtures/replay")


def test_corpus_has_three_days_and_both_modes():
    days = load_corpus(ROOT)
    total = summarize(days)

    assert total["days"] >= 3
    assert {"prematch", "live"} <= set(total["modes"])
    assert total["labels"]["same"] >= 100
    assert total["labels"]["different"] >= 20


def test_the_evaluation_reports_denominators_and_zero_false_merges():
    total = summarize(load_corpus(ROOT))

    assert total["precision"] == 1.0
    assert total["recall"] == 1.0
    assert total["false_positive"] == 0
    assert total["false_merge_rate"] == 0.0
    assert total["true_positive"] == total["labels"]["same"]
    assert total["true_negative"] == total["labels"]["different"]


def test_check_passes_on_the_frozen_corpus():
    assert main(["--check"]) == 0


def test_check_fails_when_the_precision_threshold_is_impossible():
    assert main(["--check", "--min-precision", "1.01"]) == 1


def test_check_fails_when_a_required_day_is_missing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["--root", str(empty), "--check"]) == 1
