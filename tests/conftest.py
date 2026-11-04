"""Shared test setup.

Most gate tests need a book that *declares* a per-event route, so they can show
that an unproven link on such a book blocks `verified`. In the shipped config
only Mozzartbet declares one (MDShop and Admiralbet were set to
`supports_event_id: false` on 2026-10-20 after their `?event=` routes were found
inert). Rather than rewrite every fixture around one book, the tests keep MDShop
and Admiralbet as route-declaring example books through the same in-memory
declaration map the gate reads.

A module that checks the *real* shipped config opts out with
``pytestmark = pytest.mark.real_deeplinks``.
"""

import pytest

from scrapers import common

EXAMPLE_ROUTE_BOOKS = {
    "mdshop": {
        "supports_event_id": True,
        "template": "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event={event_id}",
        "template_live": "https://www.mdshop.ba/sport-live?event={event_id}",
    },
    "admiralbet": {
        "supports_event_id": True,
        "template": "https://www.admiralbet.ba/sport-prematch?sport=Fudbal&event={event_id}",
        "template_live": "https://www.admiralbet.ba/sport-live?event={event_id}",
    },
}


def _reset_deeplink_state() -> None:
    """Clear the declaration cache and the provenance of its last file read."""
    common._deeplink_cache = None
    common._deeplink_cache_signature = None
    common._deeplink_source_mtime = None
    common._deeplink_loaded_at = None
    common._deeplink_load_error = None


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_deeplinks: run against the shipped config/bookmaker_deeplinks.json"
    )


@pytest.fixture(autouse=True)
def _example_route_books(request, monkeypatch):
    _reset_deeplink_state()
    if request.node.get_closest_marker("real_deeplinks"):
        yield
        _reset_deeplink_state()
        return
    declared = dict(common._load_deeplink_config())
    declared.update(EXAMPLE_ROUTE_BOOKS)
    # Inject a synthetic map; with loaded_at left unset the file cannot replace
    # it, which is the seam these tests rely on.
    monkeypatch.setattr(common, "_deeplink_cache", declared)
    yield
    _reset_deeplink_state()
