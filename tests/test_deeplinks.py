"""Deep-link builders and per-book event-id declarations."""
import json

import pytest

from config.settings import BOOKMAKERS
from scrapers import common
from scrapers.common import build_event_url


def _read_config() -> dict:
    with open("config/bookmaker_deeplinks.json", encoding="utf-8") as f:
        return json.load(f)


def test_mdshop_builds_per_event_url():
    url = build_event_url("mdshop", "12345", "https://www.mdshop.ba")
    assert "event=12345" in url
    assert url.startswith("https://www.mdshop.ba/")


def test_wwin_declares_no_per_event_support():
    url = build_event_url("wwin", "12345", "https://wwin.ba")
    assert url == "https://wwin.ba/kladjenje/"


def test_unknown_book_returns_base_url():
    url = build_event_url("unknownbook", "1", "https://example.test")
    assert url == "https://example.test/"


def test_declared_true_book_is_distinguishable():
    assert common.has_declaration("mdshop")


def test_declared_false_book_is_still_declared():
    assert common.has_declaration("wwin")


def test_unknown_book_is_not_declared():
    assert not common.has_declaration("unknownbook")


def test_deeplink_config_covers_every_configured_bookmaker():
    assert set(BOOKMAKERS) == set(_read_config())


def test_false_declarations_have_no_event_link_notes():
    for bookmaker, spec in _read_config().items():
        if spec["supports_event_id"] is False:
            assert spec.get("note"), f"{bookmaker} needs a no-event-link note"


def test_true_declarations_have_event_placeholders():
    for bookmaker, spec in _read_config().items():
        if spec["supports_event_id"] is True:
            assert "{event_id}" in spec["template"], f"{bookmaker} template lacks event_id"
            if "template_live" in spec:
                assert "{event_id}" in spec["template_live"], (
                    f"{bookmaker} live template lacks event_id"
                )


def test_live_template_is_used_for_supported_book():
    url = build_event_url(
        "mdshop", "12345", "https://www.mdshop.ba", live=True
    )
    assert url == "https://www.mdshop.ba/sport-live?event=12345"


def test_mozzartbet_live_template_uses_public_event_route():
    url = build_event_url(
        "mozzartbet", "73601748", "https://www.mozzartbet.ba", live=True
    )
    assert url == "https://www.mozzartbet.ba/sr/uzivo/mec/1/73601748"


def test_empty_event_id_uses_non_event_url():
    assert build_event_url("mdshop", "", "https://www.mdshop.ba") == (
        "https://www.mdshop.ba/"
    )


def test_none_event_id_uses_non_event_url():
    assert build_event_url("mdshop", None, "https://www.mdshop.ba") == (
        "https://www.mdshop.ba/"
    )


def test_event_id_is_url_encoded():
    url = build_event_url("mdshop", "12&x=3", "https://www.mdshop.ba")
    assert url == "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=12%26x%3D3"


def test_true_template_without_placeholder_is_rejected(monkeypatch):
    monkeypatch.setattr(
        common,
        "_deeplink_cache",
        {
            "broken": {
                "supports_event_id": True,
                "template": "https://example.test/no-event",
            }
        },
    )
    with pytest.raises(ValueError, match="event_id"):
        build_event_url("broken", "42", "https://example.test")
