"""Run one real scan and record its per-sport metrics as dated evidence.

    python scripts/record_scan.py prematch --out docs/evidence/...-prematch-scan.json
    python scripts/record_scan.py live --out docs/evidence/...-live-scan.json

The scan uses the configured feeds and the same ``run_scan`` path as the
dashboard. The report is written after the scan finishes so the numbers cannot
drift from the cache.
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


async def run(mode: str) -> dict:
    await api.run_scan(mode)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("prematch", "live"))
    parser.add_argument("--out", help="write the JSON report here")
    args = parser.parse_args(argv)
    report = asyncio.run(run(args.mode))
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(text)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
