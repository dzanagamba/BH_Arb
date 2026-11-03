/**
 * Surebet BiH — dashboard
 *
 * Two jobs, in this order:
 *  1. Show which surebets the last scan found (left list).
 *  2. Help place one (right bet slip): re-check the odds first, then give each
 *     leg in the order to place it, with a stake you can actually type, the
 *     bookmaker page to open, and how that bookmaker spells the match. When a
 *     leg is placed at different odds, the remaining stakes are re-planned.
 *
 * The "why is there no surebet" diagnostic and the review queue are kept from
 * the previous dashboard; their contracts are pinned by tests/test_frontend_*.py.
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let currentMode = 'prematch';       // 'prematch' (upcoming) | 'live' (in-play)
let activeScanMode = null;          // mode of the currently running scan
let activeTab = 'surebets';         // 'surebets' | 'review' | 'history'
let candidateApiKey = '';           // in-memory key for configured review mutations
let allSurebets = [];               // full list from the server
let filteredSurebets = [];          // after client-side filtering
let selectedSurebetId = null;       // the surebet open in the bet slip
let pollingInterval = null;
let activeBookmakers = new Set(['mozzartbet', 'mdshop', 'admiralbet', 'betole', 'mbet', 'sportplus', 'evlbet', 'premier_kladionica', 'wwin']);
let bookmakersConfig = {};
let globalInvestment = 100;
let stakeRounding = '1';            // 'exact' | '1' | '5' — whole KM by default
let soundMuted = true;
let audioContext = null;
let autoRescanTimer = null;
let knownSurebetSignatures = new Set();
let healthSnapshot = null;          // last /api/health payload, kept for the no-surebet diagnostic
let resultsSnapshot = null;         // last /api/results payload, same reason
let noSurebetReasons = null;        // the diagnostic copy table, fetched once at start-up
let currentCandidates = [];         // the review page on screen
const verifyState = {};             // surebet id -> {state, at, data}
const slipState = {};               // surebet id -> {investment, placed: {label: {odds, stake}}}

// How long a re-check counts as fresh enough to place on.
const VERIFY_FRESH_SECONDS = { prematch: 120, live: 30 };

// Reviewer-facing wording for deterministic gate codes. Keep the raw code in
// the rendered title attribute so diagnostics remain available to operators.
const REASON_LABELS = Object.freeze({
    league_mismatch: 'Different league',
    kickoff_delta: 'Kickoff too far apart',
    link_unverified: 'Link not verified',
    team_unresolved: 'Teams do not match',
    category_mismatch: 'Different match category',
    betradar_mismatch: 'Different Betradar match id',
    kickoff_missing: 'Kickoff time missing',
    orientation_unresolved: 'Home/away order unclear',
    no_event_link: 'No event link',
});

const SUREBET_STATUS_LABELS = Object.freeze({
    verified: { label: 'Verified pairing', ariaLabel: 'Verified match pairing' },
    suggested: { label: 'Suggested pairing', ariaLabel: 'Suggested match pairing' },
    rejected: { label: 'Rejected pairing', ariaLabel: 'Rejected match pairing' },
});

const BOOKMAKER_COLORS = {
    mozzartbet: '#FF6B00',
    mdshop:     '#22c55e',
    admiralbet: '#3b82f6',
    betole:     '#ef4444',
    mbet:       '#E91E63',
    sportplus:  '#FF5722',
    evlbet:     '#9C27B0',
    premier_kladionica: '#16A34A',
    wwin:       '#EF4444',
};

const MARKET_LABELS = {
    '1x2':            '1X2',
    'over_under_1_5': 'O/U 1.5',
    'over_under_2_5': 'O/U 2.5',
    'over_under_3_5': 'O/U 3.5',
    'btts':           'BTTS',
    'double_chance':  '1X2 + DC',
    'first_half_1x2': '1H 1X2',
    'first_half_ou':  '1H O/U',
    'asian_handicap': 'Asian Hcp',
};

// What each outcome label means, in words a bettor types into a ticket.
function outcomeDescription(label, marketType) {
    const half = marketType && marketType.startsWith('first_half') ? ' (1st half)' : '';
    const words = {
        '1': 'Home win', 'X': 'Draw', '2': 'Away win',
        '1X': 'Home or draw', 'X2': 'Draw or away', '12': 'Home or away',
        'GG': 'Both teams score', 'NG': 'Not both teams score',
    };
    if (words[label]) return words[label] + half;
    const over = /^Over (.+)$/.exec(label);
    if (over) return `Over ${over[1]} goals${half}`;
    const under = /^Under (.+)$/.exec(label);
    if (under) return `Under ${under[1]} goals${half}`;
    return label + half;
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    restorePreferences();
    restoreMode();
    updateThemeButton();
    await loadConfig();
    initBookmakerChips();
    // The diagnostic copy table is static and local, so it is read once, before
    // the first render. A panel must never be painted from a table that has not
    // arrived, and must never fall back to a sentence that names the wrong cause.
    await loadNoSurebetReasons();
    await loadResults(true);
    const tabs = document.querySelector('.results-tabs');
    if (tabs) tabs.addEventListener('keydown', handleTabKeydown);
    document.addEventListener('keydown', handleGlobalKeydown);
    // Health and review-queue refresh share one 30-second cadence.
    refreshDiagnostics();
    diagnosticsTimer = setInterval(refreshDiagnostics, 30000);
    // Ages on screen ("re-checked 12s ago") tick once a second.
    setInterval(tickAges, 1000);
});

function restoreMode() {
    try {
        const saved = localStorage.getItem('currentMode');
        if (saved === 'live' || saved === 'prematch') currentMode = saved;
    } catch (e) { /* localStorage unavailable */ }
    updateModeToggleUI();
}

function updateModeToggleUI() {
    for (const mode of ['prematch', 'live']) {
        const button = document.getElementById(`mode-${mode}`);
        if (!button) continue;
        button.classList.toggle('active', currentMode === mode);
        button.setAttribute('aria-selected', String(currentMode === mode));
    }
}

function restorePreferences() {
    try {
        stakeRounding = localStorage.getItem('stakeRounding') || '1';
        soundMuted = localStorage.getItem('soundMuted') !== '0';
    } catch (e) { /* localStorage unavailable */ }
    const roundingEl = document.getElementById('filter-rounding');
    if (roundingEl) roundingEl.value = stakeRounding;
    const sound = document.getElementById('sound-toggle');
    if (sound) sound.checked = !soundMuted;
}

async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        bookmakersConfig = data.bookmakers || {};
        const minInput = document.getElementById('filter-profit');
        if (data.min_profit_percent && minInput) minInput.value = data.min_profit_percent;
        const investInput = document.getElementById('filter-investment');
        if (data.default_investment) {
            globalInvestment = data.default_investment;
            if (investInput) investInput.value = data.default_investment;
        }
        if (data.experimental_markets) {
            document.querySelectorAll('.exp-check').forEach(label => {
                const market = label.dataset.market;
                const box = label.querySelector('input[type="checkbox"]');
                if (box && market in data.experimental_markets) {
                    box.checked = !!data.experimental_markets[market];
                }
            });
        }
    } catch (e) {
        console.warn('Config load failed:', e);
    }
}

// ─── Navigation ───────────────────────────────────────────────────────────────
function switchTab(tab) {
    const target = ['review', 'history'].includes(tab) ? tab : 'surebets';
    activeTab = target;
    document.querySelectorAll('.results-tabs [role="tab"]').forEach(button => {
        const isActive = button.dataset.tab === target;
        button.classList.toggle('active', isActive);
        button.setAttribute('aria-selected', String(isActive));
        button.tabIndex = isActive ? 0 : -1;
    });
    document.querySelectorAll('[data-tab-panel]').forEach(panel => {
        const isActive = panel.dataset.tabPanel === target;
        panel.hidden = !isActive;
        panel.setAttribute('aria-hidden', String(!isActive));
    });
    if (target === 'review') loadCandidates();
    if (target === 'history') loadHistory();
}

function handleTabKeydown(event) {
    const tab = event.target.closest('[role="tab"]');
    if (!tab) return;
    const tabs = [...document.querySelectorAll('.results-tabs [role="tab"]')];
    const currentIndex = tabs.indexOf(tab);
    if (currentIndex < 0) return;
    let nextIndex = null;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = tabs.length - 1;
    if (nextIndex !== null) {
        event.preventDefault();
        tabs[nextIndex].focus();
        switchTab(tabs[nextIndex].dataset.tab);
    }
}

// j/k move through the list, Escape closes the settings drawer.
function handleGlobalKeydown(event) {
    if (event.key === 'Escape') { toggleSettings(false); return; }
    const typing = event.target.closest('input, select, textarea');
    if (typing || activeTab !== 'surebets' || !filteredSurebets.length) return;
    if (event.key !== 'j' && event.key !== 'k') return;
    const index = filteredSurebets.findIndex(sb => sb.id === selectedSurebetId);
    const step = event.key === 'j' ? 1 : -1;
    const next = Math.min(filteredSurebets.length - 1, Math.max(0, index + step));
    selectSurebet(filteredSurebets[next].id);
}

