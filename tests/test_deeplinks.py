"""Deep-link builders and per-book event-id declarations."""
import json

from scrapers.common import build_event_url


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


def test_deeplink_config_is_valid_json():
    with open("config/bookmaker_deeplinks.json", encoding="utf-8") as f:
        data = json.load(f)
    assert "mdshop" in data
    assert data["mdshop"]["supports_event_id"] is True
