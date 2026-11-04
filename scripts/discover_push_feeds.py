#!/usr/bin/env python3
"""Capture XHR/WebSocket transport evidence for one bookmaker page (P2-10).

The probe records only transport metadata: URL, frame counts, byte totals,
opcode mix, heartbeat-like gaps and JSON/API response sizes. It never stores
odds payloads, cookies or headers. A candidate is only allowed to justify a push
adapter when the capture shows a materially fresher stream than polling.

    python scripts/discover_push_feeds.py --bookmaker maxbet --seconds 20 \
      --out docs/evidence/2026-11-04-push-maxbet.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import BOOKMAKERS  # noqa: E402

PROBE_URLS = {
    "maxbet": "https://sportsbook.maxbet.ba/sport/1",
    "mozzartbet": "https://www.mozzartbet.ba/sr/kladjenje",
    "wwin": "https://wwin.ba/kladjenje/",
    "sportplus": "https://www.sportplus.ba/prematch/betting",
}


async def probe(url: str, seconds: float) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    sockets: dict[str, dict[str, Any]] = {}
    responses: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        started = time.monotonic()

        def on_socket(socket) -> None:
            row = sockets.setdefault(
                socket.url,
                {"url": socket.url, "frames": 0, "bytes": 0, "gaps": [], "opcodes": Counter()},
            )
            row["opcodes"]["open"] += 1
            last = [time.monotonic()]

            def on_frame(payload) -> None:
                now = time.monotonic()
                row["frames"] += 1
                row["bytes"] += len(payload) if isinstance(payload, bytes) else len(str(payload))
                row["opcodes"]["binary" if isinstance(payload, bytes) else "text"] += 1
                gap = now - last[0]
                if row["frames"] > 1:
                    row["gaps"].append(round(gap, 3))
                last[0] = now

            socket.on("framereceived", on_frame)

        def on_response(response) -> None:
            try:
                request = response.request
                if request.resource_type not in {"xhr", "fetch", "websocket"}:
                    return
                length = response.headers.get("content-length")
                responses.append(
                    {
                        "url": response.url,
                        "status": response.status,
                        "kind": request.resource_type,
                        "bytes": int(length) if length and length.isdigit() else None,
                    }
                )
            except Exception:
                return

        page.on("websocket", on_socket)
        page.on("response", on_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:  # a blocked page is still evidence
            await browser.close()
            return {
                "url": url,
                "ok": False,
                "error": type(exc).__name__,
                "duration_seconds": round(time.monotonic() - started, 1),
                "websockets": [],
                "xhr": [],
            }
        await page.wait_for_timeout(int(seconds * 1000))
        await browser.close()

    for row in sockets.values():
        gaps = row.pop("gaps")
        row["heartbeat_like_gaps"] = len([gap for gap in gaps if gap >= 1.0])
        row["max_gap_seconds"] = max(gaps) if gaps else None
        row["min_gap_seconds"] = min(gaps) if gaps else None
        row["opcodes"] = dict(row["opcodes"])
        row["host"] = urlsplit(row["url"]).hostname
    return {
        "url": url,
        "ok": True,
        "duration_seconds": round(time.monotonic() - started, 1),
        "websockets": sorted(sockets.values(), key=lambda row: row["url"]),
        "xhr": responses[-100:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bookmaker", required=True, choices=sorted(PROBE_URLS))
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    url = PROBE_URLS[args.bookmaker] or str(BOOKMAKERS[args.bookmaker]["soccer_url"])
    report = asyncio.run(probe(url, args.seconds))
    report["bookmaker"] = args.bookmaker
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