function switchMode(mode) {
    if (mode !== 'prematch' && mode !== 'live') return;
    if (mode === currentMode) return;
    currentMode = mode;
    try { localStorage.setItem('currentMode', mode); } catch (e) { /* ignore */ }
    updateModeToggleUI();
    hideError();
    selectedSurebetId = null;
    loadResults(true);
    if (activeTab === 'review') loadCandidates();
}

// System → light → dark. The choice is applied before first paint by an inline
// script in index.html; here it is only changed and saved.
const THEMES = ['system', 'light', 'dark'];

function currentTheme() {
    const pinned = document.documentElement.dataset.theme;
    return pinned === 'light' || pinned === 'dark' ? pinned : 'system';
}

function cycleTheme() {
    const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
    if (next === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (e) { /* ignore */ }
    updateThemeButton();
    showToast(`Theme: ${next}`);
}

function updateThemeButton() {
    const button = document.getElementById('theme-btn');
    if (button) button.title = `Theme: ${currentTheme()} (click to change)`;
}

function toggleSettings(open) {
    const drawer = document.getElementById('settings-drawer');
    const backdrop = document.getElementById('settings-backdrop');
    if (!drawer || !backdrop) return;
    drawer.hidden = !open;
    backdrop.hidden = !open;
    if (open) loadHealth();
}

// ─── Bookmakers & markets (settings) ─────────────────────────────────────────
function initBookmakerChips() {
    const container = document.getElementById('bookie-chips');
    const wall = document.getElementById('empty-state-bookies');
    const bookieList = Object.keys(bookmakersConfig).length > 0
        ? Object.entries(bookmakersConfig)
        : Object.entries(BOOKMAKER_COLORS).map(([k]) => [k, { name: capitalize(k), color: BOOKMAKER_COLORS[k], enabled: true }]);

    activeBookmakers = new Set();
    bookieList.forEach(([id, cfg]) => { if (cfg.enabled !== false) activeBookmakers.add(id); });

    if (container) {
        container.innerHTML = '';
        bookieList.forEach(([id, cfg]) => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'chip' + (cfg.enabled !== false ? ' active' : '');
            chip.style.setProperty('--chip-color', cfg.color || BOOKMAKER_COLORS[id] || '#888');
            chip.textContent = cfg.name || capitalize(id);
            chip.setAttribute('aria-pressed', String(cfg.enabled !== false));
            chip.addEventListener('click', () => toggleBookmakerAPI(chip, id));
            container.appendChild(chip);
        });
    }
    if (wall) {
        wall.innerHTML = bookieList
            .filter(([, cfg]) => cfg.enabled !== false)
            .map(([id, cfg]) => `<span class="book-tag" style="--color:${escapeHtml(cfg.color || BOOKMAKER_COLORS[id] || '#888')}">${escapeHtml(cfg.name || capitalize(id))}</span>`)
            .join('');
    }
}

async function toggleBookmakerAPI(chip, id) {
    try {
        const res = await fetch(`/api/config/toggle/${id}`, { method: 'POST', headers: candidateActionHeaders() });
        const data = await res.json();
        if (data.status === 'ok') {
            chip.classList.toggle('active', data.enabled);
            chip.setAttribute('aria-pressed', String(data.enabled));
            if (data.enabled) activeBookmakers.add(id); else activeBookmakers.delete(id);
            if (bookmakersConfig[id]) bookmakersConfig[id].enabled = data.enabled;
            applyFilters();
        }
    } catch (e) {
        console.warn('Toggle failed:', e);
    }
}

async function toggleExperimentalMarket(box) {
    try {
        const res = await fetch(`/api/config/toggle_market/${box.value}`, { method: 'POST', headers: candidateActionHeaders() });
        const data = await res.json();
        if (data.status === 'ok') {
            box.checked = data.enabled;
            showToast(`${data.enabled ? 'Enabled' : 'Disabled'} — applies on the next scan`);
        } else {
            box.checked = !box.checked;
        }
    } catch (e) {
        box.checked = !box.checked;
    }
}

function setStakeRounding(mode) {
    stakeRounding = mode;
    try { localStorage.setItem('stakeRounding', mode); } catch (e) { /* ignore */ }
    renderSlip();
}

function recalculateAll(investment) {
    const value = parseFloat(investment);
    if (!value || value <= 0) return;
    globalInvestment = value;
    // A slip the user has not touched follows the default.
    Object.values(slipState).forEach(state => { if (!state.touched) state.investment = value; });
    // Rows and the summary quote earnings on the default stake, so they redraw too.
    applyFilters();
}

// ─── Scan ─────────────────────────────────────────────────────────────────────
async function scanNow() {
    const btn = document.getElementById('scan-btn');
    if (btn.disabled) return;
    try {
        const res = await fetch(`/api/scan?mode=${currentMode}`, { method: 'POST', headers: candidateActionHeaders() });
        const data = await res.json();
        if (res.status === 429) {
            showError(data.detail || 'Too many scans — wait a moment.');
            return;
        }
        if (data.status === 'already_scanning') {
            setStatus('scanning', 'Scan in progress…');
            startPolling();
            return;
        }
        btn.disabled = true;
        btn.textContent = 'Scanning…';
        activeScanMode = currentMode;
        showScanProgress();
        setStatus('scanning', `Scanning ${currentMode === 'live' ? 'live' : 'upcoming'} matches…`);
        startPolling();
    } catch (e) {
        showError('Could not start the scan: ' + e.message);
    }
}

let diagnosticsTimer = null;

