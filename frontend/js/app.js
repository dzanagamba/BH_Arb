/**
 * Surebet Scanner — Dashboard JavaScript
 *
 * Responsibilities:
 *  - scanNow()          — Trigger backend scan, start status polling
 *  - pollStatus()       — Poll /api/status every 2s during scan
 *  - loadResults()      — Fetch /api/results and render cards
 *  - renderSurebets()   — Build surebet card HTML from data
 *  - applyFilters()     — Client-side filter by market + min profit + bookmaker
 *  - recalculateAll()   — Re-compute stakes for new global investment
 *  - recalculateCard()  — Per-card investment input handler
 *  - playAlertSound()   — Web Audio API beep for high-profit surebets
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let currentMode = 'prematch';       // 'prematch' (future) | 'live' (in-play)
let activeScanMode = null;          // mode of the currently running scan
let allSurebets = [];          // Full list from server
let filteredSurebets = [];     // After client-side filtering
let pollingInterval = null;
let activeBookmakers = new Set(['mozzartbet', 'mdshop', 'admiralbet', 'betole', 'mbet', 'sportplus', 'evlbet', 'premier_kladionica', 'wwin']);
let bookmakersConfig = {};
let globalInvestment = 100;
let stakeRounding = 'exact';   // 'exact' | '1' | '5'
let soundMuted = false;
let audioContext = null;       // shared AudioContext (reused, no per-alert leak)
let autoRescanTimer = null;    // auto-rescan countdown interval
let knownSurebetSignatures = new Set();  // fingerprints of previously seen surebets

function restoreMode() {
    try {
        const saved = localStorage.getItem('currentMode');
        if (saved === 'live' || saved === 'prematch') {
            currentMode = saved;
        }
    } catch (e) { /* localStorage unavailable */ }
    updateModeToggleUI();
}

function updateModeToggleUI() {
    const prematchBtn = document.getElementById('mode-prematch');
    const liveBtn = document.getElementById('mode-live');
    if (prematchBtn) prematchBtn.classList.toggle('active', currentMode === 'prematch');
    if (liveBtn) liveBtn.classList.toggle('active', currentMode === 'live');
}

function switchMode(mode) {
    if (mode !== 'prematch' && mode !== 'live') return;
    if (mode === currentMode) return;
    currentMode = mode;
    try { localStorage.setItem('currentMode', mode); } catch (e) { /* ignore */ }
    updateModeToggleUI();
    hideError();
    // Load the other mode's cached results (silent, no alert sound)
    loadResults(true);
}

function surebetSignature(sb) {
    const stakes = sb.stakes
        .map(s => `${s.bookmaker}:${s.outcome_label}:${s.odds}`)
        .sort()
        .join('|');
    return `${sb.home_team}|${sb.away_team}|${sb.market_type}|${stakes}`;
}

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
    'btts':           'GG/NG',
    'double_chance':  'Dupla',
    'first_half_1x2': '1st Half 1X2',
    'first_half_ou':  '1st Half O/U',
    'asian_handicap': 'Asian Hcp',
};

// ─── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    restoreDashboardTheme();
    restorePreferences();
    restoreMode();
    await loadConfig();
    initBookmakerChips();
    await loadResults(true);  // Load any cached results from previous scan (no alert sound)
});

function restoreDashboardTheme() {
    let theme = 'terminal';
    try { theme = localStorage.getItem('dashboardTheme') || theme; } catch (e) { /* ignore */ }
    setDashboardTheme(theme, false);
}

function setDashboardTheme(theme, persist = true) {
    const themes = ['terminal', 'brief', 'signal', 'portfolio'];
    if (!themes.includes(theme)) theme = 'terminal';
    document.body.dataset.theme = theme;
    const picker = document.getElementById('theme-select');
    if (picker) picker.value = theme;
    if (persist) {
        try { localStorage.setItem('dashboardTheme', theme); } catch (e) { /* ignore */ }
    }
}

function restorePreferences() {
    try {
        stakeRounding = localStorage.getItem('stakeRounding') || 'exact';
        const roundingEl = document.getElementById('filter-rounding');
        if (roundingEl) roundingEl.value = stakeRounding;

        soundMuted = localStorage.getItem('soundMuted') === '1';
        const muteBtn = document.getElementById('mute-btn');
        if (muteBtn) muteBtn.textContent = soundMuted ? '🔕' : '🔔';
    } catch (e) { /* localStorage unavailable */ }
}

