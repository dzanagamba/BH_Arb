"""Sport identity and non-football market semantics.

Football keeps its original nine market types and normalization pipeline.  This
module adds the identity that makes a sport a *hard* boundary and the small,
explicit vocabulary the new sports share:

* a canonical sport key on every listing, group and surebet;
* per-sport outcome vocabulary (moneyline / handicap / total) and the exact
  settlement a market is priced under;
* name normalization for non-football listings, where football's club-designator
  and youth/reserve parsing does not apply.

Nothing here guesses.  A sport a parser cannot prove is left out; a market whose
settlement differs from another book's is not comparable, even when the labels
look identical.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from models.schemas import MarketType, Sport

FOOTBALL = Sport.FOOTBALL.value
BASKETBALL = Sport.BASKETBALL.value
TENNIS = Sport.TENNIS.value
ICE_HOCKEY = Sport.ICE_HOCKEY.value

# Sports the pipeline can scan. Football is always first: the football path is
# byte-for-byte the old one, and this list only decides which extra feeds are
# parsed.
ENABLED_SPORTS: tuple[str, ...] = (FOOTBALL, BASKETBALL, TENNIS)

# Book feed names -> canonical sport. A name absent here is not implemented; it
# is counted as a coverage gap by the discovery probe, never guessed.
SPORT_ALIASES: dict[str, str] = {
    "football": FOOTBALL,
    "soccer": FOOTBALL,
    "fudbal": FOOTBALL,
    "nogomet": FOOTBALL,
    "basketball": BASKETBALL,
    "kosarka": BASKETBALL,
    "košarka": BASKETBALL,
    "tennis": TENNIS,
    "tenis": TENNIS,
    "ice_hockey": ICE_HOCKEY,
    "ice hockey": ICE_HOCKEY,
    "hockey": ICE_HOCKEY,
    "hokej": ICE_HOCKEY,
}

_DISPLAY = {
    FOOTBALL: "Football",
    BASKETBALL: "Basketball",
    TENNIS: "Tennis",
    ICE_HOCKEY: "Ice hockey",
}


@dataclass(frozen=True)
class SportSpec:
    """Canonical market families and settlement for one sport."""

    key: str
    label: str
    moneyline: MarketType
    moneyline_labels: tuple[str, ...]
    handicap: MarketType
    total: MarketType
    # Settlement is part of market identity: a regular-time total and an
    # including-overtime total are different bets even at the same line.
    moneyline_settlement: str
    handicap_settlement: str
    total_settlement: str
    markets: tuple[MarketType, ...] = field(default=())

    def families(self) -> tuple[MarketType, ...]:
        return self.markets or (self.moneyline, self.handicap, self.total)


SPORT_SPECS: dict[str, SportSpec] = {
    BASKETBALL: SportSpec(
        key=BASKETBALL,
        label=_DISPLAY[BASKETBALL],
        moneyline=MarketType.MONEYLINE,
        moneyline_labels=("1", "2"),
        handicap=MarketType.HANDICAP,
        total=MarketType.TOTAL,
        # Winner includes overtime at every implemented book; handicap and total
        # are regular time at every implemented book. Mixing the two would price
        # two different bets.
        moneyline_settlement="full_time_incl_ot",
        handicap_settlement="regulation",
        total_settlement="regulation",
        markets=(MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL),
    ),
    TENNIS: SportSpec(
        key=TENNIS,
        label=_DISPLAY[TENNIS],
        moneyline=MarketType.MONEYLINE,
        moneyline_labels=("1", "2"),
        handicap=MarketType.HANDICAP,
        total=MarketType.TOTAL,
        # Tennis has no overtime; every implemented market settles on the match.
        moneyline_settlement="full_match",
        handicap_settlement="full_match",
        total_settlement="full_match",
        markets=(MarketType.MONEYLINE, MarketType.HANDICAP, MarketType.TOTAL),
    ),
    ICE_HOCKEY: SportSpec(
        key=ICE_HOCKEY,
        label=_DISPLAY[ICE_HOCKEY],
        moneyline=MarketType.MONEYLINE_3WAY,
        moneyline_labels=("1", "X", "2"),
        handicap=MarketType.HANDICAP,
        total=MarketType.TOTAL,
        moneyline_settlement="regulation",
        handicap_settlement="regulation",
        total_settlement="regulation",
        markets=(MarketType.MONEYLINE_3WAY, MarketType.HANDICAP, MarketType.TOTAL),
    ),
}


def normalize_sport(value: object) -> str:
    """Map a feed's sport label to the canonical key, or ``""`` if unknown."""
    text = " ".join(str(value or "").strip().casefold().replace("_", " ").split())
    return SPORT_ALIASES.get(text, "")


