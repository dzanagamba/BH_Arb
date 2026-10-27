"""Capture live bookmaker payloads and write trimmed market-registry fixtures.

WHY THIS SCRIPT EXISTS
----------------------
``config/bookmaker_markets.json`` declares one source ID per bookmaker/mode/market.
Two lower test layers already prove the registry is internally consistent and that
each parser dispatches the IDs it is given, but both read the SAME file, so a
wrong-but-consistent ID (registry says ``135`` where the feed really sends
``136``) keeps every one of them green.  Only a payload captured from the live
API can catch that.

This script is the provenance record for ``tests/fixtures/markets/*.json``:
every fixture it writes was read out of a real HTTP response from the book,
hand-trimmed to the smallest payload that still exercises the registry rows for
that book/mode.  Re-run it to refresh the fixtures:

    python scripts/capture_market_fixtures.py                # every book
    python scripts/capture_market_fixtures.py --books mdshop,wwin

A book that cannot be reached, or that serves no in-play football at capture
time, is reported as SKIPPED and gets NO fixture.  A missing fixture is honest;
a hand-written one built from the parser's own constants would be worthless,
because it would be wrong in the same direction as the code it is meant to check.

``expected_markets`` is written by each book's capturer from the registry rows
that the trimmed payload actually carries -- never from parser output, which
would make the assertion a tautology.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(REPO, "tests", "fixtures", "markets")
CAPTURE_DATE = datetime.now(UTC).strftime("%Y-%m-%d")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
NSOFT_DT_FMT = "%Y-%m-%dT%H:%M:%S.000"

CORE_MARKETS = ("1x2", "double_chance", "btts", "over_under_1_5", "over_under_2_5", "over_under_3_5")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _active(odds: Any) -> bool:
    """True when a captured odd is offered and above the 1.01 floor."""
    try:
        return float(odds) >= 1.01
    except (TypeError, ValueError):
        return False


def _registry_rows(bookmaker: str, mode: str) -> list[str]:
    """Core market types the registry declares for this bookmaker/mode."""
    from engine.market_registry import MARKET_REGISTRY
    from models.schemas import MarketType

    return [
        market_type.value
        for market_type in MarketType
        if market_type.value in CORE_MARKETS
        and MARKET_REGISTRY.ids_for(bookmaker, mode, market_type)
    ]


def _finish(fixture: dict[str, Any], exercised: list[str]) -> dict[str, Any]:
    """Attach expected_markets plus the declared rows the payload cannot reach."""
    declared = _registry_rows(fixture["bookmaker"], fixture["mode"])
    unknown = sorted(set(exercised) - set(declared))
    if unknown:
        raise SystemExit(f"exercised market(s) absent from the registry: {unknown}")
    fixture["expected_markets"] = sorted(exercised)
    fixture["uncovered_registry_rows"] = sorted(set(declared) - set(exercised))
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    path = os.path.join(FIXTURE_DIR, f"{fixture['bookmaker']}_{fixture['mode']}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(fixture, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"  wrote {os.path.relpath(path, REPO)} -> {fixture['expected_markets']}")
    if fixture["uncovered_registry_rows"]:
        print(f"  NOTE declared rows the feed could not supply: {fixture['uncovered_registry_rows']}")
    return fixture


def _skip(bookmaker: str, mode: str, reason: str) -> None:
    print(f"  SKIPPED {bookmaker}/{mode}: {reason}")


def _pw_ok(response: Any) -> Any:
    """Playwright's APIResponse has no raise_for_status(); check it explicitly."""
    if response.status != 200:
        raise RuntimeError(f"HTTP {response.status} from {response.url}")
    return response


# --------------------------------------------------------------------------
# NSoft — MDShop / Admiralbet
# --------------------------------------------------------------------------

NSOFT_BET_FIELDS = ("betTypeId", "sBV", "betTypeName")
NSOFT_OUTCOME_FIELDS = ("name", "odd", "orderNo")
NSOFT_DROPPED_BET = [
    "id", "eventId", "competitionId", "regionId", "sportId", "betTypeValueType",
    "isPlayable", "isInOffer", "isMostBalanced", "cashBackEnabled", "profitMargin",
    "externalId", "externalSpecifiers", "contextNote", "marketConstraint",
]
NSOFT_DROPPED_OUTCOME = [
    "id", "betId", "eventId", "competitionId", "regionId", "sportId", "betTypeId",
    "betTypeOutcomeId", "sBV", "isPlayable", "isInOffer", "cashBackEnabled",
    "useParticipiantName", "resultStatus", "isEarlyPayoutPossible", "externalId",
]

# (market type, betTypeId) the registry maps for each NSoft mode, read from the
# registry itself so the capture cannot drift from it.
NSOFT_PREMATCH_IDS = {
    "MATCH_RESULT": None,     # book-specific: 135 (mdshop) / 1639 (admiralbet)
    "DOUBLE_CHANCE": 152,
    "BTTS": 151,
}
# NSoft live reads the match total only (id 22). Its 1X2 / double chance / BTTS
# (6, 18, 42, 995) disagreed with every other book on 2026-10-20 and are kept in
# the fixture as excluded controls, never as expected markets.
NSOFT_LIVE_IDS: dict[str, Any] = {}
NSOFT_PREMATCH_EXCLUDED = [136, 148, 140, 166]
NSOFT_LIVE_EXCLUDED = [6, 42, 995, 24, 261, 56, 41]
# NSoft spells the totals legs in the site's language; both books use the
# "Manje"/"Više" pair, MDShop also serves the ASCII "Vise" spelling.
NSOFT_OU_LEGS = {"manje": "under", "vise": "over", "više": "over", "over": "over", "under": "under"}


def _trim_nsoft_bet(bet: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: bet.get(k) for k in NSOFT_BET_FIELDS},
        "betOutcomes": [
            {k: outcome.get(k) for k in NSOFT_OUTCOME_FIELDS}
            for outcome in bet.get("betOutcomes", []) or []
        ],
    }


def _nsoft_spec(bookmaker: str, mode: str, bet_id: int, market_type_name: str):
    from engine.market_registry import MARKET_REGISTRY
    from models.schemas import MarketType

    return MARKET_REGISTRY.lookup_type(
        bookmaker, mode, bet_id, MarketType[market_type_name]
    )


