"""
On-demand deep-link verification.

`deep_link_verified` is the only flag in the product that may unblock a
``verified`` match group, so the bar for setting it is deliberately high: a link
counts as verified only when the bookmaker's own site proves it served the
intended event. An HTTP 200 proves nothing — MDShop serves 200 and an identical
page for an event id that has never existed — and neither does a page that
merely rendered, because the NSoft shell happily echoes our own ``?event=<id>``
query parameter back into an iframe ``src``.

The criterion (see ``CRITERION``) is therefore structural, not a substring
search, and it demands *attributable* evidence. The link counts as verified only
when the bookmaker's own site resolved the id as data **because of our request**:

* a JSON payload served by a book-owned host, requested for that id (the request
  URL itself carries it), carrying the id as the value of a key that names an
  event — `id`/`eventId`/`matchId` and their compound forms, never a settings key
  such as `maxTotalOdd` — and as an int or a string, never as a float, or
* the rendered text of the page shows the id as a standalone value, never as
  part of a URL.

Four controls decided that shape, all measured live and all in the report: a dead
event id still gets HTTP 200 and a byte-identical page from the NSoft shells;
MDShop's ``businessModel`` payload carries ``"maxTotalOdd": 999999999999.00``,
a settings key that the KEY rule rejects (the float rule never sees it);
Admiralbet serves the same 29 KB ``bonus-tickets-with-details`` payload on every
load, so an id inside it proves nothing about our link; and the Mozzartbet route
for a dead id answers 200 with 14 bytes instead of 328 KB. Against those controls
only Mozzartbet survives — which is a fact about the bookmakers, not a broken
checker.

Run it directly:

    python scripts/verify_deeplinks.py mozzartbet --limit 3
    python scripts/verify_deeplinks.py mozzartbet --limit 20 --offset 20

A book publishes hundreds of events and each costs a real navigation, so a sweep
is many calls. The CLI keeps no record of what it has already decided, so it is
driven by ``--offset`` — resume at the Nth undecided event — and every printed
report echoes ``next_offset`` and ``remaining`` for the next call. The
``POST /api/verify-links`` endpoint needs no cursor from its caller: it reads the
events it has already decided out of its own store and skips them itself.

It is deliberately NOT part of a scan: each event costs a real browser
navigation (seconds), so triggering it from ``run_scan`` would turn a scan into
minutes of work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Collection
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import BOOKMAKERS, CACHE_DIR, NAVIGATION_TIMEOUT_MS  # noqa: E402
from scrapers.common import build_event_url, supports_event_id  # noqa: E402

CRITERION = (
    "event id resolved as a value under a key that names an event in a "
    "book-owned JSON payload that was requested for that id, or shown as a "
    "standalone value in rendered page text; an HTTP 200, a rendered shell, an "
    "echo of the requested URL, a payload the page fetches anyway, or a "
    "settings number that merely contains the id is not evidence"
)

# A response bigger than this is not an event payload; reading it would only
# cost memory and time.
MAX_BODY_BYTES = 25_000_000
# Total time a page gets to prove the event, after the document is loaded.
SETTLE_TIMEOUT_MS = 15_000
# How often the captured payloads are re-examined while the page settles.
POLL_INTERVAL_MS = 750
# Characters that make an occurrence part of a URL rather than a value.
URL_PUNCTUATION = "/?&#=.,;:"


@dataclass(frozen=True)
class LinkTarget:
    """One per-event URL to prove."""

    event_id: str
    url: str


@dataclass(frozen=True)
class LinkOutcome:
    """The result of checking one target.

    ``error`` is set only when the check could not COMPLETE (navigation error,
    browser crash). A completed check that found nothing is ``verified=False``
    with an empty ``error`` — the difference matters, because a completed check
    is allowed to clear a stale verification while an error is not.
    """

    event_id: str
    url: str
    verified: bool
    evidence: str = ""
    error: str = ""

    @property
    def completed(self) -> bool:
        return not self.error


@dataclass
class LinkReport:
    """What one on-demand verification run did, and what it cost.

    ``checked == verified + failed + errored`` always holds: an errored check
    (a navigation that never completed) is neither a proof nor a failure, and
    leaving it out of the summary made the arithmetic look wrong to every reader.

    ``next_offset`` and ``remaining`` exist so a sweep can be driven from the
    report alone. They are populated only when a run actually checked something;
    on the two early returns they stay 0, because no window was ever cut.
    """

    bookmaker: str
    mode: str = "prematch"
    status: str = "checked"  # "checked" | "skipped"
    skip_reason: str = ""
    available: int = 0
    checked: int = 0
    verified: int = 0
    failed: int = 0
    errored: int = 0
    duration_seconds: float = 0.0
    next_offset: int = 0
    remaining: int = 0
    outcomes: list[LinkOutcome] = field(default_factory=list)

    @property
    def unchecked(self) -> int:
        """Candidates that exist but were not checked (the cap cut the list)."""
        return max(0, self.available - self.checked)


# ─── The criterion (pure, and the only thing that may set `verified`) ───────────


def book_owned_host(candidate_url: str, base_url: str) -> bool:
    """Return whether a URL is served by the bookmaker's own site.

    Sub-domains count (MDShop's offers live on ``mdoffer.mdshop.ba``) but a
    look-alike host does not: the test is a suffix on a dot boundary, so
    ``evil-mdshop.ba.attacker.test`` is not book-owned.
    """
    host = urlsplit(candidate_url).hostname or ""
    base_host = urlsplit(base_url).hostname or ""
    if not host or not base_host:
        return False
    base_domain = base_host[4:] if base_host.startswith("www.") else base_host
    return host == base_host or host.endswith(f".{base_domain}")


def whole_token_span(haystack: str, event_id: str) -> tuple[int, int] | None:
    """Return the span where ``event_id`` appears as a standalone value.

    Word boundaries keep ``9984468`` from matching inside ``199844681``: an id
    that is a fragment of a longer number is not the event we asked for.
    """
    if not event_id:
        return None
    start = -1
    index = haystack.find(event_id)
    while index != -1:
        before = haystack[index - 1] if index else ""
        after_at = index + len(event_id)
        after = haystack[after_at] if after_at < len(haystack) else ""
        if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
            start = index
            break
        index = haystack.find(event_id, index + 1)
    if start == -1:
        return None
    return start, start + len(event_id)


# Keys that name an EVENT. A plain `endswith("id")` would also accept `paid`,
# `valid`, `grid`, `void` and `uuid`, so the rule is an exact-name set for the
# bare `id` plus the compound forms (`eventId`, `match_id`, `originalEventId`).
# The two sets do not overlap: an entry in both would be dead weight that reads
# as if it did something. Everything else — including `maxTotalOdd` and
# `displayNumberFormat`, both measured on live payloads — may not speak for an
# event, and it is THIS rule that rejected them, not the float rule below.
EVENT_ID_KEYS = frozenset({"id"})
EVENT_ID_KEY_SUFFIXES = ("eventid", "matchid", "gameid", "fixtureid")


def is_event_id_key(key: str) -> bool:
    """Return whether a JSON key names an event, so its value may be the event id."""
    normalized = key.lower().replace("_", "")
    return normalized in EVENT_ID_KEYS or normalized.endswith(EVENT_ID_KEY_SUFFIXES)


def json_event_paths(body: str, event_id: str, max_hits: int = 3) -> list[str]:
    """Return the JSON paths where a key that names an event holds exactly ``event_id``.

    Structural, not lexical, on purpose — a dead id once measured as "verified"
    against MDShop's ``businessModel`` payload, which carries
    ``"maxTotalOdd": 999999999999.00``. Three rules, and the FIRST is the one
    that stopped that control:

    * a key that names an event (:func:`is_event_id_key`). ``maxTotalOdd`` and
      ``displayNumberFormat`` do not end in ``id``, so a settings key is rejected
      here and the int/float comparison is never reached,
    * a value that IS the id (``1234567`` is not ``9984468``), and
    * an integer or string value, never a float. The float rule is a second
      line of defence for the same shape of false pass (a decimal amount that
      happens to equal the id under a key that does name an event), not the
      defence that ran.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return []

    hits: list[str] = []

    def walk(node: Any, key: str, path: str) -> None:
        if len(hits) >= max_hits:
            return
        if isinstance(node, dict):
            for child_key, value in node.items():
                walk(value, str(child_key), f"{path}.{child_key}")
        elif isinstance(node, list):
            for index, value in enumerate(node[:50]):
                walk(value, key, f"{path}[{index}]")
        elif isinstance(node, bool):
            return  # bool is an int subclass, and True is not an event
        elif isinstance(node, int | str) and str(node) == event_id:
            if is_event_id_key(key):
                hits.append(f"{path} = {event_id}")

    walk(data, "", "$")
    return hits


def payload_evidence(
    responses: list[tuple[str, str, str]],
    request_url: str,
    event_id: str,
    base_url: str = "",
) -> list[str]:
    """Return evidence lines for event ids resolved in book-owned JSON payloads.

    ``responses`` is ``(url, content_type, body)``. Four things are excluded, and
    each one was measured as a false pass on a live bookmaker:

    * HTML — that is where an echo of our own query parameter lives, and the NSoft
      shells echo `?event=<id>` into an iframe ``src`` for a dead id too,
    * the requested document itself,
    * a payload the page fetches on EVERY load, with or without the event
      parameter (Admiralbet's 29 KB ``bonus-tickets-with-details`` lists the
      events that have a bonus ticket, so it "proved" 2 of 6 links that did
      nothing). The evidence must be *attributable*: the request that produced
      it has to be scoped to this event id, and
    * a value that is not the event (see :func:`json_event_paths`).
    """
    evidence: list[str] = []
    for url, content_type, body in responses:
        if not body or "json" not in content_type.lower():
            continue
        if base_url and not book_owned_host(url, base_url):
            continue
        if request_url and url.split("#")[0] == request_url.split("#")[0]:
            continue  # the document we asked for, not an answer about the event
        if whole_token_span(url, event_id) is None:
            continue  # fetched anyway: proves the id is in the feed, not the link
        for path in json_event_paths(body, event_id):
            evidence.append(f"book payload {url} ({content_type.split(';')[0].strip()}) served {path}")
    return evidence


def rendered_text_evidence(text: str, event_id: str) -> str | None:
    """Return evidence when the visible page text carries the event id as a value.

    An id next to URL punctuation is a link the page is showing, not a value it
    resolved, so it is rejected — a dead event is displayed the same way. An id
    at the very start or end of the text has no adjacent character and is fine:
    `"" in "/?&#"` is True in Python, so the test must skip the empty case.
    """
    span = whole_token_span(text, event_id)
    if span is None:
        return None
    before = text[span[0] - 1] if span[0] else ""
    after = text[span[1]] if span[1] < len(text) else ""
    if (before and before in URL_PUNCTUATION) or (after and after in URL_PUNCTUATION):
        return None
    context = text[max(0, span[0] - 60): span[1] + 40].replace("\n", " ")
    return f'rendered page text shows "…{context}…"'


# ─── Targets ──────────────────────────────────────────────────────────────────


def _field(match: Any, name: str) -> Any:
    """Read a field from a match dict or a ``Match`` model."""
    if isinstance(match, dict):
        return match.get(name)
    return getattr(match, name, None)


def build_targets(
    matches: list[Any],
    bookmaker: str,
    base_url: str,
    live: bool = False,
    limit: int | None = None,
    offset: int = 0,
    settled: Collection[str] = (),
) -> list[LinkTarget]:
    """Build one target per distinct event id a bookmaker published.

    The result is a WINDOW, not a list, and the two cursor arguments are applied
    in this order, which is the whole contract:

    1. walk the feed in order, dropping other books, blank ids and repeats;
    2. skip any event id in ``settled`` — ids the caller has already DECIDED,
       verified or failed. This happens BEFORE the limit is counted, so a run
       spends its whole budget on events nobody has decided. It is the primary
       mechanism: it is idempotent, it needs no state from the caller, and it
       survives the feed growing at the head;
    3. skip the first ``offset`` of what is left (a negative offset is clamped to
       0, so it can never index from the end of the book);
    4. stop at ``limit``.

    ``offset`` exists for a caller with no store of its own — the CLI. It is a
    position in the POST-skip ordering, so it is only comparable between calls
    that skip the same set; combining it with a ``settled`` set that has grown
    since skips further ahead than the number says. The caller decides what is
    settled, so an event whose check ERRORED must never appear in ``settled``:
    see :func:`apply_report`, which is the other half of that rule.
    """
    targets: list[LinkTarget] = []
    seen: set[str] = set()
    decided = {str(event_id) for event_id in settled}
    start = max(0, offset)
    undecided_seen = 0
    for match in matches:
        if _field(match, "bookmaker") != bookmaker:
            continue
        raw = _field(match, "event_id")
        event_id = "" if raw is None else str(raw)
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        if event_id in decided:
            continue
        undecided_seen += 1
        if undecided_seen <= start:
            continue
        targets.append(
            LinkTarget(event_id=event_id, url=build_event_url(bookmaker, event_id, base_url, live))
        )
        if limit is not None and len(targets) >= limit:
            break
    return targets


def apply_report(matches: list[Any], report: LinkReport) -> int:
    """Write a report's verdicts onto the given matches; return how many changed.

    A completed check is authoritative in both directions: a proven link is
    marked, and a link that no longer proves the event is cleared. A check that
    errored leaves the flag alone — a timeout is not proof of a dead event.
    """
    verdicts = {
        outcome.event_id: outcome.verified
        for outcome in report.outcomes
        if outcome.completed
    }
    changed = 0
    for match in matches:
        event_id = str(_field(match, "event_id") or "")
        if event_id not in verdicts:
            continue
        current = bool(_field(match, "deep_link_verified"))
        if current == verdicts[event_id]:
            continue
        if isinstance(match, dict):
            match["deep_link_verified"] = verdicts[event_id]
        else:
            match.deep_link_verified = verdicts[event_id]
        changed += 1
    return changed


# ─── The browser check ────────────────────────────────────────────────────────


async def _frame_texts(page) -> list[str]:
    """Return the visible text of the main frame and every subframe."""
    texts: list[str] = []
    for frame in [*page.frames]:
        try:
            text = await frame.inner_text("body")
        except Exception:
            continue
        if text and text.strip():
            texts.append(text)
    return texts


async def check_target(page, target: LinkTarget, base_url: str) -> LinkOutcome:
    """Load one deep link and decide whether it served the intended event."""
    captured: list[tuple[str, str, str]] = []
    pending: list[Any] = []

    async def capture(response) -> None:
        url = response.url
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower() or not book_owned_host(url, base_url):
            return

        async def read() -> None:
            try:
                body = await response.text()
            except Exception:
                return
            if body and len(body) <= MAX_BODY_BYTES:
                captured.append((url, content_type, body))

        pending.append(asyncio.ensure_future(read()))

    page.on("response", capture)
    try:
        try:
            response = await page.goto(
                target.url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
            )
        except Exception as exc:
            return LinkOutcome(
                event_id=target.event_id,
                url=target.url,
                verified=False,
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )

        waited = 0
        while waited < SETTLE_TIMEOUT_MS:
            await page.wait_for_timeout(POLL_INTERVAL_MS)
            waited += POLL_INTERVAL_MS
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
                pending.clear()
            # Stop as soon as the proof arrives; a book that never sends it
            # costs the full settle window, which is the honest price.
            found = payload_evidence(captured, target.url, target.event_id, base_url)
            if found:
                return LinkOutcome(
                    event_id=target.event_id, url=target.url, verified=True, evidence=found[0]
                )

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            pending.clear()
        found = payload_evidence(captured, target.url, target.event_id, base_url)
        if found:
            return LinkOutcome(
                event_id=target.event_id, url=target.url, verified=True, evidence=found[0]
            )
        for text in await _frame_texts(page):
            shown = rendered_text_evidence(text, target.event_id)
            if shown:
                return LinkOutcome(
                    event_id=target.event_id, url=target.url, verified=True, evidence=shown
                )

        return LinkOutcome(
            event_id=target.event_id,
            url=target.url,
            verified=False,
            evidence=(
                f"no book-owned JSON payload or rendered text carried {target.event_id} "
                f"(http {response.status if response else 'n/a'})"
            ),
        )
    finally:
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        page.remove_listener("response", capture)


async def verify_bookmaker(
    bookmaker: str,
    matches: list[Any],
    mode: str = "prematch",
    live: bool | None = None,
    limit: int | None = None,
    base_url: str | None = None,
    offset: int = 0,
    settled: Collection[str] = (),
) -> LinkReport:
    """Open each of a bookmaker's per-event deep links and report what served.

    A bookmaker that declares no per-event route is skipped without launching a
    browser: there is no route to check, and "we never tried" must never be
    reported as a failure.

    ``offset`` and ``settled`` are the cursor (see :func:`build_targets`). The
    report then says where this run stopped and how much is left:

    * ``next_offset`` = ``offset + len(targets)`` — the position to resume from
      **in the post-skip ordering**, so only comparable against a run that
      skipped the same ``settled`` set,
    * ``remaining`` = the undecided targets this run did not reach, counted from
      that position onwards. It is the same number as :attr:`LinkReport.unchecked`
      — ``available`` already excludes what the cursor passed. An event this run
      REACHED but that errored is therefore not counted in ``remaining``: it is
      in ``errored``, and because an error is not a decision it is not in the
      caller's next ``settled`` set, so the next run offers it again.
    """
    started = datetime.now(UTC)
    if not supports_event_id(bookmaker):
        return LinkReport(
            bookmaker=bookmaker,
            mode=mode,
            status="skipped",
            skip_reason=f"{bookmaker} declares no declared event route — nothing to verify",
        )

    if live is None:
        live = mode == "live"
    base_url = base_url or str(BOOKMAKERS[bookmaker]["base_url"])
    available = build_targets(
        matches, bookmaker, base_url, live=live, offset=offset, settled=settled
    )
    if not available:
        # Nothing to check: report it instead of paying for a browser launch.
        return LinkReport(
            bookmaker=bookmaker,
            mode=mode,
            status="checked",
            skip_reason=(
                f"no {bookmaker} match carries an undecided event id — nothing to check "
                "(run a scan first, or every event has already been decided)"
            ),
            duration_seconds=round((datetime.now(UTC) - started).total_seconds(), 2),
        )
    targets = available[:limit] if limit else available

    from scrapers.base import launch_browser  # imported late: browser startup is expensive

    playwright, browser, context = await launch_browser()
    report = LinkReport(
        bookmaker=bookmaker, mode=mode, status="checked", available=len(available)
    )
    try:
        page = await context.new_page()
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        for target in targets:
            report.outcomes.append(await check_target(page, target, base_url))
    finally:
        try:
            await context.close()
            await browser.close()
            await playwright.stop()
        except Exception:  # pragma: no cover - cleanup is best effort
            pass

    report.checked = len(report.outcomes)
    report.verified = sum(1 for o in report.outcomes if o.verified)
    report.failed = sum(1 for o in report.outcomes if o.completed and not o.verified)
    report.errored = sum(1 for o in report.outcomes if o.error)
    report.next_offset = max(0, offset) + len(targets)
    report.remaining = max(0, len(available) - len(targets))
    report.duration_seconds = round((datetime.now(UTC) - started).total_seconds(), 2)
    return report


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _load_cached_matches(mode: str) -> list[dict]:
    path = os.path.join(CACHE_DIR, "last_live_scan.json" if mode == "live" else "last_scan.json")
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file).get("matches", [])
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bookmakers", nargs="*", help="bookmaker ids (default: every declared one)")
    parser.add_argument("--mode", default="prematch", choices=("prematch", "live"))
    parser.add_argument("--limit", type=int, default=3, help="max events per bookmaker")
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help=(
            "resume at this undecided event (0 = the first one). The CLI has no store of "
            "its own cursor, so this is how a sweep is driven here; the HTTP endpoint derives "
            "the equivalent from the events it has already decided"
        ),
    )
    args = parser.parse_args(argv)

    books = args.bookmakers or [b for b in BOOKMAKERS if supports_event_id(b)]
    matches = _load_cached_matches(args.mode)
    for bookmaker in books:
        if bookmaker not in BOOKMAKERS:
            print(json.dumps({"bookmaker": bookmaker, "error": "unknown bookmaker"}))
            continue
        report = asyncio.run(
            verify_bookmaker(
                bookmaker, matches, mode=args.mode, limit=args.limit, offset=args.offset
            )
        )
        # Store the verdicts exactly as `POST /api/verify-links` does, so the next
        # scan applies the proofs. Imported here: the server module loads its
        # state files on import, which only this branch needs.
        from server import api

        # Merge into what is already stored, never replace it: the module's
        # stores start empty until the server's startup loads them.
        if not api._deep_link_verifications:
            api._deep_link_verifications.update(api._load_deep_link_verifications())
        if not api._deep_link_decisions:
            api._deep_link_decisions.update(api._load_deep_link_decisions())
        api._record_deep_link_outcomes(args.mode, bookmaker, report.outcomes)
        api._record_deep_link_decisions(args.mode, bookmaker, report.outcomes)
        # `asdict`, not `__dict__`: a report's `outcomes` are `LinkOutcome`s, which
        # are not JSON-serialisable, so printing `__dict__` raised TypeError on the
        # first completed check — the command in this module's own docstring.
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
