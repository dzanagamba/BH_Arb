"""Run one or more real scans and record their per-sport metrics as dated evidence.

    python scripts/record_scan.py prematch --out docs/evidence/2026-11-11-scan
    python scripts/record_scan.py prematch live --out docs/evidence/2026-11-11-scan

The scan uses the configured feeds and the same ``run_scan`` path as the
dashboard. Persisted runtime state is restored first, exactly as the app's
lifespan does (SR8-4), so the diagnostic stores are extended instead of rebuilt
from empty globals. Each mode's report is written as ``<out>/<mode>-scan.json``
after that mode finishes, so the numbers cannot drift from the cache.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server import api  # noqa: E402
from server.app import _restore_state  # noqa: E402


def _scan_report(mode: str) -> dict:
    """Snapshot one finished feed's metrics, in the evidence report shape."""
    status, surebets, matches, report, per_bookmaker = api._state_for(mode)
    group_statuses: dict[str, int] = {}
    for group in report:
        value = str(group.get("status", "unknown"))
        group_statuses[value] = group_statuses.get(value, 0) + 1
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": mode,
        "matches": len(matches),
        "surebets": len(surebets),
        "groups": len(report),
        "group_statuses": dict(sorted(group_statuses.items())),
        "sport_stats": api._sport_summary(matches, report, surebets),
        "unmapped_markets": dict(api.unmapped_markets),
        "errors": list(status.errors),
        "bookmakers": dict(sorted(per_bookmaker.items())),
    }


async def run_modes(modes: list[str]) -> list[dict]:
    """Restore persisted state once, then run one scan per mode.

    Without the restore a fresh process scans with empty diagnostic globals and
    ``_finish_scan_cost`` rewrites ``cache/scan_cost.json`` with only the new
    rows, wiping the history the app had restored (SR8-4).
    """
    _restore_state()
    reports: list[dict] = []
    for mode in modes:
        await api.run_scan(mode)
        reports.append(_scan_report(mode))
    return reports


async def run(mode: str) -> dict:
    """Run one scan with the persisted state restored first (SR8-4)."""
    return (await run_modes([mode]))[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "modes",
        nargs="+",
        metavar="mode",
        choices=("prematch", "live"),
        help="one or more feeds to scan in this invocation",
    )
    parser.add_argument(
        "--out",
        help="write one <mode>-scan.json report per mode into this directory",
    )
    args = parser.parse_args(argv)
    reports = asyncio.run(run_modes(args.modes))
    texts = {
        report["mode"]: json.dumps(report, indent=2, sort_keys=True) + "\n"
        for report in reports
    }
    if args.out:
        output_dir = Path(args.out)
        output_dir.mkdir(parents=True, exist_ok=True)
        for mode, text in texts.items():
            (output_dir / f"{mode}-scan.json").write_text(text, encoding="utf-8")
    for text in texts.values():
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