function startPolling() {
    if (pollingInterval) return;
    pollingInterval = setInterval(pollStatus, 2000);
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function setAutoRescan(minutes) {
    if (autoRescanTimer) {
        clearInterval(autoRescanTimer);
        autoRescanTimer = null;
    }
    const countdownEl = document.getElementById('autorescan-countdown');
    if (!minutes || minutes <= 0) {
        if (countdownEl) countdownEl.style.display = 'none';
        return;
    }
    let remaining = minutes * 60;
    autoRescanTimer = setInterval(() => {
        remaining -= 1;
        if (countdownEl) {
            countdownEl.style.display = '';
            const m = Math.floor(remaining / 60);
            const s = (remaining % 60).toString().padStart(2, '0');
            countdownEl.textContent = `next scan ${m}:${s}`;
        }
        if (remaining <= 0) {
            remaining = minutes * 60;
            scanNow();
        }
    }, 1000);
}

async function pollStatus() {
    const pollMode = activeScanMode || currentMode;
    try {
        const res = await fetch(`/api/status?mode=${pollMode}`);
        const status = await res.json();
        updateScanProgress(status);
        if (!status.is_scanning) {
            stopPolling();
            activeScanMode = null;
            await onScanComplete(status);
        }
    } catch (e) {
        console.warn('Status poll failed:', e);
    }
}

function updateScanProgress(status) {
    const subEl = document.getElementById('scan-progress-sub');
    const doneEl = document.getElementById('scan-bookies-done');
    const barEl = document.getElementById('scan-bar');
    if (subEl) subEl.textContent = status.current_bookmaker || 'Processing…';
    setStatus('scanning', status.current_bookmaker || 'Scanning…');
    if (doneEl) {
        const progress = status.bookmaker_progress || {};
        doneEl.innerHTML = Object.entries(progress).map(([id, state]) => {
            if (state === 'skipped') return '';
            const name = escapeHtml(bookmakersConfig[id]?.name || capitalize(id));
            return `<span class="scan-bookie scan-bookie-${escapeHtml(state)}">${name}</span>`;
        }).join('');
    }
    const total = Object.values(bookmakersConfig).filter(c => c.enabled !== false).length || 4;
    const done = (status.bookmakers_done || []).length;
    if (barEl) barEl.style.width = Math.min(92, (done / total) * 85 + 5) + '%';
}

async function onScanComplete(status) {
    const barEl = document.getElementById('scan-bar');
    if (barEl) barEl.style.width = '100%';
    hideScanProgress();
    const btn = document.getElementById('scan-btn');
    btn.disabled = false;
    btn.textContent = 'Scan now';
    if (status.errors && status.errors.length > 0) {
        showError('Some bookmakers failed: ' + status.errors.slice(0, 3).join('; '));
    }
    setStatus('done', status.surebets_found > 0
        ? `${status.surebets_found} surebet${status.surebets_found > 1 ? 's' : ''} found`
        : 'Scan complete — no surebets');
    await loadResults();
    loadCandidates();
}

// ─── Results ──────────────────────────────────────────────────────────────────
async function loadResults(silent = false) {
    try {
        const res = await fetch(`/api/results?mode=${currentMode}`);
        const data = await res.json();
        allSurebets = data.surebets || [];
        // `match_groups` is the mode-correct count of groups the certainty gate
        // accepted; the health payload's equivalent is prematch-only.
        resultsSnapshot = data;

        setText('stat-matches', data.total_matches != null ? data.total_matches.toLocaleString() : '—');
        setText('stat-groups', data.match_groups != null ? Number(data.match_groups).toLocaleString() : '—');
        setText('stat-time', data.last_scan_time ? formatAgo(parseKickoff(data.last_scan_time)) : 'never');

        if (selectedSurebetId && !allSurebets.some(sb => sb.id === selectedSurebetId)) {
            selectedSurebetId = null;
        }
        applyFilters();

        // Chime for NEW high-value surebets only — never on page load, never
        // twice for the same surebet across rescans.
        const signatures = new Set(allSurebets.map(surebetSignature));
        if (!silent && allSurebets.some(s => s.profit_percent >= 3.0 && !knownSurebetSignatures.has(surebetSignature(s)))) {
            playAlertSound();
        }
        knownSurebetSignatures = signatures;
    } catch (e) {
        console.error('Failed to load results:', e);
    }
}

function surebetSignature(sb) {
    const stakes = sb.stakes
        .map(s => `${s.bookmaker}:${s.outcome_label}:${s.odds}`)
        .sort()
        .join('|');
    return `${sb.home_team}|${sb.away_team}|${sb.market_type}|${stakes}`;
}

function applyFilters() {
    const marketFilter = document.getElementById('filter-market').value;
    const profitInput = document.getElementById('filter-profit').value;
    const minProfit = profitInput !== '' ? parseFloat(profitInput) : 0;
    const searchTerm = document.getElementById('filter-search').value.trim().toLowerCase();
    const sortMode = document.getElementById('filter-sort').value;

    filteredSurebets = allSurebets.filter(sb => {
        if (marketFilter && sb.market_type !== marketFilter) return false;
        if (sb.profit_percent < minProfit) return false;
        // Every leg's bookmaker has to be one you have turned on.
        if (!sb.stakes.every(s => activeBookmakers.has(s.bookmaker))) return false;
        if (searchTerm) {
            const listed = Object.values(sb.listings || {}).map(l => `${l.home} ${l.away} ${l.league}`).join(' ');
            const haystack = `${sb.home_team} ${sb.away_team} ${sb.league || ''} ${listed}`.toLowerCase();
            if (!haystack.includes(searchTerm)) return false;
        }
        return true;
    });

    filteredSurebets.sort((a, b) => {
        if (sortMode === 'kickoff') {
            const ta = a.kickoff ? parseKickoff(a.kickoff).getTime() : Number.MAX_SAFE_INTEGER;
            const tb = b.kickoff ? parseKickoff(b.kickoff).getTime() : Number.MAX_SAFE_INTEGER;
            return ta - tb;
        }
        if (sortMode === 'league') return (a.league || '').localeCompare(b.league || '');
        return b.profit_percent - a.profit_percent;
    });

    renderSurebets(filteredSurebets);
}

function resetFilters() {
    document.getElementById('filter-market').value = '';
    document.getElementById('filter-profit').value = '0';
    document.getElementById('filter-search').value = '';
    document.getElementById('filter-sort').value = 'profit';
    applyFilters();
}

// One chip per market the scan found, with its count; the active one is kept
// even when it has none, so a filter can always be switched off.
function renderMarketChips() {
    const wrap = document.getElementById('market-chips');
    const active = document.getElementById('filter-market').value;
    if (!wrap) return;
    const counts = {};
    allSurebets.forEach(sb => { counts[sb.market_type] = (counts[sb.market_type] || 0) + 1; });
    const markets = Object.keys(MARKET_LABELS).filter(m => counts[m] || m === active);
    wrap.hidden = allSurebets.length === 0;
    wrap.innerHTML = [['', 'All', allSurebets.length], ...markets.map(m => [m, MARKET_LABELS[m], counts[m] || 0])]
        .map(([value, label, count]) => `<button type="button" class="mchip${value === active ? ' active' : ''}" aria-pressed="${value === active}" onclick="setMarketFilter('${escapeHtml(value)}')">${escapeHtml(label)} <b>${count}</b></button>`)
        .join('');
}

function setMarketFilter(market) {
    document.getElementById('filter-market').value = market;
    applyFilters();
}

function renderKpis(surebets) {
    const best = surebets.reduce((top, sb) => (!top || sb.profit_percent > top.profit_percent ? sb : top), null);
    const hero = document.querySelector('.kpi-hero');
    if (hero) hero.toggleAttribute('data-empty', !best);
    setText('kpi-best', best ? `${best.profit_percent.toFixed(2)}%` : '—');
    setText('kpi-best-sub', best
        ? `+${money(globalInvestment * best.profit_percent / 100)} KM on ${globalInvestment} KM · ${formatTeamName(best.home_team)}`
        : 'no surebet yet');
    setText('kpi-count', surebets.length);
    setText('kpi-count-sub', allSurebets.length > surebets.length
        ? `of ${allSurebets.length} found · ${allSurebets.length - surebets.length} filtered out`
        : 'above your minimum');
    setText('kpi-mode-sub', currentMode === 'live' ? 'live matches' : 'upcoming matches');
}

function renderSurebets(surebets) {
    const grid = document.getElementById('results-grid');
    setText('surebets-count', surebets.length);
    renderKpis(surebets);
    renderMarketChips();
    grid.innerHTML = '';
    const hint = document.getElementById('list-hint');
    if (hint) hint.hidden = surebets.length < 2;

    // Anything the list cannot show is handed to the diagnostic, which decides
    // which panel is up and what it says. It is never told "show the empty
    // state" — only "there is nothing to show".
    if (allSurebets.length === 0 || surebets.length === 0) {
        grid.hidden = true;
        renderNoSurebetState();
        renderSlip();
        return;
    }
    grid.hidden = false;
    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('no-results').style.display = 'none';

    surebets.forEach(sb => grid.appendChild(buildSurebetRow(sb)));
    if (!selectedSurebetId || !surebets.some(sb => sb.id === selectedSurebetId)) {
        // Open the best one straight away on a wide screen; on a phone the list
        // comes first and a tap opens the slip.
        if (window.matchMedia('(min-width: 900px)').matches) selectSurebet(surebets[0].id);
        else renderSlip();
    } else {
        markSelectedRow();
        renderSlip();
    }
}

function buildSurebetRow(sb) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'sb-row';
    row.dataset.id = sb.id;
    row.setAttribute('role', 'option');
    row.dataset.tier = profitTier(sb.profit_percent);
    const kickoff = parseKickoff(sb.kickoff);
    const when = currentMode === 'live' ? 'In play' : (kickoff ? formatKickoff(kickoff) : '');
    // Kickoff inside the hour is flagged: the window to place all legs is closing.
    const minutesAway = kickoff ? (kickoff.getTime() - Date.now()) / 60000 : null;
    const whenClass = currentMode === 'live' ? ' live' : (minutesAway != null && minutesAway >= 0 && minutesAway < 60 ? ' soon' : '');
    const whenText = whenClass === ' soon' ? `in ${Math.max(1, Math.round(minutesAway))} min` : when;
    const legs = placementOrder(sb.stakes).map(s => `
        <span class="leg-pill" title="${escapeHtml(bookName(s.bookmaker))}: ${escapeHtml(outcomeDescription(s.outcome_label, sb.market_type))} at ${s.odds.toFixed(2)}">
            <span class="book-dot" style="--color:${escapeHtml(bookColor(s.bookmaker))}">${escapeHtml(bookShort(s.bookmaker))}</span>
            <span class="leg-pick">${escapeHtml(s.outcome_label)}</span>
            <span class="leg-odds">${s.odds.toFixed(2)}</span>
        </span>`).join('');
    const check = verifyState[sb.id];
    const badge = check ? `<span class="row-check row-check-${escapeHtml(check.state)}">${escapeHtml(verifyShortLabel(check))}</span>` : '';
    // What the default stake would earn at the scanned, unrounded prices.
    const earns = globalInvestment * sb.profit_percent / 100;
    row.innerHTML = `
        <span class="row-profit"><b>${sb.profit_percent.toFixed(2)}%</b><small>+${money(earns)} KM</small></span>
        <span class="row-main">
            <span class="row-teams">${escapeHtml(formatTeamName(sb.home_team))} – ${escapeHtml(formatTeamName(sb.away_team))}</span>
            <span class="row-meta"><span class="mkt">${escapeHtml(MARKET_LABELS[sb.market_type] || sb.market_type)}</span><span class="row-when${whenClass}">${escapeHtml(whenText)}</span><span class="row-league">${escapeHtml(formatLeague(sb.league))}</span></span>
        </span>
        <span class="row-legs">${legs}</span>${badge}
    `;
    row.addEventListener('click', () => selectSurebet(sb.id));
    return row;
}

function profitTier(profit) {
    if (profit >= 3) return 'high';
    if (profit >= 1.5) return 'mid';
    if (profit >= 0.5) return 'low';
    return 'dust';
}

function markSelectedRow() {
    document.querySelectorAll('.sb-row').forEach(row => {
        const on = row.dataset.id === selectedSurebetId;
        row.classList.toggle('selected', on);
        row.setAttribute('aria-selected', String(on));
    });
}

function selectSurebet(id) {
    selectedSurebetId = id;
    markSelectedRow();
    document.body.classList.add('slip-open');
    renderSlip();
    const check = verifyState[id];
    // Odds are re-checked whenever a slip is opened and the last check is not fresh.
    if (!check || (check.state !== 'checking' && !verifyIsFresh(check))) verifySurebet(id);
    const row = document.querySelector(`.sb-row[data-id="${CSS.escape(id)}"]`);
    if (row) row.scrollIntoView({ block: 'nearest' });
}

function closeSlip() {
    document.body.classList.remove('slip-open');
}

// ─── Bet slip ─────────────────────────────────────────────────────────────────
function roundStake(value) {
    if (stakeRounding === '1') return Math.round(value);
    if (stakeRounding === '5') return Math.round(value / 5) * 5;
    return Math.round(value * 100) / 100;
}

