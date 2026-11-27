// TinyOlly AI SRE Agent console. All telemetry and model text is untrusted: it is only ever set with textContent.
'use strict';
const $ = id => document.getElementById(id);
const LABEL = { detector: 'detector', incident: 'incident', thinking: 'thinking', tool_call: 'tool', tool_result: 'result', finding: 'finding',
  recovery: 'recovery', answer: 'answer', question: 'you asked', note: 'note', info: 'info' };
const SUGGESTED = ['What changed in the last 15 minutes?', 'Which service is the riskiest right now?', 'Is anything failing right now, and why?'];
const MAX_ROWS = 600;

let reveal = false, grades = {};          // presenter toggle: score cards against the injected faults
let config = { links: {} }, status = {}, records = new Map(), lastN = 0, filter = 'all', selected = null, pinned = true;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function link(kind, value, text) {
  const template = config.links[kind];
  if (!template) return el('span', 'chip', text);
  const a = el('a', 'chip', text);
  a.href = template.replace('{id}', encodeURIComponent(value));
  a.target = '_blank'; a.rel = 'noopener';
  a.onclick = ev => ev.stopPropagation();
  return a;
}
const plain = s => String(s).replace(/\*\*|`/g, '').replace(/(^|\s)\*(\S[^*\n]*?)\*/g, '$1$2');           // models write markdown; show it as plain text
const clock = s => new Date(s * 1000).toISOString().slice(11, 19);
const duration = s => s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;

// ---- theme ----
function themeLabel() { $('theme').textContent = document.documentElement.dataset.theme === 'dark' ? '☀️ Light' : '🌙 Dark'; }
$('theme').onclick = () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('tinyolly-theme', next); } catch (e) { /* private mode */ }
  themeLabel();
};

// ---- stream ----
function text(e) {
  const d = e.data || {};
  if ((e.type === 'finding' || e.type === 'recovery' || e.type === 'answer' || e.type === 'note') && d.summary)
    return (e.type === 'note' && d.duty ? `${d.duty}: ${d.verdict}. ` : '') + d.summary;
  return e.msg;
}
function addRow(e) {
  const stream = $('stream');
  stream.querySelector('.empty')?.remove();
  const row = el('div', `row ${e.type}`);
  row.dataset.inv = e.inv ?? '';
  const failed = e.lvl === 'ERROR' || e.lvl === 'WARNING';
  row.append(el('time', '', e.t), el('span', `chip ${failed ? 'error' : e.type}`, LABEL[e.type] || e.type), el('span', 'msg', ['finding', 'recovery', 'answer', 'note'].includes(e.type) ? plain(text(e)) : text(e)));
  if (e.detail) {
    row.classList.add('has-detail');
    row.title = 'Click for the full text';
    row.onclick = ev => {
      if (ev.target.tagName === 'PRE' || String(getSelection())) return;
      const open = row.querySelector('pre');
      if (open) open.remove(); else row.append(el('pre', '', e.detail));
    };
  }
  row.hidden = selected !== null && row.dataset.inv !== String(selected);
  stream.append(row);
  while (stream.childElementCount > MAX_ROWS) stream.firstElementChild.remove();
  if (pinned) stream.scrollTop = stream.scrollHeight; else $('jump').hidden = false;
}
$('stream').addEventListener('scroll', () => {
  const s = $('stream');
  pinned = s.scrollHeight - s.scrollTop - s.clientHeight < 30;
  if (pinned) $('jump').hidden = true;
});
$('jump').onclick = () => { pinned = true; $('jump').hidden = true; $('stream').scrollTop = $('stream').scrollHeight; };

function select(id) {
  selected = selected === id ? null : id;
  for (const row of $('stream').querySelectorAll('.row')) row.hidden = selected !== null && row.dataset.inv !== String(selected);
  $('unfilter').hidden = selected === null;
  $('unfilter').textContent = `Incident ${selected} only ✕`;
  pinned = true; $('stream').scrollTop = $('stream').scrollHeight;
  renderCards();
}
$('unfilter').onclick = () => select(selected);

// ---- investigation cards ----
const VERDICT = { act_now: 'act now', watch: 'watch', noise: 'noise' };
const TL_ICON = { change: '⇄', detected: '!', signal: '+', investigation: '…', concluded: '✓', fix: '→', resolved: '↘', recovery: '♥', postmortem: '✎' };
const TH_ICON = { confirmed: '✓', ruled_out: '✗', open: '?' };

// One tool call of the investigation as a chip that opens the same query in TinyOlly; the result is in the tooltip.
function trailChip(x) {
  const a = x.args || {}, t = x.tool || '?';
  const detail = a.service || (a.trace_id ? String(a.trace_id).slice(0, 8) : '') || a.name || a.metric || '';
  const label = detail ? `${t} · ${detail}` : t;
  let kind = null, value = '';
  if (a.trace_id && /trace|span/.test(t)) { kind = 'trace'; value = a.trace_id; }
  else if (t === 'query_logs') { kind = 'logs'; value = a.service || a.trace_id || ''; }
  else if (t === 'search_spans') { kind = 'spans'; value = a.service || ''; }
  else if (t === 'search_traces') { kind = 'traces'; value = a.service || ''; }
  else if (/metric/.test(t)) { kind = 'metrics'; value = a.name || a.metric || ''; }
  else if (/service_map|edge|map_diff/.test(t)) kind = 'map';
  else if (/list_services|compare_windows|version_split/.test(t)) kind = 'catalog';
  const c = kind ? link(kind, value, label) : el('span', 'chip', label);
  c.title = (x.ok === false ? 'failed: ' : '') + (x.result || '');
  if (x.ok === false) c.classList.add('bad');
  return c;
}
function timeline(r) {
  const box = el('details', 'timeline'); box.open = r.state !== 'resolved';
  box.append(el('summary', 'label', `Timeline · ${r.timeline.length} events`));
  for (const e of r.timeline) {
    const row = el('div', `tl ${e.kind}`);
    row.append(el('time', '', clock(e.t)), el('span', 'tl-icon', TL_ICON[e.kind] || '·'), el('span', '', plain(e.text)));
    box.append(row);
  }
  return box;
}
async function showPostmortem(r, btn) {
  btn.disabled = true; btn.textContent = r.postmortem ? 'Opening…' : 'Writing… (the model takes up to a minute)';
  let md = r.postmortem;
  try {
    if (!md) {
      const res = await fetch(`api/investigations/${r.id}/postmortem`, { method: 'POST' });
      md = (await res.json()).markdown || '';
    }
  } catch (e) { md = ''; }
  btn.disabled = false; btn.textContent = 'Postmortem';
  if (!md) { btn.textContent = 'Postmortem failed, retry'; return; }
  $('pm-title').textContent = `Postmortem draft · incident #${r.id}`;
  $('pm-text').textContent = md;
  $('pm-copy').onclick = () => navigator.clipboard && navigator.clipboard.writeText(md).then(() => { $('pm-copy').textContent = 'Copied'; });
  $('pm-download').onclick = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([md], { type: 'text/markdown' })); a.download = `postmortem-incident-${r.id}.md`; a.click();
  };
  $('pm-copy').textContent = 'Copy';
  $('pm').showModal();
}

