#!/usr/bin/env python3
"""Precision/recall evaluation over the frozen multi-day replay corpus (P2-4).

The corpus is a set of dated scan extracts with explicit same/different label
pairs. This script runs the real ``MatchMatcher`` on each scan, compares its
verified groups with the labels, and fails when precision drops below the
threshold or a false merge appears.

    python scripts/evaluate_matching.py
    python scripts/evaluate_matching.py --check
    python scripts/evaluate_matching.py --out docs/evidence/matching-eval.json

Labels are not independent ground truth: on the 2026-09-25 and 2026-11-03
captures the fixture was reviewed as one fixture; on 2026-11-04 the labels are
the gate-reviewed groups from that scan plus cross-group negatives. The report
states that limit and the books/modes it covers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.matcher import MatchMatcher  # noqa: E402
from models.schemas import Match  # noqa: E402


def match_key(match: Match) -> str:
    if match.event_id:
        return f"{match.bookmaker}|{match.event_id}"
    return f"{match.bookmaker}|{match.home_team}|{match.away_team}"


def _pair(left: str, right: str) -> tuple[str, str]:
    first, second = sorted((left, right))
    return (first, second)


def _pairs(keys: list[str]) -> set[tuple[str, str]]:
    return {
        _pair(keys[i], keys[j])
        for i in range(len(keys))
        for j in range(i + 1, len(keys))
    }


def evaluate_scan(
    matches: list[Match], labels: dict[str, list[list[str]]]
) -> dict[str, Any]:
    groups = MatchMatcher().group_matches(matches)
    predicted: set[tuple[str, str]] = set()
    for group in groups:
        if group.status != "verified":
            continue
        predicted |= _pairs([match_key(match) for match in group.matches])

    same = {_pair(pair[0], pair[1]) for pair in labels.get("same", [])}
    different = {
        _pair(pair[0], pair[1]) for pair in labels.get("different", [])
    }
    true_positive = len(same & predicted)
    false_negative = len(same - predicted)
    false_positive = len(different & predicted)
    true_negative = len(different - predicted)

    precision = true_positive / (true_positive + false_positive) if (
        true_positive + false_positive
    ) else 1.0
    recall = true_positive / len(same) if same else 1.0
    false_merge_rate = false_positive / (true_positive + false_positive) if (
        true_positive + false_positive
    ) else 0.0

    books = sorted({match.bookmaker for match in matches})
    sports = sorted({match.sport for match in matches})
    return {
        "matches": len(matches),
        "groups": len(groups),
        "verified_groups": sum(1 for group in groups if group.status == "verified"),
        "books": books,
        "sports": sports,
        "labels": {
            "same": len(same),
            "different": len(different),
        },
        "true_positive": true_positive,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "strict_miss_rate": round(
            false_negative / len(same), 4
        ) if same else 0.0,
        "false_merge_rate": round(false_merge_rate, 4),
    }


def load_corpus(root: Path) -> list[dict[str, Any]]:
    days: list[dict[str, Any]] = []
    for day_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        scans: list[tuple[Path, Path]] = []
        labels_dir = day_dir / "labels"
        legacy_labels = labels_dir / "labels.json"
        if (day_dir / "scan.json").exists() and legacy_labels.exists():
            scans.append((day_dir / "scan.json", legacy_labels))
        for scan_path in sorted(day_dir.glob("*.json")):
            if scan_path.name == "scan.json":
                continue
            label_path = labels_dir / f"{scan_path.stem}.json"
            if label_path.exists():
                scans.append((scan_path, label_path))
        for scan_path, label_path in scans:
            payload = json.loads(scan_path.read_text(encoding="utf-8"))
            label_payload = json.loads(label_path.read_text(encoding="utf-8"))
            rows = payload.get("matches")
            if not isinstance(rows, list):
                raise SystemExit(f"{scan_path}: expected a 'matches' list")
            matches = [Match.model_validate(row) for row in rows]
            result = evaluate_scan(matches, label_payload)
            result.update(
                {
                    "day": day_dir.name,
                    "mode": payload.get("mode", "prematch"),
                    "source": str(scan_path),
                    "label_source": str(label_path),
                    "note": payload.get("note", ""),
                }
            )
            days.append(result)
    return days


def summarize(days: list[dict[str, Any]]) -> dict[str, Any]:
    same = sum(day["labels"]["same"] for day in days)
    different = sum(day["labels"]["different"] for day in days)
    tp = sum(day["true_positive"] for day in days)
    tn = sum(day["true_negative"] for day in days)
    fp = sum(day["false_positive"] for day in days)
    fn = sum(day["false_negative"] for day in days)
    return {
        "days": len({day["day"] for day in days}),
        "scans": len(days),
        "modes": sorted({day["mode"] for day in days}),
        "books": sorted({book for day in days for book in day["books"]}),
        "labels": {"same": same, "different": different},
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else 1.0,
        "recall": round(tp / same, 4) if same else 1.0,
        "strict_miss_rate": round(fn / same, 4) if same else 0.0,
        "false_merge_rate": round(fp / (tp + fp), 4) if (tp + fp) else 0.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(REPO_ROOT / "tests" / "fixtures" / "replay"),
    )
    parser.add_argument("--min-precision", type=float, default=0.99)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--max-false-merge-rate", type=float, default=0.0)
    parser.add_argument("--min-days", type=int, default=3)
    parser.add_argument("--out", default="")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    days = load_corpus(Path(args.root))
    total = summarize(days)
    report = {
        "corpus": str(Path(args.root)),
        "days": days,
        "totals": total,
        "thresholds": {
            "min_precision": args.min_precision,
            "min_recall": args.min_recall,
            "max_false_merge_rate": args.max_false_merge_rate,
            "min_days": args.min_days,
        },
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")

    problems: list[str] = []
    if total["days"] < args.min_days:
        problems.append(f"corpus has {total['days']} days, need {args.min_days}")
    if total["precision"] < args.min_precision:
        problems.append(
            f"precision {total['precision']:.2%} below {args.min_precision:.2%}"
        )
    if total["recall"] < args.min_recall:
        problems.append(f"recall {total['recall']:.2%} below {args.min_recall:.2%}")
    if total["false_merge_rate"] > args.max_false_merge_rate:
        problems.append(
            f"false-merge rate {total['false_merge_rate']:.2%} above "
            f"{args.max_false_merge_rate:.2%}"
        )
    if {"prematch", "live"} - set(total["modes"]):
        problems.append(f"corpus is missing modes: {sorted({'prematch', 'live'} - set(total['modes']))}")
    if args.check and problems:
        print("FAIL: " + "; ".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
