"""The Other sports tab is separate, filtered, and available in both modes."""

from pathlib import Path

HTML = Path("frontend/index.html").read_text(encoding="utf-8")
JS = Path("frontend/js/app.js").read_text(encoding="utf-8")


def test_other_sports_tab_and_panel_exist():
    assert 'id="other-tab"' in HTML
    assert 'id="other-panel"' in HTML
    assert 'data-tab-panel="other"' in HTML
    assert 'id="other-sport-filter"' in HTML
    assert 'id="other-grid"' in HTML


def test_football_panel_stays_football_only():
    assert "(sb.sport || 'football') !== 'football'" in JS
    assert "function footballSurebets()" in JS
    assert "function otherSurebets()" in JS


def test_switch_tab_accepts_other_and_renders_it():
    assert "['review', 'history', 'evidence', 'other'].includes(tab)" in JS
    assert "if (target === 'other') renderOtherSports();" in JS
    assert "setOtherSportFilter" in JS


def test_sport_filter_offers_every_reported_sport():
    assert "SPORT_LABELS" in JS
    assert "Basketball" in JS and "Tennis" in JS
    assert "All other sports" in HTML


def test_other_sports_markets_have_human_labels():
    for market in ("moneyline", "moneyline_3way", "handicap", "total"):
        assert f"'{market}'" in JS
    assert "points" in JS and "games" in JS