function setStakeRounding(mode) {
    stakeRounding = mode;
    try { localStorage.setItem('stakeRounding', mode); } catch (e) { /* ignore */ }
    recalculateAll(globalInvestment);
    applyFilters();
}

function roundStake(value) {
    if (stakeRounding === '1') return Math.round(value);
    if (stakeRounding === '5') return Math.round(value / 5) * 5;
    return Math.round(value * 100) / 100;
}

function stakeFormat(value) {
    return roundStake(value).toFixed(stakeRounding === 'exact' ? 2 : 0);
}

async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        bookmakersConfig = data.bookmakers || {};

        // Set global defaults from server config
        const minInput = document.getElementById('filter-profit');
        if (data.min_profit_percent) minInput.value = data.min_profit_percent;

        const investInput = document.getElementById('filter-investment');
        if (data.default_investment) {
            globalInvestment = data.default_investment;
            investInput.value = data.default_investment;
        }

        // Experimental-market checkboxes (server-side toggles)
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

async function toggleExperimentalMarket(box) {
    const market = box.value;
    try {
        const res = await fetch(`/api/config/toggle_market/${market}`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            box.checked = data.enabled;
            setStatus('done', `${data.enabled ? 'Enabled' : 'Disabled'} ${market} — re-scan to apply`);
        } else {
            box.checked = !box.checked;
        }
    } catch (e) {
        box.checked = !box.checked;
        console.warn('Market toggle failed:', e);
    }
}

function initBookmakerChips() {
    const container = document.getElementById('bookie-chips');
    if (!container) return;
    container.innerHTML = '';

    const bookieList = Object.keys(bookmakersConfig).length > 0
        ? Object.entries(bookmakersConfig)
        : Object.entries(BOOKMAKER_COLORS).map(([k]) => [k, { name: capitalize(k), color: BOOKMAKER_COLORS[k], enabled: true }]);

    // Rebuild the client-side filter from the server's enabled state
    activeBookmakers = new Set();
    bookieList.forEach(([id, cfg]) => {
        if (cfg.enabled !== false) activeBookmakers.add(id);
    });

    bookieList.forEach(([id, cfg]) => {
        const color = cfg.color || BOOKMAKER_COLORS[id] || '#888';
        const name = cfg.name || capitalize(id);
        const enabled = cfg.enabled !== false;

        const chip = document.createElement('button');
        chip.className = 'bookie-chip' + (enabled ? ' active' : '');
        chip.dataset.bookie = id;
        chip.style.setProperty('--chip-color', color);
        chip.innerHTML = `${name} <span class="chip-toggle-icon">${enabled ? '✓' : '✕'}</span>`;
        chip.addEventListener('click', () => toggleBookmakerAPI(chip, id));
        container.appendChild(chip);
    });
}

