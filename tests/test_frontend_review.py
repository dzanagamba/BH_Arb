"""Frontend Review contract tests: static hooks plus source-derived reason coverage."""
import ast
import re
from pathlib import Path

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")
CSS = Path("frontend/css/style.css").read_text(encoding="utf-8")
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


def _js_function_body(name: str) -> str:
    """The body of a small top-level JS function, for a recursion check."""
    match = re.search(rf"function {re.escape(name)}\([^)]*\) \{{(.*?)\n\}}", JS, re.DOTALL)
    assert match, f"{name}() is missing"
    return match.group(1)


def test_reason_label_helpers_look_up_their_table_instead_of_recurring():
    """A self-call here used to overflow the stack on the first gate reason.

    The dashboard then showed 0 surebets and 'Could not load candidates' even
    when the API held results. Pin the lookup, not just the label table.
    """
    for function, table in (
        ("reasonLabel", "REASON_LABELS"),
        ("feedReasonLabel", "FEED_REASON_LABELS"),
    ):
        body = _js_function_body(function)
        assert f"{table}[" in body, f"{function}() must read {table}"
        assert f"{function}(" not in body, f"{function}() calls itself"


def test_api_fetch_keeps_the_callers_content_type():
    """`apiFetch` merges the API key into the caller's headers, not over them.

    Dropping `Content-Type: application/json` made every JSON POST arrive as
    text/plain and fail with a 422, including the odds re-check.
    """
    body = _js_function_body("candidateActionHeaders")
    assert "{ ...headers }" in body
    assert "X-API-Key" in body


def test_switching_feed_refreshes_the_health_diagnostics_immediately():
    """Results/candidates are reloaded on a mode switch; health must be too.

    Without this, the Live tab showed the previous prematch queue and scan cost
    until the 30-second health poll.
    """
    body = _js_function_body("switchMode")
    assert "currentMode = mode" in body
    assert "loadResults(true)" in body
    assert "loadHealth()" in body


def test_paper_summary_subtitles_wrap_instead_of_clipping():
    assert ".paper-summary .kpi-sub" in CSS
    rule = CSS[CSS.index(".paper-summary .kpi-sub"):]
    rule = rule[: rule.index("}")]
    assert "white-space: normal" in rule
    assert "overflow: visible" in rule


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
    assert "closeable_only=true" in JS, (
        "N2-3 includes league mappings, so the tab must ask for every pair a "
        "mapping can close, not only the alias-actionable ones"
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


def test_recurring_blocker_panel_and_proposals_are_read_only():
    """N2-3: the panel ranks review work; no control applies a suggestion."""
    assert 'id="remediation-panel"' in HTML
    assert 'id="remediation-groups"' in HTML
    assert "REMEDIATION_LABELS" in JS
    assert "renderRemediation" in JS
    assert "candidate.remediation" in JS
    assert "proposal only" in JS
    assert "coverage-progress claim" in HTML
