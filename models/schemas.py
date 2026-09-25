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


class OddsValue(BaseModel):
    """Single named odds value."""
    label: str          # e.g., "1", "X", "2", "Over 2.5", "Under 2.5", "GG", "NG"
    value: float        # Decimal odds, e.g., 1.85


class Market(BaseModel):
    """A single betting market with its odds."""
    market_type: MarketType
    odds: list[OddsValue]


class Match(BaseModel):
    """A match scraped from a single bookmaker."""
    bookmaker: str
    home_team: str
    away_team: str
    home_team_normalized: str = ""
    away_team_normalized: str = ""
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
    deep_link_verified: bool = False
    category_tags: list[str] = []
    low_confidence: bool = False
    is_swapped: bool = False
    is_live: bool = False
    fetched_at: datetime | None = None  # naive UTC wall-clock when odds were fetched (P0-1)

    def has_markets(self) -> bool:
        return len(self.markets) > 0


MatchEventStatus = Literal["verified", "suggested", "rejected"]


class MatchEvidence(BaseModel):
    """One reason why a match group was grouped, or why a candidate was rejected."""
    rule: str
    source: Literal["rule", "ai", "human", "allowlist"]
    confidence: float = 0.0
    reason: str = ""
    league_pair: list[str] = []
    kickoff_delta_minutes: float | None = None
    allowlist_entries: list[str] = []


class CandidateReview(BaseModel):
    """An ambiguous pairing awaiting human/AI resolution."""
    id: str
    home_team: str
    away_team: str
    league: str
    kickoff: datetime | None = None
    bookmakers: list[str] = []
    ai_confidence: float = 0.0
    ai_reason: str = ""
    rule_rejections: list[str] = []
    status: Literal["pending", "approved", "rejected"] = "pending"
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str = ""


class MatchGroup(BaseModel):
    """Same real-world match found across multiple bookmakers."""
    canonical_home: str
    canonical_away: str
    league: str = ""
    kickoff: datetime | None = None
    matches: list[Match] = []
    status: MatchEventStatus = "suggested"
    evidence: list[MatchEvidence] = []


class SurebetStake(BaseModel):
    """Optimal stake for one outcome of a surebet."""
    bookmaker: str
    outcome_label: str
    odds: float
    stake: float
    potential_return: float


class Surebet(BaseModel):
    """A detected arbitrage opportunity."""
    id: str
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
