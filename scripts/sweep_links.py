#!/usr/bin/env python3
"""Convergent per-book deep-link sweep (P2-1).

``POST /api/verify-links`` already advances its own cursor: it skips every event
this book has a recorded decision on and reports how many are left. This runner
simply calls it until ``remaining`` reaches zero, respecting the endpoint's rate
limit instead of bypassing it, then writes one report.

    python scripts/sweep_links.py --bookmaker mozzartbet --mode prematch
    python scripts/sweep_links.py --bookmaker maxbet --max-calls 20 --check

The report is also what the dashboard posts to ``/api/link-sweeps`` so the
operator can read the last sweep from the same store. A failed event is counted
in the endpoint's ``errored`` field; the loop keeps going, and only a whole
request failure stops it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_REPORT = Path("cache") / "link_sweeps.json"
MAX_REPORTS = 200


class RateLimited(Exception):
    """The endpoint's per-client window refused a call; wait and retry."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited for {retry_after:.1f}s")
        self.retry_after = retry_after


def _post_json(url: str, api_key: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url, method="POST")
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        # Operator-supplied scanner URL; normally loopback HTTP. B310 is
        # documented in docs/CI.md.
        with urllib.request.urlopen(request, timeout=600) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            retry_after = 60.0
            raw = exc.headers.get("Retry-After") if exc.headers else None
            if raw:
                try:
                    retry_after = float(raw)
                except ValueError:
                    pass
            raise RateLimited(retry_after) from exc
        raise


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def sweep(
    base_url: str,
    bookmaker: str,
    *,
    mode: str = "prematch",
    api_key: str = "",
    limit: int = 5,
    max_calls: int = 100,
    interval: float = 2.0,
    post: Callable[[str, str], dict[str, Any]] = _post_json,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Call verify-links until ``remaining`` is zero or the call budget ends."""
    query = urllib.parse.urlencode(
        {"bookmaker": bookmaker, "mode": mode, "limit": limit}
    )
    url = f"{base_url.rstrip('/')}/api/verify-links?{query}"
    report: dict[str, Any] = {
        "bookmaker": bookmaker,
        "mode": mode,
        "started_at": _now(),
        "ended_at": "",
        "status": "running",
        "calls": 0,
        "available": 0,
        "checked": 0,
        "verified": 0,
        "failed": 0,
        "errored": 0,
        "unchecked": 0,
        "remaining": 0,
        "last_next_offset": 0,
        "rate_limit_waits": 0,
        "http_error": "",
        "calls_detail": [],
    }
    rate_limit_waits = 0
    while report["calls"] < max_calls:
        try:
            body = post(url, api_key)
        except RateLimited as exc:
            rate_limit_waits += 1
            if rate_limit_waits > 10:
                report["status"] = "rate_limited"
                report["http_error"] = "rate limit did not clear after 10 waits"
                break
            report["rate_limit_waits"] = rate_limit_waits
            sleep(max(0.0, exc.retry_after))
            continue
        except Exception as exc:  # noqa: BLE001 - report the whole-request failure
            report["status"] = "request_failed"
            report["http_error"] = type(exc).__name__
            break

        report["calls"] += 1
        report["available"] = max(report["available"], int(body.get("available") or 0))
        for key in ("checked", "verified", "failed", "errored", "unchecked"):
            report[key] += int(body.get(key) or 0)
        report["remaining"] = int(body.get("remaining") or 0)
        report["last_next_offset"] = int(body.get("next_offset") or 0)
        report["calls_detail"].append(
            {
                "status": body.get("status"),
                "checked": int(body.get("checked") or 0),
                "verified": int(body.get("verified") or 0),
                "failed": int(body.get("failed") or 0),
                "errored": int(body.get("errored") or 0),
                "unchecked": int(body.get("unchecked") or 0),
                "remaining": int(body.get("remaining") or 0),
            }
        )
        if body.get("status") == "skipped" or report["remaining"] == 0:
            report["status"] = "skipped" if body.get("status") == "skipped" else "converged"
            break
        if report["calls"] < max_calls:
            sleep(max(0.0, interval))

    if report["status"] == "running":
        report["status"] = "budget_exhausted"
    report["ended_at"] = _now()
    return report


def append_report(path: str | Path, report: dict[str, Any]) -> None:
    """Append one sweep to the shared report file, atomically."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"sweeps": []}
    if destination.exists():
        try:
            loaded = json.loads(destination.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("sweeps"), list):
                payload = loaded
        except (OSError, ValueError):
            payload = {"sweeps": []}
    payload["sweeps"].append(report)
    payload["sweeps"] = payload["sweeps"][-MAX_REPORTS:]
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True)
            file.write("\n")
        os.replace(temp_path, destination)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--bookmaker", required=True)
    parser.add_argument("--mode", default="prematch", choices=["prematch", "live"])
    parser.add_argument("--api-key", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--max-calls", type=int, default=100)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--out", default=str(DEFAULT_REPORT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    report = sweep(
        args.base_url,
        args.bookmaker,
        mode=args.mode,
        api_key=args.api_key,
        limit=args.limit,
        max_calls=args.max_calls,
        interval=args.interval,
    )
    append_report(args.out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.check and report["status"] not in {"converged", "skipped"}:
        print(f"FAIL: sweep ended {report['status']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