function fixBlock(fix) {
  const box = el('div', 'fix');
  box.append(el('div', '', plain(fix.action)));
  if (fix.target) box.append(el('div', 'sub', `target: ${fix.target}`));
  if (fix.command) box.append(el('code', '', fix.command));
  if (fix.risk) box.append(el('div', 'sub', `risk: ${fix.risk}`));
  const actions = el('div', 'fix-actions');
  const apply = el('button', '', 'Apply');
  apply.type = 'button'; apply.disabled = true; apply.title = 'Proposed only: a human applies it';
  actions.append(apply);
  if (fix.command && navigator.clipboard) {
    const copy = el('button', '', 'Copy command');
    copy.type = 'button';
    copy.onclick = ev => { ev.stopPropagation(); navigator.clipboard.writeText(fix.command).then(() => { copy.textContent = 'Copied'; }); };
    actions.append(copy);
  }
  box.append(actions);
  return box;
}
function card(r) {
  const c = el('article', 'card');
  c.dataset.id = r.id;
  const top = el('div', 'card-top');
  top.append(el('span', `pill ${r.state}`, r.state), el('span', 'sub', `#${r.incident} · ${clock(r.opened_at)} UTC`));
  if (r.verdict) top.append(el('span', `pill verdict ${r.verdict}`, VERDICT[r.verdict] || r.verdict));
  if (r.would_page !== null && r.would_page !== undefined)
    top.append(el('span', `pill page ${r.would_page ? 'yes' : 'no'}`, r.would_page ? 'would page' : 'would not page'));
  const g = reveal && grades[r.id];
  if (g) top.append(el('span', `pill grade ${g.result}`, g.result === 'false-positive' ? 'false positive' : `${g.result} · ${g.scenario_title}`));
  c.append(top, el('h3', '', r.title));
  const seen = r.symptoms.filter(s => s !== r.title);   // once retitled by cause, the trigger is listed here too
  if (seen.length) c.append(el('div', 'sub', seen.join(' · ')));

  const cause = r.root_cause || r.summary;
  if (cause) c.append(el('div', 'label', r.confidence ? `Conclusion · ${r.confidence} confidence` : 'Conclusion'), el('p', '', plain(cause)));
  else if (r.state === 'investigating') c.append(el('p', 'sub', 'Investigating…'));

  if ((r.theories || []).length) {
    const list = el('ul', 'theories');
    for (const t of r.theories) {
      const li = el('li', `theory ${t.status}`);
      li.append(el('span', 'th-icon', TH_ICON[t.status] || '?'), el('span', 'th-claim', plain(t.claim)), el('span', 'sub', plain(t.evidence || '')));
      list.append(li);
    }
    c.append(el('div', 'label', 'Theories'), list);
  }
  const trace = (r.evidence || []).find(e => e.kind === 'trace');
  if (trace || (r.trail || []).length) {
    const tags = el('div', 'tags');
    if (trace) tags.append(link('trace', trace.value, `trace ${trace.value.slice(0, 8)}`));
    for (const x of r.trail || []) tags.append(trailChip(x));
    c.append(el('div', 'label', `Evidence trail${(r.trail || []).length ? ` · ${r.trail.length} queries` : ''}`), tags);
  }
  if (r.blast_radius.length) {
    const tags = el('div', 'tags');
    for (const s of r.blast_radius) tags.append(link('service', s, s === r.service ? `${s} (cause)` : s));
    c.append(el('div', 'label', 'Blast radius'), tags);
  }
  if (r.suggested_fixes.length) {
    c.append(el('div', 'label', 'Proposed, not applied'));
    r.suggested_fixes.forEach(f => c.append(fixBlock(f)));
  }
  if ((r.timeline || []).length) c.append(timeline(r));
  if (r.recovered) {
    c.append(el('div', 'label', `Recovered: ${r.recovered}${r.ttr_s !== null ? ` · ${duration(r.ttr_s)} after detection` : ''}`));
    if (r.recovery_note) c.append(el('p', 'sub', plain(r.recovery_note).replace(/^Recovered:\s*(yes|no|unknown[^.]*)\.?\s*/i, '')));
  }
  if (r.ms) c.append(el('p', 'sub', `${r.model} · ${(r.ms / 1000).toFixed(0)}s · ${r.tool_calls} tool calls · ${r.tokens_in + r.tokens_out} tokens`));
  if (['concluded', 'recovering', 'resolved'].includes(r.state) && r.summary) {
    const b = el('button', 'pm-btn', r.postmortem ? 'Postmortem' : 'Write postmortem');
    b.type = 'button'; b.onclick = ev => { ev.stopPropagation(); showPostmortem(r, b); };
    c.append(b);
  }
  return c;
}
// one line per investigation; the full card opens on click
function item(r) {
  const b = el('button', 'item');
  b.type = 'button'; b.dataset.id = r.id; b.onclick = () => select(r.id);
  const meta = [`#${r.incident}`, `${clock(r.opened_at)} UTC`];
  if (r.service && r.state !== 'open' && r.state !== 'investigating') meta.push(`cause: ${r.service}`);
  const g = reveal && grades[r.id];
  if (g) meta.push(g.result);
  b.append(el('span', 'item-name', r.title), el('span', `pill ${r.state}`, r.state), el('span', 'sub', meta.join(' · ')));
  return b;
}
let rendered = '', listAt = 0;
function renderCards() {
  const list = [...records.values()].sort((a, b) => b.id - a.id)
    .filter(r => filter === 'all' || (filter === 'done') === (r.state === 'resolved'));
  const key = JSON.stringify([filter, selected, list, reveal && grades]);
  if (key === rendered) return;                       // unchanged: keep the reader's selection and focus
  rendered = key;
  const box = $('cards'), open = selected === null ? null : records.get(selected);
  const was = box.dataset.view || 'list', view = open ? String(open.id) : 'list';
  const at = box.scrollTop;
  if (was === 'list') listAt = at;
  box.dataset.view = view;
  if (open) {
    const back = el('button', 'back', '← All investigations');
    back.type = 'button'; back.onclick = () => select(selected);
    box.replaceChildren(back, card(open));
  } else box.replaceChildren(...(list.length ? list.map(item) : [el('p', 'empty', records.size ? 'None in this filter.' : 'No incidents yet. The agent opens one when a detector fires.')]));
  box.scrollTop = view === was ? at : (open ? 0 : listAt);     // keep the reader's place; a newly opened one starts at the top
}
$('filters').onclick = ev => {
  const f = ev.target.dataset.f;
  if (!f) return;
  filter = f;
  if (selected !== null) select(selected);             // a filter always shows the list
  for (const b of $('filters').children) b.classList.toggle('on', b === ev.target);
  renderCards();
};