def _nsoft_bet_ok(bet: dict[str, Any], spec) -> bool:
    """True when the bet carries at least the registry's min_legs usable labels."""
    outcomes = [o for o in bet.get("betOutcomes", []) or [] if _active(o.get("odd"))]
    labels = {str(o.get("name")) for o in outcomes} & set(spec.labels)
    return len(labels) >= spec.min_legs


def _nsoft_ou_ok(bet: dict[str, Any]) -> bool:
    legs = {
        NSOFT_OU_LEGS[str(o.get("name")).strip().casefold()]
        for o in bet.get("betOutcomes", []) or []
        if _active(o.get("odd")) and str(o.get("name")).strip().casefold() in NSOFT_OU_LEGS
    }
    return legs == {"over", "under"}


async def capture_nsoft(client: httpx.AsyncClient, bookmaker: str, mode: str) -> None:
    if bookmaker == "mdshop":
        base, office, referer, lang = (
            "https://mdoffer.mdshop.ba/api/offer/getwebevents", "1678",
            "https://www.mdshop.ba/", "sr-Latn",
        )
        result_id: int = 135
    else:
        base, office, referer, lang = (
            "https://bihoffer.admiralbet.ba/api/offer/getwebevents", "2037",
            "https://www.admiralbet.ba/sport-prematch?sport=Fudbal", "bs-Latn",
        )
        result_id = 1639

    now = datetime.now(UTC)
    ids: dict[str, Any]
    if mode == "prematch":
        date_from, date_to = now, now + timedelta(days=14)
        ids = dict(NSOFT_PREMATCH_IDS)
        ids["MATCH_RESULT"] = result_id
        ou_ids: tuple[int, ...]
        ou_ids, ou_lines, excluded = (137, 138), ("1.5", "2.5", "3.5"), NSOFT_PREMATCH_EXCLUDED
    else:
        # The live feed only returns events whose kickoff falls inside the
        # window, so the window has to START BEFORE now or already-started
        # in-play games are filtered out of the response entirely.
        date_from, date_to = now - timedelta(hours=12), now
        ids = dict(NSOFT_LIVE_IDS)
        # 28 is "Domaćin ukupno" (the HOME team's goals): never the match total.
        ou_ids, ou_lines, excluded = (22,), ("1.5", "2.5", "3.5"), NSOFT_LIVE_EXCLUDED

    url = (
        f"{base}?sportId=1&isLive={'true' if mode == 'live' else 'false'}"
        f"&dateFrom={date_from.strftime(NSOFT_DT_FMT)}&dateTo={date_to.strftime(NSOFT_DT_FMT)}"
        "&eventMappingTypes=1,2,3,4,5"
    )
    response = await client.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/utf8+json, application/json;q=0.9, text/plain;q=0.8, */*;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "language": lang,
            "officeid": office,
            "referer": referer,
        },
    )
    response.raise_for_status()
    events = response.json().get("events", [])
    if not events:
        _skip(bookmaker, mode, f"the feed served 0 events for this window ({url})")
        return

    for event in events:
        bets = event.get("bets", []) or []
        by_id = {b.get("betTypeId"): b for b in bets}
        wanted: list[tuple[int, Any]] = []
        for market_type_name, candidates in ids.items():
            if isinstance(candidates, tuple):
                # Either live double-chance ID satisfies the row; the feed serves
                # 42 (all three legs) far more often than the 1.p variant 18.
                present = [c for c in candidates if c in by_id]
                candidates = next(
                    (c for c in reversed(present)
                     if _nsoft_bet_ok(by_id[c], _nsoft_spec(bookmaker, mode, c, market_type_name))),
                    None,
                )
            else:
                candidates = candidates if candidates in by_id else None
            if candidates is None:
                wanted = []
                break
            spec = _nsoft_spec(bookmaker, mode, candidates, market_type_name)
            if spec is None or not _nsoft_bet_ok(by_id[candidates], spec):
                wanted = []
                break
            wanted.append((candidates, spec))
        if not wanted and mode != "live":
            continue
        ou_pairs = {
            str(b.get("sBV")): b
            for b in bets
            if b.get("betTypeId") in ou_ids
            and str(b.get("sBV")) in ou_lines
            and _nsoft_ou_ok(b)
        }
        if set(ou_pairs) != set(ou_lines):
            continue
        kept = [_trim_nsoft_bet(by_id[bet_id]) for bet_id, _spec in wanted]
        kept += [_trim_nsoft_bet(ou_pairs[line]) for line in ou_lines]
        for excluded_id in excluded:
            match = next((b for b in bets if b.get("betTypeId") == excluded_id), None)
            if match is not None:
                kept.append(_trim_nsoft_bet(match))
                if mode != "live":
                    break
        exercised = ["over_under_1_5", "over_under_2_5", "over_under_3_5"]
        if mode == "prematch":
            exercised = ["1x2", "double_chance", "btts"] + exercised
        _finish(
            {
                "bookmaker": bookmaker,
                "mode": mode,
                "captured_at": CAPTURE_DATE,
                "endpoint": url,
                "source": "live_api_response",
                "payload_kind": "nsoft_event_bets",
                "provenance": (
                    f"bets[] of one football event (id {event.get('id')!r}) from the live NSoft"
                    f" getwebevents response for {bookmaker} in {mode} mode, hand-trimmed to the"
                    " registry's betTypeIds, the three declared O/U lines, and one excluded"
                    " betTypeId that must not produce a market."
                ),
                "dropped_bet_fields": NSOFT_DROPPED_BET,
                "dropped_outcome_fields": NSOFT_DROPPED_OUTCOME,
                "excluded_ids_present": [
                    {"id": b["betTypeId"], "context": b.get("betTypeName")}
                    for b in kept if b["betTypeId"] in excluded
                ],
                "bets": kept,
            },
            exercised,
        )
        return
    _skip(bookmaker, mode, "no football event carried every registered market's odds together")


# --------------------------------------------------------------------------
# WWIN
# --------------------------------------------------------------------------

WWIN_API = "https://wwin.ba/content/sport-livecontent/api"
WWIN_BET_FIELDS = ("idBt", "spec")
WWIN_ODD_FIELDS = ("t", "va", "isv")
WWIN_WANT = {95: ["1", "X", "2"], 6: ["1X", "12", "X2"], 3: ["Yes", "No"]}
WWIN_OU = {11: ["Over", "Under"]}


def _trim_wwin_bet(bet: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: bet.get(k) for k in WWIN_BET_FIELDS},
        "odds": [{k: o.get(k) for k in WWIN_ODD_FIELDS} for o in bet.get("odds", []) or []],
    }


def _wwin_bet_ok(bet: dict[str, Any], labels: list[str]) -> bool:
    by_label = {str(o.get("t")): o for o in bet.get("odds", []) or []}
    return all(
        lbl in by_label
        and _active(by_label[lbl].get("va"))
        and by_label[lbl].get("isv", 1) != 0
        for lbl in labels
    )


async def capture_wwin(_client: httpx.AsyncClient, _bookmaker: str, mode: str) -> None:
    from scrapers.base import launch_browser

    playwright, browser, context = await launch_browser()
    try:
        # WWIN's events endpoint takes at most two bet ids per call, so the
        # prematch capture issues the same two requests the scraper does.
        if mode == "prematch":
            page = await context.new_page()
            await page.goto("https://wwin.ba/kladjenje/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(6000)
            now = datetime.now(UTC)
            day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
            window = {"key": "bs", "spid": "2"}
            urls: list[str] = []
            for offset in range(3):
                day = day0 + timedelta(days=offset)
                params = {
                    **window,
                    "tfrom": int((day - timedelta(hours=1)).timestamp()),
                    "tto": int((day + timedelta(days=1, hours=2)).timestamp()),
                }
                for group in ("95,6", "3,11", "4,7"):
                    urls.append(
                        f"{WWIN_API}/PrematchEvents/events?bets={group}&"
                        + "&".join(f"{k}={v}" for k, v in params.items())
                    )
            headers = {"Accept": "application/json, text/plain, */*", "Referer": "https://wwin.ba/kladjenje/"}
            by_id: dict[str, dict[str, Any]] = {}
            for url in urls:
                response = _pw_ok(await page.request.get(url, headers=headers))
                body = await response.json()
                for event in body.get("p") or body.get("events") or []:
                    slot = by_id.setdefault(str(event["id"]), {"id": event["id"], "bets": []})
                    slot["bets"].extend(event.get("bets", []) or [])
            endpoint = " + ".join(urls)
            pool = list(by_id.values())
        else:
            page = await context.new_page()
            await page.goto("https://wwin.ba/kladjenje-uzivo/", wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(6000)
            headers = {"Accept": "application/json, text/plain, */*", "Referer": "https://wwin.ba/kladjenje-uzivo/"}
            response = _pw_ok(await page.request.get(
                f"{WWIN_API}/LiveEvents/events",
                params={"key": "bs", "bets": "", "bet": "", "pbet": ""},
                headers=headers,
            ))
            events = (await response.json()).get("events", [])
            ids = [
                str(e.get("idEvent")) for e in events
                if isinstance(e, dict) and e.get("ids") == 2 and e.get("idEvent")
            ][:30]
            if not ids:
                _skip("wwin", mode, "the live feed listed no in-play football events")
                return
            endpoint = f"{WWIN_API}/LiveEvents/headerBets?bets=95,6,3,11,4,7&ids={len(ids)} football event ids"
            response = _pw_ok(await page.request.get(
                f"{WWIN_API}/LiveEvents/headerBets",
                params={"bets": "95,6,3,11,4,7", "ids": ",".join(ids)},
                headers=headers,
            ))
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in (await response.json()).get("bets", []):
                for event_id, bet in item.items():
                    grouped.setdefault(str(event_id), []).append(bet)
            pool = [{"id": eid, "bets": bets} for eid, bets in grouped.items()]

        # prematch spells the O/U line "total=2,5", live spells it "total=2.5"
        separator = "," if mode == "prematch" else "."
        wanted_specs = [f"total={line.replace('.', separator)}" for line in ("1.5", "2.5", "3.5")]
        for event in pool:
            bets = event.get("bets", []) or []
            kept: list[dict[str, Any]] = []
            ok = True
            for bet_id, labels in WWIN_WANT.items():
                match = next(
                    (b for b in bets if b.get("idBt") == bet_id and _wwin_bet_ok(b, labels)), None
                )
                if match is None:
                    ok = False
                    break
                kept.append(_trim_wwin_bet(match))
            if not ok:
                continue
            for spec in wanted_specs:
                match = next(
                    (b for b in bets
                     if b.get("idBt") == 11 and str(b.get("spec")) == spec
                     and _wwin_bet_ok(b, WWIN_OU[11])),
                    None,
                )
                if match is None:
                    ok = False
                    break
                kept.append(_trim_wwin_bet(match))
            if not ok:
                continue
            # idBt 4 (HT/FT) and 7 (handicap) are served and explicitly excluded.
            for excluded_id in (7, 4):
                match = next((b for b in bets if b.get("idBt") == excluded_id), None)
                if match is not None:
                    kept.append(_trim_wwin_bet(match))
                    break
            if not any(b["idBt"] in (4, 7) for b in kept):
                raise SystemExit(
                    f"wwin/{mode}: no excluded idBt (4 or 7) reached the payload; the "
                    "fixture would claim a control it does not contain"
                )
            _finish(
                {
                    "bookmaker": "wwin",
                    "mode": mode,
                    "captured_at": CAPTURE_DATE,
                    "endpoint": endpoint,
                    "source": "live_api_response",
                    "payload_kind": "wwin_bets",
                    "provenance": (
                        f"bets[] of one football event (id {event['id']!r}) from the live WWIN"
                        f" {'PrematchEvents/events' if mode == 'prematch' else 'LiveEvents/headerBets'}"
                        " response, hand-trimmed to idBt 95/6/3 plus idBt 11 for the three"
                        " declared totals, and one excluded idBt."
                    ),
                    "dropped_bet_fields": ["id", "idmSt", "fav", "sty", "mxb", "mxbv", "mne"],
                    "dropped_odd_fields": ["id", "mg", "idtm", "idfree", "idtft"],
                    "excluded_ids_present": [
                        {"id": b["idBt"], "context": None} for b in kept if b["idBt"] in (4, 7)
                    ],
                    "bets": kept,
                },
                list(CORE_MARKETS),
            )
            return
        _skip("wwin", mode, "no event carried 95 + 6 + 3 + 11(1.5/2.5/3.5) together")
    finally:
        await browser.close()
        await playwright.stop()


# --------------------------------------------------------------------------
# Premier Kladionica
# --------------------------------------------------------------------------

PREMIER_SYNC = "https://svc-web.premier-kladionica.com/PrSync/PrSync.ashx"
# Premier names the plain both-teams-to-score market differently per mode. The
# prematch spelling is what scrapers/premier_kladionica.py matches (NAME_BTTS);
# the live spelling is NOT, which is the defect the fixture keeps as evidence.
PREMIER_BTTS_NAMES = {"prematch": "OBA DAJU GOL", "live": "OBA TIMA DAJU GOL"}
PREMIER_HEADERS = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"}


async def _premier_call(client: httpx.AsyncClient, payload: dict[str, Any]) -> list | None:
    response = await client.post(
        PREMIER_SYNC,
        content=json.dumps([[[4, 1, 0], 7, payload]]),
        headers=PREMIER_HEADERS,
    )
    response.raise_for_status()
    data = response.json()
    return data[0] if isinstance(data, list) and data and isinstance(data[0], list) else None


async def capture_premier(client: httpx.AsyncClient, _bookmaker: str, mode: str) -> None:
    sections = await _premier_call(client, {"dogadjajIDs": "", "clientVer": 0})
    if not sections:
        _skip("premier_kladionica", mode, "the full sync returned nothing")
        return
    grupa_dog = {
        row[0]: (row[2], row[5]) for row in sections[3] or []
        if isinstance(row, list) and len(row) >= 6
    }
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    ver = sections[0][0][4] if sections and sections[0] else 0

    ids: list[int] = []
    for row in sections[5] or []:
        if not isinstance(row, list) or len(row) < 15:
            continue
        info = grupa_dog.get(row[1])
        if not info or info[0] != 2 or not row[7] or not row[8] or not row[10]:
            continue
        kickoff = row[13] if isinstance(row[13], int | float) else None
        in_play = kickoff is not None and kickoff <= now_ms
        if in_play == (mode == "live"):
            ids.append(row[0])
    if not ids:
        _skip("premier_kladionica", mode, "the full sync listed no football events in this mode")
        return

    rows_by_event: dict[int, list] = {}
    for start in range(0, len(ids), 80):
        chunk = ",".join(str(i) for i in ids[start:start + 80])
        delta = await _premier_call(client, {"dogadjajIDs": chunk, "clientVer": ver})
        for section in delta or []:
            if not isinstance(section, list):
                continue
            for row in section:
                if isinstance(row, list) and len(row) >= 9 and isinstance(row[5], int | float):
                    rows_by_event.setdefault(row[0], []).append(row)

    set_tip = [r for r in sections[7] or [] if isinstance(r, list) and len(r) >= 3 and r[0] == 2]
    name_of = {(r[0], r[1]): r[2] for r in set_tip}

    def base_name(tip: int) -> str:
        raw = str(name_of.get((2, tip), ""))
        return raw[len("LIVE -"):].strip() if raw.startswith("LIVE -") else raw

    def is_live_tip(tip: int) -> bool:
        return str(name_of.get((2, tip), "")).startswith("LIVE - ")

    def _is_fulltime_btts(base: str) -> bool:
        """True for the plain both-teams-to-score block, in either mode's spelling.

        Matched by exact name, not by substring, because a Premier event also
        carries half-time and combined variants that contain "DAJU GOL" -- "1.
        POLUVRIJEME - OBA DAJU GOL", "UTAKMICA I OBA DAJU GOL", "DVOZNAK I OBA
        DAJU GOL" -- and those are NOT kept. A substring match would sweep them
        in; the comment at the call site records what that costs.

        The plain block is the one that matters precisely because its two
        spellings differ by mode: "OBA DAJU GOL" prematch, "OBA TIMA DAJU GOL"
        live, with the parser matching only the former. That is the defect
        tests/test_market_fixtures.py guards with a strict xfail.
        """
        return base.upper() in (PREMIER_BTTS_NAMES["prematch"], PREMIER_BTTS_NAMES["live"])

    for event_id, rows in rows_by_event.items():
        by_name: dict[str, set[int]] = {}
        for tip in {row[2] for row in rows}:
            by_name.setdefault(base_name(tip), set()).add(tip)
        # UTAKMICA carries 1X2 + double chance; the "both teams to score" block
        # carries BTTS; ZBROJ GOLOVA carries the three declared totals (prematch
        # only -- the parser resolves that branch against the prematch registry).
        required = {"UTAKMICA"} | ({"ZBROJ GOLOVA"} if mode == "prematch" else set())
        if not required <= set(by_name):
            continue
        keep_tips = set().union(*(by_name[name] for name in required))
        # Keep the plain full-time BTTS block, EVEN IN LIVE MODE where the feed
        # spells it "OBA TIMA DAJU GOL" rather than the parser's NAME_BTTS of
        # "OBA DAJU GOL". That mismatch is a real defect and this block is its
        # only evidence: without it in the fixture the defect would live in prose
        # alone, and a future parser fix would have nothing to turn green.
        # tests/test_market_fixtures.py xfails on it with strict=True.
        #
        # The half-time and combined variants ("LIVE - 1. POLUVRIJEME - OBA DAJU
        # GOL", "LIVE - 1. POLUVRIJEME I OBA DAJU GOL", "DVOZNAK I OBA DAJU
        # GOL", ...) are NOT kept. Measured, not assumed: capturing one event
        # both ways changes the emitted markets not at all -- still 1x2 + double
        # chance, because none of the variants is a registered market -- while
        # adding one record_unmapped entry per variant to the process-wide
        # diagnostic on every parse, and roughly doubling the dogTipK rows the
        # fixture has to carry. They are unregistered markets, so excluding them
        # keeps the fixture minimal and keeps the diagnostic honest about what
        # the registry genuinely fails to map.
        keep_tips |= {
            tip
            for name, tips in by_name.items()
            if _is_fulltime_btts(name)
            for tip in tips
            if is_live_tip(tip) == (mode == "live")
        }
        # Only the RETAINED blocks have to be live: an in-play event still
        # carries its prematch blocks, which the parser skips anyway.
        if mode == "live" and any(not is_live_tip(tip) for tip in keep_tips):
            continue
        # The keep-set and `exercised` deliberately answer DIFFERENT questions,
        # so they are not the same predicate: the keep-set retains whichever
        # spelling this mode uses (_is_fulltime_btts accepts both), while
        # `exercised` counts BTTS only when the block carries the parser's own
        # prematch spelling, because that is the only one it can read. In live
        # mode the two therefore differ on purpose -- "OBA TIMA DAJU GOL" is
        # kept as evidence of the defect but is not emitted, so it is not
        # claimed as exercised.
        exercised = ["1x2", "double_chance"]
        # A block listed with only its header row offers nothing to read, so the
        # claim needs at least two priced outcomes under the mode's spelling.
        btts_tips = by_name.get(PREMIER_BTTS_NAMES[mode], set())
        priced = [
            row for row in rows
            if row[2] in btts_tips and row[4] != 0 and _active(row[5])
        ]
        if len(priced) >= 2:
            exercised.append("btts")
        elif mode == "live":
            continue  # keep looking for an in-play event that really offers BTTS
        if mode == "prematch":
            exercised += ["over_under_1_5", "over_under_2_5", "over_under_3_5"]
        # An excluded market carried by the same event, kept as a control.
        keyword = "LIVE - HENDIKEP" if mode == "live" else "HENDIKEP"
        for tip in sorted({row[2] for row in rows}):
            if keyword in str(name_of.get((2, tip), "")):
                keep_tips.add(tip)
                break
        rows_kept = [row for row in rows if row[2] in keep_tips]
        kept_tips = {row[2] for row in rows_kept}
        _finish(
            {
                "bookmaker": "premier_kladionica",
                "mode": mode,
                "captured_at": CAPTURE_DATE,
                "endpoint": (
                    f"POST {PREMIER_SYNC} body=[[[4,1,0],7,"
                    f'{{"dogadjajIDs":"{len(ids)} football event ids","clientVer":{ver}}}]]'
                ),
                "source": "live_api_response",
                "payload_kind": "premier_dogtipk",
                "provenance": (
                    f"dogTipK rows for one football event (id {event_id}) from the live PrSync"
                    " delta response, with the setTip/setTipVar/setTipTip definition rows for"
                    " exactly the setTip ids those odds belong to. All rows are stored verbatim"
                    " because PrSync is positional: setTipVar's line is column 9, setTipTip's"
                    " outcome code is column 4 and dogTipK's price is column 5."
                    + (
                        ""
                        if "btts" in exercised
                        else " KNOWN DEFECT, kept as evidence: the live BTTS block is named "
                        "'LIVE - OBA TIMA DAJU GOL' while the parser's NAME_BTTS is "
                        "'OBA DAJU GOL', so the parser cannot match it and the registry's "
                        "live LIVE_OBA_DAJU_GOL row is unreachable. Prematch really is "
                        "'OBA DAJU GOL', so the fix is to make NAME_BTTS mode-aware, NOT to "
                        "rename the registry row. See the xfail marker in "
                        "tests/test_market_fixtures.py."
                    )
                ),
                "dropped_fields": [],
                "excluded_ids_present": [
                    {
                        "id": str(tip),
                        "context": " ".join(str(name_of.get((2, tip), "")).split()),
                    }
                    for tip in kept_tips
                    if "HENDIKEP" in str(name_of.get((2, tip), ""))
                ],
                "bets": rows_kept,
                "lookup": {
                    "set_tip": [r for r in set_tip if r[1] in kept_tips],
                    "set_tip_var": [r for r in sections[8] or []
                                    if isinstance(r, list) and len(r) >= 10 and r[0] == 2 and r[1] in kept_tips],
                    "set_tip_tip": [r for r in sections[9] or []
                                    if isinstance(r, list) and len(r) >= 5 and r[0] == 2 and r[1] in kept_tips],
                },
            },
            exercised,
        )
        return
    _skip(
        "premier_kladionica", mode,
        "no in-play football event carried LIVE - UTAKMICA (and OBA DAJU GOL) at capture time",
    )


# --------------------------------------------------------------------------
# MBet
# --------------------------------------------------------------------------

MBET_FIELDS = ("value", "market_key", "oddtype_key", "market_status", "oddtype_status")
MBET_API = "https://api.mbet.ba/events_cached"
MBET_PREMATCH_WANT = {
    "1x2": ["ofb:fs:1", "ofb:fs:X", "ofb:fs:2"],
    "double_chance": ["ofb:dc:1X", "ofb:dc:12", "ofb:dc:X2"],
    "btts": ["ofb:gg:GG", "ofb:gg:NG"],
    "over_under_1_5": ["ofb:tg:2+", "ofb:tg:0-1"],
    "over_under_2_5": ["ofb:tg:3+", "ofb:tg:0-2"],
    "over_under_3_5": ["ofb:tg:4+", "ofb:tg:0-3"],
}
MBET_LIVE_WANT = {
    "1x2": ["lfb:ft:1", "lfb:ft:X", "lfb:ft:2"],
    "double_chance": ["lfb:dc:1X", "lfb:dc:12", "lfb:dc:X2"],
    "btts": ["lfb:bttsny:Yes", "lfb:bttsny:No"],
    "over_under_1_5": ["lfb:tg:over|1.5", "lfb:tg:under|1.5"],
    "over_under_2_5": ["lfb:tg:over|2.5", "lfb:tg:under|2.5"],
    "over_under_3_5": ["lfb:tg:over|3.5", "lfb:tg:under|3.5"],
}
MBET_CONTROL_PREFIXES = ("ofb:fts:", "ofb:sh:", "ofb:dnb:", "lfb:tg1sth:")


async def capture_mbet(client: httpx.AsyncClient, _bookmaker: str, mode: str) -> None:
    now = datetime.now(UTC)
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    url = (
        f"{MBET_API}?live={'true' if mode == 'live' else 'false'}&offer_plan=true&fields=all"
        f"&lang=ba&limit=100&offset=0&start={now.strftime(fmt)}"
        f"&end={(now + timedelta(days=14)).strftime(fmt)}&orderBy=startTimeAsc"
    )
    response = await client.get(
        url, headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    )
    response.raise_for_status()
    events = response.json().get("events", [])
    want = MBET_LIVE_WANT if mode == "live" else MBET_PREMATCH_WANT
    for event in events:
        if event.get("id_sport") != "fb" or event.get("finished"):
            continue
        odds = event.get("odds") or {}
        flat = [key for keys in want.values() for key in keys]
        if not all(key in odds for key in flat):
            continue
        if not all(
            odds[key].get("market_status") == "ACTIVE"
            and odds[key].get("oddtype_status") == 1
            and _active(odds[key].get("value"))
            for key in flat
        ):
            continue
        keep = {key: {f: odds[key].get(f) for f in MBET_FIELDS} for key in flat}
        control = next((k for k in odds if k.startswith(MBET_CONTROL_PREFIXES)), None)
        if control is not None:
            keep[control] = {f: odds[control].get(f) for f in MBET_FIELDS}
        _finish(
            {
                "bookmaker": "mbet",
                "mode": mode,
                "captured_at": CAPTURE_DATE,
                "endpoint": url,
                "source": "live_api_response",
                "payload_kind": "mbet_event_odds",
                "provenance": (
                    f"odds{{}} of one football event (id {event.get('id')!r}) from the live MBet"
                    " events_cached response, filtered to the oddtype keys the registry maps"
                    " plus one excluded market family."
                ),
                "dropped_fields": [
                    "extras", "manual_status", "special_value", "special_value_order",
                    "keyboard_code_oddtype", "special_value_history", "result", "settlement",
                ],
                "excluded_ids_present": (
                    [{"id": ":".join(control.split(":")[:2]), "context": control}]
                    if control
                    else []
                ),
                "context": {"id_sport": event.get("id_sport")},
                "bets": keep,
            },
            list(want),
        )
        return
    _skip("mbet", mode, f"no ACTIVE football event carried all of {sorted(want)}")


# --------------------------------------------------------------------------
# SportPlus
# --------------------------------------------------------------------------

SPORTPLUS_BET_FIELDS = ("id", "name")
SPORTPLUS_ODD_FIELDS = ("alias", "value")
SPORTPLUS_PREMATCH_IDS = [1, 6, 768, 800, 802]
SPORTPLUS_LIVE_NAMES = [
    "Pobjednik",
    "Dvostruka Prilika (1X - 12 - X2)",
    "Oba daju gol",
    "Zbroj golova 1.5",
    "Zbroj golova 2.5",
    "Zbroj golova 3.5",
]


def _trim_sportplus_market(market: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: market.get(k) for k in SPORTPLUS_BET_FIELDS},
        "odds": [{k: o.get(k) for k in SPORTPLUS_ODD_FIELDS} for o in market.get("odds", []) or []],
    }


