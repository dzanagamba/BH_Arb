"""The resolved locks and the manifests they were generated from (M4-1).

`requirements.txt` pins only the eight direct runtime packages; the image, CI
and the SBOM install `requirements.lock` so a transitive bump cannot change what
was tested. These checks are cheap and network-free, so every push runs them:
they catch the common failure where a direct pin is edited without regenerating
the lock. Regeneration itself is `python scripts/lock_requirements.py`.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = REPO_ROOT / "requirements.txt"
DEV_MANIFEST = REPO_ROOT / "requirements-dev.txt"
RUNTIME_LOCK = REPO_ROOT / "requirements.lock"
DEV_LOCK = REPO_ROOT / "requirements-dev.lock"


def _normalize(name: str) -> str:
    # `uvicorn[standard]` installs `uvicorn`; the lock lists the distribution.
    return name.split("[", 1)[0].strip().lower().replace("_", "-")


def _pins(path: Path) -> dict[str, str]:
    """Parse a requirements file into canonical name -> exact version."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        assert "==" in line, f"{path.name}: {line!r} is not an exact pin"
        name, version = line.split("==", 1)
        key = _normalize(name)
        assert key not in pins, f"{path.name}: duplicate entry for {name}"
        pins[key] = version.strip()
    return pins


def _lock_lines(path: Path) -> list[str]:
    return [
        raw.split("#", 1)[0].strip()
        for raw in path.read_text(encoding="utf-8").splitlines()
        if raw.split("#", 1)[0].strip() and not raw.lstrip().startswith("#")
    ]


def _lock_pins(path: Path) -> list[tuple[str, str]]:
    return [
        (_normalize(line.split("==", 1)[0]), line.split("==", 1)[1].strip())
        for line in _lock_lines(path)
    ]


def _assert_lock_covers(manifest: Path, lock: Path) -> None:
    declared = _pins(manifest)
    locked = dict(_lock_pins(lock))
    missing = {name: version for name, version in declared.items() if locked.get(name) != version}
    assert not missing, f"{lock.name} does not carry {manifest.name}'s pins: {missing}"


def test_runtime_lock_covers_every_runtime_manifest_pin():
    _assert_lock_covers(RUNTIME_MANIFEST, RUNTIME_LOCK)


def test_dev_lock_covers_every_dev_manifest_pin_and_the_runtime_set():
    _assert_lock_covers(DEV_MANIFEST, DEV_LOCK)
    _assert_lock_covers(RUNTIME_MANIFEST, DEV_LOCK)


def test_dev_lock_never_changes_a_runtime_pin():
    runtime = dict(_lock_pins(RUNTIME_LOCK))
    development = dict(_lock_pins(DEV_LOCK))
    mismatched = {
        name: (version, development.get(name))
        for name, version in runtime.items()
        if development.get(name) != version
    }
    assert not mismatched, mismatched


def test_locks_are_sorted_exact_pins_and_exclude_the_bootstrappers():
    for path in (RUNTIME_LOCK, DEV_LOCK):
        entries = _lock_pins(path)
        versions = [line[1] for line in entries]
        assert all(version for version in versions), f"{path.name} has an unpinned entry"
        lines = _lock_lines(path)
        assert lines == sorted(lines), f"{path.name} is not sorted; regenerate it"
        names = {name for name, _ in entries}
        assert not ({"pip", "setuptools", "wheel"} & names), (
            f"{path.name} pins the environment bootstrappers"
        )


def test_runtime_lock_carries_the_resolved_transitives():
    locked = dict(_lock_pins(RUNTIME_LOCK))
    for required in ("starlette", "pydantic-core", "anyio", "h11", "uvicorn"):
        assert required in locked, f"requirements.lock is missing {required}"
    # The manifests are the contract: a lock with only those eight would pass
    # the coverage checks above and hide every transitive.
    assert len(locked) > len(_pins(RUNTIME_MANIFEST))


def test_docker_ci_and_sbom_install_the_locks():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements.lock" in dockerfile
    assert "pip install --no-cache-dir -r requirements.lock" in dockerfile

    for name in ("ci.yml", "release.yml", "docker.yml", "browser.yml"):
        workflow = (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        installs = [
            line
            for line in workflow.splitlines()
            if "pip install" in line and "requirements" in line
        ]
        for line in installs:
            assert "requirements-dev.lock" in line or "requirements.lock" in line, (
                f"{name} installs an unlocked requirement file: {line.strip()}"
            )


def test_the_test_only_httpx2_stays_out_of_the_runtime_lock():
    """M4-5: `httpx2` backs Starlette's TestClient, never the app."""
    assert "httpx2" in dict(_lock_pins(DEV_LOCK))
    assert "httpx2" not in dict(_lock_pins(RUNTIME_LOCK))
    # The runtime client the adapters and respx use is still `httpx`.
    assert "httpx" in dict(_lock_pins(RUNTIME_LOCK))


def test_starlette_testclient_resolves_the_httpx2_dev_pin():
    """The warning-free TestClient is part of the installed dev set."""
    import starlette.testclient as testclient

    assert testclient.httpx.__name__ == "httpx2"
