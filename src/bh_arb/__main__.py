"""Command-line entry point for BH_Arb."""

from __future__ import annotations

from bh_arb import __version__


def main() -> int:
    print(f"BH_Arb {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
