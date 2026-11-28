#!/usr/bin/env node
// Screenshot the AI SRE Agent console with an investigation open and "prompts & tool results" showing.
//   scripts/shoot-sre-console.mjs [http://localhost:7173] [docs/images/ai-sre-console-light.png]
// Needs Node 22+ (built-in WebSocket), Chrome (or CHROME=...), and an agent that has at least one investigation.
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const url = process.argv[2] || 'http://localhost:7173';
const out = process.argv[3] || 'docs/images/ai-sre-console-light.png';
const records = (await (await fetch(`${url}/api/investigations`)).json()).investigations;
const pick = records.filter(r => r.tool_calls > 0 && r.root_cause).sort((a, b) => b.tool_calls - a.tool_calls || b.id - a.id)[0];
if (!pick) { console.error('no investigation with tool calls yet: run a demo shift first'); process.exit(1); }

const profile = mkdtempSync(join(tmpdir(), 'sre-shot-'));
const chrome = spawn(process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    ['--headless=new', '--remote-debugging-port=9333', `--user-data-dir=${profile}`, '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
try {
    let page;
    for (let i = 0; i < 50 && !page; i++) {
        await sleep(200);
        try { page = (await (await fetch('http://127.0.0.1:9333/json')).json()).find(t => t.type === 'page'); } catch { /* starting */ }
    }
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
    let id = 0; const waiting = new Map();
    ws.onmessage = m => { const d = JSON.parse(m.data); waiting.get(d.id)?.(d); };
    const send = (method, params = {}) => new Promise(ok => { waiting.set(++id, ok); ws.send(JSON.stringify({ id, method, params })); });
    const run = expression => send('Runtime.evaluate', { expression });

    await send('Emulation.setDeviceMetricsOverride', { width: 1500, height: 950, deviceScaleFactor: 1.2, mobile: false });
    await send('Page.addScriptToEvaluateOnNewDocument', { source: "localStorage.setItem('tinyolly-theme','light');localStorage.setItem('tinyolly-sre-trace','1')" });
    await send('Page.navigate', { url });
    await sleep(4000);
    await run(`document.querySelector('.item[data-id="${pick.id}"]').click()`);
    await sleep(2000);
    await run(`const b = document.querySelector('.tx-toggle'); if (b && b.textContent.startsWith('Show')) b.click()`);
    await sleep(2000);
    await run(`const t = document.querySelector('.tx.tool'); if (t) { t.open = true; const b = document.getElementById('cards');
               b.scrollTop += document.querySelector('.trace-block').getBoundingClientRect().top - b.getBoundingClientRect().top - 8; }`);
    await sleep(1000);
    const open = await send('Runtime.evaluate', { expression: `!!document.querySelector('.tx.tool[open]')`, returnByValue: true });
    if (!open.result.result.value) throw new Error('the transcript is not showing (incident older than the last agent restart?)');
    const shot = await send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(out, Buffer.from(shot.result.data, 'base64'));
    console.log(`ok   ${out} (incident ${pick.id})`);
    ws.close();
} finally {
    chrome.kill();
    await sleep(500);
    rmSync(profile, { recursive: true, force: true });
}
