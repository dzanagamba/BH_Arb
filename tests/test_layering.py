"""Package layering: importing a package must not import all of its modules.

``engine/__init__.py`` used to pull in the matcher, every scraper and Playwright,
and ``scrapers/__init__.py`` pulled in all eight books. Both are lazy now (PEP
562), so the subprocess probes below check the real import graph rather than the
test process, which already imported scrapers while collecting.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(code: str) -> object:
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_importing_engine_loads_neither_scrapers_nor_playwright():
    loaded = _run(
        "import json, sys, engine\n"
        "print(json.dumps({\n"
        "    'scrapers': any(m == 'scrapers' or m.startswith('scrapers.') for m in sys.modules),\n"
        "    'playwright': any(m == 'playwright' or m.startswith('playwright.') for m in sys.modules),\n"
        "}))\n"
    )
    assert loaded == {"scrapers": False, "playwright": False}


def test_engine_still_exports_its_public_classes_lazily():
    names = _run(
        "import json\n"
        "from engine import ArbitrageEngine, MatchMatcher, TeamNormalizer\n"
        "print(json.dumps([\n"
        "    ArbitrageEngine.__name__, MatchMatcher.__name__, TeamNormalizer.__name__\n"
        "]))\n"
    )
    assert names == ["ArbitrageEngine", "MatchMatcher", "TeamNormalizer"]


def test_importing_the_scraper_package_loads_no_book_and_no_playwright():
    loaded = _run(
        "import json, sys, scrapers\n"
        "print(json.dumps({\n"
        "    'books': sorted(\n"
        "        m for m in sys.modules\n"
        "        if m.startswith('scrapers.') and m != 'scrapers.common'\n"
        "    ),\n"
        "    'playwright': any(m == 'playwright' or m.startswith('playwright.') for m in sys.modules),\n"
        "}))\n"
    )
    assert loaded == {"books": [], "playwright": False}


def test_importing_scrapers_common_loads_no_book_and_no_playwright():
    loaded = _run(
        "import json, sys\n"
        "import scrapers.common\n"
        "print(json.dumps({\n"
        "    'books': sorted(m for m in sys.modules if m.startswith('scrapers.') and m != 'scrapers.common'),\n"
        "    'playwright': any(m == 'playwright' or m.startswith('playwright.') for m in sys.modules),\n"
        "}))\n"
    )
    assert loaded == {"books": [], "playwright": False}


def test_engine_does_not_import_the_scrapers_package():
    """M3-2: the dependency runs one way, scrapers -> engine.

    The deep-link declaration store and the AH label helpers used to make the
    engine import ``scrapers.common``, while the scrapers import the market
    registry and sports helpers: a package cycle. The store now lives in
    ``engine.deeplinks`` and the labels in ``engine.ah_labels``.
    """
    loaded = _run(
        "import json, sys\n"
        "import engine.certainty, engine.matcher, engine.arbitrage\n"
        "print(json.dumps(sorted(\n"
        "    m for m in sys.modules if m == 'scrapers' or m.startswith('scrapers.')\n"
        ")))\n"
    )
    assert loaded == []


def test_no_engine_source_imports_scrapers_even_inside_a_function():
    """A local import would reintroduce the cycle without loading it at import."""
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "engine").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "scrapers" or name.startswith("scrapers.") for name in names):
                offenders.append(path.name)
                break
    assert offenders == []


def test_the_declaration_store_left_scrapers_common():
    from scrapers import common

    for moved in ("build_event_url", "declares_no_event_id", "effective_deeplink_declarations"):
        assert not hasattr(common, moved), moved


def test_scraper_package_still_exports_its_public_classes_lazily():
    names = _run(
        "import json\n"
        "from scrapers import (\n"
        "    AdmiralbetScraper, BetoleScraper, EvlbetScraper, MaxBetScraper,\n"
        "    MBetScraper, MDShopScraper, MozzartbetScraper, SportPlusScraper,\n"
        ")\n"
        "print(json.dumps([\n"
        "    AdmiralbetScraper.__name__, BetoleScraper.__name__, EvlbetScraper.__name__,\n"
        "    MaxBetScraper.__name__, MBetScraper.__name__, MDShopScraper.__name__,\n"
        "    MozzartbetScraper.__name__, SportPlusScraper.__name__,\n"
        "]))\n"
    )
    assert names == [
        "AdmiralbetScraper",
        "BetoleScraper",
        "EvlbetScraper",
        "MaxBetScraper",
        "MBetScraper",
        "MDShopScraper",
        "MozzartbetScraper",
        "SportPlusScraper",
    ]


def test_server_does_not_import_from_scripts():
    """M3-6: the app owns the reusable logic; scripts are CLI wrappers.

    `/api/verify-links` used to import the verifier from `scripts` and the
    health/audit path imported `scripts.pairing_audit.audit`. That made the
    running application depend on a directory coverage does not measure. Both
    implementations now live in `server/`, and a script may import `server`,
    never the other way.
    """
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "server").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "scripts" or name.startswith("scripts.") for name in names):
                offenders.append(path.name)
                break
    assert offenders == []


def test_the_measurement_and_verifier_live_under_server():
    """Coverage's `source` is the app packages, so the reusable code must be one."""
    from server import deeplink_verifier, pairing_audit

    assert callable(pairing_audit.audit)
    assert callable(deeplink_verifier.verify_bookmaker)
    assert callable(deeplink_verifier.build_targets)


def test_the_scripts_keep_their_public_names():
    """The CLI wrappers re-export what their importers already used."""
    from scripts import pairing_audit, verify_deeplinks

    assert callable(pairing_audit.main)
    assert pairing_audit.audit is not None
    assert verify_deeplinks.verify_bookmaker is not None
    assert verify_deeplinks.CRITERION
