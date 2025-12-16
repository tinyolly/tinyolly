import { fetchTraceDetail } from './api.js';
import { renderTableHeader, renderJsonDetailView, renderActionButton, copyJsonWithFeedback, downloadTelemetryJson, renderEmptyState, formatTime, escapeHtml as escapeHtmlUtil } from './utils.js';

let aiSessions = [];
let currentModelFilter = 'all';
let selectedSessionIndex = null;

// Helper to extract attribute value from OTLP format (array of {key, value})
function getAttr(attrs, key) {
    if (!attrs) return null;
    if (Array.isArray(attrs)) {
        const attr = attrs.find(a => a.key === key);
        if (!attr) return null;
        const v = attr.value;
        return v.stringValue ?? v.intValue ?? v.boolValue ?? v.doubleValue ?? null;
    }
    return attrs[key] ?? null;
}

// Check if span has gen_ai attributes
function hasGenAiAttrs(span) {
    const attrs = span.attributes;
    return getAttr(attrs, 'gen_ai.system') ||
           getAttr(attrs, 'gen_ai.request.model') ||
           getAttr(attrs, 'gen_ai.usage.input_tokens');
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
    return escapeHtmlUtil(text);
}

// Truncate text with ellipsis
function truncate(text, maxLen = 100) {
    if (!text || text.length <= maxLen) return text || '';
    return text.substring(0, maxLen) + '...';
}

export async function loadAISessions() {
    const container = document.getElementById('ai-sessions-container');
    if (!container) return;

    try {
        const listResponse = await fetch('/api/traces?limit=50');
        const traceList = await listResponse.json();

        // Filter to AI traces
        const aiTraceIds = traceList
            .filter(t => t.service_name === 'ai-agent-demo' ||
                        (t.root_span_name && t.root_span_name.includes('ollama')))
            .map(t => t.trace_id);

        if (aiTraceIds.length === 0) {
            aiSessions = [];
            renderAISessions();
            updateAIMetrics();
            return;
        }

        // Fetch full details (limit to 20 for perf)
        const traceDetails = await Promise.all(
            aiTraceIds.slice(0, 20).map(id => fetchTraceDetail(id))
        );

        // Filter traces with gen_ai attributes
        aiSessions = traceDetails.filter(trace => {
            if (!trace || !trace.spans) return false;
            return trace.spans.some(hasGenAiAttrs);
        });

        renderAISessions();
        updateAIMetrics();
    } catch (err) {
        console.error("Failed to load AI sessions", err);
        container.innerHTML = '<div class="error">Failed to load AI sessions</div>';
    }
}