def _sportplus_ok(market: dict[str, Any], min_odds: int) -> bool:
    odds = market.get("odds", []) or []
    return len(odds) >= min_odds and sum(1 for o in odds if _active(o.get("value"))) >= min_odds


async def capture_sportplus(client: httpx.AsyncClient, _bookmaker: str, mode: str) -> None:
    url = (
        "https://www.sportplus.ba/api/v1/live/offer"
        if mode == "live"
        else "https://www.sportplus.ba/api/v1/prematch/offer"
    )
    response = await client.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
        },
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, str):
        data = json.loads(data)
    if mode == "live":
        pool = [
            match
            for sport in data.get("sports", [])
            if str(sport.get("name", "")).upper() == "NOGOMET"
            for match in sport.get("matches", [])
        ]
    else:
        pool = [
            m for m in data.get("matches", [])
            if str(m.get("sportName", "")).upper() == "NOGOMET"
        ]

    for match in pool:
        markets = match.get("markets", []) or []
        kept: list[dict[str, Any]] = []
        control: dict[str, Any] | None = None
        if mode == "prematch":
            by_id = {m.get("id"): m for m in markets}
            if not all(mid in by_id for mid in SPORTPLUS_PREMATCH_IDS):
                continue
            for mid in SPORTPLUS_PREMATCH_IDS:
                if not _sportplus_ok(by_id[mid], 6 if mid == 1 else 2):
                    break
                kept.append(_trim_sportplus_market(by_id[mid]))
            else:
                # 800 and 802 are two halves of one goal-range market: 800 holds
                # 01/02/3+/4+ and 802 holds 2+/03, so 1.5 and 3.5 only resolve
                # when BOTH blocks are present.
                pairs = {(m.get("id"), str(o.get("alias"))) for m in markets for o in m.get("odds", []) or []}
                if not {(800, "01"), (800, "3+"), (800, "02"), (800, "4+"), (802, "2+"), (802, "03")} <= pairs:
                    continue
                control = next((m for m in markets if m.get("id") == 178), None)
        else:
            by_name = {str(m.get("name")): m for m in markets}
            if not all(name in by_name for name in SPORTPLUS_LIVE_NAMES):
                continue
            for name in SPORTPLUS_LIVE_NAMES:
                if not _sportplus_ok(by_name[name], 3 if name == "Pobjednik" else 2):
                    break
                kept.append(_trim_sportplus_market(by_name[name]))
            else:
                control = next((m for m in markets if str(m.get("name")) == "Azijski hendikep"), None)
        if not kept:
            continue
        if control is not None:
            kept.append(_trim_sportplus_market(control))
        _finish(
            {
                "bookmaker": "sportplus",
                "mode": mode,
                "captured_at": CAPTURE_DATE,
                "endpoint": url,
                "source": "live_api_response",
                "payload_kind": "sportplus_match_markets",
                "provenance": (
                    f"markets[] of one football match (id {match.get('id')!r}) from the live"
                    f" SportPlus {mode} offer response, filtered to the blocks the registry"
                    " maps plus one block the parser must ignore."
                ),
                "dropped_market_fields": [
                    "competitors", "description", "forbiddenToCombine", "code", "isMain",
                    "order", "maxPayin", "minCombinations", "validations", "sbv", "type",
                    "subtype", "short", "special", "balanced", "tags",
                ],
                "dropped_odd_fields": [
                    "marketId", "field", "order", "description", "values", "changed", "type", "id",
                ],
                "excluded_ids_present": [
                    {
                        "id": control.get("id"),
                        "context": " ".join(str(control.get("name")).split()),
                    }
                ] if control else [],
                "bets": kept,
            },
            list(CORE_MARKETS),
        )
        return
    _skip("sportplus", mode, "no football match carried every registered market block")


