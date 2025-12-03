/**
 * Traces Module - Handles trace list and waterfall visualization
 */
import { formatTime, formatTraceId, formatDuration, copyToClipboard, downloadJson, getStatusCodeColor, formatRoute, renderJsonDetailView, renderActionButton, renderEmptyState, filterTableRows, getAttributeValue, navigateToTabWithFilter, copyJsonWithFeedback, downloadTelemetryJson, smoothScrollTo, extractServiceName, closeAllExpandedItems } from './utils.js';
import { fetchTraceDetail, loadTraces } from './api.js';

let currentTraceId = null;
let currentTraceData = null;
let selectedSpanIndex = null;
export function renderTraces(traces) {
    const container = document.getElementById('traces-container');

    if (traces.length === 0) {
        container.innerHTML = renderEmptyState('-', 'No traces yet. Send some data to get started!');
        return;
    }

    const limitNote = traces.length >= 50 ? '<div style="padding: 10px; text-align: center; color: var(--text-muted); font-size: 12px;">Showing last 50 traces (older data available in Redis).</div>' : '';

    const headerRow = `
        <div class="trace-header-row" style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 2px solid var(--border-color); background: var(--bg-secondary); font-weight: bold; font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">
            <div style="flex: 0 0 100px;">Time</div>
            <div style="flex: 0 0 120px;">ServiceName</div>
            <div style="flex: 0 0 260px;">traceId</div>
            <div style="flex: 0 0 60px; text-align: right;">Spans</div>
            <div style="flex: 0 0 80px; text-align: right;">Duration ms</div>
            <div style="flex: 0 0 70px;">Method</div>
            <div style="flex: 1;">Route / URL</div>
            <div style="flex: 0 0 60px; text-align: right;">Status</div>
        </div>
    `;

    container.innerHTML = limitNote + headerRow + traces.map(trace => {
        const displayTraceId = formatTraceId(trace.trace_id);
        const startTime = formatTime(trace.start_time);

        // Determine method, route, and status
        const method = trace.root_span_method || '';
        const route = formatRoute({
            url: trace.root_span_url,
            server_name: trace.root_span_server_name,
            host: trace.root_span_host,
            scheme: trace.root_span_scheme,
            target: trace.root_span_target,
            route: trace.root_span_route,
            name: trace.root_span_name
        });

        const status = trace.root_span_status_code || (trace.root_span_status ? (trace.root_span_status.code === 1 ? 'OK' : (trace.root_span_status.code === 2 ? 'ERR' : '')) : '');
        const statusColor = getStatusCodeColor(status);

        // Extract service name
        const serviceName = trace.service_name || trace.root_span_service_name || '-';

        return `
            <div class="trace-item" data-trace-id="${trace.trace_id}" style="display: flex; align-items: center; gap: 15px; padding: 8px 12px; border-bottom: 1px solid var(--border-color); font-size: 11px; cursor: pointer;">
                <div class="trace-time" style="font-family: monospace; color: var(--text-muted); flex: 0 0 100px;">${startTime}</div>
                <div class="trace-service" style="flex: 0 0 120px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${serviceName}">${serviceName}</div>
                <div class="trace-id" style="flex: 0 0 260px; font-family: monospace; color: var(--text-muted); font-size: 0.9em;">${displayTraceId}</div>
                <div class="trace-spans" style="flex: 0 0 60px; text-align: right; color: var(--text-muted);">${trace.span_count}</div>
                <div class="trace-duration" style="flex: 0 0 80px; text-align: right; color: var(--text-muted);">${formatDuration(trace.duration_ms)}</div>
                <div class="trace-method" style="flex: 0 0 70px; font-weight: bold; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${method}</div>
                <div class="trace-name" style="flex: 1; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${route}</div>
                <div class="trace-status" style="flex: 0 0 60px; text-align: right; color: ${statusColor}; font-weight: 500;">${status || '-'}</div>
            </div>
        `;
    }).join('');

    // Add click handlers
    container.querySelectorAll('.trace-item').forEach(item => {
        item.addEventListener('click', () => showTraceDetail(item.dataset.traceId));
    });

    // Add search functionality
    const searchInput = document.getElementById('trace-search');
    if (searchInput) {
        searchInput.addEventListener('input', filterTraces);
    }
}

