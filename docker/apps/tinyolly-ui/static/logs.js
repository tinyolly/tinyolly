/**
 * Logs Module - Handles log list, filtering, and detail views
 */
import { formatTraceId, copyToClipboard, downloadJson, formatTimestamp, renderJsonDetailView, getSeverityColor, renderActionButton, renderEmptyState, filterTableRows, copyJsonWithFeedback, downloadTelemetryJson, closeAllExpandedItems, renderTableHeader, renderLimitNote, preserveSearchFilter } from './utils.js';

const MAX_LOGS_IN_MEMORY = 1000; // Prevent unbounded memory growth
let currentLogs = [];
let selectedLogIndex = null;
let displayedLogsCount = 50;
const LOGS_PER_PAGE = 50;

export function renderLogs(logs, containerId = 'logs-container') {
    const container = document.getElementById(containerId);

    // Apply memory limit to prevent unbounded growth
    if (logs.length > MAX_LOGS_IN_MEMORY) {
        currentLogs = logs.slice(-MAX_LOGS_IN_MEMORY);
    } else {
        currentLogs = logs;
    }

    selectedLogIndex = null;
    displayedLogsCount = LOGS_PER_PAGE;

    // Clear JSON view when rendering new logs
    // (Inline views are cleared by re-rendering list)

    if (!container) {
        console.error(`Container ${containerId} not found`);
        return;
    }

    if (logs.length === 0) {
        container.innerHTML = renderEmptyState('No logs found');
        return;
    }

    // Preserve current search filter
    const searchFilter = preserveSearchFilter('log-search', filterLogs);

    renderLogList(container, logs.slice(0, displayedLogsCount), logs.length);

    // Restore search filter and reapply severity filter
    searchFilter.restore();

    // Reapply filters (including severity) after rendering
    filterLogs();

    // Add click handlers using event delegation
    // Remove existing listener to avoid duplicates if renderLogs is called multiple times
    // (Actually, replacing innerHTML removes listeners on children, but not on container itself if added via addEventListener)
    // Ideally we should use a named function and removeEventListener, or check if listener attached.
    // For simplicity in this refactor, we'll assume container is fresh or we accept potential duplicate listeners on container (which is bad).
    // Better approach: attach listener once in init, or use "onclick" property.
    container.onclick = (e) => handleLogClick(e);
}

function renderLogList(container, logsToShow, totalLogs) {
    const limitNote = renderLimitNote(logsToShow.length, totalLogs, `Showing ${logsToShow.length} of ${totalLogs} logs`);

    // Build table with headers
    const headerRow = renderTableHeader([
        { label: 'Time', flex: '0 0 100px' },
        { label: 'ServiceName', flex: '0 0 120px' },
        { label: 'Severity', flex: '0 0 60px' },
        { label: 'traceId', flex: '0 0 180px' },
        { label: 'spanId', flex: '0 0 140px' },
        { label: 'Message', flex: '1; min-width: 200px' }
    ]);

    const logsHtml = logsToShow.map((log, index) => {
        const timestamp = formatTimestamp(log.timestamp);

        const severity = log.severity || 'INFO';
        const severityColor = getSeverityColor(severity);
        const traceId = log.traceId || log.trace_id;
        const spanId = log.spanId || log.span_id;

        return `
            <div class="log-row data-table-row" data-log-index="${index}">
                <div class="log-timestamp text-mono" style="flex: 0 0 100px;">${timestamp}</div>
                <div class="text-main font-medium text-truncate" style="flex: 0 0 120px;" title="${log.service_name || log.service || ''}">${log.service_name || log.service || '-'}</div>
                <div class="log-severity ${severity}" style="flex: 0 0 60px;">${severity}</div>
                <div class="text-mono text-truncate" style="flex: 0 0 180px; font-size: 10px;" title="${traceId || ''}">
                    ${traceId ? `<a class="log-trace-link text-mono" data-trace-id="${traceId}">${formatTraceId(traceId)}</a>` : '<span class="text-muted">-</span>'}
                </div>
                <div class="text-mono text-truncate" style="flex: 0 0 140px; font-size: 10px;" title="${spanId || ''}">
                    ${spanId ? `<a class="log-span-link text-mono" data-span-id="${spanId}">${formatTraceId(spanId)}</a>` : '<span class="text-muted">-</span>'}
                </div>
                <div class="text-main" style="flex: 1; min-width: 200px; word-break: break-word;">${log.message || ''}</div>
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

// Track current severity filter
let currentSeverityFilter = 'all';

export function clearLogFilter() {
    const filterInput = document.getElementById('trace-id-filter');
    const searchInput = document.getElementById('log-search');
    if (filterInput) {
        filterInput.value = '';
    }
    if (searchInput) {
        searchInput.value = '';
    }
    // Reset severity filter to 'all'
    currentSeverityFilter = 'all';
    document.querySelectorAll('.severity-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.severity === 'all');
    });
    // Trigger filter to show all logs
    filterLogs();
}

// Filter logs by severity level
export function filterBySeverity(severity) {
    currentSeverityFilter = severity;

    // Update button states
    document.querySelectorAll('.severity-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.severity === severity);
    });

    // Apply combined filters
    filterLogs();
}

// Expose to window for onclick handlers
window.filterBySeverity = filterBySeverity;

// Filter logs based on search input and severity filter
export function filterLogs() {
    const searchInput = document.getElementById('log-search');
    if (!searchInput) return;

    const searchTerm = searchInput.value.toLowerCase();
    const logRows = document.querySelectorAll('.log-row');

    logRows.forEach(row => {
        // Check severity filter first
        let showBySeverity = true;
        if (currentSeverityFilter !== 'all') {
            // Get severity from the row - it's in a div with the severity color
            const severityDiv = row.querySelector('div[style*="font-weight: 600"]');
            if (severityDiv) {
                const rowSeverity = severityDiv.textContent.trim().toUpperCase();
                showBySeverity = rowSeverity === currentSeverityFilter;
            }
        }

        // Check search filter
        let showBySearch = true;
        if (searchTerm) {
            const rowText = row.textContent.toLowerCase();
            showBySearch = rowText.includes(searchTerm);
        }

        // Show row only if both filters pass
        row.style.display = (showBySeverity && showBySearch) ? 'flex' : 'none';
    });
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
