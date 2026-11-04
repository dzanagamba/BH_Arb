from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class MarketType(str, Enum):
    MATCH_RESULT = "1x2"
    OVER_UNDER_1_5 = "over_under_1_5"
    OVER_UNDER_2_5 = "over_under_2_5"
    OVER_UNDER_3_5 = "over_under_3_5"
    BTTS = "btts"
    DOUBLE_CHANCE = "double_chance"
    FIRST_HALF_1X2 = "first_half_1x2"
    FIRST_HALF_OU = "first_half_ou"
    ASIAN_HANDICAP = "asian_handicap"
    # Extra football total lines admitted from measured cross-book offers.
    OVER_UNDER_0_5 = "over_under_0_5"
    OVER_UNDER_4_5 = "over_under_4_5"
    OVER_UNDER_5_5 = "over_under_5_5"
    # Non-football families. The sport lives on Match/Surebet, so one family
    # name can mean "points" in basketball and "games" in tennis without ever
    # crossing sports: sport identity is a hard gate.
    MONEYLINE = "moneyline"          # two-way winner: "1" / "2"
    MONEYLINE_3WAY = "moneyline_3way"  # three-way winner: "1" / "X" / "2"
    HANDICAP = "handicap"            # line-embedded: "1 -4.5" / "2 +4.5"
    TOTAL = "total"                  # line-embedded: "Over 221.5" / "Under 221.5"


class Sport(str, Enum):
    """Canonical sport identity. The value is persisted in the cache and API."""

    FOOTBALL = "football"
    BASKETBALL = "basketball"
    TENNIS = "tennis"
    ICE_HOCKEY = "ice_hockey"


class OddsValue(BaseModel):
    """Single named odds value."""
    label: str          # e.g., "1", "X", "2", "Over 2.5", "Under 2.5", "GG", "NG"
    value: float        # Decimal odds, e.g., 1.85


class Market(BaseModel):
    """A single betting market with its odds."""
    market_type: MarketType
    odds: list[OddsValue]
    # The book's own source id when the parser knows it. Additive: the registry
    # and the generated-market path use it to attribute a discovered mapping.
    source_id: str = ""
    # Book-specific identifiers needed to build a ticket-prefill URL without a
    # second request. NSoft (MDShop/Admiralbet) needs sport/region/competition
    # and bet ids; other books leave this empty.
    source_context: dict[str, str] = {}
    # Canonical outcome label -> the book's own outcome id. Only a parser that
    # read the id from the payload fills this; it is never guessed.
    outcome_ids: dict[str, str] = {}
    # What the market settles on. Two markets may only be paired when these
    # match: "full_time" (football), "full_time_incl_ot" (basketball winner),
    # "regulation" (basketball handicap/total, hockey 60 minutes), "full_match"
    # (tennis). A mismatch is not a naming difference; it is a different bet.
    settlement: str = "full_time"
    period: str = "full_time"


class RawOffer(BaseModel):
    """A bookmaker's market before its meaning is resolved.

    New book adapters emit these instead of choosing a ``MarketType`` by hand.
    The discovery layer classifies them from labels, structure and cross-book
    price consensus, and records the provenance of the result.
    """

    bookmaker: str
    mode: str = "prematch"
    event_key: str = ""
    market_key: str = ""
    source_id: str = ""
    labels: list[str] = []
    line: float | None = None
    period: str = "full_time"
    odds: list[OddsValue] = []
    raw_payload_hash: str = ""


class Match(BaseModel):
    """A match scraped from a single bookmaker."""
    bookmaker: str
    # Hard identity key. A football listing and a basketball listing can never
    # share a match group, whatever their names look like.
    sport: str = "football"
    home_team: str
    away_team: str
    home_team_normalized: str = ""
    away_team_normalized: str = ""
    # The book's own spelling, kept when canonicalization rewrote home_team /
    # away_team ("U21/Millwall" -> "Millwall U21"); the bet slip shows it,
    # since it is what the book's search finds. Empty when nothing changed.
    home_team_source: str = ""
    away_team_source: str = ""
    league: str = ""
    league_normalized: str = ""
    country: str = ""
    country_normalized: str = ""
    kickoff: datetime | None = None
    markets: list[Market] = []
    url: str = ""
    bet_url: str = ""  # deep link that prefills a new bet slip/ticket for this match
    match_code: str = ""
    event_id: str = ""
    # Betradar match id, when the book's feed carries one. Books on the same id
    # list the same real match, whatever they call the teams.
    betradar_id: str = ""
    # Book-specific event context used only to build a destination URL (region,
    # competition and the book's own event name). Never used for identity.
    source_context: dict[str, str] = {}
    deep_link_verified: bool = False
    category_tags: list[str] = []
    is_swapped: bool = False
    is_live: bool = False
    fetched_at: datetime | None = None  # naive UTC wall-clock when odds were fetched (P0-1)

    def has_markets(self) -> bool:
        return len(self.markets) > 0


MatchEventStatus = Literal["verified", "suggested", "rejected"]


class MatchEvidence(BaseModel):
    """One reason why a match group was grouped, or why a candidate was rejected."""
    rule: str
    source: Literal["rule", "ai", "human", "allowlist", "ledger"]
    confidence: float = 0.0
    reason: str = ""
    league_pair: list[str] = []
    kickoff_delta_minutes: float | None = None
    allowlist_entries: list[str] = []
    evidence_keys: list[str] = []