function renderAISessions() {
    const container = document.getElementById('ai-sessions-container');
    container.innerHTML = '';
    selectedSessionIndex = null;

    const filtered = aiSessions.filter(session => {
        if (currentModelFilter === 'all') return true;
        const modelSpan = session.spans.find(s => getAttr(s.attributes, 'gen_ai.request.model'));
        const model = modelSpan ? getAttr(modelSpan.attributes, 'gen_ai.request.model') : '';
        return model && model.includes(currentModelFilter);
    });

    if (filtered.length === 0) {
        container.innerHTML = renderEmptyState('No AI sessions found. Data may take a moment to appear.');
        return;
    }

    // Build table header using shared utility (like logs.js)
    const headerRow = renderTableHeader([
        { label: 'Time', flex: '0 0 100px' },
        { label: 'Session', flex: '0 0 80px' },
        { label: 'Model', flex: '0 0 90px' },
        { label: 'Prompt', flex: '1; min-width: 150px' },
        { label: 'Response', flex: '1; min-width: 150px' },
        { label: 'Tokens', flex: '0 0 100px' },
        { label: 'Latency', flex: '0 0 70px' }
    ]);

    // Build rows using data-table-row pattern (like logs.js)
    const rowsHtml = filtered.slice(0, 50).map((session, index) => {
        const rootSpan = session.spans.find(s => !s.parentSpanId) || session.spans[0];
        const modelSpan = session.spans.find(s => getAttr(s.attributes, 'gen_ai.request.model'));

        const traceId = rootSpan.traceId || session.trace_id;
        const sessionId = traceId.substring(0, 8);

        // Parse time
        const startNano = parseInt(rootSpan.startTimeUnixNano || rootSpan.start_time);
        const startTime = formatTime(startNano);

        const model = modelSpan ? getAttr(modelSpan.attributes, 'gen_ai.request.model') : 'Unknown';

        // Get prompt and response
        let prompt = '';
        let response = '';
        const aiSpan = session.spans.find(s =>
            getAttr(s.attributes, 'gen_ai.prompt') || getAttr(s.attributes, 'gen_ai.prompt.0.content')
        );
        if (aiSpan) {
            prompt = getAttr(aiSpan.attributes, 'gen_ai.prompt') ||
                     getAttr(aiSpan.attributes, 'gen_ai.prompt.0.content') || '';
            response = getAttr(aiSpan.attributes, 'gen_ai.completion') ||
                       getAttr(aiSpan.attributes, 'gen_ai.completion.0.content') || '';
        }

        // Tokens
        let inputTokens = 0;
        let outputTokens = 0;
        session.spans.forEach(s => {
            inputTokens += parseInt(getAttr(s.attributes, 'gen_ai.usage.input_tokens') || 0);
            outputTokens += parseInt(getAttr(s.attributes, 'gen_ai.usage.output_tokens') || 0);
        });

        // Latency
        const endNano = parseInt(rootSpan.endTimeUnixNano || rootSpan.end_time);
        const latency = (endNano - startNano) / 1000000000;

        return `
            <div class="ai-session-row data-table-row" data-session-index="${index}" data-trace-id="${traceId}">
                <div class="text-mono" style="flex: 0 0 100px;">${startTime}</div>
                <div class="text-mono" style="flex: 0 0 80px; color: var(--primary); cursor: pointer;" title="${traceId}">${sessionId}</div>
                <div style="flex: 0 0 90px;"><span class="badge badge-model">${escapeHtml(model)}</span></div>
                <div class="text-main text-truncate" style="flex: 1; min-width: 150px;" title="${escapeHtml(prompt)}">${escapeHtml(truncate(prompt, 60))}</div>
                <div class="text-main text-truncate" style="flex: 1; min-width: 150px;" title="${escapeHtml(response)}">${escapeHtml(truncate(response, 60))}</div>
                <div class="text-mono" style="flex: 0 0 100px;"><span style="color: var(--success-text);">${inputTokens}↓</span> <span style="color: var(--primary);">${outputTokens}↑</span></div>
                <div class="text-mono" style="flex: 0 0 70px;">${latency.toFixed(2)}s</div>
            </div>
        `;
    }).join('');

    container.innerHTML = headerRow + rowsHtml;

    // Add click handlers using event delegation (like logs.js)
    container.onclick = (e) => handleSessionClick(e);
}

function handleSessionClick(e) {
    const sessionRow = e.target.closest('.ai-session-row');
    if (sessionRow) {
        const index = parseInt(sessionRow.dataset.sessionIndex);
        showSessionJson(index);
    }
}

