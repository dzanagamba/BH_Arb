"""
Shared Scraper Helpers

Unified implementations of helpers previously copy-pasted across the direct-API
scrapers (MDShop, MBet, SportPlus, EVLBet, Admiralbet). Centralizing them keeps
outcome normalization and datetime parsing consistent across bookmakers.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import quote
from zoneinfo import ZoneInfo

from models.schemas import Market, MarketType, OddsValue

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from engine.market_registry import MarketRegistry, MarketSpec

# Formats accepted when parsing datetime strings.
DT_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y %H:%M",
]


BOOKMAKER_TZ = ZoneInfo("Europe/Sarajevo")


def parse_local_dt(raw) -> datetime | None:
    """Parse a kickoff a bookmaker sends in Bosnian local time, as naive UTC.

    For feeds whose timestamps carry no offset but mean Sarajevo wall-clock
    time (SportPlus: ``"2026-10-20T20:45:00"`` is 18:45 UTC in summer time).
    A value that does carry an offset, or an epoch number, is already absolute
    and is handled exactly as :func:`parse_dt` does.
    """
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        has_offset = s.endswith(("Z", "z")) or (len(s) > 6 and s[-6] in "+-" and s[-3] == ":")
        if not has_offset:
            naive = parse_dt(s)
            if naive is None:
                return None
            return naive.replace(tzinfo=BOOKMAKER_TZ).astimezone(UTC).replace(tzinfo=None)
    return parse_dt(raw)


def parse_dt(raw) -> datetime | None:
    """
    Parse a raw datetime value (ISO string or epoch timestamp) into a naive UTC
    datetime. All bookmaker scrapers agree on naive UTC for kickoff times.
    Strings carrying an explicit offset (e.g. '+02:00' or 'Z') are converted to
    UTC first instead of having the offset silently truncated.
    """
    try:
        if not raw:
            return None
        if isinstance(raw, int | float):
            ts = raw / 1000 if raw > 1e10 else raw
            return datetime.fromtimestamp(ts, tz=UTC).replace(tzinfo=None)
        if isinstance(raw, str):
            s = raw.strip()
            # Explicit Z handling — fromisoformat doesn't accept bare Z
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is not None:
                    dt = dt.astimezone(UTC).replace(tzinfo=None)
                return dt
            except ValueError as e:
                logger.debug("Failed to parse '%s' with fromisoformat: %s", raw, e)
            for fmt in DT_FORMATS:
                try:
                    return datetime.strptime(s, fmt)
                except ValueError as e:
                    logger.debug("Failed to parse '%s' with format '%s': %s", raw, fmt, e)
                    continue
            # Fallback: truncate millis/timezone suffixes (e.g. "2026-08-20T18:00:00.000")
            for fmt in DT_FORMATS:
                try:
                    truncated = s[:19]
                    return datetime.strptime(truncated, fmt[:19])
                except ValueError as e:
                    logger.debug("Failed to parse '%s' (truncated '%s') with format '%s': %s", raw, s[:19], fmt[:19], e)
                    continue
    except Exception as e:
        logger.error(f"Failed to parse datetime '{raw}': {type(e).__name__}: {e}")
    return None


def betradar_id(*values: object) -> str:
    """The Betradar match id out of a feed field ("74235704", "sr:match:74235704")."""
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text.startswith("sr:match:"):
            text = text[len("sr:match:"):]
        if text.isdigit() and int(text) > 0:
            return text
    return ""


def qualify_league(league: str, country: str) -> str:
    """A competition name qualified by its country, unless it already carries it.

    Several books send the competition and the country as separate fields and
    name the competition without the country ("Serija A" is Italy's and
    Brazil's, "1. Division" Denmark's and Norway's), so the name alone cannot
    identify a league.
    """
    league = (league or "").strip()
    country = (country or "").strip()
    if country in ("", "-"):
        return league
    if not league or league == "-":
        return country
    if country.casefold() in league.casefold():
        return league
    return f"{country} - {league}"


def parse_teams_from_name(event_name: str) -> tuple[str, str]:
    """Parse 'Girona - Castellon' or 'Girona vs Castellon' into (home, away)."""
    if not event_name:
        return "", ""
    if " - " in event_name:
        parts = event_name.split(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    if " vs " in event_name.lower():
        idx = event_name.lower().find(" vs ")
        return event_name[:idx].strip(), event_name[idx + 4:].strip()
    return event_name.strip(), ""


def ah_line_fmt(value: float) -> str:
    """Format an Asian-handicap line magnitude compactly: 0.5 → '0.5', 1.0 → '1'."""
    if value == 0:
        return "0"
    s = f"{abs(value):g}"
    return s


def ah_label(idx: str, line: float) -> str:
    """Build a canonical Asian-handicap label: home favourite line → '1 -0.5', away → '2 +0.5'."""
    if line == 0:
        return f"{idx} 0"
    sign = "-" if line < 0 else "+"
    return f"{idx} {sign}{ah_line_fmt(line)}"


def parse_ah_label(label: str) -> tuple[str, float] | None:
    """Parse '1 -0.5' / '2 +0.5' / '1 0' into (team index, signed home-line)."""
    parts = str(label).split()
    if len(parts) != 2 or parts[0] not in ("1", "2"):
        return None
    try:
        line = float(parts[1])
    except ValueError:
        return None
    return parts[0], line


def flip_ah_label(label: str) -> str:
    """Flip an Asian-handicap label for a home/away swap: '1 -0.5' → '2 -0.5'."""
    parsed = parse_ah_label(label)
    if parsed is None:
        return label
    idx, line = parsed
    return ah_label("2" if idx == "1" else "1", line)


# How far back the NSoft live window reaches. NSoft filters `getwebevents` by
# KICKOFF against dateFrom, so an in-play game is only returned when the window
# starts before it kicked off. Measured 2026-09-25 17:00 UTC: dateFrom=now
# returned {"events": []} while 35 live football events were available, and all
# 35 came back with dateFrom=now-12h — the window the committed fixtures
# tests/fixtures/markets/{mdshop,admiralbet}_live.json were captured with.
NSOFT_LIVE_LOOKBACK = timedelta(hours=12)
NSOFT_PREMATCH_HORIZON = timedelta(days=14)


def nsoft_event_window(now: datetime, live: bool) -> tuple[datetime, datetime]:
    """Return the (dateFrom, dateTo) window for an NSoft getwebevents request.

    Prematch looks forward from `now`; live looks BACK, because a game that is
    in play has already kicked off. MDShop and Admiralbet share this, so the two
    books cannot drift apart again.
    """
    if live:
        return now - NSOFT_LIVE_LOOKBACK, now
    return now, now + NSOFT_PREMATCH_HORIZON


def normalize_outcome(label: str, market_type: MarketType) -> str:
    """
    Normalize a raw outcome label to the standard format used across markets:
    '1'/'X'/'2', 'Over 2.5'/'Under 2.5', 'GG'/'NG', '1X'/'12'/'X2'.
    Recognizes English, Bosnian/Croatian/Serbian and code aliases.
    """
    raw = str(label).strip()
    raw_lower = raw.lower()

    if market_type == MarketType.MATCH_RESULT:
        if raw in ("1", "Home", "Dom"):
            return "1"
        if raw_lower in ("x", "draw", "neriješeno", "remi"):
            return "X"
        if raw in ("2", "Away", "Gost"):
            return "2"
        return raw

    if market_type in (
        MarketType.OVER_UNDER_0_5,
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
        MarketType.OVER_UNDER_4_5,
        MarketType.OVER_UNDER_5_5,
        MarketType.FIRST_HALF_OU,
    ):
        threshold = {
            MarketType.OVER_UNDER_0_5: "0.5",
            MarketType.OVER_UNDER_1_5: "1.5",
            MarketType.OVER_UNDER_2_5: "2.5",
            MarketType.OVER_UNDER_3_5: "3.5",
            MarketType.OVER_UNDER_4_5: "4.5",
            MarketType.OVER_UNDER_5_5: "5.5",
            MarketType.FIRST_HALF_OU: "",
        }[market_type]
        if market_type == MarketType.FIRST_HALF_OU:
            # First-half totals carry the line in the raw label (e.g. "Over 1.5")
            if raw_lower.startswith("over"):
                return f"Over {raw[5:].strip()}"
            if raw_lower.startswith("under"):
                return f"Under {raw[6:].strip()}"
            return raw
        if raw_lower in ("over", "više", "vise", "da", "2+", "3+", "4+"):
            return f"Over {threshold}"
        if raw_lower in ("under", "manje", "ne", "0-1", "0-2", "0-3", "01", "02", "03"):
            return f"Under {threshold}"
        return raw

    if market_type == MarketType.FIRST_HALF_1X2:
        if raw in ("1", "Home", "Dom"):
            return "1"
        if raw_lower in ("x", "draw", "neriješeno", "remi"):
            return "X"
        if raw in ("2", "Away", "Gost"):
            return "2"
        return raw

    if market_type == MarketType.ASIAN_HANDICAP:
        # Canonical labels are "1 ±line" / "2 ∓line" — built by the scrapers.
        return raw

    if market_type == MarketType.BTTS:
        if raw_lower in ("gg", "da", "yes", "gol-gol", "both"):
            return "GG"
        if raw_lower in ("ng", "ne", "no", "bez gola"):
            return "NG"
        return raw

    if market_type == MarketType.DOUBLE_CHANCE:
        upper = raw.upper()
        if upper in ("1X", "12", "X2"):
            return upper
        return raw

    return raw


# ---------------------------------------------------------------------------
# NSoft bet parsing (used by MDShop/Admiralbet-style payloads and Betole)
#
# Verified against the live NSoft catalog (2026-08): the IDs below are the ONLY
# ones that map to our supported markets. Notably:
#   - 136 is the "Ide dalje" ADVANCE/qualification market (2-way '1'/'2'),
#     present ONLY on knockout games — it must NEVER be treated as 1X2 or DC.
#   - 148/149 are half-time 1X2s ('1','X','2' on every match) — excluded.
#   - 140 = HT/FT, 153/154/174 = DNB/handicap-style 2-way, 166 = result incl.
#     "bez golova", 143/144/161/162 = half-time total variants — all excluded.
# ---------------------------------------------------------------------------

NSOFT_BET_TYPE_MAP: dict[int, MarketType] = {
    135: MarketType.MATCH_RESULT,   # 1X2 (Konačan ishod)
    152: MarketType.DOUBLE_CHANCE,  # 1X, 12, X2
    151: MarketType.BTTS,           # GG/NG
}
NSOFT_OU_BET_IDS = {137, 138}       # O/U goals, threshold in sbv

# Live in-play NSoft bet types — VERIFIED against the live catalog (2026-08).
# Live events use a DIFFERENT bet type ID space than prematch:
#   6   = "Pobednik ostatka meča" — REST-of-match winner; sbv = current score
#   18/42 = live double chance (1X/12/X2)
#   995 = "Ostatak meča - Oba daju gol" — REST-of-match BTTS; sbv = current score
#   22  = live total goals O/U (threshold in sbv: "2.5" etc.)
# 6 and 995 settle like the full-time market only from 0-0, so they are read
# only while sbv is "0-0" (registry `requires_sbv`). 28 is "Domaćin ukupno",
# the HOME team's goals, not the match total — excluded. Everything else
# (handicap 1/14/17, correct score 24, HT/FT 261, next-goal 10/30, team-goal
# counts 39/43, cards/corners 303/304, combos 11/437/1064-…) is excluded too.
NSOFT_LIVE_BET_TYPE_MAP: dict[int, MarketType] = {
    6: MarketType.MATCH_RESULT,     # rest-of-match 1X2, only at sbv 0-0
    18: MarketType.DOUBLE_CHANCE,   # live DC
    42: MarketType.DOUBLE_CHANCE,   # live DC (variant ID)
    995: MarketType.BTTS,           # rest-of-match BTTS, only at sbv 0-0
}
NSOFT_LIVE_OU_BET_IDS = {22}        # live O/U goals, threshold in sbv
# Fallback-path twin of the registry's `requires_sbv`.
NSOFT_LIVE_REQUIRED_SBV: dict[int, str] = {6: "0-0", 995: "0-0"}

# Non-football prematch bet types, measured 2026-11-04 against the live MDShop
# catalogue for each NSoft sport id. The IDs are sport-scoped: 186 is a
# basketball winner, not a football 1X2. Live non-football IDs were not proven
# (no in-play events in the measurement window), so that path refuses to guess.
NSOFT_SPORT_BET_TYPES: dict[str, dict[int, tuple[MarketType, str]]] = {
    "basketball": {
        186: (MarketType.MONEYLINE, "full_time_incl_ot"),
        191: (MarketType.HANDICAP, "regulation"),
        213: (MarketType.TOTAL, "regulation"),
    },
    "tennis": {
        1723: (MarketType.MONEYLINE, "full_match"),
        # 220 is the game handicap. 210 is a *set* handicap (±1.5 sets) and
        # was rejected by price consensus as a false game handicap.
        220: (MarketType.HANDICAP, "full_match"),
        187: (MarketType.TOTAL, "full_match"),
    },
}
NSOFT_SPORT_LABELS: dict[str, tuple[str, ...]] = {
    "basketball": ("1", "2"),
    "tennis": ("1", "2"),
}
# A book may publish a different ID for the same sport market. Only observed,
# measured overrides belong here. Admiralbet's basketball winner is 1640;
# MDShop serves 186.
NSOFT_SPORT_BET_TYPES_BY_BOOK: dict[tuple[str, str], dict[int, tuple[MarketType, str]]] = {
    ("admiralbet", "basketball"): {
        1640: (MarketType.MONEYLINE, "full_time_incl_ot"),
        191: (MarketType.HANDICAP, "regulation"),
        213: (MarketType.TOTAL, "regulation"),
    },
}

# Registry loading is lazy so importing shared scraper helpers remains cheap
# for callers that do not parse an NSoft payload.
def _nsoft_registry() -> MarketRegistry:
    from engine.market_registry import MARKET_REGISTRY

    return MARKET_REGISTRY


def _nsoft_registered_spec(
    bookmaker: str,
    mode: str,
    betid: int | str,
    sbv: float | None = None,
) -> MarketSpec | None:
    """Resolve an NSoft ``betTypeId`` through the registry.

    This is the single registry-resolution step of :func:`parse_nsoft_bets`,
    lifted to module scope so the NSoft resolution path can be exercised
    directly (see ``tests/test_registry_parser_consistency.py``) instead of
    only from inside a payload parse.  ``sbv`` is the bet's threshold: NSoft
    shares one ID pair across every Over/Under line, so the line is part of the
    lookup key.

    An ID absent from a registered mode is recorded as unmapped, exactly as the
    parser does.
    """
    from engine.market_registry import record_unmapped

    registry = _nsoft_registry()
    spec = registry.lookup(bookmaker, mode, betid, line=sbv)
    if spec is None:
        known = getattr(registry, "has_source_id", None)
        if known is None or not known(bookmaker, mode, betid):
            record_unmapped(bookmaker, betid)
    return spec


# Outcome label sets required to accept a market (defense against
# misclassified markets like "Ide dalje" leaking into 1X2).
_MARKET_LABEL_SETS: dict[MarketType, set[str]] = {
    MarketType.MATCH_RESULT: {"1", "X", "2"},
    MarketType.DOUBLE_CHANCE: {"1X", "12", "X2"},
    MarketType.BTTS: {"GG", "NG"},
    MarketType.OVER_UNDER_0_5: {"Over 0.5", "Under 0.5"},
    MarketType.OVER_UNDER_1_5: {"Over 1.5", "Under 1.5"},
    MarketType.OVER_UNDER_2_5: {"Over 2.5", "Under 2.5"},
    MarketType.OVER_UNDER_3_5: {"Over 3.5", "Under 3.5"},
    MarketType.OVER_UNDER_4_5: {"Over 4.5", "Under 4.5"},
    MarketType.OVER_UNDER_5_5: {"Over 5.5", "Under 5.5"},
}


def _score_key(raw) -> str:
    """Canonical form of a score specifier: '0:0', '0 - 0' and '0-0' agree."""
    return "".join(str(raw or "").split()).replace(":", "-")


def nsoft_offered(obj: dict) -> bool:
    """Whether an NSoft event, bet or outcome can be bet on right now.

    NSoft keeps a suspended line in the feed with its last price and marks it
    ``isPlayable: false`` (on the event, the bet or the single outcome). On
    2026-10-27 8 of 42 live match totals were suspended that way, and a suspended
    price cannot be a surebet leg. Only an explicit ``False`` counts, so a
    payload that omits the flags is read as before.
    """
    return obj.get("isPlayable") is not False and obj.get("isInOffer") is not False


def _parse_nsoft_sport_bets(
    bets: list,
    sport: str,
    *,
    bookmaker: str,
    source_context: dict[str, str] | None = None,
) -> list[Market]:
    """Parse the measured non-football NSoft bet types for one sport."""
    mapping = (
        NSOFT_SPORT_BET_TYPES_BY_BOOK.get((bookmaker, sport))
        or NSOFT_SPORT_BET_TYPES.get(sport)
    )
    if not mapping:
        return []
    labels = NSOFT_SPORT_LABELS.get(sport, ())
    markets: list[Market] = []
    for bet in bets:
        if not isinstance(bet, dict) or not nsoft_offered(bet):
            continue
        raw_id = bet.get("betTypeId")
        try:
            bet_type_id = int(str(raw_id))
        except (TypeError, ValueError):
            continue
        spec = mapping.get(bet_type_id)
        if spec is None:
            continue
        market_type, settlement = spec
        raw_sbv = bet.get("sbv") or bet.get("sBV")
        line: float | None = None
        if raw_sbv is not None:
            try:
                line = float(str(raw_sbv).replace(",", "."))
            except ValueError:
                line = None

        outcomes = bet.get("betOutcomes", [])
        picked: list[OddsValue] = []
        for outcome in outcomes:
            if not isinstance(outcome, dict) or not nsoft_offered(outcome):
                continue
            name = str(outcome.get("name") or "").strip()
            try:
                value = float(outcome.get("odd") or 0.0)
            except (TypeError, ValueError):
                continue
            if value < 1.01:
                continue
            if market_type == MarketType.MONEYLINE:
                if name in labels:
                    picked.append(OddsValue(label=name, value=value))
            elif market_type == MarketType.HANDICAP:
                if line is None or name not in ("1", "2"):
                    continue
                from scrapers.common import ah_label

                # NSoft's `sbv` on 191/220 is the home line. The 2026-11-04
                # cross-book consensus check (sportplus/maxbet) confirmed this
                # orientation; the earlier candidate reading was an outlier.
                home_line = line
                label = ah_label("1", home_line) if name == "1" else ah_label("2", -home_line)
                picked.append(OddsValue(label=label, value=value))
            elif market_type == MarketType.TOTAL:
                if line is None:
                    continue
                if name.casefold() in ("manje", "under"):
                    picked.append(OddsValue(label=f"Under {abs(line):g}", value=value))
                elif name.casefold() in ("vise", "više", "over"):
                    picked.append(OddsValue(label=f"Over {abs(line):g}", value=value))
        actual = {odd.label for odd in picked}
        if len(actual) != len(picked):
            continue
        if market_type == MarketType.MONEYLINE and actual != set(labels):
            continue
        if len(picked) < 2:
            continue
        markets.append(
            Market(
                market_type=market_type,
                odds=picked,
                source_id=str(bet_type_id),
                source_context=dict(source_context or {}),
                settlement=settlement,
            )
        )
    return markets


def parse_nsoft_bets(
    bets: list,
    extra_bet_types: dict[int, MarketType] | None = None,
    extra_ou_bet_ids: set[int] | None = None,
    base_bet_type_map: dict[int, MarketType] | None = None,
    base_ou_bet_ids: set[int] | None = None,
    bookmaker: str = "mdshop",
    mode: str = "prematch",
    base_required_sbv: dict[int, str] | None = None,
    source_context: dict[str, str] | None = None,
    sport: str = "football",
) -> list[Market]:
    """
    Parse an NSoft ``bets[]`` array into Market objects.

    Registry entries are authoritative whenever a bookmaker/mode is explicitly
    present.  The legacy maps remain a compatibility fallback for callers that
    use a synthetic bookmaker not represented in the JSON file.  An ID in a
    registered mode that is absent from that mode is recorded rather than
    silently discarded.

    A market is accepted only when its normalized outcome labels satisfy the
    registry's ``min_legs`` rule and no label falls outside the registered set.
    This is the defense that keeps an NSoft 2-way "Ide dalje" market out of the
    1X2 pool.

    A spec with ``requires_sbv`` (or, on the fallback path, an entry in
    ``base_required_sbv``) is read only while the bet's specifier equals it:
    NSoft's live rest-of-match markets match the full-time ones only at 0-0.
    """
    registry = _nsoft_registry()
    if sport != "football":
        # Non-football IDs are sport-scoped and only prematch is proven. A live
        # non-football ID space has not been observed, so refuse rather than
        # relabel a live market as a full-time one.
        if mode == "live":
            return []
        return _parse_nsoft_sport_bets(
            bets, sport, bookmaker=bookmaker, source_context=source_context
        )
    has_mode = getattr(registry, "has_mode", None)
    has_registry = (
        has_mode(bookmaker, mode)
        if has_mode is not None
        else bool(registry.ids_for(bookmaker, mode, MarketType.MATCH_RESULT))
    )
    bet_type_map = {
        **(base_bet_type_map or NSOFT_BET_TYPE_MAP),
        **(extra_bet_types or {}),
    }
    ou_bet_ids = (
        (base_ou_bet_ids if base_ou_bet_ids is not None else NSOFT_OU_BET_IDS)
        | (extra_ou_bet_ids or set())
    )
    required_sbv_map = base_required_sbv or {}
    markets: list[Market] = []
    for bet in bets:
        if not isinstance(bet, dict):
            continue
        btid = bet.get("betTypeId")
        if btid is None or not nsoft_offered(bet):
            continue
        raw_sbv = bet.get("sbv") or bet.get("sBV")
        sbv_val = None
        if raw_sbv is not None:
            try:
                sbv_val = float(raw_sbv)
            except (ValueError, TypeError):
                pass

        market_type: MarketType | None = None
        expected_labels: set[str] = set()
        required_line: float | None = None
        required_legs = 3

        if has_registry:
            spec = _nsoft_registered_spec(bookmaker, mode, btid, sbv_val)
            if spec is None:
                continue
            market_type = spec.market_type
            expected_labels = set(spec.labels)
            required_line = spec.line
            required_legs = spec.min_legs
            if spec.requires_sbv is not None and (
                _score_key(raw_sbv) != _score_key(spec.requires_sbv)
            ):
                continue
            if required_line is not None and (
                sbv_val is None or abs(required_line - sbv_val) > 1e-9
            ):
                continue
        else:
            market_type = bet_type_map.get(btid)
            if market_type is None and btid in ou_bet_ids and sbv_val is not None:
                market_type = {
                    0.5: MarketType.OVER_UNDER_0_5,
                    1.5: MarketType.OVER_UNDER_1_5,
                    2.5: MarketType.OVER_UNDER_2_5,
                    3.5: MarketType.OVER_UNDER_3_5,
                    4.5: MarketType.OVER_UNDER_4_5,
                    5.5: MarketType.OVER_UNDER_5_5,
                }.get(sbv_val)
            if market_type is None:
                continue
            required_sbv = required_sbv_map.get(btid)
            if required_sbv is not None and _score_key(raw_sbv) != _score_key(required_sbv):
                continue
            expected_labels = _MARKET_LABEL_SETS.get(market_type, set())
            required_legs = 2 if market_type == MarketType.DOUBLE_CHANCE else len(expected_labels)

        outcomes = bet.get("betOutcomes", [])
        if not outcomes:
            continue
        odds_values: list[OddsValue] = []
        outcome_ids: dict[str, str] = {}
        for outcome in outcomes:
            if not isinstance(outcome, dict) or not nsoft_offered(outcome):
                continue
            lbl = str(outcome.get("name") or outcome.get("outcomeName") or "")
            odd_raw = outcome.get("odd") or outcome.get("odds") or outcome.get("value")
            if not lbl:
                continue
            try:
                odd_val = float(odd_raw) if odd_raw is not None else 0.0
            except (ValueError, TypeError):
                continue
            if odd_val < 1.01:
                continue
            norm_label = normalize_outcome(lbl, market_type)
            if norm_label in expected_labels:
                odds_values.append(OddsValue(label=norm_label, value=odd_val))
                raw_outcome_id = outcome.get("id")
                if raw_outcome_id is not None:
                    outcome_ids[norm_label] = str(raw_outcome_id)

        actual = {o.label for o in odds_values}
        valid = len(actual) >= required_legs and actual.issubset(expected_labels)
        if valid:
            context = dict(source_context or {})
            raw_bet_id = bet.get("id")
            if raw_bet_id is not None:
                context["bet_id"] = str(raw_bet_id)
            markets.append(
                Market(
                    market_type=market_type,
                    odds=odds_values,
                    source_id=str(btid),
                    source_context=context,
                    outcome_ids=outcome_ids,
                )
            )
    return markets


def parse_nsoft_live_bets(
    bets: list,
    bookmaker: str = "mdshop",
    source_context: dict[str, str] | None = None,
) -> list[Market]:
    """
    Parse an in-play NSoft ``bets[]`` array (live ID space).

    Live matches use the registry's live IDs.  The legacy live maps are passed
    as a fallback for synthetic/unregistered callers, and the same strict
    label-set validation is applied in either path.
    """
    return parse_nsoft_bets(
        bets,
        base_bet_type_map=NSOFT_LIVE_BET_TYPE_MAP,
        base_ou_bet_ids=NSOFT_LIVE_OU_BET_IDS,
        base_required_sbv=NSOFT_LIVE_REQUIRED_SBV,
        bookmaker=bookmaker,
        mode="live",
        source_context=source_context,
    )


_DEEPLINK_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_deeplinks.json")
_deeplink_cache: dict | None = None
# The file signature the cached map was loaded from. A cache injected directly
# by a test has no loaded_at, and is treated as an explicit override rather than
# something the file is allowed to overwrite.
_DeeplinkSignature = tuple[int, int]
_deeplink_cache_signature: _DeeplinkSignature | None = None
_deeplink_source_mtime: float | None = None
_deeplink_loaded_at: datetime | None = None
_deeplink_load_error: str | None = None


def _deeplink_file_signature() -> tuple[_DeeplinkSignature | None, float | None]:
    """Return ((mtime_ns, size), mtime_seconds) for the declaration file.

    A missing/unreadable file has no signature. That is different from a file
    that is present but empty: the first is a config that cannot be trusted, the
    second is a valid (if useless) declaration map.
    """
    try:
        stat = os.stat(_DEEPLINK_CONFIG_PATH)
    except OSError:
        return None, None
    return (stat.st_mtime_ns, stat.st_size), stat.st_mtime


def _reload_deeplink_config(
    signature: _DeeplinkSignature | None,
    mtime: float | None,
) -> None:
    """Read the declaration file and replace the cache, failing safe on error."""
    global _deeplink_cache, _deeplink_cache_signature
    global _deeplink_source_mtime, _deeplink_loaded_at, _deeplink_load_error
    data: dict = {}
    error: str | None = None
    try:
        with open(_DEEPLINK_CONFIG_PATH, encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("declaration file must contain a JSON object")
        data = loaded
    except (OSError, ValueError) as exc:
        # A malformed or missing file grants no declarations. That is the safe
        # direction: every book blocks until the file is fixed, rather than
        # continuing to trust a map that no longer matches the file.
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("Deep-link declaration config could not be loaded: %s", error)
    _deeplink_cache = data
    _deeplink_cache_signature = signature
    _deeplink_source_mtime = mtime
    _deeplink_loaded_at = datetime.now(UTC)
    _deeplink_load_error = error


def _load_deeplink_config() -> dict:
    """Return the declaration map, reloading when the file signature changes.

    The file is read only on first use and when its mtime/size changes, so a
    declaration edit takes effect on the next gate lookup or health call without
    a process restart. A map injected directly (no ``loaded_at``) is left alone;
    that is the seam tests use to exercise a synthetic declaration set.
    """
    global _deeplink_cache
    signature, mtime = _deeplink_file_signature()
    if _deeplink_cache is None or (
        _deeplink_loaded_at is not None and signature != _deeplink_cache_signature
    ):
        _reload_deeplink_config(signature, mtime)
    return _deeplink_cache if _deeplink_cache is not None else {}


def deeplink_declaration_source() -> dict:
    """Describe the declaration file the gate is currently reading.

    ``stale`` means the loaded map is not the map on disk: the file changed
    since the last successful read, the last read failed, or no file could be
    read at all. ``loaded_at`` and ``source_mtime`` make a restart-free edit
    observable in `/api/health`.
    """
    _load_deeplink_config()
    current_signature, current_mtime = _deeplink_file_signature()
    stale = _deeplink_load_error is not None or current_signature != _deeplink_cache_signature
    return {
        "path": os.path.abspath(_DEEPLINK_CONFIG_PATH),
        "loaded_at": _deeplink_loaded_at.isoformat() if _deeplink_loaded_at else None,
        "source_mtime": _deeplink_source_mtime,
        "current_mtime": current_mtime,
        "source_size": _deeplink_cache_signature[1] if _deeplink_cache_signature else None,
        "stale": stale,
        "error": _deeplink_load_error,
    }


def _declared_config(bookmaker: str) -> dict:
    """Return a bookmaker's declaration, or an empty mapping when it is absent."""
    value = _load_deeplink_config().get(bookmaker)
    return value if isinstance(value, dict) else {}


def declares_route_pattern_verified(bookmaker: str) -> bool:
    """Whether the book's per-event route pattern has a dated browser proof.

    The route embeds the book's own event id. A sampled browser check proves the
    pattern serves the event for that id; the feed then supplies the id for every
    listing. This is the industry norm for path-based bookmaker routes and is
    recorded with a date and a sample in ``config/bookmaker_deeplinks.json``.
    """
    return _declared_config(bookmaker).get("route_pattern_verified") is True


def supports_event_id(bookmaker: str) -> bool:
    """Return whether a bookmaker declares a per-event deep-link route.

    A book that declares ``supports_event_id: false`` has no per-event route by
    definition, so a link check for it is meaningless: it must be reported as
    "no declared event route", never as a failure. Undeclared books are treated
    the same way — the route is unknown, which is not the same as proven.
    """
    return _declared_config(bookmaker).get("supports_event_id") is True


def declares_no_event_id(bookmaker: str) -> bool:
    """Return whether a bookmaker explicitly declares ``supports_event_id: false``.

    Only the boolean ``False`` counts, and that strictness is the point: the
    certainty gate accepts this declaration as proof that there is no per-event
    link to prove, so a missing key, a typo, a quoted ``"false"`` or a config file
    that failed to load must all answer False here and leave the book blocking.
    ``supports_event_id`` cannot be used for the question — it answers False for
    a declaration that is absent, which is the opposite of what the gate needs to
    tell apart.
    """
    return _declared_config(bookmaker).get("supports_event_id") is False


def effective_deeplink_declarations(bookmakers: Iterable[str] | None = None) -> dict:
    """Return the declaration each book's link question is actually answered by.

    Built from the same cached config the certainty gate reads, so it reports
    what the gate is *using* rather than what the file on disk says. A file edit
    is picked up when its mtime/size changes, and the ``stale``/``loaded_at``
    fields say whether the map in force still matches the file.

    ``bookmakers`` defaults to the keys of the loaded config. A book the config
    holds but the caller did not ask about is added anyway: a caller that names
    some books and silently loses a configured one is the mistake worth surfacing.

    Each entry carries the declaration fields plus the provenance of the file
    the map came from:

    * ``loaded_at`` — when the current map was read (ISO UTC, or ``None`` for a
      synthetic map injected without a file load).
    * ``source_mtime`` — the declaration file's mtime at that read, in epoch
      seconds.
    * ``stale`` — whether the map in force differs from the file on disk (the
      file changed, or the last read failed). A stale map is still the map the
      gate uses; the flag makes the restart-free reload visible.
    * ``configured`` — whether the config holds a declaration for this book at
      all. It is the only field that can distinguish "declares no per-event
      route" from "declares nothing", and those two land on opposite sides of the
      gate.
    * ``supports_event_id`` — the declared boolean, or ``None`` when the book is
      unconfigured or its value is not a boolean. This is the same answer
      :func:`supports_event_id` gives, spelled so ``false`` survives.
    * ``declared_no_event_id`` — the gate's own predicate, and the field to read
      for anything about what blocks. ``None`` is deliberately not available here:
      a book that declares neither value answers False and still blocks, so this
      field is a real two-state answer.

    A caller wanting a plain ``{book: bool}`` map should read
    ``supports_event_id`` out of this; a caller asking what can still block must
    read ``declared_no_event_id``, because the two disagree for every book that
    declares nothing.
    """
    config = _load_deeplink_config()
    source = deeplink_declaration_source()
    names = list(bookmakers) if bookmakers is not None else list(config)
    for name in config:
        if name not in names:
            names.append(name)
    result: dict = {}
    for name in names:
        declared = config.get(name)
        raw = declared.get("supports_event_id") if isinstance(declared, dict) else None
        result[name] = {
            "loaded_at": source["loaded_at"],
            "source_mtime": source["source_mtime"],
            "stale": source["stale"],
            "configured": isinstance(declared, dict),
            # `isinstance(raw, bool)` and not `raw is True`, because the
            # declared-false case has to come back as False: mapping it to None
            # would report a book that plainly says `false` as one that says
            # nothing, which is the one distinction this map exists to make.
            "supports_event_id": raw if isinstance(raw, bool) else None,
            "declared_no_event_id": raw is False,
        }
    return result


def _base_url(base_url: str) -> str:
    """Return a normalized non-event URL for a book's base site."""
    return f"{base_url.rstrip('/')}/"


def _fallback_url(bookmaker: str, base_url: str) -> str:
    """Return the declared non-event fallback, or the normalized site base."""
    cfg = _declared_config(bookmaker)
    fallback = cfg.get("fallback")
    return fallback if isinstance(fallback, str) and fallback else _base_url(base_url)


def _event_template(bookmaker: str, live: bool) -> str:
    """Return the event template for a mode, or an empty string when none exists."""
    cfg = _declared_config(bookmaker)
    key = "template_live" if live else "template"
    template = cfg.get(key)
    if template is None and live:
        return ""
    if not isinstance(template, str) or not template:
        raise ValueError(f"Deep-link config for {bookmaker} is missing {key}")
    if "{event_id}" not in template:
        raise ValueError(
            f"Deep-link config for {bookmaker} must contain an event_id placeholder"
        )
    return template


def build_event_url(
    bookmaker: str,
    event_id: str | None,
    base_url: str,
    live: bool = False,
) -> str:
    """Build a declared per-event URL, or a non-event fallback when unavailable."""
    cfg = _declared_config(bookmaker)
    normalized_event_id = "" if event_id is None else str(event_id)
    if not cfg.get("supports_event_id"):
        template = (cfg.get("template_live") if live else None) or cfg.get("template")
        return template if isinstance(template, str) and template else _base_url(base_url)
    if not normalized_event_id:
        return _fallback_url(bookmaker, base_url)

    template = _event_template(bookmaker, live)
    if not template:
        return _fallback_url(bookmaker, base_url)
    encoded_event_id = quote(normalized_event_id, safe="")
    try:
        return template.format(event_id=encoded_event_id)
    except (IndexError, KeyError, ValueError) as exc:
        raise ValueError(
            f"Invalid deep-link template for {bookmaker}: {template!r}"
        ) from exc
