"""SR4-3: strict wire schemas at the adapter boundary, one book at a time.

MDShop was the first book: direct HTTP, one JSON envelope
(``{"events": [...]}``) and no browser session.  SR4-3b added Mozzartbet, a
Playwright hybrid whose capture freezes the odds rows rather than an event
envelope.  SR4-3c reuses the NSoft models for Admiralbet after its own dated
captures proved the same shape.  SR4-3d added Betole, whose "price row" is a
``{pick_code: price}`` map rather than a price field.  SR4-3e added MBet, whose
odds map holds either a typed entry object or a bare number.  SR4-3f added
SportPlus, whose fixtures freeze a match's ``markets[]`` array.  SR4-3h added
Premier Kladionica, whose PrSync rows are positional arrays.  The pattern the
remaining books follow, one per session:

1. Model the *raw* response (envelope, event and leaf price row) with pydantic
   ``strict=True`` and ``extra="allow"``.  Strict means a price served as a
   string, a boolean or a renamed field is a validation error, never a silent
   coercion.  ``extra="allow"`` means an added field does not break a book.
2. Keep an explicit allow-list of the keys the parser consumes.  Any other key
   is counted in ``bh_wire_unknown_keys_total`` and logged, never fatal.
3. Validate immediately after ``response.json()`` and raise
   ``ScrapeError(ScrapeKind.SCHEMA_DRIFT)`` on failure.  The adapter already
   re-raises ``ScrapeError``, so the book drops out of the scan (fail closed)
   instead of contributing zero legs as if the feed were merely empty.

The ``NSoft*`` models serve MDShop and Admiralbet (and later its sibling NSoft
books), the ``Mozzart*`` models serve Mozzartbet, the ``Betole*`` models serve
Betole's two ExeFeed envelopes, the ``Mbet*`` models serve MBet's
``events_cached`` envelope, the ``Sportplus*`` models serve SportPlus's
prematch and live offers, and the ``Premier*`` models serve Premier
Kladionica's positional PrSync tables.  Each follow-up row still needs its own
fixture-backed test before it may reuse a model.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from scrapers.errors import ScrapeError, ScrapeKind
from server.observability import metrics

logger = logging.getLogger(__name__)

MODEL_CONFIG = ConfigDict(strict=True, extra="allow")

METRIC_UNKNOWN_KEYS = "bh_wire_unknown_keys_total"


class NSoftOutcome(BaseModel):
    """One price row. ``odd`` is required and must already be a number."""

    model_config = MODEL_CONFIG

    name: str
    odd: float
    orderNo: int | None = None


class NSoftBet(BaseModel):
    """One market block inside an event."""

    model_config = MODEL_CONFIG

    betTypeId: int
    betTypeName: str | None = None
    sBV: str | None = None
    betOutcomes: list[NSoftOutcome] = Field(default_factory=list)


class NSoftEvent(BaseModel):
    """One event. The fields below are the ones a parser reads."""

    model_config = MODEL_CONFIG

    bets: list[NSoftBet] = Field(default_factory=list)
    id: int | str | None = None
    name: str | None = None
    dateTime: str | None = None
    sportId: int | None = None
    regionId: int | None = None
    regionName: str | None = None
    competitionId: int | None = None
    competitionName: str | None = None
    groupName: str | None = None
    categoryName: str | None = None
    betRadarEventId: int | str | None = None
    externalEventId: int | str | None = None
    isInOffer: bool | None = None
    isPlayable: bool | None = None


class NSoftResponse(BaseModel):
    """The NSoft ``getwebevents`` envelope."""

    model_config = MODEL_CONFIG

    events: list[NSoftEvent]


# The allow-lists. They mirror the model fields exactly, so adding a consumed
# key is one edit: a new field on the model and its entry here.
_RESPONSE_FIELDS = frozenset({"events"})
_EVENT_FIELDS = frozenset(NSoftEvent.model_fields)
_BET_FIELDS = frozenset(NSoftBet.model_fields)
_OUTCOME_FIELDS = frozenset(NSoftOutcome.model_fields)

_BETS_ADAPTER = TypeAdapter(list[NSoftBet])


def _count_unknown(
    value: Any,
    allowed: frozenset[str],
    level: str,
    counts: Counter[str],
) -> None:
    if not isinstance(value, dict):
        return
    for key in value:
        if key not in allowed:
            counts[f"{level}.{key}"] += 1


def _count_bets_unknown(bets: Any, counts: Counter[str]) -> None:
    """Count unknown keys in a ``bets`` array, without its event shell."""
    if not isinstance(bets, list):
        return
    for bet in bets:
        _count_unknown(bet, _BET_FIELDS, "bet", counts)
        outcomes = bet.get("betOutcomes") if isinstance(bet, dict) else None
        if not isinstance(outcomes, list):
            continue
        for outcome in outcomes:
            _count_unknown(outcome, _OUTCOME_FIELDS, "outcome", counts)


def unknown_key_counts(payload: Any) -> Counter[str]:
    """Unknown keys in a NSoft response, as ``level.key -> occurrences``.

    A level is ``root``, ``event``, ``bet`` or ``outcome``.  The walk is
    defensive: a malformed branch simply yields no counts, because validation
    reports the structural failure separately.
    """
    counts: Counter[str] = Counter()
    _count_unknown(payload, _RESPONSE_FIELDS, "root", counts)
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        return counts
    for event in events:
        _count_unknown(event, _EVENT_FIELDS, "event", counts)
        _count_bets_unknown(
            event.get("bets") if isinstance(event, dict) else None, counts
        )
    return counts


def _record_unknown_keys(counts: Counter[str], *, book: str) -> None:
    """Publish unknown keys as a counter and one log line, never a failure."""
    if not counts:
        return
    for path, count in sorted(counts.items()):
        level, _, field = path.partition(".")
        metrics.inc(METRIC_UNKNOWN_KEYS, count, book=book, level=level, field=field)
    logger.info(
        "[%s] unknown wire keys (kept, not fatal): %s", book, dict(counts)
    )


def _drift_message(label: str, exc: ValidationError) -> str:
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    return f"{label} schema drift at {location or 'payload'}: {first.get('msg', 'invalid')}"


def _validate(model: type[BaseModel], payload: Any, *, book: str, label: str) -> Any:
    counts = unknown_key_counts(payload)
    _record_unknown_keys(counts, book=book)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        message = _drift_message(label, exc)
        logger.warning("[%s] %s", book, message)
        raise ScrapeError(ScrapeKind.SCHEMA_DRIFT, message) from exc


def validate_response(payload: Any, *, book: str = "mdshop") -> NSoftResponse:
    """Validate one book's NSoft response envelope (MDShop or Admiralbet)."""
    return _validate(NSoftResponse, payload, book=book, label=f"{book} response")


