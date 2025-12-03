/**
 * Service Map Module - Renders service dependency graph using Cytoscape.js
 */
let cy = null;

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

        let color = '#0066CC'; // Default Blue

        // Check metrics for health status
        const metrics = node.metrics || {};
        if (metrics.error_rate && metrics.error_rate > 5) {
            color = '#ef4444'; // Red for high error rate
        } else if (metrics.error_rate && metrics.error_rate > 0) {
            color = '#f59e0b'; // Orange for some errors
        } else {
            // Fallback to topology inference if no health issues
            if (node.type === 'database') {
                shape = 'barrel';
                type = 'Database';
                color = '#10b981'; // Green
            } else if (node.type === 'messaging') {
                shape = 'rhomboid';
                type = 'Messaging';
                color = '#8b5cf6'; // Purple
            } else {
                if (inCount === 0 && outCount === 0) {
                    shape = 'ellipse';
                    type = 'Isolated';
                    color = '#94a3b8'; // Gray
                } else if (inCount === 0) {
                    shape = 'diamond';
                    type = 'Client';
                    color = '#6366f1'; // Indigo
                } else if (outCount === 0) {
                    shape = 'barrel';
                    type = 'External';
                    color = '#10b981'; // Green
                }
            }
        }

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
                    label: edge.p95 ? `${edge.p95}ms` : '',
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
        return;
    }

    // Initialize Cytoscape (First Load)
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
                    'color': '#64748b',
                    'font-size': '12px',
                    'font-family': 'Inter, sans-serif',
                    'font-weight': '600',
                    'text-valign': 'bottom',
                    'text-margin-y': 8,
                    'width': 40,
                    'height': 40,
                    'border-width': 2,
                    'border-color': '#ffffff',
                    'overlay-opacity': 0,
                    'transition-property': 'background-color, width, height',
                    'transition-duration': '0.3s'
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 2,
                    'line-color': '#cbd5e1',
                    'target-arrow-color': '#cbd5e1',
                    'target-arrow-shape': 'triangle',
                    'curve-style': 'bezier',
                    'label': 'data(label)',
                    'font-size': '10px',
                    'color': '#64748b',
                    'text-background-opacity': 1,
                    'text-background-color': '#ffffff',
                    'text-background-padding': 2,
                    'text-background-shape': 'roundrectangle',
                    'text-border-width': 1,
                    'text-border-color': '#e2e8f0',
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
            name: 'cose',
            animate: true,
            componentSpacing: 100,
            nodeRepulsion: function (node) { return 400000; },
            idealEdgeLength: function (edge) { return 100; },
            nestingFactor: 5,
            gravity: 80,
            numIter: 1000,
            coolingFactor: 0.95
        },
        minZoom: 0.5,
        maxZoom: 3,
        wheelSensitivity: 0.2
    });

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
            html += `<div style="margin-bottom: 4px; display: flex; justify-content: space-between;"><span>Rate:</span> <strong>${metrics.rate} req/s</strong></div>`;
        }

        if (metrics.error_rate !== undefined && metrics.error_rate !== null) {
            const color = metrics.error_rate > 0 ? '#ef4444' : '#10b981';
            html += `<div style="margin-bottom: 4px; display: flex; justify-content: space-between;"><span>Error Rate:</span> <strong style="color: ${color}">${metrics.error_rate}%</strong></div>`;
        }

        if (metrics.duration_p50) {
            html += `
                <div style="margin-top: 12px; font-weight: 600; margin-bottom: 6px; color: #334155;">Latency (ms)</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; text-align: center; background: #f8fafc; padding: 8px; border-radius: 4px;">
                    <div>
                        <div style="font-size: 10px; color: #64748b;">P50</div>
                        <div style="font-weight: 600;">${metrics.duration_p50}</div>
                    </div>
                    <div>
                        <div style="font-size: 10px; color: #64748b;">P95</div>
                        <div style="font-weight: 600;">${metrics.duration_p95}</div>
                    </div>
                    <div>
                        <div style="font-size: 10px; color: #64748b;">P99</div>
                        <div style="font-weight: 600;">${metrics.duration_p99}</div>
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
