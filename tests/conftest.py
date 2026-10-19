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


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_deeplinks: run against the shipped config/bookmaker_deeplinks.json"
    )


@pytest.fixture(autouse=True)
def _example_route_books(request, monkeypatch):
    common._deeplink_cache = None
    if request.node.get_closest_marker("real_deeplinks"):
        yield
        common._deeplink_cache = None
        return
    declared = dict(common._load_deeplink_config())
    declared.update(EXAMPLE_ROUTE_BOOKS)
    monkeypatch.setattr(common, "_deeplink_cache", declared)
    yield
    common._deeplink_cache = None
