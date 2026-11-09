"""Market registry: one source of truth for per-book market IDs."""

import asyncio

from engine.market_registry import MarketRegistry, _is_excluded, unmapped_markets
from models.schemas import MarketType


def test_registry_loads_and_looks_up_mdshop_1x2():
    r = MarketRegistry()
    spec = r.lookup("mdshop", "prematch", 135)
    assert spec is not None
    assert spec.market_type == MarketType.MATCH_RESULT
    assert spec.settlement == "full_time"


def test_registry_looks_up_admiralbet_bookmaker_specific_id():
    r = MarketRegistry()
    spec = r.lookup("admiralbet", "prematch", 1639)
    assert spec is not None
    assert spec.market_type == MarketType.MATCH_RESULT


def test_registry_distinguishes_prematch_from_live_ids():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 135) is not None
    assert r.lookup("mdshop", "live", 135) is None
    assert r.lookup("mdshop", "live", 22) is not None
    assert r.lookup("mdshop", "live", 6) is None  # rest-of-match: not read


def test_registry_rejects_unmapped_id():
    r = MarketRegistry()
    assert r.lookup("mdshop", "prematch", 99999) is None


def test_every_enabled_book_has_at_least_one_1x2_mode():
    from config.settings import BOOKMAKERS

    r = MarketRegistry()
    for bid in BOOKMAKERS:
        assert r.has_mode(bid, "prematch"), f"{bid} missing prematch registry mode"
        assert r.has_mode(bid, "live"), f"{bid} missing live registry mode"
    for bid, cfg in BOOKMAKERS.items():
        if not cfg.get("enabled"):
            continue
        assert any(
            r.ids_for(bid, mode, MarketType.MATCH_RESULT)
            for mode in ("prematch", "live")
        ), f"{bid} has no 1X2 registry entry"


def test_intentionally_unavailable_modes_are_empty():
    r = MarketRegistry()
    assert r.ids_for("evlbet", "live", MarketType.MATCH_RESULT) == set()
    assert r.ids_for("betole", "live", MarketType.MATCH_RESULT) == set()


def test_nsoft_parser_uses_registry_min_legs(monkeypatch):
    import engine.market_registry as registry_module
    from engine.market_registry import MarketSpec
    from scrapers import common

    class CustomRegistry:
        def has_mode(self, bookmaker, mode):
            return True

        def lookup(self, bookmaker, mode, source_id, line=None):
            return MarketSpec(
                bookmaker=bookmaker,
                mode=mode,
                market_type=MarketType.MATCH_RESULT,
                labels={"1", "2"},
                min_legs=2,
            )

        def has_source_id(self, bookmaker, mode, source_id):
            return True

    monkeypatch.setattr(registry_module, "MARKET_REGISTRY", CustomRegistry())
    bets = [{
        "betTypeId": 135,
        "betOutcomes": [
            {"name": "1", "odd": 2.0},
            {"name": "2", "odd": 2.0},
        ],
    }]
    markets = common.parse_nsoft_bets(bets)
    assert len(markets) == 1
    assert {o.label for o in markets[0].odds} == {"1", "2"}


def test_nsoft_accessor_uses_shared_module_registry(monkeypatch):
    import engine.market_registry as registry_module
    from scrapers import common

    sentinel = object()
    monkeypatch.setattr(registry_module, "MARKET_REGISTRY", sentinel)
    assert common._nsoft_registry() is sentinel


def test_known_nsoft_ou_id_with_unsupported_line_is_not_unmapped():
    from scrapers.common import parse_nsoft_bets

    unmapped_markets.pop("mdshop:137", None)
    markets = parse_nsoft_bets([{
        "betTypeId": 137,
        "sBV": 6.5,
        "betOutcomes": [
            {"name": "Over", "odd": 1.9},
            {"name": "Under", "odd": 1.9},
        ],
    }])
    assert markets == []
    assert "mdshop:137" not in unmapped_markets


def test_declared_exclusions_are_not_counted_as_unmapped():
    from engine.market_registry import record_unmapped

    unmapped_markets.pop("mdshop:136", None)
    unmapped_markets.pop("mdshop:987654", None)
    record_unmapped("mdshop", 136)
    record_unmapped("mdshop", 987654)
    assert "mdshop:136" not in unmapped_markets
    assert "mdshop:987654" in unmapped_markets