class PairSide(BaseModel):
    """One bookmaker's raw claim inside a candidate pair.

    A candidate exists because two books disagree about the same fixture, so a
    reviewable claim has to carry BOTH sides. One side alone cannot be turned
    into a team alias — that would alias a club against its own opponent.
    """

    bookmaker: str
    event_ref: str = ""
    home_team: str
    away_team: str
    link_verified: bool = False


class TeamPositionPair(BaseModel):
    """One team slot as the two bookmakers spell it, in the agreed orientation.

    ``team_a``/``team_b`` are the two raw names of the SAME club, which is what
    a reviewed allowlist entry is made of. The orientation is decided once, when
    the candidate is built, so approval never has to re-derive it.
    """

    position: Literal["home", "away"]
    team_a: str
    team_b: str


class CandidateReview(BaseModel):
    """An ambiguous pairing awaiting human/AI resolution."""
    id: str
    home_team: str
    away_team: str
    league: str
    kickoff: datetime | None = None
    bookmakers: list[str] = []
    # The cross-bookmaker claim. `home_team`/`away_team` above stay for display
    # (side A's fixture); approval reads the positions, never those two fields.
    side_a: PairSide | None = None
    side_b: PairSide | None = None
    team_positions: list[TeamPositionPair] = []
    # True when the certainty gate answers `verified` for this pair once the
    # aliases implied by team_positions are granted and both links are proven —
    # measured with `_what_if_gate`, configured exactly as the gate the scan
    # decides with, so the answer is the verdict the reviewer will actually get.
    # A kickoff, a league or a name pair no alias can carry is not something an
    # approval clears, and leaves this False.
    alias_actionable: bool = False
    # True when the gate refused partly because a deep link is unproven. That is
    # a system check, so an approval cannot clear it.
    link_blocked: bool = False
    ai_confidence: float = 0.0
    ai_reason: str = ""
    ai_same_event: bool | None = None
    rule_rejections: list[str] = []
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str = ""


class MatchGroup(BaseModel):
    """Same real-world match found across multiple bookmakers."""
    canonical_home: str
    canonical_away: str
    sport: str = "football"
    league: str = ""
    kickoff: datetime | None = None
    matches: list[Match] = []
    status: MatchEventStatus = "suggested"
    evidence: list[MatchEvidence] = []


class LegDestination(BaseModel):
    """Where a surebet leg can actually be reached, and what the link really does.

    ``kind`` is the honest rung of the ladder: a populated ticket, a match page,
    a search, or a competition page. It is never inferred from the presence of a
    URL; ``engine.destinations`` only returns ``ticket_filled`` or ``match_page``
    when the dated spot check in ``config/bookmaker_destinations.json`` proves
    the fixture (and, for a ticket, the populated selection).
    """
    kind: Literal["ticket_filled", "match_page", "search", "competition"]
    label: str
    url: str = ""
    search_text: str = ""
    identifier: str = ""
    identifier_source: str = ""
    selection: str = ""
    line: str = ""
    market: str = ""
    proof_checked_at: str = ""
    proof_summary: str = ""
    fallback_reason: str = ""
    ticket_stake_supported: bool = False
    # SportPlus keeps its ticket in localStorage, not in a URL. This is a
    # copyable, manual prefill script (not a link) and is labelled as such.
    ticket_script: str = ""
    ticket_script_label: str = ""


class SurebetStake(BaseModel):
    """Optimal stake for one outcome of a surebet."""
    bookmaker: str
    outcome_label: str
    odds: float
    stake: float
    potential_return: float
    market_type: str = ""
    selection: str = ""
    line: str = ""
    # When this leg's price was collected (naive UTC). The freshness block on
    # /api/results is summarised per book; this keeps the age attached to the
    # exact leg a reviewer is about to place.
    fetched_at: datetime | None = None
    destination: LegDestination | None = None


class Surebet(BaseModel):
    """A detected arbitrage opportunity."""
    id: str
    sport: str = "football"
    home_team: str
    away_team: str
    league: str = ""
    kickoff: datetime | None = None
    market_type: MarketType
    profit_percent: float
    total_margin: float
    stakes: list[SurebetStake]
    match_urls: dict[str, str] = {}  # bookmaker -> match page URL
    bet_urls: dict[str, str] = {}  # bookmaker -> bet-slip prefill URL (empty when unsupported)
    # How each book in the group lists the fixture, so the operator can find it
    # on a site that has no per-event page: bookmaker -> {home, away, league, kickoff}.
    listings: dict[str, dict[str, str]] = {}
    # Why the certainty gate trusts that every leg is the same match, in words.
    evidence: list[str] = []
    odds_fetched_at: datetime | None = None  # oldest leg's fetch time (naive UTC)
    found_at: datetime


class ScanStatus(BaseModel):
    """Current status of the scanning process."""
    mode: str = "prematch"  # 'prematch' | 'live'
    is_scanning: bool = False
    current_bookmaker: str = ""
    bookmakers_done: list[str] = []
    bookmaker_progress: dict[str, str] = {}  # bookmaker_id -> scraping|done|error|skipped
    total_matches: int = 0
    surebets_found: int = 0
    errors: list[str] = []
    last_scan_time: datetime | None = None
