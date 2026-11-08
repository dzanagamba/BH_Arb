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
let activeTab = 'surebets';         // 'surebets' | 'other' | 'review' | 'paper' | 'history' | 'evidence'
let otherSportFilter = 'all';       // sport id or 'all' for the Other sports tab
let configuredSports = [];          // sports the backend says it scans
let candidateApiKey = (() => { try { return sessionStorage.getItem('apiKey') || ''; } catch (e) { return ''; } })();
let candidateApiKeyDeclined = false; // a cancelled prompt stops background re-asks
let allSurebets = [];               // full list from the server
let filteredSurebets = [];          // after client-side filtering
let selectedSurebetId = null;       // the surebet open in the bet slip
let resultsRequestSeq = 0;          // guards /api/results against a late payload
let allowAutoSelect = true;         // false during a pure repaint (language change)
let statusPollFailures = 0;         // consecutive failed /api/status reads
// A scan can block the event loop for over a minute. Warn early, but keep
// polling long enough to recover and load the finished scan.
const STATUS_POLL_MAX_FAILURES = 90;
let statusMessage = { text: '', render: null }; // live status line, language-aware
let pollingInterval = null;
let activeBookmakers = new Set(['mozzartbet', 'mdshop', 'admiralbet', 'betole', 'mbet', 'sportplus', 'evlbet', 'premier_kladionica', 'wwin', 'maxbet']);
let bookmakersConfig = {};
let globalInvestment = 100;
// P3-7: advisory (default), record_only or paper. A non-advisory scan never
// publishes a live surebet, so the results banner must say so.
let scanRunMode = 'advisory';
let stakeRounding = '1';            // 'exact' | '1' | '5' — whole KM by default
let soundMuted = true;
let audioContext = null;
let autoRescanTimer = null;
let knownSurebetSignatures = new Set();
let healthSnapshot = null;          // last /api/health payload, kept for the no-surebet diagnostic
let language = (() => { try { return localStorage.getItem('language') || 'en'; } catch (e) { return 'en'; } })();

// N2-5: the Bosnian copy lives in frontend/js/i18n.js. Keys are the English
// source strings (gettext-style), so `tr()` can fall back to the key when the
// UI is running in English. Only UI chrome is translated; bookmaker, team and
// league strings always come from the feed as data.
const I18N = (typeof window !== 'undefined' && window.I18N) ? window.I18N : { bs: {} };

function tr(text, vars) {
    const dictionary = I18N.bs || {};
    const template = language === 'bs' && Object.prototype.hasOwnProperty.call(dictionary, text)
        ? dictionary[text]
        : text;
    if (!vars) return template;
    return String(template).replace(/\{(\w+)\}/g, (whole, name) => (
        Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole
    ));
}

function translateElement(element) {
    const key = element.dataset.i18n;
    if (key) {
        if (element.dataset.i18nHtml === 'true') element.innerHTML = tr(key);
        else element.textContent = tr(key);
    }
    for (const attribute of ['aria-label', 'title', 'placeholder']) {
        const keyAttribute = `i18n${attribute.split('-').map(part => part[0].toUpperCase() + part.slice(1)).join('')}`;
        const attributeKey = element.dataset[keyAttribute];
        if (attributeKey) element.setAttribute(attribute, tr(attributeKey));
    }
}

function applyLanguage() {
    document.documentElement.lang = language;
    document
        .querySelectorAll('[data-i18n], [data-i18n-aria-label], [data-i18n-title], [data-i18n-placeholder]')
        .forEach(translateElement);
    applyStatusText();
    const select = document.getElementById('filter-language');
    if (select) select.value = language;
    refreshLocalizedViews();
}

// Every generated string is rendered from `tr()`, so a language change has to
// repaint the views that are already on screen. Network-backed views reload;
// the local ones re-render from the snapshots they already hold.
function refreshLocalizedViews() {
    if (typeof updateModeToggleUI === 'function') updateModeToggleUI();
    if (typeof updateThemeButton === 'function') updateThemeButton();
    // Repaint through the same path a filter change uses, so the list, the KPI
    // counts and filteredSurebets cannot disagree. A repaint must not count as
    // a user selection: nothing may auto-open a slip or launch a re-check.
    if (typeof applyFilters === 'function' && typeof resultsSnapshot !== 'undefined' && resultsSnapshot) {
        const previousAutoSelect = allowAutoSelect;
        allowAutoSelect = false;
        try { applyFilters(); } finally { allowAutoSelect = previousAutoSelect; }
    }
    if (typeof renderOtherSports === 'function') renderOtherSports();
    if (typeof renderSlip === 'function') renderSlip();
    if (typeof renderFreshnessBanner === 'function') renderFreshnessBanner();
    if (typeof renderRunModeBanner === 'function') renderRunModeBanner();
    if (typeof renderFeedIntegrity === 'function') renderFeedIntegrity();
    if (typeof refreshNoSurebetState === 'function') refreshNoSurebetState();
    if (typeof loadCandidates === 'function' && typeof currentMode !== 'undefined') loadCandidates();
    if (typeof activeTab !== 'undefined' && activeTab === 'history' && typeof loadHistory === 'function') loadHistory();
    if (typeof activeTab !== 'undefined' && activeTab === 'evidence' && typeof loadEvidence === 'function') loadEvidence();
    if (typeof activeTab !== 'undefined' && activeTab === 'paper' && typeof loadPaper === 'function') loadPaper();
    if (typeof loadHealth === 'function') loadHealth();
}

function setLanguage(value) {
    language = value === 'bs' ? 'bs' : 'en';
    try { localStorage.setItem('language', language); } catch (e) { /* ignore */ }
    applyLanguage();
}

async function enableNotifications() {
    if (!('Notification' in window)) {
        showToast(tr('This browser does not support notifications.'));
        return;
    }
    const permission = await Notification.requestPermission();
    showToast(permission === 'granted'
        ? tr('Browser alerts enabled.')
        : tr('Browser alerts were not enabled.'));
}

// P3-4: installable shell only. Odds and /api responses are never cached.
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* installability is optional */ });
}
let resultsSnapshot = null;         // last /api/results payload, same reason
let freshnessSnapshot = null;       // P0-4: scan age, TTL and per-book freshness
let freshnessBannerSignature = null; // avoids rebuilding the banner's button every tick
let noSurebetReasons = null;        // the diagnostic copy table, fetched once at start-up
let paperState = {                  // N2-1: paper ledger filters and page offsets
    runMode: '', feedMode: '', status: '', oppOffset: 0, posOffset: 0,
    oppTotal: 0, posTotal: 0,
};
const PAPER_PAGE_SIZE = 25;
let evidenceOffset = 0;             // group-evidence page offset
let evidenceTotal = 0;
const EVIDENCE_PAGE_SIZE = 50;
const verifyState = {};             // surebet id -> {state, at, data}
const slipState = {};               // surebet id -> {investment, placed: {label: {odds, stake}}}
const sweepState = { running: false };

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
    leg_mismatch: 'Different doubleheader leg',
    kickoff_missing: 'Kickoff time missing',
    orientation_unresolved: 'Home/away order unclear',
    no_event_link: 'No event link',
    sport_mismatch: 'Different sport',
});

// N2-3: what a proposal would close. These are labels for review work, not
// trust states: no value here changes a gate verdict.
const REMEDIATION_LABELS = Object.freeze({
    alias: 'Closeable by team alias',
    league: 'Closeable by league mapping',
    'alias+league': 'Needs alias + league mapping',
    none: 'No mapping clears it',
    system_link: 'Machine link check pending',
});

// P0-6: why a zero-surebet scan has no result. The denominator is the point:
// "no crossing" and "all crossings guarded" are different operational facts.
const ZERO_RESULT_LABELS = Object.freeze({
    actionable: 'actionable',
    no_crossing: 'no board crossed',
    crossing_below_floor: 'crossed below floor',
    crossing_guarded: 'all crossings guarded',
    stale_data: 'stale feed',
    expired_data: 'only expired fixtures',
    unverified_data: 'no verified groups',
    no_priced_boards: 'no boards priced',
});

// P0-7: plain-language versions of the deterministic integrity reasons.
const FEED_REASON_LABELS = Object.freeze({
    parse_error: 'parse error',
    empty_feed: 'returned no data',
    skipped_backoff: 'skipped by back-off',
    stale_prices: 'stale prices',
    own_margin_below_one: 'own margin below 1.0',
    outlier_rate: 'outlier rate',
    missing_markets: 'missing markets',
    recovering: 'recovering',
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
    maxbet:     '#0F766E',
};

const MARKET_LABELS = {
    '1x2':            '1X2',
    'over_under_0_5': 'O/U 0.5',
    'over_under_1_5': 'O/U 1.5',
    'over_under_2_5': 'O/U 2.5',
    'over_under_3_5': 'O/U 3.5',
    'over_under_4_5': 'O/U 4.5',
    'over_under_5_5': 'O/U 5.5',
    'btts':           'BTTS',
    'double_chance':  '1X2 + DC',
    'first_half_1x2': '1H 1X2',
    'first_half_ou':  '1H O/U',
    'asian_handicap': 'Asian Hcp',
    'moneyline':      'Moneyline',
    'moneyline_3way': '3-way',
    'handicap':       'Handicap',
    'total':          'Total',
};

const SPORT_LABELS = {
    football: 'Football', basketball: 'Basketball', tennis: 'Tennis', ice_hockey: 'Ice hockey',
};

// Every label table is keyed by English source text; `tr()` resolves it to the
// active language. Keeping the tables English makes them readable and makes the
// catalog coverage test exact.
function reasonLabel(code) {
    return tr(REASON_LABELS[code] || code);
}

function feedReasonLabel(reason) {
    return tr(FEED_REASON_LABELS[reason] || reason);
}

function marketLabel(market) {
    return tr(MARKET_LABELS[market] || market);
}

function sportLabel(sport) {
    return tr(SPORT_LABELS[sport] || sport);
}

// What each outcome label means, in words a bettor types into a ticket.
function outcomeDescription(label, marketType, sport) {
    const half = marketType && marketType.startsWith('first_half') ? ' (1st half)' : '';
    const words = {
        '1': 'Home win', 'X': 'Draw', '2': 'Away win',
        '1X': 'Home or draw', 'X2': 'Draw or away', '12': 'Home or away',
        'GG': 'Both teams score', 'NG': 'Not both teams score',
    };
    if (words[label]) return tr(words[label]) + tr(half);
    const line = /^([12])\s+([+-]?\d+(?:\.\d+)?)$/.exec(label);
    if (line) {
        const side = line[1] === '1' ? 'Home' : 'Away';
        return `${tr(side)} ${line[2]}${tr(half)}`;
    }
    const unit = sport === 'tennis' ? 'games' : sport === 'basketball' ? 'points' : 'goals';
    const over = /^Over (.+)$/.exec(label);
    if (over) return tr('Over {line} {unit}{half}', { line: over[1], unit: tr(unit), half: tr(half) });
    const under = /^Under (.+)$/.exec(label);
    if (under) return tr('Under {line} {unit}{half}', { line: under[1], unit: tr(unit), half: tr(half) });
    return label + tr(half);
}

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    restorePreferences();
    restoreMode();
    applyLanguage();
    updateThemeButton();
    initInteractionHandlers();
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

// ─── Static interaction handlers ──────────────────────────────────────────────
// The shipped HTML and generated rows carry data attributes, never inline `on*`
// handlers. Keeping the behavior here lets the CSP drop `script-src
// 'unsafe-inline'` and keeps every value out of a JavaScript-string context.
function initInteractionHandlers() {
    document.addEventListener('click', handleDataAction);
    document.addEventListener('input', handleDataInput);
    document.addEventListener('change', handleDataChange);
}

function handleDataAction(event) {
    const element = event.target && event.target.closest
        ? event.target.closest('[data-action]')
        : null;
    if (!element) return;
    switch (element.dataset.action) {
        case 'switch-mode': switchMode(element.dataset.mode); break;
        case 'cycle-theme': cycleTheme(); break;
        case 'toggle-settings': toggleSettings(element.dataset.open !== 'false'); break;
        case 'scan-now': scanNow(); break;
        case 'hide-error': hideError(); break;
        case 'switch-tab': switchTab(element.dataset.tab); break;
        case 'shutdown-server': shutdownServer(); break;
        case 'sweep-links': sweepLinks(); break;
        case 'log-bet': logBet(element.dataset.slipId); break;
        case 'enable-notifications': enableNotifications(); break;
        case 'paper-export': event.preventDefault(); exportPaperCsv(); break;
        case 'bets-export': event.preventDefault(); exportBetsCsv(); break;
        case 'open-report': event.preventDefault(); openProtectedReport(element.dataset.reportUrl || '/api/debug/report'); break;
        case 'set-market-filter': setMarketFilter(element.dataset.market); break;
        case 'copy-text': copyText(element.dataset.copy, element.dataset.copyMessage); break;
        case 'close-slip': closeSlip(); break;
        case 'set-slip-investment': setSlipInvestment(element.dataset.slipId, element.dataset.amount); break;
        case 'mark-placed': markPlaced(element.dataset.slipId, element.dataset.outcomeLabel, element); break;
        case 'unmark-placed': unmarkPlaced(element.dataset.slipId, element.dataset.outcomeLabel); break;
        case 'verify-surebet': verifySurebet(element.dataset.slipId); break;
        case 'copy-surebet': copySurebetDetails(element.dataset.slipId); break;
        case 'evidence-prev': setEvidenceOffset(evidenceOffset - EVIDENCE_PAGE_SIZE); break;
        case 'evidence-next': setEvidenceOffset(evidenceOffset + EVIDENCE_PAGE_SIZE); break;
        case 'evidence-open': loadEvidenceDetail(element.dataset.groupId); break;
        case 'evidence-close': showEvidenceList(); break;
        case 'paper-refresh': loadPaper(); break;
        case 'paper-opp-prev': paperPage('opportunities', -1); break;
        case 'paper-opp-next': paperPage('opportunities', 1); break;
        case 'paper-pos-prev': paperPage('positions', -1); break;
        case 'paper-pos-next': paperPage('positions', 1); break;
        case 'paper-settle': settlePaperPosition(element.dataset.positionId); break;
    }
}

function handleDataInput(event) {
    const element = event.target;
    if (!element || !element.matches) return;
    if (element.id === 'filter-search' || element.id === 'filter-profit') {
        applyFilters();
    } else if (element.id === 'other-search' || element.id === 'other-profit') {
        renderOtherSports();
    } else if (element.id === 'evidence-search') {
        loadEvidence(true);
    } else if (element.id === 'filter-language') {
        setLanguage(element.value);
    } else if (element.id === 'filter-investment') {
        recalculateAll(element.value);
    } else if (element.matches('[data-slip-investment-input]')) {
        setSlipInvestment(element.dataset.slipId, element.value);
    }
}

function handleDataChange(event) {
    const element = event.target;
    if (!element || !element.matches) return;
    if (element.id === 'filter-sort') {
        applyFilters();
    } else if (element.id === 'other-sport-filter') {
        setOtherSportFilter(element.value);
    } else if (element.id === 'evidence-status' || element.id === 'evidence-sport') {
        loadEvidence(true);
    } else if (element.id === 'filter-rounding') {
        setStakeRounding(element.value);
    } else if (element.id === 'filter-autorescan') {
        setAutoRescan(parseInt(element.value, 10));
    } else if (element.id === 'filter-run-mode') {
        setScanRunMode(element.value);
    } else if (element.id === 'paper-run-mode') {
        setPaperFilter('runMode', element.value);
    } else if (element.id === 'paper-feed-mode') {
        setPaperFilter('feedMode', element.value);
    } else if (element.id === 'paper-status') {
        setPaperFilter('status', element.value);
    } else if (element.id === 'sound-toggle') {
        toggleSound();
    } else if (element.matches('.exp-check input[type="checkbox"]')) {
        toggleExperimentalMarket(element);
    }
}

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
    let savedRescan = 0;
    try {
        stakeRounding = localStorage.getItem('stakeRounding') || '1';
        soundMuted = localStorage.getItem('soundMuted') !== '0';
        const savedRunMode = localStorage.getItem('scanRunMode');
        if (['advisory', 'record_only', 'paper'].includes(savedRunMode)) scanRunMode = savedRunMode;
        savedRescan = parseInt(localStorage.getItem('autoRescanMinutes') || '0', 10);
    } catch (e) { /* localStorage unavailable */ }
    const roundingEl = document.getElementById('filter-rounding');
    if (roundingEl) roundingEl.value = stakeRounding;
    const sound = document.getElementById('sound-toggle');
    if (sound) sound.checked = !soundMuted;
    const runModeEl = document.getElementById('filter-run-mode');
    if (runModeEl) runModeEl.value = scanRunMode;
    const rescanEl = document.getElementById('filter-autorescan');
    const rescanMinutes = [0, 2, 5, 10].includes(savedRescan) ? savedRescan : 0;
    if (rescanEl) rescanEl.value = String(rescanMinutes);
    if (rescanMinutes > 0) setAutoRescan(rescanMinutes);
}

