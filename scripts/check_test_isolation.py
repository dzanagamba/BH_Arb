"""Run the offline suite with no generated ledger and with a populated one.

N0-1. The suite must produce the same result on a clean checkout and on an
operator machine whose ``config/generated/mapping_evidence.json`` holds claims.
The isolation fixture in ``tests/conftest.py`` redirects that ledger into a
per-test temporary tree; ``BH_ARB_TEST_RUNTIME_LEDGER=populated`` seeds the
redirected ledger with the claim that used to break the certified end-to-end
test. This script runs both modes, without touching the operator's real ledger.

Usage::

    python scripts/check_test_isolation.py
    python scripts/check_test_isolation.py --pytest-args "-q -x"
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_ENV = "BH_ARB_TEST_RUNTIME_LEDGER"


def _run(mode: str, pytest_args: list[str]) -> int:
    env = {**os.environ, LEDGER_ENV: mode}
    command = [sys.executable, "-m", "pytest", *pytest_args]
    print(f"\n=== {LEDGER_ENV}={mode}: {' '.join(command)} ===", flush=True)
    return subprocess.run(command, cwd=REPO_ROOT, env=env, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pytest-args",
        default="",
        help="extra pytest arguments, as one shell-quoted string",
    )
    args = parser.parse_args(argv)
    pytest_args = shlex.split(args.pytest_args)

    for mode in ("empty", "populated"):
        code = _run(mode, pytest_args)
        if code != 0:
            print(
                f"\nFAIL: the suite failed with {LEDGER_ENV}={mode} (exit {code})",
                file=sys.stderr,
            )
            return code
    print(
        f"\nOK: the suite passes with an empty and a populated generated ledger "
        f"({LEDGER_ENV}=empty|populated)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
