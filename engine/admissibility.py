"""Dated sport/market admissibility audit (N3-2).

The expansion rule was fixed before the measurement and must stay unchanged:

* a sport is admissible only when at least three enabled books publish at least
  three comparable full-match families under the same settlement;
* a market family is enabled only after its own dated evidence;
* a new family or a changed settlement is a prompt for evidence, never an
  automatic admission.

This module turns the one-off `scripts/measure_sports.py` and market-discovery
reports into a stable report schema, then compares a fresh report with the
shipped baseline. It never edits `ENABLED_SPORTS`, `ENABLED_MARKETS`, a parser,
the registry or a trust rule. The baseline is a measurement record; the code is
the admission decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import (
    BOOKMAKERS,
    ENABLED_MARKETS,
    ENABLED_SPORTS,
    EXPERIMENTAL_MARKETS,
)
from engine import sports
from engine.market_registry import MARKET_REGISTRY
from models.schemas import MarketType

SCHEMA_VERSION = "1"
MIN_BOOKS = 3
MIN_FAMILIES = 3
SAME_SETTLEMENT = True

REPO_ROOT = Path(__file__).resolve().parent.parent
SPORT_DISCOVERY_EVIDENCE = "docs/evidence/2026-11-04-sport-discovery.json"
FOOTBALL_LINES_EVIDENCE = "docs/evidence/2026-11-04-football-lines.json"
PREMATCH_EVIDENCE = "docs/evidence/2026-11-04-prematch-scan.json"
DEFAULT_BASELINE = "docs/evidence/2026-11-05-admissibility-baseline.json"

# Families that are sport vocabulary, not football market types. They are
# reported under their sport entry and have no separate football market row.
NON_FOOTBALL_FAMILIES = frozenset(
    {
        MarketType.MONEYLINE,
        MarketType.MONEYLINE_3WAY,
        MarketType.HANDICAP,
        MarketType.TOTAL,
    }
)

# Football lines with their own measured, machine-readable evidence. Every
# other enabled football market points at the dated prematch scan; its note
# says what that scan does and does not prove.
MEASURED_FOOTBALL_LINES = (
    "over_under_0_5",
    "over_under_4_5",
    "over_under_5_5",
)

_ENABLED_BOOKS = sorted(
    book for book, config in BOOKMAKERS.items() if config.get("enabled", True)
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _observed_at(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    value = payload.get("generated_at") or payload.get("observed_at") or ""
    return str(value)


def _evidence_row(path: str, payload: dict[str, Any] | None, scope: str) -> dict[str, Any]:
    return {
        "path": path,
        "available": payload is not None,
        "observed_at": _observed_at(payload),
        "scope": scope,
    }


def _family_settlements(sport: str) -> dict[str, str]:
    spec = sports.spec_for(sport)
    if spec is None:
        return {}
    rows: dict[str, str] = {}
    for family in spec.families():
        rows[family.value] = sports.settlement_for(sport, family)
    return rows


def _normalise_books(sport: str, raw_books: list[Any]) -> dict[str, dict[str, Any]]:
    """Normalise the measured rows into ``book -> families/settlements``.

    The two evidence shapes seen so far are a count dict (implemented scrapers)
    and a sorted family list (raw endpoint probes). Both become one map; an
    unknown family (for example MaxBet's ``total_incl_ot``) is kept but cannot
    count toward the three comparable families.
    """
    canonical = _family_settlements(sport)
    spec = sports.spec_for(sport)
    aliases = (
        {
            "moneyline": spec.moneyline.value,
            "handicap": spec.handicap.value,
            "total": spec.total.value,
        }
        if spec is not None
        else {}
    )
    books: dict[str, dict[str, Any]] = {}
    for row in raw_books:
        if not isinstance(row, dict):
            continue
        book = str(row.get("book") or "")
        if not book:
            continue
        raw_markets = row.get("markets")
        families: dict[str, int] = {}
        if isinstance(raw_markets, dict):
            for family, count in raw_markets.items():
                try:
                    amount = int(count)
                except (TypeError, ValueError):
                    continue
                if amount > 0:
                    families[aliases.get(str(family), str(family))] = amount
        elif isinstance(raw_markets, list):
            for family in raw_markets:
                families[aliases.get(str(family), str(family))] = 1
        settlements = {
            family: canonical.get(family, "unknown") for family in families
        }
        books[book] = {
            "matches": int(row.get("matches") or 0),
            "families": dict(sorted(families.items())),
            "settlements": dict(sorted(settlements.items())),
            "note": str(row.get("settlement_note") or ""),
        }
    return dict(sorted(books.items()))


def _qualifying_books(sport: str, books: dict[str, dict[str, Any]]) -> list[str]:
    comparable = set(_family_settlements(sport))
    return sorted(
        book
        for book, coverage in books.items()
        if len(comparable & set(coverage["families"])) >= MIN_FAMILIES
    )


def _sport_entry(
    sport: str,
    raw: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    books = _normalise_books(sport, list(raw.get("books") or []))
    qualifying = _qualifying_books(sport, books)
    admissible = len(qualifying) >= MIN_BOOKS
    enabled = sport in ENABLED_SPORTS
    admitted = enabled and admissible
    if admitted:
        status = "admitted"
    elif not enabled:
        status = "not_enabled"
    else:
        status = "not_admissible"
    missing_families = sorted(
        set(_family_settlements(sport))
        - {
            family
            for coverage in books.values()
            for family in coverage["families"]
        }
    )
    return {
        "sport": sport,
        "enabled": enabled,
        "admitted": admitted,
        "admissible": admissible,
        "status": status,
        "rule": {
            "min_books": MIN_BOOKS,
            "min_families": MIN_FAMILIES,
            "same_settlement": SAME_SETTLEMENT,
        },
        "family_settlements": _family_settlements(sport),
        "books": books,
        "qualifying_books": qualifying,
        "missing_families": missing_families,
        "evidence": evidence,
    }


def _football_markets(
    lines_payload: dict[str, Any] | None,
    prematch_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    lines_evidence = _evidence_row(
        FOOTBALL_LINES_EVIDENCE,
        lines_payload,
        "measured cross-book line coverage",
    )
    prematch_evidence = _evidence_row(
        PREMATCH_EVIDENCE,
        prematch_payload,
        "dated prematch scan (football market families)",
    )
    measured_rows = (lines_payload or {}).get("markets") or {}
    for market in ENABLED_MARKETS:
        market_type = MarketType(market)
        if market_type in NON_FOOTBALL_FAMILIES:
            continue
        declared_prematch = sorted(
            book
            for book in _ENABLED_BOOKS
            if MARKET_REGISTRY.ids_for(book, "prematch", market_type)
        )
        declared_live = sorted(
            book
            for book in _ENABLED_BOOKS
            if MARKET_REGISTRY.ids_for(book, "live", market_type)
        )
        if market in MEASURED_FOOTBALL_LINES:
            evidence = dict(lines_evidence)
            measured = measured_rows.get(market) or {}
            evidence["measured"] = True
            evidence["price_sources"] = list(measured.get("price_sources") or [])
            evidence["source_rows"] = dict(measured.get("source_rows") or {})
            note = "measured cross-book line coverage in the dated report"
        else:
            evidence = dict(prematch_evidence)
            evidence["measured"] = False
            evidence["price_sources"] = []
            evidence["source_rows"] = {}
            note = (
                "dated prematch scan; market-level rows are in the generated "
                "registry and MARKET_MAPPING.md, not in this report"
            )
        if market == "first_half_ou":
            note = (
                "enabled; the dated scan recorded no offer. The price guard "
                "still applies if a book starts publishing it."
            )
        rows[market] = {
            "market": market,
            "sport": sports.FOOTBALL,
            "enabled": True,
            "admitted": True,
            "experimental": market in EXPERIMENTAL_MARKETS,
            "settlement": sports.settlement_for(sports.FOOTBALL, market_type),
            "declared_books": {
                "prematch": declared_prematch,
                "live": declared_live,
            },
            "evidence": evidence,
            "note": note,
        }
    return dict(sorted(rows.items()))


def _football_sport_entry(
    markets: dict[str, Any],
    prematch_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Football's per-book coverage comes from the registry, not a probe.

    Football has no moneyline/handicap/total probe: every family is a market
    in its own right and is measured under ``markets``. Recording the registry
    declarations here keeps the sport entry complete without inventing a
    three-family threshold that football never used.
    """
    books: dict[str, dict[str, Any]] = {}
    for book in _ENABLED_BOOKS:
        families: dict[str, int] = {}
        for market in markets:
            market_type = MarketType(market)
            count = len(MARKET_REGISTRY.ids_for(book, "prematch", market_type))
            if count:
                families[market] = count
        if families:
            books[book] = {
                "matches": 0,
                "families": dict(sorted(families.items())),
                "settlements": {market: "full_time" for market in sorted(families)},
                "note": "declared in the market registry",
            }
    return {
        "sport": sports.FOOTBALL,
        "enabled": sports.FOOTBALL in ENABLED_SPORTS,
        "admitted": sports.FOOTBALL in ENABLED_SPORTS,
        "admissible": sports.FOOTBALL in ENABLED_SPORTS,
        "status": (
            "admitted" if sports.FOOTBALL in ENABLED_SPORTS else "not_enabled"
        ),
        "rule": {
            "min_books": MIN_BOOKS,
            "min_families": MIN_FAMILIES,
            "same_settlement": SAME_SETTLEMENT,
        },
        "family_settlements": {
            market: entry["settlement"] for market, entry in markets.items()
        },
        "books": dict(sorted(books.items())),
        "qualifying_books": sorted(books),
        "missing_families": [],
        "coverage_source": "market registry declarations",
        "note": (
            "Football's families are individual markets; their dated evidence "
            "rows are under 'markets'. The three-family sport probe is for the "
            "non-football sports."
        ),
        "evidence": _evidence_row(
            PREMATCH_EVIDENCE,
            prematch_payload,
            "dated football scan plus registry declarations",
        ),
    }


def build_report(
    *,
    root: Path | None = None,
    sport_evidence: str | None = None,
    football_lines_evidence: str | None = None,
    prematch_evidence: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the stable audit report from the dated evidence files.

    The report is deterministic for a fixed evidence set and generated_at. It
    never reads the operator's `cache/` or writes runtime state.
    """
    base = root or REPO_ROOT
    sport_path = sport_evidence or SPORT_DISCOVERY_EVIDENCE
    lines_path = football_lines_evidence or FOOTBALL_LINES_EVIDENCE
    prematch_path = prematch_evidence or PREMATCH_EVIDENCE
    sport_payload = _read_json(base / sport_path)
    lines_payload = _read_json(base / lines_path)
    prematch_payload = _read_json(base / prematch_path)

    raw_sports = (sport_payload or {}).get("sports") or {}
    sport_rows: dict[str, Any] = {}
    for sport in sorted(sports.SPORT_SPECS):
        raw = raw_sports.get(sport) if isinstance(raw_sports, dict) else None
        evidence = _evidence_row(
            sport_path,
            sport_payload,
            "measured per-book family coverage" if sport != sports.FOOTBALL else "football path",
        )
        sport_rows[sport] = _sport_entry(
            sport, raw if isinstance(raw, dict) else {}, evidence
        )

    markets = _football_markets(lines_payload, prematch_payload)
    sport_rows[sports.FOOTBALL] = _football_sport_entry(markets, prematch_payload)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": (
            generated_at
            or datetime.now(UTC).replace(microsecond=0).isoformat()
        ),
        "rule": {
            "min_books": MIN_BOOKS,
            "min_families": MIN_FAMILIES,
            "same_settlement": SAME_SETTLEMENT,
            "auto_admit": False,
        },
        "enabled_books": list(_ENABLED_BOOKS),
        "enabled_sports": list(ENABLED_SPORTS),
        "sports": dict(sorted(sport_rows.items())),
        "markets": markets,
        "evidence": {
            "sport_discovery": _evidence_row(
                sport_path, sport_payload, "sport and per-book family coverage"
            ),
            "football_lines": _evidence_row(
                lines_path, lines_payload, "football line coverage"
            ),
            "prematch_scan": _evidence_row(
                prematch_path, prematch_payload, "dated football scan"
            ),
        },
    }


@dataclass
class AuditResult:
    """The change detector's verdict, serialisable for the CLI and health."""

    failures: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    def add_failure(self, kind: str, detail: str, **where: Any) -> None:
        self.failures.append({"kind": kind, "detail": detail, **where})

    def add_warning(self, kind: str, detail: str, **where: Any) -> None:
        self.warnings.append({"kind": kind, "detail": detail, **where})

    @property
    def status(self) -> str:
        if self.failures:
            return "fail"
        if self.warnings:
            return "warning"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failures": self.failures,
            "warnings": self.warnings,
            "checked": self.checked,
        }


def _compare_rule(report: dict[str, Any], baseline: dict[str, Any], audit: AuditResult) -> None:
    expected = {
        "min_books": MIN_BOOKS,
        "min_families": MIN_FAMILIES,
        "same_settlement": SAME_SETTLEMENT,
        "auto_admit": False,
    }
    if report.get("rule") != expected:
        audit.add_failure(
            "rule_changed",
            "the current report rule is not the fixed admissibility rule",
            expected=expected,
            actual=report.get("rule"),
        )
    if baseline.get("rule") != expected:
        audit.add_failure(
            "threshold_lowered",
            "the baseline rule differs from the fixed three-book/three-family rule",
            expected=expected,
            actual=baseline.get("rule"),
        )
    if baseline.get("schema_version") != SCHEMA_VERSION:
        audit.add_failure(
            "schema_changed",
            "the baseline schema differs from this audit's schema",
            expected=SCHEMA_VERSION,
            actual=baseline.get("schema_version"),
        )


def _compare_sports(report: dict[str, Any], baseline: dict[str, Any], audit: AuditResult) -> None:
    baseline_sports = baseline.get("sports") or {}
    report_sports = report.get("sports") or {}
    audit.checked["sports"] = len(baseline_sports)
    for sport, base in sorted(baseline_sports.items()):
        current = report_sports.get(sport)
        if not isinstance(current, dict):
            audit.add_failure(
                "admitted_sport_missing",
                "a sport present in the baseline is absent from the report",
                sport=sport,
            )
            continue
        if base.get("admitted") and not current.get("admitted"):
            audit.add_failure(
                "admitted_sport_lost",
                "a previously admitted sport is no longer admitted",
                sport=sport,
                baseline=base.get("status"),
                current=current.get("status"),
            )
        if base.get("admissible") and not current.get("admissible"):
            audit.add_failure(
                "sport_became_inadmissible",
                "a sport that met the three-book rule no longer meets it",
                sport=sport,
                baseline_books=base.get("qualifying_books"),
                current_books=current.get("qualifying_books"),
            )
        for book in sorted(
            set(base.get("qualifying_books") or [])
            - set(current.get("qualifying_books") or [])
        ):
            audit.add_failure(
                "qualifying_book_disappeared",
                "a qualifying book no longer reaches three comparable families",
                sport=sport,
                book=book,
            )
        for family, settlement in (base.get("family_settlements") or {}).items():
            if (current.get("family_settlements") or {}).get(family) != settlement:
                audit.add_failure(
                    "sport_settlement_changed",
                    "a sport family's settlement changed; that is a different bet",
                    sport=sport,
                    family=family,
                    baseline=settlement,
                    current=(current.get("family_settlements") or {}).get(family),
                )
        for book, coverage in sorted((base.get("books") or {}).items()):
            current_coverage = (current.get("books") or {}).get(book)
            if not isinstance(current_coverage, dict):
                audit.add_failure(
                    "book_coverage_missing",
                    "a book measured in the baseline is absent from the report",
                    sport=sport,
                    book=book,
                )
                continue
            for family, count in sorted((coverage.get("families") or {}).items()):
                current_count = (current_coverage.get("families") or {}).get(family, 0)
                if count > 0 and int(current_count) <= 0:
                    audit.add_failure(
                        "admitted_family_disappeared",
                        "a previously measured family disappeared for this book",
                        sport=sport,
                        book=book,
                        family=family,
                        baseline_rows=count,
                        current_rows=current_count,
                    )
                if (coverage.get("settlements") or {}).get(family) != (
                    current_coverage.get("settlements") or {}
                ).get(family):
                    audit.add_failure(
                        "book_settlement_changed",
                        "a book's family settlement changed",
                        sport=sport,
                        book=book,
                        family=family,
                    )
            for family in sorted(
                set(current_coverage.get("families") or {})
                - set(coverage.get("families") or {})
            ):
                audit.add_warning(
                    "new_family_without_evidence",
                    "a new family was measured for this book; it is not admitted automatically",
                    sport=sport,
                    book=book,
                    family=family,
                )
        for family in sorted(
            set(current.get("family_settlements") or {})
            - set(base.get("family_settlements") or {})
        ):
            audit.add_warning(
                "new_sport_family_without_evidence",
                "a new sport family has no baseline evidence row",
                sport=sport,
                family=family,
            )
        for book in sorted(
            set(current.get("books") or {}) - set(base.get("books") or {})
        ):
            audit.add_warning(
                "new_book_without_evidence",
                "a newly measured book has no baseline evidence row",
                sport=sport,
                book=book,
            )
    for sport in sorted(set(report_sports) - set(baseline_sports)):
        audit.add_warning(
            "new_sport_without_evidence",
            "a sport has no baseline evidence row; it is not admitted automatically",
            sport=sport,
        )


def _compare_markets(report: dict[str, Any], baseline: dict[str, Any], audit: AuditResult) -> None:
    baseline_markets = baseline.get("markets") or {}
    report_markets = report.get("markets") or {}
    audit.checked["markets"] = len(baseline_markets)
    for market, base in sorted(baseline_markets.items()):
        current = report_markets.get(market)
        if not isinstance(current, dict):
            audit.add_failure(
                "admitted_market_missing",
                "a market present in the baseline is absent from the report",
                market=market,
            )
            continue
        if base.get("admitted") and not current.get("admitted"):
            audit.add_failure(
                "admitted_market_lost",
                "a previously admitted market is no longer admitted",
                market=market,
            )
        if base.get("settlement") != current.get("settlement"):
            audit.add_failure(
                "market_settlement_changed",
                "an enabled market's settlement changed",
                market=market,
                baseline=base.get("settlement"),
                current=current.get("settlement"),
            )
        base_sources = set((base.get("evidence") or {}).get("price_sources") or [])
        current_sources = set((current.get("evidence") or {}).get("price_sources") or [])
        for source in sorted(base_sources - current_sources):
            audit.add_failure(
                "admitted_price_source_disappeared",
                "a previously measured price source disappeared for this line",
                market=market,
                source=source,
            )
        for source in sorted(current_sources - base_sources):
            audit.add_warning(
                "new_price_source_without_evidence",
                "a new price source appeared for this line; it is not admitted automatically",
                market=market,
                source=source,
            )
        base_books = set((base.get("declared_books") or {}).get("prematch") or [])
        current_books = set((current.get("declared_books") or {}).get("prematch") or [])
        for book in sorted(base_books - current_books):
            audit.add_warning(
                "declared_book_family_disappeared",
                "a book no longer declares this market in the registry",
                market=market,
                book=book,
            )
    for market in sorted(set(report_markets) - set(baseline_markets)):
        audit.add_warning(
            "new_market_without_evidence",
            "a market has no baseline evidence row; it is not admitted automatically",
            market=market,
        )


def validate_evidence(report: dict[str, Any], audit: AuditResult) -> None:
    """Every enabled sport and market needs a dated evidence row."""
    sports_rows = report.get("sports") or {}
    for sport in report.get("enabled_sports") or []:
        if sport not in sports_rows:
            audit.add_failure(
                "missing_sport_entry",
                "an enabled sport has no report entry at all",
                sport=sport,
            )
    for sport, entry in sorted(sports_rows.items()):
        if not entry.get("enabled"):
            continue
        evidence = entry.get("evidence") or {}
        if not evidence.get("available") or not evidence.get("observed_at"):
            audit.add_failure(
                "missing_sport_evidence",
                "an enabled sport has no available dated evidence row",
                sport=sport,
                path=evidence.get("path"),
            )
    markets_rows = report.get("markets") or {}
    covered_markets = set(markets_rows)
    for entry in sports_rows.values():
        covered_markets |= set(entry.get("family_settlements") or {})
    for market in ENABLED_MARKETS:
        if market not in covered_markets:
            audit.add_failure(
                "missing_market_entry",
                "an enabled market has no report entry or sport family row",
                market=market,
            )
    for market, entry in sorted(markets_rows.items()):
        if not entry.get("enabled"):
            continue
        evidence = entry.get("evidence") or {}
        if not evidence.get("available") or not evidence.get("observed_at"):
            audit.add_failure(
                "missing_market_evidence",
                "an enabled market has no available dated evidence row",
                market=market,
                path=evidence.get("path"),
            )


def detect_changes(
    report: dict[str, Any],
    baseline: dict[str, Any],
) -> AuditResult:
    """Compare a fresh report with the shipped baseline.

    The comparison is one-way: evidence may appear (warning) but an admitted
    family, settlement or price source disappearing is a failure. A new family
    never changes an admitted flag.
    """
    audit = AuditResult()
    _compare_rule(report, baseline, audit)
    _compare_sports(report, baseline, audit)
    _compare_markets(report, baseline, audit)
    validate_evidence(report, audit)
    return audit


def load_baseline(path: str | Path | None = None) -> dict[str, Any]:
    baseline_path = Path(path) if path is not None else REPO_ROOT / DEFAULT_BASELINE
    payload = _read_json(baseline_path)
    if payload is None:
        raise FileNotFoundError(f"admissibility baseline not found: {baseline_path}")
    return payload


def audit(
    *,
    baseline_path: str | Path | None = None,
    **report_kwargs: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(report, audit_result)`` for the CLI and health endpoint."""
    report = build_report(**report_kwargs)
    baseline = load_baseline(baseline_path)
    return report, detect_changes(report, baseline).as_dict()


def health_summary(
    *,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    """A bounded health block: counts and statuses, never the full report."""
    try:
        report, result = audit(baseline_path=baseline_path)
    except (OSError, ValueError) as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unavailable",
            "error": f"{type(exc).__name__}: {exc}"[:200],
        }
    sports_rows = {
        sport: {
            "enabled": entry.get("enabled"),
            "admitted": entry.get("admitted"),
            "admissible": entry.get("admissible"),
            "qualifying_books": len(entry.get("qualifying_books") or []),
            "status": entry.get("status"),
        }
        for sport, entry in (report.get("sports") or {}).items()
    }
    markets_rows = {
        market: {
            "enabled": entry.get("enabled"),
            "admitted": entry.get("admitted"),
            "settlement": entry.get("settlement"),
            "evidence": (entry.get("evidence") or {}).get("path"),
            "observed_at": (entry.get("evidence") or {}).get("observed_at"),
        }
        for market, entry in (report.get("markets") or {}).items()
    }
    return {
        "schema_version": report.get("schema_version"),
        "baseline_generated_at": load_baseline(baseline_path).get("generated_at"),
        "status": result["status"],
        "failure_count": len(result["failures"]),
        "warning_count": len(result["warnings"]),
        "sports": sports_rows,
        "markets": markets_rows,
    }