function stakeFormat(value) {
    return roundStake(value).toFixed(stakeRounding === 'exact' ? 2 : 0);
}

function money(value) {
    return (Math.round(value * 100) / 100).toFixed(2);
}

// The order to place legs in: highest odds first. The long price is the one a
// bookmaker is quickest to move or limit, so it is the one to secure while the
// short, stable legs can still be adjusted around it.
function placementOrder(stakes) {
    return [...stakes].sort((a, b) => b.odds - a.odds);
}

/**
 * Stakes for every leg, as typed amounts.
 *
 * With nothing placed, stakes split `investment` so every outcome returns the
 * same, then are rounded. Once a leg is placed (at the odds actually taken and
 * the stake actually typed), the remaining legs are re-planned to return at
 * least what that leg returns, so a moved price is absorbed by the legs still
 * to place instead of silently breaking the arbitrage.
 */
function planStakes(stakes, investment, placed) {
    const placedLegs = stakes.filter(s => placed[s.outcome_label]);
    let legs;
    if (!placedLegs.length) {
        const margin = stakes.reduce((sum, s) => sum + 1 / s.odds, 0);
        legs = stakes.map(s => ({
            ...s, plannedStake: roundStake(investment * (1 / s.odds) / margin), takenOdds: s.odds, placed: false,
        }));
    } else {
        const target = Math.max(...placedLegs.map(s => placed[s.outcome_label].stake * placed[s.outcome_label].odds));
        legs = stakes.map(s => {
            const done = placed[s.outcome_label];
            if (done) return { ...s, plannedStake: done.stake, takenOdds: done.odds, placed: true };
            // Round up so the re-planned leg never returns less than the target.
            const raw = target / s.odds;
            const up = stakeRounding === '5' ? Math.ceil(raw / 5) * 5 : stakeRounding === '1' ? Math.ceil(raw) : Math.ceil(raw * 100) / 100;
            return { ...s, plannedStake: up, takenOdds: s.odds, placed: false };
        });
    }
    const total = legs.reduce((sum, leg) => sum + leg.plannedStake, 0);
    const returns = legs.map(leg => leg.plannedStake * leg.takenOdds);
    const worst = Math.min(...returns);
    return { legs, total, worst, profit: worst - total, profitPercent: total > 0 ? (worst / total - 1) * 100 : 0 };
}

// The legs at the prices the latest re-check saw. A leg whose price moved at
// the same bookmaker is planned at the new price; one that moved to another
// bookmaker or vanished keeps the scanned price and is flagged on the leg.
function currentStakes(sb, check) {
    const drift = check?.state === 'ok' || check?.state === 'gone' ? check.data?.drift || {} : {};
    return sb.stakes.map(stake => {
        const moved = drift[stake.outcome_label];
        if (moved && moved.changed && moved.new_odds != null && moved.new_bookmaker === stake.bookmaker) {
            return { ...stake, odds: Number(moved.new_odds), scannedOdds: stake.odds };
        }
        return stake;
    });
}

function slipFor(sb) {
    if (!slipState[sb.id]) slipState[sb.id] = { investment: globalInvestment, placed: {}, touched: false };
    return slipState[sb.id];
}

function renderSlip() {
    const pane = document.getElementById('slip');
    if (!pane) return;
    const sb = allSurebets.find(s => s.id === selectedSurebetId);
    if (!sb || !filteredSurebets.some(s => s.id === sb.id)) {
        pane.innerHTML = `
            <div class="slip-placeholder">
                <h3>Bet slip</h3>
                <p>Pick a surebet on the left. Its odds are re-checked first, then you get each leg in the order to place it, with the stake to type.</p>
            </div>`;
        return;
    }
    const state = slipFor(sb);
    const check = verifyState[sb.id];
    const plan = planStakes(placementOrder(currentStakes(sb, check)), state.investment, state.placed);
    const kickoff = parseKickoff(sb.kickoff);
    const exactProfit = sb.profit_percent;
    const roundingCost = exactProfit - plan.profitPercent;

    const warnings = [];
    if (plan.profit <= 0) {
        warnings.push(`<div class="slip-alert slip-alert-bad">With these stakes the worst outcome loses ${money(-plan.profit)} KM. ${Object.keys(state.placed).length ? 'A placed price moved — consider stopping or hedging rather than placing the rest.' : 'Raise the total stake or round to exact amounts.'}</div>`);
    } else if (!Object.keys(state.placed).length && roundingCost > exactProfit / 2) {
        warnings.push(`<div class="slip-alert">Rounding eats more than half the edge (${plan.profitPercent.toFixed(2)}% left of ${exactProfit.toFixed(2)}%). A larger total stake keeps more of it.</div>`);
    }
    if (plan.legs.some(leg => !leg.placed && leg.plannedStake < 1)) {
        warnings.push('<div class="slip-alert">A stake is below 1 KM — most bookmakers will not take it.</div>');
    }

    const listings = sb.listings || {};
    const legsHtml = plan.legs.map((leg, index) => {
        const name = bookName(leg.bookmaker);
        const listing = listings[leg.bookmaker];
        const listedAs = listing ? `${listing.home} – ${listing.away}` : `${formatTeamName(sb.home_team)} – ${formatTeamName(sb.away_team)}`;
        const url = (sb.bet_urls && sb.bet_urls[leg.bookmaker]) || (sb.match_urls && sb.match_urls[leg.bookmaker]) || '';
        const drift = check?.data?.drift?.[leg.outcome_label];
        let driftNote = '';
        if (leg.scannedOdds != null && !leg.placed) {
            driftNote = `<span class="leg-drift">was ${leg.scannedOdds.toFixed(2)} at scan</span>`;
        } else if (drift && drift.changed && !leg.placed) {
            driftNote = `<span class="leg-drift leg-drift-bad">${drift.new_odds != null ? 'best now ' + Number(drift.new_odds).toFixed(2) + ' at ' + escapeHtml(bookName(drift.new_bookmaker)) : 'no longer offered'}</span>`;
        }
        const stakeText = leg.plannedStake.toFixed(stakeRounding === 'exact' ? 2 : 0);
        const label = escapeHtml(leg.outcome_label);
        return `
        <li class="leg${leg.placed ? ' leg-placed' : ''}" style="--color:${escapeHtml(bookColor(leg.bookmaker))}" data-label="${label}">
            <div class="leg-step">${index + 1}</div>
            <div class="leg-body">
                <div class="leg-head">
                    <span class="leg-book">${escapeHtml(name)}</span>
                    ${url ? `<a class="btn btn-small" href="${escapeHtml(url)}" target="_blank" rel="noopener" onclick="copyText(${escapeHtml(JSON.stringify(listedAs))}, 'Match name copied — paste it into the site search')">Open ${escapeHtml(name)} ↗</a>` : ''}
                </div>
                <div class="leg-listing">
                    <span title="How ${escapeHtml(name)} lists this match">${escapeHtml(listedAs)}</span>
                    <button type="button" class="link-btn" onclick="copyText(${escapeHtml(JSON.stringify(listedAs))}, 'Match name copied')">copy name</button>
                    ${listing?.league ? `<span class="leg-league">${escapeHtml(listing.league)}</span>` : ''}
                </div>
                <div class="leg-bet">
                    <div><span class="leg-k">Pick</span><span class="leg-v">${label}</span><span class="leg-sub">${escapeHtml(outcomeDescription(leg.outcome_label, sb.market_type))}</span></div>
                    <div><span class="leg-k">Odds</span><span class="leg-v mono">${leg.takenOdds.toFixed(2)}</span>${driftNote}</div>
                    <div><span class="leg-k">Stake</span>
                        <button type="button" class="leg-v mono stake-copy" title="Copy stake" onclick="copyText('${stakeText}', 'Stake copied')">${stakeText} KM</button>
                    </div>
                    <div><span class="leg-k">Returns</span><span class="leg-v mono">${money(leg.plannedStake * leg.takenOdds)}</span></div>
                </div>
                <div class="leg-placed-row">
                    ${leg.placed
                        ? `<span class="placed-tag">Placed at ${leg.takenOdds.toFixed(2)} for ${stakeText} KM</span>
                           <button type="button" class="link-btn" onclick="unmarkPlaced('${escapeHtml(sb.id)}', ${escapeHtml(JSON.stringify(leg.outcome_label))})">undo</button>`
                        : `<label class="placed-odds">Odds taken <input class="input input-narrow mono" type="number" step="0.01" min="1.01" value="${leg.odds.toFixed(2)}" data-placed-odds></label>
                           <button type="button" class="btn btn-secondary btn-small" onclick="markPlaced('${escapeHtml(sb.id)}', ${escapeHtml(JSON.stringify(leg.outcome_label))}, this)">Mark placed</button>`}
                </div>
            </div>
        </li>`;
    }).join('');

    const evidence = (sb.evidence || []).map(line => `<li>${escapeHtml(line)}</li>`).join('');
    const placedCount = Object.keys(state.placed).length;
    const locked = placedCount ? ' disabled title="Fixed once a leg is placed"' : '';
    const presets = [50, 100, 200, 500].map(amount => `
        <button type="button" class="${Number(state.investment) === amount ? 'active' : ''}"${locked}
                onclick="setSlipInvestment('${escapeHtml(sb.id)}', ${amount})">${amount}</button>`).join('');

    pane.innerHTML = `
        <div class="slip-head">
            <button type="button" class="link-btn slip-back" onclick="closeSlip()">← All surebets</button>
            <div class="slip-eyebrow">
                <span class="mkt">${escapeHtml(MARKET_LABELS[sb.market_type] || sb.market_type)}</span>
                <span>${escapeHtml(formatLeague(sb.league))}</span>
                <span class="status-badge" hidden></span>
            </div>
            <div class="slip-title">
                <h2>${escapeHtml(formatTeamName(sb.home_team))} – ${escapeHtml(formatTeamName(sb.away_team))}</h2>
                <p>${escapeHtml(currentMode === 'live' ? 'In play' : (kickoff ? formatKickoffLong(kickoff) : 'Kickoff unknown'))}</p>
            </div>
        </div>

        <div class="slip-hero${plan.profit > 0 ? '' : ' is-loss'}">
            <div class="slip-profit" data-tier="${profitTier(plan.profitPercent)}" title="Profit of the stakes below, after rounding">
                <span class="mono">${plan.profitPercent.toFixed(2)}%</span>
                <small>${exactProfit.toFixed(2)}% at scan, exact stakes</small>
            </div>
            <div class="slip-stake">
                <label class="inline-field"><span>Total stake</span>
                    <input class="input mono" type="number" min="1" step="10" value="${state.investment}"
                           oninput="setSlipInvestment('${escapeHtml(sb.id)}', this.value)"${locked}> KM</label>
                <div class="slip-presets" aria-label="Quick stake">${presets}</div>
            </div>
        </div>

        <div class="slip-totals">
            <span>Staked <b class="mono">${money(plan.total)}</b></span>
            <span>Worst return <b class="mono">${money(plan.worst)}</b></span>
            <span class="${plan.profit > 0 ? 'good' : 'bad'}">Profit <b class="mono">${plan.profit >= 0 ? '+' : ''}${money(plan.profit)} KM</b></span>
        </div>

        ${renderVerifyBanner(sb, check)}
        ${warnings.join('')}

        <div class="slip-progress">
            <span>${placedCount ? `${placedCount} of ${plan.legs.length} placed` : `Place ${plan.legs.length} bets, top to bottom`}</span>
            <span class="slip-progress-bar"><i style="width:${(placedCount / plan.legs.length) * 100}%"></i></span>
        </div>
        <ol class="legs">${legsHtml}</ol>

        <details class="slip-howto">
            <summary>How to place this</summary>
            <ol>
                <li>Place the legs top to bottom. The first has the longest odds — the price most likely to move or be limited.</li>
                <li>On the bookmaker's site, check the odds match before you confirm. If they dropped, type the odds you got into <em>Odds taken</em> and press <em>Mark placed</em>: the stakes below are re-planned to cover it.</li>
                <li>If a later leg is gone or the profit turns red, stop. Either hedge the placed leg at the best price available or accept the single bet — do not chase.</li>
            </ol>
        </details>

        ${evidence ? `<div class="slip-evidence"><h4>Why these are the same match</h4><ul>${evidence}</ul></div>` : ''}

        <div class="slip-actions">
            <button type="button" class="btn btn-secondary" onclick="verifySurebet('${escapeHtml(sb.id)}')">Re-check odds</button>
            <button type="button" class="btn btn-secondary" onclick="copySurebetDetails('${escapeHtml(sb.id)}')">Copy slip</button>
        </div>
    `;
    applyStatusBadge(pane.querySelector('.status-badge'), sb.status || sb.match_status);
}

