/** Pure logic for the service map (no DOM / Cytoscape) so it can be unit tested with `node --test`. */
import { aiEdgeSuffix } from './edgeLabels.js';

// Dark Future Spectrum (github.com/stevelerner, palette/): one colour per node type, the same as the shapes in the
// legend (templates/partials/service-map-tab.html). Red and yellow are kept for the health ring.
export const HEALTH_FAILING = '#D23050', HEALTH_DEGRADED = '#E4B740';
export const TYPE_COLORS = {
    Client: '#E77D33', Server: '#43A4C6', External: '#C4993F', Database: '#3A3E82', Messaging: '#818A43',
    Agent: '#A64FBE', LLM: '#3E8C74', MCP: '#C66679', Isolated: '#8F949B',
    Waypoint: '#97C1CD', Gateway: '#874C21', Ztunnel: '#C89CCB'
};

// Human-readable duration from milliseconds
export function formatMs(ms) {
    const n = Number(ms);
    if (!isFinite(n)) return '';
    if (n < 1) return `${+n.toFixed(2)}ms`;
    if (n < 1000) return `${+n.toPrecision(3)}ms`;
    if (n < 60000) return `${+(n / 1000).toFixed(2)}s`;
    if (n < 3600000) return `${+(n / 60000).toFixed(1)}m`;
    return `${+(n / 3600000).toFixed(1)}h`;
}

export const fmtNum = v => (isFinite(Number(v)) ? +Number(v).toFixed(2) : v);


/** Drop TinyOlly's own services (and their edges) from a graph. */
export function filterSelfServices(graph) {
    const isSelf = id => String(id).startsWith('tinyolly-');
    return {
        ...graph,
        nodes: graph.nodes.filter(n => !isSelf(n.label || n.id)),
        edges: (graph.edges || []).filter(e => !isSelf(e.source) && !isSelf(e.target)),
    };
}

const NODE_SIZE = 40;
// Node types TinyOlly infers from callers' spans (tinyolly_common/graph_infer.py): the node itself sends nothing.
export const INFERRED_TYPES = new Set(['llm', 'mcp', 'external']);

/** Edge style class: denied beats plaintext beats mTLS; anything else is plain. */
export function edgeClass(edge) {
    if ((edge.denied_count || 0) > 0) return 'denied';
    if (edge.mtls === false) return 'plaintext';
    if (edge.mtls === true) return 'mtls';
    return '';
}

/** One-line posture summary for the bar above the map. */
export function postureSummary(p) {
    if (!p || !p.total_edges) return '';
    const parts = [`mTLS ${fmtNum(p.mtls_pct)}%`, `${p.plaintext_edges} plaintext`, `${p.denied.length} denied`];
    return parts.join(' · ');
}

/** Graph -> Cytoscape elements. Shape = service type, fill = type, ring = health. */
export function buildElements(graph) {
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

        // Shape = what the node is (always); fill = type; ring = health.
        if (node.type === 'database') {
            shape = 'barrel'; type = 'Database';
        } else if (node.type === 'messaging') {
            shape = 'rhomboid'; type = 'Messaging';
        } else if (node.type === 'agent') {                     // GenAI caller (tinyolly_common: service with gen_ai client spans)
            shape = 'round-triangle'; type = 'Agent';
        } else if (node.type === 'llm') {                       // inferred from gateway / SDK spans nothing answered
            shape = 'star'; type = 'LLM';
        } else if (node.type === 'mcp') {
            shape = 'vee'; type = 'MCP';
        } else if (inCount === 0 && outCount === 0) {
            shape = 'ellipse'; type = 'Isolated';
        } else if (inCount === 0) {
            shape = 'diamond'; type = 'Client';
        } else if (outCount === 0) {
            shape = 'hexagon'; type = 'External';
        } else {
            type = 'Server';
        }
        // Mesh roles (from the backend) override the shape: what the node is in the mesh.
        if (node.role === 'waypoint') { shape = 'cut-rectangle'; type = 'Waypoint'; }
        else if (node.role === 'gateway') { shape = 'pentagon'; type = 'Gateway'; }
        else if (node.role === 'ztunnel') { shape = 'tag'; type = 'Ztunnel'; }

        let metrics = node.metrics || {};
        // Nodes that emit no spans (LLM, MCP server, database, external host): health from their incoming edges,
        // counting calls blocked at a gateway as errors.
        if (!Object.keys(metrics).length && (graph.edges || []).some(e => e.target === node.id)) {
            const ins = graph.edges.filter(e => e.target === node.id);
            const calls = ins.reduce((a, e) => a + (e.value || 0) + (e.denied_count || 0), 0);
            const bad = ins.reduce((a, e) => a + (e.error_count || 0) + (e.denied_count || 0), 0);
            metrics = { duration_p95: Math.max(...ins.map(e => e.p95 || 0)) || null,
                        error_rate: calls ? Math.round(1000 * bad / calls) / 10 : 0 };
        }
        const color = TYPE_COLORS[type];                        // fill and shape = type; the ring = health
        const health = metrics.error_rate > 5 ? 'failing' : metrics.error_rate > 0 ? 'degraded' : '';

        elements.push({
            group: 'nodes',
            classes: [INFERRED_TYPES.has(node.type) ? 'inferred' : '', health].filter(Boolean).join(' '),   // inferred (no spans of its own): dashed outline
            data: {
                id: node.id,
                label: node.label,
                shape: shape,
                w: shape === 'hexagon' ? NODE_SIZE * 1.1547 : NODE_SIZE,   // a regular hexagon is 1.1547x wider than tall;
                h: NODE_SIZE,                                               // a square box would squash it horizontally
                type: type,
                role: node.role || 'service',
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
                classes: edgeClass(edge),
                data: {
                    id: `${edge.source}-${edge.target}`,
                    source: edge.source,
                    target: edge.target,
                    label: [edge.p95 ? formatMs(edge.p95) : '', aiEdgeSuffix(edge)].filter(Boolean).join(' · '),
                    p95: edge.p95,
                    weight: edge.value,
                    mtls: edge.mtls ?? null,
                    kind: edge.source_kind || 'traces',
                    denied: edge.denied_count || 0
                }
            });
        });
    }
    return elements;
}

// Identity of the drawn graph (nodes + edges + inferred types). Re-layout/re-fit only when it changes,
// so the 20 s auto-refresh does not reset the user's pan and zoom.
export function graphSignature(elements) {
    return elements.map(e => e.group === 'nodes' ? `n:${e.data.id}:${e.data.type}:${e.data.role}` : `e:${e.data.id}`).sort().join('|');
}

