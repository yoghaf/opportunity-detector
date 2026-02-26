/* ============================================================
   Crypto Decision Dashboard — App Logic
   
   Architecture:
     1. WebSocket connection to /ws/live for real-time data push
     2. REST fallback: GET /api/opportunities on WS failure
     3. Client-side filtering & sorting (instant, no server round-trip)
     4. Collector stats polling every 30s
   ============================================================ */

// ============================================================
// HELPER FUNCTIONS (Moved to top for safety)
// ============================================================
window.fmt = function(val) {
    if (val === undefined || val === null) return '—';
    const num = parseFloat(val);
    if (isNaN(num)) return '—';
    return num.toFixed(2);
};

window.fmtInt = function(val) {
    if (val === undefined || val === null) return '—';
    const num = parseInt(val, 10);
    if (isNaN(num)) return '—';
    return num.toLocaleString();
};

window.esc = function(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
};

window.sourceClass = function(source) {
    if (!source) return '';
    const s = source.toLowerCase();
    if (s.includes('gate')) return 'source-gate';
    if (s.includes('okx')) return 'source-okx';
    if (s.includes('binance')) return 'source-binance';
    return '';
};

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        const context = this;
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(context, args), wait);
    };
}

// ============================================================
// State
// ============================================================
const state = {
    data: [],               // Raw opportunity data from server
    filtered: [],           // After client-side filters applied
    sortCol: 'net_apr',     // Default sort: Net APR
    sortAsc: false,         // Descending
    ws: null,
    lastUpdate: null,
};

// ============================================================
// DOM refs
// ============================================================
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    wsStatus:       $('#ws-status'),
    dataStatus:     $('#data-status'),
    collectorStatus:$('#collector-status'),
    clock:          $('#clock'),
    btnRefresh:     $('#btn-refresh'),
    // KPIs
    kpiBestApr:     $('#kpi-best-apr'),
    kpiOppsCount:   $('#kpi-opps-count'),
    kpiTrendCount:  $('#kpi-trend-count'),
    kpiLastUpdate:  $('#kpi-last-update'),
    // Filters
    filterSource:   $('#filter-source'),
    filterApr:      $('#filter-apr'),
    filterLoanSize: $('#filter-loan-size'), // New
    filterSearch:   $('#filter-search'),
    filterAvailable:$('#filter-available'),
    filteredCount:  $('#filtered-count'),
    // Table
    tbody:          $('#opp-tbody'),
};