// Only show a status the backend explicitly sent; never infer safety from the
// fact that a surebet is present in the results payload.
function applyStatusBadge(statusEl, reportedStatus) {
    if (!statusEl) return;
    statusEl.hidden = true;
    statusEl.className = 'status-badge';
    statusEl.textContent = '';
    const statusInfo = Object.prototype.hasOwnProperty.call(SUREBET_STATUS_LABELS, reportedStatus)
        ? SUREBET_STATUS_LABELS[reportedStatus]
        : null;
    if (statusInfo) {
        statusEl.hidden = false;
        statusEl.classList.add(`status-${reportedStatus}`);
        statusEl.textContent = statusInfo.label;
        statusEl.setAttribute('aria-label', statusInfo.ariaLabel);
    }
}

function renderVerifyBanner(sb, check) {
    if (!check) return '<div class="verify-banner verify-idle">Odds not re-checked yet.</div>';
    if (check.state === 'checking') {
        return '<div class="verify-banner verify-checking"><span class="spinner"></span> Re-checking the odds at each bookmaker…</div>';
    }
    const ago = `<span data-ago="${check.at.getTime()}">${formatAgo(check.at)}</span>`;
    if (check.state === 'ok') {
        const fresh = verifyIsFresh(check);
        const floor = check.data.meets_min_profit === false ? ' — below your usual minimum' : '';
        return `<div class="verify-banner ${fresh ? 'verify-ok' : 'verify-stale'}">
            ${fresh ? 'Still a surebet' : 'Was a surebet'}: <b class="mono">${Number(check.data.current.profit_percent).toFixed(2)}%</b>${floor}, re-checked ${ago}.
            ${fresh ? '' : ' Re-check before placing.'}</div>`;
    }
    if (check.state === 'gone') {
        const now = check.data?.current ? ` (now ${Number(check.data.current.profit_percent).toFixed(2)}%)` : '';
        return `<div class="verify-banner verify-bad">Gone${now}. ${escapeHtml(check.data?.message || 'The prices moved.')} Checked ${ago}. Do not place.</div>`;
    }
    return `<div class="verify-banner verify-unknown">Could not confirm: ${escapeHtml(check.message || 'unknown')}. Checked ${ago}. Check each price on the site before placing.</div>`;
}

function verifyShortLabel(check) {
    if (check.state === 'checking') return 'checking';
    if (check.state === 'ok') return verifyIsFresh(check) ? 'live ✓' : 'stale';
    if (check.state === 'gone') return 'gone';
    return '?';
}

function verifyIsFresh(check) {
    if (!check || check.state !== 'ok') return false;
    return (Date.now() - check.at.getTime()) / 1000 <= VERIFY_FRESH_SECONDS[currentMode];
}

function setSlipInvestment(id, value) {
    const sb = allSurebets.find(s => s.id === id);
    const amount = parseFloat(value);
    if (!sb || !amount || amount <= 0) return;
    const state = slipFor(sb);
    state.investment = amount;
    state.touched = true;
    // Re-render without losing focus on the input being typed in.
    const active = document.activeElement;
    const caret = active && active.selectionStart;
    renderSlip();
    const input = document.querySelector('.slip-stake input');
    if (input && active && active.closest && active.closest('.slip-stake')) {
        input.focus();
        try { input.setSelectionRange(caret, caret); } catch (e) { /* number inputs */ }
    }
}

function markPlaced(id, label, button) {
    const sb = allSurebets.find(s => s.id === id);
    if (!sb) return;
    const state = slipFor(sb);
    const plan = planStakes(placementOrder(currentStakes(sb, verifyState[sb.id])), state.investment, state.placed);
    const leg = plan.legs.find(l => l.outcome_label === label);
    const input = button.closest('.leg').querySelector('[data-placed-odds]');
    const odds = parseFloat(input?.value);
    if (!leg || !odds || odds < 1.01) {
        showToast('Enter the odds you actually got');
        return;
    }
    state.placed[label] = { odds, stake: leg.plannedStake };
    renderSlip();
}

function unmarkPlaced(id, label) {
    const sb = allSurebets.find(s => s.id === id);
    if (!sb) return;
    delete slipFor(sb).placed[label];
    renderSlip();
}

// ─── Verify odds ──────────────────────────────────────────────────────────────
async function verifySurebet(id) {
    const sb = allSurebets.find(s => s.id === id);
    if (!sb) return;
    verifyState[id] = { state: 'checking', at: new Date() };
    refreshRowBadge(id);
    if (id === selectedSurebetId) renderSlip();
    let result;
    try {
        const res = await fetch('/api/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...candidateActionHeaders() },
            body: JSON.stringify({ surebet_id: id, mode: currentMode }),
        });
        const data = await res.json();
        if (!res.ok) {
            result = { state: 'unknown', at: new Date(), message: data.detail || `request failed (${res.status})` };
        } else if (data.still_profitable === true) {
            result = { state: 'ok', at: new Date(), data };
        } else if (data.still_profitable === false) {
            result = { state: 'gone', at: new Date(), data };
        } else {
            result = { state: 'unknown', at: new Date(), message: data.message || 'the bookmakers did not all answer', data };
        }
    } catch (e) {
        result = { state: 'unknown', at: new Date(), message: 'network error' };
    }
    verifyState[id] = result;
    refreshRowBadge(id);
    if (id === selectedSurebetId) renderSlip();
}

function refreshRowBadge(id) {
    const row = document.querySelector(`.sb-row[data-id="${CSS.escape(id)}"]`);
    const sb = allSurebets.find(s => s.id === id);
    if (!row || !sb) return;
    const fresh = buildSurebetRow(sb);
    fresh.classList.toggle('selected', row.classList.contains('selected'));
    fresh.setAttribute('aria-selected', row.getAttribute('aria-selected') || 'false');
    row.replaceWith(fresh);
}