# ---- Mozzartbet (SR4-3b) --------------------------------------------------
#
# Mozzartbet is a Playwright hybrid: the adapter reads the ``betting/matches``
# JSON envelope (``items`` + ``totalPages``) and one ``betting/match/{id}``
# response per event (``match.odds``).  The dated fixtures freeze the odds
# array (``bets``), so that is the row the allow-list below is proved against;
# the list-item shell itself has no capture yet and stays unmodelled, which is
# recorded in ``docs/WIRE_SCHEMAS.md``.


class MozzartGame(BaseModel):
    """One market group ("Konačan ishod", "Ukupno golova", ...).

    The three fields are required (but may be null): the dated captures always
    carry them, so a renamed ``id``/``name``/``shortName`` is drift rather than
    a row that quietly disappears.
    """

    model_config = MODEL_CONFIG

    id: int | str | None
    name: str | None
    shortName: str | None


class MozzartSubgame(BaseModel):
    """One pick inside a market group ("1", "X", "3+", "0-2", ...)."""

    model_config = MODEL_CONFIG

    name: str | None


class MozzartOdd(BaseModel):
    """One price row. ``value`` is null while a pick is suspended.

    All three fields are required (``value`` may be null): the captures always
    carry them, so a renamed price field is schema drift instead of a row the
    parser silently skips as ``value == 0``.
    """

    model_config = MODEL_CONFIG

    game: MozzartGame | None
    subgame: MozzartSubgame | None
    value: float | None


class MozzartMatch(BaseModel):
    """The ``match`` object of the per-event offer."""

    model_config = MODEL_CONFIG

    odds: list[MozzartOdd] = Field(default_factory=list)


class MozzartOffer(BaseModel):
    """The ``POST /betting/match/{id}`` response; a per-event error has no match."""

    model_config = MODEL_CONFIG

    match: MozzartMatch | None = None