async function toggleBookmakerAPI(chip, id) {
    try {
        const res = await fetch(`/api/config/toggle/${id}`, { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            if (data.enabled) {
                chip.classList.add('active');
                chip.querySelector('.chip-toggle-icon').textContent = '✓';
                chip.title = 'Click to disable';
            } else {
                chip.classList.remove('active');
                chip.querySelector('.chip-toggle-icon').textContent = '✕';
                chip.title = 'Click to enable';
            }

            // Keep the client-side bookmaker filter in sync with the backend toggle
            if (data.enabled) {
                activeBookmakers.add(id);
            } else {
                activeBookmakers.delete(id);
            }
            applyFilters();
        }
    } catch (e) {
        console.warn('Toggle failed:', e);
    }
}

// ─── Scan ─────────────────────────────────────────────────────────────────────
async function scanNow() {
    const btn = document.getElementById('scan-btn');
    if (btn.disabled) return;

    try {
        const res = await fetch(`/api/scan?mode=${currentMode}`, { method: 'POST' });
        const data = await res.json();

        if (data.status === 'already_scanning') {
            setStatus('scanning', 'Scan in progress...');
            startPolling();
            return;
        }

        // Start UI updates
        btn.disabled = true;
        activeScanMode = currentMode;
        btn.innerHTML = `<svg class="btn-icon scanning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 22V12M12 12V2M12 12H2M12 12h10"/>
        </svg> Scanning...`;

        showScanProgress();
        setStatus('scanning', `Starting ${currentMode === 'live' ? 'live' : 'future'} scan...`);
        startPolling();

    } catch (e) {
        showError('Failed to start scan: ' + e.message);
    }
}

function startPolling() {
    if (pollingInterval) return;
    pollingInterval = setInterval(pollStatus, 2000);
}

// ─── Auto-Rescan ──────────────────────────────────────────────────────────────
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
            countdownEl.textContent = `⟳ next scan in ${m}:${s}`;
        }
        if (remaining <= 0) {
            remaining = minutes * 60;
            scanNow();
        }
    }, 1000);
}function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
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
    const statusTextEl = document.getElementById('status-text');

    if (subEl) subEl.textContent = status.current_bookmaker || 'Processing...';
    if (statusTextEl) statusTextEl.textContent = status.current_bookmaker || 'Scanning...';

    // Per-bookmaker progress badges (scraping / done / error)
    if (doneEl) {
        const prog = status.bookmaker_progress || {};
        doneEl.innerHTML = Object.entries(prog).map(([id, state]) => {
            const name = bookmakersConfig[id]?.name || capitalize(id);
            if (state === 'done') return `<span class="scan-bookie-badge">✓ ${name}</span>`;
            if (state === 'scraping') return `<span class="scan-bookie-badge scanning">⟳ ${name}</span>`;
            if (state === 'error') return `<span class="scan-bookie-badge error">✕ ${name}</span>`;
            return ''; // skipped
        }).join('');
    }

    // Progress bar (estimate based on done count vs total ENABLED bookmakers)
    const enabledTotal = Object.values(bookmakersConfig).filter(c => c.enabled !== false).length;
    const total = enabledTotal || 4;
    const done = (status.bookmakers_done || []).length;
    const pct = Math.min(90, (done / total) * 80 + 5);
    if (barEl) barEl.style.width = pct + '%';
}

async function onScanComplete(status) {
    // Animate bar to 100%
    const barEl = document.getElementById('scan-bar');
    if (barEl) barEl.style.width = '100%';

    await new Promise(r => setTimeout(r, 600));
    hideScanProgress();

    // Reset scan button
    const btn = document.getElementById('scan-btn');
    btn.disabled = false;
    btn.innerHTML = `<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
    </svg> Scan Now`;

    // Show errors if any
    if (status.errors && status.errors.length > 0) {
        const errorMsg = 'Errors during scan: ' + status.errors.slice(0, 2).join('; ');
        showError(errorMsg);
    }

    if (status.surebets_found > 0) {
        setStatus('done', `${status.surebets_found} surebet${status.surebets_found > 1 ? 's' : ''} found!`);
    } else {
        setStatus('done', 'Scan complete — no surebets');
    }

    await loadResults();
}
// ─── Results ──────────────────────────────────────────────────────────────────
async function loadResults(silent = false) {
    try {
        const res = await fetch(`/api/results?mode=${currentMode}`);
        const data = await res.json();

        allSurebets = data.surebets || [];

        // Update stats
        document.getElementById('stat-matches').textContent =
            data.total_matches != null ? data.total_matches.toLocaleString() : '—';

        document.getElementById('stat-surebets').textContent =
            allSurebets.length > 0 ? allSurebets.length : '0';

        if (allSurebets.length > 0) {
            const best = allSurebets.reduce((a, b) =>
                a.profit_percent > b.profit_percent ? a : b
            );
            document.getElementById('stat-best').textContent =
                best.profit_percent.toFixed(2) + '%';
        } else {
            document.getElementById('stat-best').textContent = '—';
        }

        if (data.last_scan_time) {
            const dt = new Date(data.last_scan_time);
            document.getElementById('stat-time').textContent = formatTime(dt);
            // P0-6 staleness badge — warn if odds older than 2 minutes
            const ageSec = (Date.now() - dt.getTime()) / 1000;
            if (ageSec > 120) {
                showError(`⚠️ Odds are ${Math.round(ageSec)}s old — click Verify Odds before betting (stale cache)`);
            } else {
                // Clear stale warning if previously shown and now fresh
                const banner = document.getElementById('error-banner');
                const bannerText = document.getElementById('error-banner-text');
                if (bannerText && bannerText.textContent.includes('Odds are') && bannerText.textContent.includes('old')) {
                    hideError();
                }
            }
        }

        applyFilters();

        // Alert sound for NEW high-value surebets only — never on page load,
        // and never twice for the same surebet across rescans
        const signatures = new Set(allSurebets.map(surebetSignature));
        if (!silent) {
            const newHighValue = allSurebets.filter(
                s => s.profit_percent >= 3.0 && !knownSurebetSignatures.has(surebetSignature(s))
            );
            if (newHighValue.length > 0) {
                playAlertSound();
            }
        }
        knownSurebetSignatures = signatures;

    } catch (e) {
        console.error('Failed to load results:', e);
    }
}