def spec_for(sport: str) -> SportSpec | None:
    return SPORT_SPECS.get(sport)


def display_name(sport: str) -> str:
    return _DISPLAY.get(sport, sport.replace("_", " ").title())


def family(market_type: MarketType) -> str:
    """The semantic family a market type belongs to, for diagnostics/UI."""
    if market_type in (MarketType.MONEYLINE, MarketType.MONEYLINE_3WAY):
        return "moneyline"
    if market_type == MarketType.HANDICAP:
        return "handicap"
    if market_type == MarketType.TOTAL:
        return "total"
    if market_type in (
        MarketType.OVER_UNDER_0_5,
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
        MarketType.OVER_UNDER_4_5,
        MarketType.OVER_UNDER_5_5,
        MarketType.FIRST_HALF_OU,
    ):
        return "total"
    return ""


def settlement_for(sport: str, market_type: MarketType) -> str:
    spec = spec_for(sport)
    if spec is None:
        return "full_time"
    if market_type == spec.moneyline:
        return spec.moneyline_settlement
    if market_type == spec.handicap:
        return spec.handicap_settlement
    if market_type == spec.total:
        return spec.total_settlement
    return "full_time"


# ---------------------------------------------------------------------------
# Non-football names
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r"[./\\\-\&'’`,()\[\]]+")
_SPORT_WORD = re.compile(
    r"^\s*(?:basketball|ko[sš]arka|tennis|tenis|ice\s*hockey|hockey|hokej)\s*[-:–]?\s*",
    re.IGNORECASE,
)
_COUNTRY_PREFIX = re.compile(r"^\s*(?:[A-Z]{2,3})\s*[-/]\s*")
_SEED = re.compile(r"\s*(?:\((?:\d+|[A-Z]{2,3})\)|\[(?:\d+|[A-Z]{2,3})\])\s*")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or "").casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain.split())


_CLUB_PREFIX = re.compile(
    r"^\s*(?:ŽKK|ZKK|KK|BC|BK|KS|KKS)\s+", re.IGNORECASE
)
# A trailing gender marker is not part of a club's name. The category is
# detected from the book's own spelling before this runs (see
# TeamNormalizer.detect_special_category), so "Alba Berlin Wom" and
# "Alba Berlin" stay separate categories while sharing a clean display name.
_GENDER_SUFFIX = re.compile(r"\s+(?:Wom|Women|W|Ž)\s*$", re.IGNORECASE)
# "Basketball"/"Basket" is the sport, not the club: MaxBet writes "TFT Skopje"
# where NSoft writes "Tft" and MBet writes "TFT Basketball Club".
_SPORT_WORD_SUFFIX = re.compile(
    r"\s+(?:Basketball|Basket|Basketbol)\s*$", re.IGNORECASE
)
_CLUB_WORD_SUFFIX = re.compile(r"\s+(?:Club|Klub)\s*$", re.IGNORECASE)


def clean_team(sport: str, name: str) -> str:
    """A display/canonical spelling for a non-football side.

    This is deliberately conservative: it removes only noise every implemented
    book adds (seed/country brackets on a tennis player, a basketball club
    designator or a trailing women's marker, surrounding spacing) and never a
    token that could distinguish two teams.  Identity is still decided by the
    certainty gate.
    """
    text = " ".join(str(name or "").split())
    if sport == TENNIS:
        text = _SEED.sub(" ", text)
        # "SRB Zverev A." / "(SRB) Zverev A.": a leading country code is not
        # part of the player's name. Only a two/three letter token is removed.
        text = re.sub(r"^\(?[A-Z]{2,3}\)?\s+", "", text)
    elif sport == BASKETBALL:
        stripped = _CLUB_PREFIX.sub("", text).strip()
        if stripped:
            text = stripped
        stripped = _CLUB_WORD_SUFFIX.sub("", text).strip()
        if stripped:
            text = stripped
        stripped = _SPORT_WORD_SUFFIX.sub("", text).strip()
        if stripped:
            text = stripped
        stripped = _GENDER_SUFFIX.sub("", text).strip()
        if stripped:
            text = stripped
    cleaned = " ".join(_PUNCT.sub(" ", text).split())
    return cleaned or text