function tickAges() {
    document.querySelectorAll('[data-ago]').forEach(el => {
        el.textContent = formatAgo(new Date(Number(el.dataset.ago)));
    });
    // A check that just went stale changes the banner's colour and advice.
    const check = verifyState[selectedSurebetId];
    if (check && check.state === 'ok') {
        const banner = document.querySelector('.verify-banner');
        if (banner && banner.classList.contains('verify-ok') !== verifyIsFresh(check)) renderSlip();
    }
}

// ─── Copy ─────────────────────────────────────────────────────────────────────
async function copyText(text, message) {
    try {
        await navigator.clipboard.writeText(text);
    } catch (e) {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
    }
    if (message) showToast(message);
}

function copySurebetDetails(id) {
    const sb = allSurebets.find(s => s.id === id);
    if (!sb) return;
    const state = slipFor(sb);
    const plan = planStakes(placementOrder(currentStakes(sb, verifyState[sb.id])), state.investment, state.placed);
    const kickoff = parseKickoff(sb.kickoff);
    const lines = [
        `${formatTeamName(sb.home_team)} – ${formatTeamName(sb.away_team)}`,
        `${formatLeague(sb.league)} · ${kickoff ? formatKickoffLong(kickoff) : 'kickoff unknown'}`,
        `${MARKET_LABELS[sb.market_type] || sb.market_type} · profit ${plan.profitPercent.toFixed(2)}% (${money(plan.profit)} KM on ${money(plan.total)} KM)`,
        '',
        ...plan.legs.map((leg, index) => {
            const link = (sb.bet_urls && sb.bet_urls[leg.bookmaker]) || (sb.match_urls && sb.match_urls[leg.bookmaker]) || '';
            const listing = sb.listings?.[leg.bookmaker];
            const listed = listing ? ` [${listing.home} – ${listing.away}]` : '';
            return `${index + 1}. ${bookName(leg.bookmaker)}${listed}: ${leg.outcome_label} @ ${leg.takenOdds.toFixed(2)} → ${leg.plannedStake.toFixed(stakeRounding === 'exact' ? 2 : 0)} KM${link ? ' ' + link : ''}`;
        }),
    ];
    copyText(lines.join('\n'), 'Slip copied');
}

// ─── No-surebet diagnostic ─────────────────────────────────────────────────────
//
// The reason a surebet is absent is the one thing an operator cannot work out
// from the screen. It is read off the two payloads the dashboard already polls.
// `frontend/js/no-surebet-reasons.json` holds the copy and the guards; this
// module holds the arithmetic, and `tests/test_frontend_empty_state.py` holds
// the truth table that proves the two cannot disagree.

// The only place a case's behaviour is defined. An action the table names that
// this map does not implement renders nothing.
const DIAGNOSTIC_ACTIONS = {
    resetFilters: { label: 'Reset Filters', handler: () => resetFilters() },
    showReview: { label: 'Open review queue', handler: () => switchTab('review') },
};

// Which elements hold the copy in each panel.
const DIAGNOSTIC_PANELS = {
    'empty-state': { title: '.empty-state-title', body: '.empty-state-desc', actions: '#empty-state-actions' },
    'no-results': { title: '#no-results-title', body: '#no-results-desc', actions: '#no-results-actions' },
};

function formatCount(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toLocaleString() : '0';
}

async function loadNoSurebetReasons() {
    try {
        const res = await fetch('/js/no-surebet-reasons.json');
        if (!res.ok) throw new Error(`copy table responded ${res.status}`);
        noSurebetReasons = await res.json();
    } catch (error) {
        // Falling back to a hard-coded sentence would name a cause that has not
        // been checked, so the dashboard says it does not know instead.
        console.warn('No-surebet copy table unavailable:', error);
        noSurebetReasons = null;
    }
}

// The five facts every case is decided from. `match_groups` is read from the
// results payload rather than `verified_groups` from the health payload because
// the health counter is prematch-only, and this screen may be showing live.
function diagnosticFlags(health, results, counts) {
    const live = counts.mode === 'live';
    const feed = live ? health?.live : health?.prematch;
    const matches = live ? health?.live_matches_cached : health?.matches_cached;
    const links = live ? health?.live_unverified_links : health?.unverified_links;
    return {
        scanned: Number(matches) > 0 && feed?.last_scan_age_sec != null,
        unverified_links: Number(links) > 0,
        verified_groups: Number(results?.match_groups) > 0,
        have_surebets: Number(counts.surebets) > 0,
        show_surebets: Number(counts.shownSurebets) > 0,
    };
}

function selectNoSurebetReason(flags) {
    const table = noSurebetReasons;
    if (!table || !Array.isArray(table.cases)) return null;
    return table.cases.find(reason => {
        const guard = reason.guard || {};
        const all = Array.isArray(guard.all) ? guard.all : [];
        const none = Array.isArray(guard.none) ? guard.none : [];
        return all.every(flag => flags[flag] === true) && none.every(flag => flags[flag] !== true);
    }) || null;
}

function diagnosticValues(health, results, counts) {
    const live = counts.mode === 'live';
    return {
        matches: formatCount(live ? health?.live_matches_cached : health?.matches_cached),
        unverified_links: formatCount(live ? health?.live_unverified_links : health?.unverified_links),
        verified_groups: formatCount(results?.match_groups),
        surebets: formatCount(counts.surebets),
        profit_floor_percent: formatCount(noSurebetReasons?.profit_floor_percent),
    };
}

// Every count substituted into the copy goes through escapeHtml. An unknown
// placeholder is left alone so a typo in the table shows up.
function fillDiagnosticBody(template, values) {
    return String(template ?? '').replace(/\{([a-z_]+)\}/g, (whole, name) => (
        Object.prototype.hasOwnProperty.call(values, name) ? escapeHtml(values[name]) : whole
    ));
}

function renderCaseCopy(reason, values, live) {
    if (!reason) return { title: '', body: '' };
    const title = live && reason.title_live ? reason.title_live : reason.title;
    const body = live && reason.body_live ? reason.body_live : reason.body;
    return {
        title: fillDiagnosticBody(title, values),
        body: fillDiagnosticBody(body, values),
    };
}

function renderDiagnosticActions(reason) {
    const names = Array.isArray(reason?.actions) ? reason.actions : [];
    return names
        .filter(name => Object.prototype.hasOwnProperty.call(DIAGNOSTIC_ACTIONS, name))
        .map(name => {
            const action = DIAGNOSTIC_ACTIONS[name];
            return `<button type="button" class="btn btn-secondary" data-diagnostic-action="${escapeHtml(name)}">${escapeHtml(action.label)}</button>`;
        })
        .join('');
}

function writeDiagnosticPanel(panel, reason, copy) {
    const slots = DIAGNOSTIC_PANELS[reason.panel] || DIAGNOSTIC_PANELS['empty-state'];
    const title = panel.querySelector(slots.title);
    const body = panel.querySelector(slots.body);
    const actions = document.querySelector(slots.actions);
    if (title) title.innerHTML = copy.title;
    if (body) body.innerHTML = copy.body;
    if (!actions) return;
    actions.innerHTML = renderDiagnosticActions(reason);
    actions.hidden = !actions.innerHTML;
    actions.querySelectorAll('[data-diagnostic-action]').forEach(button => {
        const action = DIAGNOSTIC_ACTIONS[button.dataset.diagnosticAction];
        if (action) button.addEventListener('click', action.handler);
    });
}

// Shown when the dashboard cannot name a cause. Neither case may fall back to a
// hard-coded sentence: guessing is the defect this module exists to remove.
const DIAGNOSTIC_UNAVAILABLE = {
    noCopyTable: 'The dashboard could not read its diagnostic copy, so it cannot tell you why '
        + 'this scan returned nothing. /api/health and /api/results hold the counts it would '
        + 'have used.',
    countsUnread: 'The dashboard has not read the counts for this scan yet, so it cannot tell '
        + 'you why there is no surebet. /api/health and /api/results hold them.',
};

function renderNoSurebetState() {
    const emptyState = document.getElementById('empty-state');
    const noResults = document.getElementById('no-results');
    if (!emptyState || !noResults) return;
    // Without the counts, "no surebets" is not evidence of anything, so nothing
    // is claimed until /api/health has answered.
    if (!noSurebetReasons || !healthSnapshot) {
        renderDiagnosticUnavailable();
        return;
    }
    const counts = {
        mode: currentMode,
        surebets: allSurebets.length,
        shownSurebets: filteredSurebets.length,
    };
    const reason = selectNoSurebetReason(
        diagnosticFlags(healthSnapshot, resultsSnapshot, counts)
    );
    if (!reason) {
        emptyState.style.display = 'none';
        noResults.style.display = 'none';
        return;
    }
    const intoNoResults = reason.panel === 'no-results';
    const panel = intoNoResults ? noResults : emptyState;
    const other = intoNoResults ? emptyState : noResults;
    panel.style.display = '';
    other.style.display = 'none';
    panel.dataset.noSurebetReason = reason.id;
    other.removeAttribute('data-no-surebet-reason');
    // The bookmaker row is an invitation to scan, so it only shows for the case
    // that asks for one. `style.display`, not `hidden`: the row is
    // `display: flex` in the stylesheet, which outranks `[hidden]`.
    const bookies = emptyState.querySelector('.empty-state-bookies');
    if (bookies) bookies.style.display = reason.id === 'never_scanned' ? '' : 'none';
    const cta = emptyState.querySelector('.empty-cta');
    if (cta) cta.style.display = reason.id === 'never_scanned' ? '' : 'none';
    writeDiagnosticPanel(panel, reason, renderCaseCopy(
        reason,
        diagnosticValues(healthSnapshot, resultsSnapshot, counts),
        currentMode === 'live',
    ));
}

