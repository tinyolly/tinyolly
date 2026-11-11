// Run: node --test docker/apps/tinyolly-ui/tests-js/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { formatMs, fmtNum, filterSelfServices, buildElements, graphSignature } from '../static/serviceMapUtils.js';

const node = (id, extra = {}) => ({ id, label: id, ...extra });
const nodesOf = els => Object.fromEntries(els.filter(e => e.group === 'nodes').map(e => [e.data.id, e.data]));

test('formatMs picks a readable unit', () => {
    assert.equal(formatMs(0.123), '0.12ms');
    assert.equal(formatMs(12.34), '12.3ms');
    assert.equal(formatMs(1500), '1.5s');
    assert.equal(formatMs(600002.69), '10m');
    assert.equal(formatMs(7200000), '2h');
    assert.equal(formatMs('x'), '');
    assert.equal(fmtNum(1.23456), 1.23);
});

test('shape = type, colour = health', () => {
    const graph = {
        nodes: [node('client'), node('server', { metrics: { error_rate: 2 } }), node('leaf', { metrics: { error_rate: 9 } }),
                node('db', { type: 'database' }), node('mq', { type: 'messaging' }), node('lonely')],
        edges: [{ source: 'client', target: 'server' }, { source: 'server', target: 'leaf' }, { source: 'server', target: 'db' },
                { source: 'server', target: 'mq' }],
    };
    const n = nodesOf(buildElements(graph));
    assert.deepEqual([n.client.shape, n.client.type], ['diamond', 'Client']);
    assert.deepEqual([n.server.shape, n.server.type], ['round-rectangle', 'Server']);
    assert.deepEqual([n.leaf.shape, n.leaf.type], ['hexagon', 'External']);
    assert.equal(n.db.shape, 'barrel');
    assert.equal(n.mq.shape, 'rhomboid');
    assert.deepEqual([n.lonely.shape, n.lonely.type, n.lonely.color], ['ellipse', 'Isolated', '#94a3b8']);
    assert.equal(n.client.color, '#2563eb');   // healthy
    assert.equal(n.server.color, '#f59e0b');   // some errors
    assert.equal(n.leaf.color, '#ef4444');     // >5% errors
});

test('hexagons are drawn wider than tall (regular hexagon), other shapes square', () => {
    const n = nodesOf(buildElements({ nodes: [node('a'), node('b')], edges: [{ source: 'a', target: 'b' }] }));
    assert.equal(n.b.shape, 'hexagon');
    assert.ok(Math.abs(n.b.w / n.b.h - 2 / Math.sqrt(3)) < 0.001);
    assert.deepEqual([n.a.w, n.a.h], [40, 40]);
});

test('edges carry formatted p95 labels', () => {
    const els = buildElements({ nodes: [node('a'), node('b')], edges: [{ source: 'a', target: 'b', p95: 1500, value: 3 }] });
    const e = els.find(x => x.group === 'edges');
    assert.deepEqual([e.data.id, e.data.label, e.data.weight], ['a-b', '1.5s', 3]);
});

test('filterSelfServices removes tinyolly-* nodes and their edges', () => {
    const g = filterSelfServices({
        nodes: [node('cart'), node('tinyolly-ui'), node('tinyolly-opamp-server')],
        edges: [{ source: 'cart', target: 'tinyolly-ui' }, { source: 'tinyolly-ui', target: 'cart' }],
    });
    assert.deepEqual(g.nodes.map(n => n.id), ['cart']);
    assert.equal(g.edges.length, 0);
});

test('graphSignature is stable for metric changes and changes with topology', () => {
    const a = buildElements({ nodes: [node('a'), node('b')], edges: [{ source: 'a', target: 'b' }] });
    const aMetrics = buildElements({ nodes: [node('b', { metrics: { error_rate: 50 } }), node('a')], edges: [{ source: 'a', target: 'b' }] });
    const c = buildElements({ nodes: [node('a'), node('b'), node('c')], edges: [{ source: 'a', target: 'b' }] });
    assert.equal(graphSignature(a), graphSignature(aMetrics));
    assert.notEqual(graphSignature(a), graphSignature(c));
});

test('every static JS file parses as an ES module', () => {
    const dir = new URL('../static/', import.meta.url).pathname;
    for (const f of readdirSync(dir).filter(f => f.endsWith('.js'))) {
        execFileSync(process.execPath, ['--input-type=module', '--check'], { input: readFileSync(dir + f) });
    }
});
