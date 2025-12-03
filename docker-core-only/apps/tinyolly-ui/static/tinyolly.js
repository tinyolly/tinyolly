import { initTabs, startAutoRefresh, switchTab, toggleAutoRefresh } from './tabs.js';
import { loadStats, loadLogs, loadSpans } from './api.js';
import { initTheme, toggleTheme } from './theme.js';
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

import { clearTraceFilter } from './traces.js';
import { clearSpanFilter, filterSpans } from './spans.js';

import { debounce } from './utils.js';

// Expose functions globally for HTML onclick handlers
window.switchTab = switchTab;
window.toggleTheme = toggleTheme;
window.toggleAutoRefresh = toggleAutoRefresh;
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

// Global error handler
window.onerror = function (message, source, lineno, colno, error) {
    console.error('Global error caught:', message, error);
    return false;
};

// Initialize after DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    try {
        initTheme();

        // Check URL for tab parameter (for bookmarks/direct links)
        const urlParams = new URLSearchParams(window.location.search);
        const urlTab = urlParams.get('tab');
        if (urlTab) {
            localStorage.setItem('tinyolly-active-tab', urlTab);
        }

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

        // Metric search removed in OTEL rewrite (filtering now done via resource/attribute filters)

        if (localStorage.getItem('tinyolly-auto-refresh') !== 'false') {
            startAutoRefresh();
        }
    } catch (error) {
        console.error('Error during initialization:', error);
    }
});
