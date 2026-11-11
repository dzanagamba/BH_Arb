"""SR9-3: on-demand check that a served surebet's leg links open the fixture.

A one-time spot check proves a route pattern; it does not prove that the leg the
operator is looking at right now opens its fixture (and, for a ticket rung, that
the selection is on the slip). This module answers that for ONE surebet, when
the operator asks:

* a ``match_page`` or ``ticket_filled`` destination is opened in its own fresh
  browser context (no cookies kept between legs, so a filled slip from one leg
  cannot leak into the next leg's check);
* the page's rendered accessibility text is searched for both team names as the
  BOOK spells them — a competition page or a stale link that does not show the
  fixture fails;
* for a ``ticket_filled`` rung, the text AFTER the first slip marker must repeat
  both team names and the pick, which is what an empty slip cannot do.

It is advisory and never touches the certainty gate: it does not set
``deep_link_verified``, never changes a group's status, and never submits a
ticket or stores a credential. Operator-triggered only — it is never called
from ``run_scan``, so it adds no scheduled traffic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from config.settings import NAVIGATION_TIMEOUT_MS, USER_AGENT
from engine.name_keys import raw_team_key
from server.deeplink_verifier import POLL_INTERVAL_MS, SETTLE_TIMEOUT_MS
from server.timeutil import utcnow

# Only these rungs name a fixture. A search or competition destination is the
# honest fallback and has nothing per-event to open, so it is skipped, not failed.
CHECKABLE_KINDS = ("ticket_filled", "match_page")

# The book's own slip wording, folded (raw_team_key folds case, diacritics and
# punctuation). The FIRST marker is where the slip area starts: the offer comes
# before it, the ticket and its rows after it.
SLIP_MARKERS = ("tiket", "ticket", "listic", "selekcije", "betslip", "slip")
# A page that says this has an empty slip, whatever else it shows (a "recent
# selections" strip can repeat a team, but it is not a ticket).
EMPTY_SLIP_PHRASES = (
    "vas tiket je prazan",
    "tiket je prazan",
    "nema selekcija",
    "broj parova 0",
    "meceva 0",
    "your betslip is empty",
    "betslip is empty",
)

# A pick label that is only a side or a both-teams market can be searched for as
# a token. Line markets need their side in the book's own wording (the folded
# Bosnian "više"/"manje" and the English words cover the enabled books).
_SIDE_WORDS = {"over": ("vise", "over"), "under": ("manje", "under")}
_STRAIGHT_PICKS = frozenset({"1", "x", "2", "1x", "12", "x2", "gg", "ng"})
# Below this many folded characters a team name is too common to search for on a
# whole page ("II", "A"), and claiming a fixture from it would be a guess.
MIN_NAME_CHARS = 3


@dataclass(frozen=True)
class LegTarget:
    """One leg to open, in the book's own terms."""

    bookmaker: str
    kind: str
    url: str
    home: str
    away: str
    pick: str = ""
    line: str = ""


@dataclass
class LegCheck:
    """What one navigation did, per leg.

    ``failed`` is true only for a COMPLETED check that did not show what it
    promised, plus a navigation error. A skipped leg (no per-fixture URL) is not
    a failure: there was nothing to open.
    """

    bookmaker: str
    kind: str
    url: str
    opens_fixture: bool = False
    ticket_has_selection: bool = False
    failed: bool = False
    status: str = "skipped"
    evidence: str = ""
    error: str = ""


def _has_token(haystack: str, needle: str) -> bool:
    """Search for a folded value as a whole token, not inside a longer word."""
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def _slip_position(folded: str) -> int:
    """Where the slip area starts, or -1 when the page shows no slip wording."""
    return min((folded.find(marker) for marker in SLIP_MARKERS if marker in folded), default=-1)


