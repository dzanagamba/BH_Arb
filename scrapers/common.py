"""
Shared Scraper Helpers

Unified implementations of helpers previously copy-pasted across the direct-API
scrapers (MDShop, MBet, SportPlus, EVLBet, Admiralbet). Centralizing them keeps
outcome normalization and datetime parsing consistent across bookmakers.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import quote

from models.schemas import Market, MarketType, OddsValue

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


def parse_dt(raw) -> datetime | None:
    """
    Parse a raw datetime value (ISO string or epoch timestamp) into a naive UTC
    datetime. All bookmaker scrapers agree on naive UTC for kickoff times.
    Strings carrying an explicit offset (e.g. '+02:00' or 'Z') are converted to
    UTC first instead of having the offset silently truncated.
    """
    if not raw:
        return None
    try:
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
            except ValueError:
                pass
            for fmt in DT_FORMATS:
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue
            # Fallback: truncate millis/timezone suffixes (e.g. "2026-08-20T18:00:00.000")
            for fmt in DT_FORMATS:
                try:
                    return datetime.strptime(s[:19], fmt[:19])
                except ValueError:
                    continue
    except Exception:
        pass
    return None


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


def get_active_odds_value(entry) -> float | None:
    """Return float odds if entry is active/not suspended, else None (P0-2 unified guard).

    Checks common suspend signals across providers:
      - market_status != ACTIVE / oddtype_status !=1 (MBet/Alea)
      - isv ==0 (WWIN)
      - naPon !=1 (Premier)
      - value <1.01 (all)
    Accepts dict {value, market_status, ...} or bare float/str.
    """
    if entry is None:
        return None
    if isinstance(entry, dict):
        # WWIN-style isv
        if entry.get("isv") == 0:
            return None
        # Premier naPon
        if "naPon" in entry and entry.get("naPon") != 1:
            return None
        # MBet Alea market_status / oddtype_status
        if entry.get("market_status") is not None and entry.get("market_status") != "ACTIVE":
            return None
        if entry.get("oddtype_status") is not None and entry.get("oddtype_status") != 1:
            return None
        # Generic suspended/active flags
        if entry.get("suspended") is True or entry.get("active") is False:
            return None
        val = entry.get("value", entry.get("va", entry.get("odd", entry.get("odds", entry.get("koef")))))
    else:
        val = entry
    try:
        f = float(val) if val is not None else 0.0
        return f if f >= 1.01 else None
    except (ValueError, TypeError):
        return None


def nsoft_event_url(site_base: str, event_id: str, live: bool = False) -> str:
    """Deep link to a single event in an NSoft mbase sports shell (MDShop/Admiralbet).

    Both shells render the NSoft product inside an iframe and forward the
    URL query params they recognize: `event` is mapped to `eventId` for the
    product iframe and `ticketItems`/`fastTicket` prefill the bet slip —
    verified in the shell's checkQueryParams() (chunk-EDF2MGFW / chunk-PD2MVGCC).
    The `ticketItems` value format is undocumented, so only event links are
    built here. Falls back to the plain sport page when no event id is known.
    """
    route = "sport-live" if live else "sport-prematch"
    if not event_id:
        return f"{site_base}/{route}?sport=Fudbal" if not live else f"{site_base}/{route}"
    if live:
        return f"{site_base}/{route}?event={event_id}"
    return f"{site_base}/{route}?sport=Fudbal&event={event_id}"


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
        MarketType.OVER_UNDER_1_5,
        MarketType.OVER_UNDER_2_5,
        MarketType.OVER_UNDER_3_5,
        MarketType.FIRST_HALF_OU,
    ):
        threshold = {
            MarketType.OVER_UNDER_1_5: "1.5",
            MarketType.OVER_UNDER_2_5: "2.5",
            MarketType.OVER_UNDER_3_5: "3.5",
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
#   6   = live 1X2 (sbv carries the current score specifier, e.g. "0:0")
#   18/42 = live double chance (1X/12/X2)
#   995 = live BTTS (GG/NG)
#   22/28 = live total goals O/U (threshold in sbv: "2.5" etc.)
# Everything else (handicap 1/14/17, correct score 24, HT/FT 261, next-goal
# 10/30, team-goal counts 39/43, cards/corners 303/304, combos 11/437/1064-…)
# is deliberately excluded.
NSOFT_LIVE_BET_TYPE_MAP: dict[int, MarketType] = {
    6: MarketType.MATCH_RESULT,     # live 1X2, sbv = current score
    18: MarketType.DOUBLE_CHANCE,   # live DC
    42: MarketType.DOUBLE_CHANCE,   # live DC (variant ID)
    995: MarketType.BTTS,           # live BTTS
}
NSOFT_LIVE_OU_BET_IDS = {22, 28}    # live O/U goals, threshold in sbv

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
    MarketType.OVER_UNDER_1_5: {"Over 1.5", "Under 1.5"},
    MarketType.OVER_UNDER_2_5: {"Over 2.5", "Under 2.5"},
    MarketType.OVER_UNDER_3_5: {"Over 3.5", "Under 3.5"},
}


def resolve_nsoft_market_type(btid: int, sbv: float | None) -> MarketType | None:
    """Resolve an NSoft betTypeId + optional sbv threshold to a MarketType."""
    mt = NSOFT_BET_TYPE_MAP.get(btid)
    if mt is not None:
        return mt
    if btid in NSOFT_OU_BET_IDS and sbv is not None:
        if sbv == 1.5:
            return MarketType.OVER_UNDER_1_5
        if sbv == 2.5:
            return MarketType.OVER_UNDER_2_5
        if sbv == 3.5:
            return MarketType.OVER_UNDER_3_5
    return None


def parse_nsoft_bets(
    bets: list,
    extra_bet_types: dict[int, MarketType] | None = None,
    extra_ou_bet_ids: set[int] | None = None,
    base_bet_type_map: dict[int, MarketType] | None = None,
    base_ou_bet_ids: set[int] | None = None,
    bookmaker: str = "mdshop",
    mode: str = "prematch",
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
    """
    registry = _nsoft_registry()
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
    markets: list[Market] = []
    for bet in bets:
        if not isinstance(bet, dict):
            continue
        btid = bet.get("betTypeId")
        if btid is None:
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
            if required_line is not None and (
                sbv_val is None or abs(required_line - sbv_val) > 1e-9
            ):
                continue
        else:
            market_type = bet_type_map.get(btid)
            if market_type is None and btid in ou_bet_ids and sbv_val is not None:
                market_type = {
                    1.5: MarketType.OVER_UNDER_1_5,
                    2.5: MarketType.OVER_UNDER_2_5,
                    3.5: MarketType.OVER_UNDER_3_5,
                }.get(sbv_val)
            if market_type is None:
                continue
            expected_labels = _MARKET_LABEL_SETS.get(market_type, set())
            required_legs = 2 if market_type == MarketType.DOUBLE_CHANCE else len(expected_labels)

        outcomes = bet.get("betOutcomes", [])
        if not outcomes:
            continue
        odds_values: list[OddsValue] = []
        for outcome in outcomes:
            if not isinstance(outcome, dict):
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

        actual = {o.label for o in odds_values}
        valid = len(actual) >= required_legs and actual.issubset(expected_labels)
        if valid:
            markets.append(Market(market_type=market_type, odds=odds_values))
    return markets


def parse_nsoft_live_bets(
    bets: list,
    bookmaker: str = "mdshop",
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
        bookmaker=bookmaker,
        mode="live",
    )


_DEEPLINK_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "bookmaker_deeplinks.json")
_deeplink_cache: dict | None = None


def _load_deeplink_config() -> dict:
    global _deeplink_cache
    if _deeplink_cache is None:
        try:
            with open(_DEEPLINK_CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        _deeplink_cache = data if isinstance(data, dict) else {}
    return _deeplink_cache


def _declared_config(bookmaker: str) -> dict:
    """Return a bookmaker's declaration, or an empty mapping when it is absent."""
    value = _load_deeplink_config().get(bookmaker)
    return value if isinstance(value, dict) else {}


def has_declaration(bookmaker: str) -> bool:
    """Return whether the configuration explicitly declares this bookmaker."""
    return isinstance(_load_deeplink_config().get(bookmaker), dict)


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
        template = cfg.get("template")
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