class MozzartMatchesPage(BaseModel):
    """The ``POST /betting/matches`` list envelope.

    ``items`` keeps the raw item dicts: the item shell (teams, kickoff,
    competition) has no dated capture, so it is deliberately not typed yet.
    """

    model_config = MODEL_CONFIG

    items: list[dict[str, Any]] = Field(default_factory=list)
    totalPages: int | None = None


_MOZZART_ODD_FIELDS = frozenset(MozzartOdd.model_fields)
_MOZZART_GAME_FIELDS = frozenset(MozzartGame.model_fields)
_MOZZART_SUBGAME_FIELDS = frozenset(MozzartSubgame.model_fields)
_MOZZART_OFFER_FIELDS = frozenset(MozzartOffer.model_fields)
_MOZZART_MATCH_FIELDS = frozenset(MozzartMatch.model_fields)
_MOZZART_PAGE_FIELDS = frozenset(MozzartMatchesPage.model_fields)

_MOZZART_ODDS_ADAPTER = TypeAdapter(list[MozzartOdd])


def _count_mozzart_odds(rows: Any, counts: Counter[str]) -> None:
    """Count unknown keys in one odds array (levels ``odd``, ``game``, ``subgame``)."""
    if not isinstance(rows, list):
        return
    for row in rows:
        _count_unknown(row, _MOZZART_ODD_FIELDS, "odd", counts)
        if not isinstance(row, dict):
            continue
        _count_unknown(row.get("game"), _MOZZART_GAME_FIELDS, "game", counts)
        _count_unknown(row.get("subgame"), _MOZZART_SUBGAME_FIELDS, "subgame", counts)


def _drift(book: str, label: str, exc: ValidationError | ValueError) -> ScrapeError:
    if isinstance(exc, ValidationError):
        message = _drift_message(label, exc)
    else:
        message = f"{label}: {exc}"
    logger.warning("[%s] %s", book, message)
    return ScrapeError(ScrapeKind.SCHEMA_DRIFT, message)


def validate_mozzart_odds(
    rows: Any, *, book: str = "mozzartbet"
) -> list[MozzartOdd]:
    """Validate one Mozzartbet odds array (the capture's ``bets``)."""
    counts: Counter[str] = Counter()
    _count_mozzart_odds(rows, counts)
    _record_unknown_keys(counts, book=book)
    try:
        return _MOZZART_ODDS_ADAPTER.validate_python(rows, strict=True)
    except ValidationError as exc:
        raise _drift(book, f"{book} odds", exc) from exc


def validate_mozzart_offer(payload: Any, *, book: str = "mozzartbet") -> MozzartOffer:
    """Validate the per-event ``{"match": {"odds": [...]}}`` response.

    A per-event error payload (``{"error": ...}``) validates with ``match`` set
    to ``None``: the event keeps its list odds rather than dropping the book.
    A drifted odds row is schema drift and does drop the book.
    """
    counts: Counter[str] = Counter()
    _count_unknown(payload, _MOZZART_OFFER_FIELDS, "root", counts)
    match = payload.get("match") if isinstance(payload, dict) else None
    _count_unknown(match, _MOZZART_MATCH_FIELDS, "match", counts)
    if isinstance(match, dict):
        _count_mozzart_odds(match.get("odds"), counts)
    _record_unknown_keys(counts, book=book)
    try:
        return MozzartOffer.model_validate(payload)
    except ValidationError as exc:
        raise _drift(book, f"{book} offer", exc) from exc


def validate_mozzart_page(
    payload: Any, *, book: str = "mozzartbet"
) -> MozzartMatchesPage:
    """Validate the ``betting/matches`` list envelope and each item's odds.

    The item shell (teams, kickoff, competition) is not modelled until a capture
    freezes it; its keys are therefore neither rejected nor counted.  An item
    that carries an ``odds`` array gets the same row schema as the offer.
    """
    counts: Counter[str] = Counter()
    _count_unknown(payload, _MOZZART_PAGE_FIELDS, "root", counts)
    items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("odds"), list):
                _count_mozzart_odds(item["odds"], counts)
    _record_unknown_keys(counts, book=book)
    try:
        page = MozzartMatchesPage.model_validate(payload)
        for item in page.items:
            odds = item.get("odds")
            if isinstance(odds, list):
                _MOZZART_ODDS_ADAPTER.validate_python(odds, strict=True)
        return page
    except ValidationError as exc:
        raise _drift(book, f"{book} matches page", exc) from exc


