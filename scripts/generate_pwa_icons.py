#!/usr/bin/env python3
"""Generate the PWA icons (M5-5) with no image dependency.

The manifest used to declare an empty icon list, so the app was installable but
had no home-screen artwork. Draw the dashboard's chart-arrow mark on the brand
background and write 192 and 512 pixel PNGs.

    python scripts/generate_pwa_icons.py
    python scripts/generate_pwa_icons.py --check

`--check` compares the committed files with a fresh render without writing.
Pure stdlib: zlib for the PNG stream and a small 3x supersample for the edges.
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = REPO_ROOT / "frontend" / "icons"
BACKGROUND = (11, 18, 32)      # --background dark navy
ACCENT = (52, 211, 153)        # --accent mint
SIZES = (192, 512)
SUPERSAMPLE = 3
# The header SVG mark: a rising line and an arrow head in a 24-unit viewBox.
SEGMENTS = (
    ((4.0, 17.0), (9.0, 12.0)),
    ((9.0, 12.0), (13.0, 16.0)),
    ((13.0, 16.0), (20.0, 8.0)),
    ((15.0, 8.0), (20.0, 8.0)),
    ((20.0, 8.0), (20.0, 13.0)),
)


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    body = zlib.compress(b"".join(b"\x00" + row for row in rows), 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", body)
        + chunk(b"IEND", b"")
    )


def _distance(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _render(size: int) -> bytes:
    big = size * SUPERSAMPLE
    padding = big * 0.17
    inner = big - 2 * padding
    scale = inner / 24.0
    stroke = inner * 0.10 * 0.5

    def to_px(point: tuple[float, float]) -> tuple[float, float]:
        return (padding + point[0] * scale, padding + point[1] * scale)

    segments = [(to_px(a), to_px(b)) for a, b in SEGMENTS]
    rows: list[bytes] = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            total = [0, 0, 0]
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    px = x * SUPERSAMPLE + sx + 0.5
                    py = y * SUPERSAMPLE + sy + 0.5
                    on_mark = any(
                        _distance((px, py), a, b) <= stroke for a, b in segments
                    )
                    colour = ACCENT if on_mark else BACKGROUND
                    total[0] += colour[0]
                    total[1] += colour[1]
                    total[2] += colour[2]
            divisor = SUPERSAMPLE * SUPERSAMPLE
            row.extend(channel // divisor for channel in total)
        rows.append(bytes(row))
    return _png(size, size, rows)


def _expected() -> dict[Path, bytes]:
    return {ICONS_DIR / f"icon-{size}.png": _render(size) for size in SIZES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when a committed icon differs")
    args = parser.parse_args(argv)

    expected = _expected()
    if args.check:
        problems = [
            path.name
            for path, data in expected.items()
            if not path.is_file() or path.read_bytes() != data
        ]
        if problems:
            print("out of date: " + ", ".join(problems))
            print("run: python scripts/generate_pwa_icons.py")
            return 1
        print("PWA icons are in sync")
        return 0

    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    for path, data in expected.items():
        path.write_bytes(data)
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
