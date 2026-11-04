# CI, coverage and security scans

P1-4 hardening. Every push and pull request runs three jobs:

| Job | What it does |
|---|---|
| `quality` | Ruff, MyPy and the generated-market-doc check on Python 3.11. |
| `tests` | Full pytest suite on Python 3.11 and 3.12. The 3.11 leg also measures coverage, writes a markdown summary to the workflow run page, and uploads `coverage.xml`. |
| `security` | `pip-audit` against both requirement files and Bandit at medium severity and above. |

Python 3.11 stays the required runtime (it is what the container and the systemd
unit use). 3.12 is a forward-compatibility check, not a second support promise.

## Coverage

The measured baseline on 2026-11-04 was **81.55%** (reported as 82%) across
`engine`, `server`, `scrapers`, `config` and `models` (8,096 statements).
`pyproject.toml` sets `fail_under = 80`, a deliberately small cushion below that
baseline; the note in the roadmap says not to invent a high threshold that
forces low-value tests. Raise the number as real coverage improves.

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

`server/api.py`'s SHA-1 pair id was not allowlisted: it is a stable queue key,
not a security primitive, and now passes `usedforsecurity=False` to make that
explicit.

Adding a `# nosec` requires the same review as changing the rule itself: put the
reason in the surrounding comment and add a row to the table above.