function setScanRunMode(value) {
    scanRunMode = ['advisory', 'record_only', 'paper'].includes(value) ? value : 'advisory';
    try { localStorage.setItem('scanRunMode', scanRunMode); } catch (e) { /* ignore */ }
}

async function loadConfig() {
    try {
        const res = await apiFetch('/api/config');
        const data = await res.json();
        bookmakersConfig = data.bookmakers || {};
        configuredSports = Array.isArray(data.sports) ? data.sports.map(s => s.id || s) : [];
        const sweepBook = document.getElementById('sweep-book');
        if (sweepBook) {
            sweepBook.innerHTML = Object.entries(bookmakersConfig)
                .filter(([, book]) => book.enabled)
                .map(([id, book]) => `<option value="${escapeHtml(id)}">${escapeHtml(book.name || id)}</option>`)
                .join('');
        }
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
    const target = ['review', 'paper', 'history', 'evidence', 'other'].includes(tab) ? tab : 'surebets';
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
    if (target === 'paper') loadPaper();
    if (target === 'history') loadHistory();
    if (target === 'evidence') loadEvidence(true);
    if (target === 'other') renderOtherSports();
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

// j/k move through the list, Escape closes the settings drawer or the slip.
function handleGlobalKeydown(event) {
    if (event.key === 'Escape') {
        const drawer = document.getElementById('settings-drawer');
        if (drawer && !drawer.hidden) toggleSettings(false);
        else if (document.body.classList.contains('slip-open')) closeSlip();
        return;
    }
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
    // A slip belongs to the feed it was opened on. Leaving it open would hide
    // the list behind a placeholder on a phone with no way back.
    if (document.body.classList.contains('slip-open')) closeSlip();
    selectedSurebetId = null;
    // The previous feed's rows are not this feed's rows: clear them and say the
    // new one is loading instead of re-labelling stale matches.
    allSurebets = [];
    filteredSurebets = [];
    resultsSnapshot = null;
    freshnessSnapshot = null;
    showResultsLoading();
    loadResults(true);
    loadHealth();
    if (activeTab === 'review') loadCandidates();
    if (activeTab === 'evidence') loadEvidence(true);
}

// While a switch is in flight the list must not fall through to a diagnostic
// that describes a scan for the feed that is no longer on screen.
function showResultsLoading() {
    const grid = document.getElementById('results-grid');
    if (grid) { grid.innerHTML = ''; grid.hidden = true; }
    const loading = document.getElementById('list-loading');
    if (loading) {
        loading.textContent = tr('Loading the {mode} feed…', { mode: tr(currentMode === 'live' ? 'live' : 'prematch') });
        loading.hidden = false;
    }
    const empty = document.getElementById('empty-state');
    if (empty) empty.hidden = true;
    const noResults = document.getElementById('no-results');
    if (noResults) noResults.hidden = true;
    setText('stat-matches', '—');
    setText('stat-groups', '—');
    setText('stat-time', tr('never'));
    setText('surebets-count', '0');
    renderKpis([]);
    renderFreshnessBanner();
    renderRunModeBanner();
    renderFeedIntegrity();
    renderSlip();
}

function hideResultsLoading() {
    const loading = document.getElementById('list-loading');
    if (loading) { loading.hidden = true; loading.textContent = ''; }
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
    showToast(tr('Theme: {theme}', { theme: tr(next) }));
}

function updateThemeButton() {
    const button = document.getElementById('theme-btn');
    if (button) button.title = tr('Theme: {theme} (click to change)', { theme: tr(currentTheme()) });
}

function toggleSettings(open) {
    const drawer = document.getElementById('settings-drawer');
    const backdrop = document.getElementById('settings-backdrop');
    const button = document.getElementById('settings-btn');
    if (!drawer || !backdrop) return;
    const wasOpen = !drawer.hidden;
    drawer.hidden = !open;
    backdrop.hidden = !open;
    if (button) button.setAttribute('aria-expanded', String(open));
    if (open) {
        loadHealth();
        // Move focus into the drawer so a keyboard user lands on a control
        // instead of staying behind the backdrop.
        if (!wasOpen) {
            const first = drawer.querySelector('select, input, button, a, [tabindex]');
            if (first) first.focus();
        }
    } else if (wasOpen && button) {
        // Close/Escape/backdrop all return focus to the control that opened it.
        button.focus();
    }
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
            chip.dataset.riskProfile = cfg.risk_profile || 'unknown';
            chip.title = `${riskProfileLabel(cfg.risk_profile)} — ${cfg.limit_risk || 'check the book\'s limit policy'}`;
            chip.setAttribute('aria-pressed', String(cfg.enabled !== false));
            chip.addEventListener('click', () => toggleBookmakerAPI(chip, id));
            container.appendChild(chip);
        });
    }
    if (wall) {
        wall.innerHTML = '';
        bookieList
            .filter(([, cfg]) => cfg.enabled !== false)
            .forEach(([id, cfg]) => {
                const tag = document.createElement('span');
                tag.className = 'book-tag';
                // CSSOM assignment, not a style attribute: CSP style-src does
                // not block it and the value is never parsed as HTML.
                tag.style.setProperty('--color', cfg.color || BOOKMAKER_COLORS[id] || '#888');
                tag.textContent = cfg.name || capitalize(id);
                wall.appendChild(tag);
            });
    }
}

async function toggleBookmakerAPI(chip, id) {
    try {
        const res = await apiFetch(`/api/config/toggle/${encodeURIComponent(id)}`, { method: 'POST', headers: candidateActionHeaders() });
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
        const res = await apiFetch(`/api/config/toggle_market/${encodeURIComponent(box.value)}`, { method: 'POST', headers: candidateActionHeaders() });
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
        const res = await apiFetch(`/api/scan?mode=${currentMode}&run_mode=${encodeURIComponent(scanRunMode)}`, { method: 'POST', headers: candidateActionHeaders() });
        const data = await res.json().catch(() => ({}));
        if (res.status === 429) {
            showError(data.detail || tr('Too many scans — wait a moment.'));
            return;
        }
        if (!res.ok) {
            showError(data.detail || tr('Could not start the scan: {error}', { error: `HTTP ${res.status}` }));
            return;
        }
        if (data.status === 'maintenance') {
            // A 200 "maintenance" is not a started scan: never show progress or
            // a completion message for work that did not begin.
            showError(tr('The scanner is in maintenance. Try again when it is available.'));
            return;
        }
        if (data.status === 'already_scanning') {
            activeScanMode = currentMode;
            btn.disabled = true;
            setScanButtonLabel('Scanning…');
            showScanProgress();
            setStatus('scanning', scanModeText(), scanModeText);
            startPolling();
            return;
        }
        btn.disabled = true;
        setScanButtonLabel('Scanning…');
        activeScanMode = currentMode;
        showScanProgress();
        setStatus('scanning', scanModeText(), scanModeText);
        startPolling();
    } catch (e) {
        showError(tr('Could not start the scan: {error}', { error: e.message }));
    }
}

// Replace only the label inside the scan button. Writing `btn.textContent`
// destroyed the `data-i18n` span, so a later language switch could not find it.
function setScanButtonLabel(key) {
    const btn = document.getElementById('scan-btn');
    if (!btn) return;
    const span = btn.querySelector('span[data-i18n]') || btn.querySelector('span');
    const text = tr(key);
    if (span) {
        span.dataset.i18n = key;
        span.textContent = text;
    } else {
        btn.textContent = text;
    }
}

function scanModeText() {
    return tr('Scanning {mode} matches…', { mode: tr((activeScanMode || currentMode) === 'live' ? 'live' : 'upcoming') });
}

let diagnosticsTimer = null;