# ---- Betole (SR4-3d) ------------------------------------------------------
#
# Betole is plain HTTP on the ExeFeed platform.  Its "price row" is not an
# object with a price field but a ``{pick_code: price}`` map, and the two
# endpoints wrap that map differently: the desk listing is
# ``{"esMatches": [event, ...]}`` (each event carries ``odds``) and the batched
# full offer is a list of ``{"id": ..., "odds": {...}}`` rows.  The dated
# fixture freezes one event's odds map, so that is what the map schema is
# proved against; the desk event shell has no capture yet and stays unmodelled.


class BetoleDeskPage(BaseModel):
    """The desk listing envelope; the event dicts are kept raw.

    ``esMatches`` is required: a renamed envelope key must fail the schema
    instead of reading as an empty (and therefore plausible) page.
    """

    model_config = MODEL_CONFIG

    esMatches: list[dict[str, Any]]


class BetoleOfferRow(BaseModel):
    """One row of the batched full-offer response."""

    model_config = MODEL_CONFIG

    id: int | str
    odds: dict[str, float | None]


_BETOLE_DESK_FIELDS = frozenset(BetoleDeskPage.model_fields)
_BETOLE_OFFER_ROW_FIELDS = frozenset(BetoleOfferRow.model_fields)

_BETOLE_ODDS_ADAPTER = TypeAdapter(dict[str, float | None])
_BETOLE_OFFERS_ADAPTER = TypeAdapter(list[BetoleOfferRow])


def validate_betole_offer_map(
    odds: Any, *, book: str = "betole"
) -> dict[str, float | None]:
    """Validate one event's ``{pick_code: price}`` map (the fixture's ``bets``).

    The keys are pick codes, not field names, so they are data rather than an
    allow-list: every code the feed serves is accepted and the parser decides
    which ones it can price.  The values are the pricing surface, so they must
    already be numbers (a string or a boolean price is drift).
    """
    try:
        return _BETOLE_ODDS_ADAPTER.validate_python(odds, strict=True)
    except ValidationError as exc:
        raise _drift(book, f"{book} odds", exc) from exc


def validate_betole_desk(payload: Any, *, book: str = "betole") -> BetoleDeskPage:
    """Validate the desk listing envelope and every event's odds map.

    The desk *event* shell (teams, kickoff, live flags) has no dated capture, so
    it is deliberately not modelled: its keys are neither rejected nor counted.
    A renamed team field still drops that event silently; SR4-4/SR5-1 own the
    structural drift alarm.
    """
    counts: Counter[str] = Counter()
    _count_unknown(payload, _BETOLE_DESK_FIELDS, "root", counts)
    _record_unknown_keys(counts, book=book)
    try:
        page = BetoleDeskPage.model_validate(payload)
        for event in page.esMatches:
            odds = event.get("odds")
            if odds is not None:
                _BETOLE_ODDS_ADAPTER.validate_python(odds, strict=True)
        return page
    except ValidationError as exc:
        raise _drift(book, f"{book} desk page", exc) from exc


def validate_betole_offers(
    payload: Any, *, book: str = "betole"
) -> list[BetoleOfferRow]:
    """Validate the batched full-offer response (a list of ``id``/``odds`` rows)."""
    counts: Counter[str] = Counter()
    if isinstance(payload, list):
        for row in payload:
            _count_unknown(row, _BETOLE_OFFER_ROW_FIELDS, "row", counts)
    _record_unknown_keys(counts, book=book)
    try:
        return _BETOLE_OFFERS_ADAPTER.validate_python(payload, strict=True)
    except ValidationError as exc:
        raise _drift(book, f"{book} offers", exc) from exc


# ---- MBet (SR4-3e) --------------------------------------------------------
#
# MBet is plain HTTP on the Alea platform.  The envelope is
# ``{"events": [...]}`` and an event's ``odds`` is a map whose keys are
# oddtype keys (data, like Betole's pick codes) and whose values are either the
# entry object below or a bare number.  The dated fixtures freeze one event's
# odds map, so that is what the entry schema is proved against; the event shell
# has no capture yet and stays unmodelled.


