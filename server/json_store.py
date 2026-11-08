"""Atomic JSON documents for the server's runtime state (M3-1 stage 3).

Every runtime JSON file has the same job: one document, written whole, read
whole. This module owns that job and nothing else. It carries no schema, makes
no policy decision and never merges or validates a payload — the caller owns the
document's shape, its locks and the meaning of a missing or malformed file.

``atomic_write_json`` writes through a temporary file in the destination
directory and replaces it, so a reader never sees a half-written document and a
crash leaves either the old file or the new one. ``read_json`` returns ``None``
for a missing, unreadable or malformed file, which is the "start from the
default" branch every caller already had.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any


def atomic_write_json(
    path: str, payload: object, prefix: str, indent: int | None = 2
) -> None:
    """Write JSON through a temp file so a reader never sees a partial document.

    ``indent=None`` writes compact JSON. Machine files (the scan caches and the
    evidence ledger) use that: indentation is a material share of their size and
    no reader depends on it. Configuration and human-inspectable decision files
    keep the default readable layout.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{prefix}.", suffix=".tmp", dir=directory, text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(
                payload,
                file,
                ensure_ascii=False,
                indent=indent,
                separators=(",", ":") if indent is None else None,
                default=str,
            )
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def read_json(path: str) -> Any | None:
    """Return a JSON document, or ``None`` when it is missing or unusable.

    The caller validates the shape. A malformed file is treated like a missing
    one because every store's recovery is the same: start from its default and
    rewrite on the next save. A parse error is never allowed to stop a scan.
    """
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, TypeError, ValueError):
        return None
