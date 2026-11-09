"""
Shared Scraper Helpers

Unified implementations of helpers previously copy-pasted across the direct-API
scrapers (MDShop, MBet, SportPlus, EVLBet, Admiralbet). Centralizing them keeps
outcome normalization and datetime parsing consistent across bookmakers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from engine.ah_labels import ah_label as ah_label
from engine.ah_labels import ah_line_fmt as ah_line_fmt
from engine.ah_labels import flip_ah_label as flip_ah_label
from engine.ah_labels import parse_ah_label as parse_ah_label
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
    from engine.market_registry import registry

    return registry()


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
        seen_labels: set[str] = set()
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
            # SR4-7a: the feed normally sends one row per outcome, but a
            # duplicated row must not become two legs for this book. The first
            # offered price wins; later duplicates are ignored.
            if norm_label in expected_labels and norm_label not in seen_labels:
                seen_labels.add(norm_label)
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
