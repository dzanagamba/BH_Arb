"""Honest per-leg destinations for a surebet.

A destination answers one question: *what will this link actually do when the
operator clicks it?* The answer comes from a dated coverage record
(``config/bookmaker_destinations.json``), never from the presence of a URL. The
ladder is:

1. ``ticket_filled`` — the match opens with this leg's selection already on the
   ticket (and, where the site accepts it, the stake);
2. ``match_page`` — the per-event page for the fixture;
3. ``search`` — the book's own spelling, offered for copying;
4. ``competition`` — the book's competition page.

A route is only used at a rung its recorded spot check supports. A ticket route
without a confirmed populated ticket is not a ticket, and a per-event route
without a confirmed fixture is not a match page: both fall visibly to the next
rung instead of being presented as something they are not.

This module is deliberately outside the certainty gate. It never writes
``deep_link_verified`` and never changes a group's status; a manual link check
cannot make an unverified group display. It also never stores credentials and
never places a bet.
"""

from __future__ import annotations

import json
import string
from pathlib import Path
from typing import Any
from urllib.parse import quote

from models.schemas import LegDestination, MarketType, Match, Surebet, SurebetStake

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "bookmaker_destinations.json"

LADDER: tuple[str, ...] = ("ticket_filled", "match_page", "search", "competition")

MARKET_LABELS: dict[str, str] = {
    "1x2": "1X2",
    "over_under_1_5": "O/U 1.5",
    "over_under_2_5": "O/U 2.5",
    "over_under_3_5": "O/U 3.5",
    "btts": "BTTS",
    "double_chance": "1X2 + DC",
    "first_half_1x2": "1H 1X2",
    "first_half_ou": "1H O/U",
    "asian_handicap": "Asian handicap",
}

_coverage_cache: dict[str, Any] | None = None


def load_coverage(path: Path | str | None = None) -> dict[str, Any]:
    """Read the dated coverage record, or an empty mapping when it is absent."""
    global _coverage_cache
    if path is None and _coverage_cache is not None:
        return _coverage_cache
    target = Path(path) if path is not None else CONFIG_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if path is None:
        _coverage_cache = data
    return data


def clear_cache() -> None:
    """Forget the loaded record (tests and a process that edits the file)."""
    global _coverage_cache
    _coverage_cache = None


def _book_config(bookmaker: str, coverage: dict[str, Any]) -> dict[str, Any]:
    books = coverage.get("books")
    if not isinstance(books, dict):
        return {}
    value = books.get(bookmaker)
    return value if isinstance(value, dict) else {}


def _mode_config(bookmaker: str, mode: str, coverage: dict[str, Any]) -> dict[str, Any]:
    book = _book_config(bookmaker, coverage)
    modes = book.get("modes")
    if not isinstance(modes, dict):
        return {}
    value = modes.get(mode)
    if isinstance(value, dict):
        return value
    fallback = modes.get("prematch")
    return fallback if isinstance(fallback, dict) else {}


def _routes(mode_config: dict[str, Any]) -> list[dict[str, Any]]:
    routes = mode_config.get("routes")
    if not isinstance(routes, list):
        return []
    return [route for route in routes if isinstance(route, dict)]