class MbetOdd(BaseModel):
    """One priced oddtype entry.

    The capture writes all five fields for every key (values may be null), so
    they are required: a renamed ``value`` or status field is drift instead of
    an odd the parser silently reads as suspended.
    """

    model_config = MODEL_CONFIG

    value: float | None
    market_key: str | None
    oddtype_key: str | None
    market_status: str | None
    oddtype_status: int | None


class MbetResponse(BaseModel):
    """The ``events_cached`` envelope; the event dicts are kept raw."""

    model_config = MODEL_CONFIG

    events: list[dict[str, Any]]


_MBET_RESPONSE_FIELDS = frozenset(MbetResponse.model_fields)
_MBET_ODD_FIELDS = frozenset(MbetOdd.model_fields)

_MBET_ODDS_ADAPTER: TypeAdapter[dict[str, MbetOdd | float | None]] = TypeAdapter(
    dict[str, MbetOdd | float | None]
)
_MBET_ODD_ADAPTER: TypeAdapter[MbetOdd | float | None] = TypeAdapter(
    MbetOdd | float | None
)


def _count_mbet_odds(odds: Any, counts: Counter[str]) -> None:
    """Count unknown keys in one odds map; keys themselves are oddtype data."""
    if not isinstance(odds, dict):
        return
    for entry in odds.values():
        _count_unknown(entry, _MBET_ODD_FIELDS, "odd", counts)


def validate_mbet_odds(
    odds: Any, *, book: str = "mbet"
) -> dict[str, MbetOdd | float | None]:
    """Validate one event's ``odds`` map (the fixture's ``bets``).

    The keys are oddtype keys, not field names, so they are data: every key is
    accepted and the parser decides which ones it can price.  A value may be
    the entry object or a bare number; a string price is rejected.
    """
    counts: Counter[str] = Counter()
    _count_mbet_odds(odds, counts)
    _record_unknown_keys(counts, book=book)
    try:
        return _MBET_ODDS_ADAPTER.validate_python(odds, strict=True)
    except ValidationError as exc:
        raise _drift(book, f"{book} odds", exc) from exc


def validate_mbet_response(payload: Any, *, book: str = "mbet") -> MbetResponse:
    """Validate the ``events_cached`` envelope and every event's odds map.

    The event shell (sport id, competitors, kickoff, tournament) has no dated
    capture and stays unmodelled: its keys are neither rejected nor counted, so
    a renamed team field still drops that event silently (SR4-4/SR5-1 close it).
    """
    counts: Counter[str] = Counter()
    _count_unknown(payload, _MBET_RESPONSE_FIELDS, "root", counts)
    events = payload.get("events") if isinstance(payload, dict) else None
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                _count_mbet_odds(event.get("odds"), counts)
    _record_unknown_keys(counts, book=book)
    try:
        response = MbetResponse.model_validate(payload)
        for event in response.events:
            odds = event.get("odds")
            if isinstance(odds, dict):
                for entry in odds.values():
                    _MBET_ODD_ADAPTER.validate_python(entry, strict=True)
        return response
    except ValidationError as exc:
        raise _drift(book, f"{book} events page", exc) from exc


# ---- SportPlus (SR4-3f) ---------------------------------------------------
#
# SportPlus is plain HTTP.  The dated fixtures freeze one match's ``markets[]``
# array: each block has ``id``, ``name`` and an ``odds`` list of
# ``{"alias", "value"}`` rows.  The prematch envelope is ``{"matches": [...]}``
# (sometimes double-serialised as a JSON string) and the live one is
# ``{"sports": [{"name": ..., "matches": [...]}]}``; the match shells have no
# capture yet and stay unmodelled.


class SportplusOdd(BaseModel):
    """One ``{"alias", "value"}`` price row."""

    model_config = MODEL_CONFIG

    alias: str | None
    value: float | None


class SportplusMarket(BaseModel):
    """One market block.  ``odds`` is required but nullable: the parser already
    treats a block with no odds as empty, while a renamed ``odds`` key is drift.
    """

    model_config = MODEL_CONFIG

    id: int | str | None
    name: str | None
    odds: list[SportplusOdd] | None


class SportplusPrematchPage(BaseModel):
    """The prematch offer envelope; the match dicts are kept raw."""

    model_config = MODEL_CONFIG

    matches: list[dict[str, Any]]


