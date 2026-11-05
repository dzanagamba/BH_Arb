"""N2-1: paper ledger UI, paging, settle controls and CSV round-trip."""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from models.schemas import MarketType, Surebet, SurebetStake
from server import api
from server.app import app
from server.paper import PaperStore

NOW = datetime.now(UTC).replace(tzinfo=None)
KICKOFF = NOW + timedelta(hours=6)
HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")


def _surebet(
    *,
    home: str = "Sarajevo",
    odds: tuple[float, float, float] = (2.2, 4.0, 4.0),
) -> Surebet:
    labels = (("mbet", "1"), ("wwin", "X"), ("sportplus", "2"))
    margin = sum(1.0 / value for value in odds)
    stakes = []
    for (bookmaker, label), value in zip(labels, odds, strict=True):
        stake = round(100.0 * (1.0 / value) / margin, 2)
        stakes.append(
            SurebetStake(
                bookmaker=bookmaker,
                outcome_label=label,
                odds=value,
                stake=stake,
                potential_return=round(stake * value, 2),
                market_type="1x2",
                selection=label,
            )
        )
    return Surebet(
        id=f"sb-{home}",
        sport="football",
        home_team=home,
        away_team="Zeljeznicar",
        league="BiH - Premier Liga",
        kickoff=KICKOFF,
        market_type=MarketType.MATCH_RESULT,
        profit_percent=round((1.0 / margin - 1.0) * 100.0, 2),
        total_margin=round(margin, 4),
        raw_margin=round(margin, 6),
        stakes=stakes,
        found_at=NOW,
    )


def _store(tmp_path) -> PaperStore:
    store = PaperStore(str(tmp_path / "paper.sqlite3"), bankroll_start=1000.0)
    store.initialize()
    return store


def _open_position(store: PaperStore, *, home: str = "Sarajevo", scan=None):
    scan = scan or NOW - timedelta(minutes=1)
    records = store.record_opportunities(
        [_surebet(home=home)],
        feed_mode="prematch",
        run_mode="paper",
        scan_time=scan,
    )
    store.open_positions_from_scan(records, scan_time=scan)
    return store.list_positions()[0]


def _client(monkeypatch, store: PaperStore) -> TestClient:
    monkeypatch.setattr(api, "_paper_store", store)
    return TestClient(app)


def test_paper_endpoints_publish_totals_paging_and_denominators(tmp_path, monkeypatch):
    store = _store(tmp_path)
    for index in range(3):
        _open_position(store, home=f"Home {index}")
    client = _client(monkeypatch, store)

    first = client.get("/api/paper/positions?limit=2&offset=0").json()
    second = client.get("/api/paper/positions?limit=2&offset=2").json()

    assert first["no_bet_placed"] is True
    assert first["total"] == 3
    assert first["limit"] == 2
    assert len(first["positions"]) == 2
    assert len(second["positions"]) == 1
    assert {row["id"] for row in first["positions"]}.isdisjoint(
        {row["id"] for row in second["positions"]}
    )

    opportunities = client.get("/api/paper/opportunities?limit=2&offset=0").json()
    assert opportunities["total"] == 3
    assert len(opportunities["opportunities"]) == 2
    assert opportunities["run_mode"] == "all"

    summary = client.get("/api/paper/summary").json()
    assert summary["no_bet_placed"] is True
    assert summary["denominators"]["roi"] == "settled paper positions only"
    assert summary["store"]["rows"]["paper_positions"] == 3
    assert summary["store"]["bytes"] > 0
    assert summary["store"]["retention"]["paper_days"] > 0
    assert "last_maintenance" in summary["store"]


