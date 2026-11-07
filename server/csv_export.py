"""Safe CSV cells for operator exports.

Spreadsheet software treats a leading ``=``, ``+``, ``-`` or ``@`` as a formula.
Team, league, market and note text comes from bookmaker feeds, so exports must
neutralise a formula-looking string while leaving numbers (including negative
numbers) untouched.
"""

from __future__ import annotations

from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value
