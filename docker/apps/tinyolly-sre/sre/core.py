"""Generic SRE agent: detect -> group into incidents -> investigate once with a model + MCP tools -> recovery check.
Knows nothing about a telemetry product; everything product-specific lives in a Backend."""
from __future__ import annotations
import collections, json, logging, os, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from .backend import Backend, Signal
from .backends import BACKENDS
from .console import HTML

E = os.getenv
LLM_URL = E("LLM_URL", "http://host.docker.internal:11434/v1").rstrip("/")   # any OpenAI-compatible endpoint (Ollama default)
LLM_KEY = E("LLM_API_KEY", "")
MODEL = E("MODEL", "qwen3:8b")
DETECT_S = int(E("DETECT_SECONDS", "30"))
WARMUP_S = int(E("WARMUP_SECONDS", "60"))
SETTLE_S = int(E("INCIDENT_SETTLE_SECONDS", "30"))
CLEAR_POLLS = int(E("INCIDENT_CLEAR_POLLS", "2"))
MAX_CALLS = int(E("MAX_TOOL_CALLS", "6"))
DEADLINE_S = int(E("DEADLINE_SECONDS", "120"))
MAX_PER_HOUR = int(E("MAX_INVESTIGATIONS_PER_HOUR", "12"))
MAX_TOOL_CHARS = int(E("MAX_TOOL_CHARS", "2500"))
MAX_TOKENS = int(E("MAX_TOKENS", "1500"))
PORT = int(E("PORT", "8080"))
ENV_NAME = E("ENV_NAME", "local")
REVIEW_EVERY_S = int(E("REVIEW_EVERY_SECONDS", "300"))          # one routine review per interval; 0 disables
REVIEW_MAX_PER_HOUR = int(E("REVIEW_MAX_PER_HOUR", "30"))        # shared by reviews, change notes, runbooks, digests (own budget, not the incident cap)
CHANGE_NOTES = E("CHANGE_NOTES", "1") == "1"                    # change-risk note per new change marker, plus a post-change check
CHANGE_CHECK_S = int(E("CHANGE_CHECK_SECONDS", "150"))
RUNBOOK = E("RUNBOOK", "1") == "1"                              # next steps after each incident's finding
DIGEST_EVERY_S = int(E("DIGEST_EVERY_SECONDS", "1800"))         # digest of the last hour; 0 disables
NOTE_CHARS = {"runbook": 700, "digest": 700}
ASKS = {
    "shift-note": "Shift note for the on-call: what is failing, what is slow, what changed, traffic. Cite service names and numbers from the evidence.",
    "instrumentation-gaps": "Instrumentation review: services that lack logs, logs without trace ids, spans that never close the loop. Name the services and the fix (which SDK or collector setting).",
    "mesh-posture": "Mesh security review: plaintext (non-mTLS) edges and denied calls. Say which edges matter and whether a denial looks like a misconfigured policy or an intended block.",
    "platform-health": "Platform health: is the telemetry store itself healthy (size vs cap, dropped metric series, cardinality)? Name the likely cause of any pressure and one action.",
    "change-risk": "A change just happened (see CHANGE). Give: the affected service's baseline, who depends on it, the one signal to watch, and whether anything already covers it.",
    "post-change": "Check the change in CHANGE against the evidence: did error rate, latency or traffic move for the affected or dependent services since it? Say clearly 'no visible effect' or what regressed.",
    "runbook": "Give up to 3 next steps for the incident in CHANGE, from actions that exist here (roll back or restart, toggle a flag, scale). Each with how to verify it worked.",
    "digest": "Digest of the last hour from the agent's own findings in the evidence: incidents, review flags, what recovered, what is still open.",
}
TOOL_DUTIES = {"change-risk", "post-change"}


class Feed(logging.Handler):
    """The console's memory: the agent's own log lines (newest last), with optional expandable detail."""
    def __init__(self):
        super().__init__(); self.q = collections.deque(maxlen=500); self.n = 0
    def emit(self, r):
        self.n += 1
        self.q.append({"n": self.n, "t": time.strftime("%H:%M:%S", time.gmtime(r.created)), "lvl": r.levelname, "msg": r.getMessage(), "detail": getattr(r, "detail", "")[:12000]})

