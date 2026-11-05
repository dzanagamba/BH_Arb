"""Scheduled sport/market admissibility re-audit (N3-2).

Two modes:

* ``--check`` (default in CI) compares a fresh report against the shipped dated
  baseline and fails when an admitted sport, market, family, settlement or
  price source disappeared, or when the fixed rule was changed;
* ``--write-baseline`` records a fresh dated snapshot after a human has reviewed
  a new measurement. It never enables a sport or market; that still requires a
  code change and its evidence.

The live network measurement remains ``scripts/measure_sports.py``. Point this
script at its output with ``--sport-evidence`` after copying it under
``docs/evidence/`` with its date in the file name. The default run is offline and
reads only the shipped evidence files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.admissibility import (  # noqa: E402
    DEFAULT_BASELINE,
    build_report,
    detect_changes,
    load_baseline,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--baseline",
        default=DEFAULT_BASELINE,
        help="dated baseline to compare against or write (default: %(default)s)",
    )
    parser.add_argument("--out", help="write the fresh report here")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the fresh report with the baseline and exit 1 on failure",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="write the fresh report as the new baseline (review first)",
    )
    parser.add_argument(
        "--sport-evidence",
        help="override the sport-discovery evidence path (relative to the repo)",
    )
    parser.add_argument(
        "--football-lines-evidence",
        help="override the football-lines evidence path (relative to the repo)",
    )
    parser.add_argument(
        "--prematch-evidence",
        help="override the prematch-scan evidence path (relative to the repo)",
    )
    parser.add_argument(
        "--generated-at",
        help="fixed report timestamp for a reproducible artifact",
    )
    args = parser.parse_args(argv)

    report = build_report(
        sport_evidence=args.sport_evidence,
        football_lines_evidence=args.football_lines_evidence,
        prematch_evidence=args.prematch_evidence,
        generated_at=args.generated_at,
    )

    if args.write_baseline:
        target = Path(args.baseline)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            f"wrote {target} ({len(report.get('sports', {}))} sports, "
            f"{len(report.get('markets', {}))} markets)",
            file=sys.stderr,
        )
        return 0

    if args.check:
        result = detect_changes(report, load_baseline(args.baseline)).as_dict()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result["status"] == "fail" else 0

    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
