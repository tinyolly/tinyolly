import { initTabs, startAutoRefresh, switchTab, toggleAutoRefresh } from './tabs.js';
import { loadStats, loadLogs, loadSpans } from './api.js';
import { initTheme, toggleTheme } from './theme.js';
import { initHideTinyOllyToggle, toggleHideTinyOlly } from './filter.js';
import {
    showTraceDetail,
    showTracesList,
    toggleTraceJSON,
    copyTraceJSON,
    downloadTraceJSON,
    showLogsForTrace,
    clearLogFilter,
    filterLogs
} from './render.js';

import { clearTraceFilter, filterTraces } from './traces.js';
import { clearSpanFilter, filterSpans } from './spans.js';
import { filterMetrics } from './metrics.js';

import { debounce } from './utils.js';

// Expose functions globally for HTML onclick handlers
window.switchTab = switchTab;
window.toggleTheme = toggleTheme;
window.toggleAutoRefresh = toggleAutoRefresh;
window.toggleHideTinyOlly = toggleHideTinyOlly;
window.showTraceDetail = showTraceDetail;
window.showTracesList = showTracesList;
window.toggleTraceJSON = toggleTraceJSON;
window.copyTraceJSON = copyTraceJSON;
window.downloadTraceJSON = downloadTraceJSON;
window.showLogsForTrace = showLogsForTrace;
window.loadLogs = loadLogs;
window.loadSpans = loadSpans;
window.clearLogFilter = clearLogFilter;
window.filterLogs = filterLogs;
window.clearTraceFilter = clearTraceFilter;
window.clearSpanFilter = clearSpanFilter;
window.filterSpans = filterSpans;
window.filterTraces = filterTraces;

// Global error handler
window.onerror = function (message, source, lineno, colno, error) {
    console.error('Global error caught:', message, error);
    return false;
};

// Initialize after DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    try {
        initTheme();
        initHideTinyOllyToggle();

        // Tab initialization now handles URL parameters internally
        initTabs();
        loadStats();

        // Attach log search event listener with debounce
        const logSearch = document.getElementById('log-search');
        if (logSearch) {
            logSearch.addEventListener('keyup', debounce(filterLogs, 300));
        }

        // Attach span search event listener with debounce
        const spanSearch = document.getElementById('span-search');
        if (spanSearch) {
            spanSearch.addEventListener('keyup', debounce(filterSpans, 300));
        }

        // Attach trace search event listener with debounce
        const traceSearch = document.getElementById('trace-search');
        if (traceSearch) {
            traceSearch.addEventListener('keyup', debounce(filterTraces, 300));
        }

        // Attach metric search event listener with debounce
        const metricSearch = document.getElementById('metric-search');
        if (metricSearch) {
            metricSearch.addEventListener('keyup', debounce(filterMetrics, 300));
        }

        if (localStorage.getItem('tinyolly-auto-refresh') !== 'false') {
            startAutoRefresh();
        }

        // Handle deep links (traceId, spanId, search params)
        handleDeepLink();
    } catch (error) {
        console.error('Error during initialization:', error);
    }
});

/** Process URL deep link parameters after init (non-traceId links) */
function handleDeepLink() {
    const urlParams = new URLSearchParams(window.location.search);
    const traceId = urlParams.get('traceId');
    const spanId = urlParams.get('spanId');
    const search = urlParams.get('search');

    // traceId is handled by initTabs directly — skip here
    if (traceId) return;

    if (spanId) {
        // Deep link to spans filtered by spanId
        switchTab('spans', null, true);
        setTimeout(() => {
            const searchInput = document.getElementById('span-search');
            if (searchInput) {
                searchInput.value = spanId;
                filterSpans();
            }
        }, 500);
    } else if (search) {
        // Deep link with search query for current tab
        const tab = urlParams.get('tab') || 'logs';
        const searchIds = { traces: 'trace-search', spans: 'span-search', logs: 'log-search', metrics: 'metric-search' };
        const filterFns = { traces: filterTraces, spans: filterSpans, logs: filterLogs, metrics: filterMetrics };
        const searchId = searchIds[tab];
        if (searchId) {
            setTimeout(() => {
                const searchInput = document.getElementById(searchId);
                if (searchInput) {
                    searchInput.value = search;
                    if (filterFns[tab]) filterFns[tab]();
                }
            }, 500);
        }
    }
}