function renderDiagnosticUnavailable() {
    const emptyState = document.getElementById('empty-state');
    const noResults = document.getElementById('no-results');
    if (noResults) {
        noResults.style.display = 'none';
        noResults.removeAttribute('data-no-surebet-reason');
    }
    if (!emptyState) return;
    emptyState.style.display = '';
    emptyState.dataset.noSurebetReason = 'diagnostics_unavailable';
    const title = emptyState.querySelector('.empty-state-title');
    const body = emptyState.querySelector('.empty-state-desc');
    if (title) title.textContent = 'No Surebets — Reason Unknown';
    if (body) body.textContent = noSurebetReasons
        ? DIAGNOSTIC_UNAVAILABLE.countsUnread
        : DIAGNOSTIC_UNAVAILABLE.noCopyTable;
    const bookies = emptyState.querySelector('.empty-state-bookies');
    if (bookies) bookies.style.display = 'none';
    const cta = emptyState.querySelector('.empty-cta');
    if (cta) cta.style.display = 'none';
    const actions = document.getElementById('empty-state-actions');
    if (actions) {
        actions.innerHTML = '';
        actions.hidden = true;
    }
}

// Re-read the retained payloads on the 30s cadence, so a reason that changes
// is corrected without waiting for a filter change.
function refreshNoSurebetState() {
    const emptyState = document.getElementById('empty-state');
    const noResults = document.getElementById('no-results');
    const panelIsUp = [emptyState, noResults]
        .some(panel => panel && panel.style.display !== 'none');
    if (!panelIsUp) return;
    renderNoSurebetState();
}

// ─── Candidate review ──────────────────────────────────────────────────────────
const REASON_UNKNOWN_LABEL = 'Unrecognised gate reason';

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;',
    })[character]);
}

function candidateConfidence(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return 0;
    const normalized = numeric > 1 ? numeric / 100 : numeric;
    return Math.min(1, Math.max(0, normalized));
}

// The card is a name judgement, so give the reviewer the evidence: one search
// for both spellings, the competition and the date. This is a link, not a
// server-side verdict — a human still decides, and the gate still proves.
function fixtureSearchUrl(candidate) {
    const teams = [candidate.home_team, candidate.away_team].filter(Boolean).join(' vs ');
    const date = candidate.kickoff ? String(candidate.kickoff).slice(0, 10) : '';
    const query = [teams, candidate.league || '', date].filter(Boolean).join(' ');
    return `https://www.google.com/search?q=${encodeURIComponent(query)}`;
}

function renderCandidatesMessage(message) {
    const list = document.getElementById('candidates-list');
    if (!list) return;
    list.innerHTML = `
        <div class="empty-state">
            <h2 class="empty-state-title">${escapeHtml(message)}</h2>
            <p class="empty-state-desc">The review queue could not be refreshed. Try again in a moment.</p>
        </div>
    `;
}

// The queue is served one bounded page at a time: a full scan can queue five
// figures, and this tab re-renders every poll.
const CANDIDATE_PAGE_SIZE = 100;

function candidateActionHeaders() {
    return candidateApiKey ? { 'X-API-Key': candidateApiKey } : {};
}

async function candidateListFetch(url) {
    const send = () => fetch(url, { headers: candidateActionHeaders() });
    let response = await send();
    if (response.status === 401 && !candidateApiKey) {
        const entered = window.prompt('This SureBet deployment requires an API key to read the review queue.');
        if (entered && entered.trim()) {
            candidateApiKey = entered.trim();
            response = await send();
        }
    }
    return response;
}

async function loadCandidates() {
    try {
        // Only the pairs an approval can clear. A full scan queues thousands,
        // and most are refused for a league gap, a kickoff no decision moves or
        // a name pair below the reviewed-alias floor: a card with an Approve
        // button there promises a fix that does not exist. The server still
        // reports the full `total` and the closable `actionable_total` so the
        // tab can say exactly what it is not showing.
        const response = await candidateListFetch(
            `/api/candidates?actionable_only=true&limit=${CANDIDATE_PAGE_SIZE}&offset=0&mode=${currentMode}`
        );
        if (response.ok === false) throw new Error(`Candidate request failed (${response.status})`);
        const data = await response.json();
        renderCandidates(
            Array.isArray(data.candidates) ? data.candidates : [],
            Number(data.total) || 0,
            Number(data.actionable_total) || 0,
        );
    } catch (error) {
        console.error('Candidates load failed:', error);
        renderCandidatesMessage('Could not load candidates.');
    }
}

function renderCandidates(candidates, total, actionableTotal) {
    const list = document.getElementById('candidates-list');
    const count = document.getElementById('review-count');
    const queue = Array.isArray(candidates) ? candidates : [];
    if (!list) return;
    if (count) count.textContent = actionableTotal;
    currentCandidates = queue;
    // Keep only selections that are still on the page.

    if (!queue.length) {
        // Two different nothings: an empty filtered page can still sit on top
        // of a large queue no human decision can move.
        const nothingQueued = total === 0;
        list.innerHTML = `
            <div class="empty-state">
                <h2 class="empty-state-title">${nothingQueued ? 'No unresolved pairings.' : 'No actionable pairings.'}</h2>
                <p class="empty-state-desc">${nothingQueued
                    ? 'The ledger has not left any pairing without a terminal decision.'
                    : `${total} pairing${total === 1 ? '' : 's'} are informational; the ledger learns them automatically.`}</p>
            </div>
        `;
        return;
    }

    // AI confidence helps a reviewer prioritise; it never grants trust. A
    // negative AI verdict sorts last whatever its confidence. Then the closest
    // spellings first, since those are the quickest to decide.
    const orderedCandidates = [...queue].sort((left, right) => {
        const leftNegative = left.ai_same_event === false;
        const rightNegative = right.ai_same_event === false;
        if (leftNegative !== rightNegative) return leftNegative ? 1 : -1;
        const byAi = candidateConfidence(right.ai_confidence) - candidateConfidence(left.ai_confidence);
        if (byAi) return byAi;
        return (Number(right.name_score) || 0) - (Number(left.name_score) || 0);
    });

    const pageNote = total > queue.length
        ? `<p class="candidates-page-note">Showing ${queue.length} of ${actionableTotal} pairings an approval can clear, of ${total} queued in total. The rest cannot be closed by a human decision.</p>`
        : '';

    list.innerHTML = pageNote + orderedCandidates.map((candidate) => {
        const id = escapeHtml(candidate.id || '');
        const homeTeam = escapeHtml(formatTeamName(candidate.home_team || 'Unknown'));
        const awayTeam = escapeHtml(formatTeamName(candidate.away_team || 'Unknown'));
        const league = escapeHtml(formatLeague(candidate.league || 'Unknown league'));
        const kickoffDate = candidate.kickoff ? parseKickoff(candidate.kickoff) : null;
        const kickoff = kickoffDate ? escapeHtml(formatKickoff(kickoffDate)) : 'Kickoff unknown';
        const bookmakers = (Array.isArray(candidate.bookmakers) ? candidate.bookmakers : [])
            .map(bookmaker => escapeHtml(bookName(bookmaker)))
            .join(' / ') || 'No bookmakers recorded';
        const confidence = Math.round(candidateConfidence(candidate.ai_confidence) * 100);
        const nameScore = Math.round(Number(candidate.name_score) || 0);
        const aiNegative = candidate.ai_same_event === false;
        const aiReason = candidate.ai_reason ? escapeHtml(candidate.ai_reason) : '';
        const aiVerdict = aiNegative
            ? `<p class="candidate-ai"><strong>AI verdict:</strong> <span class="candidate-ai-negative">not the same event</span> ${aiReason}</p>`
            : (aiReason ? `<p class="candidate-ai"><strong>AI suggestion (${confidence}%):</strong> ${aiReason} <span class="candidate-ai-note">Suggestion only — a human must decide.</span></p>` : '');
        const positions = Array.isArray(candidate.team_positions) ? candidate.team_positions : [];
        const positionItems = positions.length
            ? positions.map(position => `
                <li class="candidate-position${position.team_a !== position.team_b ? ' differs' : ''}">
                    <span class="candidate-position-slot">${escapeHtml(position.position)}</span>
                    <span>${escapeHtml(position.team_a)}</span>
                    <span aria-hidden="true">≈</span>
                    <span>${escapeHtml(position.team_b)}</span>
                </li>
            `).join('')
            : '<li class="candidate-position candidate-position-none">No cross-bookmaker names recorded — run a scan to regenerate this candidate</li>';
        const searchUrl = fixtureSearchUrl(candidate);
        const readOnlyNote = candidate.link_blocked
            ? 'The ledger learns this pairing automatically; the link half is a separate machine check.'
            : 'The ledger learns this pairing automatically; this card is informational.';
        const reasons = Array.isArray(candidate.rule_rejections) ? candidate.rule_rejections : [];
        const reasonItems = reasons.length
            ? reasons.map(reason => {
                const rawCode = String(reason);
                const label = REASON_LABELS[rawCode] || rawCode || REASON_UNKNOWN_LABEL;
                return `<li class="candidate-reason" title="${escapeHtml(rawCode)}">${escapeHtml(label)}</li>`;
            }).join('')
            : '<li class="candidate-reason candidate-reason-none">No reason recorded</li>';
        return `
            <article class="candidate-card" data-id="${id}" data-confidence="${confidence}"${aiNegative ? ' data-ai-verdict="negative"' : ''}>
                <div class="candidate-body">
                    <div class="candidate-card-header">
                        <div class="candidate-teams"><span>${homeTeam}</span> <span class="candidate-vs">vs</span> <span>${awayTeam}</span></div>
                        <span class="name-score" data-score="${nameScore >= 85 ? 'high' : nameScore >= 65 ? 'mid' : 'low'}" title="How alike the least-alike name pair is">${nameScore}% alike</span>
                    </div>
                    <div class="candidate-meta">${league} · ${kickoff} · ${bookmakers}</div>
                    <ul class="candidate-positions" aria-label="How the two bookmakers spell each team">${positionItems}</ul>
                    <ul class="candidate-reasons" aria-label="Why the certainty gate refused">${reasonItems}</ul>
                    ${aiVerdict}
                    <p class="candidate-approval-note">${escapeHtml(readOnlyNote)}</p>
                </div>
                <div class="candidate-actions">
                    <a class="btn btn-secondary btn-small" href="${escapeHtml(searchUrl)}" target="_blank" rel="noopener noreferrer"
                       title="Search the web for this fixture">Check on the web ↗</a>
                </div>
            </article>
        `;
    }).join('');
}

