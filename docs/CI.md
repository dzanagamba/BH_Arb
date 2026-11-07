# CI, coverage and security scans

P1-4/N1-4 hardening. Every push and pull request runs four jobs:

| Job | What it does |
|---|---|
| `quality` | Ruff, MyPy, the generated-market-doc check and the dated sport/market admissibility audit on Python 3.11. |
| `tests` | Full pytest suite on Python 3.11 and 3.12. The 3.11 leg also measures coverage, writes a markdown summary to the workflow run page, and uploads `coverage.xml`. The 3.11 leg then runs the opt-in property load budgets separately. |
| `security` | `pip-audit` against both requirement files and Bandit at medium severity and above. |
| `sbom` | CycloneDX JSON from the resolved runtime environment (a clean venv with `requirements.txt` installed), verified to cover the whole resolved set and uploaded as `sbom-cyclonedx`. |

Python 3.11 stays the required runtime (it is what the container and the systemd
unit use). 3.12 is a forward-compatibility check, not a second support promise.

## Hermetic tests and runtime state

The offline suite must give the same result on a clean checkout and on an
operator machine with a populated `config/generated/mapping_evidence.json`,
`cache/` and SQLite store (N0-1). `tests/conftest.py` enforces this:

* An autouse fixture redirects `engine.matcher.MAPPING_EVIDENCE_FILE`,
  `engine.mapping_evidence.DEFAULT_PATH`, `config.settings.CACHE_DIR`, every
  JSON cache file in `server/api.py`, and `STORAGE_PATH` into a per-test
  temporary tree.
* A session-scoped guard fingerprints `config/generated/` and `cache/` at the
  start and fails the run if any test added, removed or changed a file there.
* Shipped config inputs (`config/bookmaker_markets.json`, the deeplink
  declarations, the reviewed allowlist) are not redirected: they are source, not
  runtime state.

A test that intentionally reads this machine's runtime state is marked
`@pytest.mark.real_runtime_state` and is skipped unless
`BH_ARB_TEST_RUNTIME_STATE=1` is set. Never delete or rewrite the operator's
ledger to make a test pass; redirect the path instead.

The CI `tests` job runs the suite twice on Python 3.11: once with no generated
ledger (the coverage run) and once with
`BH_ARB_TEST_RUNTIME_LEDGER=populated`, which seeds the redirected ledger with
the one alias claim that used to break `tests/test_e2e_certified.py`. Run both
modes locally with:

```bash
python scripts/check_test_isolation.py
```

## Parser contracts

The 3.11 leg also runs `python scripts/refresh_fixtures.py --check`. It fails
when a frozen market fixture no longer matches its dated contract (top-level
keys, source-id set, labels, nested shape), when an enabled book has no
contract, or when a capture is older than the 120-day policy. A capture failure
is reported separately and never treated as a feed change. See
`docs/PARSER_CONTRACTS.md` for the refresh cadence and the diff format.

## Admissibility audit

The `quality` job runs `python scripts/audit_admissibility.py --check` (N3-2).
It compares a fresh offline report with
`docs/evidence/2026-11-05-admissibility-baseline.json` and fails when an admitted
sport/market/family disappears, a settlement changes or the three-book rule was
lowered. New families are warnings and are never auto-admitted. The live
bookmaker probe (`scripts/measure_sports.py`) stays out of CI; see
`docs/ADMISSIBILITY_AUDIT.md` for the weekly operator procedure.

## Property tests and load budgets

The fast suite includes the property-based pricing and identity tests
(`tests/test_properties_pricing.py`, `tests/test_properties_identity.py`). A
separate 3.11 step runs the opt-in load budgets:

```bash
BH_ARB_TEST_SLOW=1 python -m pytest tests/test_perf_budgets.py
```

Without `BH_ARB_TEST_SLOW=1` those two tests are skipped, so the normal suite
keeps its runtime. See `docs/PROPERTY_TESTS.md` for the invariants, the budgets
and the local commands.

## Coverage

The measured baseline on 2026-11-06 was **85.63%** across
`engine`, `server`, `scrapers`, `config` and `models` (11,639 statements).
`pyproject.toml` sets `fail_under = 80`, a deliberately small cushion below that
baseline. The old roadmap's rule was: do not set an arbitrary high coverage
threshold that forces low-value tests; use the current measured baseline. Raise
the number as real coverage improves.