class SportplusLivePage(BaseModel):
    """The live offer envelope; the sport and match dicts are kept raw.

    ``date`` is carried by the feed but never read, so it is declared without a
    type claim (``Any``) purely to keep it out of the unknown-key telemetry.
    """

    model_config = MODEL_CONFIG

    sports: list[dict[str, Any]]
    date: Any = None


_SPORTPLUS_MARKET_FIELDS = frozenset(SportplusMarket.model_fields)
_SPORTPLUS_ODD_FIELDS = frozenset(SportplusOdd.model_fields)
_SPORTPLUS_PREMATCH_FIELDS = frozenset(SportplusPrematchPage.model_fields)
_SPORTPLUS_LIVE_FIELDS = frozenset(SportplusLivePage.model_fields)

_SPORTPLUS_MARKETS_ADAPTER = TypeAdapter(list[SportplusMarket])


def _count_sportplus_markets(markets: Any, counts: Counter[str]) -> None:
    """Count unknown keys in a ``markets[]`` array (levels ``market``, ``odd``)."""
    if not isinstance(markets, list):
        return
    for market in markets:
        _count_unknown(market, _SPORTPLUS_MARKET_FIELDS, "market", counts)
        if not isinstance(market, dict):
            continue
        odds = market.get("odds")
        if isinstance(odds, list):
            for odd in odds:
                _count_unknown(odd, _SPORTPLUS_ODD_FIELDS, "odd", counts)


def _check_sportplus_markets(markets: Any, *, book: str, label: str) -> None:
    """Validate a ``markets[]`` array; the caller has already counted keys."""
    try:
        _SPORTPLUS_MARKETS_ADAPTER.validate_python(markets, strict=True)
    except ValidationError as exc:
        raise _drift(book, label, exc) from exc


def validate_sportplus_markets(
    markets: Any, *, book: str = "sportplus"
) -> list[SportplusMarket]:
    """Validate one match's ``markets[]`` array (the fixtures' ``bets``)."""
    counts: Counter[str] = Counter()
    _count_sportplus_markets(markets, counts)
    _record_unknown_keys(counts, book=book)
    try:
        return _SPORTPLUS_MARKETS_ADAPTER.validate_python(markets, strict=True)
    except ValidationError as exc:
        raise _drift(book, f"{book} markets", exc) from exc


def validate_sportplus_prematch(
    payload: Any, *, book: str = "sportplus"
) -> SportplusPrematchPage:
    """Validate the prematch ``{"matches": [...]}`` envelope and every market."""
    counts: Counter[str] = Counter()
    _count_unknown(payload, _SPORTPLUS_PREMATCH_FIELDS, "root", counts)
    matches = payload.get("matches") if isinstance(payload, dict) else None
    if isinstance(matches, list):
        for match in matches:
            if isinstance(match, dict):
                _count_sportplus_markets(match.get("markets"), counts)
    _record_unknown_keys(counts, book=book)
    try:
        page = SportplusPrematchPage.model_validate(payload)
    except ValidationError as exc:
        raise _drift(book, f"{book} prematch page", exc) from exc
    for match in page.matches:
        _check_sportplus_markets(
            match.get("markets"), book=book, label=f"{book} markets"
        )
    return page


