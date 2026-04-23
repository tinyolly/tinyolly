/**
 * Tabs Module - Manages tab switching, auto-refresh, and browser history
 */
import { loadLogs, loadSpans, loadTraces, loadMetrics, loadServiceMap, loadServiceCatalog, loadCollector, initCollector } from './api.js';
import { showTracesList, isSpanDetailOpen } from './render.js';
import { clearMetricSearch } from './metrics.js';

let currentTab = 'traces';
let autoRefreshInterval = null;
let autoRefreshEnabled = true;
const TAB_REFRESH_INTERVAL_MS = {
    traces: 5000,
    spans: 5000,
    logs: 5000,
    metrics: 8000,
    catalog: 20000,
    map: 20000,
    'ai-agents': 10000,
};
const STATS_REFRESH_INTERVAL_MS = 10000;
let lastTabRefreshAt = 0;
let lastStatsRefreshAt = 0;
try {
    autoRefreshEnabled = localStorage.getItem('tinyolly-auto-refresh') !== 'false';
} catch (e) {
    console.warn('LocalStorage access failed:', e);
}

export function getCurrentTab() {
    return currentTab;
}

export function initTabs() {
    // Check URL parameter first (for bookmarks/direct links)
    const urlParams = new URLSearchParams(window.location.search);
    const urlTab = urlParams.get('tab');
    const traceId = urlParams.get('traceId');

    // Always default to 'logs' tab when opening the base URL
    // Only use URL parameter if explicitly provided
    const savedTab = urlTab || 'logs';

    if (traceId && savedTab === 'traces') {
        // Deep link to a specific trace — activate tab UI without loading trace list
        currentTab = 'traces';
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        const btn = document.querySelector('.tab[data-tab="traces"]');
        if (btn) btn.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        const contentDiv = document.getElementById('traces-content');
        if (contentDiv) contentDiv.classList.add('active');
        // Show detail directly
        import('./traces.js').then(module => module.showTraceDetail(traceId));
    } else {
        switchTab(savedTab, null, true); // true = initial load, don't push to history
    }
    updateAutoRefreshButton();

    // Handle browser back/forward buttons
    window.addEventListener('popstate', (event) => {
        if (event.state && event.state.tab) {
            switchTab(event.state.tab, null, true);
            // If navigating back to a trace detail, re-open it
            if (event.state.traceId) {
                import('./traces.js').then(module => {
                    setTimeout(() => module.showTraceDetail(event.state.traceId), 300);
                });
            }
        }
    });
}

export function switchTab(tabName, element, fromHistory = false) {
    // Clear metric search when leaving metrics tab
    if (currentTab === 'metrics' && tabName !== 'metrics') {
        clearMetricSearch();
    }

    currentTab = tabName;
    try {
        localStorage.setItem('tinyolly-active-tab', tabName);
    } catch (e) { console.warn('LocalStorage access failed:', e); }

    // Update browser history (only if not from history navigation)
    if (!fromHistory) {
        const url = new URL(window.location);
        url.searchParams.set('tab', tabName);
        window.history.pushState({ tab: tabName }, '', url);
    }

    // Update tab buttons
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    if (element) {
        element.classList.add('active');
    } else {
        const btn = document.querySelector(`.tab[data-tab="${tabName}"]`);
        if (btn) btn.classList.add('active');
    }

    // Update tab content
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

    const contentId = `${tabName}-content`;
    const contentDiv = document.getElementById(contentId);
    if (contentDiv) {
        contentDiv.classList.add('active');
    }

    // Load data
    if (tabName === 'logs') loadLogs();
    else if (tabName === 'spans') {
        import('./spans.js').then(spansModule => {
            const serviceFilter = spansModule.getServiceFilter ? spansModule.getServiceFilter() : null;
            loadSpans(serviceFilter);
        });
    }
    else if (tabName === 'traces') {
        // Reset to list view when switching to traces tab
        showTracesList();
    }
    else if (tabName === 'metrics') loadMetrics();
    else if (tabName === 'catalog') loadServiceCatalog();
    else if (tabName === 'map') loadServiceMap();
    else if (tabName === 'collector') {
        initCollector();
        loadCollector();
    }
    else if (tabName === 'ai-agents') {
        import('./aiAgents.js').then(module => module.loadAISessions());
    }
}

