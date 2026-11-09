#!/usr/bin/env python3
"""Docker smoke test for P1-3.

Builds the image (unless ``--no-build``), starts a container with a named cache
volume, waits for ``/api/health``, checks the runtime uid is non-root, launches
the bundled Chromium headless, writes a marker into ``/app/cache``, restarts the
container and verifies the marker survived. Everything is cleaned up on the way
out.

Run on a Linux host with Docker access:

    python scripts/docker_smoke.py
    python scripts/docker_smoke.py --no-build --image bh-arb:local
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request

NAME = "bh-arb-smoke"
VOLUME = "bh-arb-smoke-cache"

# Chromium is installed in the image for the browser-backed books, so the smoke
# proves it actually launches as the non-root runtime user, with the same
# no-sandbox flags `launch_browser()` uses. A missing system library or a broken
# browser bundle fails here, not on the first live scan.
CHROMIUM_PROBE = """\
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    page = browser.new_page()
    page.set_content("<title>chromium-ok</title>")
    print(page.title())
    browser.close()
"""


def _run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    printable = " ".join(args)
    print(f"+ {printable}", flush=True)
    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture,
    )


def _ignore_failure(args: list[str]) -> None:
    subprocess.run(args, check=False, text=True, capture_output=True)


def _cleanup() -> None:
    _ignore_failure(["docker", "rm", "-f", NAME])
    _ignore_failure(["docker", "volume", "rm", VOLUME])


def _health(port: int) -> dict:
    url = f"http://127.0.0.1:{port}/api/health"
    # Local loopback probe only; the scheme is fixed above. See docs/CI.md.
    with urllib.request.urlopen(url, timeout=3) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _wait_for_health(port: int, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            body = _health(port)
            if body.get("status") == "ok":
                return body
            last_error = f"status was {body.get('status')!r}"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise SystemExit(f"/api/health did not pass within {timeout:.0f}s: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="bh-arb:smoke")
    parser.add_argument(
        "--no-build", action="store_true", help="use an existing image instead of building"
    )
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    _cleanup()
    try:
        if not args.no_build:
            _run(["docker", "build", "-t", args.image, "."])

        _run(["docker", "volume", "create", VOLUME])
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                NAME,
                "-p",
                f"127.0.0.1:{args.port}:8000",
                "-e",
                "HOST=0.0.0.0",
                "--mount",
                f"type=volume,src={VOLUME},dst=/app/cache",
                args.image,
            ]
        )

        body = _wait_for_health(args.port, args.timeout)
        print(f"health: {json.dumps(body, sort_keys=True)}", flush=True)

        uid = _run(
            ["docker", "exec", NAME, "id", "-u"], capture=True
        ).stdout.strip()
        if uid == "0":
            raise SystemExit("container is running as root")
        print(f"runtime uid: {uid} (non-root)", flush=True)

        chromium = _run(
            ["docker", "exec", NAME, "python", "-c", CHROMIUM_PROBE],
            capture=True,
        ).stdout.strip()
        if chromium != "chromium-ok":
            raise SystemExit(f"Chromium did not launch in the container: {chromium!r}")
        print("chromium: launched headless", flush=True)

        _run(
            [
                "docker",
                "exec",
                NAME,
                "python",
                "-c",
                "open('/app/cache/smoke-marker','w',encoding='utf-8').write('ok')",
            ]
        )
        _run(["docker", "restart", NAME])
        _wait_for_health(args.port, args.timeout)
        marker = _run(
            [
                "docker",
                "exec",
                NAME,
                "python",
                "-c",
                "print(open('/app/cache/smoke-marker',encoding='utf-8').read())",
            ],
            capture=True,
        ).stdout.strip()
        if marker != "ok":
            raise SystemExit(f"cache marker did not survive the restart: {marker!r}")

        print("PASS: health is up, the user is non-root, Chromium launched, cache survived restart")
        return 0
    finally:
        logs = subprocess.run(
            ["docker", "logs", "--tail", "40", NAME],
            check=False,
            text=True,
            capture_output=True,
        )
        if logs.returncode == 0 and logs.stdout.strip():
            print("--- container logs (tail) ---", flush=True)
            print(logs.stdout[-4000:], flush=True)
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