def clean_league(sport: str, league: str) -> str:
    """A stable competition id for a non-football listing.

    Bookmakers qualify the same competition differently ("SAD - NBA", "USA
    NBA", "NBA").  The sport word and a leading country code are removed, then
    the name is folded.  The gate additionally accepts a token-containment
    match inside one sport, so a country prefix cannot hide a real competition.
    """
    text = _SPORT_WORD.sub("", str(league or "").strip())
    text = _COUNTRY_PREFIX.sub("", text)
    folded = _fold(text)
    return " ".join(_PUNCT.sub(" ", folded).split())


_LEAGUE_GENERIC = frozenset(
    {
        "league", "liga", "lig", "division", "div", "cup", "kup",
        "tournament", "open", "atp", "wta", "group", "grupa", "conference", "pool", "m",
    }
)


def league_tokens(league: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _fold(league).replace("-", " ").split()
        if token not in _LEAGUE_GENERIC
    )


def league_tokens_compatible(left: str, right: str) -> bool:
    """One competition's meaningful tokens contain the other's, in one sport.

    ``nba`` vs ``sad nba`` passes; ``nba`` vs ``wnba`` does not (``wnba`` is one
    token, not a superset of ``nba``).  An empty token set proves nothing.
    """
    left_tokens = league_tokens(left)
    right_tokens = league_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    # A division number is identity, not noise: "ABA Liga" and "ABA Liga 2"
    # are different competitions even though the latter is a token superset.
    left_numbers = {token for token in _fold(left).split() if token.isdigit()}
    right_numbers = {token for token in _fold(right).split() if token.isdigit()}
    if left_numbers != right_numbers:
        return False
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def tennis_name_match(left: str, right: str, left_tokens: list[str], right_tokens: list[str]) -> bool:
    """Surname(s) + initial identity for tennis players across books.

    ``Zverev A.`` and ``Alexander Zverev`` are the same player; two different
    Zverevs (``Zverev M.`` / ``Zverev A.``) stay apart because the initial
    differs.  Compound surnames and doubles pairs are handled by treating each
    token longer than one character as part of the surname set: ``De Minaur A.``
    matches ``Alex De Minaur`` and ``Haverlag I / Udvardy P`` matches
    ``Haverlag Udvardy``.  A single surname with no initial on either side is
    never enough.
    """
    def split(tokens: list[str]) -> tuple[set[str], set[str]]:
        surnames = {token for token in tokens if len(token) > 1}
        initials = {token for token in tokens if len(token) == 1}
        return surnames, initials

    left_surnames, left_initials = split(left_tokens)
    right_surnames, right_initials = split(right_tokens)
    if not left_surnames or not right_surnames:
        return False
    # One side may omit a sponsor/extra name token, but it may not introduce a
    # surname the other side does not have at all.
    if not (left_surnames <= right_surnames or right_surnames <= left_surnames):
        return False
    shared = left_surnames & right_surnames
    if not shared:
        return False

    if left_initials and right_initials:
        return left_initials == right_initials

    initials = left_initials or right_initials
    if not initials:
        # Both books give surnames only. Two or more shared surnames are a
        # doubles pair, which is distinctive enough; one surname is not.
        return len(shared) >= 2

    # The side that spells names in full may carry the first name as well as
    # the surname. Each initial must agree with that first name. When the full
    # side has no extra token (a doubles pair written with initials only on the
    # other side), the surname set itself has to identify more than one player.
    full_side = right_tokens if left_initials else left_tokens
    first_tokens = [
        token
        for token in full_side
        if len(token) > 1 and token not in shared
    ]
    if not first_tokens:
        return len(shared) >= 2
    return all(
        any(token.startswith(initial) for token in first_tokens)
        for initial in initials
    )
