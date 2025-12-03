/**
 * Logs Module - Handles log list, filtering, and detail views
 */
import { formatTraceId, copyToClipboard, downloadJson, formatTimestamp, renderJsonDetailView, getSeverityColor, renderActionButton, renderEmptyState, filterTableRows, copyJsonWithFeedback, downloadTelemetryJson, closeAllExpandedItems } from './utils.js';

let currentLogs = [];
let selectedLogIndex = null;
let displayedLogsCount = 50;
const LOGS_PER_PAGE = 50;

export function renderLogs(logs, containerId = 'logs-container') {
    const container = document.getElementById(containerId);
    currentLogs = logs;
    selectedLogIndex = null;
    displayedLogsCount = LOGS_PER_PAGE;

    // Clear JSON view when rendering new logs
    // (Inline views are cleared by re-rendering list)

    if (!container) {
        console.error(`Container ${containerId} not found`);
        return;
    }

    if (logs.length === 0) {
        container.innerHTML = renderEmptyState('📝', 'No logs found');
        return;
    }

    // Preserve current search filter
    const searchInput = document.getElementById('log-search');
    const currentFilter = searchInput ? searchInput.value : '';

    renderLogList(container, logs.slice(0, displayedLogsCount), logs.length);

    // Restore search input value (in case it was cleared during render)
    if (currentFilter && searchInput) {
        searchInput.value = currentFilter;
    }

    // Re-apply search filter if one was active
    if (currentFilter) {
        setTimeout(() => filterLogs(), 10);
    }

    // Add click handlers using event delegation
    // Remove existing listener to avoid duplicates if renderLogs is called multiple times
    // (Actually, replacing innerHTML removes listeners on children, but not on container itself if added via addEventListener)
    // Ideally we should use a named function and removeEventListener, or check if listener attached.
    // For simplicity in this refactor, we'll assume container is fresh or we accept potential duplicate listeners on container (which is bad).
    // Better approach: attach listener once in init, or use "onclick" property.
    container.onclick = (e) => handleLogClick(e);
}

function renderLogList(container, logsToShow, totalLogs) {
    const limitNote = `<div style="padding: 10px; text-align: center; color: var(--text-muted); font-size: 12px;">Showing ${logsToShow.length} of ${totalLogs} logs</div>`;

    // Build table with headers
    const headerRow = `
        <div class="log-header-row" style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 2px solid var(--border-color); background: var(--bg-secondary); font-weight: bold; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
            <div style="flex: 0 0 100px;">Time</div>
            <div style="flex: 0 0 120px;">ServiceName</div>
            <div style="flex: 0 0 60px;">Severity</div>
            <div style="flex: 0 0 180px;">traceId</div>
            <div style="flex: 0 0 140px;">spanId</div>
            <div style="flex: 1; min-width: 200px;">Message</div>
        </div>
    `;

    const logsHtml = logsToShow.map((log, index) => {
        const timestamp = formatTimestamp(log.timestamp);

        const severity = log.severity || 'INFO';
        const severityColor = getSeverityColor(severity);
        const traceId = log.traceId || log.trace_id;
        const spanId = log.spanId || log.span_id;

        return `
            <div class="log-row" data-log-index="${index}" style="display: flex; flex-direction: row; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 1px solid var(--border-color); font-size: 11px; cursor: pointer;">
                <div style="flex: 0 0 100px; font-family: 'JetBrains Mono', monospace; color: var(--text-muted);">${timestamp}</div>
                <div style="flex: 0 0 120px; color: var(--text-main); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${log.service_name || log.service || ''}">${log.service_name || log.service || '-'}</div>
                <div style="flex: 0 0 60px; font-weight: 600; font-size: 10px; color: ${severityColor};">${severity}</div>
                <div style="flex: 0 0 180px; font-family: 'JetBrains Mono', monospace; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${traceId || ''}">
                    ${traceId ? `<a class="log-trace-link" data-trace-id="${traceId}" style="color: var(--primary); cursor: pointer; text-decoration: none; font-family: 'JetBrains Mono', monospace;">${formatTraceId(traceId)}</a>` : '<span style="color: var(--text-muted);">-</span>'}
                </div>
                <div style="flex: 0 0 140px; font-family: 'JetBrains Mono', monospace; font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${spanId || ''}">
                    ${spanId ? `<a class="log-span-link" data-span-id="${spanId}" style="color: var(--primary); cursor: pointer; text-decoration: none; font-family: 'JetBrains Mono', monospace;">${formatTraceId(spanId)}</a>` : '<span style="color: var(--text-muted);">-</span>'}
                </div>
                <div style="flex: 1; min-width: 200px; color: var(--text-main); word-break: break-word;">${log.message || ''}</div>
            </div>
        `;
    }).join('');

    let loadMoreHtml = '';
    if (logsToShow.length < totalLogs) {
        loadMoreHtml = `
            <div style="text-align: center; padding: 20px;">
                <button id="load-more-logs-btn" style="padding: 8px 16px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 4px; color: var(--text-main); cursor: pointer;">
                    Load More Logs (${totalLogs - logsToShow.length} remaining)
                </button>
            </div>
        `;
    }

    container.innerHTML = limitNote + headerRow + logsHtml + loadMoreHtml;

    const loadMoreBtn = document.getElementById('load-more-logs-btn');
    if (loadMoreBtn) {
        loadMoreBtn.onclick = () => {
            displayedLogsCount += LOGS_PER_PAGE;
            renderLogList(container, currentLogs.slice(0, displayedLogsCount), currentLogs.length);
            // Re-apply filter
            filterLogs();
        };
    }
}