export function startAutoRefresh() {
    stopAutoRefresh();

    autoRefreshInterval = setInterval(() => {
        const now = Date.now();

        // Don't refresh if user has an active search filter on the current tab
        const searchIds = {
            traces: 'trace-search',
            spans: 'span-search',
            logs: 'log-search',
            metrics: 'metric-search'
        };
        const searchId = searchIds[currentTab];
        if (searchId) {
            const searchInput = document.getElementById(searchId);
            if (searchInput && searchInput.value.trim() !== '') {
                return; // Skip refresh while user is filtering
            }
        }

        const tabInterval = TAB_REFRESH_INTERVAL_MS[currentTab] || 5000;
        const tabRefreshDue = now - lastTabRefreshAt >= tabInterval;

        // Don't refresh if a span detail is open
        if (currentTab === 'spans' && isSpanDetailOpen()) {
            return;
        }

        // Don't refresh if this tab is not due yet.
        if (!tabRefreshDue) {
            if (now - lastStatsRefreshAt >= STATS_REFRESH_INTERVAL_MS) {
                lastStatsRefreshAt = now;
                import('./api.js').then(module => module.loadStats());
            }
            return;
        }

        // Don't refresh metrics if a chart is open
        if (currentTab === 'metrics') {
            import('./metrics.js').then(module => {
                if (module.isMetricChartOpen && module.isMetricChartOpen()) {
                    return;
                } else {
                    lastTabRefreshAt = now;
                    loadMetrics();
                }
            });
        } else if (currentTab === 'traces' && !document.getElementById('trace-detail-view').style.display.includes('block')) {
            lastTabRefreshAt = now;
            loadTraces();
        } else if (currentTab === 'spans') {
            import('./spans.js').then(spansModule => {
                const serviceFilter = spansModule.getServiceFilter ? spansModule.getServiceFilter() : null;
                lastTabRefreshAt = now;
                loadSpans(serviceFilter, { background: true });
            });
        } else if (currentTab === 'logs') {
            import('./render.js').then(module => {
                if (module.isLogJsonOpen && module.isLogJsonOpen()) {
                    return;
                } else {
                    lastTabRefreshAt = now;
                    loadLogs(null, { background: true });
                }
            });
        } else if (currentTab === 'catalog') {
            lastTabRefreshAt = now;
            loadServiceCatalog();
        } else if (currentTab === 'map') {
            lastTabRefreshAt = now;
            loadServiceMap();
        } else if (currentTab === 'ai-agents') {
            import('./aiAgents.js').then(module => {
                // Don't refresh if JSON view is open or detail view is open
                if (module.isAISessionJsonOpen && module.isAISessionJsonOpen()) {
                    return;
                }
                if (document.getElementById('ai-detail-view').style.display.includes('block')) {
                    return;
                }
                lastTabRefreshAt = now;
                module.loadAISessions();
            });
        }
        // Don't auto-refresh collector tab - user is editing config

        // Also refresh stats (independent, slower cadence)
        if (now - lastStatsRefreshAt >= STATS_REFRESH_INTERVAL_MS) {
            lastStatsRefreshAt = now;
            import('./api.js').then(module => module.loadStats());
        }

    }, 1000);
}

export function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

export function toggleAutoRefresh() {
    autoRefreshEnabled = !autoRefreshEnabled;
    try {
        localStorage.setItem('tinyolly-auto-refresh', autoRefreshEnabled);
    } catch (e) { console.warn('LocalStorage access failed:', e); }

    if (autoRefreshEnabled) {
        startAutoRefresh();
    } else {
        stopAutoRefresh();
    }
    updateAutoRefreshButton();
}

function updateAutoRefreshButton() {
    const btn = document.getElementById('auto-refresh-btn');
    const icon = document.getElementById('refresh-icon');
    const state = document.getElementById('refresh-state');
    const text = document.getElementById('refresh-text');

    if (!btn || !icon || !state || !text) return;

    if (autoRefreshEnabled) {
        icon.textContent = '⏸';
        btn.title = 'Pause auto-refresh';
        state.textContent = 'LIVE';
        text.textContent = 'Pause Auto-Refresh';
        btn.classList.remove('paused');
        btn.setAttribute('aria-pressed', 'true');
    } else {
        icon.textContent = '▶';
        btn.title = 'Resume auto-refresh';
        state.textContent = 'PAUSED';
        text.textContent = 'Resume Auto-Refresh';
        btn.classList.add('paused');
        btn.setAttribute('aria-pressed', 'false');
    }
}