FEED = Feed()
log = logging.getLogger("sre")
logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","msg":"%(message)s"}')
log.addHandler(FEED)


class MCP:
    """Minimal streamable-HTTP MCP client."""
    def __init__(self, url, auth=""):
        self.url, self.n, self.c = url, 0, httpx.Client(timeout=40)
        self.h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **({"Authorization": auth} if auth else {})}
    def _post(self, body):
        r = self.c.post(self.url, headers=self.h, json=body); r.raise_for_status()
        if r.headers.get("mcp-session-id"): self.h["mcp-session-id"] = r.headers["mcp-session-id"]
        data = next((l[5:].strip() for l in r.text.splitlines() if l.startswith("data:")), r.text)
        return json.loads(data) if data.strip() else {}
    def rpc(self, method, params=None):
        self.n += 1
        out = self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        if "error" in out: raise RuntimeError(f"{method}: {out['error'].get('message', out['error'])}")
        return out.get("result", {})
    def tools(self):
        self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "tinyolly-sre", "version": "1"}})
        try: self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Exception: pass
        return self.rpc("tools/list").get("tools", [])
    def call(self, name, args):
        res = self.rpc("tools/call", {"name": name, "arguments": args})
        return ("ERROR: " if res.get("isError") else "") + "\n".join(p.get("text", "") for p in res.get("content", []) if isinstance(p, dict))


def _slim(o):
    if isinstance(o, dict): return {k: _slim(v) for k, v in o.items() if k not in ("description", "title", "examples", "default") or isinstance(v, dict)}
    if isinstance(o, list): return [_slim(x) for x in o]
    return o

def to_openai(tools):
    return [{"type": "function", "function": {"name": t["name"], "description": (t.get("description") or "")[:300],
             "parameters": _slim(t.get("inputSchema") or {"type": "object", "properties": {}})}} for t in tools]

def parse_final(text):
    t = re.sub(r"```(?:json)?", "", text or "").strip(); i, j = t.find("{"), t.rfind("}")
    try: d = json.loads(t[i:j + 1]) if 0 <= i < j else None
    except ValueError: return None
    return d if isinstance(d, dict) and len(str(d.get("summary", "")).strip()) >= 30 else None

def chat(messages, tools=None, timeout=60):
    body = {"model": MODEL, "messages": messages, "max_tokens": MAX_TOKENS, **({"tools": tools} if tools else {})}
    r = httpx.post(f"{LLM_URL}/chat/completions", json=body, timeout=max(timeout, 5), headers={"Authorization": f"Bearer {LLM_KEY}"} if LLM_KEY else {})
    r.raise_for_status()
    d = r.json(); return d["choices"][0]["message"], d["choices"][0].get("finish_reason"), d.get("usage") or {}