def _route_for(mode_config: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for route in _routes(mode_config):
        if route.get("kind") == kind:
            return route
    return None


def _template_fields(template: str) -> set[str]:
    try:
        return {
            field
            for _, field, _, _ in string.Formatter().parse(template)
            if field is not None
        }
    except ValueError:
        return set()


def _format(template: str, values: dict[str, str]) -> str:
    """Format only when every placeholder in the template has a real value."""
    if not template:
        return ""
    fields = _template_fields(template)
    if any(not values.get(field) for field in fields):
        return ""
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return ""


def _proof_ok(route: dict[str, Any], kind: str) -> bool:
    proof = route.get("proof")
    if not isinstance(proof, dict):
        return False
    if proof.get("result") != "confirmed":
        return False
    if proof.get("fixture_confirmed") is not True:
        return False
    if kind == "ticket_filled" and proof.get("ticket_confirmed") is not True:
        return False
    return True


def _page_ok(route: dict[str, Any]) -> bool:
    """Whether a non-fixture page (search or competition) was confirmed to open."""
    proof = route.get("proof")
    return (
        isinstance(proof, dict)
        and proof.get("result") == "confirmed"
        and proof.get("page_confirmed") is True
    )


def _proof_summary(proof: dict[str, Any] | None) -> str:
    if not isinstance(proof, dict):
        return ""
    checked = str(proof.get("checked_at") or "")
    sample = str(proof.get("sample_fixture") or "")
    event = str(proof.get("sample_event_id") or "")
    bits = ["spot-checked" if checked else "unchecked"]
    if checked:
        bits.append(checked)
    if sample:
        bits.append(sample)
    if event:
        bits.append(f"event {event}")
    return " · ".join(bits)


def _identifier(match: Match, source: str) -> str:
    if source == "event_id":
        return str(match.event_id or "")
    if source == "betradar_id":
        return str(match.betradar_id or "")
    if source == "match_code":
        return str(match.match_code or "")
    return ""


def _book_spelling(match: Match) -> tuple[str, str]:
    home = match.home_team_source or match.home_team
    away = match.away_team_source or match.away_team
    return home, away


def _search_text(match: Match, template: str) -> str:
    home, away = _book_spelling(match)
    return _format(
        template,
        {
            "home": home,
            "away": away,
            "league": match.league or "",
            "query": "",
        },
    ) or f"{home} {away}".strip()


def selection_line(label: str) -> str:
    """The line a selection carries, or an empty string for a line-free market."""
    text = str(label or "").strip()
    low = text.lower()
    if low.startswith("over "):
        return text[5:].strip()
    if low.startswith("under "):
        return text[6:].strip()
    parts = text.split()
    if len(parts) == 2 and parts[0] in ("1", "2"):
        try:
            float(parts[1])
        except ValueError:
            return ""
        return parts[1]
    return ""


def _find_market(match: Match, market_type: MarketType, label: str):
    # A cross-market Double Chance surebet may take its "1" leg from the book's
    # 1X2 market and its "X2" leg from the DC market, so both source markets are
    # valid for that surebet type.
    wanted = (
        (MarketType.DOUBLE_CHANCE, MarketType.MATCH_RESULT)
        if market_type == MarketType.DOUBLE_CHANCE
        else (market_type,)
    )
    for market in match.markets:
        if market.market_type not in wanted:
            continue
        if any(odd.label == label for odd in market.odds):
            return market
    return None


def _ticket_items(match: Match, stake: SurebetStake, market_type: MarketType) -> str:
    """Build NSoft's ``ticketItems`` JSON from the parser's own ids.

    The format is the one the NSoft client reads: a JSON array of arrays
    ``[sportId, regionId, competitionId, eventId, betId, betOutcomeId]``. Every
    value must come from the book's payload; a missing one returns an empty
    string so the caller falls back instead of guessing.
    """
    market = _find_market(match, market_type, stake.outcome_label)
    if market is None:
        return ""
    context = market.source_context
    required = ("sport_id", "region_id", "competition_id", "event_id", "bet_id")
    if any(not context.get(key) for key in required):
        return ""
    outcome_id = market.outcome_ids.get(stake.outcome_label, "")
    if not outcome_id:
        return ""
    values: list[int | str] = []
    for key in required:
        raw = str(context[key])
        values.append(int(raw) if raw.isdigit() else raw)
    values.append(int(outcome_id) if outcome_id.isdigit() else outcome_id)
    return json.dumps([values], separators=(",", ":"))


def _sportplus_prefill_script(
    match: Match, stake: SurebetStake, market_type: MarketType, mode: str
) -> tuple[str, str]:
    """Build a copyable SportPlus localStorage prefill script, or an empty pair.

    SportPlus has no per-event URL and no ticket query parameter: its slip is
    read from ``localStorage["ticket"]`` on page load. This script fetches the
    site's own current offer, finds the same match/market/selection by the ids
    the scraper carried, writes one pair with the planned stake, and reloads.
    It places no bet and is deliberately a manual copy action, not a link.
    """
    if match.bookmaker != "sportplus" or mode != "prematch":
        return "", ""
    market = _find_market(match, market_type, stake.outcome_label)
    if market is None:
        return "", ""
    context = market.source_context
    match_id = context.get("sportplus_match_id") or ""
    market_code = context.get("sportplus_market_code") or ""
    try:
        aliases = json.loads(context.get("sportplus_odd_aliases") or "{}")
    except ValueError:
        aliases = {}
    alias = str(aliases.get(stake.outcome_label) or "")
    if not match_id or not market_code or not alias:
        return "", ""
    try:
        planned_stake = round(float(stake.stake), 2)
    except (TypeError, ValueError):
        return "", ""
    script = """(async()=>{
  const res=await fetch('/api/v1/prematch/offer');
  let text=(await res.text()).trim();
  text=text.replace(/^<string[^>]*>/,'').replace(/<\\/string>\\s*$/,'').trim();
  let data=JSON.parse(text);
  let layers=0;
  while(typeof data==='string' && layers<3){data=JSON.parse(data);layers++;}
  if(!data || !Array.isArray(data.matches)){console.log('SportPlus offer shape',data);alert('SportPlus: offer shape not recognised');return;}
  const match=data.matches.find(m=>String(m.id)===__MATCH_ID__);
  if(!match){alert('SportPlus: match not found');return;}
  const market=match.markets.find(m=>String(m.code)===__MARKET_CODE__);
  if(!market){alert('SportPlus: market not found');return;}
  const odd=market.odds.find(o=>String(o.alias)===__ALIAS__);
  if(!odd){alert('SportPlus: selection not found');return;}
  const ticket={pairs:[{sportId:match.sportId,matchId:match.id,matchDate:match.matchDate,market,odd,isFix:false,canBet:true}],info:{numberOfPairs:1,totalOdd:odd.value,possiblePayout:0,stakeTax:0,taxedStake:0,possibleWin:0,bonus:0,bonusPercentage:0,winTax:0,taxedWin:0,stake:__STAKE__,systemCombinations:[],selectedCombination:[],fixedPairsNumber:0,systemPairsNumber:0,minCombinations:{numberOfMinimumCombinations:1,pairName:''}},type:0};
  localStorage.setItem('cn-prematch.ticket',JSON.stringify(ticket));
  location.reload();
})()"""
    script = (
        script.replace("__MATCH_ID__", json.dumps(str(match_id)))
        .replace("__MARKET_CODE__", json.dumps(str(market_code)))
        .replace("__ALIAS__", json.dumps(str(alias)))
        .replace("__STAKE__", json.dumps(planned_stake))
    )
    return script, "Copy SportPlus prefill script (manual, not a link)"


def _event_values(match: Match, stake: SurebetStake, market_type: MarketType) -> dict[str, str]:
    home, away = _book_spelling(match)
    region = str(match.source_context.get("region_name") or "")
    competition = str(match.source_context.get("competition_name") or "")
    event_name = str(match.source_context.get("event_name") or f"{home} - {away}")
    sport_id = str(match.source_context.get("sport_id") or "")
    region_id = str(match.source_context.get("region_id") or "")
    competition_id = str(match.source_context.get("competition_id") or "")
    return {
        "event_id": str(match.event_id or ""),
        "betradar_id": str(match.betradar_id or ""),
        "match_code": str(match.match_code or ""),
        "sport_id": sport_id,
        "region_id": region_id,
        "competition_id": competition_id,
        "region": quote(region.replace(" ", "_"), safe=""),
        "competition": quote(competition.replace(" ", "_"), safe=""),
        "competition_key": (
            f"{sport_id}-{region_id}-{competition_id}"
            if sport_id and region_id and competition_id
            else ""
        ),
        "event_name": quote(event_name.replace(" ", "_"), safe=""),
        "ticket_items": quote(_ticket_items(match, stake, market_type), safe=""),
        "home": home,
        "away": away,
        "query": "",
        "name": "",
    }


def _label(route: dict[str, Any], book_name: str, text: str = "") -> str:
    template = str(route.get("label") or "")
    if not template:
        return ""
    return _format(
        template,
        {"name": book_name, "book": book_name, "text": text, "search": text},
    ) or template


def _search_fallback(
    match: Match,
    book_name: str,
    reason: str,
    route: dict[str, Any] | None = None,
) -> LegDestination:
    template = str((route or {}).get("search_text_template") or "{home} {away}")
    text = _search_text(match, template)
    return LegDestination(
        kind="search",
        label=f"Search {book_name} for “{text}”",
        search_text=text,
        identifier=str(match.event_id or ""),
        identifier_source="event_id" if match.event_id else "teams",
        selection="",
        line="",
        market="",
        proof_checked_at=str(((route or {}).get("proof") or {}).get("checked_at") or ""),
        proof_summary=_proof_summary((route or {}).get("proof")),
        fallback_reason=reason,
    )


def build_destination(
    match: Match,
    stake: SurebetStake,
    market_type: MarketType,
    mode: str = "prematch",
    coverage: dict[str, Any] | None = None,
) -> LegDestination:
    """Return the best honest destination for one leg, or a visible search fallback."""
    record = coverage if coverage is not None else load_coverage()
    mode_config = _mode_config(match.bookmaker, mode, record)
    book_name = str(_book_config(match.bookmaker, record).get("name") or match.bookmaker)
    values = _event_values(match, stake, market_type)
    selection = str(stake.outcome_label or "")
    line = selection_line(selection)
    market_label = MARKET_LABELS.get(market_type.value, market_type.value)
    reason = ""

    ticket_route = _route_for(mode_config, "ticket_filled")
    if ticket_route is not None:
        if _proof_ok(ticket_route, "ticket_filled"):
            url = _format(str(ticket_route.get("url_template") or ""), values)
            if url:
                proof = ticket_route.get("proof") or {}
                stake_supported = bool(
                    (ticket_route.get("ticket") or {}).get("stake_prefilled")
                )
                label = _label(ticket_route, book_name)
                if not label:
                    label = (
                        f"Open {book_name} ticket (pick, odds and stake prefilled)"
                        if stake_supported
                        else f"Open {book_name} ticket (pick prefilled; set stake)"
                    )
                return LegDestination(
                    kind="ticket_filled",
                    label=label,
                    url=url,
                    search_text=f"{values['home']} {values['away']}".strip(),
                    identifier=values["event_id"],
                    identifier_source=str(ticket_route.get("identifier_source") or ""),
                    selection=selection,
                    line=line,
                    market=market_label,
                    proof_checked_at=str(proof.get("checked_at") or ""),
                    proof_summary=_proof_summary(proof),
                    ticket_stake_supported=stake_supported,
                )
            reason = "ticket parameters missing"
        else:
            reason = "ticket route has no confirmed populated-ticket proof"

    match_route = _route_for(mode_config, "match_page")
    if match_route is not None:
        if _proof_ok(match_route, "match_page"):
            url = _format(str(match_route.get("url_template") or ""), values)
            if url:
                proof = match_route.get("proof") or {}
                return LegDestination(
                    kind="match_page",
                    label=_label(match_route, book_name) or f"Open {book_name} match",
                    url=url,
                    search_text=f"{values['home']} {values['away']}".strip(),
                    identifier=_identifier(
                        match, str(match_route.get("identifier_source") or "event_id")
                    ),
                    identifier_source=str(match_route.get("identifier_source") or ""),
                    selection=selection,
                    line=line,
                    market=market_label,
                    proof_checked_at=str(proof.get("checked_at") or ""),
                    proof_summary=_proof_summary(proof),
                    fallback_reason=reason,
                )
            reason = reason or "match identifier missing"
        else:
            reason = reason or "match route has no confirmed fixture proof"

    search_route = _route_for(mode_config, "search")
    if search_route is not None:
        text = _search_text(
            match, str(search_route.get("search_text_template") or "{home} {away}")
        )
        url = ""
        if _page_ok(search_route):
            url = _format(
                str(search_route.get("url_template") or ""),
                {**values, "query": quote(text, safe="")},
            )
        if url:
            proof = search_route.get("proof") or {}
            return LegDestination(
                kind="search",
                label=_label(search_route, book_name, text)
                or f"Search {book_name} for “{text}”",
                url=url,
                search_text=text,
                identifier=str(match.event_id or ""),
                identifier_source="event_id" if match.event_id else "teams",
                selection=selection,
                line=line,
                market=market_label,
                proof_checked_at=str(proof.get("checked_at") or ""),
                proof_summary=_proof_summary(proof),
                fallback_reason=reason,
            )
        # An in-page search with no stable URL is not a clickable destination.
        # Keep the book's spelling for the competition page's own search, but
        # prefer a confirmed competition URL over a text-only rung.
        reason = reason or "search has no stable URL"

    competition_route = _route_for(mode_config, "competition")
    if competition_route is not None:
        url = str(competition_route.get("url") or competition_route.get("url_template") or "")
        if url and _page_ok(competition_route):
            proof = competition_route.get("proof") or {}
            script, script_label = _sportplus_prefill_script(
                match, stake, market_type, mode
            )
            return LegDestination(
                kind="competition",
                label=_label(competition_route, book_name) or f"Open {book_name} competition",
                url=url,
                search_text=f"{values['home']} {values['away']}".strip(),
                identifier=str(match.event_id or ""),
                identifier_source="event_id" if match.event_id else "teams",
                selection=selection,
                line=line,
                market=market_label,
                proof_checked_at=str(proof.get("checked_at") or ""),
                proof_summary=_proof_summary(proof),
                fallback_reason=reason or "no confirmed per-event route",
                ticket_script=script,
                ticket_script_label=script_label,
            )
        reason = reason or "competition page has no confirmed proof"

    return _search_fallback(
        match,
        book_name,
        reason or "no recorded route for this book and mode",
        search_route,
    )


def attach_destinations(surebet: Surebet, group, mode: str = "prematch") -> int:
    """Attach one destination to every stake; return how many were attached.

    Only ``Match`` data already in the group is used. This function does not
    perform a request, set ``deep_link_verified`` or change any group status.
    """
    by_book = {match.bookmaker: match for match in group.matches}
    attached = 0
    for stake in surebet.stakes:
        match = by_book.get(stake.bookmaker)
        if match is None:
            continue
        stake.market_type = surebet.market_type.value
        stake.selection = str(stake.outcome_label or "")
        stake.line = selection_line(stake.outcome_label)
        stake.destination = build_destination(
            match, stake, surebet.market_type, mode=mode
        )
        attached += 1
    return attached


def coverage_gaps(coverage: dict[str, Any] | None = None) -> list[str]:
    """Return the books/modes that have no route at all, for the dated record."""
    record = coverage if coverage is not None else load_coverage()
    books = record.get("books")
    if not isinstance(books, dict):
        return ["coverage record has no books"]
    gaps: list[str] = []
    for bookmaker, book in books.items():
        modes = book.get("modes") if isinstance(book, dict) else None
        if not isinstance(modes, dict):
            gaps.append(f"{bookmaker}: no modes")
            continue
        for mode in ("prematch", "live"):
            if not _routes(modes.get(mode) or {}):
                gaps.append(f"{bookmaker}/{mode}: no route")
    return gaps