// ---- data ----
function header() {
  $('env').textContent = `env: ${config.env || '?'}`;
  $('counts').textContent = `${status.open_incidents ?? 0} open · ${status.investigations_last_hour ?? 0}/${status.max_per_hour ?? '?'} runs this hour`;
  const d = status.demo, mmss = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  $('demo').hidden = !d || d.state === 'stopped';
  $('reveal').hidden = !d;
  if (d) $('demo').textContent = `demo: ${d.state}` + (d.next_fault_in_s != null ? ` · next fault in ${mmss(Math.max(0, d.next_fault_in_s))}` : '');
}
async function refresh() {
  try {
    const j = await (await fetch('api/investigations')).json();
    status = j.status;
    records = new Map(j.investigations.map(r => [r.id, r]));
    if (reveal) grades = (await (await fetch('demo/grades')).json()).grades || {};
    header(); renderCards();
  } catch (e) { /* the stream tag already shows the disconnect */ }
}
function connect() {
  const source = new EventSource('stream');
  source.onopen = () => { $('conn').textContent = 'live'; $('conn').classList.remove('bad'); };
  source.onerror = () => { $('conn').textContent = 'disconnected, retrying'; $('conn').classList.add('bad'); };
  source.onmessage = m => {
    const e = JSON.parse(m.data);
    if (e.n <= lastN) { $('stream').replaceChildren(); records.clear(); if (selected !== null) select(selected); }   // the agent restarted
    lastN = e.n;
    if (e.type === 'investigation') { if (e.data) { records.set(e.data.id, e.data); renderCards(); } return; }
    addRow(e);
  };
}

