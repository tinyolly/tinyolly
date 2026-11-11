/** Pure logic for the service map (no DOM / Cytoscape) so it can be unit tested with `node --test`. */

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

/** Graph -> Cytoscape elements. Shape = service type, colour = health. */
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
    return elements;
}

// Identity of the drawn graph (nodes + edges + inferred types). Re-layout/re-fit only when it changes,
// so the 20 s auto-refresh does not reset the user's pan and zoom.
export function graphSignature(elements) {
    return elements.map(e => e.group === 'nodes' ? `n:${e.data.id}:${e.data.type}` : `e:${e.data.id}`).sort().join('|');
}

