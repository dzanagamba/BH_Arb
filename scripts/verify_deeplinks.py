"""
CLI for on-demand deep-link verification.

The verifier itself lives in `server/deeplink_verifier.py`: `/api/verify-links`
imports it from there and coverage measures it. This module only loads cached
matches, prints the report and stores verdicts, so the command below keeps the
same names and behaviour it always had.

    python scripts/verify_deeplinks.py mozzartbet --limit 3
    python scripts/verify_deeplinks.py mozzartbet --limit 20 --offset 20

It is deliberately NOT part of a scan: each event costs a real browser
navigation (seconds), so triggering it from `run_scan` would turn a scan into
minutes of work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import BOOKMAKERS, CACHE_DIR  # noqa: E402
from engine.deeplinks import supports_event_id  # noqa: E402
from server.deeplink_verifier import (  # noqa: E402
    CRITERION,
    EVENT_ID_KEY_SUFFIXES,
    EVENT_ID_KEYS,
    MAX_BODY_BYTES,
    SETTLE_TIMEOUT_MS,
    LinkOutcome,
    LinkReport,
    LinkTarget,
    apply_report,
    book_owned_host,
    build_targets,
    check_target,
    is_event_id_key,
    json_event_paths,
    payload_evidence,
    rendered_text_evidence,
    verify_bookmaker,
    whole_token_span,
)

# Re-exported for the tests and callers that import the verifier through this
# script; the implementation lives in server/deeplink_verifier.py.
__all__ = [
    "CRITERION",
    "EVENT_ID_KEYS",
    "EVENT_ID_KEY_SUFFIXES",
    "MAX_BODY_BYTES",
    "SETTLE_TIMEOUT_MS",
    "LinkOutcome",
    "LinkReport",
    "LinkTarget",
    "apply_report",
    "book_owned_host",
    "build_targets",
    "check_target",
    "is_event_id_key",
    "json_event_paths",
    "main",
    "payload_evidence",
    "rendered_text_evidence",
    "verify_bookmaker",
    "whole_token_span",
]

def _load_cached_matches(mode: str) -> list[dict]:
    path = os.path.join(CACHE_DIR, "last_live_scan.json" if mode == "live" else "last_scan.json")
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file).get("matches", [])
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bookmakers", nargs="*", help="bookmaker ids (default: every declared one)")
    parser.add_argument("--mode", default="prematch", choices=("prematch", "live"))
    parser.add_argument("--limit", type=int, default=3, help="max events per bookmaker")
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help=(
            "resume at this undecided event (0 = the first one). The CLI has no store of "
            "its own cursor, so this is how a sweep is driven here; the HTTP endpoint derives "
            "the equivalent from the events it has already decided"
        ),
    )
    args = parser.parse_args(argv)

    books = args.bookmakers or [b for b in BOOKMAKERS if supports_event_id(b)]
    matches = _load_cached_matches(args.mode)
    for bookmaker in books:
        if bookmaker not in BOOKMAKERS:
            print(json.dumps({"bookmaker": bookmaker, "error": "unknown bookmaker"}))
            continue
        report = asyncio.run(
            verify_bookmaker(
                bookmaker, matches, mode=args.mode, limit=args.limit, offset=args.offset
            )
        )
        # Store the verdicts exactly as `POST /api/verify-links` does, so the next
        # scan applies the proofs. Imported here: the server module loads its
        # state files on import, which only this branch needs.
        from server import api

        # Merge into what is already stored, never replace it: the module's
        # stores start empty until the server's startup loads them.
        if not api._deep_link_verifications:
            api._deep_link_verifications.update(api._load_deep_link_verifications())
        if not api._deep_link_decisions:
            api._deep_link_decisions.update(api._load_deep_link_decisions())
        api._record_deep_link_outcomes(args.mode, bookmaker, report.outcomes)
        api._record_deep_link_decisions(args.mode, bookmaker, report.outcomes)
        # `asdict`, not `__dict__`: a report's `outcomes` are `LinkOutcome`s, which
        # are not JSON-serialisable, so printing `__dict__` raised TypeError on the
        # first completed check — the command in this module's own docstring.
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
