"""Deep-link builders and per-book event-id declarations."""
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from config.settings import BOOKMAKERS
from scrapers import common
from scrapers.common import build_event_url

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_config() -> dict:
    with open("config/bookmaker_deeplinks.json", encoding="utf-8") as f:
        return json.load(f)


def test_mdshop_builds_per_event_url():
    url = build_event_url("mdshop", "12345", "https://www.mdshop.ba")
    assert "event=12345" in url
    assert url.startswith("https://www.mdshop.ba/")


def test_wwin_declares_no_per_event_support():
    url = build_event_url("wwin", "12345", "https://wwin.ba")
    assert url == "https://wwin.ba/kladjenje/"


def test_unknown_book_returns_base_url():
    url = build_event_url("unknownbook", "1", "https://example.test")
    assert url == "https://example.test/"


def test_deeplink_config_covers_every_configured_bookmaker():
    assert set(BOOKMAKERS) == set(_read_config())


def test_false_declarations_have_no_event_link_notes():
    for bookmaker, spec in _read_config().items():
        if spec["supports_event_id"] is False:
            assert spec.get("note"), f"{bookmaker} needs a no-event-link note"


def test_true_declarations_have_event_placeholders():
    for bookmaker, spec in _read_config().items():
        if spec["supports_event_id"] is True:
            assert "{event_id}" in spec["template"], f"{bookmaker} template lacks event_id"
            if "template_live" in spec:
                assert "{event_id}" in spec["template_live"], (
                    f"{bookmaker} live template lacks event_id"
                )


def test_live_template_is_used_for_supported_book():
    url = build_event_url(
        "mdshop", "12345", "https://www.mdshop.ba", live=True
    )
    assert url == "https://www.mdshop.ba/sport-live?event=12345"


def test_mozzartbet_live_template_uses_public_event_route():
    url = build_event_url(
        "mozzartbet", "73601748", "https://www.mozzartbet.ba", live=True
    )
    assert url == "https://www.mozzartbet.ba/sr/uzivo/mec/1/73601748"


def test_empty_event_id_uses_non_event_url():
    assert build_event_url("mdshop", "", "https://www.mdshop.ba") == (
        "https://www.mdshop.ba/"
    )


def test_none_event_id_uses_non_event_url():
    assert build_event_url("mdshop", None, "https://www.mdshop.ba") == (
        "https://www.mdshop.ba/"
    )


def test_event_id_is_url_encoded():
    url = build_event_url("mdshop", "12&x=3", "https://www.mdshop.ba")
    assert url == "https://www.mdshop.ba/sport-prematch?sport=Fudbal&event=12%26x%3D3"


def test_true_template_without_placeholder_is_rejected(monkeypatch):
    monkeypatch.setattr(
        common,
        "_deeplink_cache",
        {
            "broken": {
                "supports_event_id": True,
                "template": "https://example.test/no-event",
            }
        },
    )
    with pytest.raises(ValueError, match="event_id"):
        build_event_url("broken", "42", "https://example.test")


# ===========================================================================
# The tripwire on a wrongly-declared book (I4)
# ===========================================================================
#
# `scripts/verify_deeplinks.py` returns `status="skipped"` for any book whose
# `supports_event_id` is not True, so the one tool that could catch a wrong
# `false` is switched off for exactly the six books where it would matter. What
# is left is the browser re-verification the implementer named, which needs a
# browser and cannot be automated.
#
# The structural check that needs no browser: a book declared
# `supports_event_id: false` is declaring that it has no per-event route, so
# every match it captures must carry its non-event fallback. The day a bookmaker
# adds per-event routes, its scraper starts emitting them and the captured feed
# stops matching the declaration — which is the drift that would silently widen
# what the gate accepts on a declaration that is no longer true. It holds on the
# captured corpus today, and it costs one dict lookup per match.


