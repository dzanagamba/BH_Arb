"""Every checkable claim in README.md and PLAN.md, compared to the code it describes.

WHY THIS FILE EXISTS
--------------------
Four claims in this plan were corrected for describing something other than what
the code or data did. Each correction was caught by a human re-reading, never by
the suite. This file is the automation for that class of defect: it reads the
documentation and the implementation and fails when they disagree.

THE RULE THAT SHAPES EVERY TEST HERE
------------------------------------
**A check that never opens the document is not a doc-claim check.** It is a no-op
that confirms the code still says what it said, and it occupies a test slot while
guarding nothing. So two rules hold throughout:

1. Every predicate below takes the document's text and is called with the real
   ``README.md`` *and* with the implementation's current values. Where the naive
   version of a check inspected only one side, the missing side is now explicit:
   the ``AI_*`` defaults compare the README's table against ``engine/ai.py``, and
   the reason vocabulary is produced by *running* the gate rather than by
   grepping it.
2. **Every predicate is proved capable of failing.** Each has a companion
   ``test_*_fails_*`` that breaks the document the way that predicate is supposed
   to catch and asserts the predicate notices. A predicate with no companion is a
   no-op wearing a test's name, and
   ``test_every_doc_predicate_is_proven_capable_of_failing`` fails on any
   predicate that lacks one.

Rule 2 is the structural answer to this file's own first draft, in which three
checks were labelled doc-vs-code but only inspected the code, and the single
check guarding the approval boundary required two words to appear *anywhere* in
a 180-line file. Deleting the sentence the brief singled out left that check
green. It is now scoped to one paragraph inside one section.

THE HEADLINE IS A DATED MEASUREMENT, NOT A REPO FACT
-----------------------------------------------------
"MDShop's and Admiralbet's ``?event=<id>`` routes are inert" cannot be derived
from this repository; it is what a browser saw on 2026-09-25. What the repo *can*
reproduce is which books declare a per-event route at all, so that is what the
headline checks compare, and the README now tells a reader which part is which.
Nothing here asserts that a route works, or that it fails to work.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from engine.ai import MatchAI
from engine.certainty import HARD_REJECT_REASONS, CertaintyGate
from models.schemas import Market, MarketType, Match, OddsValue
from server import api, app

REPO_ROOT = Path(__file__).resolve().parent.parent
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
PLAN = (REPO_ROOT / "PLAN.md").read_text(encoding="utf-8")

# A backticked bare identifier. The tables legitimately enumerate paths, URLs,
# numbers and prose as well, and only these can be a claim about a name.
_TOKEN = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")

_LIST_ITEM = re.compile(r"^\s*(?:[*\-]|\d+\.)\s")


def _claims(text: str) -> list[str]:
    """Logical claims: a blank-line-separated block, or a single list item.

    Whitespace-collapsed to one string each. Claims rather than lines, because
    the README wraps at 79 columns and a line-scoped check would be testing the
    formatter. Claims rather than the whole file, and *finer* than paragraphs,
    because a run of adjacent bullets is one paragraph: scoping the approval
    boundary to a paragraph let a neighbouring bullet's "never" stand in for the
    prohibition, which is the bug this file's first draft shipped.
    """
    claims: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                claims.append(current)
                current = []
            continue
        if _LIST_ITEM.match(line) and current:
            claims.append(current)
            current = []
        current.append(stripped)
    if current:
        claims.append(current)
    return [re.sub(r"\s+", " ", " ".join(claim)).strip() for claim in claims]


def _section(text: str, heading: str) -> str:
    """The body of one ``## heading``, up to the next ``## ``."""
    start = text.index(heading) + len(heading)
    rest = text[start:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _callout(text: str) -> str:
    """The block-quoted status callout at the top of the document, unwrapped."""
    return "\n".join(
        line.lstrip().lstrip(">").strip()
        for line in text.splitlines()
        if line.lstrip().startswith(">")
    )


def _row(text: str, first_cell: str) -> list[str]:
    """The cells of the ``| ... |`` table row whose first cell is exact."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and cells[0] == first_cell:
            return cells
    raise AssertionError(f"no table row whose first cell is {first_cell!r}")


# ===========================================================================
# 1. The headline
# ===========================================================================


def _deeplink_config() -> dict[str, dict]:
    """The whole deep-link declaration, keyed by bookmaker."""
    raw = json.loads(
        (REPO_ROOT / "config" / "bookmaker_deeplinks.json").read_text(encoding="utf-8")
    )
    return {book: cfg for book, cfg in raw.items() if isinstance(cfg, dict)}


def _declaring_books() -> set[str]:
    """The books that declare a per-event deep-link route at all."""
    return {
        book for book, cfg in _deeplink_config().items()
        if cfg.get("supports_event_id") is True
    }


def _headline_problems(text: str) -> list[str]:
    """Everything wrong with the callout claim about the declared-route books.

    Scoped to the single callout claim that says the routes are inert, and within
    it to the *sentence* that says so. The callout also holds a "how to re-check
    this" claim that names all three declared books, so scoping to the callout or
    the file would credit the inertness to a mention meant for something else.
    """
    problems: list[str] = []
    callout = _callout(text)
    headline = next(
        (claim for claim in _claims(callout) if "inert" in claim.lower()), ""
    )
    if not headline:
        return ["no callout claim states that the declared routes are inert"]
    if not re.search(r"[Oo]nly Mozzartbet", headline):
        problems.append("the headline never names Mozzartbet as the one verifying link")

    declaring = _declaring_books()
    sentences = re.split(r"(?<=[.!?])\**\s+", headline)
    inert = [s for s in sentences if "inert" in s.lower()]
    if not inert:
        problems.append("no sentence in the headline calls any route inert")
        return problems
    spoken = " ".join(inert).lower()
    # Over EVERY book the repo knows, not just the ones declaring a route: naming
    # a book with no per-event route as inert is as wrong as naming the wrong
    # pair, and a set built from `declaring` alone could never see it.
    named = {book for book in _deeplink_config() if book.lower() in spoken}
    if named != {"mdshop", "admiralbet"}:
        problems.append(
            f"the sentence calling routes inert names {sorted(named) or 'no book'}; it "
            f"must name exactly the two declared books with inert routes, and the "
            f"books declaring a route are {sorted(declaring)}"
        )
    # Every declared book must be accounted for: if a fourth book ever declares a
    # route, this fails until the headline says something about it.
    unaccounted = declaring - named - {"mozzartbet"}
    if unaccounted:
        problems.append(
            f"the headline says nothing about declared-route book(s) {sorted(unaccounted)}"
        )
    return problems


def test_headline_names_exactly_the_declared_but_inert_books():
    """The headline's book names match ``config/bookmaker_deeplinks.json``.

    The two books the headline calls inert, and only those, may be among the books
    declaring a per-event route -- and the one it names as working must be too.
    The inertness itself is a dated browser measurement this file cannot derive,
    which is why the README says so and points at the script.
    """
    assert _declaring_books() == {"admiralbet", "mdshop", "mozzartbet"}, (
        "the declared-route set changed, so the README headline naming three books "
        "must be revisited before this test can be trusted"
    )
    problems = _headline_problems(README)
    assert problems == [], "; ".join(problems)


def test_headline_check_fails_when_a_book_is_unlinked_from_the_inertness():
    """Proves the previous test reads the headline, not the whole document.

    The broken copy still names both books in "What it does" and in the re-check
    claim -- as the real one does -- so only a headline-scoped check catches this.
    """
    broken = README.replace(
        "MDShop's and Admiralbet's declared `?event=<id>` routes are **inert**",
        "MDShop's and Admiralbet's declared `?event=<id>` routes are **active**",
    )
    assert broken != README, "the mutation did not apply; the check is untested"
    assert "mdshop" in broken.lower() and "admiralbet" in broken.lower(), (
        "the broken copy must still name both books elsewhere, or this proves nothing"
    )
    problems = _headline_problems(broken)
    assert problems, "a headline calling the routes 'active' passed the check"
    assert any("inert" in problem for problem in problems)


def test_headline_check_fails_when_a_route_less_book_is_called_inert():
    """A book with no per-event route cannot be named as having an inert one.

    Betole declares `supports_event_id: false` — it has no `?event=<id>` route at
    all, so there is nothing about it to be inert. The first version of the
    headline check built its set of named books from the books that *declare* a
    route, so a book outside that set could be named in the inertness sentence and
    the check could not see it. This drives exactly that.
    """
    assert "betole" in _deeplink_config()
    assert "betole" not in _declaring_books(), (
        "betole now declares a route, so this companion no longer tests what it says"
    )
    broken = README.replace(
        "MDShop's and Admiralbet's declared `?event=<id>` routes are **inert**",
        "MDShop's, Admiralbet's and Betole's `?event=<id>` routes are **inert**",
    )
    assert broken != README, "the mutation did not apply; the check is untested"
    problems = _headline_problems(broken)
    assert problems, (
        "naming a book that declares no per-event route as having an inert one passed"
    )
    assert any("betole" in problem for problem in problems)


# The callout's statement of what the link half of `verified` requires, checked
# against the gate instead of against the prose. Both books are read from
# `config/bookmaker_deeplinks.json`, so this cannot drift from the config, and
# both matches carry an unproven link, so the only thing being compared is the
# declaration.
_ROUTE_LESS_BOOK = "mbet"      # config: supports_event_id false
_ROUTE_BEARING_BOOK = "mdshop"  # config: supports_event_id true


def _gate_status_for(bookmaker: str) -> str:
    """The gate's answer for one book's unproven link, as the callout describes it."""
    gate = CertaintyGate()
    pair = [_match(), _match(bookmaker=bookmaker, deep_link_verified=False)]
    gate.normalize(pair)
    return gate.evaluate_pair(*pair).status


def _link_policy_problems(text: str) -> list[str]:
    """Whether the callout states the link policy the gate actually implements.

    The claim is about the code, so it is settled by running the code: one book
    that declares a per-event route and one that declares it has none, both with
    an unproven link. Whichever way the gate answers, the callout has to say it —
    and the sentence that was true only while the gate ignored the declarations
    is rejected outright, because "a proven deep link on both sides" is the exact
    claim that was wrong.
    """
    callout = _callout(text)
    problems: list[str] = []
    route_less, route_bearing = _ROUTE_LESS_BOOK, _ROUTE_BEARING_BOOK
    less_status = _gate_status_for(route_less)
    bearing_status = _gate_status_for(route_bearing)
    if less_status != "verified":
        problems.append(
            f"{route_less} declares no per-event route and the gate answers "
            f"{less_status!r} for its unproven link, so the callout must not claim "
            "the gate refuses it"
        )
    if bearing_status == "verified":
        problems.append(
            f"{route_bearing} declares a per-event route and the gate answers "
            f"{bearing_status!r} for its unproven link, so the callout must not "
            "claim a declared route is optional"
        )
    if not re.search(r"no per-event (?:URL|url|route)", callout):
        problems.append("the callout never says what a book without a per-event route gets")
    if "verified on identity alone" not in callout:
        problems.append(
            "the callout never says a book that declares no per-event route is "
            "verified on identity alone"
        )
    if "fails safe" not in callout:
        problems.append(
            "the callout never says that a book with no declaration is not accepted, "
            "which is the fail-safe the gate implements"
        )
    if re.search(r"proven deep link", callout, re.IGNORECASE):
        problems.append(
            "the callout still demands a proven deep link, which the gate stopped "
            "requiring of a book that declares it has no per-event route"
        )
    return problems


def test_callout_states_the_link_policy_the_gate_implements():
    """The callout's link claim, checked by running the gate on both branches."""
    problems = _link_policy_problems(README)
    assert problems == [], "; ".join(problems)


def test_link_policy_fails_when_the_callout_demands_a_link_on_both_sides():
    """Proves the previous test can see the sentence that used to be there.

    The old callout said ``verified`` "requires a proven deep link on *both*
    sides" and attributed the whole outcome to the books' routing. That sentence
    was the defect described in prose: the gate never consulted the declaration,
    so a book that has none was refused for a link it never offered.
    """
    broken = README.replace(
        "and `verified` includes the link half of the claim",
        "and `verified` requires a proven deep link on *both* sides",
    )
    assert broken != README, "the mutation did not apply; the check is untested"
    assert "proven deep link on *both* sides" in broken, "the mutation left no copy"
    problems = _link_policy_problems(broken)
    assert problems, "a callout demanding a link on both sides passed the check"
    assert any("proven deep link" in problem for problem in problems)


def test_link_policy_fails_when_the_callout_drops_the_route_less_branch():
    """The accepted branch is the one the callout has to state, so removing it fails."""
    broken = re.sub(
        r"`no_event_link` evidence note and is verified on identity alone[^.]*\.",
        "the group is verified like any other.",
        README,
    )
    assert broken != README, "the mutation did not apply; the check is untested"
    assert "verified on identity alone" not in _callout(broken), (
        "the mutation left a copy in the callout; untested"
    )
    problems = _link_policy_problems(broken)
    assert problems, "a callout that dropped the route-less branch passed the check"
    assert any("identity alone" in problem for problem in problems)


# ===========================================================================
# 2. Environment variables: the README table against engine/ai.py
# ===========================================================================


def _code_env_default(name: str) -> str | None:
    """The default ``os.getenv`` gives ``name`` in ``engine/ai.py``, or None."""
    source = inspect.getsource(MatchAI.__init__)
    match = re.search(rf'os\.getenv\(\s*"{name}",\s*"([^"]*)"\s*\)', source)
    return match.group(1) if match else None


def _env_problems(text: str) -> list[str]:
    """Every ``AI_*`` default the README states that the code does not use."""
    problems: list[str] = []
    for name in ("AI_BASE_URL", "AI_MODEL"):
        code_default = _code_env_default(name)
        if code_default is None:
            problems.append(f"{name} has no os.getenv default in engine/ai.py")
            continue
        try:
            row = " | ".join(_row(text, f"`{name}`"))
        except AssertionError as exc:
            problems.append(str(exc))
            continue
        if code_default not in row:
            problems.append(
                f"the README's {name} row does not carry the code's default "
                f"{code_default!r}: {row!r}"
            )
    if "`AI_API_KEY`" not in text:
        problems.append("the README no longer documents AI_API_KEY")
    elif _code_env_default("AI_API_KEY") not in ("", None):
        problems.append("AI_API_KEY now has a code default; the README says it is empty")
    return problems


def test_env_var_defaults_in_the_readme_match_engine_ai():
    """The README's env table carries ``engine/ai.py``'s actual defaults.

    Both directions are read: a code change that moves a default fails here, and
    so does a README that documents a default the code does not use.
    """
    assert _code_env_default("AI_BASE_URL") == "https://api.openai.com/v1"
    assert _code_env_default("AI_MODEL") == "gpt-4o-mini"
    problems = _env_problems(README)
    assert problems == [], "; ".join(problems)


def test_env_check_fails_when_only_the_readme_changes():
    """Proves the previous test reads the README row, not just ``engine/ai.py``.

    The first draft of this check grepped the code alone, so rewriting the
    README's table left it green.
    """
    broken = README.replace("https://api.openai.com/v1", "https://api.example.test/v1")
    assert broken != README, "the mutation did not apply; the check is untested"
    problems = _env_problems(broken)
    assert problems, "a README documenting a base URL the code does not use passed"
    assert any("AI_BASE_URL" in problem for problem in problems)


# ===========================================================================
# 3. The status vocabulary, produced by RUNNING the gate
# ===========================================================================


def _match(**overrides: object) -> Match:
    """A proven match; ``overrides`` break exactly one part of the claim."""
    base: dict[str, object] = {
        "bookmaker": "mdshop",
        "home_team": "Sarajevo",
        "away_team": "Željezničar",
        "league": "BiH - Premier Liga",
        "kickoff": datetime(2026, 9, 25, 18, 0),
        "event_id": "e1",
        "url": "https://example.test/e1",
        "deep_link_verified": True,
        "markets": [Market(market_type=MarketType.MATCH_RESULT, odds=[
            OddsValue(label="1", value=2.0),
            OddsValue(label="X", value=3.0),
            OddsValue(label="2", value=3.0),
        ])],
    }
    base.update(overrides)
    return Match(**base)  # type: ignore[arg-type]


def _observed_reasons() -> tuple[set[str], set[str]]:
    """The reason vocabulary the gate can actually emit, by running it.

    Split into hard rejects and the rest, because the README's table makes exactly
    that distinction. Observed rather than grepped, so a reason the code stopped
    producing cannot linger in the documentation unnoticed.
    """
    gate = CertaintyGate()
    kickoff = datetime(2026, 9, 25, 18, 0)
    cases = [
        _match(bookmaker="mbet", event_id="e2", league="Primeira Liga"),
        _match(bookmaker="mbet", event_id="e2", kickoff=None),
        _match(bookmaker="mbet", event_id="e2", kickoff=kickoff + timedelta(minutes=30)),
        _match(bookmaker="mbet", event_id="e2", home_team="Gamma SC", away_team="Delta Club"),
        # `link_unverified` needs a book that DECLARES a per-event route: the six
        # books declaring `supports_event_id: false` are accepted with a
        # `no_event_link` evidence note instead, so mbet can no longer produce
        # this reason. The default bookmaker is mdshop, which declares a route.
        _match(deep_link_verified=False),
        # ...and `no_event_link` is now reachable only through a book that has
        # declared nothing at all, which is the fail-safe branch. It also needs
        # the link UNPROVEN as well as absent: _link_evidence returns
        # verified_link first, so a bare empty url/event_id never reaches it.
        _match(bookmaker="undeclared_book", url="", event_id="", deep_link_verified=False),
        _match(bookmaker="mbet", event_id="e3", category_tags=["women"]),
    ]
    observed: set[str] = set()
    for case in cases:
        pair = [_match(), case]
        gate.normalize(pair)
        observed.update(gate.evaluate_pair(*pair).reasons)
    return observed & set(HARD_REJECT_REASONS), observed - set(HARD_REJECT_REASONS)


def _vocabulary_problems(text: str) -> list[str]:
    """Every mismatch between the README's status table and the live gate.

    Only the reason cell is read (the third onwards): the first cell is the status
    name itself, and including it made the gate look as though it emitted
    "rejected" and "suggested".
    """
    problems: list[str] = []
    hard, soft = _observed_reasons()
    for status, expected in (("rejected", hard), ("suggested", soft)):
        try:
            cells = _row(text, f"`{status}`")
        except AssertionError as exc:
            problems.append(str(exc))
            continue
        documented = set(_TOKEN.findall(" | ".join(cells[2:])))
        missing, invented = expected - documented, documented - expected
        if missing:
            problems.append(f"the README's {status} row omits {sorted(missing)}")
        if invented:
            problems.append(
                f"the README's {status} row claims {sorted(invented)}, which the gate "
                "cannot produce"
            )
    return problems


def test_status_reason_vocabulary_matches_what_the_gate_emits():
    """The README's three-status table is the gate's real reason vocabulary.

    The gate is *run* to collect its reasons rather than grepped, so a reason it
    stopped emitting is caught and a reason it gained is caught too. The
    direction that matters most is the second: the first draft of this check only
    asked whether each documented string appeared somewhere in
    ``certainty.py``, so a README could invent a reason and pass.
    """
    hard, soft = _observed_reasons()
    assert hard <= set(HARD_REJECT_REASONS), (
        f"{sorted(hard - set(HARD_REJECT_REASONS))} produced a hard reject without being "
        "in HARD_REJECT_REASONS, so calling it hard here is wrong"
    )
    assert hard, "the probe produced no hard reasons, so this test would be vacuous"
    assert soft, "the probe produced no soft reasons, so this test would be vacuous"
    problems = _vocabulary_problems(README)
    assert problems == [], "; ".join(problems)


def test_dead_hard_reject_vocabulary_is_documented_as_dead():
    """``HARD_REJECT_REASONS`` names one reason the gate never emits; say so.

    The assignment in `engine/certainty.py` lists `orientation_unresolved`, but
    nothing in the module ever appends it — the unresolvable-orientation case is
    reported as `team_unresolved`. Left undocumented, a reader comparing the table
    with that set would conclude the gate rejects something it does not. The
    README says so, and this pins both sides: implement the reason or delete the
    entry, and this fails until the README's wrinkle sentence is updated to match.
    """
    hard, _ = _observed_reasons()
    dead = set(HARD_REJECT_REASONS) - hard
    assert dead == {"orientation_unresolved"}, (
        f"the hard-reject vocabulary the gate never emits is {sorted(dead)}, not just "
        "orientation_unresolved; the README's note about it is stale"
    )
    section = _section(README, "## Match & mapping certainty")
    assert "HARD_REJECT_REASONS" in section
    for reason in dead:
        assert reason in section, (
            f"{reason!r} is declared hard-reject but never emitted, and the README no "
            "longer says so"
        )
    assert "never emits" in section


def test_readme_cites_hard_reject_reasons_by_symbol_and_not_by_line():
    """The README must not pin `HARD_REJECT_REASONS` to a line number.

    This is the same defect class the whole link-declaration change was fixing: a
    document asserting a precise fact about the code that nothing re-checks. It
    went stale the moment the commit added an import above the assignment — the
    README and this file's own docstring both still cited
    `engine/certainty.py:20` while the assignment sat on line 27.

    So the check is on the *shape* of the citation, and it resolves the symbol the
    README names. If someone reintroduces a line-number citation anywhere in the
    file, this fails; there is no line number here that a future edit cannot
    falsify.
    """
    cited = re.findall(r"`engine/certainty\.py:(\d+)`", README)
    assert cited == [], (
        f"README.md pins engine/certainty.py to lines {cited}; a line number goes stale "
        "on the next import. Cite the symbol `HARD_REJECT_REASONS` instead"
    )
    # The assignment the README points at must still exist, found by symbol.
    source = (REPO_ROOT / "engine" / "certainty.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assigned = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "HARD_REJECT_REASONS" for t in node.targets
        )
    ]
    assert len(assigned) == 1, (
        f"expected exactly one module-level HARD_REJECT_REASONS assignment, found "
        f"{len(assigned)}; the README's pointer to it is meaningless"
    )
    assert "HARD_REJECT_REASONS" in _section(README, "## Match & mapping certainty")