// ─── History ──────────────────────────────────────────────────────────────────
async function loadHistory() {
    const body = document.getElementById('history-body');
    if (!body) return;
    try {
        const res = await fetch('/api/history', { headers: candidateActionHeaders() });
        const data = await res.json();
        const entries = data.entries || [];
        if (entries.length === 0) {
            body.innerHTML = '<tr><td colspan="6" class="history-empty">No scans yet</td></tr>';
            return;
        }
        body.innerHTML = entries.map(e => {
            const time = e.scan_time ? escapeHtml(parseKickoff(e.scan_time).toLocaleString()) : '—';
            const errs = (e.errors || []).length;
            const mode = e.mode === 'live' ? '<span class="tag tag-live">Live</span>' : '<span class="tag">Upcoming</span>';
            return `<tr>
                <td>${mode}</td>
                <td>${time}</td>
                <td class="mono">${formatCount(e.total_matches)}</td>
                <td class="mono">${formatCount(e.match_groups)}</td>
                <td class="mono${e.surebets_found > 0 ? ' good' : ''}">${formatCount(e.surebets_found)}</td>
                <td class="mono${errs > 0 ? ' bad' : ''}" title="${escapeHtml((e.errors || []).join(' | '))}">${errs}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" class="history-empty">Failed to load history</td></tr>';
    }
}

// ─── UI helpers ───────────────────────────────────────────────────────────────
function showScanProgress() {
    document.getElementById('scan-progress').style.display = '';
    document.getElementById('scan-bar').style.width = '5%';
}

function hideScanProgress() {
    document.getElementById('scan-progress').style.display = 'none';
}

function setStatus(state, text) {
    const pill = document.getElementById('status-pill');
    pill.className = 'status-pill ' + state;
    document.getElementById('status-text').textContent = text;
}

function showError(msg) {
    document.getElementById('error-banner-text').textContent = msg;
    document.getElementById('error-banner').style.display = '';
}

function hideError() {
    document.getElementById('error-banner').style.display = 'none';
}

async function shutdownServer() {
    if (!window.confirm('Stop the server? Scans stop and this page goes offline.')) return;
    const btn = document.getElementById('shutdown-btn');
    btn.disabled = true;
    try {
        const res = await fetch('/api/shutdown', { method: 'POST', headers: candidateActionHeaders() });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || `HTTP ${res.status}`);
        }
    } catch (e) {
        btn.disabled = false;
        showError(`Could not stop the server: ${e.message}`);
        return;
    }
    // Stop polling so the dead server does not fill the console with errors.
    stopPolling();
    setAutoRescan(0);
    clearInterval(diagnosticsTimer);
    toggleSettings(false);
    document.getElementById('stopped-screen').hidden = false;
}

let toastTimer = null;
function showToast(message) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 2500);
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function bookName(id) {
    return bookmakersConfig[id]?.name || capitalize(id);
}

function bookColor(id) {
    return bookmakersConfig[id]?.color || BOOKMAKER_COLORS[id] || '#888';
}

function bookShort(id) {
    const name = bookName(id);
    return name.replace(/[^A-Za-z0-9]/g, '').slice(0, 3).toUpperCase();
}

// ─── Formatting ───────────────────────────────────────────────────────────────
function parseKickoff(str) {
    if (!str) return null;
    // Scrapers store naive UTC; JS would read a bare ISO string as local time.
    const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(str);
    const dt = new Date(hasTz ? str : str + 'Z');
    return isNaN(dt) ? null : dt;
}

function formatAgo(dt) {
    if (!dt || isNaN(dt)) return '—';
    const sec = Math.max(0, Math.round((Date.now() - dt.getTime()) / 1000));
    if (sec < 60) return `${sec}s ago`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    return dt.toLocaleDateString();
}

function formatKickoff(dt) {
    if (!dt || isNaN(dt)) return '';
    const time = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const today = new Date();
    const tomorrow = new Date(today.getTime() + 86400000);
    if (dt.toDateString() === today.toDateString()) return `Today ${time}`;
    if (dt.toDateString() === tomorrow.toDateString()) return `Tomorrow ${time}`;
    return `${dt.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} ${time}`;
}

function formatKickoffLong(dt) {
    const hours = (dt.getTime() - Date.now()) / 3600000;
    const rel = hours > 0 && hours < 48 ? ` (in ${hours < 1 ? Math.round(hours * 60) + ' min' : Math.round(hours) + ' h'})` : '';
    return formatKickoff(dt) + rel;
}

function formatTeamName(name) {
    if (!name) return 'Unknown';
    return name
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase())
        .trim();
}

function formatLeague(league) {
    if (!league) return '';
    return league
        .replace(/_/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase())
        .trim();
}

function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

async function refreshDiagnostics() {
    // The review queue rides the same cadence as the health poll.
    await Promise.all([loadHealth(), loadCandidates()]);
}

async function loadHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        // The counts that say WHY there is no surebet live in this response, so
        // the payload is kept for the diagnostic.
        healthSnapshot = data;
        const bar = document.getElementById('health-bar');
        if (!bar) return;
        const fmtAge = (sec) => sec == null ? '—' : sec < 60 ? `${Math.round(sec)}s ago` : `${Math.round(sec/60)}m ago`;
        const fmtPer = (obj) => obj && Object.keys(obj).length ? Object.entries(obj).map(([k,v]) => `${k}:${v}`).join(' ') : '—';
        bar.style.display = '';
        bar.innerHTML = `Health — Prematch ${fmtAge(data.prematch?.last_scan_age_sec)} [${fmtPer(data.prematch?.per_bookie)}] | Live ${fmtAge(data.live?.last_scan_age_sec)} [${fmtPer(data.live?.per_bookie)}] | TTL ${data.odds_ttl_sec}s`;
        if (data.prematch?.errors?.length || data.live?.errors?.length) {
            bar.title = [...(data.prematch?.errors||[]), ...(data.live?.errors||[])].join(' | ');
        }
        refreshNoSurebetState();
    } catch (e) { /* ignore */ }
}

// ─── Alert sound ──────────────────────────────────────────────────────────────
function toggleSound() {
    soundMuted = !soundMuted;
    try { localStorage.setItem('soundMuted', soundMuted ? '1' : '0'); } catch (e) { /* ignore */ }
    const box = document.getElementById('sound-toggle');
    if (box) box.checked = !soundMuted;
}

function playAlertSound() {
    if (soundMuted) return;
    try {
        if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
        if (audioContext.state === 'suspended') audioContext.resume();
        const playNote = (freq, startTime, duration) => {
            const osc = audioContext.createOscillator();
            const gain = audioContext.createGain();
            osc.connect(gain);
            gain.connect(audioContext.destination);
            osc.frequency.value = freq;
            osc.type = 'sine';
            gain.gain.setValueAtTime(0, startTime);
            gain.gain.linearRampToValueAtTime(0.2, startTime + 0.01);
            gain.gain.linearRampToValueAtTime(0, startTime + duration);
            osc.start(startTime);
            osc.stop(startTime + duration + 0.01);
        };
        playNote(523, audioContext.currentTime, 0.2);
        playNote(659, audioContext.currentTime + 0.2, 0.2);
        playNote(784, audioContext.currentTime + 0.4, 0.3);
    } catch (e) {
        // Audio not available — silent.
    }
}
