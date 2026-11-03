"""Frontend Review contract tests: static hooks plus source-derived reason coverage."""
import ast
import re
from pathlib import Path

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
CERTAINTY_SOURCE = Path("engine/certainty.py")
KNOWN_REASON_CODES = frozenset(
    {
        "league_mismatch",
        "kickoff_missing",
        "kickoff_delta",
        "category_mismatch",
        "betradar_mismatch",
        "team_unresolved",
        "orientation_unresolved",
        "link_unverified",
        "no_event_link",
    }
)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _string_literals(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else set()
    if isinstance(node, ast.Set | ast.List | ast.Tuple):
        return set().union(*(_string_literals(element) for element in node.elts))
    if isinstance(node, ast.Call):
        return set().union(*(_string_literals(argument) for argument in node.args))
    if isinstance(node, ast.BoolOp):
        return set().union(*(_string_literals(value) for value in node.values))
    if isinstance(node, ast.IfExp):
        return _string_literals(node.body) | _string_literals(node.orelse)
    return set()


def _source_reason_codes() -> set[str]:
    """Extract literals only from the gate's reason sinks, not all source strings."""
    tree = ast.parse(CERTAINTY_SOURCE.read_text(encoding="utf-8"))
    reason_codes: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            target_names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if "HARD_REJECT_REASONS" in target_names:
                reason_codes.update(_string_literals(node.value))
        if isinstance(node, ast.Call):
            function_name = _dotted_name(node.func)
            if function_name in {
                "reasons.append",
                "reasons.extend",
                "result.reasons.append",
                "result.reasons.extend",
                "link_reasons.add",
            }:
                reason_codes.update(_string_literals(node))
            if function_name == "GateResult":
                for keyword in node.keywords:
                    if keyword.arg == "reasons":
                        reason_codes.update(_string_literals(keyword.value))

    return reason_codes


def _reason_labels() -> dict[str, str]:
    match = re.search(
        r"const REASON_LABELS = Object\.freeze\((\{.*?\n\});",
        JS,
        flags=re.DOTALL,
    )
    assert match, "REASON_LABELS lookup is missing"
    labels = re.findall(
        r"^\s*([a-z][a-z0-9_]*):\s*'([^']*)'",
        match.group(1),
        re.MULTILINE,
    )
    return dict(labels)


def _missing_reason_labels(reason_codes: set[str], labels: dict[str, str]) -> list[str]:
    return sorted(code for code in reason_codes if not labels.get(code, "").strip())


def test_index_has_review_tab():
    assert 'id="review-tab"' in HTML
    assert 'id="candidates-list"' in HTML


def test_js_has_read_only_candidate_hooks():
    assert "loadCandidates" in JS
    assert "renderCandidates" in JS
    assert "/api/candidates" in JS
    assert "readOnlyNote" in JS
    assert "approveCandidate" not in JS
    assert "rejectCandidate" not in JS


def test_status_badge_never_claims_verified_without_backend_status():
    assert 'class="status-badge status-verified"' not in HTML
    assert "|| 'verified'" not in JS
    assert "statusEl.hidden = true" in JS
    assert "statusEl.hidden = false" in JS


def test_candidate_reads_use_the_existing_api_key_header():
    assert "'X-API-Key'" in JS
    assert "window.prompt" in JS
    assert "candidateActionHeaders" in JS


def test_candidate_queue_is_read_as_a_bounded_page():
    """A full scan queues five figures; the tab polls every 30s."""
    assert "CANDIDATE_PAGE_SIZE" in JS
    assert "limit=${CANDIDATE_PAGE_SIZE}" in JS
    assert "offset=0" in JS
    assert "actionable_only=true" in JS, (
        "the tab must ask for the pairs an approval can clear, not the whole "
        "refused population: the rest carry an Approve button that cannot work"
    )
    assert "data.total" in JS
    assert "actionable_total" in JS
    assert "readOnlyNote" in JS


def test_candidate_queue_read_requires_the_api_key_when_configured():
    assert "candidateListFetch" in JS
    assert "candidateActionHeaders()" in JS
    read_call = JS[JS.index("async function candidateListFetch"):JS.index("async function loadCandidates")]
    assert "401" in read_call


def test_candidate_card_shows_both_spellings_and_is_read_only():
    assert "candidate.team_positions" in JS
    assert "position.team_a" in JS and "position.team_b" in JS
    assert "candidate.link_blocked" in JS
    assert "readOnlyNote" in JS
    assert "ledger learns this pairing automatically" in JS


def test_candidate_card_has_no_approval_controls():
    assert "Approve pairing" not in JS
    assert "Reject pairing" not in JS
    assert "data-candidate-select" not in JS


def test_candidate_card_offers_only_a_web_check():
    assert "Check on the web" in JS
    assert "candidate.alias_actionable" not in JS


def test_candidate_card_links_to_a_web_check_before_approval():
    """The reviewer has to be able to confirm both spellings are one fixture."""
    assert "fixtureSearchUrl" in JS
    assert "https://www.google.com/search?q=" in JS
    assert "Check on the web" in JS
    assert "target=\"_blank\"" in JS
    assert "rel=\"noopener noreferrer\"" in JS


def test_review_intro_says_the_view_is_read_only():
    assert "This view is read-only" in HTML
    assert "the evidence ledger learns" in HTML


def test_empty_review_is_read_only():
    assert "No actionable pairings." in JS
    assert "the ledger learns them automatically" in JS


def test_negative_ai_verdict_sorts_last_regardless_of_confidence():
    assert "ai_same_event === false" in JS
    assert "return leftNegative ? 1 : -1" in JS


def test_source_reason_extraction_is_nonempty():
    reason_codes = _source_reason_codes()
    assert reason_codes
    assert KNOWN_REASON_CODES <= reason_codes


def test_reason_labels_cover_source_derived_reason_codes():
    labels = _reason_labels()
    reason_codes = _source_reason_codes()
    assert _missing_reason_labels(reason_codes, labels) == []
    # Guard the detector itself: a deliberately absent label must be reported.
    assert _missing_reason_labels({"intentional_missing_reason"}, labels) == [
        "intentional_missing_reason"
    ]


def test_partial_acceptance_can_be_recorded():
    """A book that takes only part of a stake must feed the real amount back."""
    assert "data-placed-stake" in JS
    assert "Stake accepted" in JS
    assert "state.placed[label] = { odds, stake }" in JS


def test_rendered_links_are_scheme_checked():
    assert "function safeUrl" in JS
    assert "parsed.protocol === 'http:'" in JS
    assert "escapeHtml(safeUrl(url))" in JS
