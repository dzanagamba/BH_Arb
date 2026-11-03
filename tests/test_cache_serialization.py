"""The atomic cache writer serialises stray datetimes without a round-trip."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from server.api import _atomic_write_json


def test_atomic_write_serializes_a_datetime(tmp_path: Path):
    path = tmp_path / "cache.json"
    _atomic_write_json(
        str(path),
        {"scan_time": datetime(2026, 11, 3, 5, 30), "matches": []},
        "cache",
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["scan_time"] == "2026-11-03 05:30:00"
    assert saved["matches"] == []