function applyFilters() {
    const marketFilter = document.getElementById('filter-market').value;
    const profitInput = document.getElementById('filter-profit').value;
    const minProfit = profitInput !== '' ? parseFloat(profitInput) : 0;
    const searchTerm = document.getElementById('filter-search').value.trim().toLowerCase();
    const sortMode = document.getElementById('filter-sort').value;

    filteredSurebets = allSurebets.filter(sb => {
        // Market filter
        if (marketFilter && sb.market_type !== marketFilter) return false;
        // Profit filter
        if (sb.profit_percent < minProfit) return false;
        // Bookmaker filter — check if ANY stake uses an active bookmaker
        const sbBookmakers = new Set(sb.stakes.map(s => s.bookmaker));
        const hasActive = [...sbBookmakers].some(b => activeBookmakers.has(b));
        if (!hasActive) return false;
        // Search filter — team or league substring
        if (searchTerm) {
            const haystack = `${sb.home_team} ${sb.away_team} ${sb.league || ''}`.toLowerCase();
            if (!haystack.includes(searchTerm)) return false;
        }
        return true;
    });

    // Sort
    filteredSurebets.sort((a, b) => {
        if (sortMode === 'kickoff') {
            const ta = a.kickoff ? new Date(a.kickoff).getTime() : Number.MAX_SAFE_INTEGER;
            const tb = b.kickoff ? new Date(b.kickoff).getTime() : Number.MAX_SAFE_INTEGER;
            return ta - tb;
        }
        if (sortMode === 'league') {
            return (a.league || '').localeCompare(b.league || '');
        }
        return b.profit_percent - a.profit_percent; // profit desc (default)
    });

    renderSurebets(filteredSurebets);
}

function resetFilters() {
    document.getElementById('filter-market').value = '';
    document.getElementById('filter-profit').value = '0.5';
    document.getElementById('filter-search').value = '';
    document.getElementById('filter-sort').value = 'profit';
    // Re-activate all bookmakers
    activeBookmakers = new Set(Object.keys(BOOKMAKER_COLORS));
    document.querySelectorAll('.bookie-chip').forEach(c => c.classList.add('active'));
    applyFilters();
}

// ─── Rendering ────────────────────────────────────────────────────────────────
function renderSurebets(surebets) {
    const grid = document.getElementById('results-grid');
    const emptyState = document.getElementById('empty-state');
    const noResults = document.getElementById('no-results');

    grid.innerHTML = '';

    // Mode-aware empty state copy
    if (currentMode === 'live') {
        document.querySelector('.empty-state-title').textContent = 'No Live Matches Scanned';
        document.querySelector('.empty-state-desc').innerHTML =
            'Click <strong>Scan Now</strong> to scan all bookmakers for <strong>in-play</strong> arbitrage opportunities. Live odds change fast — rescan often.';
    } else {
        document.querySelector('.empty-state-title').textContent = 'Ready to Hunt Surebets';
        document.querySelector('.empty-state-desc').innerHTML =
            'Click <strong>Scan Now</strong> to start scanning all 9 bookmakers for arbitrage opportunities. Browser windows will open — solve any CAPTCHA if prompted.';
    }

    // Show empty state if no data at all
    if (allSurebets.length === 0) {
        emptyState.style.display = '';
        noResults.style.display = 'none';
        return;
    }

    emptyState.style.display = 'none';

    // Show no-results if filters eliminate everything
    if (surebets.length === 0) {
        noResults.style.display = '';
        return;
    }

    noResults.style.display = 'none';

    surebets.forEach((sb, idx) => {
        const card = buildSurebetCard(sb, idx);
        grid.appendChild(card);
    });
}

