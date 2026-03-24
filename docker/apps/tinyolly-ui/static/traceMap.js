/**
 * Trace Map Module - Renders a per-trace service dependency graph using Cytoscape.js
 * Shows which services participated in a trace and the call flow between them.
 */
import { extractServiceName, formatDuration } from './utils.js';

let traceCy = null;

/**
 * Builds a graph of {nodes, edges} from trace spans.
 * Nodes = unique services + inferred external callers.
 * Edges = cross-service parent→child calls + external→service calls.
 */
function buildTraceGraph(spans) {
    const spanById = new Map();
    const serviceSpans = new Map(); // service -> [spans]
    const edges = new Map(); // "source->target" -> { count, totalDuration }

    // Index spans by ID and group by service
    spans.forEach(span => {
        const id = span.spanId || span.span_id;
        if (id) spanById.set(id, span);

        const service = extractServiceName(span) || 'unknown';
        if (!serviceSpans.has(service)) {
            serviceSpans.set(service, []);
        }
        serviceSpans.get(service).push(span);
    });

    // Detect external callers: spans whose parentSpanId is set but not in this trace.
    // These represent calls from an external client (mobile app, test client, browser, etc.)
    // Group by unique external parent to avoid duplicating the same caller.
    const externalParents = new Set(); // set of external parentSpanIds
    const externalToService = new Map(); // "Inferred Client->service" -> count
    spans.forEach(span => {
        const parentId = span.parentSpanId || span.parent_span_id;
        if (!parentId || spanById.has(parentId)) return;
        // This span has a parent not in the trace — it was called by an external service
        externalParents.add(parentId);
        const childService = extractServiceName(span) || 'unknown';
        const edgeKey = `Inferred Client->${childService}`;
        const existing = externalToService.get(edgeKey) || { target: childService, count: 0, totalDurationNs: 0 };
        existing.count++;
        const start = span.startTimeUnixNano || span.start_time || 0;
        const end = span.endTimeUnixNano || span.end_time || 0;
        existing.totalDurationNs += (end - start);
        externalToService.set(edgeKey, existing);
    });

    // Build edges from parent-child cross-service relationships (within the trace)
    spans.forEach(span => {
        const parentId = span.parentSpanId || span.parent_span_id;
        if (!parentId) return;

        const parentSpan = spanById.get(parentId);
        if (!parentSpan) return; // External parent, handled above

        const childService = extractServiceName(span) || 'unknown';
        const parentService = extractServiceName(parentSpan) || 'unknown';

        if (childService === parentService) return; // Same service, skip

        const edgeKey = `${parentService}->${childService}`;
        const existing = edges.get(edgeKey) || { source: parentService, target: childService, count: 0, totalDurationNs: 0 };
        existing.count++;

        const start = span.startTimeUnixNano || span.start_time || 0;
        const end = span.endTimeUnixNano || span.end_time || 0;
        existing.totalDurationNs += (end - start);

        edges.set(edgeKey, existing);
    });

    // Build nodes
    const nodes = [];

    // Add inferred external client node if we detected orphan parent references.
    // Only add if the orphan parents all point into services we already know about —
    // if a real client service sent its own spans, those would already appear as a
    // service node with proper cross-service edges, so no inferred node is needed for them.
    if (externalParents.size > 0) {
        nodes.push({
            id: 'Inferred Client',
            label: 'Inferred Client',
            spanCount: externalParents.size,
            isRoot: true,
            isExternal: true,
            totalDurationMs: 0
        });
    }

    serviceSpans.forEach((svcSpans, service) => {
        // A service is root only if no external callers were detected AND it has orphan spans
        const isRoot = externalParents.size === 0 && svcSpans.some(s => {
            const pid = s.parentSpanId || s.parent_span_id;
            return !pid;
        });

        let totalDurationNs = 0;
        svcSpans.forEach(s => {
            const start = s.startTimeUnixNano || s.start_time || 0;
            const end = s.endTimeUnixNano || s.end_time || 0;
            totalDurationNs += (end - start);
        });

        nodes.push({
            id: service,
            label: service,
            spanCount: svcSpans.length,
            isRoot: isRoot,
            isExternal: false,
            totalDurationMs: totalDurationNs / 1_000_000
        });
    });

    // Build edge list — internal cross-service edges
    const edgeList = [];
    edges.forEach(edge => {
        const avgDurationMs = edge.totalDurationNs / edge.count / 1_000_000;
        edgeList.push({
            source: edge.source,
            target: edge.target,
            count: edge.count,
            avgDurationMs: avgDurationMs
        });
    });

    // Add inferred external caller edges
    externalToService.forEach(edge => {
        const avgDurationMs = edge.totalDurationNs / edge.count / 1_000_000;
        edgeList.push({
            source: 'Inferred Client',
            target: edge.target,
            count: edge.count,
            avgDurationMs: avgDurationMs
        });
    });

    return { nodes, edges: edgeList };
}