# --------------------------------------------------------------------------
# Mozzartbet
# --------------------------------------------------------------------------

MOZZART_GAMES = (1, 2, 3, 130, 141)
MOZZART_API = "https://www.mozzartbet.ba/betting/matches"
# Game 3 ("Ukupno golova") spells its legs as N+/N-M subgames. A totals market
# needs BOTH legs (the registry's min_legs is 2), so a market counts as
# exercised only when the event carries both of its subgames with live odds.
MOZZART_OU = {
    "over_under_1_5": ("2+", "0-1"),
    "over_under_2_5": ("3+", "0-2"),
    "over_under_3_5": ("4+", "0-3"),
}
MOZZART_CORE = {
    "1x2": ((1, "1"), (1, "X"), (1, "2")),
    "double_chance": ((2, "1X"), (2, "12"), (2, "X2")),
    "btts": ((130, "gg"), (130, "ng")),
}


def _trim_mozzart_odd(odd: dict[str, Any]) -> dict[str, Any]:
    game = odd.get("game") or {}
    subgame = odd.get("subgame") or {}
    return {
        "game": {"id": game.get("id"), "shortName": game.get("shortName"), "name": game.get("name")},
        "subgame": {"name": subgame.get("name")},
        "value": odd.get("value"),
    }


async def capture_mozzartbet(_client: httpx.AsyncClient, _bookmaker: str, mode: str) -> None:
    from scrapers.base import launch_browser

    playwright, browser, context = await launch_browser()
    try:
        page = await context.new_page()
        await page.goto(
            f"https://www.mozzartbet.ba/sr/{'uzivo' if mode == 'live' else 'kladjenje'}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(4000)
        date_filter = "live" if mode == "live" else "all_days"
        response = _pw_ok(await page.request.post(
            MOZZART_API,
            data={
                "date": date_filter, "sort": "bycompetition", "pageSize": 15, "sportId": 1,
                "competitionIds": [], "search": "", "matchTypeId": 0, "currentPage": 0,
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "medium": "WEB",
                "Referer": "https://www.mozzartbet.ba/sr/kladjenje/sport/1?date=all_days",
                "x-unique-id": "mozz_capture",
            },
        ))
        items = (await response.json()).get("items", [])
        if not items:
            _skip("mozzartbet", mode, "betting/matches returned no items")
            return
        core = {key for pair in MOZZART_CORE.values() for key in pair}
        for event in items:
            odds = event.get("odds") or []
            by_key = {
                (o["game"]["id"], str(o["subgame"].get("name"))): o.get("value") for o in odds
            }
            if not core <= set(by_key):
                continue
            if not all(_active(by_key[key]) for key in core):
                continue
            totals = sorted(
                market
                for market, (over, under) in MOZZART_OU.items()
                if _active(by_key.get((3, over))) and _active(by_key.get((3, under)))
            )
            if not totals:
                continue
            keep = [
                _trim_mozzart_odd(o) for o in odds if (o.get("game") or {}).get("id") in MOZZART_GAMES
            ]
            exercised = list(MOZZART_CORE) + totals
            absent = sorted(set(MOZZART_OU) - set(totals))
            _finish(
                {
                    "bookmaker": "mozzartbet",
                    "mode": mode,
                    "captured_at": CAPTURE_DATE,
                    "endpoint": f"POST {MOZZART_API} body={{\"date\":\"{date_filter}\",\"sportId\":1,...}}",
                    "source": "live_api_response",
                    "payload_kind": "mozzartbet_event_odds",
                    "provenance": (
                        f"odds[] of one football item (id {event.get('id')!r}) from the live"
                        " Mozzartbet betting/matches response, filtered to games 1/2/3/130 plus"
                        " the excluded game 141 (Mozzart kombinacije). The feed serves no"
                        f" {', '.join(absent) or 'other'} subgame pair for game 3 that would"
                        " complete a totals market, so those registry rows stay unexercised:"
                        " a totals market needs both legs and the registry's min_legs is 2."
                    ),
                    "dropped_odd_fields": ["id", "rank", "specialOddValue", "priority", "topOdd"],
                    "dropped_subgame_fields": ["id", "rank", "description", "fullId"],
                    "dropped_game_fields": ["rank", "specialOddValueType"],
                    "excluded_ids_present": [{"id": 141, "context": "kmb Mozzart kombinazzije"}],
                    "bets": keep,
                },
                exercised,
            )
            return
        _skip("mozzartbet", mode, "no item carried games 1/2/3/130 with usable odds")
    finally:
        await browser.close()
        await playwright.stop()


# --------------------------------------------------------------------------
# EVLBet
# --------------------------------------------------------------------------

EVLBET_API = "https://sportapis.evlbet.com/SportsOfferApi/api/sport/offer/v3/matches/flat"


async def capture_evlbet(client: httpx.AsyncClient, _bookmaker: str, _mode: str) -> None:
    url = f"{EVLBET_API}?SportIds=388&Limit=100&Offset=0"
    try:
        response = await client.get(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://evlbet.com",
                "Referer": "https://evlbet.com/",
            },
        )
        response.raise_for_status()
    except Exception as error:  # noqa: BLE001
        _skip("evlbet", "prematch", f"host unreachable from this machine: {type(error).__name__}: {error}")
        return
    data = response.json()
    events = data if isinstance(data, list) else data.get("Response", [])
    if not events:
        _skip(
            "evlbet", "prematch",
            f"the flat offer feed answered {response.status_code} with an empty list "
            f"(no matches for any SportIds/Limit/Offset) — the API is up but serves no "
            "offer right now, so there is nothing to capture",
        )
        return
    for event in events:
        offer = event.get("BasicOffer") or {}
        odds = offer.get("Odds", []) or []
        if offer.get("HasSbv") or offer.get("Sbv") is not None:
            continue
        if not {"1", "X", "2"} <= {str(o.get("Name")) for o in odds}:
            continue
        if not all(_active(o.get("Odd")) for o in odds):
            continue
        _finish(
            {
                "bookmaker": "evlbet",
                "mode": "prematch",
                "captured_at": CAPTURE_DATE,
                "endpoint": url,
                "source": "live_api_response",
                "payload_kind": "evlbet_match",
                "provenance": (
                    f"one match (id {event.get('Id')!r}) from the live EVLBet flat offer feed,"
                    " carrying the registered full-time result offer."
                ),
                "dropped_fields": [],
                "excluded_ids_present": [],
                "bets": [event],
            },
            ["1x2"],
        )
        return
    _skip("evlbet", "prematch", "no match carried a 1/X/2 BasicOffer")