def test_supported_experimental_ids_are_not_declared_excluded():
    assert not _is_excluded("mbet", "ofb:ht")
    assert not _is_excluded("mbet", "ofb:hc")
    assert not _is_excluded("wwin", 2)
    assert not _is_excluded("sportplus", 4)
    assert not _is_excluded("sportplus", 25)
    assert not _is_excluded("betole", 4)
    assert not _is_excluded("betole", 5)
    assert not _is_excluded("betole", 6)


def test_name_exclusions_cover_advance_and_premier_templates():
    assert _is_excluded("mozzartbet", 999, context="Ko ide dalje")
    assert _is_excluded("premier_kladionica", 999, context="HENDIKEP")
    assert _is_excluded("sportplus", 999, context="NAČIN PROLAZA")
    assert not _is_excluded("premier_kladionica", 999, context="UTAKMICA")


def test_unknown_id_is_recorded_not_silently_dropped():
    from engine.market_registry import record_unmapped

    record_unmapped("mdshop", 424242)
    assert "mdshop:424242" in unmapped_markets


def test_an_id_known_for_another_market_type_is_not_unmapped():
    """Every book, evlbet included, treats a known wrong-type ID as mapped."""
    from scrapers.evlbet import _evlbet_registered_spec

    unmapped_markets.pop("evlbet:12005", None)
    assert _evlbet_registered_spec("prematch", "12005", MarketType.BTTS) is None
    assert "evlbet:12005" not in unmapped_markets

    assert _evlbet_registered_spec("prematch", "no-such-id", MarketType.BTTS) is None
    assert "evlbet:no-such-id" in unmapped_markets


def test_shared_resolver_keeps_working_for_registries_without_has_source_id(monkeypatch):
    import engine.market_registry as registry_module
    from engine.market_registry import registered_spec

    class LookupOnly:
        def lookup_type(self, bookmaker, mode, source_id, market_type, line=None):
            return None

    monkeypatch.setattr(registry_module, "MARKET_REGISTRY", LookupOnly())
    unmapped_markets.pop("mbet:424243", None)
    assert registered_spec("mbet", "prematch", "424243", MarketType.MATCH_RESULT) is None
    assert "mbet:424243" in unmapped_markets


def test_health_surfaces_unmapped_market_counter():
    from server.api import health

    result = asyncio.run(health())
    assert result["unmapped_markets"] == unmapped_markets


def test_registry_can_reject_a_bookmakers_core_market_id(monkeypatch):
    """A parser must not fall back to a hard-coded ID when the registry rejects it."""
    import engine.market_registry as registry_module
    import scrapers.betole as betole_module
    import scrapers.evlbet as evlbet_module
    import scrapers.mbet as mbet_module
    import scrapers.mozzartbet as mozzart_module
    import scrapers.premier_kladionica as premier_module
    import scrapers.sportplus as sportplus_module
    import scrapers.wwin as wwin_module

    class RejectingRegistry:
        def has_mode(self, bookmaker, mode):
            return True

        def lookup(self, bookmaker, mode, source_id, line=None):
            return None

        def lookup_type(self, bookmaker, mode, source_id, market_type, line=None):
            return None

        def ids_for(self, bookmaker, mode, market_type):
            return set()

    rejecting = RejectingRegistry()
    # Every scraper resolves through the shared helper in engine.market_registry.
    monkeypatch.setattr(registry_module, "MARKET_REGISTRY", rejecting)

    wwin_bets = [{"idBt": 95, "odds": [
        {"t": label, "va": 2.0, "isv": 1} for label in ("1", "X", "2")
    ]}]
    assert wwin_module._build_markets_from_bets(wwin_bets) == []

    mbet_odds = {f"ofb:fs:{label}": 2.0 for label in ("1", "X", "2")}
    assert mbet_module._resolve_mbet_market("fb", mbet_odds) == {}

    sportplus_markets = sportplus_module.SportPlusScraper()._parse_markets([
        {"id": 1, "name": "NOGOMET", "odds": [
            {"alias": label, "value": 2.0} for label in ("1", "X", "2")
        ]},
    ])
    assert sportplus_markets == []

    premier = premier_module.PremierKladionicaScraper()
    premier_markets = premier._build_markets(
        rows=[[0, 0, 1546, 1, tip, 2.0, 1, 0, 1] for tip in (1, 2, 3)],
        set_tip={(2, 1546): "UTAKMICA"},
        set_tip_var={},
        set_tip_tip={(2, 1546, 1): "1", (2, 1546, 2): "X", (2, 1546, 3): "2"},
        live=False,
    )
    assert premier_markets == []

    mozzart_markets = mozzart_module._parse_markets({"odds": [
        {"game": {"id": 1, "name": "Konačan ishod"},
         "subgame": {"name": label}, "value": 2.0}
        for label in ("1", "X", "2")
    ]})
    assert mozzart_markets == []

    evlbet_event = {
        "TeamHome": "A", "TeamAway": "B", "Id": 1,
        "BasicOffer": {"Odds": [
            {"Name": label, "Odd": 2.0} for label in ("1", "X", "2")
        ]},
    }
    assert evlbet_module.EvlbetScraper()._parse_event(evlbet_event) is None

    betole_markets = betole_module._parse_betole_markets(
        {"1": 2.0, "2": 2.0, "3": 2.0}
    )
    assert betole_markets == []


