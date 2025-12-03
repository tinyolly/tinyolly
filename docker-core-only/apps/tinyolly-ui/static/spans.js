/**
 * Spans Module - Handles span list and detail views with service filtering
 */
import { formatTime, formatTraceId, formatDuration, copyToClipboard, downloadJson, getStatusCodeColor, formatRoute, renderJsonDetailView, renderActionButton, renderEmptyState, filterTableRows, getAttributeValue, navigateToTabWithFilter, copyJsonWithFeedback, downloadTelemetryJson, smoothScrollTo, extractServiceName, closeAllExpandedItems } from './utils.js';

let currentSpanDetail = null;
let currentSpanData = null;

export function isSpanDetailOpen() {
    return currentSpanDetail !== null;
}

export function renderSpans(spans) {
    const container = document.getElementById('spans-container');
    if (!container) return;

    if (spans.length === 0) {
        container.innerHTML = renderEmptyState('🔍', 'No spans found');
        return;
    }

    const limitNote = '<div style="padding: 10px; text-align: center; color: var(--text-muted); font-size: 12px;">Showing last 50 spans</div>';

    const headerRow = `
        <div class="trace-header-row" style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 2px solid var(--border-color); background: var(--bg-secondary); font-weight: bold; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
            <div style="flex: 0 0 100px;">Time</div>
            <div style="flex: 0 0 120px;">ServiceName</div>
            <div style="flex: 0 0 260px;">traceId</div>
            <div style="flex: 0 0 180px;">spanId</div>
            <div style="flex: 0 0 80px; text-align: right;">Duration ms</div>
            <div style="flex: 0 0 70px;">Method</div>
            <div style="flex: 1;">Route / URL</div>
            <div style="flex: 0 0 60px; text-align: right;">Status</div>
        </div>
    `;

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
    const searchInput = document.getElementById('span-search');
    const currentFilter = searchInput ? searchInput.value : '';

    container.innerHTML = limitNote + headerRow + spansHtml;

    // Restore search input value (in case it was cleared during render)
    if (currentFilter && searchInput) {
        searchInput.value = currentFilter;
    }

    // Re-apply search filter if one was active
    if (currentFilter) {
        setTimeout(() => filterSpans(), 10);
    }

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

    // Add search functionality (reuse searchInput from above)
    if (searchInput) {
        searchInput.addEventListener('input', filterSpans);
    }
}

export function filterSpans() {
    const searchInput = document.getElementById('span-search');
    if (!searchInput) return;

    const spanRows = document.querySelectorAll('#spans-container .span-row-wrapper');
    const selectors = ['.trace-id', '.span-id', '.span-service', '.trace-name', '.trace-method', '.trace-status'];
    
    filterTableRows(spanRows, searchInput.value, selectors, 'block');
}

export function clearSpanFilter() {
    const searchInput = document.getElementById('span-search');
    if (searchInput) {
        searchInput.value = '';
        filterSpans();
    }
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