def test_vocabulary_check_fails_on_an_invented_and_on_a_dropped_reason():
    """Proves the vocabulary test reads the README's table cells, not just the code."""
    invented = README.replace("`category_mismatch`", "`orientation_unresolved`", 1)
    assert invented != README, "the first mutation did not apply; untested"
    problems = _vocabulary_problems(invented)
    assert problems, "a README inventing a rejected reason passed the check"
    assert any("cannot produce" in problem for problem in problems)

    dropped = re.sub(r"`kickoff_delta`,\s*", "", README)
    assert dropped != README, "the second mutation did not apply; untested"
    problems = _vocabulary_problems(dropped)
    assert problems, "a README dropping a reason the gate emits passed the check"
    assert any("kickoff_delta" in problem for problem in problems)


# ===========================================================================
# 4. The approval boundary
# ===========================================================================

_BOUNDARY_FRAGMENTS = ("deep_link_verified", "human approval", "never")


def _approval_problems(text: str) -> list[str]:
    """Whether the approval boundary is stated, and stated in one place.

    Scoped to a single *claim* inside the certainty section, so neither the word
    "never" elsewhere in a 200-line file nor a neighbouring bullet's "never" can
    stand in for the prohibition. The first version of this check required only
    that "never" and "deep_link_verified" both occur somewhere in the README;
    deleting "never by a human approval" left it green.
    """
    problems: list[str] = []
    section = _section(text, "## Match & mapping certainty")
    carriers = [
        claim
        for claim in _claims(section)
        if all(fragment in claim.lower() for fragment in _BOUNDARY_FRAGMENTS)
    ]
    if not carriers:
        problems.append(
            "no claim in the certainty section states that `deep_link_verified` is "
            "never set by a human approval"
        )
    if "team alias" not in section:
        problems.append("the section never says an approval grants a team alias")
    if "team_alias_allowlist.json" not in section:
        problems.append("the section never names config/team_alias_allowlist.json")
    return problems