// ============================================================
// WebSocket
// ============================================================
function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/live`;
    
    dom.wsStatus.className = 'pill pill-ws';
    dom.wsStatus.innerHTML = '<span class="dot"></span> Connecting...';

    const ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        state.ws = ws;
        state.wsRetries = 0;
        dom.wsStatus.className = 'pill pill-ws connected';
        dom.wsStatus.innerHTML = '<span class="dot"></span> Live';
        console.log('[WS] Connected');
        
        // Heartbeat: Send ping every 10s to keep connection alive
        if (state.pingInterval) clearInterval(state.pingInterval);
        state.pingInterval = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 10000);
    };
    
    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'data_update') {
                handleDataUpdate(msg);
            } else if (msg.type === 'pong') {
                // Heartbeat response, ignore
            }
        } catch (err) {
            console.error('[WS] Parse error:', err);
        }
    };
    
    ws.onclose = () => {
        if (state.pingInterval) clearInterval(state.pingInterval);
        state.ws = null;
        dom.wsStatus.className = 'pill pill-ws error';
        dom.wsStatus.innerHTML = '<span class="dot"></span> Disconnected';
        console.log('[WS] Disconnected');
        
        // Auto-reconnect with backoff
        if (state.wsRetries < state.maxWsRetries) {
            const delay = Math.min(1000 * Math.pow(1.5, state.wsRetries), 30000);
            state.wsRetries++;
            // console.log(`[WS] Reconnecting in ${(delay/1000).toFixed(1)}s (attempt ${state.wsRetries})`);
            setTimeout(connectWebSocket, delay);
        }
    };
    
    ws.onerror = () => {
        dom.wsStatus.className = 'pill pill-ws error';
        dom.wsStatus.innerHTML = '<span class="dot"></span> Error';
    };
}

// ============================================================
// Data handling
// ============================================================
function handleDataUpdate(msg) {
    state.data = msg.data || [];
    state.lastUpdate = msg.timestamp;
    
    dom.dataStatus.className = 'pill pill-data active';
    dom.dataStatus.innerHTML = `<span class="dot"></span> ${state.data.length} tokens`;
    
    applyFiltersAndRender();
    updateKPIs();
    
    // Brief flash to indicate update
    dom.dataStatus.classList.add('flash-update');
    setTimeout(() => dom.dataStatus.classList.remove('flash-update'), 600);
    
    // Update token dropdowns
    populateTokenDropdowns(state.data);
}

function populateTokenDropdowns(data) {
    if (!data || data.length === 0) return;
    
    // Get all unique tokens, sorted
    const tokens = [...new Set(data.map(d => d.currency))].sort();
    
    // Targets
    const targets = ['bot-token', 'borrow-token'];
    
    targets.forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        
        const currentVal = sel.value;
        
        // Clear (keep nothing or rebuild all)
        sel.innerHTML = '';
        
        // Add options
        tokens.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            sel.appendChild(opt);
        });
        
        // Restore selection if possible, otherwise default to commonly used ones or first
        if (tokens.includes(currentVal)) {
            sel.value = currentVal;
        } else if (tokens.includes('ETH') && !currentVal) {
            sel.value = 'ETH';
        }
    });
}

function applyFiltersAndRender() {
    let data = [...state.data];
    
    // Source filter (Server handles strict filtering, but we keep local logic for immediate UI feedback if needed, 
    // or as a backup if we rely on cached state).

    // Source filter - Client Side (Visual only, backing up server)
    const source = dom.filterSource.value;
    if (source === 'okx') {
        data = data.filter(d => d.best_loan_source === 'OKX');
    } else if (source === 'binance') {
        data = data.filter(d => d.best_loan_source === 'Binance');
    }
    
    // APR filter
    const minApr = parseFloat(dom.filterApr.value) || 0;
    if (minApr !== 0) {
        data = data.filter(d => (d.net_apr || 0) >= minApr);
    }
    
    // Search filter
    const search = dom.filterSearch.value.trim().toUpperCase();
    if (search) {
        data = data.filter(d => (d.currency || '').toUpperCase().includes(search));
    }
    
    // Available filter
    const avail = dom.filterAvailable.value;
    if (avail === 'available') {
        data = data.filter(d => d.available === true || d.status === '✅ AVAILABLE');
    } else if (avail === 'unavailable') {
        data = data.filter(d => d.available === false || d.status === '❌ NOT AVAILABLE');
    }
    
    // Sort
    data.sort((a, b) => {
        const va = a[state.sortCol] ?? 0;
        const vb = b[state.sortCol] ?? 0;
        if (typeof va === 'string') {
            return state.sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        return state.sortAsc ? va - vb : vb - va;
    });
    
    state.filtered = data;
    dom.filteredCount.textContent = data.length;
    
    renderTable(data);
}

// ============================================================
// Table rendering
// ============================================================
function renderTable(data) {
    if (data.length === 0) {
        dom.tbody.innerHTML = `
            <tr class="loading-row">
                <td colspan="8">No opportunities matching filters</td>
            </tr>`;
        return;
    }
    
    try {
        // Build HTML efficiently
        const rows = data.map(d => {
            const netApr = d.net_apr || 0;
            const gateApr = d.gate_apr || 0;
            const okxRate = d.okx_loan_rate || 0;
            const binanceRate = d.binance_loan_rate || 0; // Fix variable name binanceRate vs binRate
            const maxLoan = d.okx_avail_loan || 0;
            const source = d.best_loan_source || 'None';
            const isAvailable = d.available === true || d.status === '✅ AVAILABLE';
            
            const effEv = d.effective_ev || 0;
            const gateWd = d.gate_wd_fee_usd || 0;
            const okxWd = d.okx_wd_fee_usd || 0;
            const binWd = d.binance_wd_fee_usd || 0;

            // Determine Borrow Rate based on source
            let borrowRate = 0;
            if (source.toLowerCase().includes('okx')) borrowRate = okxRate;
            else if (source.toLowerCase().includes('binance')) borrowRate = binanceRate;

            // --- New Calculation Logic ---
            const loanSize = parseFloat(dom.filterLoanSize.value) || 1000;
            const dailyEarn = (netApr / 100 / 365) * loanSize;
            
            // Mock Signal (Placeholder Phase 7)
            const signals = ['▲ Early', '▲ Weak', '■ Flat', '▼ Fading'];
            // Hash token name to get consistent signal for demo
            const hash = token => token.split('').reduce((a,b)=>(((a<<5)-a)+b.charCodeAt(0))|0, 0);
            const sigIndex = Math.abs(hash(d.currency)) % 4;
            const signalText = signals[sigIndex];
            const signalClass = sigIndex === 0 ? 'signal-early' : sigIndex === 1 ? 'signal-weak' : sigIndex === 3 ? 'signal-fade' : 'signal-flat';

            return `<tr>
                <td class="cell-token" onclick="window.openChartModal('${d.currency}')" style="cursor:pointer; text-decoration:underline;">${esc(d.currency || '—')} 📊</td>
                <td class="cell-signal ${signalClass}">${signalText}</td>
                <td class="num ${gateApr > 50 ? 'cell-positive' : 'cell-neutral'}">${fmt(gateApr)}</td>
                <td class="num ${borrowRate > 0 ? 'cell-neutral' : 'cell-zero'}">${borrowRate > 0 ? fmt(borrowRate) : '—'}</td>
                <td class="num cell-wd-fee" style="color:var(--text-primary); font-weight:600;"><small>$</small>${fmt(gateWd)}</td>
                <td class="num ${netApr > 50 ? 'cell-positive' : netApr > 0 ? 'cell-neutral' : 'cell-negative'}"><strong>${fmt(netApr)}</strong></td>
                <td class="num cell-daily" style="font-weight:700; color:var(--green);"><small>$</small>${fmt(dailyEarn)}</td>
                <td class="num cell-ev ${effEv > 0 ? 'cell-positive' : 'cell-negative'}" style="font-weight:700;"><small>$</small>${fmt(effEv)}</td>
                <td><span class="cell-source ${sourceClass(source)}">${source}</span></td>
                <td class="num">${maxLoan > 0 ? fmtInt(maxLoan) : '—'}</td>
                <td class="cell-status">${isAvailable ? '✅' : '❌'}</td>
            </tr>`;
        });
        
        dom.tbody.innerHTML = rows.join('');
    } catch (err) {
        console.error("Render Error:", err);
        dom.tbody.innerHTML = `<tr><td colspan="8" style="color:red; text-align:center;">RENDER ERROR: ${err.message}</td></tr>`;
    }
}

// ============================================================
// KPI updates
// ============================================================
function updateKPIs() {
    const data = state.data;
    if (!data.length) return;
    
    const netAprs = data.map(d => d.net_apr || 0);
    const topApr = Math.max(...netAprs);
    // const avgApr = netAprs.reduce((a, b) => a + b, 0) / netAprs.length;
    // const highCount = netAprs.filter(a => a > 50).length;
    
    dom.kpiOppsCount.textContent = data.length;
    dom.kpiBestApr.textContent = fmt(topApr) + '%';
    // dom.kpiTrendCount.textContent = '0'; // Placeholder logic
    
    if (state.lastUpdate) {
        const d = new Date(state.lastUpdate);
        dom.kpiLastUpdate.textContent = d.toLocaleTimeString();
    }
}

// ============================================================
// Collector stats (polling)
// ============================================================
async function fetchCollectorStats() {
    try {
        const res = await fetch('/api/collector/stats');
        const stats = await res.json();
        
        if (stats.total_observations != null) {
            // dom.kpiDbRows.textContent = stats.total_observations.toLocaleString(); // Removed KPI
            dom.collectorStatus.className = 'pill pill-collector active';
            dom.collectorStatus.innerHTML = `<span class="dot"></span> ${stats.unique_tokens || 0} tokens`;
        } else {
            dom.collectorStatus.className = 'pill pill-collector warning';
            dom.collectorStatus.innerHTML = '<span class="dot"></span> No data';
        }
    } catch (err) {
        dom.collectorStatus.className = 'pill pill-collector error';
        dom.collectorStatus.innerHTML = '<span class="dot"></span> Offline';
    }
}

// ============================================================
// Sorting
// ============================================================
function initSorting() {
    $$('.data-table thead th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.col;
            
            if (state.sortCol === col) {
                state.sortAsc = !state.sortAsc;
            } else {
                state.sortCol = col;
                state.sortAsc = false;
            }
            
            // Update header styling
            $$('.data-table thead th').forEach(h => {
                h.classList.remove('active-sort', 'asc');
            });
            th.classList.add('active-sort');
            if (state.sortAsc) th.classList.add('asc');
            
            applyFiltersAndRender();
        });
    });
}

// ============================================================
// Filter event listeners
// ============================================================
function initFilters() {
    dom.filterSource.addEventListener('change', () => {
        // Trigger server fetch when source changes
        fetchDataREST(); 
        // Also apply local filter purely for UI responsiveness until new data arrives
        applyFiltersAndRender();
    });
    dom.filterAvailable.addEventListener('change', applyFiltersAndRender);
    dom.filterApr.addEventListener('input', debounce(applyFiltersAndRender, 300));
    dom.filterLoanSize.addEventListener('input', debounce(applyFiltersAndRender, 300)); // New
    dom.filterSearch.addEventListener('input', debounce(applyFiltersAndRender, 200));
}

// ============================================================
// Refresh button
// ============================================================
function initRefresh() {
    dom.btnRefresh.addEventListener('click', async () => {
        dom.btnRefresh.disabled = true;
        dom.btnRefresh.textContent = '⏳';
        
        try {
            // Try WebSocket first
            if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                const json = await res.json();
                if (json.status === 'ok') {
                    // Trigger manual fetch if WS doesn't push
                    const dataRes = await fetch('/api/opportunities');
                    const dataJson = await dataRes.json();
                    handleDataUpdate(dataJson);
                }
            }
        } catch (err) {
            console.error('Refresh failed:', err);
        }
        
        setTimeout(() => {
            dom.btnRefresh.disabled = false;
            dom.btnRefresh.textContent = '🔄';
        }, 2000);
    });
}

// ============================================================
// Clock
// ============================================================
function updateClock() {
    const now = new Date();
    dom.clock.textContent = now.toLocaleTimeString();
}



// ============================================================
// REST fallback (if WebSocket not available)
// ============================================================
async function fetchDataREST() {
    try {
        const source = dom.filterSource.value;
        const res = await fetch(`/api/opportunities?source=${source}`);
        const json = await res.json();
        handleDataUpdate(json);
    } catch (err) {
        console.error('[REST] Fetch failed:', err);
    }
}


// ============================================================
// Tab navigation
// ============================================================
function initTabs() {
    $$('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.dataset.tab;
            
            // Update buttons
            $$('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Update content
            $$('.tab-content').forEach(c => c.classList.remove('active'));
            const target = document.getElementById(targetId);
            if (target) target.classList.add('active');
        });
    });
}

// ============================================================
// Sniper Bot controls
// ============================================================
function initBotControls() {
    const btnStart = $('#bot-start');
    const btnStop = $('#bot-stop');
    
    if (!btnStart || !btnStop) return;
    
    btnStart.addEventListener('click', async () => {
        const token = $('#bot-token').value;
        const amount = parseFloat($('#bot-amount').value) || 0;
        const ltv = parseFloat($('#bot-ltv').value) || 70;
        const useBrowser = $('#bot-browser').checked;
        const sniperMode = $('#bot-sniper-mode').checked;
        
        btnStart.disabled = true;
        btnStart.textContent = '⏳ Starting...';
        
        try {
            const res = await fetch('/api/bot/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token, amount, ltv, use_browser: useBrowser, sniper_mode: sniperMode }),
            });
            const json = await res.json();
            
            const badge = $('#bot-badge');
            const statusBox = $('#bot-status-box');
            
            if (json.status === 'started') {
                badge.className = 'badge-running';
                badge.innerHTML = '🟢 RUNNING';
                statusBox.innerHTML = `<div class="status-line success">✅ Sniping ${token} | LTV: ${ltv}% | Mode: ${sniperMode ? 'Sniper' : 'Santai'}</div>`;
            } else {
                statusBox.innerHTML = `<div class="status-line error">❌ ${json.message || 'Failed to start'}</div>`;
            }
        } catch (err) {
            $('#bot-status-box').innerHTML = `<div class="status-line error">❌ Error: ${err.message}</div>`;
        }
        
        btnStart.disabled = false;
        btnStart.textContent = '▶️ START SNIPER';
    });
    
    btnStop.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/bot/stop', { method: 'POST' });
            const json = await res.json();
            
            const badge = $('#bot-badge');
            badge.className = 'badge-idle';
            badge.innerHTML = '⚪ IDLE';
            
            $('#bot-status-box').innerHTML = `<div class="status-line info">⏹️ Bot stopped.</div>`;
        } catch (err) {
            $('#bot-status-box').innerHTML = `<div class="status-line error">❌ Error: ${err.message}</div>`;
        }
    });
}

// ============================================================
// OKX Browser actions
// ============================================================
function initBrowserActions() {
    const btnQR = $('#btn-qr-login');
    const btnChrome = $('#btn-chrome-login');
    const btnBorrow = $('#btn-borrow');
    
    if (btnQR) {
        btnQR.addEventListener('click', async () => {
            btnQR.disabled = true;
            btnQR.textContent = '⏳ Launching...';
            $('#login-status').innerHTML = '<div class="status-line info">Launching browser for QR login...</div>';
            
            try {
                const res = await fetch('/api/browser/login', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({method: 'qr'}) });
                const json = await res.json();
                $('#login-status').innerHTML = `<div class="status-line success">${json.message || 'Browser launched!'}</div>`;
            } catch (err) {
                $('#login-status').innerHTML = `<div class="status-line error">❌ ${err.message}</div>`;
            }
            
            btnQR.disabled = false;
            btnQR.textContent = '📱 Launch QR Login';
        });
    }
    
    if (btnChrome) {
        btnChrome.addEventListener('click', async () => {
            btnChrome.disabled = true;
            btnChrome.textContent = '⏳ Launching...';
            $('#login-status').innerHTML = '<div class="status-line info">Launching System Chrome... Close all Chrome windows first!</div>';
            
            try {
                const res = await fetch('/api/browser/login', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({method: 'chrome'}) });
                const json = await res.json();
                $('#login-status').innerHTML = `<div class="status-line success">${json.message || 'Chrome launched!'}</div>`;
            } catch (err) {
                $('#login-status').innerHTML = `<div class="status-line error">❌ ${err.message}</div>`;
            }
            
            btnChrome.disabled = false;
            btnChrome.textContent = '💻 Login via System Chrome';
        });
    }
    
    if (btnBorrow) {
        btnBorrow.addEventListener('click', async () => {
            const token = $('#borrow-token').value;
            const amount = $('#borrow-amount').value;
            
            if (!amount) {
                $('#browser-logs').textContent = '❌ Please enter amount';
                return;
            }
            
            btnBorrow.disabled = true;
            btnBorrow.textContent = '⏳ Executing...';
            $('#browser-logs').textContent = `Executing borrow: ${amount} ${token}...`;
            
            try {
                const res = await fetch('/api/browser/borrow', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token, amount }),
                });
                const json = await res.json();
                $('#browser-logs').textContent = json.message || 'Borrow process started in background.';
            } catch (err) {
                $('#browser-logs').textContent = `❌ Error: ${err.message}`;
            }
            
            btnBorrow.disabled = false;
            btnBorrow.textContent = '💸 Execute Borrow Now';
        });
    }
}

// ============================================================
// Bot status polling
// ============================================================
async function pollBotStatus() {
    try {
        const res = await fetch('/api/bot/status');
        const json = await res.json();
        
        const badge = $('#bot-badge');
        const statusBox = $('#bot-status-box');
        const logBox = $('#bot-logs');
        
        if (json.running) {
            badge.className = 'badge-running';
            badge.innerHTML = '🟢 RUNNING';
            statusBox.innerHTML = `<div class="status-line success">${esc(json.status_msg || 'Running...')}</div>`;
        } else {
            badge.className = 'badge-idle';
            badge.innerHTML = '⚪ IDLE';
        }
        
        if (json.logs && json.logs.length > 0) {
            logBox.textContent = json.logs.join('\n');
            logBox.scrollTop = logBox.scrollHeight;
        }
    } catch (err) {
        // Silent fail — bot status is optional
    }
}

// ============================================================
// Session status
// ============================================================
async function fetchSessionStatus() {
    const icon = $('#session-icon');
    const text = $('#session-text');
    const detail = $('#session-detail');
    const banner = $('#session-banner');
    
    if (!icon || !text) return;
    
    try {
        const res = await fetch('/api/browser/session');
        const s = await res.json();
        
        if (s.session_exists) {
            const ageMin = s.age_minutes || 0;
            let ageStr;
            if (ageMin < 60) {
                ageStr = `${ageMin} menit lalu`;
            } else if (ageMin < 1440) {
                ageStr = `${Math.floor(ageMin / 60)} jam lalu`;
            } else {
                ageStr = `${Math.floor(ageMin / 1440)} hari lalu`;
            }
            
            // Session age warning
            if (ageMin > 1440) {
                // > 24 hours — likely expired
                icon.textContent = '⚠️';
                text.textContent = `Session Expired? (Login: ${s.last_login})`;
                text.style.color = 'var(--amber)';
                banner.style.borderColor = 'var(--amber)';
            } else {
                icon.textContent = '✅';
                text.textContent = `Browser Session Active (Login: ${s.last_login})`;
                text.style.color = 'var(--green)';
                banner.style.borderColor = 'var(--green-dim)';
            }
            
            let detailParts = [ageStr];
            if (s.cookie_count > 0) detailParts.push(`${s.cookie_count} cookies`);
            if (s.profile_exists) detailParts.push('Profile saved');
            detail.textContent = detailParts.join(' · ');
        } else {
            icon.textContent = '❌';
            text.textContent = 'No Browser Session Found! Please Login first.';
            text.style.color = 'var(--red)';
            banner.style.borderColor = 'var(--red-dim)';
            detail.textContent = 'okx_session.json not found';
        }
    } catch (err) {
        icon.textContent = '⚠️';
        text.textContent = 'Cannot check session (server error)';
        text.style.color = 'var(--amber)';
        detail.textContent = '';
    }
}

// ============================================================
// Predictions Logic
// ============================================================
// ============================================================
// Predictions Logic (Phase 2: Probabilistic)
// ============================================================
async function loadPredictions() {
    const tbody = $('#pred-tbody');
    const loading = $('#pred-loading');
    const empty = $('#pred-empty');
    const results = $('#pred-results');
    
    if (!tbody) return;
    
    // Reset UI
    results.style.display = 'none';
    empty.style.display = 'none';
    loading.style.display = 'block';
    
    try {
        const res = await fetch('/api/predictions?limit=20');
        const json = await res.json();
        const data = json.data || [];
        
        loading.style.display = 'none';
        
        if (data.length === 0) {
            empty.style.display = 'block';
            return;
        }
        
        results.style.display = 'block';
        
        const rows = data.map(d => {
            // Unpack Probabilistic Data
            const regime = d.regime || 'Unknown';
            const signal = d.signal || 'NEUTRAL';
            const confidence = d.confidence || 0;
            const vol = d.volatility || 0;
            
            // Visual Styles associated with Regime
            let regimeClass = 'badge-idle';
            if (regime === 'Rising') regimeClass = 'badge-running'; // Green
            else if (regime === 'High') regimeClass = 'badge-collecting'; // Blue
            else if (regime === 'Decay') regimeClass = 'badge-error'; // Red
            
            // Signal Badge
            let signalClass = 'signal-flat';
            let signalIcon = '⚪ Neutral';
            if (signal === 'BUY') {
                signalClass = 'signal-strong';
                signalIcon = '🟢 LONG';
            } else if (signal === 'SELL') {
                signalClass = 'signal-fade'; // using fade style for sell/red
                signalIcon = '🔴 SHORT';
            } 
            
            // Confidence Bar Color
            let barColor = 'var(--text-muted)';
            if (confidence > 80) barColor = 'var(--green)';
            else if (confidence > 50) barColor = 'var(--blue)';
            else if (confidence < 30) barColor = 'var(--red)';

            return `<tr>
                <td class="cell-token" onclick="window.openChartModal('${d.token}')" style="cursor:pointer; text-decoration:underline;">${esc(d.token)} 📊</td>
                <td class="num font-bold">${fmt(d.current_apr)}%</td>
                <td><span class="${regimeClass}" style="font-size:0.8rem; padding: 2px 8px;">${regime}</span></td>
                <td class="cell-signal ${signalClass}">${signalIcon}</td>
                <td class="num">${vol.toFixed(3)}</td>
                <td>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <div class="progress-bar" style="width:80px; background:var(--bg-tertiary)">
                            <div class="progress-fill" style="width: ${confidence}%; background:${barColor}"></div>
                        </div>
                        <small>${confidence}%</small>
                    </div>
                </td>
            </tr>`;
        });
        
        tbody.innerHTML = rows.join('');
        
    } catch (err) {
        loading.innerHTML = `<div class="status-line error">❌ Failed to load predictions: ${err.message}</div>`;
    }
}

function initPredictions() {
    const btn = document.querySelector('[data-tab="tab-predictions"]');
    if (btn) {
        btn.addEventListener('click', loadPredictions);
    }
}


// ============================================================
// Bootstrap
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initPredictions();
    initSorting();
    initFilters();
    initRefresh();
    initBotControls();
    initBrowserActions();
    
    // Clock
    updateClock();
    setInterval(updateClock, 1000);
    
    // Collector stats
    fetchCollectorStats();
    setInterval(fetchCollectorStats, 30000);
    
    // Bot status polling
    pollBotStatus();
    setInterval(pollBotStatus, 5000);
    
    // Session status
    fetchSessionStatus();
    setInterval(fetchSessionStatus, 60000);
    
    // Connect WebSocket
    connectWebSocket();
    
    // REST fallback: if no WS data after 3s, fetch via REST
    setTimeout(() => {
        if (state.data.length === 0) {
            console.log('[REST] WS data not received, falling back to REST');
            fetchDataREST().catch(err => {
                const el = document.getElementById('loading');
                if (el) el.innerHTML = `<div class="status-line error">❌ Connection Failed: Server Unreachable<br><small>Check python dev.py console</small></div>`;
            });
        }
    }, 3000);
});


// ============================================================
// CHART MODAL & VISUALIZATION
// ============================================================
let chartInstance = null;

window.openChartModal = async function(token) {
    const modal = document.getElementById('chart-modal');
    const title = document.getElementById('chart-title');
    const ctx = document.getElementById('aprChart').getContext('2d');
    
    if (!modal) return;
    
    title.innerHTML = `APR History: <span style="color:var(--green)">${token}</span>`;
    modal.classList.add('visible');
    
    // Destroy previous chart
    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }
    
    // Show loading text on canvas? Or just wait.
    
    // Fetch Data
    try {
        const res = await fetch(`/api/history/${token}`);
        const data = await res.json();
        
        if (!data || data.length === 0) {
            alert('No history data available for this token yet.');
            return;
        }
        
        // Show Trend
        if (data.trend) {
            const t = data.trend;
            let color = 'var(--text-muted)';
            let arrow = '➡️';
            if (t.trend === 'UP') { color = 'var(--green)'; arrow = '↗️'; }
            if (t.trend === 'DOWN') { color = 'var(--red)'; arrow = '↘️'; }
            
            title.innerHTML = `APR History: <span style="color:var(--green)">${token}</span> 
                <span style="font-size:0.8rem; background:${color}20; color:${color}; padding:4px 8px; border-radius:4px; margin-left:10px;">
                ${arrow} ${t.trend} (${t.strength})
                </span>`;
        }
        
        renderChart(ctx, data.data, token);
        
    } catch (err) {
        console.error('Failed to load chart data:', err);
        title.innerHTML += ' <span style="color:var(--red)">(Error loading data)</span>';
    }
};

// Close Modal Logic
document.querySelector('.close-modal').addEventListener('click', () => {
    document.getElementById('chart-modal').classList.remove('visible');
});

window.onclick = function(event) {
    const modal = document.getElementById('chart-modal');
    if (event.target === modal) {
        modal.classList.remove('visible');
    }
};

function renderChart(ctx, history, token) {
    // History is array of {timestamp, net_apr, gate_apr, borrow_rate, source}
    // Sort by time just in case
    history.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    
    const labels = history.map(d => {
        const date = new Date(d.timestamp);
        return date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    });
    
    const netAprs = history.map(d => d.net_apr);
    const gateAprs = history.map(d => d.gate_apr);
    const borrowRates = history.map(d => d.borrow_rate);
    
    if (netAprs.length === 0) {
        // Handle empty
        return;
    }

    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Net APR',
                    data: netAprs,
                    borderColor: '#22c55e', // Green
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true,
                    pointRadius: 2
                },
                {
                    label: 'Gate Earn',
                    data: gateAprs,
                    borderColor: '#3b82f6', // Blue
                    borderWidth: 1,
                    borderDash: [5, 5],
                    tension: 0.3,
                    pointRadius: 0
                },
                {
                    label: 'Borrow Cost',
                    data: borrowRates,
                    borderColor: '#ef4444', // Red
                    borderWidth: 1,
                    borderDash: [2, 2],
                    tension: 0.3,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    labels: { color: '#9ca3af' }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                x: {
                    grid: { color: '#1f2937' },
                    ticks: { color: '#6b7280' }
                },
                y: {
                    grid: { color: '#1f2937' },
                    ticks: { color: '#6b7280' }
                }
            }
        }
    });
}