def _slip_has_pick(slip: str, target: LegTarget) -> bool:
    """Whether the folded slip text shows this leg's pick.

    A straight 1/X/2, DC or BTTS pick is one token. A line market needs its side
    in the book's own wording and its line, because a slip for the other side of
    the same line is a different bet. Any other label falls back to the label
    token, so a new market degrades to a weaker check instead of crashing.
    """
    folded = raw_team_key(target.pick)
    line = raw_team_key(target.line)
    if folded in _STRAIGHT_PICKS:
        return _has_token(slip, folded)
    side_words = next(
        (words for word, words in _SIDE_WORDS.items() if folded.startswith(word)), None
    )
    if side_words is not None:
        return any(_has_token(slip, word) for word in side_words) and (
            not line or _has_token(slip, line)
        )
    return _has_token(slip, line or folded)


def judge(text: str, target: LegTarget) -> LegCheck:
    """Decide one leg from the page's rendered text, without a browser.

    This is the whole criterion, so it can be tested against captured page text.
    ``text`` is the concatenated accessibility text of every frame.
    """
    check = LegCheck(bookmaker=target.bookmaker, kind=target.kind, url=target.url)
    folded = raw_team_key(text)
    home = raw_team_key(target.home)
    away = raw_team_key(target.away)
    if min(len(home), len(away)) < MIN_NAME_CHARS:
        check.status = "skipped"
        check.evidence = (
            "the book's spelling is too short to search for on a page, so this "
            "leg was not judged"
        )
        return check
    if not (_has_token(folded, home) and _has_token(folded, away)):
        check.status = "fixture_not_found"
        check.failed = True
        check.evidence = (
            f"the page does not show both team names ({target.home} / {target.away})"
        )
        return check
    check.opens_fixture = True
    if target.kind != "ticket_filled":
        check.status = "ok"
        check.evidence = "the page shows both team names"
        return check

    if any(phrase in folded for phrase in EMPTY_SLIP_PHRASES):
        check.status = "ticket_empty"
        check.failed = True
        check.evidence = "the fixture opened but the slip says it is empty"
        return check
    marker = _slip_position(folded)
    if marker < 0:
        check.status = "ticket_empty"
        check.failed = True
        check.evidence = "the fixture opened but the page shows no slip"
        return check
    slip = folded[marker:]
    if _has_token(slip, home) and _has_token(slip, away) and _slip_has_pick(
        slip, target
    ):
        check.ticket_has_selection = True
        check.status = "ok"
        check.evidence = "the slip repeats both team names and the pick"
        return check
    check.status = "ticket_empty"
    check.failed = True
    check.evidence = (
        "the fixture opened but the slip does not show this pick "
        f"({target.pick}{f' {target.line}' if target.line else ''})"
    )
    return check


def build_targets(surebet: dict[str, Any]) -> list[LegTarget]:
    """The checkable legs of one served surebet, in stake order."""
    listings = surebet.get("listings") or {}
    fallback_home = str(surebet.get("home_team") or "")
    fallback_away = str(surebet.get("away_team") or "")
    targets: list[LegTarget] = []
    for stake in surebet.get("stakes") or []:
        if not isinstance(stake, dict):
            continue
        destination = stake.get("destination") or {}
        kind = str(destination.get("kind") or "")
        url = str(destination.get("url") or "")
        if kind not in CHECKABLE_KINDS or not url:
            continue
        bookmaker = str(stake.get("bookmaker") or "")
        listing = listings.get(bookmaker) or {}
        targets.append(
            LegTarget(
                bookmaker=bookmaker,
                kind=kind,
                url=url,
                home=str(listing.get("home") or fallback_home),
                away=str(listing.get("away") or fallback_away),
                pick=str(destination.get("selection") or stake.get("outcome_label") or ""),
                line=str(destination.get("line") or stake.get("line") or ""),
            )
        )
    return targets


