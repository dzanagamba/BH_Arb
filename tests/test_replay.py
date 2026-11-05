"""The replay harness is deterministic and its acceptance gate is real."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
CORPUS = REPO_ROOT / "tests" / "fixtures" / "replay" / "2026-11-03"
SCRIPT = REPO_ROOT / "scripts" / "replay_mappings.py"


def _run(ledger: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the harness against an explicit, empty seed ledger.

    Without ``--ledger`` a replay reads ``config/generated/mapping_evidence.json``,
    which is gitignored runtime state. The harness must not change its answer
    because an operator has a populated ledger on disk (N0-1).
    """
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(CORPUS), "--ledger", str(ledger), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _report(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_replay_is_deterministic_except_for_the_timestamp(tmp_path):
    first = _report(_run(tmp_path / "ledger.json", "--no-learn"))
    second = _report(_run(tmp_path / "ledger.json", "--no-learn"))
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


def test_replay_records_the_acceptance_metrics(tmp_path):
    report = _report(_run(tmp_path / "ledger.json", "--no-learn"))
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


def test_check_passes_on_the_frozen_corpus(tmp_path):
    result = _run(tmp_path / "ledger.json", "--check")
    assert result.returncode == 0, result.stderr


def test_cold_mode_is_a_different_label_and_same_measurement(tmp_path):
    seeded = _report(_run(tmp_path / "seeded.json", "--seeded", "--no-learn"))
    cold = _report(_run(tmp_path / "cold.json", "--cold", "--no-learn"))
    seeded.pop("generated_at")
    cold.pop("generated_at")
    seeded.pop("mode")
    cold.pop("mode")
    assert seeded == cold


def test_cold_start_learns_to_a_fixed_point(tmp_path):
    result = _run(tmp_path / "ledger.json", "--cold", "--check")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["fixed_point"] is True
    assert report["iterations"] >= 1
    assert report["ledger_claims"] >= 1
    assert report["false_merges"] == 0
    assert report["pairs_unresolved"] == 0
