"""
Premier Kladionica Scraper — premier-kladionica.com

Direct JSON-RPC via httpx (no browser). Host moved from svc-test to svc-web
on 2026-10-27 (svc-test now answers 503). Protocol reverse-engineered and
verified against the live feed (2026-08-15):

Full sync:
  POST https://svc-web.premier-kladionica.com/PrSync/PrSync.ashx
  Body: [[[4,1,0],7,{"dogadjajIDs":"","clientVer":0}]]
  Response: positional sections indexed by:
    ["execRes","tipIgre","sport","grupaDog","setDog","dog","grupaTip",
     "setTip","setTipVar","setTipTip","not used","dogVar","dogTipK",
     "pravila","dogLiveScore"]
  Empty sections are omitted.

Odds (delta sync): POST method 7 with {"dogadjajIDs":"<event ids>",
  "clientVer":<last ver>} returns dogTipK rows:
    [dogID, grupaTipID, setTipID, setTipVarID, setTipTipID, koef,
     naPon, dobitni, koef1]

Market decoding (football sport id = 2):
  setTip   (sport, setTipID)            -> market name (e.g. "UTAKMICA")
  setTipVar(sport, setTipID, varID)     -> line, e.g. "(-2,5+)" (index 9)
  setTipTip(sport, setTipID, varID, tipID) -> outcome code ("1","X","2",
             "1X","da","ne","m","v", ...)

Supported (name-based, verified):
  "UTAKMICA"             -> 1X2 (kods 1/X/2) + double chance (1X/X2/12)
  "OBA DAJU GOL"         -> BTTS (kods da/ne or o-da/o-ne); live: "OBA TIMA DAJU GOL"
  "ZBROJ GOLOVA"         -> O/U goals; line from setTipVar; half-goal lines
                            0.5 through 5.5 are mapped (all observed offers).
In-play markets are prefixed "LIVE - " (used for live mode). All other
markets (handicaps, halves, HT/FT, correct score, corners, cards, "NAČIN
PROLAZA", player markets, combos) are excluded.
"""

import json
import logging
from datetime import UTC, datetime

import httpx

from engine.market_registry import record_unmapped, registered_spec
from models.schemas import Market, MarketType, Match, OddsValue
from scrapers.errors import ScrapeError, ScrapeKind
from scrapers.retry import fetch_with_retry
from scrapers.transport import transport_client
from scrapers.wire_schemas import validate_premier_sync

logger = logging.getLogger(__name__)

BOOKMAKER_ID = "premier_kladionica"
BASE_URL = "https://www.premier-kladionica.com"
SYNC_URL = "https://svc-web.premier-kladionica.com/PrSync/PrSync.ashx"

API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}

FOOTBALL_SPORT_ID = 2
ODDS_CHUNK = 150

# Verified football market names (setTip name, normalised).
NAME_1X2 = "UTAKMICA"
NAME_BTTS = "OBA DAJU GOL"
# The in-play feed spells the same block differently ("LIVE - OBA TIMA DAJU GOL"
# once the prefix is stripped), so BTTS is matched per mode.
NAME_BTTS_LIVE = "OBA TIMA DAJU GOL"
NAME_OU = "ZBROJ GOLOVA"
NAME_FH_1X2 = "1. POLUVRIJEME"
# First-half total goals appear under a few name forms:
#   "1. POLUVRIJEME - ZBROJ GOLOVA" (+ optional "(±X,5+)" line suffix),
#   "ZBROJ GOLOVA 1. POLUVRIJEME", "ZBROJ GOLOVA 1.POLUVRIJEME".
FH_OU_NAME_PREFIXES = ("1. POLUVRIJEME - ZBROJ GOLOVA", "ZBROJ GOLOVA 1.")

OU_LINES = {
    "0.5": MarketType.OVER_UNDER_0_5,
    "1.5": MarketType.OVER_UNDER_1_5,
    "2.5": MarketType.OVER_UNDER_2_5,
    "3.5": MarketType.OVER_UNDER_3_5,
    "4.5": MarketType.OVER_UNDER_4_5,
    "5.5": MarketType.OVER_UNDER_5_5,
}