function startPolling() {
    if (pollingInterval) return;
    statusPollFailures = 0;
    pollingInterval = setInterval(pollStatus, 2000);
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function setAutoRescan(minutes) {
    const value = [0, 2, 5, 10].includes(Number(minutes)) ? Number(minutes) : 0;
    try { localStorage.setItem('autoRescanMinutes', String(value)); } catch (e) { /* ignore */ }
    if (autoRescanTimer) {
        clearInterval(autoRescanTimer);
        autoRescanTimer = null;
    }
    const countdownEl = document.getElementById('autorescan-countdown');
    if (!value) {
        if (countdownEl) countdownEl.hidden = true;
        return;
    }
    let remaining = value * 60;
    autoRescanTimer = setInterval(() => {
        remaining -= 1;
        if (countdownEl) {
            countdownEl.hidden = false;
            const m = Math.floor(remaining / 60);
            const s = (remaining % 60).toString().padStart(2, '0');
            countdownEl.textContent = tr('next scan {minutes}:{seconds}', { minutes: m, seconds: s });
        }
        if (remaining <= 0) {
            remaining = value * 60;
            scanNow();
        }
    }, 1000);
}

async function pollStatus() {
    const pollMode = activeScanMode || currentMode;
    try {
        const res = await apiFetch(`/api/status?mode=${pollMode}`);
        if (!res.ok) throw new Error(tr('request failed ({status})', { status: res.status }));
        const status = await res.json();
        const recovered = statusPollFailures > 0;
        statusPollFailures = 0;
        if (recovered) hideError();
        updateScanProgress(status);
        if (!status.is_scanning) {
            stopPolling();
            activeScanMode = null;
            await onScanComplete(status);
        }
    } catch (e) {
        statusPollFailures += 1;
        console.warn('Status poll failed:', e);
        // Warn once, but keep polling: the scan may be running behind a long
        // synchronous stage, and dropping the poll would hide its result.
        if (statusPollFailures === 5) {
            showError(tr('Could not read the server status.'));
        }
        // A genuinely dead endpoint must not leave a spinner up for ever, and
        // must not look like a completed scan.
        if (statusPollFailures >= STATUS_POLL_MAX_FAILURES) {
            statusPollFailures = 0;
            stopPolling();
            activeScanMode = null;
            hideScanProgress();
            const btn = document.getElementById('scan-btn');
            if (btn) {
                btn.disabled = false;
                setScanButtonLabel('Scan now');
            }
            showError(tr('Could not read the server status.'));
            setStatus('done', tr('Could not read the server status.'), () => tr('Could not read the server status.'));
        }
    }
}

function updateScanProgress(status) {
    const subEl = document.getElementById('scan-progress-sub');
    const doneEl = document.getElementById('scan-bookies-done');
    const barEl = document.getElementById('scan-bar');
    if (subEl) subEl.textContent = status.current_bookmaker || tr('Processing…');
    const statusText = () => status.current_bookmaker || tr('Scanning…');
    setStatus('scanning', statusText(), statusText);
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
    if (barEl) barEl.style.setProperty('--scan-progress', String(Math.min(92, (done / total) * 85 + 5)));
}

async function onScanComplete(status) {
    const barEl = document.getElementById('scan-bar');
    if (barEl) barEl.style.setProperty('--scan-progress', '100');
    hideScanProgress();
    const btn = document.getElementById('scan-btn');
    btn.disabled = false;
    setScanButtonLabel('Scan now');
    if (status.errors && status.errors.length > 0) {
        showError(tr('Some bookmakers failed: {books}', { books: status.errors.slice(0, 3).join('; ') }));
    }
    const completeText = () => (status.surebets_found > 0
        ? tr(status.surebets_found === 1 ? '{count} surebet found' : '{count} surebets found', { count: status.surebets_found })
        : tr('Scan complete — no surebets'));
    setStatus('done', completeText(), completeText);
    await loadResults();
    loadCandidates();
}

// ─── Results ──────────────────────────────────────────────────────────────────
async function loadResults(silent = false) {
    const requestedMode = currentMode;
    const token = ++resultsRequestSeq;
    try {
        const res = await apiFetch(`/api/results?mode=${requestedMode}`);
        if (!res.ok) throw new Error(tr('request failed ({status})', { status: res.status }));
        const data = await res.json();
        // A late response for the feed the user has already left must never
        // commit: the payload carries its own mode, and the token catches an
        // older request for the same mode.
        if (requestedMode !== currentMode || token !== resultsRequestSeq) return;
        if (data.mode && data.mode !== requestedMode) return;
        allSurebets = data.surebets || [];
        // `match_groups` is the mode-correct count of groups the certainty gate
        // accepted; the health payload's equivalent is prematch-only.
        resultsSnapshot = data;
        freshnessSnapshot = data.freshness || null;
        hideResultsLoading();
        renderFreshnessBanner();
        renderRunModeBanner();
        renderFeedIntegrity();

        setText('stat-matches', data.total_matches != null ? data.total_matches.toLocaleString() : '—');
        setText('stat-groups', data.match_groups != null ? Number(data.match_groups).toLocaleString() : '—');
        setText('stat-time', data.last_scan_time ? formatAgo(parseKickoff(data.last_scan_time)) : tr('never'));

        if (selectedSurebetId && !allSurebets.some(sb => sb.id === selectedSurebetId)) {
            selectedSurebetId = null;
        }
        applyFilters();
        renderOtherSports();

        // Chime for NEW high-value surebets only — never on page load, never
        // twice for the same surebet across rescans.
        const signatures = new Set(allSurebets.map(surebetSignature));
        if (!silent && allSurebets.some(s => s.profit_percent >= 3.0 && !knownSurebetSignatures.has(surebetSignature(s)))) {
            playAlertSound();
        }
        knownSurebetSignatures = signatures;
    } catch (e) {
        if (requestedMode !== currentMode || token !== resultsRequestSeq) return;
        console.error('Failed to load results:', e);
        const message = tr('Failed to load results: {error}', { error: e.message });
        // Keep whatever list was already on screen, but make the failure visible
        // instead of letting a 401/500 look like a scan with no surebets.
        const loading = document.getElementById('list-loading');
        if (loading && !loading.hidden) loading.textContent = message;
        showError(message);
    }
}

// P0-4: staleness is a live state, not a value frozen at load time. Recompute
// the age from the scan timestamp each tick so a page left open crosses its TTL
// visibly instead of continuing to look current.
function currentFreshness() {
    if (!freshnessSnapshot) return null;
    const scan = freshnessSnapshot.scan_time ? parseKickoff(freshnessSnapshot.scan_time) : null;
    const age = scan ? Math.max(0, (Date.now() - scan.getTime()) / 1000) : null;
    const ttl = Number(freshnessSnapshot.ttl_sec) || 0;
    const stale = Boolean(freshnessSnapshot.stale) || age == null || (ttl > 0 && age > ttl);
    return { ...freshnessSnapshot, age_sec: age, stale };
}

function staleFeed() {
    return Boolean(currentFreshness()?.stale);
}

function freshnessAgeText(seconds) {
    if (seconds == null) return tr('unknown age');
    if (seconds < 60) return tr('{count}s', { count: Math.round(seconds) });
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return tr('{minutes}m {seconds}s', { minutes, seconds: Math.round(seconds % 60) });
    const hours = Math.floor(minutes / 60);
    return tr('{hours}h {minutes}m', { hours, minutes: minutes % 60 });
}

function renderFreshnessBanner() {
    const banner = document.getElementById('freshness-banner');
    if (!banner) return;
    const fresh = currentFreshness();
    const stale = Boolean(fresh?.stale);
    document.body.classList.toggle('feed-stale', stale);
    const signature = [
        stale,
        fresh?.mode,
        fresh?.state,
        fresh?.ttl_sec,
        fresh?.age_sec == null ? null : Math.floor(fresh.age_sec / 10),
        (fresh?.stale_books || []).join(','),
        allSurebets.length === 0,
    ].join('|');
    if (signature === freshnessBannerSignature) return;
    freshnessBannerSignature = signature;
    banner.hidden = !stale;
    if (!stale) { banner.innerHTML = ''; return; }

    const mode = tr(fresh.mode === 'live' ? 'live' : 'prematch');
    const ttl = fresh.ttl_sec;
    const books = (fresh.stale_books || []).map(b => bookName(b));
    const booksText = books.length
        ? tr(' Stale book(s): {books}.', { books: books.map(escapeHtml).join(', ') })
        : '';
    // Before the first scan with nothing listed there is no price to warn about,
    // and the empty state already offers the scan. A calm notice, not an alarm;
    // as soon as any row is on screen the full stale warning returns.
    const quiet = fresh.state === 'never_scanned' && allSurebets.length === 0;
    banner.classList.toggle('freshness-banner-quiet', quiet);
    if (quiet) {
        banner.innerHTML = `<strong>${escapeHtml(tr('No completed {mode} scan.', { mode }))}</strong> ${escapeHtml(tr('Nothing on this screen is a current price.'))}`;
        return;
    }
    let message;
    if (fresh.state === 'never_scanned') {
        message = `<strong>${escapeHtml(tr('No completed {mode} scan.', { mode }))}</strong> ${escapeHtml(tr('Nothing on this screen is a current price.'))}`;
    } else if (fresh.state === 'book_older_than_ttl') {
        message = `<strong>${escapeHtml(tr('Historical {mode} data.', { mode }))}</strong> ${escapeHtml(tr('At least one book is older than the {ttl}s freshness budget.', { ttl }))}${booksText}`;
    } else {
        message = `<strong>${escapeHtml(tr('Historical {mode} data.', { mode }))}</strong> ${escapeHtml(tr('The last scan is {age} old; the budget is {ttl}s.', { age: freshnessAgeText(fresh.age_sec), ttl }))}${booksText}`;
    }
    banner.innerHTML = `${message} ${escapeHtml(tr('These odds are not current — re-check a slip or run a new scan.'))}
        <button type="button" class="btn btn-primary btn-small" data-action="scan-now">${escapeHtml(tr('Scan now'))}</button>`;
}

// P3-7: the last completed scan may not have been advisory. Say so instead of
// letting an earlier live list look like the result of a record-only run.
function renderRunModeBanner() {
    const banner = document.getElementById('run-mode-banner');
    if (!banner) return;
    const runMode = resultsSnapshot?.run_mode || 'advisory';
    if (runMode === 'advisory') {
        banner.hidden = true;
        banner.innerHTML = '';
        return;
    }
    const count = Number(resultsSnapshot?.recorded_opportunities || 0);
    const label = runMode === 'paper' ? tr('Paper trading') : tr('Record-only');
    const noun = tr(count === 1 ? 'opportunity' : 'opportunities');
    const detail = runMode === 'paper'
        ? tr(' {count} verified {noun} recorded and tracked in the virtual paper ledger.', { count, noun })
        : tr(' {count} verified {noun} recorded in the paper ledger.', { count, noun });
    banner.hidden = false;
    banner.innerHTML = `<strong>${escapeHtml(label)}${escapeHtml(tr(' scan.'))}</strong>${escapeHtml(detail)}
        ${escapeHtml(tr('No live surebet is shown and no bet was placed. Switch Run mode back to Advisory to scan for live opportunities.'))}`;
}

// P0-7: only unhealthy books are shown here. A healthy feed needs no badge,
// and a quarantined one must say which book is out and why it is not priced.
function renderFeedIntegrity() {
    const strip = document.getElementById('feed-integrity');
    if (!strip) return;
    const payload = resultsSnapshot?.feed_integrity || {};
    const books = Object.values(payload.books || {});
    const unhealthy = books.filter(book => book.state && book.state !== 'healthy');
    const frozen = Number(payload.stale_prices?.count || 0);
    strip.hidden = unhealthy.length === 0 && frozen === 0;
    if (!unhealthy.length && frozen === 0) { strip.innerHTML = ''; return; }
    const badges = unhealthy.map(book => {
        const state = book.state === 'quarantined' ? 'quarantined' : 'degraded';
        const reasons = (book.reasons || []).map(reason => feedReasonLabel(reason));
        const reasonText = reasons.join(', ') || book.reason || tr('unhealthy');
        const label = book.name || bookName(book.bookmaker);
        return `<span class="feed-integrity-badge" data-state="${escapeHtml(state)}" title="${escapeHtml(book.reason || reasonText)}">`
            + `<b>${escapeHtml(label)}</b> ${escapeHtml(tr(state))} — ${escapeHtml(reasonText)}`
            + (state === 'quarantined' ? ` · ${escapeHtml(tr('not priced'))}` : '')
            + '</span>';
    }).join('');
    // N0-2: a frozen price is refused, not quarantined; say so without
    // pretending the whole book is out.
    const frozenBadge = frozen
        ? `<span class="feed-integrity-badge" data-state="degraded" title="${escapeHtml(tr('A price unchanged while peers moved, or older than the book update budget, is refused for this scan.'))}">`
            + `<b>${escapeHtml(tr('price frozen'))}</b> ${frozen} ${escapeHtml(tr(frozen === 1 ? 'row refused' : 'rows refused'))}`
            + '</span>'
        : '';
    strip.innerHTML = `<span class="feed-integrity-title">${escapeHtml(tr('Feed integrity'))}</span>${badges}${frozenBadge}`;
}

function surebetSignature(sb) {
    const stakes = sb.stakes
        .map(s => `${s.bookmaker}:${s.outcome_label}:${s.odds}`)
        .sort()
        .join('|');
    return `${sb.home_team}|${sb.away_team}|${sb.market_type}|${stakes}`;
}

function footballSurebets() {
    return allSurebets.filter(sb => (sb.sport || 'football') === 'football');
}

function applyFilters() {
    const marketFilter = document.getElementById('filter-market').value;
    const profitInput = document.getElementById('filter-profit').value;
    const minProfit = profitInput !== '' ? parseFloat(profitInput) : 0;
    const searchTerm = document.getElementById('filter-search').value.trim().toLowerCase();
    const sortMode = document.getElementById('filter-sort').value;

    filteredSurebets = allSurebets.filter(sb => {
        // This panel is football only; the Other sports tab has its own filter.
        if ((sb.sport || 'football') !== 'football') return false;
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
    const pool = footballSurebets();
    const counts = {};
    pool.forEach(sb => { counts[sb.market_type] = (counts[sb.market_type] || 0) + 1; });
    const markets = Object.keys(MARKET_LABELS).filter(m => counts[m] || m === active);
    wrap.hidden = pool.length === 0;
    wrap.innerHTML = [['', tr('All'), pool.length], ...markets.map(m => [m, marketLabel(m), counts[m] || 0])]
        .map(([value, label, count]) => `<button type="button" class="mchip${value === active ? ' active' : ''}" aria-pressed="${value === active}" data-action="set-market-filter" data-market="${escapeHtml(value)}">${escapeHtml(label)} <b>${count}</b></button>`)
        .join('');
}

function setMarketFilter(market) {
    document.getElementById('filter-market').value = market;
    applyFilters();
}

function renderKpis(surebets) {
    const pool = footballSurebets();
    const best = surebets.reduce((top, sb) => (!top || sb.profit_percent > top.profit_percent ? sb : top), null);
    const hero = document.querySelector('.kpi-hero');
    if (hero) hero.toggleAttribute('data-empty', !best);
    setText('kpi-best', best ? `${best.profit_percent.toFixed(2)}%` : '—');
    setText('kpi-best-sub', best
        ? tr('+{profit} KM on {stake} KM · {team}', { profit: money(globalInvestment * best.profit_percent / 100), stake: globalInvestment, team: formatTeamName(best.home_team) })
        : tr('no surebet yet'));
    setText('kpi-count', surebets.length);
    setText('kpi-count-sub', pool.length > surebets.length
        ? tr('of {found} found · {filtered} filtered out', { found: pool.length, filtered: pool.length - surebets.length })
        : tr('above your minimum'));

    const metrics = resultsSnapshot?.opportunity_metrics || {};
    const boards = Number(metrics.boards) || 0;
    const crossingRate = Number(metrics.crossing_rate_percent);
    setText('kpi-crossing', boards > 0 && Number.isFinite(crossingRate)
        ? `${crossingRate.toFixed(2)}%`
        : '—');
    setText('kpi-crossing-sub', boards > 0
        ? tr('{crossed} of {boards} boards · {actionable} actionable', { crossed: Number(metrics.crossed) || 0, boards, actionable: Number(metrics.actionable) || 0 })
        : tr(ZERO_RESULT_LABELS[metrics.zero_result_reason] || 'no boards priced'));
    setText('kpi-mode-sub', tr(currentMode === 'live' ? 'live matches' : 'upcoming matches'));
}

function otherSurebets() {
    return allSurebets.filter(sb => (sb.sport || 'football') !== 'football');
}

function setOtherSportFilter(value) {
    otherSportFilter = value || 'all';
    renderOtherSports();
}

function renderOtherSports() {
    const grid = document.getElementById('other-grid');
    if (!grid) return;
    const pool = otherSurebets();
    const sports = [...new Set([
        ...configuredSports.filter(s => s !== 'football'),
        ...pool.map(sb => sb.sport || 'football'),
    ])].sort();
    if (otherSportFilter !== 'all' && !sports.includes(otherSportFilter)) {
        otherSportFilter = 'all';
    }
    const select = document.getElementById('other-sport-filter');
    if (select) {
        const options = [`<option value="all">${escapeHtml(tr('All other sports'))}</option>`]
            .concat(sports.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(sportLabel(s))}</option>`));
        select.innerHTML = options.join('');
        select.value = otherSportFilter;
    }
    const search = (document.getElementById('other-search')?.value || '').trim().toLowerCase();
    const minProfit = parseFloat(document.getElementById('other-profit')?.value || '0') || 0;
    const rows = pool.filter(sb => {
        if (otherSportFilter !== 'all' && (sb.sport || 'football') !== otherSportFilter) return false;
        if (sb.profit_percent < minProfit) return false;
        if (!sb.stakes.every(s => activeBookmakers.has(s.bookmaker))) return false;
        if (search) {
            const haystack = `${sb.home_team} ${sb.away_team} ${sb.league || ''}`.toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    }).sort((a, b) => b.profit_percent - a.profit_percent);

    setText('other-count', pool.length);
    setText('other-kpi-count', rows.length);
    const best = rows[0];
    setText('other-kpi-best', best ? `${best.profit_percent.toFixed(2)}%` : '—');
    setText('other-kpi-sports', sports.length ? sports.map(s => sportLabel(s)).join(' · ') : tr('none yet'));
    const empty = document.getElementById('other-empty');
    if (empty) empty.hidden = rows.length > 0;
    grid.innerHTML = rows.map(sb => {
        const sport = sb.sport || 'football';
        const legs = sb.stakes.map(stake => `
            <span class="leg-pill" title="${escapeHtml(bookName(stake.bookmaker))}: ${escapeHtml(outcomeDescription(stake.outcome_label, sb.market_type, sport))} at ${stake.odds.toFixed(2)}">
                <b>${escapeHtml(bookName(stake.bookmaker))}</b>
                ${escapeHtml(outcomeDescription(stake.outcome_label, sb.market_type, sport))}
                <span class="mono">${stake.odds.toFixed(2)}</span>
            </span>`).join('');
        return `<article class="other-card" role="listitem" data-sport="${escapeHtml(sport)}">
            <div class="row-top">
                <span class="sport-badge">${escapeHtml(sportLabel(sport))}</span>
                <span class="profit mono">${sb.profit_percent.toFixed(2)}%</span>
            </div>
            <div class="row-title">${escapeHtml(formatTeamName(sb.home_team))} <span class="row-vs">vs</span> ${escapeHtml(formatTeamName(sb.away_team))}</div>
            <div class="row-meta"><span class="mkt">${escapeHtml(marketLabel(sb.market_type))}</span><span class="row-league">${escapeHtml(formatLeague(sb.league))}</span></div>
            <div class="other-legs">${legs}</div>
        </article>`;
    }).join('');
}

function renderSurebets(surebets) {
    const grid = document.getElementById('results-grid');
    hideResultsLoading();
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
        if (selectedSurebetId || document.body.classList.contains('slip-open')) closeSlip();
        else renderSlip();
        return;
    }
    grid.hidden = false;
    document.getElementById('empty-state').hidden = true;
    document.getElementById('no-results').hidden = true;

    surebets.forEach(sb => grid.appendChild(buildSurebetRow(sb)));
    const selectionVisible = selectedSurebetId && surebets.some(sb => sb.id === selectedSurebetId);
    if (!selectionVisible) {
        // The selected row was filtered out or replaced by a new scan. Close the
        // slip: on a phone `slip-open` hides the list behind a dead placeholder.
        if (selectedSurebetId || document.body.classList.contains('slip-open')) closeSlip();
        // Open the best one straight away on a wide screen; on a phone the list
        // comes first and a tap opens the slip. A pure repaint (language change)
        // never counts as opening a slip.
        if (allowAutoSelect && window.matchMedia('(min-width: 900px)').matches) selectSurebet(surebets[0].id);
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
    row.setAttribute('aria-selected', 'false');
    row.dataset.tier = profitTier(sb.profit_percent);
    const kickoff = parseKickoff(sb.kickoff);
    const when = currentMode === 'live' ? tr('In play') : (kickoff ? formatKickoff(kickoff) : '');
    // Kickoff inside the hour is flagged: the window to place all legs is closing.
    const minutesAway = kickoff ? (kickoff.getTime() - Date.now()) / 60000 : null;
    const whenClass = currentMode === 'live' ? ' live' : (minutesAway != null && minutesAway >= 0 && minutesAway < 60 ? ' soon' : '');
    const whenText = whenClass === ' soon' ? tr('in {minutes} min', { minutes: Math.max(1, Math.round(minutesAway)) }) : when;
    const legs = placementOrder(sb.stakes).map(s => `
        <span class="leg-pill" title="${escapeHtml(bookName(s.bookmaker))}: ${escapeHtml(outcomeDescription(s.outcome_label, sb.market_type, sb.sport))} at ${s.odds.toFixed(2)}">
            <span class="book-dot" data-book-color="${escapeHtml(s.bookmaker)}">${escapeHtml(bookShort(s.bookmaker))}</span>
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
            <span class="row-meta"><span class="mkt">${escapeHtml(marketLabel(sb.market_type))}</span><span class="row-when${whenClass}">${escapeHtml(whenText)}</span><span class="row-league">${escapeHtml(formatLeague(sb.league))}</span></span>
        </span>
        <span class="row-legs">${legs}</span>${badge}
    `;
    applyDynamicStyles(row);
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
    selectedSurebetId = null;
    markSelectedRow();
    renderSlip();
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

// The served odds are the only source of truth for the margin. These helpers
// let the slip check the payload's number instead of trusting a second
// calculation silently.
function servedMargin(sb) {
    const stakes = sb && Array.isArray(sb.stakes) ? sb.stakes : [];
    return stakes.reduce((sum, stake) => sum + 1 / Number(stake.odds), 0);
}

function servedProfitPercent(sb) {
    const margin = servedMargin(sb);
    return margin > 0 ? (1 / margin - 1) * 100 : 0;
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
                <button type="button" class="link-btn slip-back" data-action="close-slip">← ${escapeHtml(tr('All surebets'))}</button>
                <h3>${escapeHtml(tr('Bet slip'))}</h3>
                <p>${escapeHtml(tr('Pick a surebet on the left. Its odds are re-checked first, then you get each leg in the order to place it, with the stake to type.'))}</p>
            </div>`;
        return;
    }
    const state = slipFor(sb);
    const check = verifyState[sb.id];
    const plan = planStakes(placementOrder(currentStakes(sb, check)), state.investment, state.placed);
    const kickoff = parseKickoff(sb.kickoff);
    const exactProfit = sb.profit_percent;
    const roundingCost = exactProfit - plan.profitPercent;
    const exactProfitAmount = plan.total * exactProfit / 100;
    const roundingEffect = plan.profit - exactProfitAmount;
    const derivedMargin = servedMargin(sb);
    const reportedMargin = Number(sb.raw_margin ?? sb.total_margin);
    const marginMismatch = Number.isFinite(reportedMargin)
        && Math.abs(reportedMargin - derivedMargin) > 1e-6;
    const profitMismatch = Math.abs(servedProfitPercent(sb) - exactProfit) > 0.01;

    const warnings = [];
    if (staleFeed()) {
        warnings.push(`<div class="slip-alert slip-alert-bad">${escapeHtml(tr('These are historical scan prices, not a current opportunity. Copy is disabled; use Re-check odds to establish the current prices before placing.'))}</div>`);
    }
    if (marginMismatch || profitMismatch) {
        warnings.push(`<div class="slip-alert slip-alert-bad">${escapeHtml(tr('The served odds do not reproduce the payload margin. Do not use this slip; run a new scan.'))}</div>`);
    }
    if (plan.profit <= 0) {
        warnings.push(`<div class="slip-alert slip-alert-bad">${escapeHtml(tr('With these stakes the worst outcome loses {loss} KM.', { loss: money(-plan.profit) }))} ${escapeHtml(Object.keys(state.placed).length ? tr('A placed price moved — consider stopping or hedging rather than placing the rest.') : tr('Raise the total stake or round to exact amounts.'))}</div>`);
    } else if (!Object.keys(state.placed).length && roundingCost > exactProfit / 2) {
        warnings.push(`<div class="slip-alert">${escapeHtml(tr('Rounding eats more than half the edge ({left}% left of {exact}%). A larger total stake keeps more of it.', { left: plan.profitPercent.toFixed(2), exact: exactProfit.toFixed(2) }))}</div>`);
    }
    if (plan.legs.some(leg => !leg.placed && leg.plannedStake < 1)) {
        warnings.push(`<div class="slip-alert">${escapeHtml(tr('A stake is below 1 KM — most bookmakers will not take it.'))}</div>`);
    }
    const overLimit = plan.legs.filter(leg => {
        const limit = Number(bookmakersConfig?.[leg.bookmaker]?.max_stake);
        return !leg.placed && limit > 0 && leg.plannedStake > limit;
    });
    const softOverLimit = overLimit.filter(leg => bookRisk(leg.bookmaker).profile === 'soft');
    const otherOverLimit = overLimit.filter(leg => bookRisk(leg.bookmaker).profile !== 'soft');
    if (otherOverLimit.length) {
        const details = otherOverLimit.map(leg => `${bookName(leg.bookmaker)} ${stakeFormat(leg.plannedStake)}/${stakeFormat(bookmakersConfig[leg.bookmaker].max_stake)}`).join(', ');
        warnings.push(`<div class="slip-alert">${escapeHtml(tr('Above the advisory book limit: {details} KM. Split or reduce before placing.', { details }))}</div>`);
    }
    if (softOverLimit.length) {
        const details = softOverLimit.map(leg => `${bookName(leg.bookmaker)} ${stakeFormat(leg.plannedStake)}/${stakeFormat(bookmakersConfig[leg.bookmaker].max_stake)}`).join(', ');
        warnings.push(`<div class="slip-alert slip-alert-bad" data-risk-warning="soft-book-stake">${escapeHtml(tr('High stake at a soft book: {details} KM. Retail books often cut stakes or limit accounts after repeated arbing. Reduce or split the stake; this warning is advisory and nothing is placed automatically.', { details }))}</div>`);
    }

    const listings = sb.listings || {};
    const legsHtml = plan.legs.map((leg, index) => {
        const name = bookName(leg.bookmaker);
        const risk = bookRisk(leg.bookmaker);
        const riskTitle = `${risk.typical} ${risk.limit}`.trim();
        const listing = listings[leg.bookmaker];
        const listedAs = listing ? `${listing.home} – ${listing.away}` : `${formatTeamName(sb.home_team)} – ${formatTeamName(sb.away_team)}`;
        // The destination is the only thing that may label a link. A fallback is
        // never presented as a filled ticket, and a plain match page is never
        // called a ticket.
        const dest = leg.destination || {};
        const destKind = dest.kind || '';
        const url = dest.url || '';
        const destLabel = dest.label || (url ? tr('Open {name}', { name }) : '');
        const searchText = dest.search_text || listedAs;
        const pickText = dest.selection || leg.selection || leg.outcome_label;
        const pickLine = dest.line || leg.line || '';
        const lineText = pickLine && !String(pickText).includes(pickLine) ? tr(' · line {line}', { line: pickLine }) : '';
        const copyLabel = tr(destKind === 'search' ? 'copy search' : destKind === 'competition' ? 'copy fixture' : 'copy name');
        const stakeNote = destKind === 'ticket_filled' && !dest.ticket_stake_supported
            ? `<span class="leg-sub">${escapeHtml(tr('stake not prefilled'))}</span>` : '';
        const drift = check?.data?.drift?.[leg.outcome_label];
        let driftNote = '';
        if (leg.scannedOdds != null && !leg.placed) {
            driftNote = `<span class="leg-drift">${escapeHtml(tr('was {odds} at scan', { odds: leg.scannedOdds.toFixed(2) }))}</span>`;
        } else if (drift && drift.changed && !leg.placed) {
            driftNote = `<span class="leg-drift leg-drift-bad">${drift.new_odds != null ? escapeHtml(tr('best now {odds} at {book}', { odds: Number(drift.new_odds).toFixed(2), book: bookName(drift.new_bookmaker) })) : escapeHtml(tr('no longer offered'))}</span>`;
        }
        const stakeText = leg.plannedStake.toFixed(stakeRounding === 'exact' ? 2 : 0);
        const label = escapeHtml(leg.outcome_label);
        return `
        <li class="leg${leg.placed ? ' leg-placed' : ''}" data-book-color="${escapeHtml(leg.bookmaker)}" data-label="${label}">
            <div class="leg-step">${index + 1}</div>
            <div class="leg-body">
                <div class="leg-head">
                    <span class="leg-book-wrap">
                        <span class="leg-book">${escapeHtml(name)}</span>
                        <span class="risk-badge" data-risk-profile="${escapeHtml(risk.profile)}" title="${escapeHtml(riskTitle)}">${escapeHtml(riskProfileLabel(risk.profile))}</span>
                    </span>
                    ${url ? `<a class="btn btn-small dest-link" data-dest-kind="${escapeHtml(destKind)}" href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noopener" title="${escapeHtml(dest.proof_summary || destKind || '')}">${escapeHtml(destLabel)} ↗</a>` : ''}
                    ${destKind === 'search' && !url ? `<button type="button" class="btn btn-small btn-secondary" ${copyAttributes(searchText, tr('Search text copied'))}>${escapeHtml(tr('Copy search text'))}</button>` : ''}
                    ${dest.ticket_script ? `<button type="button" class="btn btn-small btn-secondary" title="${escapeHtml(tr('Paste this in the SportPlus page console; it only fills the slip'))}" ${copyAttributes(dest.ticket_script, tr('SportPlus prefill script copied — paste it into the SportPlus page console'))}>${escapeHtml(dest.ticket_script_label || tr('Copy prefill script'))}</button>` : ''}
                </div>
                <div class="leg-listing">
                    <span title="${escapeHtml(tr('How {name} lists this match', { name }))}">${escapeHtml(listedAs)}</span>
                    <button type="button" class="link-btn" ${copyAttributes(searchText, copyLabel === tr('copy search') ? tr('Search text copied') : tr('Match name copied'))}>${copyLabel}</button>
                    ${listing?.league ? `<span class="leg-league">${escapeHtml(listing.league)}</span>` : ''}
                    ${destKind ? `<span class="leg-league">${escapeHtml(destKind === 'ticket_filled' ? tr('ticket') : destKind === 'match_page' ? tr('match page') : destKind)}</span>` : ''}
                    <span class="leg-risk-note" title="${escapeHtml(risk.limit)}">${escapeHtml(risk.typical)}</span>
                </div>
                <div class="leg-bet">
                    <div><span class="leg-k">${escapeHtml(tr('Pick'))}</span><span class="leg-v">${escapeHtml(pickText)}${escapeHtml(lineText)}</span><span class="leg-sub">${escapeHtml(outcomeDescription(leg.outcome_label, sb.market_type, sb.sport))}</span>${stakeNote}</div>
                    <div><span class="leg-k">${escapeHtml(tr('Odds'))}</span><span class="leg-v mono">${leg.takenOdds.toFixed(2)}</span>${driftNote}</div>
                    <div><span class="leg-k">${escapeHtml(tr('Stake'))}</span>
                        <button type="button" class="leg-v mono stake-copy" title="${escapeHtml(tr('Copy stake'))}" ${copyAttributes(stakeText, tr('Stake copied'))}>${stakeText} KM</button>
                    </div>
                    <div><span class="leg-k">${escapeHtml(tr('Returns'))}</span><span class="leg-v mono">${money(leg.plannedStake * leg.takenOdds)}</span></div>
                </div>
                <div class="leg-placed-row">
                    ${leg.placed
                        ? `<span class="placed-tag">${escapeHtml(tr('Placed at {odds} for {stake} KM', { odds: leg.takenOdds.toFixed(2), stake: stakeText }))}</span>
                           <button type="button" class="link-btn" data-action="unmark-placed" data-slip-id="${escapeHtml(sb.id)}" data-outcome-label="${escapeHtml(leg.outcome_label)}">${escapeHtml(tr('undo'))}</button>`
                        : `<label class="placed-odds">${escapeHtml(tr('Odds taken'))} <input class="input input-narrow mono" type="number" step="0.01" min="1.01" value="${leg.odds.toFixed(2)}" data-placed-odds></label>
                           <label class="placed-odds">${escapeHtml(tr('Stake accepted'))} <input class="input input-narrow mono" type="number" step="1" min="0.01" value="${leg.plannedStake}" data-placed-stake></label>
                           <button type="button" class="btn btn-secondary btn-small" data-action="mark-placed" data-slip-id="${escapeHtml(sb.id)}" data-outcome-label="${escapeHtml(leg.outcome_label)}">${escapeHtml(tr('Mark placed'))}</button>`}
                </div>
            </div>
        </li>`;
    }).join('');

    const evidence = (sb.evidence || []).map(line => `<li>${escapeHtml(line)}</li>`).join('');
    const placedCount = Object.keys(state.placed).length;
    const locked = placedCount ? ` disabled title="${escapeHtml(tr('Fixed once a leg is placed'))}"` : '';
    const presets = [50, 100, 200, 500].map(amount => `
        <button type="button" class="${Number(state.investment) === amount ? 'active' : ''}"${locked}
                data-action="set-slip-investment" data-slip-id="${escapeHtml(sb.id)}" data-amount="${amount}">${amount}</button>`).join('');

    pane.innerHTML = `
        <div class="slip-head">
            <button type="button" class="link-btn slip-back" data-action="close-slip">← ${escapeHtml(tr('All surebets'))}</button>
            <div class="slip-eyebrow">
                <span class="mkt">${escapeHtml(marketLabel(sb.market_type))}</span>
                <span>${escapeHtml(formatLeague(sb.league))}</span>
                <span class="status-badge" hidden></span>
            </div>
            <div class="slip-title">
                <h2>${escapeHtml(formatTeamName(sb.home_team))} – ${escapeHtml(formatTeamName(sb.away_team))}</h2>
                <p>${escapeHtml(currentMode === 'live' ? tr('In play') : (kickoff ? formatKickoffLong(kickoff) : tr('Kickoff unknown')))}</p>
            </div>
        </div>

        <div class="slip-hero${plan.profit > 0 ? '' : ' is-loss'}">
            <div class="slip-profit" data-tier="${profitTier(plan.profitPercent)}" title="${escapeHtml(tr('Realized profit of the rounded stakes below'))}">
                <span class="mono">${plan.profitPercent.toFixed(2)}%</span>
                <small>${escapeHtml(tr('{profit}% at scan, exact stakes', { profit: exactProfit.toFixed(2) }))}</small>
            </div>
            <div class="slip-stake">
                <label class="inline-field"><span>${escapeHtml(tr('Total stake'))}</span>
                    <input class="input mono" type="number" min="1" step="10" value="${state.investment}"
                           data-slip-investment-input data-slip-id="${escapeHtml(sb.id)}"${locked}> KM</label>
                <div class="slip-presets" aria-label="${escapeHtml(tr('Quick stake'))}">${presets}</div>
            </div>
        </div>

        <div class="slip-totals">
            <span>${escapeHtml(tr('Staked'))} <b class="mono">${money(plan.total)}</b></span>
            <span>${escapeHtml(tr('Worst return'))} <b class="mono">${money(plan.worst)}</b></span>
            <span>${escapeHtml(tr('Exact profit'))} <b class="mono">${exactProfitAmount >= 0 ? '+' : ''}${money(exactProfitAmount)} KM</b></span>
            <span class="${plan.profit > 0 ? 'good' : 'bad'}">${escapeHtml(tr('Realized profit'))} <b class="mono">${plan.profit >= 0 ? '+' : ''}${money(plan.profit)} KM</b></span>
            <span class="${roundingEffect < 0 ? 'bad' : ''}">${escapeHtml(tr('Rounding effect'))} <b class="mono">${roundingEffect >= 0 ? '+' : '−'}${money(Math.abs(roundingEffect))} KM</b></span>
        </div>

        ${renderVerifyBanner(sb, check)}
        ${warnings.join('')}

        <div class="slip-progress">
            <span>${placedCount
                ? escapeHtml(tr('{placed} of {total} placed', { placed: placedCount, total: plan.legs.length }))
                : escapeHtml(tr('Place {total} bets, top to bottom', { total: plan.legs.length }))}</span>
            <span class="slip-progress-bar"><i data-progress="${(placedCount / plan.legs.length) * 100}"></i></span>
        </div>
        <ol class="legs">${legsHtml}</ol>

        <details class="slip-howto">
            <summary>${escapeHtml(tr('How to place this'))}</summary>
            <ol>
                <li>${escapeHtml(tr('Place the legs top to bottom. The first has the longest odds — the price most likely to move or be limited.'))}</li>
                <li>${escapeHtml(tr('On the bookmaker site, check the odds match before you confirm. If they dropped or the book accepted only part of the stake, type what you actually got into Odds taken and Stake accepted, then press Mark placed: the remaining stakes are re-planned to cover it.'))}</li>
                <li>${escapeHtml(tr('If a later leg is gone or the profit turns red, stop. Either hedge the placed leg at the best price available or accept the single bet — do not chase.'))}</li>
            </ol>
        </details>

        ${evidence ? `<div class="slip-evidence"><h3>${escapeHtml(tr('Why these are the same match'))}</h3><ul>${evidence}</ul></div>` : ''}

        <div class="slip-actions">
            <button type="button" class="btn btn-secondary" data-action="verify-surebet" data-slip-id="${escapeHtml(sb.id)}">${escapeHtml(tr('Re-check odds'))}</button>
            <button type="button" class="btn btn-secondary" data-action="log-bet" data-slip-id="${escapeHtml(sb.id)}">${escapeHtml(tr('Log bet'))}</button>
            <button type="button" class="btn btn-secondary" data-action="copy-surebet" data-slip-id="${escapeHtml(sb.id)}"${staleFeed() ? ' disabled aria-disabled="true" data-stale-blocked="true"' : ''}>${escapeHtml(tr('Copy slip'))}</button>
        </div>
    `;
    applyDynamicStyles(pane);
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
        statusEl.textContent = tr(statusInfo.label);
        statusEl.setAttribute('aria-label', tr(statusInfo.ariaLabel));
    }
}

// Translate, escape the copy, then splice in trusted markup for the named
// placeholders. Escaping after `tr()` turned a live `<span data-ago>` into
// visible text.
function trWithMarkup(text, markup) {
    const names = Object.keys(markup);
    const tokens = {};
    names.forEach((name, i) => { tokens[name] = `\u0000${i}\u0000`; });
    let out = escapeHtml(tr(text, tokens));
    names.forEach((name, i) => { out = out.split(`\u0000${i}\u0000`).join(markup[name]); });
    return out;
}

function renderVerifyBanner(sb, check) {
    if (!check) return `<div class="verify-banner verify-idle">${escapeHtml(tr('Odds not re-checked yet.'))}</div>`;
    if (check.state === 'checking') {
        return `<div class="verify-banner verify-checking"><span class="spinner"></span> ${escapeHtml(tr('Re-checking the odds at each bookmaker…'))}</div>`;
    }
    const ago = `<span data-ago="${check.at.getTime()}">${formatAgo(check.at)}</span>`;
    if (check.state === 'ok') {
        const fresh = verifyIsFresh(check);
        const floor = check.data.meets_min_profit === false ? tr(' — below your usual minimum') : '';
        return `<div class="verify-banner ${fresh ? 'verify-ok' : 'verify-stale'}">
            ${escapeHtml(fresh ? tr('Still a surebet') : tr('Was a surebet'))}: <b class="mono">${Number(check.data.current.profit_percent).toFixed(2)}%</b>${escapeHtml(floor)}, ${trWithMarkup('re-checked {ago}.', { ago })}
            ${fresh ? '' : escapeHtml(tr(' Re-check before placing.'))}</div>`;
    }
    if (check.state === 'gone') {
        const now = check.data?.current ? ` (now ${Number(check.data.current.profit_percent).toFixed(2)}%)` : '';
        return `<div class="verify-banner verify-bad">${escapeHtml(tr('Gone{now}.', { now }))} ${escapeHtml(check.data?.message || tr('The prices moved.'))} ${trWithMarkup('Checked {ago}. Do not place.', { ago })}</div>`;
    }
    return `<div class="verify-banner verify-unknown">${escapeHtml(tr('Could not confirm: {reason}.', { reason: check.message || tr('unknown') }))} ${trWithMarkup('Checked {ago}. Check each price on the site before placing.', { ago })}</div>`;
}

function verifyShortLabel(check) {
    if (check.state === 'checking') return tr('checking');
    if (check.state === 'ok') return verifyIsFresh(check) ? tr('live ✓') : tr('stale');
    if (check.state === 'gone') return tr('gone');
    return tr('unconfirmed');
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
    const row = button.closest('.leg');
    const input = row.querySelector('[data-placed-odds]');
    const stakeInput = row.querySelector('[data-placed-stake]');
    const odds = parseFloat(input?.value);
    const stake = parseFloat(stakeInput?.value);
    if (!leg || !odds || odds < 1.01) {
        showToast(tr('Enter the odds you actually got'));
        return;
    }
    if (!stake || stake <= 0) {
        showToast(tr('Enter the stake the bookmaker accepted'));
        return;
    }
    // Partial acceptance is a real outcome: the remaining legs are re-planned
    // around the amount the book actually took, not the amount we asked for.
    state.placed[label] = { odds, stake };
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
        const res = await apiFetch('/api/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...candidateActionHeaders() },
            body: JSON.stringify({ surebet_id: id, mode: currentMode }),
        });
        const data = await res.json();
        if (!res.ok) {
            result = { state: 'unknown', at: new Date(), message: data.detail || tr('request failed ({status})', { status: res.status }) };
        } else if (data.still_profitable === true) {
            result = { state: 'ok', at: new Date(), data };
        } else if (data.still_profitable === false) {
            result = { state: 'gone', at: new Date(), data };
        } else {
            result = { state: 'unknown', at: new Date(), message: data.message || tr('the bookmakers did not all answer'), data };
        }
    } catch (e) {
        result = { state: 'unknown', at: new Date(), message: tr('network error') };
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
    // P0-4: crossing the TTL while the page is open must change what the page
    // allows, not just a number in a corner. Re-render once on the transition.
    const wasStale = document.body.classList.contains('feed-stale');
    renderFreshnessBanner();
    if (wasStale !== document.body.classList.contains('feed-stale')) {
        applyFilters();
        if (selectedSurebetId) renderSlip();
    }
    // A check that just went stale changes the banner's colour and advice.
    const check = verifyState[selectedSurebetId];
    if (check && check.state === 'ok') {
        const banner = document.querySelector('.verify-banner');
        if (banner && banner.classList.contains('verify-ok') !== verifyIsFresh(check)) renderSlip();
    }
}

// ─── Copy ─────────────────────────────────────────────────────────────────────
// A data attribute, never a JavaScript string inside an HTML attribute. The
// value is escaped for attribute context and the click handler reads it back
// from `dataset`, so a quote, backtick, parenthesis or `</script>` in a scraped
// name cannot break out of the button.
function copyAttributes(value, message) {
    // Copying a stale price is the one action that turns a historical number
    // into something a reviewer might place. Re-check stays enabled as the way
    // to establish the current price.
    // `typeof` keeps this helper executable in isolation by the XSS tests, while
    // the browser uses the real freshness state.
    const stale = typeof staleFeed === 'function' && staleFeed()
        ? ' disabled aria-disabled="true" data-stale-blocked="true"'
        : '';
    return `data-action="copy-text" data-copy="${escapeHtml(value)}" data-copy-message="${escapeHtml(message)}"${stale}`;
}

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

// A manual record of what was actually placed. It never places a bet and it
// does not change the scanner's trust model.
async function logBet(id) {
    const sb = allSurebets.find(s => s.id === id);
    if (!sb) return;
    const state = slipFor(sb);
    const check = verifyState[sb.id];
    const plan = planStakes(placementOrder(currentStakes(sb, check)), state.investment, state.placed);
    const body = {
        surebet_id: sb.id,
        mode: currentMode,
        home_team: sb.home_team,
        away_team: sb.away_team,
        market_type: sb.market_type,
        event_key: sb.event_key || '',
        kickoff: sb.kickoff || '',
        league: sb.league || '',
        sport: sb.sport || 'football',
        investment: state.investment,
        notes: tr('Logged from the bet slip'),
        legs: plan.legs.map(leg => ({
            bookmaker: leg.bookmaker,
            outcome_label: leg.outcome_label,
            odds: leg.odds,
            stake: leg.plannedStake,
            accepted_odds: leg.placed ? leg.takenOdds : 0,
            accepted_stake: leg.placed ? leg.plannedStake : 0,
            market_type: leg.market_type || sb.market_type,
            line: leg.line || '',
            settlement: leg.settlement || '',
            period: leg.period || '',
        })),
    };
    try {
        const response = await apiFetch('/api/bets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }, tr('This SureBet deployment requires an API key to log a bet.'));
        if (!response.ok) throw new Error(tr('HTTP {status}', { status: response.status }));
        showToast(tr('Bet logged. Settle it in the bet log when the legs finish.'));
    } catch (error) {
        showToast(tr('Could not log the bet: {error}', { error: error.message }));
    }
}

function copySurebetDetails(id) {
    if (staleFeed()) {
        showToast(tr('Historical prices — re-check the odds before copying.'));
        return;
    }
    const sb = allSurebets.find(s => s.id === id);
    if (!sb) return;
    const state = slipFor(sb);
    const plan = planStakes(placementOrder(currentStakes(sb, verifyState[sb.id])), state.investment, state.placed);
    const kickoff = parseKickoff(sb.kickoff);
    const lines = [
        `${formatTeamName(sb.home_team)} – ${formatTeamName(sb.away_team)}`,
        `${formatLeague(sb.league)} · ${kickoff ? formatKickoffLong(kickoff) : tr('kickoff unknown')}`,
        tr('{market} · profit {profit}% ({amount} KM on {total} KM)', { market: marketLabel(sb.market_type), profit: plan.profitPercent.toFixed(2), amount: money(plan.profit), total: money(plan.total) }),
        '',
        ...plan.legs.map((leg, index) => {
            const dest = leg.destination || {};
            const link = dest.url || '';
            const listing = sb.listings?.[leg.bookmaker];
            const listed = listing ? ` [${listing.home} – ${listing.away}]` : '';
            const where = dest.kind ? ` {${dest.kind}}` : '';
            return `${index + 1}. ${bookName(leg.bookmaker)}${listed}: ${leg.outcome_label} @ ${leg.takenOdds.toFixed(2)} → ${leg.plannedStake.toFixed(stakeRounding === 'exact' ? 2 : 0)} KM${where}${link ? ' ' + link : ''}`;
        }),
    ];
    copyText(lines.join('\n'), tr('Slip copied'));
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
    const bosnian = language === 'bs';
    // Pick the field first (live or prematch), then its Bosnian variant. Asking
    // for title_bs before title_live_bs made every live Bosnian sentence fall
    // through to the prematch one.
    const titleField = live && reason.title_live ? 'title_live' : 'title';
    const bodyField = live && reason.body_live ? 'body_live' : 'body';
    const title = (bosnian && reason[`${titleField}_bs`]) || reason[titleField];
    const body = (bosnian && reason[`${bodyField}_bs`]) || reason[bodyField];
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
            return `<button type="button" class="btn btn-secondary" data-diagnostic-action="${escapeHtml(name)}">${escapeHtml(tr(action.label))}</button>`;
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
    noCopyTable: 'The dashboard could not read its diagnostic copy, so it cannot tell you why this scan returned nothing. /api/health and /api/results hold the counts it would have used.',
    countsUnread: 'The dashboard has not read the counts for this scan yet, so it cannot tell you why there is no surebet. /api/health and /api/results hold them.',
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
        emptyState.hidden = true;
        noResults.hidden = true;
        return;
    }
    const intoNoResults = reason.panel === 'no-results';
    const panel = intoNoResults ? noResults : emptyState;
    const other = intoNoResults ? emptyState : noResults;
    panel.hidden = false;
    other.hidden = true;
    // The bookmaker row is an invitation to scan, so it only shows for the case
    // that asks for one. The stylesheet's `[hidden]` rule outranks the row's
    // `display: flex`, so the attribute is enough.
    const bookies = emptyState.querySelector('.empty-state-bookies');
    if (bookies) bookies.hidden = reason.id !== 'never_scanned';
    const cta = emptyState.querySelector('.empty-cta');
    if (cta) cta.hidden = reason.id !== 'never_scanned';
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
        noResults.hidden = true;
    }
    if (!emptyState) return;
    emptyState.hidden = false;
    const title = emptyState.querySelector('.empty-state-title');
    const body = emptyState.querySelector('.empty-state-desc');
    if (title) title.textContent = tr('No Surebets — Reason Unknown');
    if (body) body.textContent = noSurebetReasons
        ? tr(DIAGNOSTIC_UNAVAILABLE.countsUnread)
        : tr(DIAGNOSTIC_UNAVAILABLE.noCopyTable);
    const bookies = emptyState.querySelector('.empty-state-bookies');
    if (bookies) bookies.hidden = true;
    const cta = emptyState.querySelector('.empty-cta');
    if (cta) cta.hidden = true;
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
        .some(panel => panel && !panel.hidden);
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

function safeUrl(value) {
    if (!value) return '';
    try {
        const parsed = new URL(String(value), window.location.href);
        return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : '';
    } catch (e) {
        return '';
    }
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

// ─── Group evidence (P1-1) ───────────────────────────────────────────────────
// The list is always bounded by `/api/groups`; the detail call is the only
// place a full evidence trail is downloaded.
async function loadEvidence(reset = false) {
    if (reset) evidenceOffset = 0;
    const requestedMode = currentMode;
    const list = document.getElementById('evidence-list');
    const detail = document.getElementById('evidence-detail');
    if (!list) return;
    if (detail) detail.hidden = true;
    list.hidden = false;

    const status = document.getElementById('evidence-status')?.value || '';
    const sport = document.getElementById('evidence-sport')?.value || '';
    const search = (document.getElementById('evidence-search')?.value || '').trim();
    let query = `mode=${encodeURIComponent(requestedMode)}&limit=${EVIDENCE_PAGE_SIZE}&offset=${evidenceOffset}`;
    if (status) query += `&status=${encodeURIComponent(status)}`;
    if (sport) query += `&sport=${encodeURIComponent(sport)}`;
    if (search) query += `&search=${encodeURIComponent(search)}`;

    try {
        const response = await apiFetch(`/api/groups?${query}`);
        if (!response.ok) throw new Error(`groups responded ${response.status}`);
        const payload = await response.json();
        if (requestedMode !== currentMode) return;
        evidenceTotal = Number(payload.total) || 0;
        evidenceOffset = Number(payload.offset) || 0;
        renderEvidenceList(payload);
    } catch (error) {
        if (requestedMode !== currentMode) return;
        console.error('Group evidence load failed:', error);
        list.innerHTML = '<div class="empty-state"><h2 class="empty-state-title">Could not load group evidence.</h2><p class="empty-state-desc">The API did not return a group page.</p></div>';
        setText('evidence-page', '—');
    }
}

function renderEvidenceList(payload) {
    const list = document.getElementById('evidence-list');
    if (!list) return;
    const groups = payload.groups || [];
    const total = Number(payload.total) || 0;
    const offset = Number(payload.offset) || 0;
    const count = Number(payload.count) || groups.length;
    setText('evidence-page', total ? `${offset + 1}–${offset + count} of ${total}` : '0 groups');
    if (!groups.length) {
        list.innerHTML = `<div class="empty-state"><h2 class="empty-state-title">${escapeHtml(tr('No matching groups.'))}</h2><p class="empty-state-desc">${escapeHtml(tr('Change the filters or run a scan for this feed.'))}</p></div>`;
        return;
    }
    list.innerHTML = groups.map(group => {
        const bookmakers = (group.bookmakers || []).map(book => bookName(book.bookmaker)).join(' · ');
        const reasons = (group.reasons || []).slice(0, 4).map(reason => reasonLabel(reason)).join(', ');
        return `<button type="button" class="evidence-row" data-action="evidence-open" data-group-id="${escapeHtml(group.group_id)}">
            <span class="evidence-row-title">${escapeHtml(group.canonical_match || tr('unknown fixture'))}</span>
            <span class="evidence-row-status" data-state="${escapeHtml(group.status || '')}">${escapeHtml(tr(group.status || 'unknown'))}</span>
            <span class="evidence-row-meta">${escapeHtml(formatLeague(group.league))} · ${escapeHtml(String(group.sport || 'football'))} · ${escapeHtml(bookmakers || tr('no books'))}</span>
            <span class="evidence-row-meta">${escapeHtml(reasons || tr('no gate reasons'))}</span>
        </button>`;
    }).join('');
}

function setEvidenceOffset(offset) {
    const lastPageStart = evidenceTotal
        ? Math.floor((evidenceTotal - 1) / EVIDENCE_PAGE_SIZE) * EVIDENCE_PAGE_SIZE
        : 0;
    evidenceOffset = Math.max(0, Math.min(offset, lastPageStart));
    loadEvidence();
}

function showEvidenceList() {
    const list = document.getElementById('evidence-list');
    const detail = document.getElementById('evidence-detail');
    if (list) list.hidden = false;
    if (detail) { detail.hidden = true; detail.innerHTML = ''; }
}

async function loadEvidenceDetail(groupId) {
    const list = document.getElementById('evidence-list');
    const detail = document.getElementById('evidence-detail');
    if (!list || !detail || groupId == null) return;
    const requestedMode = currentMode;
    try {
        const response = await apiFetch(`/api/groups/${encodeURIComponent(groupId)}?mode=${encodeURIComponent(requestedMode)}`);
        if (!response.ok) throw new Error(tr('group responded {status}', { status: response.status }));
        const payload = await response.json();
        if (requestedMode !== currentMode) return;
        renderEvidenceDetail(payload.group);
        list.hidden = true;
        detail.hidden = false;
    } catch (error) {
        if (requestedMode !== currentMode) return;
        console.error('Group detail load failed:', error);
        list.hidden = true;
        detail.hidden = false;
        detail.innerHTML = `<div class="empty-state"><h2 class="empty-state-title">${escapeHtml(tr('Could not load this group.'))}</h2><p class="empty-state-desc">${escapeHtml(tr('The group may have been replaced by a new scan.'))}</p></div>`;
    }
}

function renderEvidenceDetail(group) {
    const detail = document.getElementById('evidence-detail');
    if (!detail || !group) return;
    const books = (group.bookmakers || []).map(book =>
        `<li><b>${escapeHtml(bookName(book.bookmaker))}</b> · ${escapeHtml(tr('event'))} ${escapeHtml(book.event_id || '—')} · ${escapeHtml(tr('{count} markets', { count: String(book.num_markets || 0) }))}</li>`
    ).join('');
    const evidence = (group.evidence || []).map(item => {
        const confidence = Number(item.confidence);
        const confidenceText = Number.isFinite(confidence) ? tr(' · confidence {value}', { value: confidence.toFixed(2) }) : '';
        const league = (item.league_pair || []).length ? tr(' · league {leagues}', { leagues: item.league_pair.join(' / ') }) : '';
        return `<li><b>${escapeHtml(tr(item.rule || 'evidence'))}</b> <span class="evidence-reason">${escapeHtml(item.reason || '')}${escapeHtml(confidenceText)}${escapeHtml(league)}</span></li>`;
    }).join('');
    detail.innerHTML = `
        <div class="evidence-detail-head">
            <button type="button" class="btn btn-small btn-secondary" data-action="evidence-close">← ${escapeHtml(tr('All groups'))}</button>
            <h3>${escapeHtml(group.canonical_match || tr('unknown fixture'))}</h3>
            <span class="evidence-row-status" data-state="${escapeHtml(group.status || '')}">${escapeHtml(tr(group.status || 'unknown'))}</span>
        </div>
        <div class="evidence-row-meta">${escapeHtml(formatLeague(group.league))} · ${escapeHtml(String(group.sport || 'football'))} · ${escapeHtml(group.kickoff || tr('kickoff unknown'))}</div>
        <h3>${escapeHtml(tr('Bookmakers'))}</h3>
        <ul>${books || `<li>${escapeHtml(tr('none'))}</li>`}</ul>
        <h3>${escapeHtml(tr('Gate evidence'))}</h3>
        <ul>${evidence || `<li>${escapeHtml(tr('none recorded'))}</li>`}</ul>
    `;
}

function renderCandidatesMessage(message) {
    const list = document.getElementById('candidates-list');
    if (!list) return;
    list.innerHTML = `
        <div class="empty-state">
            <h2 class="empty-state-title">${escapeHtml(message)}</h2>
            <p class="empty-state-desc">${escapeHtml(tr('The review queue could not be refreshed. Try again in a moment.'))}</p>
        </div>
    `;
}

// The queue is served one bounded page at a time: a full scan can queue five
// figures, and this tab re-renders every poll.
const CANDIDATE_PAGE_SIZE = 100;

function candidateActionHeaders(headers = {}) {
    const merged = { ...headers };
    if (candidateApiKey) merged['X-API-Key'] = candidateApiKey;
    return merged;
}

async function apiFetch(url, options = {}, promptText = 'This SureBet deployment requires an API key.') {
    const send = () => fetch(url, { ...options, headers: candidateActionHeaders(options.headers || {}) });
    const keyUsed = candidateApiKey;
    let response = await send();
    if (response.status !== 401) return response;
    if (candidateApiKey && candidateApiKey !== keyUsed) return send();
    // A background poll does not re-ask after a cancel; a click (a POST) does.
    if (candidateApiKeyDeclined && !options.method) return response;
    const entered = window.prompt(tr(promptText));
    if (entered && entered.trim()) {
        candidateApiKey = entered.trim();
        candidateApiKeyDeclined = false;
        try { sessionStorage.setItem('apiKey', candidateApiKey); } catch (e) { /* storage unavailable */ }
        response = await send();
    } else {
        candidateApiKeyDeclined = true;
    }
    return response;
}

async function candidateListFetch(url) {
    const send = () => fetch(url, { headers: candidateActionHeaders() });
    let response = await send();
    if (response.status === 401 && !candidateApiKey) {
        const entered = window.prompt(tr('This SureBet deployment requires an API key to read the review queue.'));
        if (entered && entered.trim()) {
            candidateApiKey = entered.trim();
            response = await send();
        }
    }
    return response;
}

const SWEEP_MAX_CALLS = 100;
// Mirrors scripts/sweep_links.py: ten waits, then give up and say why.
const SWEEP_MAX_RATE_LIMIT_WAITS = 10;

function sweepDelay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// A sweep is just repeated verify-links calls. The server owns the cursor, so
// this loop stops when it reports remaining=0; a 429 is waited out, never
// bypassed. One completed report is posted to /api/link-sweeps, even when the
// sweep failed — the measurement matters most when it did.
async function sweepLinks() {
    if (sweepState.running) return;
    const bookEl = document.getElementById('sweep-book');
    const modeEl = document.getElementById('sweep-mode');
    const statusEl = document.getElementById('sweep-status');
    const bookmaker = bookEl ? bookEl.value : '';
    const mode = modeEl ? modeEl.value : 'prematch';
    if (!bookmaker) {
        if (statusEl) statusEl.textContent = tr('Pick a book with a declared event route first.');
        return;
    }
    sweepState.running = true;
    const startedAt = new Date().toISOString();
    const totals = {
        bookmaker, mode, calls: 0, available: 0, checked: 0,
        verified: 0, failed: 0, errored: 0, unchecked: 0,
        remaining: 0, last_next_offset: 0,
    };
    let status = 'budget_exhausted';
    let httpError = '';
    let rateLimitWaits = 0;
    const callsDetail = [];
    try {
        while (totals.calls < SWEEP_MAX_CALLS) {
            const query = `bookmaker=${encodeURIComponent(bookmaker)}&mode=${encodeURIComponent(mode)}&limit=5`;
            const response = await apiFetch(
                `/api/verify-links?${query}`,
                { method: 'POST' },
                'This SureBet deployment requires an API key to sweep links.'
            );
            if (response.status === 429) {
                rateLimitWaits += 1;
                if (rateLimitWaits > SWEEP_MAX_RATE_LIMIT_WAITS) {
                    status = 'rate_limited';
                    httpError = 'rate limit did not clear after 10 waits';
                    break;
                }
                if (statusEl) statusEl.textContent = tr('Rate limited by the server — waiting before the next check…');
                await sweepDelay(5000);
                continue;
            }
            if (!response.ok) throw new Error(tr('verify-links returned {status}', { status: response.status }));
            const body = await response.json();
            totals.calls += 1;
            totals.available = Math.max(totals.available, Number(body.available || 0));
            for (const key of ['checked', 'verified', 'failed', 'errored', 'unchecked']) {
                totals[key] += Number(body[key] || 0);
            }
            totals.remaining = Number(body.remaining || 0);
            totals.last_next_offset = Number(body.next_offset || 0);
            callsDetail.push({
                status: body.status,
                checked: Number(body.checked || 0),
                verified: Number(body.verified || 0),
                failed: Number(body.failed || 0),
                errored: Number(body.errored || 0),
                unchecked: Number(body.unchecked || 0),
                remaining: totals.remaining,
            });
            if (statusEl) {
                statusEl.textContent = tr('Checked {checked} · verified {verified} · failed {failed} · errored {errored} · remaining {remaining}', totals);
            }
            if (body.status === 'skipped' || totals.remaining === 0) {
                status = body.status === 'skipped' ? 'skipped' : 'converged';
                break;
            }
            await sweepDelay(1500);
        }
    } catch (error) {
        status = 'request_failed';
        httpError = error.message;
        if (statusEl) statusEl.textContent = tr('Sweep failed: {error}', { error: error.message });
    }
    const report = {
        ...totals, status, http_error: httpError,
        started_at: startedAt, ended_at: new Date().toISOString(),
        rate_limit_waits: rateLimitWaits, calls_detail: callsDetail,
    };
    try {
        const reportResponse = await apiFetch(
            '/api/link-sweeps',
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(report),
            },
            'This SureBet deployment requires an API key to save the sweep report.'
        );
        if (!reportResponse.ok) throw new Error(tr('HTTP {status}', { status: reportResponse.status }));
        if (statusEl && status !== 'request_failed') {
            statusEl.textContent = tr('Sweep {status}: {checked} checked, {verified} verified, {failed} failed, {errored} errored.', { status, checked: totals.checked, verified: totals.verified, failed: totals.failed, errored: totals.errored });
        }
    } catch (error) {
        if (statusEl) statusEl.textContent = tr('Sweep failed: {error}', { error: error.message });
    } finally {
        sweepState.running = false;
    }
}

async function loadCandidates() {
    const requestedMode = currentMode;
    try {
        // Only the pairs a mapping can clear. A full scan queues thousands, and
        // most are refused for a league gap, a kickoff no decision moves or a
        // name pair below the reviewed-alias floor: a card there promises a fix
        // that does not exist. `closeable_only` includes both team aliases and
        // league mappings (N2-3); the server still reports the full `total`, the
        // alias-only `actionable_total` and the closeable `closeable_total` so
        // the tab can say exactly what it is not showing.
        const response = await candidateListFetch(
            `/api/candidates?closeable_only=true&limit=${CANDIDATE_PAGE_SIZE}&offset=0&mode=${requestedMode}`
        );
        if (response.ok === false) throw new Error(tr('Candidate request failed ({status})', { status: response.status }));
        const data = await response.json();
        if (requestedMode !== currentMode) return;
        renderCandidates(
            Array.isArray(data.candidates) ? data.candidates : [],
            Number(data.total) || 0,
            Number(data.closeable_total ?? data.actionable_total) || 0,
            data.blocker_counts || {},
            data.remediation_counts || {},
            {
                found: Number(data.found) || 0,
                dropped: Number(data.dropped) || 0,
                cap: Number(data.cap) || 0,
            },
        );
    } catch (error) {
        console.error('Candidates load failed:', error);
        if (requestedMode !== currentMode) return;
        renderCandidatesMessage(tr('Could not load candidates.'));
    }
}

function renderCandidates(candidates, total, closeableTotal, blockerCounts = {}, remediationCounts = {}, capInfo = {}) {
    const list = document.getElementById('candidates-list');
    const count = document.getElementById('review-count');
    const queue = Array.isArray(candidates) ? candidates : [];
    if (!list) return;
    if (count) count.textContent = closeableTotal;
    // Keep only selections that are still on the page.

    if (!queue.length) {
        // Two different nothings: an empty filtered page can still sit on top
        // of a large queue no human decision can move.
        const nothingQueued = total === 0;
        list.innerHTML = `
            <div class="empty-state">
                <h2 class="empty-state-title">${escapeHtml(nothingQueued ? tr('No unresolved pairings.') : tr('No actionable pairings.'))}</h2>
                <p class="empty-state-desc">${escapeHtml(nothingQueued
                    ? tr('The ledger has not left any pairing without a terminal decision.')
                    : tr('{count} pairing(s) are informational; the ledger learns them automatically.', { count: total }))}</p>
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

    // M2-4: the queue is capped, so the tab says so. A reviewer must never read
    // a retained page as the whole queue.
    const droppedByCap = Number(capInfo.dropped) || 0;
    const capNote = droppedByCap > 0
        ? `<p class="candidates-page-note">${escapeHtml(tr('The review queue keeps {retained} of {found} pairings found this scan (cap {cap}); {dropped} lower-priority pairings were not retained.', { retained: total, found: Number(capInfo.found) || total, cap: Number(capInfo.cap) || 0, dropped: droppedByCap }))}</p>`
        : '';
    const pageNote = total > queue.length
        ? `<p class="candidates-page-note">${escapeHtml(tr('Showing {shown} of {closeable} pairings a mapping can close, of {total} queued in total. The rest cannot be closed by a team alias or league mapping.', { shown: queue.length, closeable: closeableTotal, total }))}</p>`
        : '';
    const blockers = {
        alias: Number(blockerCounts.alias) || 0,
        league: Number(blockerCounts.league) || 0,
        link: Number(blockerCounts.link) || 0,
        other: Number(blockerCounts.other) || 0,
    };
    const remediation = {
        alias: Number(remediationCounts.alias) || 0,
        league: Number(remediationCounts.league) || 0,
        both: Number(remediationCounts['alias+league']) || 0,
        systemLink: Number(remediationCounts.system_link) || 0,
        none: Number(remediationCounts.none) || 0,
    };
    const blockerNote = total
        ? `<p class="candidates-page-note">${escapeHtml(tr('Queue: {alias} actionable · {league} league-blocked · {link} link-pending · {other} informational. Closeable by a proposed mapping: {rAlias} alias · {rLeague} league · {rBoth} alias+league · {rLink} system-link · {rNone} none of {total}.', { alias: blockers.alias, league: blockers.league, link: blockers.link, other: blockers.other, rAlias: remediation.alias, rLeague: remediation.league, rBoth: remediation.both, rLink: remediation.systemLink, rNone: remediation.none, total }))}</p>`
        : '';

    list.innerHTML = capNote + blockerNote + pageNote + orderedCandidates.map((candidate) => {
        const id = escapeHtml(candidate.id || '');
        const homeTeam = escapeHtml(formatTeamName(candidate.home_team || tr('Unknown')));
        const awayTeam = escapeHtml(formatTeamName(candidate.away_team || tr('Unknown')));
        const league = escapeHtml(formatLeague(candidate.league || tr('Unknown league')));
        const kickoffDate = candidate.kickoff ? parseKickoff(candidate.kickoff) : null;
        const kickoff = kickoffDate ? escapeHtml(formatKickoff(kickoffDate)) : tr('Kickoff unknown');
        const bookmakers = (Array.isArray(candidate.bookmakers) ? candidate.bookmakers : [])
            .map(bookmaker => escapeHtml(bookName(bookmaker)))
            .join(' / ') || tr('No bookmakers recorded');
        const confidence = Math.round(candidateConfidence(candidate.ai_confidence) * 100);
        const nameScore = Math.round(Number(candidate.name_score) || 0);
        const aiNegative = candidate.ai_same_event === false;
        const aiReason = candidate.ai_reason ? escapeHtml(candidate.ai_reason) : '';
        const aiVerdict = aiNegative
            ? `<p class="candidate-ai"><strong>${escapeHtml(tr('AI verdict:'))}</strong> <span class="candidate-ai-negative">${escapeHtml(tr('not the same event'))}</span> ${aiReason}</p>`
            : (aiReason ? `<p class="candidate-ai"><strong>${escapeHtml(tr('AI suggestion ({confidence}%):', { confidence }))}</strong> ${aiReason} <span class="candidate-ai-note">${escapeHtml(tr('Suggestion only — a human must decide.'))}</span></p>` : '');
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
            : `<li class="candidate-position candidate-position-none">${escapeHtml(tr('No cross-bookmaker names recorded — run a scan to regenerate this candidate'))}</li>`;
        const searchUrl = fixtureSearchUrl(candidate);
        const readOnlyNote = tr(candidate.link_blocked
            ? 'The ledger learns this pairing automatically; the link half is a separate machine check.'
            : 'The ledger learns this pairing automatically; this card is informational.');
        const reasons = Array.isArray(candidate.rule_rejections) ? candidate.rule_rejections : [];
        const reasonItems = reasons.length
            ? reasons.map(reason => {
                const rawCode = String(reason);
                const label = reasonLabel(rawCode) || tr(REASON_UNKNOWN_LABEL);
                return `<li class="candidate-reason" title="${escapeHtml(rawCode)}">${escapeHtml(label)}</li>`;
            }).join('')
            : `<li class="candidate-reason candidate-reason-none">${escapeHtml(tr('No reason recorded'))}</li>`;
        const candidateRemediation = candidate.remediation || null;
        const actionKey = candidateRemediation ? String(candidateRemediation.action || 'none') : 'none';
        const actionLabel = tr(REMEDIATION_LABELS[actionKey] || REMEDIATION_LABELS.none);
        const proposalItems = candidateRemediation && Array.isArray(candidateRemediation.proposals)
            ? candidateRemediation.proposals.map(proposal => {
                const kind = tr(proposal.kind === 'league_equivalence' ? 'league mapping' : 'team alias');
                const ledger = proposal.ledger_status && proposal.ledger_status !== 'absent'
                    ? `${tr(proposal.ledger_status)} ${(Number(proposal.ledger_confidence) * 100).toFixed(0)}%`
                    : tr('absent from ledger');
                return `<li class="candidate-proposal" title="${escapeHtml(`${proposal.entry} — ledger ${ledger}; proposal only`)}">`
                    + `<span class="candidate-proposal-kind">${escapeHtml(kind)}</span> `
                    + `<span class="mono">${escapeHtml(proposal.entry || '')}</span> `
                    + `<span class="candidate-proposal-ledger">ledger ${escapeHtml(ledger)}</span></li>`;
            }).join('')
            : '';
        const remediationBlock = candidateRemediation
            ? `<div class="candidate-remediation" data-action="${escapeHtml(actionKey)}">
                    <p class="candidate-remediation-head"><span class="candidate-remediation-action">${escapeHtml(actionLabel)}</span> <span class="candidate-proposal-only">${escapeHtml(tr('proposal only — nothing is applied'))}</span></p>
                    ${proposalItems ? `<ul class="candidate-proposals" aria-label="Proposed mappings">${proposalItems}</ul>` : ''}
                </div>`
            : '';
        return `
            <article class="candidate-card" data-id="${id}" data-confidence="${confidence}"${aiNegative ? ' data-ai-verdict="negative"' : ''}>
                <div class="candidate-body">
                    <div class="candidate-card-header">
                        <div class="candidate-teams"><span>${homeTeam}</span> <span class="candidate-vs">vs</span> <span>${awayTeam}</span></div>
                        <span class="name-score" data-score="${nameScore >= 85 ? 'high' : nameScore >= 65 ? 'mid' : 'low'}" title="${escapeHtml(tr('How alike the least-alike name pair is'))}">${escapeHtml(tr('{score}% alike', { score: nameScore }))}</span>
                    </div>
                    <div class="candidate-meta">${league} · ${kickoff} · ${bookmakers}</div>
                    <ul class="candidate-positions" aria-label="How the two bookmakers spell each team">${positionItems}</ul>
                    <ul class="candidate-reasons" aria-label="Why the certainty gate refused">${reasonItems}</ul>
                    ${remediationBlock}
                    ${aiVerdict}
                    <p class="candidate-approval-note">${escapeHtml(readOnlyNote)}</p>
                </div>
                <div class="candidate-actions">
                    <a class="btn btn-secondary btn-small" href="${escapeHtml(safeUrl(searchUrl))}" target="_blank" rel="noopener noreferrer"
                       title="${escapeHtml(tr('Search the web for this fixture'))}">${escapeHtml(tr('Check on the web ↗'))}</a>
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
        const res = await apiFetch('/api/history', { headers: candidateActionHeaders() });
        if (!res.ok) throw new Error(tr('request failed ({status})', { status: res.status }));
        const data = await res.json();
        const entries = data.entries || [];
        if (entries.length === 0) {
            body.innerHTML = `<tr><td colspan="7" class="history-empty">${escapeHtml(tr('No scans yet'))}</td></tr>`;
            return;
        }
        body.innerHTML = entries.map(e => {
            const time = e.scan_time ? escapeHtml(parseKickoff(e.scan_time).toLocaleString()) : '—';
            const errs = (e.errors || []).length;
            const mode = e.mode === 'live' ? `<span class="tag tag-live">${escapeHtml(tr('Live'))}</span>` : `<span class="tag">${escapeHtml(tr('Upcoming'))}</span>`;
            return `<tr>
                <td>${mode}</td>
                <td>${time}</td>
                <td class="mono">${formatCount(e.total_matches)}</td>
                <td class="mono">${formatCount(e.match_groups)}</td>
                <td class="mono${e.surebets_found > 0 ? ' good' : ''}">${formatCount(e.surebets_found)}</td>
                <td class="mono" title="${escapeHtml(tr('actionable / queued after this scan'))}">${formatCount(e.candidate_actionable)} / ${formatCount(e.candidate_queue)}</td>
                <td class="mono${errs > 0 ? ' bad' : ''}" title="${escapeHtml((e.errors || []).join(' | '))}">${errs}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        body.innerHTML = `<tr><td colspan="7" class="history-empty">${escapeHtml(tr('Failed to load history'))}</td></tr>`;
    }
}

// ─── UI helpers ───────────────────────────────────────────────────────────────
function showScanProgress() {
    document.getElementById('scan-progress').hidden = false;
    document.getElementById('scan-bar').style.setProperty('--scan-progress', '5');
}

function hideScanProgress() {
    document.getElementById('scan-progress').hidden = true;
}

function setStatus(state, text, render) {
    const pill = document.getElementById('status-pill');
    if (pill) pill.className = 'status-pill ' + state;
    statusMessage = { text: text || '', render: typeof render === 'function' ? render : null };
    applyStatusText();
}

// The status line is live state, not a fixed label. It owns its text instead of
// a data-i18n attribute, so a language switch cannot reset a running scan back
// to "Ready".
function applyStatusText() {
    const el = document.getElementById('status-text');
    if (!el) return;
    delete el.dataset.i18n;
    el.textContent = statusMessage.render ? statusMessage.render() : (statusMessage.text || tr('Ready'));
}

function showError(msg) {
    document.getElementById('error-banner-text').textContent = msg;
    document.getElementById('error-banner').hidden = false;
}

function hideError() {
    document.getElementById('error-banner').hidden = true;
}

async function shutdownServer() {
    if (!window.confirm(tr('Stop the server? Scans stop and this page goes offline.'))) return;
    const btn = document.getElementById('shutdown-btn');
    btn.disabled = true;
    try {
        const res = await apiFetch('/api/shutdown', { method: 'POST', headers: candidateActionHeaders() });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || tr('HTTP {status}', { status: res.status }));
        }
    } catch (e) {
        btn.disabled = false;
        showError(tr('Could not stop the server: {error}', { error: e.message }));
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

function applyDynamicStyles(root) {
    if (!root || !root.querySelectorAll) return;
    // Colours and progress widths are set as CSS custom properties through the
    // CSSOM. They are never serialised into an inline style attribute, so the
    // CSP needs no 'unsafe-inline' for styles.
    root.querySelectorAll('[data-book-color]').forEach(element => {
        element.style.setProperty('--color', bookColor(element.dataset.bookColor));
    });
    root.querySelectorAll('[data-progress]').forEach(element => {
        const value = Number(element.dataset.progress);
        element.style.setProperty('--progress', String(Number.isFinite(value) ? value : 0));
    });
}

function bookColor(id) {
    return bookmakersConfig[id]?.color || BOOKMAKER_COLORS[id] || '#888';
}

// Advisory only: the profile never changes the certainty gate, the price-source
// rule or the stake math. It tells the operator what kind of book a leg is at.
function bookRisk(id) {
    const cfg = bookmakersConfig?.[id] || {};
    return {
        profile: cfg.risk_profile || 'unknown',
        typical: cfg.typical_max_stake_note || tr('No typical stake recorded.'),
        limit: cfg.limit_risk || tr('Unknown risk profile: check the book limit policy.'),
    };
}

function riskProfileLabel(profile) {
    return tr(({ sharp: 'Sharp', soft: 'Soft book', exchange: 'Exchange', unknown: 'Unknown risk' })[profile] || 'Unknown risk');
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
    if (sec < 60) return tr('{count}s ago', { count: sec });
    const min = Math.floor(sec / 60);
    if (min < 60) return tr('{count}m ago', { count: min });
    const hr = Math.floor(min / 60);
    if (hr < 24) return tr('{count}h ago', { count: hr });
    return dt.toLocaleDateString();
}

function formatKickoff(dt) {
    if (!dt || isNaN(dt)) return '';
    const time = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const today = new Date();
    const tomorrow = new Date(today.getTime() + 86400000);
    if (dt.toDateString() === today.toDateString()) return tr('Today {time}', { time });
    if (dt.toDateString() === tomorrow.toDateString()) return tr('Tomorrow {time}', { time });
    return `${dt.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} ${time}`;
}

function formatKickoffLong(dt) {
    const hours = (dt.getTime() - Date.now()) / 3600000;
    const rel = hours > 0 && hours < 48 ? tr(' ({when})', { when: hours < 1 ? tr('{count} min', { count: Math.round(hours * 60) }) : tr('{count} h', { count: Math.round(hours) }) }) : '';
    return formatKickoff(dt) + rel;
}

// Upper-case the first letter of each word. `\b\w` is ASCII-only, so it treated
// "Željezničar" as the words "Ž", "eljezni", "ar" and printed "ŽEljezničAr".
function capitalizeWords(text) {
    return text.replace(/(^|[^\p{L}\p{M}\p{N}'’])(\p{L})/gu, (_, lead, letter) => lead + letter.toUpperCase());
}

function formatTeamName(name) {
    if (!name) return tr('Unknown');
    return capitalizeWords(name.replace(/_/g, ' ')).trim();
}

function formatLeague(league) {
    if (!league) return '';
    return capitalizeWords(league.replace(/_/g, ' ')).trim();
}

function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

async function refreshDiagnostics() {
    // The review queue rides the same cadence as the health poll.
    await Promise.all([loadHealth(), loadCandidates()]);
}

function coveragePolyline(points, key) {
    if (!Array.isArray(points) || !points.length) return '';
    const values = points.map(point => Math.max(0, Number(point?.[key]) || 0));
    const max = Math.max(1, ...values);
    const width = 240;
    const height = 44;
    return points.map((point, index) => {
        const x = points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
        const y = height - (values[index] / max) * (height - 4) - 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
}

function renderRemediation(data) {
    const panel = document.getElementById('remediation-panel');
    const list = document.getElementById('remediation-groups');
    if (!panel || !list) return;
    const remediation = data?.candidate_remediation?.[currentMode] || {};
    const groups = Array.isArray(remediation.groups) ? remediation.groups : [];
    const points = Array.isArray(data?.pairing_trend?.[currentMode])
        ? data.pairing_trend[currentMode]
        : [];
    if (!groups.length && !points.length) {
        panel.hidden = true;
        list.innerHTML = '';
        return;
    }
    panel.hidden = false;
    const counts = remediation.counts || {};
    const total = Number(remediation.total) || 0;
    const closeable = Number(remediation.closeable) || 0;
    setText(
        'remediation-summary',
        tr('{mode}: {closeable}/{total} closeable · alias {alias} · league {league} · alias+league {both} · system-link {link} · none {none}', {
            mode: currentMode,
            closeable,
            total,
            alias: Number(counts.alias) || 0,
            league: Number(counts.league) || 0,
            both: Number(counts['alias+league']) || 0,
            link: Number(counts.system_link) || 0,
            none: Number(counts.none) || 0,
        })
    );
    const note = document.getElementById('remediation-note');
    if (note) note.textContent = tr('Queue size is a diagnostic, not a coverage-progress claim. A proposal is never applied here.');
    list.innerHTML = groups.length
        ? groups.map(row => {
            const action = tr(REMEDIATION_LABELS[row.action] || row.action || 'unknown');
            const rawReasons = Array.isArray(row.reasons) ? row.reasons : [];
            const reasons = rawReasons.map(code => reasonLabel(code)).join(', ')
                || 'no reason recorded';
            const share = (Number(row.share || 0) * 100).toFixed(1);
            return `<li class="remediation-group" data-action="${escapeHtml(String(row.action || 'none'))}" title="${escapeHtml(rawReasons.join(', '))}">`
                + `<span class="remediation-count mono">${Number(row.count) || 0}</span>`
                + `<span class="remediation-action">${escapeHtml(action)}</span>`
                + `<span class="remediation-meta">${escapeHtml(row.book_pair || '')} · ${escapeHtml(row.league || '')} · ${escapeHtml(reasons)}</span>`
                + `<span class="remediation-share mono">${escapeHtml(tr('{share}% of {total}', { share, total }))}</span>`
                + `</li>`;
        }).join('')
        : `<li class="remediation-empty">${escapeHtml(tr('No blocked candidates in this queue.'))}</li>`;
    const line = document.getElementById('remediation-line');
    if (line) line.setAttribute('points', coveragePolyline(points, 'strict_misses'));
    const last = points[points.length - 1] || {};
    setText(
        'remediation-trend-summary',
        points.length
            ? tr('{misses} miss(es) of {listings} listing(s) · {rate}%', { misses: Number(last.strict_misses) || 0, listings: Number(last.matches) || 0, rate: (Number(last.strict_miss_rate || 0) * 100).toFixed(2) })
            : tr('no scan yet')
    );
}

function renderCoverageTrend(data) {
    const box = document.getElementById('coverage-trend');
    if (!box) return;
    const points = Array.isArray(data?.coverage_trend?.[currentMode])
        ? data.coverage_trend[currentMode]
        : [];
    if (!points.length) {
        box.hidden = true;
        return;
    }
    box.hidden = false;
    const flags = document.getElementById('coverage-line-flags');
    const unmapped = document.getElementById('coverage-line-unmapped');
    if (flags) flags.setAttribute('points', coveragePolyline(points, 'flag_count'));
    if (unmapped) unmapped.setAttribute('points', coveragePolyline(points, 'unmapped_rows'));
    const last = points[points.length - 1] || {};
    const mapping = data?.mapping_coverage?.[currentMode] || {};
    const ratio = mapping.coverage == null ? '—' : `${(Number(mapping.coverage) * 100).toFixed(1)}%`;
    const rows = `${Number(mapping.numerator) || 0}/${Number(mapping.denominator) || 0}`;
    setText('coverage-trend-summary', tr('{mode}: {flags} flag(s) · {unmapped} unmapped rows · mapped {rows} ({ratio})', { mode: currentMode, flags: Number(last.flag_count) || 0, unmapped: Number(last.unmapped_rows) || 0, rows, ratio }));
}

function formatBytes(value) {
    if (value == null) return 'n/a';
    const bytes = Number(value);
    if (!Number.isFinite(bytes)) return 'n/a';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderScanCost(data) {
    const box = document.getElementById('scan-cost');
    const body = document.getElementById('scan-cost-body');
    if (!box || !body) return;
    const report = data?.scan_cost?.[currentMode] || {};
    const books = report.books || {};
    const names = Object.keys(books).sort();
    if (!names.length) {
        box.hidden = true;
        body.innerHTML = '';
        return;
    }
    box.hidden = false;
    const totals = report.totals || {};
    const fmt = (value, suffix = '') => (
        value == null || !Number.isFinite(Number(value))
            ? tr('n/a')
            : `${Number(value).toFixed(2)}${suffix}`
    );
    setText('scan-cost-summary', tr('{mode}: {books} book(s) · {wall} wall · {requests} requests · {matches} matches · {per} s/match', { mode: currentMode, books: Number(totals.books) || names.length, wall: fmt(totals.wall_seconds, 's'), requests: fmt(totals.requests), matches: Number(totals.matches) || 0, per: fmt(totals.seconds_per_match, 's') }));
    body.innerHTML = names.map(name => {
        const book = books[name] || {};
        const missing = (book.missing || []).join('; ');
        const perMatch = Number(book.matches) > 0
            ? Number(book.wall_seconds) / Number(book.matches)
            : null;
        return `<tr title="${escapeHtml(missing)}">`
            + `<td>${escapeHtml(name)}</td>`
            + `<td>${escapeHtml(book.outcome || '?')}</td>`
            + `<td>${fmt(book.wall_seconds, 's')}</td>`
            + `<td>${fmt(book.browser_seconds, 's')}</td>`
            + `<td>${fmt(book.requests)}</td>`
            + `<td>${formatBytes(book.bytes)}</td>`
            + `<td>${Number(book.matches) || 0}</td>`
            + `<td>${fmt(perMatch, 's')}</td>`
            + '</tr>';
    }).join('');
}

// ─── Paper ledger (N2-1) ──────────────────────────────────────────────────────
// Read-mostly. Every number is shown with its denominator, and no control here
// can place a bet or copy a live slip.
function paperQueryString(params) {
    return Object.entries(params)
        .filter(([, value]) => value !== '' && value != null)
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
        .join('&');
}

function paperQuery() {
    return paperQueryString({
        days: '30',
        limit: String(PAPER_PAGE_SIZE),
        offset: String(paperState.oppOffset),
        run_mode: paperState.runMode,
        feed_mode: paperState.feedMode,
    });
}

function paperPositionQuery() {
    return paperQueryString({
        days: '30',
        limit: String(PAPER_PAGE_SIZE),
        offset: String(paperState.posOffset),
        feed_mode: paperState.feedMode,
        status: paperState.status,
    });
}

function paperPageLabel(offset, total) {
    if (!total) return tr('0 of 0');
    const first = Math.min(total, offset + 1);
    const last = Math.min(total, offset + PAPER_PAGE_SIZE);
    return tr('{first}–{last} of {total}', { first, last, total });
}

function paperExportUrl() {
    return '/api/paper/export.csv?' + paperQueryString({
        days: '30',
        run_mode: paperState.runMode,
        feed_mode: paperState.feedMode,
        status: paperState.status,
    });
}

function updatePaperExportLink() {
    const link = document.getElementById('paper-export');
    if (!link) return;
    link.href = paperExportUrl();
}

// Downloads carry the API key in a header, never in the URL: a link or a
// navigation cannot attach sessionStorage, so the fetch is the only way an
// API-key deployment can export anything.
async function downloadProtected(url, filename, promptText) {
    try {
        const res = await apiFetch(
            url,
            {},
            promptText || tr('This SureBet deployment requires an API key to download this file.')
        );
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || tr('HTTP {status}', { status: res.status }));
        }
        const blob = await res.blob();
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
        showError(tr('Could not download the file: {error}', { error: error.message }));
    }
}

function exportPaperCsv() {
    return downloadProtected(paperExportUrl(), 'bh-arb-paper.csv');
}

function exportBetsCsv() {
    return downloadProtected('/api/bets/export.csv?days=30', 'bh-arb-bets.csv');
}

async function openProtectedReport(url) {
    const popup = window.open('', '_blank');
    try {
        const res = await apiFetch(url);
        if (!res.ok) throw new Error(tr('HTTP {status}', { status: res.status }));
        const text = await res.text();
        const objectUrl = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
        if (popup) popup.location.href = objectUrl;
        else downloadProtected(url, 'bh-arb-report.json');
        setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
    } catch (error) {
        if (popup) popup.close();
        showError(tr('Could not open the report: {error}', { error: error.message }));
    }
}

async function loadPaper() {
    try {
        const [summaryRes, oppRes, posRes] = await Promise.all([
            apiFetch('/api/paper/summary?days=30'),
            apiFetch(`/api/paper/opportunities?${paperQuery()}`),
            apiFetch(`/api/paper/positions?${paperPositionQuery()}`),
        ]);
        if (!summaryRes.ok || !oppRes.ok || !posRes.ok) {
            throw new Error(`paper ledger returned ${summaryRes.status}/${oppRes.status}/${posRes.status}`);
        }
        const summary = await summaryRes.json();
        const opportunities = await oppRes.json();
        const positions = await posRes.json();
        renderPaperSummary(summary);
        renderPaperOpportunities(opportunities);
        renderPaperPositions(positions);
        updatePaperExportLink();
    } catch (error) {
        console.warn('Paper ledger load failed:', error);
        setText('paper-store', tr('Paper store: could not load the ledger.'));
    }
}

function renderPaperSummary(summary) {
    const data = summary || {};
    const days = Number(data.days) || 30;
    setText('paper-recorded', formatCount(data.opportunities_recorded));
    setText('paper-recorded-sub', tr('opportunities in the last {days} day(s)', { days }));
    setText('paper-positions', formatCount(data.positions));
    setText('paper-positions-sub', tr('paper positions in the last {days} day(s)', { days }));
    setText('paper-open-settled', `${formatCount(data.open_positions)} / ${formatCount(data.settled_positions)}`);
    setText('paper-open-settled-sub', tr('open / settled of {count} position(s)', { count: formatCount(data.positions) }));
    setText('paper-roi', data.roi == null ? '—' : `${(Number(data.roi) * 100).toFixed(2)}%`);
    setText('paper-roi-sub', data.roi == null
        ? tr('no settled positions (0 of {count} position(s))', { count: formatCount(data.positions) })
        : tr('profit {profit} on settled stake {staked} ({settled} settled)', { profit: money(data.profit), staked: money(data.staked), settled: formatCount(data.settled_positions) }));
    setText('paper-hit', data.hit_rate == null ? '—' : `${(Number(data.hit_rate) * 100).toFixed(2)}%`);
    setText('paper-hit-sub', data.hit_rate == null
        ? tr('no marked positions (0 of {count} position(s))', { count: formatCount(data.positions) })
        : tr('{count} marked position(s)', { count: formatCount(data.hit_rate_positions) }));
    setText('paper-clv', data.clv == null ? '—' : `${(Number(data.clv) * 100).toFixed(2)}%`);
    setText('paper-clv-sub', data.clv == null
        ? tr('no marked legs with a next-scan price')
        : tr('{count} leg(s) with a next-scan price', { count: formatCount(data.clv_legs) }));
    const execution = data.execution_adjusted || {};
    const optimistic = data.simulated_open || {};
    const pct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`;
    setText(
        'paper-fill-summary',
        tr('Execution-adjusted ROI {roi} on {count} complete fill record(s) · worst case {worst} on {filled} KM filled · optimistic {optimistic} on {open} open position(s)', {
            roi: pct(execution.roi),
            count: formatCount(execution.positions),
            worst: execution.worst_case_profit == null ? '—' : `${money(execution.worst_case_profit)} KM`,
            filled: money(execution.filled_stake),
            optimistic: pct(optimistic.roi_if_all_filled),
            open: formatCount(optimistic.positions),
        })
    );
    const count = document.getElementById('paper-count');
    if (count) count.textContent = formatCount(data.positions);
    const store = data.store || {};
    const rows = store.rows || {};
    const retention = store.retention || {};
    const last = store.last_maintenance && store.last_maintenance.finished_at
        ? store.last_maintenance.finished_at
        : tr('never');
    setText(
        'paper-store',
        tr('Paper store: {bytes} · {recorded} recorded row(s) · {positions} position row(s) · retention {days} day(s) / {cap} row cap · last maintenance {last}', {
            bytes: formatBytes(store.bytes),
            recorded: formatCount(rows.recorded_opportunities),
            positions: formatCount(rows.paper_positions),
            days: formatCount(retention.paper_days),
            cap: formatCount(retention.paper_max_rows),
            last,
        })
    );
}

function paperEvent(row) {
    return `${row.home_team || '?'} – ${row.away_team || '?'}`;
}

function renderPaperOpportunities(payload) {
    const body = document.getElementById('paper-opportunities-body');
    if (!body) return;
    const rows = Array.isArray(payload?.opportunities) ? payload.opportunities : [];
    const total = Number(payload?.total) || 0;
    paperState.oppTotal = total;
    setText('paper-opp-total', tr('{count} row(s)', { count: total }));
    setText('paper-opp-page', paperPageLabel(paperState.oppOffset, total));
    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="6">${escapeHtml(tr('No recorded opportunities in this window.'))}</td></tr>`;
        return;
    }
    body.innerHTML = rows.map(row => {
        const profit = row.profit_percent == null ? '—' : `${Number(row.profit_percent).toFixed(2)}%`;
        const best = row.best_book
            ? `${escapeHtml(row.best_book)} @ ${Number(row.best_odds).toFixed(2)}`
            : '—';
        return '<tr>'
            + `<td class="mono">${escapeHtml(row.recorded_at || '')}</td>`
            + `<td>${escapeHtml(paperEvent(row))}<span class="paper-sub">${escapeHtml(row.league || '')} · ${escapeHtml(row.kickoff || '')}</span></td>`
            + `<td>${escapeHtml(row.market_type || '')}${row.line ? ` <span class="paper-sub">${escapeHtml(row.line)}</span>` : ''}</td>`
            + `<td class="mono">${profit}</td>`
            + `<td>${best}</td>`
            + `<td>${escapeHtml(row.gate_verdict || '')}</td>`
            + '</tr>';
    }).join('');
}

function paperMarkCell(position) {
    const mark = position.mark || {};
    if (!mark || mark.marked_at == null) return `<span class="paper-sub">${escapeHtml(tr('not marked yet'))}</span>`;
    const matched = Number(mark.matched_legs) || 0;
    const total = Number(mark.total_legs) || 0;
    const label = tr(mark.available ? 'available' : 'unavailable');
    const cls = mark.available ? 'paper-mark-ok' : 'paper-mark-bad';
    const reason = mark.reason ? `<span class="paper-sub">${escapeHtml(mark.reason)}</span>` : '';
    const fills = Array.isArray(mark.fills) ? mark.fills : [];
    const counts = {};
    for (const fill of fills) counts[fill.status] = (counts[fill.status] || 0) + 1;
    const fillText = Object.entries(counts).map(([status, count]) => `${count} ${tr(status)}`).join(', ') || tr('no fill record');
    const fill = tr(mark.fill_complete ? 'fill complete' : 'fill incomplete');
    const worst = mark.worst_case_profit == null ? tr('n/a') : `${money(mark.worst_case_profit)} KM`;
    return `<span class="${cls}">${escapeHtml(label)} (${matched}/${total})</span>`
        + `<span class="paper-sub">${escapeHtml(fill)}: ${escapeHtml(fillText)} · ${escapeHtml(tr('filled {filled}/{planned} · worst {worst}', { filled: money(mark.filled_stake), planned: money(mark.planned_stake), worst }))}</span>`
        + reason;
}

function paperSettleCell(position) {
    if (position.status !== 'open') {
        const profit = position.realized_profit == null ? '' : ` · ${money(position.realized_profit)} KM`;
        return `<span class="paper-sub">${escapeHtml(tr('settled{profit}', { profit }))}</span>`;
    }
    const legs = Array.isArray(position.entry_legs) ? position.entry_legs : [];
    const selects = legs.map(leg => {
        const label = String(leg.outcome_label || '');
        return `<label class="paper-sub">${escapeHtml(label)}`
            + `<select data-paper-result data-position-id="${escapeHtml(position.id)}" data-leg-label="${escapeHtml(label)}">`
            + `<option value="">—</option><option value="won">${escapeHtml(tr('Won'))}</option>`
            + `<option value="lost">${escapeHtml(tr('Lost'))}</option><option value="void">${escapeHtml(tr('Void'))}</option>`
            + '</select></label>';
    }).join('');
    return `<div class="paper-settle">${selects}`
        + `<button type="button" class="btn btn-small btn-secondary" data-action="paper-settle" data-position-id="${escapeHtml(position.id)}">${escapeHtml(tr('Settle'))}</button>`
        + '</div>';
}

function renderPaperPositions(payload) {
    const body = document.getElementById('paper-positions-body');
    if (!body) return;
    const rows = Array.isArray(payload?.positions) ? payload.positions : [];
    const total = Number(payload?.total) || 0;
    paperState.posTotal = total;
    setText('paper-pos-total', tr('{count} row(s)', { count: total }));
    setText('paper-pos-page', paperPageLabel(paperState.posOffset, total));
    if (!rows.length) {
        body.innerHTML = `<tr><td colspan="7">${escapeHtml(tr('No paper positions in this window.'))}</td></tr>`;
        return;
    }
    body.innerHTML = rows.map(position => {
        const sim = position.simulated_profit == null
            ? '—'
            : `${money(position.simulated_profit)} KM`;
        return '<tr>'
            + `<td>${escapeHtml(paperEvent(position))}<span class="paper-sub">${escapeHtml(position.league || '')} · ${escapeHtml(position.kickoff || '')}</span></td>`
            + `<td>${escapeHtml(position.market_type || '')}${position.line ? ` <span class="paper-sub">${escapeHtml(position.line)}</span>` : ''}</td>`
            + `<td>${escapeHtml(position.status || '')}</td>`
            + `<td class="mono">${money(position.stake)} KM</td>`
            + `<td class="mono">${sim}</td>`
            + `<td>${paperMarkCell(position)}</td>`
            + `<td>${paperSettleCell(position)}</td>`
            + '</tr>';
    }).join('');
}

async function settlePaperPosition(positionId) {
    const selects = [...document.querySelectorAll(
        `[data-paper-result][data-position-id="${positionId}"]`
    )];
    if (!selects.length) return;
    if (selects.some(select => !select.value)) {
        showToast(tr('Set a result for every leg before settling.'));
        return;
    }
    const legs = selects.map(select => ({
        outcome_label: select.dataset.legLabel,
        result: select.value,
    }));
    try {
        const response = await apiFetch(
            `/api/paper/positions/${encodeURIComponent(positionId)}/settle`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ legs }),
            },
            tr('This SureBet deployment requires an API key to settle a paper position.')
        );
        if (!response.ok) throw new Error(tr('settle returned {status}', { status: response.status }));
        showToast(tr('Paper position settled.'));
        loadPaper();
    } catch (error) {
        showToast(tr('Could not settle the paper position: {error}', { error: error.message }));
    }
}

function paperPage(kind, direction) {
    const key = kind === 'opportunities' ? 'oppOffset' : 'posOffset';
    const total = kind === 'opportunities' ? paperState.oppTotal : paperState.posTotal;
    // Stay on a page that exists: the API total, not the offset, is the limit.
    const lastPageStart = total > 0
        ? Math.floor((total - 1) / PAPER_PAGE_SIZE) * PAPER_PAGE_SIZE
        : 0;
    paperState[key] = Math.max(0, Math.min(paperState[key] + direction * PAPER_PAGE_SIZE, lastPageStart));
    loadPaper();
}

function setPaperFilter(name, value) {
    paperState[name] = value;
    paperState.oppOffset = 0;
    paperState.posOffset = 0;
    loadPaper();
}

async function loadHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        // The counts that say WHY there is no surebet live in this response, so
        // the payload is kept for the diagnostic.
        healthSnapshot = data;
        renderCoverageTrend(data);
        renderScanCost(data);
        renderRemediation(data);
        const bar = document.getElementById('health-bar');
        if (!bar) return;
        const fmtAge = (sec) => sec == null ? '—' : sec < 60 ? `${Math.round(sec)}s ago` : `${Math.round(sec/60)}m ago`;
        const fmtPer = (obj) => obj && Object.keys(obj).length ? Object.entries(obj).map(([k,v]) => `${k}:${v}`).join(' ') : '—';
        bar.hidden = false;
        const missRate = Number(data.pairing?.strict_miss_rate);
        const pairing = Number.isFinite(missRate)
            ? tr('Pairing {rate}% miss', { rate: (missRate * 100).toFixed(2) })
            : tr('Pairing —');
        const coverageFlags = (Number(data.coverage_budget?.prematch?.flag_count) || 0)
            + (Number(data.coverage_budget?.live?.flag_count) || 0);
        bar.innerHTML = escapeHtml(tr('Health — Prematch {prematch} | Live {live} | TTL {ttl}s | {pairing}', { prematch: `${fmtAge(data.prematch?.last_scan_age_sec)} [${fmtPer(data.prematch?.per_bookie)}]`, live: `${fmtAge(data.live?.last_scan_age_sec)} [${fmtPer(data.live?.per_bookie)}]`, ttl: data.odds_ttl_sec, pairing }));
        const titles = [...(data.prematch?.errors||[]), ...(data.live?.errors||[])];
        if (coverageFlags) titles.push(tr('Coverage {count} flag(s)', { count: coverageFlags }));
        for (const mode of ['prematch', 'live']) {
            for (const flag of (data.coverage_budget?.[mode]?.flags || [])) {
                titles.push(`${mode} ${flag.bookmaker}/${flag.sport}/${flag.market}: ${flag.kind} ${flag.observed}/${flag.baseline}`);
            }
        }
        if (titles.length) bar.title = titles.join(' | ');
        try {
            const betResponse = await apiFetch('/api/bets/summary?days=30');
            if (betResponse.ok) {
                const bet = await betResponse.json();
                const roi = bet.roi == null ? '—' : `${(Number(bet.roi) * 100).toFixed(2)}%`;
                const clv = bet.clv == null ? '—' : `${(Number(bet.clv) * 100).toFixed(2)}%`;
                const closing = bet.closing_capture || {};
                const closingLegs = `${Number(closing.legs_with_closing || 0)}/${Number(closing.legs_total || 0)}`;
                const sources = Object.entries(closing.by_source || {})
                    .map(([source, count]) => `${source} ${count}`).join(', ');
                setText('bet-summary', tr('Bet log: {settled}/{bets} settled · ROI {roi} · bankroll {bankroll} KM · CLV {clv} ({legs} legs) · closing {closing}{sources}', { settled: bet.settled_bets, bets: bet.bets, roi, bankroll: money(bet.bankroll), clv, legs: bet.clv_legs, closing: closingLegs, sources: sources ? ` (${sources})` : '' }));
            }
        } catch (e) { /* the bet log is optional */ }
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