function buildSurebetCard(sb, idx) {
    const tpl = document.getElementById('surebet-card-tpl');
    const card = tpl.content.cloneNode(true).querySelector('.surebet-card');

    card.dataset.id = sb.id;
    card.dataset.margin = sb.total_margin;
    card.dataset.profit = sb.profit_percent;

    // Profit tier coloring
    if (sb.profit_percent >= 3.0) card.dataset.tier = 'high';
    else if (sb.profit_percent >= 1.5) card.dataset.tier = 'mid';
    else if (sb.profit_percent >= 0.0) card.dataset.tier = 'low';
    else card.dataset.tier = 'negative';

    // Profit value
    card.querySelector('.profit-value').textContent = sb.profit_percent.toFixed(2) + '%';

    // Market badge
    card.querySelector('.market-badge').textContent =
        MARKET_LABELS[sb.market_type] || sb.market_type;

    // League
    card.querySelector('.card-league').textContent =
        formatLeague(sb.league) || 'Unknown League';

    // Live badge + kickoff (in-play matches show a LIVE marker)
    const isLiveMode = currentMode === 'live';
    const liveBadge = card.querySelector('.card-live-badge');
    if (isLiveMode) {
        liveBadge.style.display = '';
    }

    // Kickoff
    const kickoffDt = parseKickoff(sb.kickoff);
    card.querySelector('.card-kickoff').textContent =
        isLiveMode ? (kickoffDt ? `Started ${formatTime(kickoffDt)}` : 'In play') : (kickoffDt ? formatKickoff(kickoffDt) : '');

    // Teams
    card.querySelector('.team-home').textContent = formatTeamName(sb.home_team);
    card.querySelector('.team-away').textContent = formatTeamName(sb.away_team);

    // Stakes
    const stakesEl = card.querySelector('.card-stakes');
    sb.stakes.forEach(stake => {
        const stakeDiv = buildStakeRow(stake, sb.market_type, sb.match_urls || {}, sb.bet_urls || {});
        stakesEl.appendChild(stakeDiv);
    });

    // Return display
    const ret = (globalInvestment / sb.total_margin);
    card.querySelector('.return-value').textContent = ret.toFixed(2) + ' KM';

    // Investment input
    const investInput = card.querySelector('.card-invest-input');
    investInput.value = globalInvestment;
    investInput.addEventListener('input', (e) => {
        recalculateCard(card, sb, parseFloat(e.target.value) || 0);
    });

    return card;
}

function buildStakeRow(stake, marketType, matchUrls, betUrls) {
    const div = document.createElement('div');
    div.className = 'stake-row';

    const bookieName = bookmakersConfig[stake.bookmaker]?.name ||
                       capitalize(stake.bookmaker);
    const bookieColor = bookmakersConfig[stake.bookmaker]?.color ||
                        BOOKMAKER_COLORS[stake.bookmaker] || '#888';

    const url = matchUrls ? matchUrls[stake.bookmaker] : null;
    const bookieHtml = url
        ? `<a class="stake-bookie-link" href="${url}" target="_blank" rel="noopener" style="color: ${bookieColor}" title="Open match page on ${bookieName}">${bookieName}</a>`
        : `<div class="stake-bookie" style="color: ${bookieColor}">${bookieName}</div>`;

    // Ticket button: bet-slip prefill URL when the bookmaker supports it,
    // otherwise falls back to the match page URL.
    const betUrl = betUrls ? betUrls[stake.bookmaker] : null;
    const ticketHref = betUrl || url;
    const ticketTitle = betUrl
        ? `Add ${stake.outcome_label} @ ${stake.odds.toFixed(2)} to ticket on ${bookieName}`
        : (url ? `Open match on ${bookieName}` : null);
    const ticketHtml = ticketHref && ticketTitle
        ? `<a class="stake-ticket-link" href="${ticketHref}" target="_blank" rel="noopener" title="${ticketTitle}" aria-label="${ticketTitle}">🎫</a>`
        : '';

    div.innerHTML = `
        <div class="stake-bookie-row">
            ${bookieHtml}
            ${ticketHtml}
        </div>
        <div class="stake-outcome">${stake.outcome_label}</div>
        <div class="stake-odds">${stake.odds.toFixed(2)}</div>
        <div class="stake-amount">Bet: <strong data-stake="${stake.stake}">${stakeFormat(stake.stake)} KM</strong></div>
    `;
    return div;
}

// ─── Recalculate Stakes ───────────────────────────────────────────────────────
function recalculateAll(investment) {
    const val = parseFloat(investment) || 100;
    globalInvestment = val;

    document.querySelectorAll('.surebet-card').forEach(card => {
        const sbId = card.dataset.id;
        const sb = allSurebets.find(s => s.id === sbId);
        if (sb) recalculateCard(card, sb, val);
        card.querySelector('.card-invest-input').value = val;
    });
}

