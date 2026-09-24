"""
Shared Scraper Helpers

Unified implementations of helpers previously copy-pasted across the direct-API
scrapers (MDShop, MBet, SportPlus, EVLBet, Admiralbet). Centralizing them keeps
outcome normalization and datetime parsing consistent across bookmakers.
"""

from datetime import UTC, datetime

from models.schemas import Market, MarketType, OddsValue

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
) -> list[Market]:
    """
    Parse an NSoft `bets[]` array into Market objects.

    A market is only accepted when its normalized outcome labels fully cover
    the expected set for its resolved market type — e.g. a "1X2" must contain
    all of 1/X/2. This rejects misclassified 2-way markets (advance/qualifier,
    draw-no-bet, handicap) that would otherwise pollute the 1X2 pools.

    `extra_bet_types` adds bookmaker-specific bet type IDs on top of the base
    map (e.g. Admiralbet serves prematch 1X2 as 1639) and `extra_ou_bet_ids`
    adds O/U goal IDs. Live feeds REPLACE the base maps entirely (different ID
    space) via `base_bet_type_map`/`base_ou_bet_ids`.
    """
    bet_type_map = {**(base_bet_type_map or NSOFT_BET_TYPE_MAP), **(extra_bet_types or {})}
    ou_bet_ids = (base_ou_bet_ids if base_ou_bet_ids is not None else NSOFT_OU_BET_IDS) | (extra_ou_bet_ids or set())
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
        market_type = bet_type_map.get(btid)
        if market_type is None and btid in ou_bet_ids and sbv_val is not None:
            if sbv_val == 1.5:
                market_type = MarketType.OVER_UNDER_1_5
            elif sbv_val == 2.5:
                market_type = MarketType.OVER_UNDER_2_5
            elif sbv_val == 3.5:
                market_type = MarketType.OVER_UNDER_3_5
        if market_type is None:
            continue
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
            if norm_label in _MARKET_LABEL_SETS.get(market_type, set()):
                odds_values.append(OddsValue(label=norm_label, value=odd_val))

        expected = _MARKET_LABEL_SETS.get(market_type, set())
        actual = {o.label for o in odds_values}
        # 1X2 and BTTS/O-U must be COMPLETE; Double Chance needs at least 2 legs
        if market_type == MarketType.DOUBLE_CHANCE:
            valid = len(actual) >= 2 and actual.issubset(expected)
        else:
            valid = expected.issubset(actual)
        if valid:
            markets.append(Market(market_type=market_type, odds=odds_values))
    return markets


def parse_nsoft_live_bets(bets: list) -> list[Market]:
    """
    Parse an in-play NSoft `bets[]` array (live ID space).

    Live matches use different bet type IDs (see NSOFT_LIVE_BET_TYPE_MAP);
    prematch IDs like 135/152 never appear here. The same strict label-set
    validation is applied, so dead/suspended outcome sides are dropped and
    misclassified 2-way markets never pollute the 1X2 pool.
    """
    return parse_nsoft_bets(
        bets,
        base_bet_type_map=NSOFT_LIVE_BET_TYPE_MAP,
        base_ou_bet_ids=NSOFT_LIVE_OU_BET_IDS,
    )
