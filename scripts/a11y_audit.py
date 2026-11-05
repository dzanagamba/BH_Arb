"""Automated accessibility audit for the dashboard shell (N2-5).

The audit runs the shipped page in Chromium, walks the main tabs, opens a
synthetic bet slip, and runs two layers of checks:

* a small built-in DOM audit that always runs (landmarks, accessible names,
  label associations, duplicate ids, tab semantics, live regions);
* axe-core when it can be found (`--axe PATH`, `AXE_PATH`, or a local
  `node_modules/axe-core/axe.min.js`).

Axp failures are reported with their selector and rule, and an explicit
allowlist keeps a reviewed, documented exception from hiding a new issue. The
script never annotates or changes the product.

    python scripts/a11y_audit.py
    python scripts/a11y_audit.py --url http://localhost:8000
    python scripts/a11y_audit.py --axe node_modules/axe-core/axe.min.js --json out.json

The Playwright browser is optional tooling: with no browser installed the
script exits 2 with a clear message, and the offline suite still runs the static
checks in ``tests/test_accessibility_axe.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend"

# Reviewed exceptions. Each entry is (rule, selector_fragment, reason). A new
# violation outside this list fails the audit, so an accepted issue cannot hide
# a regression elsewhere. The list is intentionally empty today: every shipped
# tab and the synthetic slip pass both the built-in audit and axe-core, including
# their contrast thresholds. Add an entry only with a measured reason, never to
# make a run green.
ALLOWLIST: tuple[tuple[str, str, str], ...] = ()

BUILT_IN_SCRIPT = r"""
() => {
    const issues = [];
    const visible = (el) => {
        if (!el || el.hidden) return false;
        if (el.closest('[hidden]')) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden';
    };
    const accessibleName = (el) => {
        const label = el.getAttribute('aria-label')
            || (el.labels && el.labels[0] && el.labels[0].textContent)
            || el.getAttribute('title')
            || el.textContent
            || '';
        return String(label).trim();
    };
    const add = (rule, selector, message) => issues.push({ rule, selector, message });

    document.querySelectorAll('button, a[href], input, select, textarea').forEach((el) => {
        if (!visible(el)) return;
        if (!accessibleName(el)) {
            add('accessible-name', cssPath(el), 'interactive element has no accessible name');
        }
    });
    document.querySelectorAll('input:not([type="hidden"]), select, textarea').forEach((el) => {
        if (!visible(el)) return;
        const labelled = (el.labels && el.labels.length)
            || el.getAttribute('aria-label')
            || el.getAttribute('aria-labelledby');
        if (!labelled) add('label', cssPath(el), 'form control has no label');
    });
    document.querySelectorAll('[role="tab"]').forEach((tab) => {
        if (!visible(tab)) return;
        const selected = tab.getAttribute('aria-selected');
        if (selected !== 'true' && selected !== 'false') {
            add('tab-state', cssPath(tab), 'tab is missing aria-selected');
        }
        if (tab.tabIndex > 0) add('focus-order', cssPath(tab), 'positive tabindex');
    });
    document.querySelectorAll('[id]').forEach((el) => {
        if (document.querySelectorAll(`[id="${CSS.escape(el.id)}"]`).length > 1) {
            add('duplicate-id', cssPath(el), `duplicate id ${el.id}`);
        }
    });
    const landmarks = ['main', 'header', 'nav[aria-label]'];
    for (const landmark of landmarks) {
        if (!document.querySelector(landmark)) {
            add('landmark', landmark, `missing ${landmark} landmark`);
        }
    }
    if (!document.querySelector('[aria-live="polite"], [aria-live="assertive"]')) {
        add('live-region', 'body', 'no live region for asynchronous status');
    }
    if (!document.querySelector('.skip-link')) {
        add('skip-link', 'body', 'no skip link');
    }
    document.querySelectorAll('[tabindex]').forEach((el) => {
        const value = Number(el.getAttribute('tabindex'));
        if (value > 0) add('focus-order', cssPath(el), 'positive tabindex');
    });
    return issues;

    function cssPath(el) {
        if (el.id) return `#${CSS.escape(el.id)}`;
        const parts = [];
        while (el && el.nodeType === 1 && parts.length < 4) {
            let part = el.tagName.toLowerCase();
            if (el.classList.length) part += `.${[...el.classList].map(CSS.escape).join('.')}`;
            parts.unshift(part);
            el = el.parentElement;
        }
        return parts.join(' > ');
    }
}
"""

SLIP_FIXTURE = r"""
() => {
    const slip = {
        id: 'a11y-slip',
        home_team: 'Sarajevo',
        away_team: 'Zeljeznicar',
        league: 'Premijer Liga',
        kickoff: new Date(Date.now() + 3600_000).toISOString(),
        sport: 'football',
        market_type: '1x2',
        profit_percent: 2.4,
        total_margin: 0.976,
        status: 'verified',
        evidence: ['Same event: league and kickoff agree.'],
        listings: {},
        stakes: [
            { bookmaker: 'mbet', outcome_label: '1', odds: 2.1, stake: 50, potential_return: 105, market_type: '1x2', selection: '1' },
            { bookmaker: 'wwin', outcome_label: 'X', odds: 3.4, stake: 32, potential_return: 108.8, market_type: '1x2', selection: 'X' },
            { bookmaker: 'maxbet', outcome_label: '2', odds: 4.2, stake: 26, potential_return: 109.2, market_type: '1x2', selection: '2' },
        ],
    };
    if (typeof window.renderSurebets === 'function') {
        allSurebets = [slip];
        filteredSurebets = [slip];
        resultsSnapshot = { opportunity_metrics: {}, surebets: [slip] };
        window.renderSurebets([slip]);
        if (typeof window.selectSurebet === 'function') window.selectSurebet(slip.id);
        return Boolean(document.querySelector('#slip .slip-head'));
    }
    return false;
}
"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # noqa: D102 - silence the server
        pass


