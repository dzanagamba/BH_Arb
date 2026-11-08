"""P1-4: CI publishes coverage and runs dependency and security scans."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_DEV = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
PYPROJECT = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
CI = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
DOC = (REPO_ROOT / "docs" / "CI.md").read_text(encoding="utf-8")
GITIGNORE = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
API = (REPO_ROOT / "server" / "api.py").read_text(encoding="utf-8")
SCORING = (REPO_ROOT / "server" / "candidate_scoring.py").read_text(encoding="utf-8")
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))


def test_dev_requirements_pin_the_coverage_and_scan_tools():
    for line in ("pytest-cov==", "coverage==", "pip-audit==", "bandit=="):
        assert line in REQUIREMENTS_DEV, line


def test_coverage_is_scoped_and_has_a_measured_floor():
    assert 'source = ["engine", "server", "scrapers", "config", "models"]' in PYPROJECT
    assert "fail_under = 80" in PYPROJECT
    # Tests and operator scripts must not pad the denominator.
    assert '"tests"' not in PYPROJECT.split("[tool.coverage.run]", 1)[1].split("[", 1)[0]


def test_ci_runs_tests_with_coverage_and_publishes_the_report():
    assert "python -m pytest --cov" in CI
    assert "--cov-report=term-missing" in CI
    assert "--cov-report=xml" in CI
    assert "coverage.xml" in CI
    assert "actions/upload-artifact" in CI
    assert "coverage report --format=markdown" in CI
    assert "GITHUB_STEP_SUMMARY" in CI


def test_ci_runs_dependency_and_static_security_scans_on_every_push_and_pr():
    assert "on:\n  push:\n  pull_request:" in CI
    assert "python -m pip_audit -r requirements.txt" in CI
    assert "python -m pip_audit -r requirements-dev.txt" in CI
    assert "python -m bandit" in CI
    assert "-ll" in CI
    assert "security:" in CI
    assert "permissions:\n  contents: read" in CI


def test_ci_keeps_python_311_required_and_checks_312():
    assert 'python-version: ["3.11", "3.12"]' in CI
    assert "matrix.python-version == '3.11'" in CI


def test_every_workflow_is_least_privilege():
    assert WORKFLOWS, "no workflows found"
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        assert "permissions:\n  contents: read" in text, workflow.name
        assert "contents: write" not in text, workflow.name


def test_development_install_matches_ci():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    install = "pip install -r requirements.txt -r requirements-dev.txt"
    assert install in CI
    assert install in readme


def test_allowlisted_findings_are_documented_at_the_call_site_and_in_the_doc():
    capture = (REPO_ROOT / "scripts" / "capture_market_fixtures.py").read_text(
        encoding="utf-8"
    )
    smoke = (REPO_ROOT / "scripts" / "docker_smoke.py").read_text(encoding="utf-8")
    soak = (REPO_ROOT / "scripts" / "soak.py").read_text(encoding="utf-8")

    assert "# nosec B501" in capture
    assert smoke.count("# nosec B310") == 1
    assert soak.count("# nosec B310") == 2
    for rule in ("B501", "B310"):
        assert rule in DOC, rule
    assert "usedforsecurity=False" in SCORING
    assert "PYSEC-2026-1845" in DOC


def test_coverage_artifacts_are_gitignored():
    for entry in (".coverage", "coverage.xml", "htmlcov/"):
        assert entry in GITIGNORE, entry