function showSessionJson(index) {
    // Get filtered sessions in same order as rendered
    const filtered = aiSessions.filter(session => {
        if (currentModelFilter === 'all') return true;
        const modelSpan = session.spans.find(s => getAttr(s.attributes, 'gen_ai.request.model'));
        const model = modelSpan ? getAttr(modelSpan.attributes, 'gen_ai.request.model') : '';
        return model && model.includes(currentModelFilter);
    });

    if (!filtered || !filtered[index]) return;

    const session = filtered[index];
    const sessionRow = document.querySelector(`.ai-session-row[data-session-index="${index}"]`);
    if (!sessionRow) return;

    // Find the AI span (with gen_ai attributes)
    const aiSpan = session.spans.find(hasGenAiAttrs) || session.spans[0];
    const traceId = session.trace_id || aiSpan.traceId;

    // Check if JSON view is already open for this row
    const existingJsonView = sessionRow.nextElementSibling;
    if (existingJsonView && existingJsonView.classList.contains('ai-session-json-row')) {
        // Toggle close
        existingJsonView.remove();
        sessionRow.style.background = '';
        selectedSessionIndex = null;
        return;
    }

    // Close any other open JSON views
    document.querySelectorAll('.ai-session-json-row').forEach(row => row.remove());
    document.querySelectorAll('.ai-session-row').forEach(row => row.style.background = '');

    // Highlight selected row
    sessionRow.style.background = 'var(--bg-hover)';
    selectedSessionIndex = index;

    // Create buttons HTML
    const buttonsHtml = `
        ${renderActionButton(`copy-ai-json-btn-${index}`, 'Copy JSON', 'primary')}
        ${renderActionButton(`download-ai-json-btn-${index}`, 'Download JSON', 'primary')}
        ${renderActionButton(`close-ai-json-btn-${index}`, 'Close', 'primary')}
        <span id="copy-ai-json-feedback-${index}" style="color: var(--success); font-size: 12px; display: none; margin-left: 8px;">Copied!</span>
    `;

    const title = `
        AI Span Details
        <span style="font-weight: normal; color: var(--text-muted); font-size: 0.9em; margin-left: 8px; font-family: 'JetBrains Mono', monospace;">
            ${traceId.substring(0, 12)}
        </span>
    `;

    // Create JSON view row
    const jsonRow = document.createElement('div');
    jsonRow.className = 'ai-session-json-row';
    jsonRow.style.background = 'var(--bg-card)';
    jsonRow.style.borderBottom = '1px solid var(--border-color)';
    jsonRow.style.padding = '0 16px';

    // Use shared render function with AI span data
    jsonRow.innerHTML = renderJsonDetailView(aiSpan, title, buttonsHtml);

    // Insert after the session row
    sessionRow.parentNode.insertBefore(jsonRow, sessionRow.nextSibling);

    // Attach handlers for the buttons
    document.getElementById(`copy-ai-json-btn-${index}`).onclick = (e) => {
        e.stopPropagation();
        copyJsonWithFeedback(aiSpan, `copy-ai-json-feedback-${index}`);
    };

    document.getElementById(`download-ai-json-btn-${index}`).onclick = (e) => {
        e.stopPropagation();
        downloadTelemetryJson(aiSpan, 'ai-span', traceId);
    };

    document.getElementById(`close-ai-json-btn-${index}`).onclick = (e) => {
        e.stopPropagation();
        jsonRow.remove();
        sessionRow.style.background = '';
        selectedSessionIndex = null;
    };
}

function updateAIMetrics() {
    let totalTokens = 0;
    let totalLatency = 0;

    aiSessions.forEach(s => {
        s.spans.forEach(span => {
            totalTokens += parseInt(getAttr(span.attributes, 'gen_ai.usage.input_tokens') || 0);
            totalTokens += parseInt(getAttr(span.attributes, 'gen_ai.usage.output_tokens') || 0);
        });
        const root = s.spans.find(sp => !sp.parentSpanId) || s.spans[0];
        const startNano = parseInt(root.startTimeUnixNano || root.start_time);
        const endNano = parseInt(root.endTimeUnixNano || root.end_time);
        totalLatency += (endNano - startNano) / 1000000000;
    });

    document.getElementById('ai-total-sessions').textContent = aiSessions.length;
    document.getElementById('ai-total-tokens').textContent = totalTokens.toLocaleString();
    document.getElementById('ai-avg-latency').textContent = aiSessions.length > 0
        ? (totalLatency / aiSessions.length).toFixed(2) + 's'
        : '-';

    // Cost: $0.002 per 1k tokens (simplified)
    const cost = (totalTokens / 1000) * 0.002;
    document.getElementById('ai-total-cost').textContent = '$' + cost.toFixed(4);
}

