# Release checklist (N1-4)

A release is a tag push (`v*`) or a manual `Release` workflow run. The normal CI
still runs on the tag push; the release workflow adds the two artifacts that
must be proven at release time: a built image that serves `/api/health`, and an
SBOM generated from the runtime environment that `requirements.txt` resolves to.

## What runs where

| Workflow | Trigger | Proof |
|---|---|---|
| `CI` | every push and pull request | Ruff, MyPy, generated market doc, full pytest on 3.11/3.12, both ledger modes, pip-audit, Bandit, CycloneDX SBOM artifact. |
| `Docker` | PR/push touching deployment inputs, or manual | Builds the image with GHA layer cache and runs `scripts/docker_smoke.py`: `/api/health`, non-root user, cache survives restart. |
| `Release` | `v*` tag or manual | CycloneDX SBOM artifact plus the same Docker smoke; a failed smoke fails the release workflow. |
| Dependabot | weekly | Grouped runtime and dev dependency PRs; each PR runs the normal pull-request CI. |

The Docker job is deliberately path-triggered rather than part of the fast unit
job. The Chromium layer is the expensive part.

## Release checklist

1. Confirm the tag is on a commit whose `CI` run is green.
2. Confirm `sbom` is green and the `sbom-cyclonedx` artifact is present.
3. Confirm the `Docker` or `Release` smoke is green.
4. Check `docs/DEPLOYMENT.md` still matches the image and systemd unit.
5. Tag and push; the `Release` workflow is the final gate.

## Local equivalents

```bash
# Quality and tests
python -m pytest
BH_ARB_TEST_RUNTIME_LEDGER=populated python -m pytest
python -m ruff check .
python -m mypy .
python scripts/generate_market_mapping_doc.py --check

# Security
python -m pip_audit -r requirements.lock --progress-spinner off
python -m pip_audit -r requirements-dev.lock --progress-spinner off
python -m bandit -r engine server scrapers config models main.py scripts -ll -q

# SBOM (the resolved runtime lock the image installs, not the manifest)
python -m venv .sbom-venv
.sbom-venv/bin/pip install -r requirements.lock
.sbom-venv/bin/pip freeze --all > sbom-requirements.txt
cyclonedx-py requirements sbom-requirements.txt \
  --of JSON --output-reproducible -o sbom.cdx.json
python - <<'PY'
import json
p = json.load(open("sbom.cdx.json", encoding="utf-8"))
assert p["bomFormat"] == "CycloneDX" and len(p["components"]) >= 27
print(len(p["components"]), "components")
PY

# Docker smoke (build, health, non-root, restart persistence)
python scripts/docker_smoke.py
python scripts/docker_smoke.py --no-build --image bh-arb:local
```

For the same layer cache CI uses:

```bash
docker buildx build --load -t bh-arb:local \
  --cache-from type=gha --cache-to type=gha,mode=max .
```

## Build time

Chromium plus its system libraries is roughly 400 MB and dominates a cold build:
expect **5–10 minutes** on a clean runner. The Dockerfile keeps the browser
install in its own layer after `requirements.txt`, and the workflows restore it
with `cache-from: type=gha`; an app-only change should therefore reuse the
cached layer instead of downloading Chromium again. A requirements change
invalidates the browser layer because it sits above the pip layer.

## Dependency updates

`.github/dependabot.yml` groups updates into:

- **runtime-dependencies** — FastAPI, Uvicorn, Playwright, Pydantic, RapidFuzz,
  HTTPX, python-dotenv and tzdata;
- **dev-dependencies** — pytest/coverage, Ruff, MyPy, Hypothesis, pip-audit,
  Bandit and CycloneDX;
- **github-actions** — all action bumps in one PR; Dependabot rewrites the
  commit-SHA pin and its `# vX.Y.Z` comment together;
- **docker** — the digest pin on `python:3.11-slim`; Dependabot advances the
  `@sha256:` digest and keeps the tag.

Dependabot PRs run the full `CI` workflow. The Docker smoke is path-triggered,
so a dependency-only PR that does not touch a deployment input will not pay the
Chromium build cost; run `Docker` manually when the update changes Playwright or
the runtime requirements.

## Notes and limits

- The SBOM is an inventory of the runtime environment `requirements.txt`
  resolves to; it is not a vulnerability report. `pip-audit` remains the
  vulnerability gate.
- The image job is optional by design for repositories with a build-minute
  budget; the SBOM and dependency-update jobs still run.
- A release is not accepted on a green unit suite alone: the Docker smoke must
  serve `/api/health` from the built image.
