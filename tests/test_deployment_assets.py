"""P1-3: the deployment assets stay complete and non-root.

The image itself is built by the optional Docker workflow / `docker_smoke.py`;
these checks are the fast, offline guard that the files still describe the
deployment the roadmap promises.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
COMPOSE = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
SYSTEMD = (REPO_ROOT / "deploy" / "bh-arb.service").read_text(encoding="utf-8")
SMOKE = (REPO_ROOT / "scripts" / "docker_smoke.py").read_text(encoding="utf-8")
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
DEPLOYMENT = (REPO_ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")


def test_dockerfile_is_python311_slim_and_installs_playwright():
    assert "FROM python:3.11-slim" in DOCKERFILE
    assert "playwright install --with-deps chromium" in DOCKERFILE
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in DOCKERFILE
    assert "pip install --no-cache-dir -r requirements.txt" in DOCKERFILE


def test_dockerfile_runs_as_a_non_root_user():
    assert "USER scanner" in DOCKERFILE
    assert "USER root" not in DOCKERFILE
    assert "useradd" in DOCKERFILE
    assert "groupadd" in DOCKERFILE
    # Code must be owned by the runtime user, not just readable by it.
    assert "--chown=${BH_UID}:${BH_GID}" in DOCKERFILE


def test_dockerfile_has_a_health_check_on_the_health_route():
    assert "HEALTHCHECK" in DOCKERFILE
    assert "/api/health" in DOCKERFILE
    assert "urllib.request" in DOCKERFILE


def test_dockerignore_keeps_runtime_state_secrets_and_dev_caches_out():
    for entry in (
        ".git",
        ".venv",
        "cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".env",
        "config/generated/mapping_evidence.json",
    ):
        assert entry in DOCKERIGNORE, entry
    # The tracked generated market registry must stay in the image.
    assert "config/generated/bookmaker_markets.json" not in DOCKERIGNORE


def test_compose_mounts_persistent_state_and_checks_health():
    assert "./cache:/app/cache" in COMPOSE
    assert "./config:/app/config" in COMPOSE
    assert 'HOST: "0.0.0.0"' in COMPOSE
    assert "/api/health" in COMPOSE
    assert "healthcheck:" in COMPOSE
    assert "127.0.0.1:${BH_PORT:-8000}:8000" in COMPOSE
    assert "read_only: true" in COMPOSE
    assert "no-new-privileges:true" in COMPOSE


def test_systemd_unit_is_non_root_and_scoped_to_state_directories():
    assert "[Service]" in SYSTEMD
    assert "User=bh-arb" in SYSTEMD
    assert "Group=bh-arb" in SYSTEMD
    assert "ExecStart=/opt/bh-arb/.venv/bin/python /opt/bh-arb/main.py" in SYSTEMD
    assert "EnvironmentFile=-/etc/bh-arb.env" in SYSTEMD
    assert "Restart=on-failure" in SYSTEMD
    assert "ProtectSystem=strict" in SYSTEMD
    assert "ProtectHome=true" in SYSTEMD
    assert "ReadWritePaths=/opt/bh-arb/cache" in SYSTEMD
    assert "ReadWritePaths=/opt/bh-arb/config/generated" in SYSTEMD


def test_smoke_script_builds_runs_checks_nonroot_and_restart_persistence():
    assert "/api/health" in SMOKE
    assert "docker" in SMOKE
    assert '"build"' in SMOKE
    assert '"restart"' in SMOKE
    assert '"id", "-u"' in SMOKE
    assert "smoke-marker" in SMOKE
    assert "non-root" in SMOKE


def test_readme_has_copy_paste_deployment_steps():
    assert "## Deployment" in README
    assert "docker compose up --build -d" in README
    assert "docs/DEPLOYMENT.md" in README
    assert "curl -fsS http://127.0.0.1:8000/api/health" in README


def test_deployment_doc_covers_backup_and_restore_of_trust_inputs():
    for path in (
        "cache/",
        "config/generated/mapping_evidence.json",
        "config/team_alias_allowlist.json",
        "config/bookmaker_deeplinks.json",
    ):
        assert path in DEPLOYMENT, path
    assert "Backup" in DEPLOYMENT
    assert "Restore" in DEPLOYMENT
    assert "non-root" in DEPLOYMENT
    assert "5–10 minutes" in DEPLOYMENT


def test_docker_workflow_is_optional_and_runs_the_smoke_test():
    workflow = (REPO_ROOT / ".github" / "workflows" / "docker.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch" in workflow
    assert "docker build" in workflow
    assert "scripts/docker_smoke.py" in workflow