class Agent:
    def __init__(self, backend: Backend):
        self.b, self.busy, self.starts, self.rstarts = backend, threading.Lock(), [], []
        self.history = collections.deque(maxlen=100)
        self.started = time.time(); self.incidents: list[dict] = []; self.inc_n = 0; self.stats = collections.Counter()
        self.playbook = open(E("PLAYBOOK_FILE", "playbook.md")).read() if os.path.exists(E("PLAYBOOK_FILE", "playbook.md")) else "You are an SRE agent. Answer with JSON {\"summary\",\"cited_trace_id\",\"cited_service\"}."

    # ---- one model run (investigation, recovery check, or free-form ask) ----
    def run(self, trigger, entity="", recovery=False, question="", duty="", ctx="", wait=300):
        """duty="" is an incident investigation / recovery check / ask; a duty name is a review-type note with its own budget."""
        if not self.busy.acquire(timeout=wait): log.info("busy, skipped: %s", trigger); return None
        try:
            now = time.time(); bud, cap = (self.rstarts, REVIEW_MAX_PER_HOUR) if duty else (self.starts, MAX_PER_HOUR)
            bud[:] = [x for x in bud if now - x < 3600]
            if len(bud) >= cap: log.warning("hourly cap (%d) reached, skipped: %s", cap, trigger); return None
            bud.append(now)
            t0, calls, tin, tout, status, seen, final, text = time.time(), 0, 0, 0, "error", [], None, ""
            if duty == "digest": evidence, top_svc, top_tid = self.digest_evidence(), "", ""
            elif duty: evidence, top_svc, top_tid = self.b.review_evidence(duty, ctx), "", ""
            else: evidence, top_svc, top_tid = self.b.evidence(trigger, entity, recovery)
            log.info("evidence (%d chars) for %r", len(evidence), trigger[:80], extra={"detail": evidence})
            tools, allow, mcp = [], set(), None
            if self.b.mcp_url and not recovery and (not duty or duty in TOOL_DUTIES):
                try:
                    mcp = MCP(self.b.mcp_url, self.b.mcp_auth)
                    listed = [t for t in mcp.tools() if self.b.mcp_allow is None or t["name"] in self.b.mcp_allow]
                    allow = {t["name"] for t in listed}; tools = to_openai(listed)
                except Exception as e: log.warning("MCP unavailable (%s); investigating from evidence only", type(e).__name__)
            sys_ = self.playbook + (f"\n\nOnly these tools exist: {', '.join(sorted(allow))}." if allow else "\n\nNo tools exist; use only the evidence.")
            user = (f"Question: {question}\nAnswer in plain text, at most 120 words." if question else
                    f"Duty: {duty}. {ASKS[duty]}\n{('CHANGE: ' + ctx) if ctx else ''}\nStart with `VERDICT: ok|watch|act`, then at most {NOTE_CHARS.get(duty, 400) // 6} words of plain text, no JSON." if duty else f"Trigger: {trigger}") + \
                   f"\nEnvironment: {ENV_NAME}. Now: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}.\n\nEVIDENCE (already fetched):\n{evidence}"
            msgs = [{"role": "system", "content": sys_}, {"role": "user", "content": user}]
            log.info("prompt to %s (%d tools)", MODEL, len(tools), extra={"detail": f"SYSTEM:\n{sys_}\n\nUSER:\n{user}"})
            nudges = 0
            try:
                while True:
                    left = DEADLINE_S - (time.time() - t0)
                    if left <= 2: status = "timeout"; break
                    m, fin, u = chat(msgs, tools or None, left); tin += u.get("prompt_tokens", 0); tout += u.get("completion_tokens", 0)
                    text = m.get("content") or text; tcs = m.get("tool_calls") or []
                    log.info("model reply: %d tokens out, tool calls %s", u.get("completion_tokens", 0), [t["function"]["name"] for t in tcs], extra={"detail": m.get("content") or "(no text)"})
                    if not tcs:
                        if question or duty: final, status = {"summary": (m.get("content") or "").strip()}, "ok"; break
                        final = parse_final(m.get("content"))
                        if final: status = "ok"; break
                        if nudges >= 2: status = "timeout"; break
                        nudges += 1; msgs += [{"role": "assistant", "content": m.get("content") or ""}, {"role": "user", "content": "Give the final JSON answer now."}]; continue
                    if calls + len(tcs) > MAX_CALLS: status = "timeout"; break
                    msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
                    for tc in tcs:
                        calls += 1; fn = tc["function"]["name"]
                        if fn not in allow: out = f"ERROR: tool not allowed; only: {', '.join(sorted(allow))}"; log.warning("refused tool %s", fn)
                        else:
                            try: out = mcp.call(fn, json.loads(tc["function"].get("arguments") or "{}"))
                            except Exception as e: out = f"ERROR: {e}"
                            log.info("tool %s -> %d chars", fn, len(out), extra={"detail": f"ARGS: {tc['function'].get('arguments')}\n\n{out[:MAX_TOOL_CHARS * 2]}"})
                        msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": out[:MAX_TOOL_CHARS]}); seen.append(out[:MAX_TOOL_CHARS])
                if status == "timeout" and not final:       # last call, no tools: answer from what was gathered
                    msgs.append({"role": "user", "content": "Stop calling tools. Give the final JSON answer now."})
                    m, _, _ = chat(msgs, None, 30); final = parse_final(m.get("content"))
            except Exception as e:
                status = "error"; text = text or f"{type(e).__name__}: {e}"; log.warning("run failed: %s", e)
            summ = str((final or {}).get("summary") or "[no final answer] " + re.sub(r"\s+", " ", text))[:600]
            tid, svc = str((final or {}).get("cited_trace_id") or ""), str((final or {}).get("cited_service") or "")
            known = " ".join(seen + [evidence])
            if not re.fullmatch(r"[0-9a-f]{32}", tid) or tid not in known: tid = top_tid     # cite only ids that were really seen
            if not svc or svc not in known: svc = top_svc
            self.stats["reviews" if duty else "investigations"] += 1
            f = {"summary": summ, "trace": tid, "service": svc, "status": status, "tool_calls": calls, "tokens_in": tin, "tokens_out": tout, "ms": int((time.time() - t0) * 1000)}
            log.info("%s (%s, %d tool calls): service=%s trace=%s | %s", "answer" if question else "finding", status, calls, svc or "-", tid or "-", summ)
            if duty:
                v = re.match(r"\s*VERDICT:\s*(ok|watch|act)\b", summ, re.I); verdict = v.group(1).lower() if v else "ok"
                f["summary"] = re.sub(r"^\s*VERDICT:\s*\w+\s*", "", summ)[:NOTE_CHARS.get(duty, 400)]; f["verdict"] = verdict
                self.b.publish("ai-review", f"AI SRE {duty}: {verdict}", {**f, "duty": duty, "model": MODEL})
            elif not question:
                self.b.publish("ai-finding", f"AI SRE: {trigger[:120]}", {**f, "trigger": trigger[:200], "model": MODEL})
            if not question: self.history.append({"t": time.time(), "kind": duty or "finding", "trigger": trigger[:120], "status": status, "verdict": f.get("verdict", ""), "summary": f["summary"][:200]})
            return f
        finally: self.busy.release()

    # ---- incidents ----
    def add_signal(self, s: Signal, now=None):
        now = now or time.time()
        inc = next((i for i in self.incidents if i["open"] and s.entity in i["entities"]), None)
        if inc:
            inc["last"], inc["quiet"] = now, 0
            if s.kind not in inc.setdefault("kinds", {inc["kind"]}): inc["kinds"].add(s.kind); inc["texts"].append(s.text)   # a second kind of symptom on the same entity
            return
        self.stats["signals"] += 1
        if now - self.started < WARMUP_S: log.info("warming up, signal ignored: %s", s.text); return
        self.inc_n += 1
        inc = {"n": self.inc_n, "kind": s.kind, "open": True, "entities": {s.entity}, "texts": [s.text], "t0": now, "last": now, "quiet": 0, "investigated": False, "svc": ""}
        self.incidents.append(inc); log.info("incident %d opened: %s", inc["n"], s.text)

    def tick(self, signals: list[Signal], now=None):
        now = now or time.time()
        live = {s.entity for s in signals}
        for s in signals: self.add_signal(s, now)
        for inc in self.incidents:
            if not inc["open"]: continue
            if not inc["investigated"] and now - inc["t0"] >= SETTLE_S:
                inc["investigated"] = True; trig = f"incident {inc['n']}: " + "; ".join(inc["texts"])
                threading.Thread(target=self._investigate, args=(inc, trig), daemon=True).start()
            elif inc["investigated"]:
                inc["quiet"] = 0 if inc["entities"] & live else inc["quiet"] + 1
                if inc["quiet"] >= CLEAR_POLLS:
                    inc["open"] = False; log.info("incident %d resolved", inc["n"])
                    threading.Thread(target=self.run, args=(f"incident {inc['n']} resolved: {'; '.join(inc['texts'])}", inc["svc"] or next(iter(inc["entities"])), True), daemon=True).start()

    def _investigate(self, inc, trig):
        f = self.run(trig, next(iter(inc["entities"])))
        if f:
            inc["svc"] = f["service"]
            if RUNBOOK: self.run(trig, duty="runbook", ctx=f"{trig} | finding: {f['summary']}", wait=120)

    def loop(self):
        while True:
            try: self.stats["checks"] += 1; self.tick(self.b.detect())
            except Exception as e: log.warning("detect failed: %s: %s", type(e).__name__, e)
            time.sleep(DETECT_S)

    def _quiet(self):
        return not any(i["open"] for i in self.incidents) and time.time() - self.started >= WARMUP_S

    def reviews(self):
        """Rotate through the backend's duties; skipped while an incident is open, warming up, or the model is busy (never delays an investigation)."""
        k = 0
        while REVIEW_EVERY_S > 0 and self.b.duties:
            time.sleep(REVIEW_EVERY_S)
            if not self._quiet(): continue
            duty = self.b.duties[k % len(self.b.duties)]; k += 1
            try: self.run(f"review: {duty}", duty=duty, wait=1)
            except Exception as e: log.warning("review %s failed: %s", duty, e)

    def changes(self):
        """Every new change marker (flag, deploy, policy) gets a change-risk note now and a post-change check later."""
        seen = {e.get("id") or e.get("timestamp") for e in self.b.changes(120)}
        while CHANGE_NOTES:
            time.sleep(DETECT_S)
            for e in reversed(self.b.changes(5)):
                key = e.get("id") or e.get("timestamp")
                if key in seen: continue
                seen.add(key); ctx = f"{e.get('title')} (source {e.get('source')}, {e.get('attributes') or {}})"[:300]
                log.info("change marker: %s", ctx)
                def go(ctx=ctx):
                    self.run(f"change: {ctx[:80]}", duty="change-risk", ctx=ctx, wait=60)
                    time.sleep(CHANGE_CHECK_S); self.run(f"post-change: {ctx[:80]}", duty="post-change", ctx=ctx, wait=120)
                threading.Thread(target=go, daemon=True).start()

    def digest_evidence(self):
        rows = [h for h in self.history if time.time() - h["t"] < 3600]
        return "AGENT FINDINGS, LAST HOUR (time | kind | verdict | trigger | summary):\n" + "\n".join(
            f"  {time.strftime('%H:%M', time.gmtime(h['t']))}Z | {h['kind']} | {h['verdict'] or h['status']} | {h['trigger']} | {h['summary']}" for h in rows) + \
            f"\nOPEN INCIDENTS: {[i['texts'][0] for i in self.incidents if i['open']] or 'none'}"

    def digest(self):
        first = True
        while DIGEST_EVERY_S > 0:
            time.sleep(min(300, DIGEST_EVERY_S) if first else DIGEST_EVERY_S); first = False
            if self.history and self._quiet(): self.run("digest", duty="digest", wait=1)

    def status(self):
        return {"uptime_s": int(time.time() - self.started), "model": MODEL, "backend": self.b.name, "open_incidents": sum(i["open"] for i in self.incidents),
                "investigations_last_hour": len(self.starts), "max_per_hour": MAX_PER_HOUR, "reviews_last_hour": len(self.rstarts), **self.stats}