async def page_text(page: Any) -> str:
    """The rendered text of every frame, from the accessibility tree.

    The accessibility tree is what a sighted operator can read: it includes
    closed shadow roots (MaxBet renders its whole sportsbook that way, while the
    document body holds only the site chrome) and iframes. ``inner_text`` is the
    fallback for a frame whose accessibility snapshot is unavailable.
    """
    chunks: list[str] = []
    for frame in page.frames:
        try:
            snapshot = await frame.locator("body").aria_snapshot(timeout=3000)
        except Exception:
            snapshot = ""
        if snapshot:
            chunks.append(snapshot)
            continue
        try:
            text = await frame.inner_text("body")
        except Exception:
            continue
        if text:
            chunks.append(text)
    return "\n".join(chunks)


async def check_target(page: Any, target: LegTarget) -> LegCheck:
    """Open one leg and judge it, polling until the settle window is spent."""
    try:
        await page.goto(
            target.url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
        )
    except Exception as exc:  # navigation never completed: not a failed fixture
        return LegCheck(
            bookmaker=target.bookmaker,
            kind=target.kind,
            url=target.url,
            failed=True,
            status="error",
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )

    waited = 0
    while True:
        check = judge(await page_text(page), target)
        if check.status in {"ok", "skipped"} or waited >= SETTLE_TIMEOUT_MS:
            return check
        await page.wait_for_timeout(POLL_INTERVAL_MS)
        waited += POLL_INTERVAL_MS


def report_for(
    surebet: dict[str, Any],
    mode: str,
    started: datetime,
    legs: list[LegCheck],
    status: str,
    reason: str = "",
) -> dict[str, Any]:
    """The one response shape, whether legs were opened or the check was skipped."""
    opened = sum(1 for leg in legs if leg.opens_fixture)
    tickets = sum(1 for leg in legs if leg.ticket_has_selection)
    return {
        "surebet_id": str(surebet.get("id") or ""),
        "mode": mode,
        "status": status,
        "skip_reason": reason,
        "checked_at": started.isoformat(timespec="seconds"),
        "duration_seconds": round((utcnow() - started).total_seconds(), 2),
        "legs": [
            {
                "bookmaker": leg.bookmaker,
                "kind": leg.kind,
                "url": leg.url,
                "opens_fixture": leg.opens_fixture,
                "ticket_has_selection": leg.ticket_has_selection,
                "failed": leg.failed,
                "status": leg.status,
                "evidence": leg.evidence,
                "error": leg.error,
            }
            for leg in legs
        ],
        "summary": {
            "legs": len(legs),
            "opened": opened,
            "tickets": tickets,
            "failed": sum(1 for leg in legs if leg.failed),
            "skipped": sum(1 for leg in legs if leg.status == "skipped"),
        },
    }


async def check_surebet(surebet: dict[str, Any], mode: str = "prematch") -> dict[str, Any]:
    """Open every checkable leg of one surebet and report per-leg results."""
    started = utcnow()
    targets = build_targets(surebet)
    if not targets:
        return report_for(surebet, mode, started, [], "skipped", skip_reason(surebet))

    from scrapers.base import launch_browser  # late: browser startup is expensive

    playwright, browser, context = await launch_browser()
    legs: list[LegCheck] = []
    try:
        # The launcher's context is shared and blocks resources; each leg gets a
        # fresh, unblocked context so the check sees what the operator would and
        # no leg inherits another leg's slip.
        await context.close()
        for target in targets:
            leg_context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="bs-BA",
                user_agent=USER_AGENT,
            )
            try:
                page = await leg_context.new_page()
                legs.append(await check_target(page, target))
            finally:
                await leg_context.close()
    finally:
        try:
            await browser.close()
            await playwright.stop()
        except Exception:  # pragma: no cover - cleanup is best effort
            pass

    return report_for(surebet, mode, started, legs, "checked")


def skip_reason(surebet: dict[str, Any]) -> str:
    """Why a surebet has nothing to check, in words for the operator."""
    stakes = [s for s in surebet.get("stakes") or [] if isinstance(s, dict)]
    if not stakes:
        return "this surebet has no legs"
    kinds = sorted({
        str((stake.get("destination") or {}).get("kind") or "none") for stake in stakes
    })
    return (
        "no leg has a per-fixture link (best available: "
        + ", ".join(kinds)
        + ") — nothing to open"
    )
