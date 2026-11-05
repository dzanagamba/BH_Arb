"""The dashboard's CSP carries a per-request nonce and no script 'unsafe-inline'."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from server.app import app

NONCE_RE = re.compile(r"'nonce-([A-Za-z0-9_-]+)'")


def _script_src(csp: str) -> str:
    for directive in csp.split(";"):
        name, _, value = directive.strip().partition(" ")
        if name == "script-src":
            return value
    raise AssertionError(f"script-src is missing from CSP: {csp}")


def test_dashboard_csp_uses_a_nonce_and_not_unsafe_inline_scripts():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"

    script_src = _script_src(response.headers["content-security-policy"])
    assert "'unsafe-inline'" not in script_src
    assert "'self'" in script_src
    match = NONCE_RE.search(script_src)
    assert match, f"script-src has no nonce: {script_src}"
    nonce = match.group(1)

    # The pre-paint theme bootstrap, i18n.js and app.js all carry it.
    assert response.text.count(f'nonce="{nonce}"') == 3
    assert "__CSP_NONCE__" not in response.text


def test_each_dashboard_request_gets_a_fresh_nonce():
    client = TestClient(app)
    first = client.get("/")
    second = client.get("/")

    first_nonce = NONCE_RE.search(_script_src(first.headers["content-security-policy"]))
    second_nonce = NONCE_RE.search(_script_src(second.headers["content-security-policy"]))
    assert first_nonce and second_nonce
    assert first_nonce.group(1) != second_nonce.group(1)

    # The markup must carry the nonce from its own header, not the previous
    # response's. A cache that replayed the old HTML would fail this.
    assert f'nonce="{first_nonce.group(1)}"' in first.text
    assert f'nonce="{second_nonce.group(1)}"' in second.text
    assert f'nonce="{first_nonce.group(1)}"' not in second.text


def test_api_responses_still_carry_the_hardening_headers():
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in _script_src(response.headers["content-security-policy"])
