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
