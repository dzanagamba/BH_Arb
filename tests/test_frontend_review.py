"""Frontend Review contract tests: static hooks plus backend-reason coverage."""
import re
from datetime import datetime, timedelta
from pathlib import Path

from engine.certainty import HARD_REJECT_REASONS, CertaintyGate
from models.schemas import Match

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
KICKOFF = datetime(2026, 9, 25, 18, 0)


def _match(
    bookmaker: str,
    home: str,
    away: str,
    league: str,
    *,
    kickoff: datetime | None = KICKOFF,
    home_normalized: str | None = None,
    away_normalized: str | None = None,
    category_tags: list[str] | None = None,
    event_id: str = "event",
    url: str = "",
    link_verified: bool = True,
) -> Match:
    return Match(
        bookmaker=bookmaker,
        home_team=home,
        away_team=away,
        home_team_normalized=home_normalized or home.lower(),
        away_team_normalized=away_normalized or away.lower(),
        league=league,
        kickoff=kickoff,
        category_tags=category_tags or [],
        event_id=event_id,
        url=url,
        deep_link_verified=link_verified,
    )


def _gate_reason_codes() -> set[str]:
    gate = CertaintyGate()
    pairs = [
        (
            _match("a", "Alpha", "Beta", "League A"),
            _match("b", "Alpha", "Beta", "League B"),
        ),
        (
            _match("a", "Alpha", "Beta", "League A"),
            _match("b", "Alpha", "Beta", "League A", kickoff=None),
        ),
        (
            _match("a", "Alpha", "Beta", "League A"),
            _match("b", "Alpha", "Beta", "League A", kickoff=KICKOFF + timedelta(minutes=45)),
        ),
        (
            _match("a", "Alpha", "Beta", "League A"),
            _match("b", "Alpha", "Beta", "League A", category_tags=["U21"]),
        ),
        (
            _match("a", "Alpha", "Beta", "League A"),
            _match("b", "Gamma", "Delta", "League A"),
        ),
        (
            _match(
                "a",
                "Alpha",
                "Beta",
                "League A",
                event_id="",
                url="https://example.test/alpha",
                link_verified=False,
            ),
            _match("b", "Alpha", "Beta", "League A", event_id="verified"),
        ),
        (
            _match("a", "Alpha", "Beta", "League A", event_id="", link_verified=False),
            _match("b", "Alpha", "Beta", "League A", event_id="", link_verified=False),
        ),
    ]
    reasons = set(HARD_REJECT_REASONS)
    for left, right in pairs:
        reasons.update(gate.evaluate_pair(left, right).reasons)
    return reasons


def _reason_labels() -> dict[str, str]:
    match = re.search(
        r"const REASON_LABELS = Object\.freeze\((\{.*?\n\});",
        JS,
        flags=re.DOTALL,
    )
    assert match, "REASON_LABELS lookup is missing"
    labels = re.findall(r"^\s*([a-z][a-z0-9_]*):\s*'([^']*)'", match.group(1), re.MULTILINE)
    return dict(labels)


def test_index_has_review_tab():
    assert 'id="review-tab"' in HTML
    assert 'id="candidates-list"' in HTML


def test_js_has_candidate_hooks():
    assert "loadCandidates" in JS
    assert "renderCandidates" in JS
    assert "/api/candidates" in JS
    assert "approveCandidate" in JS
    assert "rejectCandidate" in JS


def test_status_badge_never_claims_verified_without_backend_status():
    assert 'class="status-badge status-verified"' not in HTML
    assert "|| 'verified'" not in JS
    assert "statusEl.hidden = true" in JS
    assert "statusEl.hidden = false" in JS


def test_candidate_actions_use_the_existing_api_key_header():
    assert "'X-API-Key'" in JS
    assert "window.prompt" in JS
    assert "candidateActionFetch" in JS


def test_reason_labels_cover_reason_codes_the_gate_can_emit():
    labels = _reason_labels()
    reason_codes = _gate_reason_codes()
    assert reason_codes <= labels.keys()
    assert all(labels[reason_code].strip() for reason_code in reason_codes)