# --------------------------------------------------------------------------
# MaxBet
# --------------------------------------------------------------------------

MAXBET_API = "https://sportsbook.maxbet.ba/sportsbook/rest/v2/matches"
MAXBET_MARKET_FIELDS = ("id", "name", "specifiers")
MAXBET_OUTCOME_FIELDS = ("outcome", "outcomeId", "status", "oddValue", "marketAvailableForBetting")
MAXBET_PLAIN = {1: "1x2", 10: "double_chance", 27: "btts"}
MAXBET_TOTALS = {"1.5": "over_under_1_5", "2.5": "over_under_2_5", "3.5": "over_under_3_5"}
# A total at a line the registry does not price: kept as a control that must emit nothing.
MAXBET_CONTROL_TOTAL = "4.5"


def _trim_maxbet_market(market: dict[str, Any]) -> dict[str, Any]:
    trimmed = {f: market[f] for f in MAXBET_MARKET_FIELDS if f in market}
    trimmed["outcomes"] = [
        {f: o.get(f) for f in MAXBET_OUTCOME_FIELDS} for o in market.get("outcomes") or []
    ]
    return trimmed


def _maxbet_open(market: dict[str, Any]) -> bool:
    outcomes = market.get("outcomes") or []
    return bool(outcomes) and all(
        o.get("status") == 0 and o.get("marketAvailableForBetting") is not False
        and _active(o.get("oddValue"))
        for o in outcomes
    )