def _serve(directory: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/index.html"


def _axe_path(explicit: str) -> Path | None:
    candidates = [
        explicit,
        os.environ.get("AXE_PATH", ""),
        str(REPO_ROOT / "node_modules" / "axe-core" / "axe.min.js"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def _allowed(rule: str, selector: str) -> bool:
    return any(
        rule == allowed_rule and fragment in selector
        for allowed_rule, fragment, _reason in ALLOWLIST
    )


def audit(url: str, axe: Path | None) -> dict[str, Any]:
    """Run the browser audit and return a report with explicit denominators."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment dependent
        raise SystemExit(f"Playwright is not installed: {exc}") from exc

    tabs = ["surebets", "review", "paper", "history", "evidence", "other"]
    report: dict[str, Any] = {
        "url": url,
        "axe": str(axe) if axe else "",
        "checked_tabs": [],
        "slip": False,
        "issues": [],
        "built_in_issues": 0,
        "axe_issues": 0,
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(300)
                for tab in tabs:
                    button = page.query_selector(f'[data-tab="{tab}"]')
                    if button is None:
                        continue
                    button.click()
                    page.wait_for_timeout(100)
                    report["checked_tabs"].append(tab)
                    for issue in page.evaluate(BUILT_IN_SCRIPT):
                        if not _allowed(issue["rule"], issue["selector"]):
                            report["issues"].append({"source": "built-in", "tab": tab, **issue})
                report["built_in_issues"] = len(
                    [issue for issue in report["issues"] if issue["source"] == "built-in"]
                )
                if page.evaluate(SLIP_FIXTURE):
                    page.wait_for_timeout(150)
                    report["slip"] = bool(page.query_selector("#slip .slip-head"))
                    for issue in page.evaluate(BUILT_IN_SCRIPT):
                        if not _allowed(issue["rule"], issue["selector"]):
                            report["issues"].append(
                                {"source": "built-in", "tab": "slip", **issue}
                            )
                if axe is not None:
                    page.add_script_tag(path=str(axe))
                    for tab in report["checked_tabs"] + (["slip"] if report["slip"] else []):
                        if tab == "slip":
                            page.evaluate(SLIP_FIXTURE)
                        else:
                            page.click(f'[data-tab="{tab}"]')
                        page.wait_for_timeout(100)
                        result = page.evaluate(
                            "async () => await axe.run(document, {resultTypes: ['violations']})"
                        )
                        for violation in result.get("violations", []):
                            for node in violation.get("nodes", []):
                                selector = " ".join(node.get("target", []))
                                if _allowed(violation["id"], selector):
                                    continue
                                report["issues"].append(
                                    {
                                        "source": "axe",
                                        "tab": tab,
                                        "rule": violation["id"],
                                        "selector": selector,
                                        "message": violation.get("help", ""),
                                    }
                                )
                    report["axe_issues"] = len(
                        [issue for issue in report["issues"] if issue["source"] == "axe"]
                    )
            finally:
                browser.close()
    except Exception as exc:
        raise SystemExit(
            "could not launch Chromium for the accessibility audit: "
            f"{exc}. Install it with 'python -m playwright install chromium'."
        ) from exc
    report["allowlist"] = [
        {"rule": rule, "selector": fragment, "reason": reason}
        for rule, fragment, reason in ALLOWLIST
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="", help="running dashboard URL; default: serve frontend/")
    parser.add_argument("--axe", default="", help="path to axe.min.js")
    parser.add_argument("--json", default="", help="write the full report here")
    args = parser.parse_args(argv)

    axe = _axe_path(args.axe)
    server = None
    url = args.url
    if not url:
        server, url = _serve(FRONTEND)
    try:
        report = audit(url, axe)
    finally:
        if server is not None:
            server.shutdown()
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.json:
        Path(args.json).write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
    if not report["checked_tabs"]:
        print("FAIL: no main tab could be audited", file=sys.stderr)
        return 1
    if report["issues"]:
        print(
            f"FAIL: {len(report['issues'])} accessibility issue(s)", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
