"""Market registry: one source of truth for per-book market IDs."""

import asyncio

from engine.market_registry import MarketRegistry, unmapped_markets
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
    assert r.lookup("mdshop", "live", 6) is not None


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

    monkeypatch.setattr(common, "_NSOFT_REGISTRY", CustomRegistry())
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


def test_known_nsoft_ou_id_with_unsupported_line_is_not_unmapped():
    from scrapers.common import parse_nsoft_bets

    unmapped_markets.pop("mdshop:137", None)
    markets = parse_nsoft_bets([{
        "betTypeId": 137,
        "sBV": 4.5,
        "betOutcomes": [
            {"name": "Over", "odd": 1.9},
            {"name": "Under", "odd": 1.9},
        ],
    }])
    assert markets == []
    assert "mdshop:137" not in unmapped_markets


def test_unknown_id_is_recorded_not_silently_dropped():
    from engine.market_registry import record_unmapped

    record_unmapped("mdshop", 424242)
    assert "mdshop:424242" in unmapped_markets


def test_health_surfaces_unmapped_market_counter():
    from server.api import health

    result = asyncio.run(health())
    assert result["unmapped_markets"] == unmapped_markets


def test_registry_can_reject_a_bookmakers_core_market_id(monkeypatch):
    """A parser must not fall back to a hard-coded ID when the registry rejects it."""
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
    for module in (
        betole_module,
        evlbet_module,
        mbet_module,
        mozzart_module,
        premier_module,
        sportplus_module,
        wwin_module,
    ):
        monkeypatch.setattr(module, "MARKET_REGISTRY", rejecting, raising=False)

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
