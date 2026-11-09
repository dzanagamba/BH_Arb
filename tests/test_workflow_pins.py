"""GitHub Actions and the Docker base image are pinned (M4-3).

A moving `@v4` tag can be repointed at new code, and a bare `python:3.11-slim`
tag can move at any pull. This project pins every action to a commit SHA with
the version in a comment (which Dependabot reads and updates) and the base image
to a digest. These checks are offline: they prove the pins are present and
well-formed, not that a SHA is still the newest release.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
DEPENDABOT = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

# owner/repository@<40 hex>  # vX.Y.Z or vX
_USES = re.compile(
    r"^\s*-?\s*uses:\s*(?P<repo>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{40})"
    r"\s+#\s*(?P<version>v?\d[^\s]*)\s*$"
)


def test_every_action_is_pinned_to_a_commit_sha_with_a_version_comment():
    offenders: list[str] = []
    checked = 0
    for workflow in WORKFLOWS:
        for number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "uses:" not in line:
                continue
            checked += 1
            if not _USES.match(line):
                offenders.append(f"{workflow.name}:{number}: {line.strip()}")
    assert checked > 0, "no action uses found; the check is untested"
    assert offenders == [], (
        "workflow actions must be pinned to a commit SHA with a version "
        f"comment so Dependabot can update them: {offenders}"
    )


def test_the_base_image_is_pinned_to_a_digest():
    from_lines = [line for line in DOCKERFILE.splitlines() if line.startswith("FROM ")]
    assert from_lines, "the Dockerfile has no FROM line"
    for line in from_lines:
        assert re.search(r"@sha256:[0-9a-f]{64}\b", line), (
            f"base image is not digest-pinned: {line}"
        )
        assert "python:3.11-slim@" in line


def test_dependabot_covers_the_actions_and_docker_pins():
    assert 'package-ecosystem: "github-actions"' in DEPENDABOT
    assert 'package-ecosystem: "docker"' in DEPENDABOT
    # Dependabot updates a SHA pin only when the version comment names it.
    assert "version comment" in DEPENDABOT or "SHA" in DEPENDABOT