Tests, operator scripts and generated runtime state are outside the measured
packages. The suite itself is not the product.

Reproduce locally:

```bash
python -m pytest --cov --cov-report=term-missing
python -m coverage report --format=markdown
```

`coverage.xml` is gitignored build output; the CI job uploads it as an
artifact.

## Dependency audit

```bash
python -m pip_audit -r requirements.txt --progress-spinner off
python -m pip_audit -r requirements-dev.txt --progress-spinner off
```

Both files must be clean. `pip-audit` fails the job on any advisory with an
available resolution.

The first audit found `pytest 8.4.1` affected by `PYSEC-2026-1845`, fixed in
`9.0.3`. The dev dependency was upgraded rather than allowlisted, and the full
suite was re-run on pytest 9.

If a future advisory has **no fixed version**, or is provably not reachable in
this project, add `--ignore-vuln <ID>` to the relevant CI step **and** record
the id, the reason and the review date here. Never silently skip an advisory.

## SBOM

The image installs `requirements.txt`, which pins the eight direct dependencies
and resolves to 27 runtime packages (29 including pip and setuptools). The `sbom` job installs that file into a clean venv
and generates CycloneDX JSON from the resolved set, so the artifact describes
what the image actually contains rather than the 8-line manifest:

```bash
python -m venv .sbom-venv
.sbom-venv/bin/pip install -r requirements.txt
.sbom-venv/bin/pip freeze --all > sbom-requirements.txt
cyclonedx-py requirements sbom-requirements.txt \
  --of JSON --output-reproducible -o sbom.cdx.json
```

The job asserts `bomFormat == "CycloneDX"`, a spec version, at least 27
components, and that `starlette` and `pydantic-core` (resolved transitives) are
present, so a regression back to the 8-component manifest-only output fails. It
then uploads `sbom-cyclonedx` for 90 days. `--output-reproducible` keeps the
document stable for the same resolved set. The release workflow runs the same
steps, so a release artifact and a PR artifact come from the same resolution.
`cyclonedx-bom==8.0.1` is in `requirements-dev.txt`; it is not part of the
runtime image.

The SBOM is an inventory, not a vulnerability report. `pip-audit` remains the
vulnerability gate.

## Release and dependency updates

`.github/workflows/release.yml` runs on a `v*` tag or manually: it regenerates
the SBOM and runs the Docker smoke. A failed smoke fails the release workflow.
`.github/dependabot.yml` groups runtime dependencies, dev dependencies, GitHub
Actions and the Docker base image into separate weekly PRs; every PR runs this
full CI. See `docs/RELEASE.md` for the checklist and local equivalents.

## Static security scan

```bash
python -m bandit -r engine server scrapers config models main.py scripts -ll -q
```

`-ll` means medium and above fail the job; low-severity style findings are still
printed in a non-`-q` run but do not block. The current baseline has only
low-severity findings: best-effort `try/except/pass` cleanup, an `assert` in a
developer mapping script, and fixed-argument `subprocess` calls in the operator
scripts. They are accepted, not hidden.

### Allowlist

The allowlist is inline `# nosec` with a short reason, so it is visible at the
call site and in review. There are four accepted entries:

| Location | Rule | Why it is accepted |
|---|---|---|
| `scripts/capture_market_fixtures.py` (`main`) | `B501` (`verify=False`) | Capture-only developer tool. Some bookmaker hosts present an invalid chain from a developer machine; it reads public pages and never sends credentials. |
| `scripts/docker_smoke.py` (`_health`) | `B310` (`urlopen`) | Fixed `http://127.0.0.1:<port>/api/health` loopback probe. |
| `scripts/soak.py` (`_get_json`, `_post`) | `B310` (`urlopen`) | Operator-supplied scanner endpoint, normally loopback HTTP. |
| `server/alerts.py` (webhook/Telegram `send`) | `B310` (`urlopen`) | Operator-configured HTTPS webhook or the fixed Telegram Bot API endpoint; URL/token are never logged. |
| `scripts/sweep_links.py` (`_post_json`) | `B310` (`urlopen`) | Operator-supplied scanner endpoint, normally loopback HTTP. |

`server/api.py`'s SHA-1 pair id was not allowlisted: it is a stable queue key,
not a security primitive, and now passes `usedforsecurity=False` to make that
explicit.

Adding a `# nosec` requires the same review as changing the rule itself: put the
reason in the surrounding comment and add a row to the table above.
