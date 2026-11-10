/**
 * Service Map Module - Renders service dependency graph using Cytoscape.js
 */
let cy = null;

// Human-readable duration from milliseconds
function formatMs(ms) {
    const n = Number(ms);
    if (!isFinite(n)) return '';
    if (n < 1) return `${+n.toFixed(2)}ms`;
    if (n < 1000) return `${+n.toPrecision(3)}ms`;
    if (n < 60000) return `${+(n / 1000).toFixed(2)}s`;
    if (n < 3600000) return `${+(n / 60000).toFixed(1)}m`;
    return `${+(n / 3600000).toFixed(1)}h`;
}

const fmtNum = v => (isFinite(Number(v)) ? +Number(v).toFixed(2) : v);

export function renderServiceMap(graph) {
    const container = document.getElementById('service-map-cy');
    if (!container) return;

    // Validate graph data
    if (!graph || !graph.nodes || !Array.isArray(graph.nodes)) {
        console.error('Invalid graph data:', graph);
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: var(--text-muted);">Invalid service map data</div>';
        return;
    }

    // Hide loading spinner
    const loadingEl = document.getElementById('map-loading');
    if (loadingEl) loadingEl.style.display = 'none';

    if (graph.nodes.length === 0) {
        if (cy) {
            cy.destroy();
            cy = null;
        }
        container.innerHTML = '<div style="height: 100%; display: flex; align-items: center; justify-content: center; text-align: center; color: var(--text-muted); padding: 24px;">No persisted service map is available. Click Refresh to clear the snapshot, then wait for new traces to arrive.</div>';
        return;
    }

    // Calculate node types (Root, Leaf, Intermediate)
    const incoming = new Map();
    const outgoing = new Map();

    graph.nodes.forEach(n => {
        incoming.set(n.id, 0);
        outgoing.set(n.id, 0);
    });

    // Safely handle edges (might be empty or undefined)
    if (graph.edges && Array.isArray(graph.edges)) {
        graph.edges.forEach(e => {
            outgoing.set(e.source, (outgoing.get(e.source) || 0) + 1);
            incoming.set(e.target, (incoming.get(e.target) || 0) + 1);
        });
    }

    // Transform data for Cytoscape
    const elements = [];

    // Nodes
    graph.nodes.forEach(node => {
        let shape = 'round-rectangle';
        let type = node.type || 'Service';

        const inCount = incoming.get(node.id) || 0;
        const outCount = outgoing.get(node.id) || 0;

        // Shape = what the node is (always); colour = health (always).
        if (node.type === 'database') {
            shape = 'barrel'; type = 'Database';
        } else if (node.type === 'messaging') {
            shape = 'rhomboid'; type = 'Messaging';
        } else if (inCount === 0 && outCount === 0) {
            shape = 'ellipse'; type = 'Isolated';
        } else if (inCount === 0) {
            shape = 'diamond'; type = 'Client';
        } else if (outCount === 0) {
            shape = 'hexagon'; type = 'External';
        } else {
            type = 'Server';
        }

        const metrics = node.metrics || {};
        let color = '#2563eb';                                  // healthy
        if (type === 'Isolated') color = '#94a3b8';             // no traffic
        if (metrics.error_rate > 5) color = '#ef4444';          // high error rate
        else if (metrics.error_rate > 0) color = '#f59e0b';     // some errors

        elements.push({
            group: 'nodes',
            data: {
                id: node.id,
                label: node.label,
                shape: shape,
                type: type,
                color: color,
                metrics: metrics
            }
        });
    });

    // Edges
    if (graph.edges && Array.isArray(graph.edges)) {
        graph.edges.forEach(edge => {
            elements.push({
                group: 'edges',
                data: {
                    id: `${edge.source}-${edge.target}`,
                    source: edge.source,
                    target: edge.target,
                    label: edge.p95 ? formatMs(edge.p95) : '',
                    p95: edge.p95,
                    weight: edge.value
                }
            });
        });
    }

    // If we already have a cytoscape instance, perform incremental update
    if (cy) {
        cy.batch(() => {
            const currentNodes = new Set(cy.nodes().map(n => n.id()));
            const currentEdges = new Set(cy.edges().map(e => e.id()));

            // Update Nodes
            elements.filter(e => e.group === 'nodes').forEach(ele => {
                if (currentNodes.has(ele.data.id)) {
                    cy.$id(ele.data.id).data(ele.data);
                    currentNodes.delete(ele.data.id);
                } else {
                    cy.add(ele);
                }
            });

            // Update Edges
            elements.filter(e => e.group === 'edges').forEach(ele => {
                if (currentEdges.has(ele.data.id)) {
                    cy.$id(ele.data.id).data(ele.data);
                    currentEdges.delete(ele.data.id);
                } else {
                    cy.add(ele);
                }
            });

            // Remove orphans
            currentNodes.forEach(nodeId => cy.$id(nodeId).remove());
            currentEdges.forEach(edgeId => cy.$id(edgeId).remove());
        });
        // Re-run layout to position any new nodes properly
        cy.one('layoutstop', applyPendingSelection);
        cy.layout({
            name: 'dagre',
            rankDir: 'LR',
            nodeSep: 60,
            rankSep: 120,
            edgeSep: 30,
            animate: true,
            animationDuration: 500,
            fit: true,
            padding: 30
        }).run();
        return;
    }

    // Initialize Cytoscape (First Load)
    container.innerHTML = '';

    // Read computed CSS variable values for dark/light mode support
    const cs = getComputedStyle(document.documentElement);
    const textColor = cs.getPropertyValue('--text-muted').trim() || '#64748b';
    const bgCard = cs.getPropertyValue('--bg-card').trim() || '#ffffff';
    const borderColor = cs.getPropertyValue('--border-color').trim() || '#e2e8f0';

    cy = cytoscape({
        container: container,
        elements: elements,
        style: [
            {
                selector: 'node',
                style: {
                    'background-color': 'data(color)',
                    'label': 'data(label)',
                    'shape': 'data(shape)',
                    'color': textColor,
                    'font-size': '12px',
                    'font-family': 'Inter, sans-serif',
                    'font-weight': '600',
                    'text-valign': 'bottom',
                    'text-margin-y': 8,
                    'width': 40,
                    'height': 40,
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
                    'font-size': '10px',
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
                    'border-width': 4,
                    'border-color': '#bfdbfe'
                }
            }
        ],
        layout: {
            name: 'dagre',
            rankDir: 'LR',
            nodeSep: 60,
            rankSep: 120,
            edgeSep: 30,
            animate: true,
            animationDuration: 500,
            fit: true,
            padding: 30
        },
        minZoom: 0.5,
        maxZoom: 3,
        wheelSensitivity: 0.2
    });

    cy.one('layoutstop', applyPendingSelection);

    // Click Handler for Details Panel
    cy.on('tap', 'node', function (evt) {
        const node = evt.target;
        const data = node.data();
        const metrics = data.metrics || {};

        const panel = document.getElementById('service-details-panel');
        const title = document.getElementById('details-title');
        const content = document.getElementById('details-content');

        if (!panel || !title || !content) return;

        title.textContent = data.label;

        let html = `
            <div style="margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #f1f5f9;">
                <span style="background: ${data.color}; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; text-transform: uppercase;">${data.type}</span>
            </div>
        `;

        if (metrics.span_count !== undefined) {
            html += `<div style="margin-bottom: 4px; display: flex; justify-content: space-between;"><span>Total Spans:</span> <strong>${metrics.span_count}</strong></div>`;
        }

        if (metrics.rate !== undefined && metrics.rate !== null) {
            html += `<div style="margin-bottom: 4px; display: flex; justify-content: space-between;"><span>Rate:</span> <strong>${fmtNum(metrics.rate)} req/s</strong></div>`;
        }

        if (metrics.error_rate !== undefined && metrics.error_rate !== null) {
            const color = metrics.error_rate > 0 ? '#ef4444' : '#10b981';
            html += `<div style="margin-bottom: 4px; display: flex; justify-content: space-between;"><span>Error Rate:</span> <strong style="color: ${color}">${fmtNum(metrics.error_rate)}%</strong></div>`;
        }

        if (metrics.duration_p50) {
            html += `
                <div style="margin-top: 12px; font-weight: 600; margin-bottom: 6px; color: #334155;">Latency</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; text-align: center; background: #f8fafc; padding: 8px; border-radius: 4px;">
                    <div>
                        <div style="font-size: 10px; color: #64748b;">P50</div>
                        <div style="font-weight: 600;">${formatMs(metrics.duration_p50)}</div>
                    </div>
                    <div>
                        <div style="font-size: 10px; color: #64748b;">P95</div>
                        <div style="font-weight: 600;">${formatMs(metrics.duration_p95)}</div>
                    </div>
                    <div>
                        <div style="font-size: 10px; color: #64748b;">P99</div>
                        <div style="font-weight: 600;">${formatMs(metrics.duration_p99)}</div>
                    </div>
                </div>
            `;
        } else {
            html += `<div style="margin-top: 12px; color: #94a3b8; font-style: italic;">No latency data available</div>`;
        }

        // Add navigation buttons
        const safeLabel = data.label.replace(/'/g, "\\'");
        html += `
            <div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #f1f5f9; display: flex; flex-direction: column; gap: 8px;">
                <button onclick="window.viewServiceCatalog('${safeLabel}');"
                    style="width: 100%; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: all 0.2s;">
                    <span>Service Catalog</span>
                </button>
                <div style="display: flex; gap: 8px;">
                    <button onclick="window.viewServiceSpans('${safeLabel}');" 
                        style="flex: 1; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; display: flex; align-items: center; justify-content: center; gap: 4px; transition: all 0.2s;">
                        <span>Spans</span>
                    </button>
                    <button onclick="window.viewServiceLogs('${safeLabel}');" 
                        style="flex: 1; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; display: flex; align-items: center; justify-content: center; gap: 4px; transition: all 0.2s;">
                        <span>Logs</span>
                    </button>
                </div>
                <button onclick="window.viewMetricsForService('${safeLabel}');" 
                    style="width: 100%; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: all 0.2s;">
                    <span>Metrics</span>
                </button>
            </div>
        `;

        content.innerHTML = html;
        panel.style.display = 'block';
    });

    // Hide panel when clicking background
    cy.on('tap', function (evt) {
        if (evt.target === cy) {
            const panel = document.getElementById('service-details-panel');
            if (panel) panel.style.display = 'none';
        }
    });
}


// Select a service node (as if clicked): centre on it and open its details panel. Returns false if not drawn yet.
export function selectServiceNode(name) {
    if (!cy) return false;
    const node = cy.nodes().filter(n => n.data('label') === name || n.id() === name);
    if (node.empty()) return false;
    cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1) }, { duration: 300 });
    node.emit('tap');
    return true;
}

// Selection requested from another tab: wait for the map's own render/layout (which fits the whole graph)
// to finish, then focus once. Otherwise the layout's fit re-zooms right after our focus (a visible double zoom).
let pendingSelection = null;
let pendingTimer = null;

function applyPendingSelection() {
    if (!pendingSelection) return;
    const name = pendingSelection;
    pendingSelection = null;
    clearTimeout(pendingTimer);
    selectServiceNode(name);
}

export function selectServiceNodeWhenReady(name) {
    pendingSelection = name;
    clearTimeout(pendingTimer);
    // Fallback if no layout runs (e.g. empty/cached map): give up waiting after 4s and focus directly
    pendingTimer = setTimeout(applyPendingSelection, 4000);
}
window.selectServiceNodeWhenReady = selectServiceNodeWhenReady;