// ---- ask ----
async function ask(question) {
  question = question.trim();
  if (!question || $('send').disabled) return;
  $('send').disabled = true;
  $('send').textContent = status.busy ? 'Queued…' : 'Thinking…';       // one model run at a time
  $('q').value = '';
  pinned = true;
  if (selected !== null) select(selected);
  const failed = msg => addRow({ t: clock(Date.now() / 1000), type: 'info', lvl: 'ERROR', msg, inv: null });
  try {
    const res = await fetch('ask', { method: 'POST', body: JSON.stringify({ question }) });
    const j = await res.json();
    if (!res.ok) failed(j.error || 'the question failed');
    else if (j.skipped) failed(j.answer);                              // answers arrive on the stream; only refusals do not
  } catch (e) { failed('could not reach the agent'); }
  $('send').disabled = false; $('send').textContent = 'Ask';
}
async function models(post) {
  try {
    const j = await (await fetch('api/models', post ? { method: 'POST', body: JSON.stringify({ name: post }) } : {})).json();
    const sel = $('model'); sel.replaceChildren();
    for (const p of j.presets || []) {
      const o = el('option', '', `${p.label} · ${p.model}${p.reachable === 'ok' ? '' : p.reachable === 'unknown' ? '' : ' (unreachable)'}`);
      o.value = p.name; o.selected = p.name === j.current; o.title = p.reachable; sel.append(o);
    }
    sel.disabled = (j.presets || []).length < 2;
  } catch (e) { /* keep the last list */ }
}
$('model').onchange = ev => models(ev.target.value);
$('reveal').onclick = async () => {
  reveal = !reveal; $('reveal').textContent = reveal ? 'Hide scores' : 'Reveal scores';
  await refresh();
};
$('ask').onsubmit = ev => { ev.preventDefault(); ask($('q').value); };
for (const q of SUGGESTED) {
  const b = el('button', '', q);
  b.type = 'button'; b.onclick = () => ask(q);
  $('chips').append(b);
}

(async () => {
  themeLabel();
  try { config = await (await fetch('api/config')).json(); } catch (e) { /* links stay plain text */ }
  await refresh();
  models(); setInterval(models, 30000);
  connect();
  setInterval(refresh, 5000);
})();
