/**
 * Spans Module - Handles span list and detail views with service filtering
 */
import { formatTime, formatTraceId, formatDuration, copyToClipboard, downloadJson, getStatusCodeColor, formatRoute, renderJsonDetailView, renderActionButton, renderEmptyState, filterTableRows, getAttributeValue, navigateToTabWithFilter, copyJsonWithFeedback, downloadTelemetryJson, smoothScrollTo, extractServiceName, closeAllExpandedItems, renderTableHeader, renderLimitNote, preserveSearchFilter } from './utils.js';

let currentSpanDetail = null;
let currentSpanData = null;
let currentStatusFilter = 'all';

export function isSpanDetailOpen() {
    return currentSpanDetail !== null;
}

export function renderSpans(spans) {
    const container = document.getElementById('spans-container');
    if (!container) return;

    if (spans.length === 0) {
        container.innerHTML = renderEmptyState('No spans found');
        return;
    }

    const limitNote = renderLimitNote(50, spans.length, 'Showing last 50 spans');

    const headerRow = renderTableHeader([
        { label: 'Time', flex: '0 0 100px' },
        { label: 'ServiceName', flex: '0 0 120px' },
        { label: 'traceId', flex: '0 0 260px' },
        { label: 'spanId', flex: '0 0 180px' },
        { label: 'Duration', flex: '0 0 80px', align: 'right' },
        { label: 'Method', flex: '0 0 70px' },
        { label: 'Route / URL', flex: '1' },
        { label: 'Status', flex: '0 0 60px', align: 'right' }
    ]);

    const spansHtml = spans.map(span => {
        const displayTraceId = formatTraceId(span.trace_id);
        const displaySpanId = formatTraceId(span.span_id);
        const startTime = formatTime(span.start_time);

        const method = span.method || '';
        const route = formatRoute(span);
        const status = span.status_code || (span.status ? (span.status.code === 1 ? 'OK' : (span.status.code === 2 ? 'ERR' : '')) : '');
        const statusColor = getStatusCodeColor(status);

        // Extract service name
        const serviceName = span.service_name || '-';

        return `
            <div class="span-row-wrapper">
                <div class="trace-item" data-span-id="${span.span_id}" style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 1px solid var(--border-color); font-size: 11px; cursor: pointer;">
                    <div class="trace-time" style="font-family: monospace; color: var(--text-muted); flex: 0 0 100px;">${startTime}</div>
                    <div class="span-service" style="flex: 0 0 120px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${serviceName}">${serviceName}</div>
                    <div class="trace-id" style="flex: 0 0 260px; font-family: monospace; color: var(--text-muted); font-size: 0.9em;">${displayTraceId}</div>
                    <div class="span-id" style="flex: 0 0 180px; font-family: monospace; color: var(--text-muted); font-size: 0.9em;">${displaySpanId}</div>
                    <div class="trace-duration" style="flex: 0 0 80px; text-align: right; color: var(--text-muted);">${formatDuration(span.duration_ms)}</div>
                    <div class="trace-method" style="flex: 0 0 70px; font-weight: bold; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${method}</div>
                    <div class="trace-name" style="flex: 1; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${route}</div>
                    <div class="trace-status" style="flex: 0 0 60px; text-align: right; color: ${statusColor}; font-weight: 500;">${status || '-'}</div>
                </div>
                <div class="span-detail-inline" id="span-detail-${span.span_id}" style="display: none;"></div>
            </div>
        `;
    }).join('');

    // Preserve current search filter
    const searchFilter = preserveSearchFilter('span-search', filterSpans);

    container.innerHTML = limitNote + headerRow + spansHtml;

    // Restore search filter
    searchFilter.restore();

    // Reapply filters (including status) after rendering
    filterSpans();

    // Add click handlers (same pattern as traces)
    container.querySelectorAll('.trace-item').forEach(item => {
        item.addEventListener('click', () => {
            const spanId = item.dataset.spanId;
            const span = spans.find(s => s.span_id === spanId);
            if (span) {
                currentSpanData = span;
                showSpanDetail(spanId, spans);
            }
        });
    });

    // Restore span detail if one was showing and span still exists
    if (currentSpanDetail && currentSpanData) {
        const stillExists = spans.find(s => s.span_id === currentSpanDetail);
        if (stillExists) {
            setTimeout(() => showSpanDetail(currentSpanDetail, spans), 10);
        }
    }
}

export function filterSpans() {
    const searchInput = document.getElementById('span-search');
    if (!searchInput) return;

    const searchTerm = searchInput.value.toLowerCase();
    const spanRows = document.querySelectorAll('#spans-container .span-row-wrapper');

    spanRows.forEach(row => {
        // Check status filter first
        let showByStatus = true;
        if (currentStatusFilter !== 'all') {
            const statusDiv = row.querySelector('.trace-status');
            if (statusDiv) {
                const statusText = statusDiv.textContent.trim();
                const statusCode = parseInt(statusText);
                if (!isNaN(statusCode)) {
                    if (currentStatusFilter === '2xx') {
                        showByStatus = statusCode >= 200 && statusCode < 300;
                    } else if (currentStatusFilter === '4xx') {
                        showByStatus = statusCode >= 400 && statusCode < 500;
                    } else if (currentStatusFilter === '5xx') {
                        showByStatus = statusCode >= 500 && statusCode < 600;
                    }
                } else {
                    // Non-numeric status (OK, ERR, etc.) - show based on context
                    showByStatus = currentStatusFilter === 'all';
                }
            }
        }

        // Check search filter
        let showBySearch = true;
        if (searchTerm) {
            const rowText = row.textContent.toLowerCase();
            showBySearch = rowText.includes(searchTerm);
        }

        // Show row only if both filters pass
        row.style.display = (showByStatus && showBySearch) ? 'block' : 'none';
    });
}