async def capture_maxbet(client: httpx.AsyncClient, _bookmaker: str, mode: str) -> None:
    url = f"{MAXBET_API}?sportId=1&ot=1&ot=10&ot=27&ot=17&ln=cnr"
    if mode == "live":
        url += "&status=Live"
    response = await client.get(
        url, headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    )
    response.raise_for_status()
    events = response.json()
    wanted_status = 3 if mode == "live" else 1

    best: tuple[int, dict[str, Any], list[dict[str, Any]], list[str]] | None = None
    for event in events if isinstance(events, list) else []:
        if event.get("eventType") != "Match" or event.get("status") != wanted_status:
            continue
        keep: list[dict[str, Any]] = []
        exercised: list[str] = []
        control = None
        for market in event.get("odds") or []:
            total = str((market.get("specifiers") or {}).get("total") or "")
            if market.get("id") in MAXBET_PLAIN and _maxbet_open(market):
                keep.append(_trim_maxbet_market(market))
                exercised.append(MAXBET_PLAIN[market["id"]])
            elif market.get("id") == 17 and total in MAXBET_TOTALS and _maxbet_open(market):
                keep.append(_trim_maxbet_market(market))
                exercised.append(MAXBET_TOTALS[total])
            elif market.get("id") == 17 and total == MAXBET_CONTROL_TOTAL:
                control = _trim_maxbet_market(market)
        if control is not None:
            keep.append(control)
        if best is None or len(exercised) > best[0]:
            best = (len(exercised), event, keep, exercised)
        if len(exercised) == len(MAXBET_PLAIN) + len(MAXBET_TOTALS):
            break
    if best is None or not best[3]:
        _skip("maxbet", mode, "no football event carried an open registered market")
        return
    _, event, keep, exercised = best
    _finish(
        {
            "bookmaker": "maxbet",
            "mode": mode,
            "captured_at": CAPTURE_DATE,
            "endpoint": url,
            "source": "live_api_response",
            "payload_kind": "maxbet_match_odds",
            "provenance": (
                f"odds[] of one football match (id {event.get('id')!r}, {event.get('name')!r})"
                " from the live MaxBet sportsbook /rest/v2/matches response, trimmed to the"
                " open markets the registry maps plus the unpriced 4.5 total as a control."
            ),
            "dropped_bet_fields": ["isPlayerMarket", "description"],
            "dropped_odd_fields": ["id", "description", "updateDate", "providerTimestamp",
                                   "externalIds"],
            "excluded_ids_present": [],
            "bets": keep,
        },
        exercised,
    )


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

CAPTORS = {
    "mdshop": capture_nsoft,
    "admiralbet": capture_nsoft,
    "wwin": capture_wwin,
    "premier_kladionica": capture_premier,
    "mbet": capture_mbet,
    "sportplus": capture_sportplus,
    "mozzartbet": capture_mozzartbet,
    "evlbet": capture_evlbet,
    "maxbet": capture_maxbet,
}
BOTH_MODES = {
    "mdshop", "admiralbet", "wwin", "premier_kladionica",
    "mbet", "sportplus", "mozzartbet", "maxbet",
}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Capture live market fixtures")
    parser.add_argument("--books", default="", help="comma-separated subset of bookmakers")
    args = parser.parse_args()
    books = [b.strip() for b in args.books.split(",") if b.strip()] or list(CAPTORS)
    unknown = [b for b in books if b not in CAPTORS]
    if unknown:
        parser.error(f"unknown bookmaker(s): {unknown}")

    async with httpx.AsyncClient(timeout=120.0, verify=False, follow_redirects=True) as client:
        for book in books:
            print(f"== {book}")
            for mode in (("prematch", "live") if book in BOTH_MODES else ("prematch",)):
                await CAPTORS[book](client, book, mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