FH_OU_LINES = {"0.5", "1.5", "2.5"}


def _registered_spec(
    mode: str,
    source_id: str,
    market_type: MarketType,
    line: float | None = None,
):
    return registered_spec("premier_kladionica", mode, source_id, market_type, line=line)


def _norm_name(name: str) -> str:
    return " ".join(str(name).upper().strip().split())


def _is_fh_ou_name(base_name: str) -> bool:
    if "PAR/NEPAR" in base_name:
        return False
    if base_name.startswith(FH_OU_NAME_PREFIXES):
        return True
    return base_name == "ZBROJ GOLOVA 1.POLUVRIJEME"


def _parse_line_generic(line_str: str, allowed: set[str]) -> str | None:
    """Parse a line specifier like "(-2,5+)" / "(0,5)" / "(-0,5+)" into "2.5" / "0.5"."""
    if not line_str:
        return None
    s = line_str.strip().strip("()")
    s = s.replace("+", "")
    s = s.strip("-")
    s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    key = f"{value:.1f}"
    return key if key in allowed else None


def _parse_line(line_str: str) -> str | None:
    """Parse a PK line specifier like "(-2,5+)" or "(2,5)" into "2.5"."""
    if not line_str:
        return None
    s = line_str.strip().strip("()")
    s = s.replace("+", "")
    s = s.strip("-")
    s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    key = f"{value:.1f}"
    return key if key in OU_LINES else None