function filterTraces() {
    const searchInput = document.getElementById('trace-search');
    if (!searchInput) return;

    const traceItems = document.querySelectorAll('#traces-container .trace-item');
    const selectors = ['.trace-id', '.trace-service', '.trace-name', '.trace-method', '.trace-status'];
    
    filterTableRows(traceItems, searchInput.value, selectors, 'flex');
}

export function clearTraceFilter() {
    const searchInput = document.getElementById('trace-search');
    if (searchInput) {
        searchInput.value = '';
        filterTraces();
    }
}

export async function showTraceDetail(traceId) {
    currentTraceId = traceId;

    // Show detail view, hide list
    document.getElementById('traces-list-view').style.display = 'none';
    document.getElementById('trace-detail-view').style.display = 'block';

    // Load trace details
    const trace = await fetchTraceDetail(traceId);
    if (trace) {
        await renderWaterfall(trace);
    }
}

export function showTracesList() {
    document.getElementById('traces-list-view').style.display = 'block';
    document.getElementById('trace-detail-view').style.display = 'none';
    currentTraceId = null;
    currentTraceData = null;
    loadTraces(); // Refresh list
}

export function toggleTraceJSON() {
    const jsonView = document.getElementById('trace-json-view');

    if (jsonView.style.display === 'none') {
        // Build buttons HTML
        const buttonsHtml = `
            ${renderActionButton('copy-trace-json-btn', 'Copy JSON', 'secondary')}
            ${renderActionButton('download-trace-json-btn', 'Download JSON', 'secondary')}
            ${renderActionButton('close-trace-json-btn', 'Close', 'secondary')}
            <span id="copy-trace-feedback"
                style="color: var(--success); font-size: 12px; display: none; margin-left: 8px;">Copied!</span>
        `;

        const title = `Trace JSON <span style="font-weight: normal; color: var(--text-muted); font-size: 0.9em; margin-left: 8px; font-family: 'JetBrains Mono', monospace;">(traceId: ${formatTraceId(currentTraceId)})</span>`;

        jsonView.innerHTML = renderJsonDetailView(currentTraceData, title, buttonsHtml);
        jsonView.style.display = 'block';

        // Attach event handlers for the buttons
        document.getElementById('copy-trace-json-btn').onclick = (e) => {
            e.stopPropagation();
            copyTraceJSON();
        };

        document.getElementById('download-trace-json-btn').onclick = (e) => {
            e.stopPropagation();
            downloadTraceJSON();
        };

        document.getElementById('close-trace-json-btn').onclick = (e) => {
            e.stopPropagation();
            toggleTraceJSON();
        };

        // Scroll to JSON view
        smoothScrollTo(jsonView);
    } else {
        jsonView.style.display = 'none';
        jsonView.innerHTML = '';
    }
}

export function copyTraceJSON() {
    copyJsonWithFeedback(currentTraceData, 'copy-trace-feedback');
}

export function downloadTraceJSON() {
    downloadTelemetryJson(currentTraceData, 'trace', currentTraceId);
}

export function showLogsForTrace() {
    if (!currentTraceId) return;
    navigateToTabWithFilter('logs', 'log-search', currentTraceId, 'filterLogs');
}

