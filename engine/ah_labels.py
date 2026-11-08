"""Asian-handicap label helpers.

A canonical AH label is ``"<side> <signed line>"``: ``"1 -0.5"`` for the home
favourite, ``"2 +0.5"`` for the away side. These are pricing vocabulary shared by
the parser, the matcher and the engine, not scraper I/O, so they live in
``engine`` and ``scrapers.common`` re-exports them for the adapters.

Splitting them out also removes the last ``engine`` -> ``scrapers`` import: the
matcher and the arbitrage engine only needed these conversions.
"""

from __future__ import annotations


def ah_line_fmt(value: float) -> str:
    """Format an Asian-handicap line magnitude compactly: 0.5 → '0.5', 1.0 → '1'."""
    if value == 0:
        return "0"
    s = f"{abs(value):g}"
    return s


def ah_label(idx: str, line: float) -> str:
    """Build a canonical Asian-handicap label: home favourite line → '1 -0.5', away → '2 +0.5'."""
    if line == 0:
        return f"{idx} 0"
    sign = "-" if line < 0 else "+"
    return f"{idx} {sign}{ah_line_fmt(line)}"


def parse_ah_label(label: str) -> tuple[str, float] | None:
    """Parse '1 -0.5' / '2 +0.5' / '1 0' into (team index, signed home-line)."""
    parts = str(label).split()
    if len(parts) != 2 or parts[0] not in ("1", "2"):
        return None
    try:
        line = float(parts[1])
    except ValueError:
        return None
    return parts[0], line


def flip_ah_label(label: str) -> str:
    """Flip an Asian-handicap label for a home/away swap: '1 -0.5' → '2 -0.5'."""
    parsed = parse_ah_label(label)
    if parsed is None:
        return label
    idx, line = parsed
    return ah_label("2" if idx == "1" else "1", line)
