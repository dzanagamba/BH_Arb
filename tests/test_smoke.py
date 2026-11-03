"""The scaffold is importable and the CLI entry point runs."""

from __future__ import annotations

import pytest

from bh_arb import __version__
from bh_arb.__main__ import main


def test_version_is_present() -> None:
    assert __version__


def test_cli_entry_point(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    assert "BH_Arb" in capsys.readouterr().out