async function renderWaterfall(trace) {
    const spans = trace.spans;
    currentTraceData = trace;
    selectedSpanIndex = null;

    // Find trace bounds
    const startTimes = spans.map(s => s.startTimeUnixNano || s.start_time || 0);
    const endTimes = spans.map(s => s.endTimeUnixNano || s.end_time || 0);
    const traceStart = Math.min(...startTimes);
    const traceEnd = Math.max(...endTimes);
    const traceDuration = traceEnd - traceStart;
    const traceDurationMs = traceDuration / 1_000_000;

    const container = document.getElementById('trace-detail-container');
    const displayTraceId = formatTraceId(trace.trace_id);

    // Fetch logs for this trace
    let traceLogs = [];
    try {
        const response = await fetch(`/api/logs?trace_id=${trace.trace_id}`);
        if (response.ok) {
            traceLogs = await response.json();
        }
    } catch (e) {
        console.error('Error fetching trace logs:', e);
    }

    // Create time markers
    const timeMarkers = [0, 0.25, 0.5, 0.75, 1.0].map(fraction => {
        const timeMs = traceDurationMs * fraction;
        let className = 'time-marker';
        let positionStyle = `left: ${fraction * 100}%;`;

        if (fraction === 0) className += ' first';
        else if (fraction === 1.0) {
            className += ' last';
            positionStyle = '';
        }

        return `<div class="${className}" style="${positionStyle}">${timeMs.toFixed(2)}ms</div>`;
    }).join('');

    // Render action buttons in a white box at the top
    const actionButtonsHtml = `
        <div class="json-detail-view" style="background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px; padding: 16px; margin: 12px 0;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div style="font-size: 14px; font-weight: 600; color: var(--text-main);">
                    Trace: ${displayTraceId}
                    <span style="font-weight: normal; color: var(--text-muted); font-size: 0.9em; margin-left: 8px;">
                        ${trace.span_count} spans - ${traceDurationMs.toFixed(2)}ms total
                    </span>
                </div>
                <div style="display: flex; gap: 8px;">
                    ${renderActionButton('back-to-traces-btn', 'Back to Traces', 'primary')}
                    ${renderActionButton('view-trace-json-btn', 'Trace JSON', 'primary')}
                    ${renderActionButton('view-trace-logs-btn', 'Logs', 'primary')}
                    ${renderActionButton('view-related-metrics-btn', 'Metrics', 'primary')}
                </div>
            </div>
        </div>
    `;

    // Build logs section
    const logsHtml = traceLogs.length > 0 ? `
        <div style="margin: 16px 0; padding: 12px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px;">
            <div style="font-weight: 600; color: var(--text-main); margin-bottom: 8px; font-size: 13px;">
                Correlated Logs (${traceLogs.length})
            </div>
            <div style="max-height: 200px; overflow-y: auto;">
                ${traceLogs.map(log => {
                    const timestamp = new Date(log.timestamp * 1000).toLocaleTimeString();
                    const severity = log.severity || 'INFO';
                    const severityColors = {
                        'ERROR': '#ef4444',
                        'WARN': '#f59e0b',
                        'INFO': '#3b82f6',
                        'DEBUG': '#6b7280'
                    };
                    const color = severityColors[severity] || '#6b7280';
                    return `
                        <div style="padding: 6px; border-bottom: 1px solid var(--border-color); font-size: 11px; display: flex; gap: 12px; align-items: start;">
                            <span style="font-family: monospace; color: var(--text-muted); white-space: nowrap;">${timestamp}</span>
                            <span style="font-weight: 600; color: ${color}; min-width: 50px;">${severity}</span>
                            <span style="flex: 1; color: var(--text-main);">${log.message || ''}</span>
                        </div>
                    `;
                }).join('')}
            </div>
        </div>
    ` : '';

    container.innerHTML = `
        ${actionButtonsHtml}
        ${logsHtml}
        <div class="waterfall">
            ${spans.map((span, idx) => {
        const startTime = span.startTimeUnixNano || span.start_time || 0;
        const endTime = span.endTimeUnixNano || span.end_time || 0;
        const duration = endTime - startTime;
        const offset = startTime - traceStart;

        const leftPercent = (offset / traceDuration) * 100;
        const widthPercent = (duration / traceDuration) * 100;

        return `
                    <div class="span-row">
                        <div class="span-info">
                            <div class="span-name" title="${span.name}">${span.name}</div>
                            <div class="span-timeline">
                                <div class="span-bar" data-span-index="${idx}" style="left: ${leftPercent}%; width: ${widthPercent}%;">
                                    ${duration > traceDuration * 0.1 ? (duration / 1_000_000).toFixed(2) + 'ms' : ''}
                                </div>
                            </div>
                            <div class="span-duration">${(duration / 1_000_000).toFixed(2)}ms</div>
                        </div>
                    </div>
                `;
    }).join('')}
        </div>
        <div class="time-axis">
            <div class="time-markers">
                ${timeMarkers}
            </div>
        </div>
        <div id="span-json-container"></div>
    `;

    // Add click handlers for span bars
    container.querySelectorAll('.span-bar').forEach(bar => {
        bar.addEventListener('click', (e) => {
            const spanIndex = parseInt(e.currentTarget.getAttribute('data-span-index'));
            showSpanJson(spanIndex);
        });
    });

    // Add click handlers for action buttons
    document.getElementById('back-to-traces-btn').addEventListener('click', showTracesList);
    document.getElementById('view-trace-json-btn').addEventListener('click', toggleTraceJSON);
    document.getElementById('view-trace-logs-btn').addEventListener('click', showLogsForTrace);
    document.getElementById('view-related-metrics-btn').addEventListener('click', () => viewMetricsForTrace(trace));
}