def test_approval_boundary_is_stated_in_one_place():
    """Approval grants team identity; it never grants a link.

    The claim the brief singled out, so it is the one that had to be impossible
    to weaken silently. ``never`` occurs six times in this README and is tied to
    ``deep_link_verified`` in exactly one of them.
    """
    problems = _approval_problems(README)
    assert problems == [], "; ".join(problems)


def test_approval_check_fails_when_the_prohibition_is_removed():
    """Proves the previous test reads the sentence, not the word "never"."""
    broken = re.sub(r"never by a\s+human approval", "on occasion by a human approval", README)
    assert broken != README, "the mutation did not apply; the check is untested"
    problems = _approval_problems(broken)
    assert problems, "removing the prohibition from the approval sentence left it green"


# ===========================================================================
# 5. The Review tab has no URL path -- against the router and the frontend
# ===========================================================================


def _review_tab_problems(text: str) -> list[str]:
    """Whether the README's "no dedicated URL" claim matches the app and the JS."""
    problems: list[str] = []
    section = _section(text, "## Match & mapping certainty")
    if "no dedicated URL" not in section:
        problems.append("the README no longer says the Review tab has no dedicated URL")

    paths = {getattr(route, "path", "") for route in app.app.routes}
    if "/" not in paths:
        problems.append("the app no longer serves the dashboard at /")
    for path in sorted(p for p in paths if "review" in p.lower()):
        problems.append(f"the app serves a review path ({path}); the README is stale")

    frontend = (REPO_ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    for pattern in ("location.hash", "URLSearchParams", "pushState", "replaceState"):
        if pattern in frontend:
            problems.append(
                f"frontend/js/app.js now uses {pattern}, so the tab may have a URL"
            )

    index = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    tabs = re.findall(r'data-tab="([a-z]+)"', index)
    if tabs[:2] != ["surebets", "review"]:
        problems.append(f"the dashboard tabs are {tabs}, not surebets then review")
    return problems


def test_review_tab_really_has_no_url_path():
    """The README's "no dedicated URL" is checked against the app, not asserted."""
    problems = _review_tab_problems(README)
    assert problems == [], "; ".join(problems)


def test_review_tab_check_fails_when_the_readme_claim_is_dropped():
    """Proves the previous test reads the sentence out of the document."""
    broken = README.replace("There is no dedicated URL", "There is a dedicated URL")
    assert broken != README, "the mutation did not apply; the check is untested"
    assert _review_tab_problems(broken), "a README claiming a URL passed the check"


# ===========================================================================
# 6. Endpoints the README names
# ===========================================================================

_CANDIDATE_ENDPOINTS = (
    ("GET", "/candidates"),
    ("POST", "/candidates/{candidate_id}/approve"),
    ("POST", "/candidates/{candidate_id}/reject"),
    ("POST", "/verify-links"),
)


def _routed_endpoints() -> set[tuple[str, str]]:
    """``(method, path)`` for every route on the API router."""
    from fastapi.routing import APIRoute

    return {
        (method, route.path)
        for route in api.router.routes
        if isinstance(route, APIRoute)
        for method in (route.methods or set())
    }


def _endpoint_problems(text: str) -> list[str]:
    """Every endpoint the README names, checked against the live router."""
    problems: list[str] = []
    routed = _routed_endpoints()
    for method, path in _CANDIDATE_ENDPOINTS:
        if (method, path) not in routed:
            problems.append(f"the README documents {method} {path}, which no longer exists")
        if path not in text:
            problems.append(f"the README no longer names {method} {path}")
    return problems


def test_documented_endpoints_exist_in_the_router():
    """Each endpoint the README tells a reader to call is really routed."""
    problems = _endpoint_problems(README)
    assert problems == [], "; ".join(problems)


def test_endpoint_check_fails_when_the_readme_names_a_route_that_does_not_exist():
    """Proves the previous test reads the endpoint strings out of the document."""
    broken = README.replace(
        "/api/candidates/{candidate_id}/approve", "/api/candidates/{id}/ok"
    )
    assert broken != README, "the mutation did not apply; the check is untested"
    problems = _endpoint_problems(broken)
    assert problems, "a README naming a non-existent route passed"
    assert any("approve" in problem for problem in problems)


# ===========================================================================
# 7. The two documented scripts, against their own argparse declarations
# ===========================================================================

_SCRIPTS = ("verify_deeplinks.py", "generate_market_mapping_doc.py")


def _declared_flags(script: Path) -> set[str]:
    """Every flag string ``script`` passes to ``add_argument``, from its AST."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            flags.add(first.value)
    return flags


def _tool_problems(text: str) -> list[str]:
    """Every flag the README tells a reader to pass that the script lacks."""
    problems: list[str] = []
    for name in _SCRIPTS:
        if name not in text:
            problems.append(f"the README no longer documents scripts/{name}")
        flags = _declared_flags(REPO_ROOT / "scripts" / name)
        for line in text.splitlines():
            if name not in line or not line.strip().startswith("python"):
                continue
            for token in line.split()[2:]:
                if token.startswith("-") and token.split("=")[0] not in flags:
                    problems.append(
                        f"the README documents `{token}` but scripts/{name} declares "
                        f"none of {sorted(flags)}"
                    )
    return problems


def test_documented_script_flags_exist_in_those_scripts():
    """The invocations in the README parse against the scripts' real flags."""
    problems = _tool_problems(README)
    assert problems == [], "; ".join(problems)


def test_tool_check_fails_when_the_readme_documents_an_invented_flag():
    """Proves the previous test reads the invocations out of the document."""
    broken = README.replace(
        "python scripts/verify_deeplinks.py mozzartbet --limit 3",
        "python scripts/verify_deeplinks.py mozzartbet --sweep-all",
    )
    assert broken != README, "the mutation did not apply; the check is untested"
    problems = _tool_problems(broken)
    assert problems, "a README documenting a flag the script lacks passed"
    assert any("--sweep-all" in problem for problem in problems)


# ===========================================================================
# 8. How a link sweep advances, tied to the function that makes it advance
# ===========================================================================


def _convergence_problems(text: str, source: str | None = None) -> list[str]:
    """The README's account of sweep convergence, against ``build_targets`` itself.

    Both directions, because a stale caveat and an invented capability are the
    same defect: the README said "cannot converge" while the function had no
    cursor, and the day the function grew one the sentence became false. So the
    warning is required exactly while the cursor is absent, and the description
    of the cursor is required exactly while it is present.

    Scoped to the claims that name ``build_targets``, not the whole section. The
    certainty section runs ~130 lines, and a check that only asks whether
    ``offset`` occurs *somewhere* in it is the weak shape this file exists to
    avoid: a neighbouring paragraph's mention would stand in for the explanation.
    ``source`` is a parameter so a companion can prove the code-side branch fails.
    """
    problems: list[str] = []
    section = _section(text, "## Match & mapping certainty")
    carriers = [claim for claim in _claims(section) if "build_targets" in claim]
    if source is None:
        source = (REPO_ROOT / "scripts" / "verify_deeplinks.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.FunctionDef) and node.name == "build_targets"):
            continue
        params = {arg.arg for arg in node.args.args}
        names = {target.id for target in ast.walk(node) if isinstance(target, ast.Name)}
        has_cursor = {"offset", "settled"} <= params
        if has_cursor:
            if "cannot converge" in section:
                problems.append(
                    "build_targets takes offset and settled, so the README's claim that a "
                    "per-book sweep cannot converge is stale"
                )
            # One claim must name the function AND explain both halves of the cursor.
            explained = [
                claim for claim in carriers
                if "`settled`" in claim and "`offset`" in claim and "skip" in claim.lower()
            ]
            if not explained:
                problems.append(
                    "no claim naming build_targets explains that `settled` ids are skipped "
                    "before the window is cut and what `offset` resumes at"
                )
        elif "cannot converge" not in section:
            problems.append(
                f"build_targets takes {sorted(params)}; the README no longer warns that a "
                "sweep cannot converge"
            )
        if "seen" not in names:
            problems.append("build_targets no longer dedupes event ids; re-read the claim")
        break
    else:
        problems.append("build_targets is gone; the README's claim has no referent")
    return problems


def test_convergence_caveat_matches_build_targets():
    """The README's account of a sweep is tied to the function that makes it."""
    problems = _convergence_problems(README)
    assert problems == [], "; ".join(problems)


def test_convergence_check_fails_when_the_readme_drops_the_warning():
    """Proves the previous test reads the warning out of the document."""
    broken = README.replace("advances", "cannot converge today")
    assert broken != README, "the mutation did not apply; the check is untested"
    assert _convergence_problems(broken), "a README dropping the cursor passed"


def test_convergence_check_fails_when_only_one_half_of_the_cursor_is_explained():
    """`settled` and `offset` are different mechanisms; explaining one is not
    explaining the other, so a claim that drops `offset` alone must fail."""
    broken = README.replace("`offset` (a positional\nresume, for a caller with no store of its own — which is the CLI), and the",
                            "and the")
    assert broken != README, "the mutation did not apply; the check is untested"
    assert _convergence_problems(broken), "a README describing only `settled` passed"


def test_convergence_check_fails_when_the_code_loses_the_cursor():
    """The other direction: a README that promises a cursor `build_targets` does
    not have is the same defect, and only reading the code catches it."""
    source = (REPO_ROOT / "scripts" / "verify_deeplinks.py").read_text(encoding="utf-8")
    stripped = source.replace("    offset: int = 0,\n", "").replace(
        "    settled: Collection[str] = (),\n", ""
    )
    assert stripped != source, "the mutation did not apply; the check is untested"
    problems = _convergence_problems(README, source=stripped)
    assert any("cannot converge" in problem for problem in problems), problems


def test_convergence_check_fails_when_build_targets_is_gone():
    problems = _convergence_problems(README, source="def other():\n    pass\n")
    assert any("gone" in problem for problem in problems), problems


# ===========================================================================
# 9. The two known defects, and the tripwires that guard them
# ===========================================================================

_DEFECT_TOKENS = ("premier", "XPASS", "dateFrom=now")
# What the README says, and the code comment that measured it. The README phrases
# it in prose and the comment in a URL, so each side has its own literal.
_README_FIGURES = ("35 live football events", "12 hours")
_CODE_FIGURES = ("35 live football events", "now-12h")


def _defect_problems(text: str) -> list[str]:
    """The known-defects section, against the tripwires recorded in-repo."""
    problems: list[str] = []
    section = _section(text, "## Match & mapping certainty")
    for token in _DEFECT_TOKENS:
        if token not in section:
            problems.append(f"the known-defects section no longer mentions {token!r}")

    fixtures = (REPO_ROOT / "tests" / "test_market_fixtures.py").read_text(encoding="utf-8")
    if "@pytest.mark.xfail" not in fixtures or "strict=True" not in fixtures:
        problems.append(
            "test_market_fixtures.py no longer holds a strict xfail, so the XPASS "
            "tripwire the README describes does not exist"
        )
    if "LIVE - OBA TIMA DAJU GOL" not in fixtures:
        problems.append("the premier live BTTS block name is no longer in the test file")

    mdshop = (REPO_ROOT / "scrapers" / "mdshop.py").read_text(encoding="utf-8")
    if "KNOWN DEFECT" not in mdshop:
        problems.append("scrapers/mdshop.py no longer records the live-window KNOWN DEFECT")
    for figure in _CODE_FIGURES:
        if figure not in mdshop:
            problems.append(f"scrapers/mdshop.py no longer carries the figure {figure!r}")
    for figure in _README_FIGURES:
        if figure not in text:
            problems.append(f"the README no longer quotes the measurement {figure!r}")
    return problems


def test_defect_pointer_matches_the_tripwires_in_repo():
    """The two known defects the README lists are the two recorded in-repo.

    ``premier_kladionica`` live BTTS is guarded by a strict xfail, so the README
    must name both the defect and the tripwire; the NSoft live window is guarded
    by a ``KNOWN DEFECT`` comment that carries the measurement the README quotes,
    so the quoted figures must still be there.
    """
    problems = _defect_problems(README)
    assert problems == [], "; ".join(problems)


def test_defect_check_fails_when_the_readme_drops_a_tripwire():
    """Proves the previous test reads the tripwires out of the document."""
    broken = README.replace("XPASS", "a pass")
    assert broken != README, "the mutation did not apply; the check is untested"
    assert "strict=True" in (REPO_ROOT / "tests" / "test_market_fixtures.py").read_text(
        encoding="utf-8"
    ), "the code side must still say it, or this proves nothing"
    problems = _defect_problems(broken)
    assert problems, "a README dropping the tripwire passed"
    assert any("XPASS" in problem for problem in problems)


# ===========================================================================
# 10. PLAN.md, and the pointer that makes the headline reproducible
# ===========================================================================

_PHASE_HEADING = "### Phase 4 — Mapping certainty (Done)"

# The phrases the 2026-09-25 status header asserted and 2026-09-26 retired. Kept
# verbatim, because the point is to catch the *old sentence* coming back, not to
# catch a paraphrase of it. Each is present-tense prose about what `verified`
# requires, and each became false when the gate was taught to read
# `config/bookmaker_deeplinks.json` on 2026-09-26.
_RETIRED_HEADER_CLAIMS = (
    "needs a proven deep link",
    "on purpose",
)


def _plan_header_defects(plan: str) -> list[str]:
    """Defects in PLAN.md's block-quoted status callout — the first line a reader sees.

    Named ``_defects`` and not ``_problems`` on purpose: the module-wide guard
    ``test_every_doc_predicate_is_proven_capable_of_failing`` calls every
    ``*_problems`` predicate with ``README``, and this one reads PLAN.md, so
    folding it into that set would fail the guard for the wrong reason.

    Three things are checked, and the first is the one that regressed:

    1. No retired present-tense claim. The header read "The scanner now produces
       zero surebets on purpose: `verified` needs a proven deep link", which was
       true on 2026-09-25 and stopped being true when the gate began consulting
       the per-book declaration — a declared-false book is verified on identity
       alone, and the declaration *is* the proof. §3 was corrected to past tense
       with a dated correction paragraph; the header was not, and no test covered
       it, so the two halves of the same claim could drift apart silently.
    2. The header states the counts, and the counts are read out of
       ``config/bookmaker_deeplinks.json`` rather than typed in, so flipping a
       declaration cannot leave a stale "6 of the 9" in the first line.
    3. The header still carries the two things that did *not* change: MDShop's
       and Admiralbet's routes are inert, and the zero-surebet figure is a
       measurement with conditions rather than a slogan. A header that dropped
       either would be over-correcting the defect it was fixed for.
    """
    header = _callout(plan)
    problems = [
        f"the status header still asserts the retired claim {claim!r}"
        for claim in _RETIRED_HEADER_CLAIMS
        if claim in header.lower()
    ]

    declarations = json.loads(
        (REPO_ROOT / "config" / "bookmaker_deeplinks.json").read_text(encoding="utf-8")
    )
    no_route = [book for book, spec in declarations.items() if spec.get("supports_event_id") is False]
    with_route = [book for book, spec in declarations.items() if spec.get("supports_event_id") is True]
    counts = f"{len(no_route)} of the {len(declarations)} books"
    if counts not in header:
        problems.append(
            f"the status header does not state {counts!r}; the counts must come from "
            "config/bookmaker_deeplinks.json, and a flipped declaration has to show up here"
        )
    for token in ("config/bookmaker_deeplinks.json", "supports_event_id: false"):
        if token not in header:
            problems.append(
                f"the status header never mentions {token!r}, so it cannot explain why "
                "the retired claim stopped being true"
            )
    lowered = header.lower()
    for book in with_route:
        if book not in lowered:
            problems.append(
                f"the status header drops {book!r}, one of the "
                f"{len(with_route)} books that must still have its route proven"
            )
    for token in ("inert", "zero surebets", "§3"):
        if token.lower() not in header.lower():
            problems.append(
                f"the status header drops {token!r}: the inertness is a bookmaker-side "
                "fact that did not change, and the figure has to point at its conditions"
            )
    return problems


def test_plan_declares_phase_four_done_with_the_headline():
    """PLAN.md carries the phase section and repeats the headline result.

    The header and §3 are checked by the *same* test on purpose. They make one
    claim in two places — that zero surebets is today's correct output — and
    checking only §3 is what let the header keep asserting the superseded
    present-tense version. One test, one document, one claim.
    """
    problems: list[str] = []
    if _PHASE_HEADING not in PLAN:
        problems.append(f"PLAN.md has no {_PHASE_HEADING!r} section")
    else:
        phase = _section(PLAN, _PHASE_HEADING)
        for token in ("inert", "zero surebets", "Mozzartbet", "verified"):
            if token.lower() not in phase.lower():
                problems.append(f"the Phase 4 section never mentions {token!r}")
    problems.extend(_plan_header_defects(PLAN))
    assert problems == [], "; ".join(problems)


def test_plan_header_check_fails_when_the_header_regresses_to_the_old_claim():
    """Proves the header half of the previous test reads the header.

    Restores the exact 2026-09-25 status line — present tense, "needs a proven
    deep link", "on purpose", and no declaration counts — and asserts the check
    notices all three ways it can fail. The second mutation is the drift this
    item was raised for: §3 correct, header not.
    """
    retired = (
        "> **Status (2026-09-25):** Phase 4 (mapping certainty) shipped — 13 tasks, "
        "503 tests green. **The scanner now produces zero surebets on purpose:** "
        "`verified` needs a proven deep link, and MDShop's and Admiralbet's "
        "`?event=<id>` routes are inert. See §3 *Phase 4*."
    )
    current = [
        line
        for line in PLAN.splitlines()
        if line.startswith("> **Status (2026-09-26):**")
    ]
    assert len(current) == 1, f"expected one 2026-09-26 status line, found {len(current)}"

    regressed = PLAN.replace(current[0], retired, 1)
    assert regressed != PLAN, "the first mutation did not apply; untested"
    problems = _plan_header_defects(regressed)
    assert problems, "the retired 2026-09-25 header passed the check"
    assert any("needs a proven deep link" in problem for problem in problems)
    assert any("on purpose" in problem for problem in problems)
    assert any("6 of the 9 books" in problem for problem in problems)
    assert any("bookmaker_deeplinks.json" in problem for problem in problems)

    # The drift this item was raised for, isolated: §3 untouched, header stale.
    section_intact = _section(regressed, _PHASE_HEADING)
    assert "Correction (2026-09-26)" in section_intact, "the mutation touched §3; untested"
    assert _plan_header_defects(regressed), "a correct §3 excused a stale header"


# The pointers the headline claim must carry, and why each one matters.
_POINTERS = (
    ("config/bookmaker_deeplinks.json", "the reproducible half: which books declare a route"),
    ("tests/test_readme_claims.py", "these claims are themselves checked"),
    ("verify_deeplinks.py", "the script that can re-measure the inertness"),
    ("2026-09-25", "the date the measurement was taken"),
    ("task-12-report", "where the finding is recorded"),
)


def _pointer_problems(text: str) -> list[str]:
    """The headline is a dated measurement, so it must say how to re-check it.

    Two halves: the part the repo CAN reproduce (which books declare an event
    route) must be pointed at in-repo, and the inertness itself must be attributed
    to the script and the dated report rather than presented as a repo fact.
    """
    callout = _callout(text)
    return [
        f"the callout does not point at {token!r} ({why})"
        for token, why in _POINTERS
        if token not in callout
    ]


def test_readme_points_at_how_to_recheck_the_headline():
    """Every pointer the headline needs, checked against the callout itself."""
    problems = _pointer_problems(README)
    assert problems == [], "; ".join(problems)


def test_pointer_check_fails_when_the_callout_loses_a_pointer():
    """Proves the previous test reads the pointers out of the callout."""
    broken = README.replace("task-12-report", "an old thread")
    assert broken != README, "the mutation did not apply; the check is untested"
    assert "task-12-report" not in broken, "the mutation left a copy behind; untested"
    problems = _pointer_problems(broken)
    assert problems, "a callout losing its source passed"
    assert any("task-12-report" in problem for problem in problems)


# ===========================================================================
# 11. The guard on the guard
# ===========================================================================


def _predicates() -> dict[str, object]:
    """Every ``*_problems`` predicate defined in this module, by name."""
    return {
        name: value
        for name, value in globals().items()
        if name.endswith("_problems") and inspect.isfunction(value)
    }


def _companions() -> set[str]:
    """Every ``test_*_fails_*`` defined in this module, by name."""
    return {name for name in globals() if name.startswith("test_") and "_fails_" in name}


def test_every_doc_predicate_is_proven_capable_of_failing():
    """No predicate in this file may be a no-op, and none may be unaccompanied.

    Two failure modes, both real in this file's own first draft:

    * a predicate that does not open the document (there were three), and
    * a predicate so weak that nothing proves it can fail (the approval boundary,
      which passed with its sentence deleted).

    So: every ``*_problems`` predicate must pass on the real README, and each must
    have a ``test_*_fails_*`` companion naming it. A new predicate added without a
    companion is how the second failure mode returns.
    """
    predicates, companions = _predicates(), _companions()
    assert predicates, "no predicates found; the introspection itself is broken"
    problems: list[str] = []
    for name, predicate in sorted(predicates.items()):
        assert callable(predicate)
        failures = predicate(README)  # type: ignore[operator]
        if failures:
            problems.append(f"{name} reports on the real README: {'; '.join(failures)}")
        if not any(name.removesuffix("_problems") in companion for companion in companions):
            problems.append(
                f"{name} has no test_*_fails_* companion, so nothing proves it can fail"
            )
    assert not problems, "\n".join(problems)


def test_the_predicate_guard_would_notice_an_empty_predicate_set():
    """The guard above must fail, not pass, if its introspection finds nothing.

    Without this, replacing every predicate with ``None`` would make the guard's
    own ``assert predicates`` the only thing standing between a rename and a
    silently empty suite. This drives that path directly.
    """
    saved = _predicates()
    try:
        for name in saved:
            globals()[name] = None
        with pytest.raises(AssertionError, match="no predicates found"):
            test_every_doc_predicate_is_proven_capable_of_failing()
    finally:
        for name, value in saved.items():
            globals()[name] = value
    assert set(_predicates()) == set(saved), "the module was not restored"