class PremierKladionicaScraper:
    """Scraper for premier-kladionica.com — PrSync JSON-RPC."""

    def __init__(self):
        self.headers = dict(API_HEADERS)

    async def fetch_and_parse(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        mode = "live" if live else "prematch"
        async with transport_client(BOOKMAKER_ID, mode) as client:
            sync = await self._full_sync(client)
            if not sync:
                return []
            sections = sync

            # sports: sportID -> naziv (section 2)
            sports = {}
            for row in sections[2] or []:
                if isinstance(row, list) and len(row) >= 3:
                    sports[row[0]] = row[2]

            # grupaDog: grupaDogID -> (sportID, naziv) (section 3)
            grupa_dog = {}
            for row in sections[3] or []:
                if isinstance(row, list) and len(row) >= 6:
                    grupa_dog[row[0]] = (row[2], row[5])

            # setTip: (sport, setTipID) -> name (section 7)
            set_tip = {}
            for row in sections[7] or []:
                if isinstance(row, list) and len(row) >= 3:
                    set_tip[(row[0], row[1])] = row[2]

            # setTipVar: (sport, setTipID, varID) -> line (section 8, index 9)
            set_tip_var = {}
            for row in sections[8] or []:
                if isinstance(row, list) and len(row) >= 10:
                    set_tip_var[(row[0], row[1], row[2])] = row[9]

            # setTipTip: (sport, setTipID, tipID) -> kod (section 9).
            # Column 2 of the def rows is the outcome tipID (the dogTipK rows
            # reference tipID 1..6 for "UTAKMICA"); column 3 is only an
            # ordering/specifier column and must NOT be part of the key.
            set_tip_tip = {}
            for row in sections[9] or []:
                if isinstance(row, list) and len(row) >= 5:
                    key = (row[0], row[1], row[2])
                    if key not in set_tip_tip:
                        set_tip_tip[key] = row[4]

            # dogs: football events (section 5)
            now_aware = (scan_time.replace(tzinfo=UTC) if scan_time and scan_time.tzinfo is None else scan_time) if scan_time else datetime.now(UTC)
            now_ms = int(now_aware.timestamp() * 1000)
            events = []
            for row in sections[5] or []:
                if not isinstance(row, list) or len(row) < 15:
                    continue
                dog_id, grupa_dog_id = row[0], row[1]
                info = grupa_dog.get(grupa_dog_id)
                if not info or info[0] != FOOTBALL_SPORT_ID:
                    continue
                home, away = str(row[7] or "").strip(), str(row[8] or "").strip()
                if not home or not away:
                    continue
                if not row[10]:  # naPon (on offer)
                    continue
                kickoff_ms = row[13] if isinstance(row[13], int | float) else None
                is_in_play = kickoff_ms is not None and kickoff_ms <= now_ms
                if live != is_in_play:
                    continue
                if live:
                    name_l = f"{home} {away}".lower()
                    if "srl" in name_l or "virtual" in name_l:
                        continue
                events.append({
                    "id": dog_id,
                    "home": home,
                    "away": away,
                    "league": info[1],
                    "kickoff_ms": kickoff_ms,
                    "status": row[9],  # blokirano
                })

            if not events:
                logger.info(f"[PremierKladionica] No {'live' if live else 'prematch'} football events in sync")
                return []

            # delta sync for odds — concurrent batches (P1-5)
            odds_by_event: dict[int, list[list]] = {}
            ver = sections[0][0][4] if sections and sections[0] else 0
            import asyncio as _asyncio
            chunk_ids_list = [",".join(str(e["id"]) for e in events[start:start + ODDS_CHUNK]) for start in range(0, len(events), ODDS_CHUNK)]
            async def _fetch_chunk(chunk_ids: str):
                return await self._delta_sync(client, chunk_ids, ver)
            deltas = await _asyncio.gather(*[_fetch_chunk(cid) for cid in chunk_ids_list])
            for delta in deltas:
                if delta is None:
                    continue
                for sec in delta:
                    if not isinstance(sec, list):
                        continue
                    for row in sec:
                        if isinstance(row, list) and len(row) >= 9 and isinstance(row[5], int | float):
                            odds_by_event.setdefault(row[0], []).append(row)

            matches: list[Match] = []
            for event in events:
                if event["status"]:
                    continue  # blocked
                rows = odds_by_event.get(event["id"])
                if not rows:
                    continue
                markets = self._build_markets(rows, set_tip, set_tip_var, set_tip_tip, live=live)
                if not markets:
                    continue
                kickoff = None
                if event["kickoff_ms"]:
                    kickoff = datetime.fromtimestamp(event["kickoff_ms"] / 1000, tz=UTC).replace(tzinfo=None)
                matches.append(Match(
                    bookmaker=BOOKMAKER_ID,
                    home_team=event["home"],
                    away_team=event["away"],
                    league=event["league"] or "Fudbal",
                    kickoff=kickoff,
                    markets=markets,
                    url=f"{BASE_URL}/ponuda/",
                    match_code=str(event["id"]),
                    event_id=str(event["id"]),
                    deep_link_verified=False,
                    is_live=live,
                    fetched_at=datetime.now(UTC).replace(tzinfo=None),
                ))

            logger.info(f"[PremierKladionica] {'Live' if live else 'Prematch'} total: {len(matches)} matches")
            return matches

    def _build_markets(self, rows: list[list], set_tip, set_tip_var, set_tip_tip, live: bool) -> list[Market]:
        """Group dogTipK rows into markets by (setTipID, varID) and classify."""
        # dedupe: keep the latest koef per (setTipID, varID, tipID)
        seen: dict[tuple[int, int, int], tuple[float, int]] = {}
        for row in rows:
            _dog, _gt, set_tip_id, var_id, tip_id, koef, na_pon, _dob, _k1 = row[:9]
            key = (set_tip_id, var_id, tip_id)
            if key not in seen or (na_pon == 1 and koef > seen[key][0]):
                seen[key] = (koef, na_pon)
        # group: setTipID -> varID -> [(tipID, koef, naPon)]
        grouped: dict[int, dict[int, list[tuple[int, float, int]]]] = {}
        for (set_tip_id, var_id, tip_id), (koef, na_pon) in seen.items():
            if na_pon != 1 or koef <= 1.01:
                continue
            grouped.setdefault(set_tip_id, {}).setdefault(var_id, []).append((tip_id, koef, na_pon))

        markets: list[Market] = []

        def add_market(
            market_type: MarketType, odds: list[OddsValue], source_id: str = ""
        ) -> None:
            if any(m.market_type == market_type for m in markets):
                return
            markets.append(
                Market(market_type=market_type, odds=odds, source_id=source_id)
            )

        for set_tip_id, vars_map in grouped.items():
            name = _norm_name(set_tip.get((FOOTBALL_SPORT_ID, set_tip_id), ""))
            is_live_market = name.startswith("LIVE -")
            if live != is_live_market:
                continue
            base_name = name[len("LIVE -"):].strip() if is_live_market else name

            for var_id, tips in vars_map.items():
                if base_name == NAME_1X2:
                    source_prefix = "LIVE_UTAKMICA" if live else "UTAKMICA_1X2"
                    mr_spec = _registered_spec(
                        "live" if live else "prematch", source_prefix, MarketType.MATCH_RESULT
                    )
                    dc_source = "LIVE_UTAKMICA_DC" if live else "UTAKMICA_DC"
                    dc_spec = _registered_spec(
                        "live" if live else "prematch", dc_source, MarketType.DOUBLE_CHANCE
                    )
                    by_kod = {str(set_tip_tip.get((FOOTBALL_SPORT_ID, set_tip_id, tip_id), "?")): koef
                              for tip_id, koef, _n in tips}
                    if mr_spec is not None:
                        match_result = [
                            OddsValue(label=label, value=by_kod[label])
                            for label in ("1", "X", "2")
                            if by_kod.get(label) and label in mr_spec.labels
                        ]
                        if (
                            len(match_result) >= mr_spec.min_legs
                            and {o.label for o in match_result}.issubset(mr_spec.labels)
                        ):
                            add_market(MarketType.MATCH_RESULT, match_result, str(set_tip_id))
                    if dc_spec is not None:
                        dc = [
                            OddsValue(label=label, value=by_kod[label])
                            for label in ("1X", "X2", "12")
                            if by_kod.get(label) and label in dc_spec.labels
                        ]
                        if len(dc) >= dc_spec.min_legs:
                            add_market(MarketType.DOUBLE_CHANCE, dc, str(set_tip_id))
                elif base_name == (NAME_BTTS_LIVE if live else NAME_BTTS):
                    source_id = "LIVE_OBA_DAJU_GOL" if live else "OBA_DAJU_GOL"
                    spec = _registered_spec(
                        "live" if live else "prematch", source_id, MarketType.BTTS
                    )
                    by_kod = {str(set_tip_tip.get((FOOTBALL_SPORT_ID, set_tip_id, tip_id), "?")): koef
                              for tip_id, koef, _n in tips}
                    gg = by_kod.get("da") or by_kod.get("o-da") or by_kod.get("GG")
                    ng = by_kod.get("ne") or by_kod.get("o-ne") or by_kod.get("NG")
                    btts_odds = [
                        OddsValue(label=label, value=value)
                        for label, value in (("GG", gg), ("NG", ng))
                        if value is not None
                    ]
                    actual = {odd.label for odd in btts_odds}
                    if (
                        spec is not None
                        and len(actual) >= spec.min_legs
                        and actual.issubset(spec.labels)
                    ):
                        add_market(MarketType.BTTS, btts_odds, str(set_tip_id))
                elif base_name == NAME_FH_1X2 and not live:
                    by_kod = {str(set_tip_tip.get((FOOTBALL_SPORT_ID, set_tip_id, tip_id), "?")): koef
                              for tip_id, koef, _n in tips}
                    fh_result = [OddsValue(label=k, value=v) for k, v in
                                 [("1", by_kod.get("1")), ("X", by_kod.get("X")), ("2", by_kod.get("2"))]
                                 if v]
                    if len(fh_result) == 3 and {o.label for o in fh_result} == {"1", "X", "2"}:
                        add_market(MarketType.FIRST_HALF_1X2, fh_result, str(set_tip_id))
                elif _is_fh_ou_name(base_name) and not live:
                    line = _parse_line_generic(
                        str(set_tip_var.get((FOOTBALL_SPORT_ID, set_tip_id, var_id), "")),
                        FH_OU_LINES,
                    )
                    if line is None:
                        continue
                    by_kod = {str(set_tip_tip.get((FOOTBALL_SPORT_ID, set_tip_id, tip_id), "?")): koef
                              for tip_id, koef, _n in tips}
                    over = by_kod.get("v") or by_kod.get("više") or by_kod.get("Vise") or by_kod.get("Over")
                    under = by_kod.get("m") or by_kod.get("manje") or by_kod.get("Under")
                    if over and under:
                        add_market(MarketType.FIRST_HALF_OU, [
                            OddsValue(label=f"Over {line}", value=over),
                            OddsValue(label=f"Under {line}", value=under),
                        ], str(set_tip_id))
                elif base_name == NAME_OU:
                    line = _parse_line(str(set_tip_var.get((FOOTBALL_SPORT_ID, set_tip_id, var_id), "")))
                    if line is None:
                        continue
                    market_type = OU_LINES[line]
                    spec = _registered_spec(
                        "live" if live else "prematch",
                        "LIVE_ZBROJ_GOLOVA" if live else "ZBROJ_GOLOVA",
                        market_type,
                        line=float(line),
                    )
                    by_kod = {str(set_tip_tip.get((FOOTBALL_SPORT_ID, set_tip_id, tip_id), "?")): koef
                              for tip_id, koef, _n in tips}
                    over = by_kod.get("v") or by_kod.get("više") or by_kod.get("Vise") or by_kod.get("Over")
                    under = by_kod.get("m") or by_kod.get("manje") or by_kod.get("Under")
                    ou_odds = [
                        OddsValue(label=label, value=value)
                        for label, value in (("Over", over), ("Under", under))
                        if value is not None
                    ]
                    actual = {
                        f"{odd.label} {line}" for odd in ou_odds
                    }
                    if (
                        spec is not None
                        and len(actual) >= spec.min_legs
                        and actual.issubset(spec.labels)
                    ):
                        add_market(
                            market_type,
                            [
                                OddsValue(label=f"{odd.label} {line}", value=odd.value)
                                for odd in ou_odds
                            ],
                            str(set_tip_id),
                        )
                else:
                    record_unmapped(
                        "premier_kladionica", set_tip_id, context=base_name
                    )
        return markets

    async def _full_sync(self, client: httpx.AsyncClient) -> list | None:
        return await self._sync_call(
            client, {"dogadjajIDs": "", "clientVer": 0}, kind="full"
        )

    async def _delta_sync(self, client: httpx.AsyncClient, dog_ids: str, client_ver) -> list | None:
        return await self._sync_call(
            client, {"dogadjajIDs": dog_ids, "clientVer": client_ver}, kind="delta"
        )

    async def _sync_call(
        self, client: httpx.AsyncClient, payload: dict, *, kind: str
    ) -> list | None:
        # The JSON-RPC body is a read-only odds query, so POST retries are safe.
        try:
            response = await fetch_with_retry(
                client,
                SYNC_URL,
                method="POST",
                content=json.dumps([[[4, 1, 0], 7, payload]]),
                headers=self.headers,
            )
        except ScrapeError:
            raise
        except Exception as e:
            logger.warning(f"[PremierKladionica] Sync request failed: {e}")
            return None
        try:
            data = response.json()
        except ValueError as exc:
            raise ScrapeError(
                ScrapeKind.SCHEMA_DRIFT,
                f"{BOOKMAKER_ID} sync response is not JSON: {exc}",
            ) from exc
        # SR4-3h: PrSync is positional, so the schema checks the envelope shape
        # and types the capture-backed tables before the parser reads them.
        return validate_premier_sync(data, kind=kind, book=BOOKMAKER_ID)

    async def scrape(self, live: bool = False, scan_time: datetime | None = None) -> list[Match]:
        return await self.fetch_and_parse(live=live, scan_time=scan_time)