function showSpanJson(spanIndex) {
    if (!currentTraceData || !currentTraceData.spans[spanIndex]) return;

    const span = currentTraceData.spans[spanIndex];
    const container = document.getElementById('span-json-container');

    document.querySelectorAll('.span-bar').forEach((bar, idx) => {
        bar.classList.toggle('selected', idx === spanIndex);
    });

    selectedSpanIndex = spanIndex;

    const buttonsHtml = `
        ${renderActionButton('copy-span-json-btn', 'Copy JSON', 'secondary')}
        ${renderActionButton('download-span-json-btn', 'Download JSON', 'secondary')}
        ${renderActionButton('close-span-json-btn', 'Close', 'secondary')}
        <span id="copy-span-json-feedback" style="color: var(--success); font-size: 12px; display: none; margin-left: 8px;">Copied!</span>
    `;

    const title = `
        Span: ${span.name} 
        <span style="font-weight: normal; color: var(--text-muted); font-size: 0.9em; margin-left: 8px; font-family: 'JetBrains Mono', monospace;">
            (spanId: ${span.spanId || span.span_id})
        </span>
    `;

    container.innerHTML = renderJsonDetailView(span, title, buttonsHtml);

    // Attach handlers for the buttons
    document.getElementById('copy-span-json-btn').onclick = () => {
        copyJsonWithFeedback(span, 'copy-span-json-feedback');
    };

    document.getElementById('download-span-json-btn').onclick = () => {
        const spanId = span.spanId || span.span_id;
        downloadTelemetryJson(span, 'span', spanId);
    };

    document.getElementById('close-span-json-btn').onclick = () => {
        container.innerHTML = '';
        document.querySelectorAll('.span-bar').forEach(bar => bar.classList.remove('selected'));
        selectedSpanIndex = null;
    };
}

function viewMetricsForTrace(trace) {
    // Extract service name from root span
    if (!trace || !trace.spans || trace.spans.length === 0) return;
    
    // Find root span (no parent)
    const rootSpan = trace.spans.find(s => !s.parentSpanId && !s.parent_span_id) || trace.spans[0];
    
    // Extract service.name from span
    let serviceName = extractServiceName(rootSpan);
    
    // Calculate time range (±5 minutes around trace)
    const traceStartNano = rootSpan.startTimeUnixNano || rootSpan.start_time || 0;
    const traceStartSec = traceStartNano / 1_000_000_000;
    const fiveMinutes = 5 * 60;
    
    // Call global function to view metrics with filters
    if (window.viewMetricsForService) {
        window.viewMetricsForService(serviceName, traceStartSec - fiveMinutes, traceStartSec + fiveMinutes);
    }
}

// Close all expanded trace span details (in waterfall view)
window.closeAllTraceDetails = () => {
    closeAllExpandedItems({
        containers: ['#span-json-container', '#trace-json-view'],
        classes: [{ selector: '.span-bar', class: 'selected' }],
        callbacks: [() => { selectedSpanIndex = null; }]
    });
};

