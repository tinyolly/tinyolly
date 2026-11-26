/** Extra text for a service-map edge label on LLM and MCP edges (tokens or tools, then calls blocked at the gateway). */
export function aiEdgeSuffix(edge) {
    const blocked = Object.values(edge.blocked || {}).reduce((a, b) => a + b, 0);
    const main = aiMain(edge);
    return [main, blocked ? `${blocked} blocked` : ''].filter(Boolean).join(' · ');
}

function aiMain(edge) {
    const fmt = n => {
        if (n < 1000) return String(Math.round(n));
        const k = n / 1000;
        const s = k.toFixed(1);
        return (s.endsWith('.0') ? s.slice(0, -2) : s) + 'k';
    };

    const tokens = (edge.tokens_in || 0) + (edge.tokens_out || 0);
    if (tokens > 0) {
        if (edge.value > 0 && edge.req_rate > 0) {
            return fmt(tokens / edge.value * edge.req_rate * 60) + ' tok/min';
        }
        return fmt(tokens) + ' tok';
    }

    const tools = edge.tools || {};
    const names = Object.keys(tools);
    if (names.length > 0) {
        let top = names[0];
        for (const name of names) {
            if (tools[name] > tools[top]) top = name;
        }
        const others = names.length - 1;
        return others > 0 ? `${top} +${others}` : top;
    }

    return '';
}