def _comparable(url: str) -> str:
    """Reduce a URL to the parts a per-event route would actually change.

    Path and query are kept byte for byte: a per-event route differs there, which
    is the whole detection mechanism. What is folded is host case, a leading
    ``www.``, and a trailing slash — none of which makes a URL event-scoped.

    The ``www.`` fold is not cosmetic. `cache/last_scan.json` carries MBet at
    `https://mbet.ba/`, because `scrapers/mbet.py:532` hard-codes that host,
    while the declared fallback is `https://www.mbet.ba/`. Those are the same
    page, so a byte comparison would have failed on the correct data and taught
    everyone to ignore this test. Three of the four declared-false books in the
    capture are byte-identical to their declaration; MBet differs only by the
    alias. A bookmaker that changed only its fallback's ``www.`` would not be
    caught, and that is the accepted limit — it is not a per-event route.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def _declared_false_url_drift(matches: list[dict], declarations: dict) -> list[str]:
    """Return one string per captured match that contradicts a `false` declaration.

    A book is only in scope when it is *declared* false: a declared-true book
    carrying a per-event URL is the design working, and a book with no
    declaration has made no claim to contradict.
    """
    drift: list[str] = []
    for match in matches:
        bookmaker = match.get("bookmaker")
        spec = declarations.get(bookmaker)
        if not isinstance(spec, dict) or spec.get("supports_event_id") is not False:
            continue
        url = match.get("url")
        fallback = spec.get("template")
        if not url or not isinstance(fallback, str):
            continue
        if _comparable(url) != _comparable(fallback):
            drift.append(
                f"{bookmaker}: captured {url!r}, declared no per-event route with "
                f"fallback {fallback!r}"
            )
    return drift


def _declared_false_books() -> list[str]:
    return sorted(
        book
        for book, spec in _read_config().items()
        if spec.get("supports_event_id") is False
    )


def _fallback_corpus(declarations: dict) -> list[dict]:
    """One match per declared-false book, each carrying exactly its fallback URL."""
    return [
        {
            "bookmaker": book,
            "url": declarations[book]["template"],
            "event_id": f"{book}-event-1",
            "deep_link_verified": False,
        }
        for book in _declared_false_books()
    ]


@pytest.mark.real_deeplinks
def test_a_declared_no_route_book_never_carries_a_per_event_url_in_the_capture():
    """The captured scan must agree with every `supports_event_id: false`.

    Reads `cache/last_scan.json`, which is gitignored (`.gitignore:20`), so a
    fresh clone has no corpus and this SKIPS rather than passing — the skip is
    the point of the next test, which exercises the same predicate on data built
    from the config and therefore runs everywhere.
    """
    cache = REPO_ROOT / "cache" / "last_scan.json"
    if not cache.exists():
        pytest.skip(
            f"{cache} is absent (cache/*.json is gitignored); this corpus check needs a "
            "real scan. The predicate itself is covered unconditionally by "
            "test_the_declared_no_route_url_check_catches_a_per_event_url"
        )
    scan = json.loads(cache.read_text(encoding="utf-8"))
    matches = scan["matches"]
    declarations = _read_config()
    in_scope = [
        m
        for m in matches
        if declarations.get(m.get("bookmaker"), {}).get("supports_event_id") is False
    ]
    assert in_scope, (
        f"the captured scan holds no declared-false book, so this check is vacuous; "
        f"re-capture ({cache} has {len(matches)} matches)"
    )
    drift = _declared_false_url_drift(matches, declarations)
    assert drift == [], "; ".join(sorted(set(drift)))


@pytest.mark.parametrize("bookmaker", _declared_false_books())
def test_the_declared_no_route_url_check_catches_a_per_event_url(bookmaker):
    """Proves the check above is real, for every book it has to cover.

    Two directions, on a corpus built from the config so it runs without a scan:
    the declared fallback is clean, and the same book emitting a plausible
    per-event URL is reported. The mutation is written per book rather than once
    for mbet, because the URLs a real bookmaker would ship differ in shape
    (`/utakmica/<id>`, `?event=<id>`, a host-level path), and a check that only
    catches one book's habit is not a check.
    """
    declarations = _read_config()
    assert declarations[bookmaker]["supports_event_id"] is False, (
        f"{bookmaker} no longer declares a false route; this test's premise is gone"
    )
    clean = _fallback_corpus(declarations)
    assert _declared_false_url_drift(clean, declarations) == [], (
        f"{bookmaker} carrying its own declared fallback was reported as drift, so the "
        "check would fire on correct data"
    )

    for per_event_url in (
        f"https://www.example.test/match/{bookmaker}-event-1",
        f"https://www.example.test/?event={bookmaker}-event-1",
        f"https://www.example.test/{bookmaker}/event-1",
    ):
        drifted = [dict(match) for match in clean]
        for match in drifted:
            if match["bookmaker"] == bookmaker:
                match["url"] = per_event_url
        problems = _declared_false_url_drift(drifted, declarations)
        assert any(bookmaker in problem for problem in problems), (
            f"{bookmaker} emitting {per_event_url!r} was not reported; the check cannot "
            "catch the drift it exists for"
        )
        assert len(problems) == 1, (
            f"{bookmaker} emitting {per_event_url!r} produced {problems}; exactly one "
            "book drifted, so only one report is correct"
        )


def test_the_declared_no_route_url_check_ignores_books_that_claim_a_route():
    """A declared-true book carrying a per-event URL is the design, not drift."""
    declarations = _read_config()
    corpus = [
        {
            "bookmaker": "mozzartbet",
            "url": "https://www.mozzartbet.ba/sr/kladjenje/sport/1/match/6676802",
            "event_id": "6676802",
            "deep_link_verified": False,
        },
        # A book with no declaration has claimed nothing to contradict either.
        {
            "bookmaker": "undeclared-book",
            "url": "https://undeclared.test/match/1",
            "event_id": "1",
            "deep_link_verified": False,
        },
    ]
    assert _declared_false_url_drift(corpus, declarations) == []


# ===========================================================================
# P0-5: declarations reload without a process restart
# ===========================================================================


def _point_at(monkeypatch, path: Path) -> None:
    """Point the loader at a temp file and clear the previous load's state."""
    monkeypatch.setattr(common, "_DEEPLINK_CONFIG_PATH", str(path))
    common._deeplink_cache = None
    common._deeplink_cache_signature = None
    common._deeplink_source_mtime = None
    common._deeplink_loaded_at = None
    common._deeplink_load_error = None


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_declaration_change_is_picked_up_without_restart(tmp_path, monkeypatch):
    path = tmp_path / "bookmaker_deeplinks.json"
    _write(path, {"demo": {"supports_event_id": False, "template": "https://demo.test/"}})
    _point_at(monkeypatch, path)

    assert common.supports_event_id("demo") is False
    first = common.deeplink_declaration_source()
    assert first["stale"] is False
    assert first["loaded_at"] is not None
    assert first["source_mtime"] is not None

    _write(
        path,
        {
            "demo": {
                "supports_event_id": True,
                "template": "https://demo.test/event/{event_id}",
            }
        },
    )

    # No restart, no second loader instance: the next lookup sees the edit.
    assert common.supports_event_id("demo") is True
    effective = common.effective_deeplink_declarations(["demo"])["demo"]
    assert effective["supports_event_id"] is True
    assert effective["declared_no_event_id"] is False
    assert effective["stale"] is False
    assert effective["loaded_at"] is not None
    assert effective["source_mtime"] is not None


