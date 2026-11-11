/**
 * Service Map Module - Renders service dependency graph using Cytoscape.js
 */
import { formatMs, fmtNum, graphSignature, filterSelfServices, buildElements } from './serviceMapUtils.js';

let cy = null;

// Layout: connected services as a left-to-right dagre graph; isolated services (no edges) in a grid to its right.
const HIDE_SELF_KEY = 'tinyolly.map.hideSelf';
function hideSelfServices() { return localStorage.getItem(HIDE_SELF_KEY) === '1'; }
window.toggleHideSelfServices = (on) => {
    localStorage.setItem(HIDE_SELF_KEY, on ? '1' : '0');
    lastSignature = null;                    // force a re-layout
    if (window.refreshServiceMap) window.refreshServiceMap();
};

let lastSignature = null;

// Size the map to the visible window (below its top edge) so the fitted graph is always fully in view.
function sizeMapToViewport() {
    const box = document.querySelector('.map-container');
    if (!box) return;
    const pageTop = box.getBoundingClientRect().top + window.scrollY;   // independent of current scroll
    box.style.height = `${Math.max(420, window.innerHeight - pageTop - 16)}px`;
}

let resizeTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (cy && document.querySelector('.map-container')) { sizeMapToViewport(); cy.resize(); cy.fit(undefined, 30); } }, 150);
});

function layoutMap() {
    sizeMapToViewport();
    const connected = cy.nodes().filter(n => n.degree(false) > 0);
    const isolated = cy.nodes().filter(n => n.degree(false) === 0);

    const place = () => {
        const bb = connected.empty() ? { x1: 0, x2: 0, y1: 0, h: 0 } : connected.boundingBox();
        const rows = Math.max(3, Math.ceil(bb.h / 96));
        const x0 = connected.empty() ? 0 : bb.x2 + 140;
        isolated.sort((a, b) => a.data('label').localeCompare(b.data('label'))).forEach((n, i) => {
            n.position({ x: x0 + Math.floor(i / rows) * 150, y: bb.y1 + (i % rows) * 96 });
        });
        cy.resize();
        cy.fit(undefined, 30);   // whole graph visible
        applyPendingSelection();
    };

    if (connected.empty()) { place(); return; }
    const layout = connected.union(connected.connectedEdges()).layout({
        name: 'dagre',
        rankDir: 'LR',
        nodeSep: 60,
        rankSep: 120,
        edgeSep: 30,
        animate: false,
        fit: false,
        padding: 30
    });
    layout.one('layoutstop', place);
    layout.run();
}

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

    // Optionally hide TinyOlly's own services (set by the checkbox above the map)
    if (hideSelfServices()) graph = filterSelfServices(graph);

    const elements = buildElements(graph);

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
        const sig = graphSignature(elements);
        if (sig !== lastSignature) {
            lastSignature = sig;
            layoutMap();
        } else {
            cy.resize();
            applyPendingSelection();
        }
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
                    'width': 'data(w)',
                    'height': 'data(h)',
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
        layout: { name: 'preset' },
        minZoom: 0.1,
        maxZoom: 3,
        wheelSensitivity: 0.2
    });

    lastSignature = graphSignature(elements);
    layoutMap();

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
                    <button onclick="window.viewServiceTraces('${safeLabel}');"
                        style="flex: 1; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: all 0.2s;">
                        <span>Traces</span>
                    </button>
                    <button onclick="window.viewServiceSpans('${safeLabel}');"
                        style="flex: 1; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: all 0.2s;">
                        <span>Spans</span>
                    </button>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button onclick="window.viewServiceLogs('${safeLabel}');"
                        style="flex: 1; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: all 0.2s;">
                        <span>Logs</span>
                    </button>
                    <button onclick="window.viewMetricsForService('${safeLabel}');"
                        style="flex: 1; padding: 6px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px; font-weight: 500; transition: all 0.2s;">
                        <span>Metrics</span>
                    </button>
                </div>
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