export function filterAIByModel(model) {
    currentModelFilter = model;
    document.querySelectorAll('#ai-agents-list-view .status-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.model === model);
    });
    renderAISessions();
}

window.filterAIByModel = filterAIByModel;
window.refreshAIView = loadAISessions;

export function showAISessionDetail(traceId) {
    const session = aiSessions.find(s => s.trace_id === traceId);
    if (!session) return;

    document.getElementById('ai-agents-list-view').style.display = 'none';
    document.getElementById('ai-detail-view').style.display = 'block';

    const container = document.getElementById('ai-session-detail-container');
    container.innerHTML = '';

    const spans = session.spans.sort((a, b) => {
        return parseInt(a.startTimeUnixNano || a.start_time) - parseInt(b.startTimeUnixNano || b.start_time);
    });
    const rootSpan = spans.find(s => !s.parentSpanId) || spans[0];
    const startTimeOffset = parseInt(rootSpan.startTimeUnixNano || rootSpan.start_time);

    document.getElementById('ai-session-title').textContent = `Session: ${traceId.substring(0, 12)}`;

    spans.forEach(span => {
        const isAI = getAttr(span.attributes, 'gen_ai.system') || getAttr(span.attributes, 'gen_ai.request.model');
        const isTool = span.name.includes('tool') || getAttr(span.attributes, 'agent.tool.name');

        const spanStart = parseInt(span.startTimeUnixNano || span.start_time);
        const spanEnd = parseInt(span.endTimeUnixNano || span.end_time);
        const relativeStart = (spanStart - startTimeOffset) / 1000000000;
        const duration = (spanEnd - spanStart) / 1000000000;

        const card = document.createElement('div');
        card.className = 'ai-span-card';
        if (isAI) card.classList.add('ai-span');
        else if (isTool) card.classList.add('tool-span');

        let icon = isAI ? '🤖' : (isTool ? '🛠' : '⚡');
        let html = `
            <div class="span-header">
                <span class="span-name">${icon} ${escapeHtml(span.name)}</span>
                <span class="span-timing">+${relativeStart.toFixed(2)}s (${duration.toFixed(2)}s)</span>
            </div>
        `;

        if (isAI) {
            const prompt = getAttr(span.attributes, 'gen_ai.prompt') ||
                getAttr(span.attributes, 'gen_ai.prompt.0.content') || '';
            const completion = getAttr(span.attributes, 'gen_ai.completion') ||
                getAttr(span.attributes, 'gen_ai.completion.0.content') || '';
            const model = getAttr(span.attributes, 'gen_ai.request.model') || '';
            const inTokens = getAttr(span.attributes, 'gen_ai.usage.input_tokens') || 0;
            const outTokens = getAttr(span.attributes, 'gen_ai.usage.output_tokens') || 0;

            html += `
                <div class="ai-content">
                    <div class="prompt-section">
                        <div class="section-label">PROMPT</div>
                        <div class="section-content">${escapeHtml(prompt)}</div>
                    </div>
                    <div class="completion-section">
                        <div class="section-label">COMPLETION</div>
                        <div class="section-content">${escapeHtml(completion)}</div>
                    </div>
                    <div class="ai-meta">
                        Model: ${escapeHtml(model)} | Tokens: ${inTokens} in / ${outTokens} out
                    </div>
                </div>
            `;
        }

        card.innerHTML = html;
        container.appendChild(card);
    });
}

export function closeAISessionDetail() {
    document.getElementById('ai-agents-list-view').style.display = 'block';
    document.getElementById('ai-detail-view').style.display = 'none';
}

window.showAISessionDetail = showAISessionDetail;
window.closeAISessionDetail = closeAISessionDetail;

// Track if JSON view is open (for auto-refresh suppression)
export function isAISessionJsonOpen() {
    return selectedSessionIndex !== null;
}
