"""The replay harness is deterministic and its acceptance gate is real."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
CORPUS = REPO_ROOT / "tests" / "fixtures" / "replay" / "2026-11-03"
SCRIPT = REPO_ROOT / "scripts" / "replay_mappings.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(CORPUS), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _report(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_replay_is_deterministic_except_for_the_timestamp():
    first = _report(_run("--no-learn"))
    second = _report(_run("--no-learn"))
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


def test_replay_records_the_acceptance_metrics():
    report = _report(_run("--no-learn"))
    for key in (
        "matches_total",
        "books",
        "pairs_total",
        "pairs_evidence_backed",
        "pairs_verified",
        "pairs_rejected",
        "pairs_quarantined",
        "pairs_unresolved",
        "false_merges",
        "groups_verified",
        "surebets_count",
        "market_rows_total",
        "market_rows_mapped",
        "market_rows_unmapped",
    ):
        assert key in report
    assert report["matches_total"] == 3
    assert report["pairs_evidence_backed"] >= 1
    assert report["false_merges"] == 0


def test_check_passes_on_the_frozen_corpus():
    result = _run("--check")
    assert result.returncode == 0, result.stderr


def test_cold_mode_is_a_different_label_and_same_measurement():
    seeded = _report(_run("--seeded", "--no-learn"))
    cold = _report(_run("--cold", "--no-learn"))
    seeded.pop("generated_at")
    cold.pop("generated_at")
    seeded.pop("mode")
    cold.pop("mode")
    assert seeded == cold