function recalculateCard(card, sb, investment) {
    if (!investment || investment <= 0 || sb.total_margin >= 1.0) return;

    const totalMargin = sb.total_margin;
    const guaranteedReturn = investment / totalMargin;

    // Update return display
    card.querySelector('.return-value').textContent =
        guaranteedReturn.toFixed(2) + ' KM';

    // Update each stake amount
    sb.stakes.forEach(stake => {
        const implied = 1.0 / stake.odds;
        const newStake = roundStake(investment * (implied / totalMargin));
        // Find the stake row for this outcome
        const rows = card.querySelectorAll('.stake-row');
        rows.forEach(row => {
            const stakeEl = row.querySelector('[data-stake]');
            const outcomeEl = row.querySelector('.stake-outcome');
            if (stakeEl && outcomeEl &&
                outcomeEl.textContent === stake.outcome_label) {
                stakeEl.textContent = newStake.toFixed(stakeRounding === 'exact' ? 2 : 0) + ' KM';
                stakeEl.dataset.stake = newStake;
            }
        });
    });
}

// ─── Verify Odds ──────────────────────────────────────────────────────────────
async function verifySurebet(btn) {
    const card = btn.closest('.surebet-card');
    if (!card) return;
    const sbId = card.dataset.id;
    const original = btn.textContent;
    btn.textContent = '⟳ Verifying...';
    btn.disabled = true;
    btn.classList.remove('verify-ok', 'verify-bad');
    try {
        const res = await fetch('/api/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ surebet_id: sbId, mode: currentMode }),
        });
        const data = await res.json();
        if (!res.ok) {
            btn.textContent = data.detail || 'Verify failed';
            btn.classList.add('verify-bad');
        } else if (data.still_profitable) {
            btn.textContent = `✓ Still ${data.current.profit_percent}%`;
            btn.classList.add('verify-ok');
        } else if (data.current) {
            btn.textContent = `✕ Now ${data.current.profit_percent}%`;
            btn.classList.add('verify-bad');
        } else {
            btn.textContent = data.message || 'Verify failed';
            btn.classList.add('verify-bad');
        }
    } catch (e) {
        btn.textContent = 'Verify failed';
        btn.classList.add('verify-bad');
    } finally {
        btn.disabled = false;
        setTimeout(() => {
            btn.textContent = original;
            btn.classList.remove('verify-ok', 'verify-bad');
        }, 6000);
    }
}

// ─── Scan History ─────────────────────────────────────────────────────────────
async function toggleHistory() {
    const panel = document.getElementById('history-panel');
    if (!panel) return;
    if (panel.style.display === 'none') {
        panel.style.display = '';
        await loadHistory();
    } else {
        panel.style.display = 'none';
    }
}

async function loadHistory() {
    const body = document.getElementById('history-body');
    if (!body) return;
    try {
        const res = await fetch('/api/history');
        const data = await res.json();
        const entries = data.entries || [];
        if (entries.length === 0) {
            body.innerHTML = '<tr><td colspan="6" class="history-empty">No scans yet</td></tr>';
            return;
        }
        body.innerHTML = entries.map(e => {
            const time = e.scan_time ? new Date(e.scan_time).toLocaleString() : '—';
            const errs = (e.errors || []).length;
            const mode = e.mode === 'live'
                ? '<span class="history-mode history-mode-live">LIVE</span>'
                : '<span class="history-mode">FUTURE</span>';
            return `<tr>
                <td>${mode}</td>
                <td>${time}</td>
                <td>${e.total_matches ?? '—'}</td>
                <td>${e.match_groups ?? '—'}</td>
                <td class="${e.surebets_found > 0 ? 'history-surebets' : ''}">${e.surebets_found ?? 0}</td>
                <td class="${errs > 0 ? 'history-errors' : ''}">${errs}</td>
            </tr>`;
        }).join('');
    } catch (e) {
        body.innerHTML = '<tr><td colspan="6" class="history-empty">Failed to load history</td></tr>';
    }
}

