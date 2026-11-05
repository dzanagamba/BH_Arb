"""Refresh the dated market fixtures and their parser contracts (N2-6).

Two jobs, deliberately separate:

* ``--capture`` re-runs the real live capture (``capture_market_fixtures.py``).
  A network failure is reported as **capture failed**, never as "the feed
  changed".
* ``--write`` recomputes ``tests/fixtures/markets/contracts.json`` from the
  fixtures on disk and prints the diff against the reviewed expectation.
  ``--check`` (the CI form) fails when the payload changed without an updated
  expectation, when an enabled book has no dated contract, or when a fixture is
  older than the policy in the contract file.

The script never edits the market registry, a parser or a trust rule. A new id
in a diff is a prompt for a human re-capture and the existing admissibility
evidence, not an automatic admission.

    python scripts/refresh_fixtures.py --check
    python scripts/refresh_fixtures.py --capture --write
    python scripts/refresh_fixtures.py --books maxbet,wwin --write
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import BOOKMAKERS  # noqa: E402
from engine.parser_contracts import (  # noqa: E402
    CONTRACTS_PATH,
    compute_all,
    diff_all,
    load_contracts,
    save_contracts,
    stale_contracts,
)


def enabled_books() -> list[str]:
    return sorted(book for book, config in BOOKMAKERS.items() if config.get("enabled"))


def _missing_books(contracts: dict[str, dict[str, Any]]) -> list[str]:
    covered = {str(contract.get("bookmaker")) for contract in contracts.values()}
    return [book for book in enabled_books() if book not in covered]


def build_report(
    *,
    contracts_path: Path = CONTRACTS_PATH,
    today: date | None = None,
) -> dict[str, Any]:
    """Compare the shipped fixtures with their reviewed contracts."""
    payload = load_contracts(contracts_path)
    expected = payload.get("contracts") or {}
    actual = compute_all(contracts_path.parent)
    diff = diff_all(expected, actual)
    max_age = int(payload.get("max_age_days") or 120)
    stale = stale_contracts(actual, max_age_days=max_age, today=today)
    missing = _missing_books(actual)
    ok = not diff["added"] and not diff["removed"] and not diff["changed"] and not stale and not missing
    return {
        "ok": ok,
        "contracts": len(actual),
        "max_age_days": max_age,
        "diff": diff,
        "stale": stale,
        "missing_books": missing,
        "capture": "not_requested",
    }


def capture(books: list[str]) -> dict[str, Any]:
    """Run the live capture; distinguish a capture failure from feed drift."""
    command = [sys.executable, str(REPO_ROOT / "scripts" / "capture_market_fixtures.py")]
    if books:
        command += ["--books", ",".join(books)]
    completed = subprocess.run(
        command, cwd=REPO_ROOT, text=True, capture_output=True, check=False
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "status": "ok" if completed.returncode == 0 else "capture_failed",
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-12:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-12:]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="CI form; non-zero on drift")
    parser.add_argument("--write", action="store_true", help="write the contract file")
    parser.add_argument("--capture", action="store_true", help="re-run the live capture")
    parser.add_argument("--books", default="", help="comma-separated subset for --capture")
    parser.add_argument("--contracts", default=str(CONTRACTS_PATH))
    parser.add_argument("--json", default="", help="write the report here")
    args = parser.parse_args(argv)

    contracts_path = Path(args.contracts)
    books = [book.strip() for book in args.books.split(",") if book.strip()]
    capture_report = capture(books) if args.capture else {"status": "not_requested"}
    if args.capture and capture_report["status"] != "ok":
        report = {"ok": False, "capture": capture_report}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1

    report = build_report(contracts_path=contracts_path)
    report["capture"] = capture_report
    if args.write:
        before = load_contracts(contracts_path).get("contracts") or {}
        actual = compute_all(contracts_path.parent)
        save_contracts(
            actual,
            contracts_path,
            max_age_days=int(load_contracts(contracts_path).get("max_age_days") or 120),
        )
        report = build_report(contracts_path=contracts_path)
        report["capture"] = capture_report
        report["written"] = len(actual)
        report["changed_from_previous"] = diff_all(before, actual)

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
    if args.check and not report["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