def test_a_malformed_file_fails_safe_and_says_so(tmp_path, monkeypatch):
    path = tmp_path / "bookmaker_deeplinks.json"
    _write(path, {"demo": {"supports_event_id": False, "template": "https://demo.test/"}})
    _point_at(monkeypatch, path)
    assert common.declares_no_event_id("demo") is True

    path.write_text('{"demo": ', encoding="utf-8")

    assert common._load_deeplink_config() == {}, (
        "a malformed declaration file must not preserve trust from the old map"
    )
    assert common.declares_no_event_id("demo") is False
    source = common.deeplink_declaration_source()
    assert source["stale"] is True
    assert source["error"]

    # Fixing the file is picked up on the next call, without a restart.
    _write(path, {"demo": {"supports_event_id": False, "template": "https://demo.test/"}})
    assert common.declares_no_event_id("demo") is True
    assert common.deeplink_declaration_source()["stale"] is False


def test_health_reports_the_declaration_source_and_a_bad_file_safely(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from server.app import app

    path = tmp_path / "bookmaker_deeplinks.json"
    _write(path, {"demo": {"supports_event_id": False, "template": "https://demo.test/"}})
    _point_at(monkeypatch, path)
    client = TestClient(app)

    body = client.get("/api/health").json()
    source = body["deep_link_declaration_source"]
    assert source["stale"] is False
    assert source["loaded_at"] is not None
    assert source["source_mtime"] is not None
    assert body["deep_link_declarations"]["demo"]["loaded_at"] == source["loaded_at"]

    path.write_text("not json", encoding="utf-8")
    body = client.get("/api/health").json()
    source = body["deep_link_declaration_source"]
    assert source["stale"] is True
    assert source["error"]
    # The malformed file is visible and grants nothing; health still answers.
    assert body["deep_link_declarations"]["wwin"]["configured"] is False
    assert body["deep_link_declarations"]["wwin"]["declared_no_event_id"] is False