function handleLogClick(e) {
    // Handle trace link clicks
    const traceLink = e.target.closest('.log-trace-link');
    if (traceLink) {
        e.preventDefault();
        e.stopPropagation(); // Prevent row click
        const traceId = traceLink.dataset.traceId;
        if (traceId && window.showTraceDetail) {
            // Switch to traces tab first
            if (window.switchTab) {
                window.switchTab('traces');
            }
            // Then show the trace detail
            setTimeout(() => window.showTraceDetail(traceId), 100);
        }
        return;
    }

    // Handle span link clicks
    const spanLink = e.target.closest('.log-span-link');
    if (spanLink) {
        e.preventDefault();
        e.stopPropagation(); // Prevent row click
        const spanId = spanLink.dataset.spanId;

        if (spanId) {
            // Switch to spans tab
            if (window.switchTab) {
                window.switchTab('spans');
            }

            // Wait for spans to load, then find and click the span row
            setTimeout(() => {
                // Find the span row by its data-span-id attribute
                const spanRow = document.querySelector(`.trace-item[data-span-id="${spanId}"]`);
                if (spanRow) {
                    // Programmatically click the span row to open its detail
                    spanRow.click();
                    // Scroll to the span
                    spanRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }, 300); // Give more time for spans to render
        }
        return;
    }

    // Handle log row click
    const logRow = e.target.closest('.log-row');
    if (logRow) {
        const index = parseInt(logRow.dataset.logIndex);
        showLogJson(index);
    }
}

function showLogJson(index) {
    if (!currentLogs || !currentLogs[index]) return;

    const log = currentLogs[index];
    const logRow = document.querySelector(`.log-row[data-log-index="${index}"]`);
    if (!logRow) return;

    // Check if JSON view is already open for this row
    const existingJsonView = logRow.nextElementSibling;
    if (existingJsonView && existingJsonView.classList.contains('log-json-row')) {
        // Toggle close
        existingJsonView.remove();
        logRow.style.background = '';
        selectedLogIndex = null;
        return;
    }

    // Close any other open JSON views
    document.querySelectorAll('.log-json-row').forEach(row => row.remove());
    document.querySelectorAll('.log-row').forEach(row => row.style.background = '');

    // Highlight selected row
    logRow.style.background = 'var(--bg-hover)';
    selectedLogIndex = index;

    // Create buttons HTML
    const buttonsHtml = `
        ${renderActionButton(`copy-log-json-btn-${index}`, 'Copy JSON', 'primary')}
        ${renderActionButton(`download-log-json-btn-${index}`, 'Download JSON', 'primary')}
        ${renderActionButton(`close-log-json-btn-${index}`, 'Close', 'primary')}
        <span id="copy-log-json-feedback-${index}" style="color: var(--success); font-size: 12px; display: none; margin-left: 8px;">Copied!</span>
    `;

    const title = `
        Log Details
        <span style="font-weight: normal; color: var(--text-muted); font-size: 0.9em; margin-left: 8px; font-family: 'JetBrains Mono', monospace;">
            ${new Date(log.timestamp * 1000).toLocaleString()}
        </span>
    `;

    // Create JSON view row
    const jsonRow = document.createElement('div');
    jsonRow.className = 'log-json-row';
    jsonRow.style.background = 'var(--bg-card)';
    jsonRow.style.borderBottom = '1px solid var(--border-color)';
    jsonRow.style.padding = '0 16px'; // Add padding to align with row content

    // Use shared render function
    jsonRow.innerHTML = renderJsonDetailView(log, title, buttonsHtml);

    // Insert after the log row
    logRow.parentNode.insertBefore(jsonRow, logRow.nextSibling);

    // Attach handlers for the buttons
    document.getElementById(`copy-log-json-btn-${index}`).onclick = (e) => {
        e.stopPropagation();
        copyJsonWithFeedback(log, `copy-log-json-feedback-${index}`);
    };

    document.getElementById(`download-log-json-btn-${index}`).onclick = (e) => {
        e.stopPropagation();
        downloadTelemetryJson(log, 'log', log.timestamp);
    };

    document.getElementById(`close-log-json-btn-${index}`).onclick = (e) => {
        e.stopPropagation();
        jsonRow.remove();
        logRow.style.background = '';
        selectedLogIndex = null;
    };
}

export function clearLogFilter() {
    const filterInput = document.getElementById('trace-id-filter');
    const searchInput = document.getElementById('log-search');
    if (filterInput) {
        filterInput.value = '';
    }
    if (searchInput) {
        searchInput.value = '';
    }
    // Trigger filter to show all logs
    filterLogs();
}

// Filter logs based on search input (searches all log content)
export function filterLogs() {
    const searchInput = document.getElementById('log-search');
    if (!searchInput) return;

    const logRows = document.querySelectorAll('.log-row');
    // Search entire row text content
    const selectors = ['*']; // Searches all text in the row
    
    filterTableRows(logRows, searchInput.value, selectors, 'flex');
}

export function isLogJsonOpen() {
    return selectedLogIndex !== null;
}


// Close all expanded log details
window.closeAllLogs = () => {
    closeAllExpandedItems({
        containers: ['.log-json-row'],
        classes: [{ selector: '.log-row', style: { background: '' } }],
        callbacks: [() => { selectedLogIndex = null; }]
    });
};
