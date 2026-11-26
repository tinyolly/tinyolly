// Run: node --test docker/apps/tinyolly-ui/tests-js/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { aiEdgeSuffix } from '../static/edgeLabels.js';

test('LLM edge: tokens per minute from tokens per call x call rate', () => {
    // 4690 + 755 tokens over 23 calls at 0.05 calls/s -> 236.7 tok/call * 3 calls/min = 710 tok/min
    assert.equal(aiEdgeSuffix({ value: 23, req_rate: 0.05, tokens_in: 4690, tokens_out: 755 }), '710 tok/min');
    assert.equal(aiEdgeSuffix({ value: 10, req_rate: 1, tokens_in: 400, tokens_out: 100 }), '3k tok/min');
    assert.equal(aiEdgeSuffix({ value: 10, req_rate: 1, tokens_in: 700, tokens_out: 80 }), '4.7k tok/min');
});

test('LLM edge without a rate shows the token total', () => {
    assert.equal(aiEdgeSuffix({ value: 3, req_rate: 0, tokens_in: 5000, tokens_out: 400 }), '5.4k tok');
    assert.equal(aiEdgeSuffix({ value: 3, tokens_in: 120, tokens_out: 0 }), '120 tok');
});

test('MCP edge: busiest tool, plus how many others', () => {
    assert.equal(aiEdgeSuffix({ value: 69, tools: { fetch: 23 } }), 'fetch');
    assert.equal(aiEdgeSuffix({ value: 9, tools: { search: 2, fetch: 5, cart: 1 } }), 'fetch +2');
});

test('plain edges get nothing', () => {
    assert.equal(aiEdgeSuffix({ value: 5, req_rate: 1 }), '');
    assert.equal(aiEdgeSuffix({ value: 5, tokens_in: 0, tokens_out: 0, tools: {} }), '');
    assert.equal(aiEdgeSuffix({}), '');
});

test('calls blocked at the gateway are counted after the main text', () => {
    assert.equal(aiEdgeSuffix({ value: 0, blocked: { Guardrail: 2, Authorization: 1 } }), '3 blocked');
    assert.equal(aiEdgeSuffix({ value: 69, tools: { fetch: 23 }, blocked: { Authorization: 4 } }), 'fetch · 4 blocked');
});