def validate_sportplus_live(
    payload: Any, *, book: str = "sportplus"
) -> SportplusLivePage:
    """Validate the live ``{"sports": [...]}`` envelope and every market."""
    counts: Counter[str] = Counter()
    _count_unknown(payload, _SPORTPLUS_LIVE_FIELDS, "root", counts)
    sports = payload.get("sports") if isinstance(payload, dict) else None
    if isinstance(sports, list):
        for sport in sports:
            matches = sport.get("matches") if isinstance(sport, dict) else None
            if isinstance(matches, list):
                for match in matches:
                    if isinstance(match, dict):
                        _count_sportplus_markets(match.get("markets"), counts)
    _record_unknown_keys(counts, book=book)
    try:
        page = SportplusLivePage.model_validate(payload)
    except ValidationError as exc:
        raise _drift(book, f"{book} live page", exc) from exc
    for sport in page.sports:
        matches = sport.get("matches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            if isinstance(match, dict):
                _check_sportplus_markets(
                    match.get("markets"), book=book, label=f"{book} markets"
                )
    return page


# ---- Premier Kladionica (SR4-3h) -----------------------------------------
#
# PrSync answers with ``[sections]`` where every section is a list of rows and a
# column's meaning is its index.  The dated fixtures freeze two of those
# tables: the dogTipK odds rows (``bets``) and the setTip/setTipVar/setTipTip
# definition rows (``lookup``).  "Unknown keys" has no per-field meaning here,
# so the counter reports *unknown sections* (slots past the fifteen the parser
# documents) instead.

_PREMIER_ODD_COLUMNS = (
    "dog_id",
    "grupa_tip_id",
    "set_tip_id",
    "var_id",
    "tip_id",
    "koef",
    "na_pon",
    "dobitni",
    "koef1",
)


class PremierOddRow(BaseModel):
    """One dogTipK odds row; ``koef`` (column 5) is the price."""

    model_config = MODEL_CONFIG

    dog_id: int
    grupa_tip_id: int
    set_tip_id: int
    var_id: int
    tip_id: int
    koef: float
    na_pon: int | str
    dobitni: str | int | None
    koef1: str | int | None

    @model_validator(mode="before")
    @classmethod
    def _from_columns(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("odds row must be a list of columns")
        if len(value) < len(_PREMIER_ODD_COLUMNS):
            raise ValueError(
                f"odds row has {len(value)} columns, expected at least "
                f"{len(_PREMIER_ODD_COLUMNS)}"
            )
        return dict(zip(_PREMIER_ODD_COLUMNS, value, strict=False))


class PremierSetTip(BaseModel):
    """One setTip row: ``[sport, setTipID, name, ...]``."""

    model_config = MODEL_CONFIG

    sport_id: int
    set_tip_id: int
    name: str

    @model_validator(mode="before")
    @classmethod
    def _from_columns(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("setTip row must be a list of columns")
        if len(value) < 3:
            raise ValueError(f"setTip row has {len(value)} columns, expected at least 3")
        return dict(zip(("sport_id", "set_tip_id", "name"), value, strict=False))


class PremierSetTipVar(BaseModel):
    """One setTipVar row; the line specifier is column 9."""

    model_config = MODEL_CONFIG

    sport_id: int
    set_tip_id: int
    var_id: int
    line: str | None

    @model_validator(mode="before")
    @classmethod
    def _from_columns(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("setTipVar row must be a list of columns")
        if len(value) < 10:
            raise ValueError(
                f"setTipVar row has {len(value)} columns, expected at least 10"
            )
        return {
            "sport_id": value[0],
            "set_tip_id": value[1],
            "var_id": value[2],
            "line": value[9],
        }


class PremierSetTipTip(BaseModel):
    """One setTipTip row; the outcome code is column 4."""

    model_config = MODEL_CONFIG

    sport_id: int
    set_tip_id: int
    tip_id: int
    code: str | None

    @model_validator(mode="before")
    @classmethod
    def _from_columns(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("setTipTip row must be a list of columns")
        if len(value) < 5:
            raise ValueError(
                f"setTipTip row has {len(value)} columns, expected at least 5"
            )
        return {
            "sport_id": value[0],
            "set_tip_id": value[1],
            "tip_id": value[2],
            "code": value[4],
        }


PREMIER_SECTION_COUNT = 15

_PREMIER_ODDS_ADAPTER = TypeAdapter(list[PremierOddRow])
_PREMIER_SET_TIP_ADAPTER = TypeAdapter(list[PremierSetTip])
_PREMIER_SET_TIP_VAR_ADAPTER = TypeAdapter(list[PremierSetTipVar])
_PREMIER_SET_TIP_TIP_ADAPTER = TypeAdapter(list[PremierSetTipTip])


def validate_premier_odds(
    rows: Any, *, book: str = "premier_kladionica"
) -> list[PremierOddRow]:
    """Validate one event's dogTipK rows (the fixtures' ``bets``)."""
    try:
        return _PREMIER_ODDS_ADAPTER.validate_python(rows, strict=True)
    except ValidationError as exc:
        raise _drift(book, f"{book} odds rows", exc) from exc


def validate_premier_lookup(
    set_tip: Any,
    set_tip_var: Any,
    set_tip_tip: Any,
    *,
    book: str = "premier_kladionica",
) -> tuple[list[PremierSetTip], list[PremierSetTipVar], list[PremierSetTipTip]]:
    """Validate the three definition tables (the fixtures' ``lookup``)."""
    try:
        return (
            _PREMIER_SET_TIP_ADAPTER.validate_python(set_tip, strict=True),
            _PREMIER_SET_TIP_VAR_ADAPTER.validate_python(set_tip_var, strict=True),
            _PREMIER_SET_TIP_TIP_ADAPTER.validate_python(set_tip_tip, strict=True),
        )
    except ValidationError as exc:
        raise _drift(book, f"{book} lookup rows", exc) from exc


def validate_premier_sync(
    payload: Any, *, kind: str, book: str = "premier_kladionica"
) -> list:
    """Validate one PrSync response and return its raw ``sections`` list.

    ``kind`` is ``"full"`` (definitions + events) or ``"delta"`` (dogTipK odds
    rows).  Only capture-backed tables are typed: the setTip/setTipVar/setTipTip
    rows on a full sync and every non-empty delta section as odds rows.  The
    event and execRes sections have no dated capture and stay unmodelled.
    """
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise ScrapeError(
            ScrapeKind.SCHEMA_DRIFT,
            f"{book} sync response is not [[sections]]",
        )
    sections = payload[0]
    if kind == "full" and len(sections) < 10:
        raise ScrapeError(
            ScrapeKind.SCHEMA_DRIFT,
            f"{book} full sync has {len(sections)} sections, expected at least 10",
        )
    counts: Counter[str] = Counter()
    for index in range(PREMIER_SECTION_COUNT, len(sections)):
        counts[f"section.{index}"] += 1
    _record_unknown_keys(counts, book=book)
    try:
        for index, rows in enumerate(sections):
            if rows is None:
                continue
            if not isinstance(rows, list):
                raise ValueError(f"section {index} is not a list of rows")
            if kind == "full":
                premier_adapters: dict[int, TypeAdapter[Any]] = {
                    7: _PREMIER_SET_TIP_ADAPTER,
                    8: _PREMIER_SET_TIP_VAR_ADAPTER,
                    9: _PREMIER_SET_TIP_TIP_ADAPTER,
                }
                adapter = premier_adapters.get(index)
                if adapter is not None:
                    adapter.validate_python(rows, strict=True)
            else:
                _PREMIER_ODDS_ADAPTER.validate_python(rows, strict=True)
    except (ValidationError, ValueError) as exc:
        raise _drift(book, f"{book} {kind} sync", exc) from exc
    return sections


def validate_bets(bets: Any, *, book: str = "mdshop") -> list[NSoftBet]:
    """Validate just the ``events[*].bets`` array a captured fixture holds.

    The dated fixtures freeze the bets array, not the event shell around it, so
    this is the entry point that proves a capture still satisfies the schema.
    """
    counts: Counter[str] = Counter()
    _count_bets_unknown(bets, counts)
    _record_unknown_keys(counts, book=book)
    try:
        return _BETS_ADAPTER.validate_python(bets, strict=True)
    except ValidationError as exc:
        message = _drift_message(f"{book} bets", exc)
        logger.warning("[%s] %s", book, message)
        raise ScrapeError(ScrapeKind.SCHEMA_DRIFT, message) from exc


__all__ = [
    "METRIC_UNKNOWN_KEYS",
    "BetoleDeskPage",
    "BetoleOfferRow",
    "MbetOdd",
    "MbetResponse",
    "MozzartGame",
    "MozzartMatch",
    "MozzartMatchesPage",
    "MozzartOdd",
    "MozzartOffer",
    "MozzartSubgame",
    "NSoftBet",
    "NSoftEvent",
    "NSoftOutcome",
    "NSoftResponse",
    "PremierOddRow",
    "PremierSetTip",
    "PremierSetTipTip",
    "PremierSetTipVar",
    "SportplusLivePage",
    "SportplusMarket",
    "SportplusOdd",
    "SportplusPrematchPage",
    "unknown_key_counts",
    "validate_bets",
    "validate_betole_desk",
    "validate_betole_offer_map",
    "validate_betole_offers",
    "validate_mbet_odds",
    "validate_mbet_response",
    "validate_mozzart_odds",
    "validate_mozzart_offer",
    "validate_mozzart_page",
    "validate_premier_lookup",
    "validate_premier_odds",
    "validate_premier_sync",
    "validate_response",
    "validate_sportplus_live",
    "validate_sportplus_markets",
    "validate_sportplus_prematch",
]
