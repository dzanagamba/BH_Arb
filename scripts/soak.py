"""Repeated-scan soak harness.

Runs scans against a live server, records matches/groups/surebets, the server's
resident memory and the number of browser processes after each scan, and fails
when memory grows by more than 50% between the first and last sample or a browser
process is still alive after a scan. The 24-hour acceptance run uses this tool;
a short run is a smoke test, not a substitute for it.

    python scripts/soak.py --cycles 2 --interval 30 --pid <server-pid>
    python scripts/soak.py --minutes 1440 --interval 300 --pid <server-pid> --check
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class Sample:
    at: str
    matches: int
    groups: int
    surebets: int
    rss_mb: float | None
    browsers: int
    errors: int = 0


def _get_json(url: str, api_key: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url)
    if api_key:
        request.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _post(url: str, api_key: str = "") -> dict[str, Any]:
    request = urllib.request.Request(url, method="POST")
    if api_key:
        request.add_header("X-API-Key", api_key)
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _rss_mb(pid: int | None) -> float | None:
    if pid is None:
        return None
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def _browser_count() -> int:
    try:
        completed = subprocess.run(
            ["pgrep", "-c", "chrome|chromium"],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(completed.stdout.strip() or 0)
    except (OSError, ValueError):
        return 0


def summarize(samples: list[Sample], max_growth: float = 0.50) -> dict[str, Any]:
    if not samples:
        return {"samples": 0, "ok": False, "reason": "no samples"}
    first, last = samples[0], samples[-1]
    growth = None
    if first.rss_mb and last.rss_mb is not None:
        growth = round((last.rss_mb - first.rss_mb) / first.rss_mb, 4)
    problems: list[str] = []
    if growth is not None and growth > max_growth:
        problems.append(f"memory grew {growth:.0%} (limit {max_growth:.0%})")
    if last.browsers > 0:
        problems.append(f"{last.browsers} browser process(es) still alive after the scan")
    return {
        "samples": len(samples),
        "first": asdict(first),
        "last": asdict(last),
        # The whole curve, not just the endpoints: a long run is judged by
        # whether RSS plateaus or keeps climbing, and two numbers cannot show
        # that.
        "history": [asdict(sample) for sample in samples],
        "rss_series": [sample.rss_mb for sample in samples],
        "memory_growth": growth,
        "max_growth": max_growth,
        "ok": not problems,
        "problems": problems,
    }


def _wait_for_scan(base: str, mode: str, api_key: str, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status = _get_json(f"{base}/api/status?mode={mode}", api_key)
        except (TimeoutError, urllib.error.URLError):
            time.sleep(10)
            continue
        if not status.get("is_scanning"):
            return
        time.sleep(10)
    raise TimeoutError("scan did not finish before the timeout")


def run(
    base: str,
    *,
    mode: str,
    cycles: int,
    minutes: float,
    interval: float,
    api_key: str,
    pid: int | None,
) -> list[Sample]:
    samples: list[Sample] = []
    deadline = time.time() + minutes * 60 if minutes > 0 else None
    index = 0
    while index < cycles and (deadline is None or time.time() < deadline):
        index += 1
        _post(f"{base}/api/scan?mode={mode}", api_key)
        _wait_for_scan(base, mode, api_key)
        health = _get_json(f"{base}/api/health", api_key)
        results = _get_json(f"{base}/api/results?mode={mode}", api_key)
        mode_health = health.get(mode) or {}
        errors = len(mode_health.get("errors") or [])
        samples.append(
            Sample(
                at=datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
                matches=int(results.get("total_matches") or 0),
                groups=int(results.get("match_groups") or 0),
                surebets=int(results.get("surebets_count") or 0),
                rss_mb=_rss_mb(pid),
                browsers=_browser_count(),
                errors=errors,
            )
        )
        if deadline is None or time.time() + interval < deadline:
            time.sleep(interval)
    return samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mode", default="prematch", choices=["prematch", "live"])
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--minutes", type=float, default=0, help="wall-clock budget (0 = cycles only)")
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--pid", type=int, help="server PID for RSS sampling")
    parser.add_argument("--out", help="write the JSON report here")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    samples = run(
        args.base_url.rstrip("/"),
        mode=args.mode,
        cycles=args.cycles,
        minutes=args.minutes,
        interval=args.interval,
        api_key=args.api_key,
        pid=args.pid,
    )
    report = summarize(samples)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    if args.check and not report["ok"]:
        print("FAIL: " + "; ".join(report["problems"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