// Filter spans by status code range
export function filterSpansByStatus(status) {
    currentStatusFilter = status;

    // Update button states
    document.querySelectorAll('#spans-content .status-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.status === status);
    });

    // Apply combined filters
    filterSpans();
}

// Expose to window for onclick handlers
window.filterSpansByStatus = filterSpansByStatus;

export function clearSpanFilter() {
    const searchInput = document.getElementById('span-search');
    if (searchInput) {
        searchInput.value = '';
    }
    // Reset status filter to 'all'
    currentStatusFilter = 'all';
    document.querySelectorAll('#spans-content .status-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.status === 'all');
    });
    filterSpans();
}

export function getServiceFilter() {
    // Get service filter from URL or other source if needed
    // For now, return null to load all spans
    return null;
}

function showSpanDetail(spanId, spans) {
    let span = currentSpanData;
    if (!span || span.span_id !== spanId) {
        span = spans.find(s => s.span_id === spanId);
    }
    if (!span) return;

    currentSpanDetail = spanId;
    currentSpanData = span;

    // Close all other span details
    document.querySelectorAll('.span-detail-inline').forEach(el => {
        if (el.id !== `span-detail-${spanId}`) {
            el.style.display = 'none';
            el.innerHTML = '';
        }
    });

    const detailContainer = document.getElementById(`span-detail-${spanId}`);
    if (!detailContainer) return;

    detailContainer.style.display = 'block';
    const buttonsHtml = `
        ${renderActionButton(`view-trace-btn-${spanId}`, 'View Trace', 'primary')}
        ${renderActionButton(`view-logs-btn-${spanId}`, 'Logs', 'primary')}
        ${renderActionButton(`view-span-metrics-btn-${spanId}`, 'Metrics', 'primary')}
        ${renderActionButton(`copy-span-btn-${spanId}`, 'Copy JSON', 'primary')}
        ${renderActionButton(`download-span-btn-${spanId}`, 'Download JSON', 'primary')}
        ${renderActionButton(`close-span-btn-${spanId}`, 'Close', 'primary')}
        <span id="copy-span-feedback-${spanId}" style="color: var(--success); font-size: 12px; display: none; margin-left: 8px;">Copied!</span>
    `;

    const title = `
        Span: ${span.name} 
        <span style="font-weight: normal; color: var(--text-muted); font-size: 0.9em; margin-left: 8px; font-family: 'JetBrains Mono', monospace;">
            (spanId: ${formatTraceId(span.span_id)})
        </span>
    `;

    detailContainer.innerHTML = renderJsonDetailView(span, title, buttonsHtml);

    // Scroll to the detail view
    smoothScrollTo(detailContainer);

    // Attach event handlers
    document.getElementById(`view-trace-btn-${spanId}`).addEventListener('click', () => {
        viewTraceFromSpan(span.trace_id);
    });

    document.getElementById(`view-logs-btn-${spanId}`).addEventListener('click', () => {
        showLogsForSpan(span.trace_id, span.span_id);
    });

    document.getElementById(`view-span-metrics-btn-${spanId}`).addEventListener('click', () => {
        viewMetricsForSpan(span);
    });

    document.getElementById(`copy-span-btn-${spanId}`).addEventListener('click', () => {
        copyJsonWithFeedback(span, `copy-span-feedback-${spanId}`);
    });

    document.getElementById(`download-span-btn-${spanId}`).addEventListener('click', () => {
        downloadTelemetryJson(span, 'span', span.span_id);
    });

    document.getElementById(`close-span-btn-${spanId}`).addEventListener('click', () => {
        detailContainer.style.display = 'none';
        detailContainer.innerHTML = '';
        currentSpanDetail = null;
        currentSpanData = null;
    });
}

function viewTraceFromSpan(traceId) {
    // Switch to traces tab
    if (window.switchTab) {
        window.switchTab('traces');
    }
    
    // Wait for tab to load, then show the trace detail
    setTimeout(() => {
        if (window.showTraceDetail) {
            window.showTraceDetail(traceId);
        }
    }, 300);
}

function showLogsForSpan(traceId, spanId) {
    navigateToTabWithFilter('logs', 'log-search', spanId, 'filterLogs');
}

function viewMetricsForSpan(span) {
    // Extract service name
    let serviceName = extractServiceName(span);
    
    // Extract HTTP attributes for filtering
    const httpMethod = getAttributeValue(span, ['http.method', 'http.request.method']);
    const httpStatusCode = getAttributeValue(span, ['http.status_code', 'http.response.status_code']);
    const httpRoute = getAttributeValue(span, ['http.route', 'http.target', 'url.path']);
    
    // Build filters object
    const filters = {
        resource: {},
        attributes: {}
    };
    
    if (serviceName) {
        filters.resource['service.name'] = serviceName;
    }
    
    if (httpMethod) {
        filters.attributes['http.method'] = httpMethod;
    }
    
    if (httpStatusCode) {
        filters.attributes['http.status_code'] = String(httpStatusCode);
    }
    
    // Call global function to view metrics with filters
    if (window.viewMetricsWithFilters) {
        window.viewMetricsWithFilters(filters);
    }
}

// Close all expanded span details
window.closeAllSpans = () => {
    closeAllExpandedItems({
        containers: ['.span-detail-inline'],
        callbacks: [() => { 
            currentSpanDetail = null;
            currentSpanData = null;
        }]
    });
};