/**
 * Renders the trace map into the given container element.
 */
export function renderTraceMap(trace, container) {
    if (!trace || !trace.spans || trace.spans.length === 0) {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">No span data available for trace map.</div>';
        return;
    }

    const graph = buildTraceGraph(trace.spans);

    if (graph.nodes.length === 0) {
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">No services found in this trace.</div>';
        return;
    }

    // Single service with no external callers — no graph needed
    if (graph.nodes.length === 1 && graph.edges.length === 0) {
        const node = graph.nodes[0];
        container.innerHTML = `
            <div style="padding: 20px; text-align: center; color: var(--text-muted);">
                Single service trace: <strong style="color: var(--text-main);">${node.label}</strong>
                (${node.spanCount} span${node.spanCount !== 1 ? 's' : ''}, ${formatDuration(node.totalDurationMs)})
            </div>`;
        return;
    }

    // Build Cytoscape container
    container.innerHTML = `
        <div class="trace-map-wrapper">
            <div id="trace-map-cy" class="trace-map-cy"></div>
            <div class="trace-map-legend">
                <div style="font-weight: 600; margin-bottom: 6px; color: var(--text-muted);">Legend</div>
                <div style="display: flex; align-items: center; margin-bottom: 4px;">
                    <div style="width: 12px; height: 12px; background: #6366f1; transform: rotate(45deg); margin-right: 8px; border: 1px solid #4f46e5;"></div>
                    <span>Client <span style="color: var(--text-muted); font-size: 10px;">(inferred from trace context)</span></span>
                </div>
                <div style="display: flex; align-items: center; margin-bottom: 4px;">
                    <div style="width: 12px; height: 12px; background: #0066CC; border-radius: 2px; margin-right: 8px; border: 1px solid #0052CC;"></div>
                    <span>Service</span>
                </div>
            </div>
            <div id="trace-map-details" class="trace-map-details" style="display: none;">
                <div id="trace-map-details-title" style="font-weight: 600; margin-bottom: 8px;"></div>
                <div id="trace-map-details-content"></div>
            </div>
        </div>
    `;

    const cyContainer = document.getElementById('trace-map-cy');

    // Transform to Cytoscape elements
    const elements = [];

    graph.nodes.forEach(node => {
        let shape, color;
        if (node.isExternal) {
            shape = 'diamond';
            color = '#6366f1'; // Indigo for external client
        } else if (node.isRoot) {
            shape = 'diamond';
            color = '#6366f1';
        } else {
            shape = 'round-rectangle';
            color = '#0066CC';
        }
        elements.push({
            group: 'nodes',
            data: {
                id: node.id,
                label: node.label,
                shape: shape,
                color: color,
                spanCount: node.spanCount,
                totalDurationMs: node.totalDurationMs,
                isRoot: node.isRoot,
                isExternal: node.isExternal || false
            }
        });
    });

    graph.edges.forEach(edge => {
        const label = edge.count > 1
            ? `${edge.count} calls · ${formatDuration(edge.avgDurationMs)}`
            : formatDuration(edge.avgDurationMs);
        elements.push({
            group: 'edges',
            data: {
                id: `${edge.source}->${edge.target}`,
                source: edge.source,
                target: edge.target,
                label: label,
                count: edge.count
            }
        });
    });

    // Destroy previous instance
    if (traceCy) {
        traceCy.destroy();
        traceCy = null;
    }

    traceCy = cytoscape({
        container: cyContainer,
        elements: elements,
        style: (function() {
            // Read computed CSS variable values for dark/light mode support
            const cs = getComputedStyle(document.documentElement);
            const textColor = cs.getPropertyValue('--text-muted').trim() || '#64748b';
            const bgCard = cs.getPropertyValue('--bg-card').trim() || '#ffffff';
            const borderColor = cs.getPropertyValue('--border-color').trim() || '#e2e8f0';
            return [
            {
                selector: 'node',
                style: {
                    'background-color': 'data(color)',
                    'label': 'data(label)',
                    'shape': 'data(shape)',
                    'color': textColor,
                    'font-size': '11px',
                    'font-family': 'Inter, sans-serif',
                    'font-weight': '600',
                    'text-valign': 'bottom',
                    'text-margin-y': 6,
                    'width': 28,
                    'height': 28,
                    'border-width': 2,
                    'border-color': bgCard,
                    'overlay-opacity': 0,
                    'transition-property': 'background-color, width, height',
                    'transition-duration': '0.3s'
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 2,
                    'line-color': borderColor,
                    'target-arrow-color': borderColor,
                    'target-arrow-shape': 'triangle',
                    'curve-style': 'bezier',
                    'label': 'data(label)',
                    'font-size': '9px',
                    'color': textColor,
                    'text-background-opacity': 1,
                    'text-background-color': bgCard,
                    'text-background-padding': 2,
                    'text-background-shape': 'roundrectangle',
                    'text-border-width': 1,
                    'text-border-color': borderColor,
                    'text-border-opacity': 1
                }
            },
            {
                selector: 'node:selected',
                style: {
                    'border-width': 3,
                    'border-color': '#bfdbfe'
                }
            }
        ];})(),
        layout: {
            name: 'dagre',
            rankDir: 'LR',
            nodeSep: 60,
            rankSep: 100,
            edgeSep: 30,
            animate: true,
            animationDuration: 400,
            fit: true,
            padding: 30
        },
        minZoom: 0.5,
        maxZoom: 3,
        wheelSensitivity: 0.2
    });

    // Node click — show details panel
    traceCy.on('tap', 'node', function (evt) {
        const data = evt.target.data();
        const panel = document.getElementById('trace-map-details');
        const title = document.getElementById('trace-map-details-title');
        const content = document.getElementById('trace-map-details-content');
        if (!panel || !title || !content) return;

        title.textContent = data.label;

        const typeLabel = data.isExternal ? 'Inferred Client' : (data.isRoot ? 'Root Service' : 'Service');
        let html = `
            <div style="margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid var(--border-color);">
                <span style="background: ${data.color}; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; text-transform: uppercase;">
                    ${typeLabel}
                </span>
            </div>
        `;

        if (data.isExternal) {
            html += `
                <div style="margin-bottom: 4px; display: flex; justify-content: space-between;">
                    <span>Calls into trace:</span> <strong>${data.spanCount}</strong>
                </div>
                <div style="margin-top: 8px; font-size: 10px; color: var(--text-muted); font-style: italic;">
                    Inferred from orphan parent span IDs.<br>The caller did not export spans to TinyOlly.
                </div>
            `;
        } else {
            html += `
                <div style="margin-bottom: 4px; display: flex; justify-content: space-between;">
                    <span>Spans:</span> <strong>${data.spanCount}</strong>
                </div>
                <div style="margin-bottom: 4px; display: flex; justify-content: space-between;">
                    <span>Duration:</span> <strong>${formatDuration(data.totalDurationMs)}</strong>
                </div>
            `;
        }

        content.innerHTML = html;
        panel.style.display = 'block';
    });

    // Hide panel on background click
    traceCy.on('tap', function (evt) {
        if (evt.target === traceCy) {
            const panel = document.getElementById('trace-map-details');
            if (panel) panel.style.display = 'none';
        }
    });
}

/** Destroys the trace map Cytoscape instance (cleanup) */
export function destroyTraceMap() {
    if (traceCy) {
        traceCy.destroy();
        traceCy = null;
    }
}