def test_filters_apply_to_opportunities_and_positions(tmp_path, monkeypatch):
    store = _store(tmp_path)
    scan = NOW - timedelta(minutes=1)
    record_only = store.record_opportunities(
        [_surebet(home="Record Only")],
        feed_mode="prematch",
        run_mode="record_only",
        scan_time=scan,
    )
    paper = store.record_opportunities(
        [_surebet(home="Paper")],
        feed_mode="live",
        run_mode="paper",
        scan_time=scan,
    )
    store.open_positions_from_scan(paper, scan_time=scan)
    client = _client(monkeypatch, store)

    record_rows = client.get(
        "/api/paper/opportunities?run_mode=record_only"
    ).json()
    assert record_rows["total"] == 1
    assert record_rows["opportunities"][0]["home_team"] == "Record Only"

    live_rows = client.get("/api/paper/positions?feed_mode=live").json()
    assert live_rows["total"] == 1
    assert live_rows["positions"][0]["home_team"] == "Paper"

    no_live = client.get("/api/paper/positions?feed_mode=prematch").json()
    assert no_live["total"] == 0
    assert record_only  # the record-only opportunity was stored, not dropped


def test_csv_round_trips_every_displayed_row(tmp_path, monkeypatch):
    store = _store(tmp_path)
    position = _open_position(store, home="CSV Home")
    client = _client(monkeypatch, store)

    displayed_positions = client.get("/api/paper/positions?limit=50").json()["positions"]
    displayed_opportunities = client.get(
        "/api/paper/opportunities?limit=50"
    ).json()["opportunities"]
    response = client.get("/api/paper/export.csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert {row["kind"] for row in rows} == {"opportunity", "position"}
    csv_positions = [row for row in rows if row["kind"] == "position"]
    csv_opportunities = [row for row in rows if row["kind"] == "opportunity"]
    assert {row["id"] for row in csv_positions} == {
        row["id"] for row in displayed_positions
    }
    assert {row["id"] for row in csv_opportunities} == {
        row["id"] for row in displayed_opportunities
    }
    position_row = next(row for row in csv_positions if row["id"] == position["id"])
    assert position_row["kind"] == "position"
    assert json.loads(position_row["legs_json"])[0]["bookmaker"] == "mbet"
    assert position_row["stake"] == "100.0"


def test_a_paper_position_can_be_settled_through_the_api(tmp_path, monkeypatch):
    store = _store(tmp_path)
    position = _open_position(store)
    client = _client(monkeypatch, store)

    response = client.post(
        f"/api/paper/positions/{position['id']}/settle",
        json={
            "legs": [
                {"outcome_label": "1", "result": "won"},
                {"outcome_label": "X", "result": "lost"},
                {"outcome_label": "2", "result": "lost"},
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "settled"
    summary = client.get("/api/paper/summary").json()
    assert summary["open_positions"] == 0
    assert summary["settled_positions"] == 1
    assert summary["roi"] is not None


def test_an_unavailable_mark_says_why(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _open_position(store)
    store.open_positions_from_scan([], scan_time=NOW + timedelta(minutes=5))
    client = _client(monkeypatch, store)

    position = client.get("/api/paper/positions").json()["positions"][0]

    assert position["mark"]["available"] is False
    assert "disappeared" in position["mark"]["reason"]


def test_the_paper_tab_is_read_only_and_has_settle_controls():
    assert 'id="paper-tab"' in HTML
    assert 'id="paper-panel"' in HTML
    assert "Paper simulation only" in HTML
    assert 'id="paper-export"' in HTML
    assert "/api/paper/export.csv" in HTML
    assert "settlePaperPosition" in JS
    assert "data-action=\"paper-settle\"" in JS
    assert "paperMarkCell" in JS
    assert "No recorded opportunities" in JS
    assert "No paper positions" in JS
    assert "settled" in JS and "unavailable" in JS
    # The paper pane must not offer a live slip or copy action.
    paper_js = JS[JS.index("function renderPaperPositions"):JS.index("async function loadHealth")]
    assert "copy-surebet" not in paper_js
    assert "copy-text" not in paper_js
    assert "log-bet" not in paper_js


NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on this machine")


def _js_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced function {name}")


def _paper_driver() -> str:
    functions = "\n".join(
        _js_function(JS, name)
        for name in (
            "paperPageLabel",
            "paperEvent",
            "paperMarkCell",
            "paperSettleCell",
            "renderPaperOpportunities",
            "renderPaperPositions",
            "renderPaperSummary",
        )
    )
    return f"""
const paperState = {{ oppOffset: 0, posOffset: 0 }};
const PAPER_PAGE_SIZE = 25;
const elements = {{}};
function element(id) {{
    if (!elements[id]) elements[id] = {{ innerHTML: '', textContent: '' }};
    return elements[id];
}}
global.document = {{ getElementById: id => element(id) }};
function escapeHtml(value) {{
    return String(value == null ? '' : value).replace(/[&<>"']/g, c => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }})[c]);
}}
function formatCount(value) {{ return Number(value || 0).toLocaleString('en-US'); }}
function money(value) {{ return Number(value || 0).toFixed(2); }}
function formatBytes(value) {{ return value == null ? 'n/a' : String(value); }}
function setText(id, value) {{ element(id).textContent = value; }}
{functions}
const empty = {{ opportunities: [], total: 0 }};
renderPaperOpportunities(empty);
renderPaperPositions({{ positions: [], total: 0 }});
const emptyHtml = element('paper-opportunities-body').innerHTML + element('paper-positions-body').innerHTML;

const openPosition = {{
    id: 'pos-open', status: 'open', home_team: 'Home', away_team: 'Away',
    league: 'League', kickoff: '2026-11-07T18:00', market_type: '1x2',
    stake: 100, simulated_profit: 2.5, entry_legs: [
        {{ outcome_label: '1' }}, {{ outcome_label: '2' }},
    ], mark: null,
}};
renderPaperPositions({{ positions: [openPosition], total: 1 }});
const openHtml = element('paper-positions-body').innerHTML;

const settledPosition = {{
    ...openPosition, id: 'pos-settled', status: 'settled', realized_profit: 4.2,
}};
renderPaperPositions({{ positions: [settledPosition], total: 1 }});
const settledHtml = element('paper-positions-body').innerHTML;

const unavailablePosition = {{
    ...openPosition, id: 'pos-unavailable',
    mark: {{ marked_at: '2026-11-07T18:05', available: false,
             matched_legs: 1, total_legs: 2, reason: '1 of 2 entry legs are no longer quoted' }},
}};
renderPaperPositions({{ positions: [unavailablePosition], total: 1 }});
const unavailableHtml = element('paper-positions-body').innerHTML;

renderPaperSummary({{
    days: 30, opportunities_recorded: 3, positions: 2, open_positions: 1,
    settled_positions: 1, staked: 100, profit: 4.2, roi: 0.042,
    hit_rate: 0.5, hit_rate_positions: 2, clv: 0.01, clv_legs: 4,
    store: {{ bytes: 2048, rows: {{ recorded_opportunities: 3, paper_positions: 2 }},
              retention: {{ paper_days: 180, paper_max_rows: 200000 }},
              last_maintenance: {{ finished_at: '2026-11-05T00:00:00' }} }},
}});
console.log(JSON.stringify({{
    emptyHtml,
    openHtml,
    settledHtml,
    unavailableHtml,
    roiSub: element('paper-roi-sub').textContent,
    hitSub: element('paper-hit-sub').textContent,
    clvSub: element('paper-clv-sub').textContent,
    store: element('paper-store').textContent,
}}));
"""


@needs_node
def test_paper_frontend_renders_empty_open_settled_and_unavailable_states():
    completed = subprocess.run(
        [NODE, "-e", _paper_driver()],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert "No recorded opportunities" in result["emptyHtml"]
    assert "No paper positions" in result["emptyHtml"]
    assert 'data-action="paper-settle"' in result["openHtml"]
    assert 'data-paper-result' in result["openHtml"]
    assert "settled" in result["settledHtml"]
    assert "4.20" in result["settledHtml"]
    assert "unavailable" in result["unavailableHtml"]
    assert "1 of 2 entry legs are no longer quoted" in result["unavailableHtml"]
    assert "settled stake" in result["roiSub"]
    assert "marked position(s)" in result["hitSub"]
    assert "leg(s) with a next-scan price" in result["clvSub"]
    assert "retention 180 day(s)" in result["store"]