def make_handler(agent: Agent):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, code, body, ctype="application/json"):
            b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            if self.path == "/healthz": return self._send(200, {"ok": True})
            if self.path.startswith("/events"):
                after = int(re.search(r"after=(\d+)", self.path).group(1)) if "after=" in self.path else 0
                return self._send(200, {"events": [e for e in FEED.q if e["n"] > after], "status": agent.status()})
            self._send(200, HTML, "text/html; charset=utf-8")
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError: body = {}
            if self.path == "/investigate":
                a = str(body.get("alert") or "manual trigger")[:200]
                threading.Thread(target=agent.run, args=(a,), daemon=True).start(); return self._send(202, {"started": a})
            if self.path == "/ask":
                q = str(body.get("question") or "").strip()[:400]
                if not q: return self._send(400, {"error": "question required"})
                f = agent.run("ask", question=q); return self._send(200, {"answer": (f or {}).get("summary", "skipped (busy or hourly cap)")})
            self._send(404, {"error": "not found"})
    return H


def main():
    name = E("SRE_BACKEND", "tinyolly")
    agent = Agent(BACKENDS[name]())
    log.info("tinyolly-sre up: backend=%s model=%s llm=%s detect=%ss", name, MODEL, LLM_URL, DETECT_S)
    if DETECT_S > 0:
        for fn in (agent.loop, agent.reviews, agent.changes, agent.digest): threading.Thread(target=fn, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(agent)).serve_forever()