def test_wwin_live_request_includes_every_supported_live_market_id():
    from scrapers.wwin import _request_market_ids

    assert set(_request_market_ids("live")) == {95, 6, 3, 11}


def test_wwin_live_parser_keeps_dc_btts_and_ou():
    from scrapers.wwin import _build_markets_from_bets

    markets = _build_markets_from_bets([
        {"idBt": 6, "odds": [
            {"t": label, "va": 2.0, "isv": 1} for label in ("1X", "12", "X2")
        ]},
        {"idBt": 3, "odds": [
            {"t": "Yes", "va": 2.0, "isv": 1},
            {"t": "No", "va": 1.8, "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=2,5", "odds": [
            {"t": "Over", "va": 1.9, "isv": 1},
            {"t": "Under", "va": 1.9, "isv": 1},
        ]},
    ], mode="live")
    assert {market.market_type for market in markets} == {
        MarketType.DOUBLE_CHANCE,
        MarketType.BTTS,
        MarketType.OVER_UNDER_2_5,
    }


def test_premier_live_double_chance_resolves_and_is_not_unmapped():
    from scrapers.premier_kladionica import PremierKladionicaScraper

    unmapped_markets.pop("premier_kladionica:LIVE_UTAKMICA_DC", None)
    scraper = PremierKladionicaScraper()
    set_tip = {(2, 2338): "LIVE - UTAKMICA"}
    set_tip_tip = {
        (2, 2338, 1): "1",
        (2, 2338, 2): "X",
        (2, 2338, 3): "2",
        (2, 2338, 4): "1X",
        (2, 2338, 5): "X2",
        (2, 2338, 6): "12",
    }
    rows = [
        [1, 2, 2338, 1, tip_id, odd, 1, 0, 1]
        for tip_id, odd in (
            (1, 2.0), (2, 3.0), (3, 3.5), (4, 1.4), (5, 1.6), (6, 1.3)
        )
    ]
    markets = scraper._build_markets(rows, set_tip, {}, set_tip_tip, live=True)
    assert any(market.market_type == MarketType.DOUBLE_CHANCE for market in markets)
    assert "premier_kladionica:LIVE_UTAKMICA_DC" not in unmapped_markets


def test_betole_shared_parser_files_unknown_ids_under_betole():
    from scrapers.mozzartbet import _parse_markets

    unmapped_markets.pop("mozzartbet:999", None)
    unmapped_markets.pop("betole:999", None)
    event = {
        "odds": [{
            "game": {"id": 999, "name": "Nepoznat"},
            "subgame": {"name": "1"},
            "value": 2.0,
        }]
    }
    assert _parse_markets(event, bookmaker="betole", mode="prematch") == []
    assert "betole:999" in unmapped_markets
    assert "mozzartbet:999" not in unmapped_markets


def test_label_checks_reject_incomplete_registered_label_sets(monkeypatch):
    import engine.market_registry as registry_module
    import scrapers.wwin as wwin_module
    from engine.market_registry import MarketSpec

    class IncompleteLabelsRegistry:
        def lookup_type(self, bookmaker, mode, source_id, market_type, line=None):
            if market_type == MarketType.BTTS:
                return MarketSpec(
                    bookmaker=bookmaker,
                    mode=mode,
                    market_type=market_type,
                    labels={"GG"},
                    min_legs=2,
                )
            return MarketSpec(
                bookmaker=bookmaker,
                mode=mode,
                market_type=market_type,
                labels={f"Over {line}"},
                line=line,
                min_legs=2,
            )

    monkeypatch.setattr(registry_module, "MARKET_REGISTRY", IncompleteLabelsRegistry())
    markets = wwin_module._build_markets_from_bets([
        {"idBt": 3, "odds": [
            {"t": "Yes", "va": 2.0, "isv": 1},
            {"t": "No", "va": 1.8, "isv": 1},
        ]},
        {"idBt": 11, "spec": "total=2,5", "odds": [
            {"t": "Over", "va": 1.9, "isv": 1},
            {"t": "Under", "va": 1.9, "isv": 1},
        ]},
    ])
    assert markets == []


class _EmptyRegistry:
    """A fake the parsers must follow once the shared global is replaced.

    ``has_mode`` is True so the NSoft parser takes its registry path and asks
    this fake for a spec, instead of falling back to its legacy map — the
    fallback is for synthetic callers and would hide whether the seam reached it.
    """

    def has_mode(self, bookmaker, mode):
        return True

    def has_source_id(self, bookmaker, mode, source_id):
        return False

    def specs_for(self, bookmaker, mode, source_id):
        return []

    def lookup(self, bookmaker, mode, source_id, line=None):
        return None

    def lookup_type(self, bookmaker, mode, source_id, market_type, line=None):
        return None

    def ids_for(self, bookmaker, mode, market_type):
        return set()


def test_accessors_resolve_the_shared_object_at_call_time(monkeypatch):
    """M3-5: one replacement covers every accessor, not an import-time copy."""
    import engine.market_registry as registry_module

    fake = _EmptyRegistry()
    monkeypatch.setattr(registry_module, "MARKET_REGISTRY", fake)

    assert registry_module.registry() is fake
    assert registry_module.ids_for("mdshop", "prematch", MarketType.MATCH_RESULT) == set()
    assert registry_module.has_source_id("mdshop", "prematch", 135) is False
    assert registry_module.specs_for("mdshop", "prematch", 135) == []
    assert (
        registry_module.lookup_type(
            "mdshop", "prematch", 135, MarketType.MATCH_RESULT
        )
        is None
    )
    assert (
        registry_module.registered_spec(
            "mdshop", "prematch", 424244, MarketType.MATCH_RESULT
        )
        is None
    )


def test_replacing_the_registry_after_import_reaches_every_parser(monkeypatch):
    """The seam used to patch one module global while adapters held their own.

    Every parser now calls the accessor, so a fake installed after the adapter
    modules were imported is the registry they see. If any module captured the
    object at import time, this test would return the real markets instead.
    """
    import engine.market_registry as registry_module
    from engine.admissibility import ids_for as admissibility_ids_for
    from scrapers import common
    from scrapers.maxbet import _spec_for
    from scrapers.mbet import _resolve_mbet_market
    from scrapers.mozzartbet import _parse_markets as mozzart_parse
    from scrapers.wwin import _request_market_ids

    fake = _EmptyRegistry()
    monkeypatch.setattr(registry_module, "MARKET_REGISTRY", fake)

    assert admissibility_ids_for("mdshop", "prematch", MarketType.MATCH_RESULT) == set()
    assert _spec_for("prematch", 424244, None) is None
    assert _request_market_ids("live") == []
    assert _resolve_mbet_market(
        "fb", {"ofb:fs:1": 2.0, "ofb:fs:X": 3.0, "ofb:fs:2": 4.0}
    ) == {}
    assert common.parse_nsoft_bets([{
        "betTypeId": 135,
        "betOutcomes": [
            {"name": "1", "odd": 2.0},
            {"name": "X", "odd": 3.0},
            {"name": "2", "odd": 4.0},
        ],
    }], bookmaker="mdshop", mode="prematch") == []
    assert mozzart_parse(
        {
            "odds": [
                {
                    "game": {"id": 1, "shortName": "ki", "name": "Konacan ishod"},
                    "subgame": {"name": label},
                    "value": 2.0,
                }
                for label in ("1", "X", "2")
            ]
        },
        "prematch",
        "mozzartbet",
    ) == []