// ─── Copy Bet Details ─────────────────────────────────────────────────────────
async function copySurebetDetails(btn) {
    const card = btn.closest('.surebet-card');
    if (!card) return;
    const sb = allSurebets.find(s => s.id === card.dataset.id);
    if (!sb) return;

    const lines = [
        `🏆 ${formatTeamName(sb.home_team)} vs ${formatTeamName(sb.away_team)}`,
        `📋 League: ${formatLeague(sb.league) || 'Unknown'}`,
        `🕒 Kickoff: ${parseKickoff(sb.kickoff) ? formatKickoff(parseKickoff(sb.kickoff)) : 'TBA'}`,
        `🎯 Market: ${MARKET_LABELS[sb.market_type] || sb.market_type}`,
        `💰 Profit: ${sb.profit_percent.toFixed(2)}% (Investment: ${globalInvestment} KM)`,
        ``,
        `Stakes:`,
        ...sb.stakes.map(stake => {
            const name = bookmakersConfig[stake.bookmaker]?.name || capitalize(stake.bookmaker);
            const stakeAmt = stakeFormat(globalInvestment * (1 / stake.odds) / sb.total_margin);
            const link = (sb.bet_urls && sb.bet_urls[stake.bookmaker]) ||
                         (sb.match_urls && sb.match_urls[stake.bookmaker]);
            const linkSuffix = link ? ` (${link})` : '';
            return `  • ${name}: ${stake.outcome_label} @ ${stake.odds.toFixed(2)} → ${stakeAmt} KM${linkSuffix}`;
        }),
    ];
    const text = lines.join('\n');

    try {
        await navigator.clipboard.writeText(text);
    } catch (e) {
        // Fallback for non-secure contexts
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
    }

    const original = btn.textContent;
    btn.textContent = '✓ Copied!';
    setTimeout(() => { btn.textContent = original; }, 1500);
}

// ─── UI Helpers ───────────────────────────────────────────────────────────────
function showScanProgress() {
    document.getElementById('scan-progress').style.display = '';
    document.getElementById('scan-bar').style.width = '5%';
    document.getElementById('empty-state').style.display = 'none';
}

function hideScanProgress() {
    document.getElementById('scan-progress').style.display = 'none';
}

function setStatus(state, text) {
    const pill = document.getElementById('status-pill');
    const textEl = document.getElementById('status-text');
    pill.className = 'status-pill ' + state;
    textEl.textContent = text;
}

function showError(msg) {
    const banner = document.getElementById('error-banner');
    document.getElementById('error-banner-text').textContent = msg;
    banner.style.display = '';
}

function hideError() {
    document.getElementById('error-banner').style.display = 'none';
}

// ─── Formatting ───────────────────────────────────────────────────────────────
function parseKickoff(str) {
    if (!str) return null;
    // Scrapers store naive UTC; JS would interpret a bare ISO string as local time.
    // Append 'Z' when the string carries no timezone marker.
    const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(str);
    const dt = new Date(hasTz ? str : str + 'Z');
    return isNaN(dt) ? null : dt;
}

function formatTime(dt) {
    const now = new Date();
    const diffMs = now - dt;
    const diffMin = Math.floor(diffMs / 60000);

    if (diffMin < 1) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return dt.toLocaleDateString();
}

function formatKickoff(dt) {
    if (!dt || isNaN(dt)) return '';
    const today = new Date();
    const isToday = dt.toDateString() === today.toDateString();
    const time = dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (isToday) return '🕒 Today ' + time;
    return '🕒 ' + dt.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + time;
}

function formatTeamName(name) {
    if (!name) return 'Unknown';
    // Capitalize first letter of each word, handle underscores from canonical IDs
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

// ─── Alert Sound ──────────────────────────────────────────────────────────────
function toggleSound() {
    soundMuted = !soundMuted;
    try { localStorage.setItem('soundMuted', soundMuted ? '1' : '0'); } catch (e) { /* ignore */ }
    const muteBtn = document.getElementById('mute-btn');
    if (muteBtn) muteBtn.textContent = soundMuted ? '🔕' : '🔔';
}

function playAlertSound() {
    if (soundMuted) return;
    try {
        // Reuse a single AudioContext to avoid leaking one per alert
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioContext.state === 'suspended') {
            audioContext.resume();
        }

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

        // Pleasant ascending 3-note chime
        playNote(523, audioContext.currentTime,       0.2);  // C5
        playNote(659, audioContext.currentTime + 0.2, 0.2);  // E5
        playNote(784, audioContext.currentTime + 0.4, 0.3);  // G5
    } catch (e) {
        // Audio not available — silent fail
    }
}
