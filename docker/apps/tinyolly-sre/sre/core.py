"""Generic SRE agent: detect -> group into incidents -> investigate once with a model + MCP tools -> recovery check.
Knows nothing about a telemetry product; everything product-specific lives in a Backend."""
from __future__ import annotations
import atexit, collections, copy, json, logging, os, re, signal, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx
from .backend import Backend, Signal
from .backends import BACKENDS
from . import demo, grade, llm

STATIC = os.path.join(os.path.dirname(__file__), "static")
PAGES = {"/": ("index.html", "text/html"), "/console.css": ("console.css", "text/css"), "/console.js": ("console.js", "text/javascript")}

E = os.getenv
MODELS = llm.Models()                                            # presets: local Ollama (default), OpenAI, Claude; switchable at runtime
DETECT_S = int(E("DETECT_SECONDS", "30"))
WARMUP_S = int(E("WARMUP_SECONDS", "60"))
SETTLE_S = int(E("INCIDENT_SETTLE_SECONDS", "30"))
CLEAR_POLLS = int(E("INCIDENT_CLEAR_POLLS", "2"))
MAX_CALLS = int(E("MAX_TOOL_CALLS", "8"))
DEADLINE_S = int(E("DEADLINE_SECONDS", "120"))
MAX_PER_HOUR = int(E("MAX_INVESTIGATIONS_PER_HOUR", "12"))
MAX_TOOL_CHARS = int(E("MAX_TOOL_CHARS", "2500"))
REINVESTIGATE = int(E("INCIDENT_REINVESTIGATE", "1"))          # extra investigations when a new kind of symptom joins a concluded incident
GROUP_S = int(E("INCIDENT_GROUP_SECONDS", "180"))               # a caller/callee signal joins an incident this young
PORT = int(E("PORT", "8080"))
ENV_NAME = E("ENV_NAME", "local")
REVIEW_EVERY_S = int(E("REVIEW_EVERY_SECONDS", "300"))          # one routine review per interval; 0 disables
REVIEW_MAX_PER_HOUR = int(E("REVIEW_MAX_PER_HOUR", "30"))        # shared by reviews, change notes, runbooks, digests (own budget, not the incident cap)
CHANGE_NOTES = E("CHANGE_NOTES", "1") == "1"                    # change-risk note per new change marker, plus a post-change check
CHANGE_CHECK_S = int(E("CHANGE_CHECK_SECONDS", "150"))
RUNBOOK = E("RUNBOOK", "0") == "1"                              # off by default (repeated the card); next steps after each incident's finding
DIGEST_EVERY_S = int(E("DIGEST_EVERY_SECONDS", "1800"))         # digest of the last hour; 0 disables
NOTE_CHARS = {"runbook": 900, "digest": 900}
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
PM_SYS = ("You write blameless incident postmortems from the FACTS given (JSON). Use only those facts; do not invent numbers, people or systems. "
          "Answer in exactly these five markdown sections and nothing else:\n### Summary\n<2-3 sentences>\n### Impact\n<what was affected, for how long>\n"
          "### Five whys\n1. <why>\n(up to 5)\n### What went well\n- <item>\n(up to 4)\n### Prevention\n- <concrete action item>\n(up to 4)")
PM_KEYS = {"summary": "summary", "impact": "impact", "five whys": "five_whys", "what went well": "went_well", "prevention": "prevention"}


def parse_sections(text):
    """'### Heading' sections -> {key: text or [items]}; list sections are split into their numbered/bulleted lines."""
    out, key = {}, None
    for line in (text or "").splitlines():
        m = re.match(r"\s*#{2,4}\s*(.+?)\s*$", line)
        if m:
            key = PM_KEYS.get(m.group(1).strip().lower().rstrip(":")); continue
        if key and line.strip(): out.setdefault(key, []).append(line.strip())
    res = {}
    for k, lines in out.items():
        if k in ("summary", "impact"): res[k] = " ".join(lines)
        else: res[k] = [re.sub(r"^(\d+[.)]|[-*•])\s*", "", l) for l in lines if re.match(r"^(\d+[.)]|[-*•])\s*", l)]
    return res


class Feed(logging.Handler):
    """The console's memory: the agent's own log lines (newest last), typed and tagged with their investigation."""
    def __init__(self):
        super().__init__(); self.q = collections.deque(maxlen=500); self.n = 0; self.cond = threading.Condition()
    def emit(self, r):
        with self.cond:
            self.n += 1
            self.q.append({"n": self.n, "t": time.strftime("%H:%M:%S", time.gmtime(r.created)), "lvl": r.levelname, "msg": r.getMessage(),
                           "type": getattr(r, "type", "info"), "inv": getattr(r, "inv", None), "data": getattr(r, "data", None), "detail": getattr(r, "detail", "")[:12000]})
            self.cond.notify_all()
    def after(self, n, wait=0.0):
        """Events newer than n; waits up to `wait` seconds for one. A client ahead of us (agent restarted) gets everything."""
        with self.cond:
            if n > self.n: n = 0
            if wait and n >= self.n: self.cond.wait(wait)
            return [e for e in self.q if e["n"] > n]

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

def _raw(m):
    """Provider-native copy of an assistant turn (Claude), replayed unchanged on the next call."""
    return {"_raw": m["_raw"]} if m.get("_raw") else {}

def ev(type_, inv=None, detail="", data=None):
    """`extra` for a typed feed line."""
    return {"type": type_, "inv": inv, "detail": detail, "data": data}

def _clip(v, n):
    """At most n characters, cut at a word and marked, so the console never shows half a word."""
    s = str(v or "").strip()
    return s if len(s) <= n else s[:n - 1].rsplit(" ", 1)[0] + "…"

VERDICTS = ("act_now", "watch", "noise")
ERROR_KINDS = {"errors", "error-rate", "op-errors", "logs"}         # triage: act_now = would page a human (shadow mode: nothing is paged)


def structured(final):
    """The model's final JSON reduced to the fields the console shows. Fixes are text only and always `proposed`."""
    d = final or {}
    conf = str(d.get("confidence") or "").lower()
    fixes = d.get("suggested_fixes") if isinstance(d.get("suggested_fixes"), list) else []
    verdict = str(d.get("verdict") or "").lower().replace(" ", "_")
    verdict = verdict if verdict in VERDICTS else ("act_now" if conf == "high" else "watch")     # older/weaker models may omit it
    hyp = d.get("hypotheses") if isinstance(d.get("hypotheses"), list) else []
    theories = [{"claim": _clip(h.get("claim"), 200), "status": (str(h.get("status") or "open").lower().replace(" ", "_") if str(h.get("status") or "").lower().replace(" ", "_") in ("confirmed", "ruled_out", "open") else "open"),
                 "evidence": _clip(h.get("evidence"), 300)} for h in hyp if isinstance(h, dict) and h.get("claim")][:4]
    return {"root_cause": _clip(d.get("root_cause"), 600), "confidence": conf if conf in ("high", "medium", "low") else "low",
            "suggested_fixes": [{**{k: _clip(f.get(k), 400) for k in ("action", "target", "command", "risk")}, "status": "proposed"}
                                for f in fixes if isinstance(f, dict) and f.get("action")][:3],
            "verdict": verdict, "would_page": verdict == "act_now", "theories": theories}

def chat(messages, tools=None, timeout=60):
    return MODELS.chat(messages, tools, timeout)


class Agent:
    def __init__(self, backend: Backend):
        self.b, self.busy, self.starts, self.rstarts = backend, threading.Lock(), [], []
        self.history = collections.deque(maxlen=100)
        self.started = time.time(); self.incidents: list[dict] = []; self.inc_n = 0; self.stats = collections.Counter()
        self.investigations: dict[int, dict] = {}; self.ilock = threading.Lock()
        self.shift: demo.Shift | None = None          # demo shift driver, when a flag backend is configured
        self.playbook = open(E("PLAYBOOK_FILE", "playbook.md")).read() if os.path.exists(E("PLAYBOOK_FILE", "playbook.md")) else "You are an SRE agent. Answer with JSON {\"summary\",\"cited_trace_id\",\"cited_service\"}."

    # ---- one model run (investigation, recovery check, or free-form ask) ----
    def run(self, trigger, entity="", recovery=False, question="", duty="", ctx="", wait=300, inv=None):
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
            log.info("evidence (%d chars) for %r", len(evidence), trigger[:80], extra=ev("thinking", inv, evidence))
            tools, allow, mcp = [], set(), None
            if self.b.mcp_url and not recovery and (not duty or duty in TOOL_DUTIES):
                try:
                    mcp = MCP(self.b.mcp_url, self.b.mcp_auth)
                    listed = [t for t in mcp.tools() if self.b.mcp_allow is None or t["name"] in self.b.mcp_allow]
                    allow = {t["name"] for t in listed}; tools = to_openai(listed)
                except Exception as e: log.warning("MCP unavailable (%s); investigating from evidence only", type(e).__name__)
            elif getattr(self.b, "local_tools", None) and not recovery and (not duty or duty in TOOL_DUTIES):
                mcp = self.b.local_tools; listed = mcp.tools(); allow = {t["name"] for t in listed}; tools = to_openai(listed)   # replay: tools over recorded data
            sys_ = self.playbook + (f"\n\nOnly these tools exist: {', '.join(sorted(allow))}. At most {MAX_CALLS} tool calls in total; answer as soon as the evidence supports a cause." if allow else "\n\nNo tools exist; use only the evidence.")
            user = (f"Question: {question}\nAnswer in plain text, at most 120 words." if question else
                    f"Duty: {duty}. {ASKS[duty]}\n{('CHANGE: ' + ctx) if ctx else ''}\nStart with `VERDICT: ok|watch|act`, then at most {NOTE_CHARS.get(duty, 400) // 6} words of plain text, no JSON." if duty else f"Trigger: {trigger}") + \
                   f"\nEnvironment: {ENV_NAME}. Now: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}.\n\nEVIDENCE (already fetched):\n{evidence}"
            msgs = [{"role": "system", "content": sys_}, {"role": "user", "content": user}]
            log.info("prompt to %s (%d tools)", MODELS.model, len(tools), extra=ev("thinking", inv, f"SYSTEM:\n{sys_}\n\nUSER:\n{user}"))
            nudges, capped, used, trail = 0, False, [], []
            try:
                while True:
                    left = DEADLINE_S - (time.time() - t0)
                    if left <= 2: status = "timeout"; break
                    m, fin, u = chat(msgs, tools or None, left); tin += u.get("prompt_tokens", 0); tout += u.get("completion_tokens", 0)
                    text = m.get("content") or text; tcs = m.get("tool_calls") or []
                    log.info("model reply: %d tokens out, tool calls %s", u.get("completion_tokens", 0), [t["function"]["name"] for t in tcs], extra=ev("thinking", inv, m.get("content") or "(no text)"))
                    if not tcs:
                        if question or duty: final, status = {"summary": (m.get("content") or "").strip()}, "ok"; break
                        final = parse_final(m.get("content"))
                        if final: status = "ok"; break
                        if nudges >= 2: status = "timeout"; break
                        nudges += 1; msgs += [{"role": "assistant", "content": m.get("content") or "", **_raw(m)}, {"role": "user", "content": "Give the final JSON answer now."}]; continue
                    if calls + len(tcs) > MAX_CALLS: capped = True; break
                    msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs, **_raw(m)})
                    for tc in tcs:
                        calls += 1; fn = tc["function"]["name"]; args = tc["function"].get("arguments") or "{}"
                        log.info("tool %s %s", fn, args[:160], extra=ev("tool_call", inv, args))
                        if fn not in allow: out = f"ERROR: tool not allowed; only: {', '.join(sorted(allow))}"; log.warning("refused tool %s", fn, extra=ev("tool_result", inv))
                        else:
                            try: out = mcp.call(fn, json.loads(tc["function"].get("arguments") or "{}"))
                            except Exception as e: out = f"ERROR: {e}"
                            used.append(fn); log.info("tool %s -> %d chars", fn, len(out), extra=ev("tool_result", inv, out[:MAX_TOOL_CHARS * 2]))
                        try: targs = json.loads(args) if args.strip() else {}
                        except ValueError: targs = {}
                        trail.append({"tool": fn, "args": {k: _clip(v, 120) for k, v in (targs if isinstance(targs, dict) else {}).items()},
                                      "result": _clip(re.sub(r"\s+", " ", out), 280), "ok": fn in allow and not out.startswith("ERROR"), "t": time.time()})
                        msgs.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": out[:MAX_TOOL_CHARS]}); seen.append(out[:MAX_TOOL_CHARS])
                if (capped or status == "timeout") and not final:       # last call, no tools: answer from what was gathered
                    msgs.append({"role": "user", "content": "Stop calling tools. Give the final JSON answer now."})
                    m, _, u = chat(msgs, None, 30); tin += u.get("prompt_tokens", 0); tout += u.get("completion_tokens", 0)
                    text = m.get("content") or text
                    if question or duty: final = {"summary": text.strip()} if text.strip() else None
                    else: final = parse_final(text)
                    status = "ok" if final else "timeout"
            except Exception as e:
                status = "error"; text = text or f"{type(e).__name__}: {e}"; log.warning("run failed: %s", e, extra=ev("finding", inv))
            summ = _clip((final or {}).get("summary") or "[no final answer] " + re.sub(r"\s+", " ", text), 1500 if question else 900)
            tid, svc = str((final or {}).get("cited_trace_id") or ""), str((final or {}).get("cited_service") or "")
            known = " ".join(seen + [evidence])
            if not re.fullmatch(r"[0-9a-f]{32}", tid) or tid not in known: tid = top_tid     # cite only ids that were really seen
            if not svc or svc not in known: svc = top_svc
            self.stats["reviews" if duty else "investigations"] += 1
            f = {"summary": summ, "trace": tid, "service": svc, "status": status, "tool_calls": calls, "tokens_in": tin, "tokens_out": tout, "ms": int((time.time() - t0) * 1000)}
            if not (question or duty or recovery): f.update(structured(final)); f["tools_used"] = list(dict.fromkeys(used)); f["trail"] = trail
            if duty:
                v = re.match(r"\s*VERDICT:\s*(ok|watch|act)\b", summ, re.I); verdict = v.group(1).lower() if v else "ok"
                f["summary"] = re.sub(r"^\s*VERDICT:\s*\w+\s*", "", summ); f["summary"] = _clip(f["summary"], NOTE_CHARS.get(duty, 400)); f["verdict"] = verdict
                self.b.publish("ai-review", f"TinyOlly AI SRE Agent {duty}: {verdict}", {**f, "duty": duty, "model": MODELS.model})
            elif not question:
                self.b.publish("ai-finding", f"TinyOlly AI SRE Agent: {trigger[:120]}", {**f, "trigger": trigger[:200], "model": MODELS.model})
            kind = "answer" if question else "note" if duty else "recovery" if recovery else "finding"
            log.info("%s (%s, %d tool calls): service=%s trace=%s | %s", kind, status, calls, svc or "-", tid or "-", f["summary"],
                     extra=ev(kind, inv, f"{f['summary']}\n\nservice: {svc or '-'}\ntrace: {tid or '-'}\n{status}, {calls} tool calls, {f['ms']} ms",
                              {"summary": f["summary"], "duty": duty, "verdict": f.get("verdict", "")}))
            if not question: self.history.append({"t": time.time(), "kind": duty or "finding", "trigger": trigger[:120], "status": status, "verdict": f.get("verdict", ""), "summary": f["summary"][:200]})
            return f
        finally: self.busy.release()

    # ---- incidents ----
    def _edges(self):
        try: return self.b.topology()
        except Exception: return set()

    def _find_incident(self, entity, now):
        """The open incident on this entity, else a young one holding a direct caller or callee of it."""
        live = [i for i in self.incidents if i["open"]]
        hit = next((i for i in live if entity in i["entities"]), None)
        if hit: return hit
        edges = self._edges()
        return next((i for i in live if now - i["t0"] <= GROUP_S and any((entity, o) in edges or (o, entity) in edges for o in i["entities"])), None)

    def _deepest(self, inc):
        """The entity that calls no other entity of the incident: where to start looking."""
        edges, names = self._edges(), inc["order"]
        return next((n for n in names if not any((n, o) in edges for o in names if o != n)), names[0])

    def add_signal(self, s: Signal, now=None):
        now = now or time.time()
        inc = self._find_incident(s.entity, now)
        if inc:
            inc["last"], inc["quiet"] = now, 0
            new_entity = s.entity not in inc["entities"]
            if new_entity: inc["entities"].add(s.entity); inc["order"].append(s.entity)
            if new_entity or (s.entity, s.kind) not in inc["kinds"]:     # a new symptom
                had = {k for _, k in inc["kinds"]}                          # errors joining an incident that had none: maybe a new cause
                escalated = s.kind in ERROR_KINDS and not (had & ERROR_KINDS)   # (a traffic drop joining an error incident is a consequence)
                inc["kinds"].add((s.entity, s.kind)); inc["texts"].append(s.text)
                self._update(inc["n"], symptoms=list(inc["texts"]), blast_radius=self._blast(inc))
                log.info("incident %d also: %s", inc["n"], s.text, extra=ev("incident", inc["n"])); self._tl(inc["n"], "signal", s.text, now)
                if escalated and inc["investigated"] and inc.get("re", 0) < REINVESTIGATE and not inc.get("running"):
                    inc["re"] = inc.get("re", 0) + 1; inc["investigated"] = False; inc["t_inv"] = now
                    self._tl(inc["n"], "investigation", f"New kind of symptom ({s.kind}): investigating again", now)
                    self._update(inc["n"], reinvestigated_at=now)
                    log.info("incident %d: new kind of symptom (%s), investigating again", inc["n"], s.kind, extra=ev("incident", inc["n"]))
            return
        self.stats["signals"] += 1
        if now - self.started < WARMUP_S: log.info("warming up, signal ignored: %s", s.text, extra=ev("detector")); return
        self.inc_n += 1
        inc = {"n": self.inc_n, "open": True, "entities": {s.entity}, "order": [s.entity], "kinds": {(s.entity, s.kind)}, "texts": [s.text], "t0": now, "last": now, "quiet": 0, "investigated": False, "svc": ""}
        self.incidents.append(inc)
        with self.ilock:
            self.investigations[inc["n"]] = {"id": inc["n"], "incident": inc["n"], "state": "open", "opened_at": now, "concluded_at": None, "resolved_at": None,
                "title": s.text, "service": s.entity, "symptoms": [s.text], "summary": "", "root_cause": "", "confidence": "", "evidence": [], "blast_radius": [s.entity],
                "suggested_fixes": [], "recovered": None, "recovery_note": "", "ttd_s": None, "ttr_s": None, "reinvestigated_at": None,
                "verdict": "", "would_page": None, "theories": [], "trail": [], "postmortem": "",
                "timeline": [{"t": now, "kind": "detected", "text": f"Detected: {s.text}"}], "model": MODELS.model, "status": "", "tool_calls": 0, "tokens_in": 0, "tokens_out": 0, "ms": 0}
            while len(self.investigations) > 100: self.investigations.pop(next(iter(self.investigations)))
        log.info("incident %d opened: %s", inc["n"], s.text, extra=ev("incident", inc["n"]))
        self._update(inc["n"])

    def _blast(self, inc):
        """Entities with signals, plus their direct callers."""
        edges = self._edges()
        return list(dict.fromkeys(inc["order"] + sorted(str(a) for a, b in edges if b in inc["entities"])))

    def _update(self, n, **changes):
        """Change one investigation record and push its new snapshot to the stream."""
        with self.ilock:
            r = self.investigations.get(n)
            if not r: return
            r.update(changes); snap = copy.deepcopy(r)
        log.info("investigation %d: %s", n, snap["state"], extra=ev("investigation", n, data=snap))

    def _tl(self, n, kind, text, t=None):
        """Append one event to an investigation's timeline (kept sorted by time; the console draws it)."""
        with self.ilock:
            r = self.investigations.get(n)
            if not r: return
            r.setdefault("timeline", []).append({"t": t or time.time(), "kind": kind, "text": _clip(text, 200)})
            r["timeline"].sort(key=lambda e: e["t"])

    def records(self):
        with self.ilock: return copy.deepcopy(list(reversed(self.investigations.values())))

    def tick(self, signals: list[Signal], now=None):
        now = now or time.time()
        live = {s.entity for s in signals}
        for s in signals: self.add_signal(s, now)
        for inc in self.incidents:
            if not inc["open"]: continue
            if not inc["investigated"] and now - inc.get("t_inv", inc["t0"]) >= SETTLE_S:
                inc["investigated"] = True; trig = f"incident {inc['n']}: " + "; ".join(inc["texts"])
                threading.Thread(target=self._investigate, args=(inc, trig), daemon=True).start()
            elif inc["investigated"]:
                inc["quiet"] = 0 if inc["entities"] & live else inc["quiet"] + 1
                if inc["quiet"] >= CLEAR_POLLS:
                    inc["open"] = False; log.info("incident %d resolved", inc["n"], extra=ev("incident", inc["n"]))
                    self._tl(inc["n"], "resolved", "Signals cleared", now)
                    self._update(inc["n"], state="recovering", resolved_at=now, ttr_s=int(now - inc["t0"]))
                    threading.Thread(target=self._recover, args=(inc,), daemon=True).start()

    def _investigate(self, inc, trig):
        n = inc["n"]; inc["running"] = True
        try: self._investigate_once(inc, trig)
        finally: inc["running"] = False

    def _investigate_once(self, inc, trig):
        n = inc["n"]
        self._update(n, state="investigating", blast_radius=self._blast(inc)); self._tl(n, "investigation", f"Investigation started from {self._deepest(inc)}")
        f = self.run(trig, self._deepest(inc), inv=n)
        with self.ilock: state = (self.investigations.get(n) or {}).get("state")
        done = "concluded" if state == "investigating" else state        # it may already be recovering
        if not f: self._update(n, state=done, status="skipped", summary="Not investigated: model busy or hourly cap reached."); return
        inc["svc"] = f["service"]
        proof = ([{"kind": "trace", "value": f["trace"]}] if f.get("trace") else []) + [{"kind": "tool", "value": t} for t in f.get("tools_used", [])]
        with self.ilock: opened = (self.investigations.get(n) or {}).get("opened_at") or time.time()
        try:                                                        # change markers that concern this incident: the usual "what changed?"
            norm = lambda x: re.sub(r"[^a-z0-9]", "", str(x).lower())
            names = {norm(x) for x in inc["entities"]} | {norm(x) for x in self._blast(inc)}
            recent = [e for e in self.b.changes(30) if opened - 900 <= float(e.get("timestamp") or 0) <= time.time()]
            hits = [e for e in recent if any(nm and nm in norm(f"{e.get('title')} {e.get('attributes') or ''}") for nm in names)]
            if not hits:                                            # nothing names a service here: the nearest change just before, if any
                near = [e for e in recent if opened - 300 <= float(e["timestamp"]) <= opened]
                hits = [max(near, key=lambda e: float(e["timestamp"]))] if near else []
            have = {x["text"] for x in (self.investigations.get(n) or {}).get("timeline", [])}
            for e in hits:
                if f"Change: {e.get('title')}" not in have: self._tl(n, "change", f"Change: {e.get('title')}", float(e["timestamp"]))
        except Exception as ex: log.warning("timeline changes: %s", ex)
        self._tl(n, "concluded", f"Concluded ({f.get('confidence', '?')} confidence, {f.get('verdict', '?').replace('_', ' ')}): {_clip(f.get('root_cause') or f['summary'], 160)}")
        if f.get("suggested_fixes"): self._tl(n, "fix", f"Fix proposed: {f['suggested_fixes'][0]['action']}")
        self._update(n, state=done, concluded_at=time.time(), service=f["service"] or self._deepest(inc), evidence=proof,
                     **{k: f[k] for k in ("summary", "root_cause", "confidence", "suggested_fixes", "status", "tool_calls", "tokens_in", "tokens_out", "ms",
                                          "verdict", "would_page", "theories", "trail") if k in f})
        if RUNBOOK: self.run(trig, duty="runbook", ctx=f"{trig} | finding: {f['summary']}", wait=120, inv=n)

    def postmortem(self, n, wait=120):
        """Markdown postmortem draft for investigation n: facts, timeline, theories and evidence from the record; summary, impact,
        5 whys and prevention written by the model (left out if the model is busy or fails). Cached on the record."""
        with self.ilock: r = copy.deepcopy(self.investigations.get(n))
        if not r: return None
        if r.get("postmortem"): return r["postmortem"]
        hhmm = lambda t: time.strftime("%H:%M:%S", time.gmtime(t)) + "Z"
        facts = {k: r.get(k) for k in ("title", "service", "symptoms", "summary", "root_cause", "confidence", "verdict", "blast_radius", "recovered", "ttr_s", "theories")}
        facts["timeline"] = [f"{hhmm(e['t'])} {e['text']}" for e in r.get("timeline", [])]
        facts["fixes"] = [x.get("action") for x in r.get("suggested_fixes", [])]
        nar = {}
        if self.busy.acquire(timeout=wait):
            try:
                m, _, _ = chat([{"role": "system", "content": PM_SYS}, {"role": "user", "content": "FACTS:\n" + json.dumps(facts)[:7000]}], None, 120)
                nar = parse_sections(m.get("content") or "")
            except Exception as e: log.warning("postmortem %d: model part skipped: %s", n, e)
            finally: self.busy.release()
        lst = lambda k: [str(x) for x in (nar.get(k) or []) if str(x).strip()][:5]
        pm = r.get("ttr_s"); links = self.b.links()
        out = [f"# Postmortem: {r['title']}", "",
               f"Incident #{n} · cause service **{r.get('service') or '-'}** · {time.strftime('%Y-%m-%d', time.gmtime(r['opened_at']))} · "
               f"triage: {(r.get('verdict') or '-').replace('_', ' ')}{' (would page)' if r.get('would_page') else ''} · model {r.get('model')}", "",
               "_Draft written by the TinyOlly AI SRE Agent from its own records. Review before sharing._", "",
               "## Summary", "", str(nar.get("summary") or r.get("summary") or "-"), "",
               "## Impact", "", str(nar.get("impact") or f"Services affected: {', '.join(r.get('blast_radius') or []) or '-'}."),
               "", f"Blast radius: {', '.join(r.get('blast_radius') or []) or '-'}. Time from detection to recovery: {f'{pm // 60} min {pm % 60} s' if pm is not None else 'not recovered yet'}.", "",
               "## Timeline (UTC)", "", "| Time | Event |", "|---|---|"]
        out += [f"| {hhmm(e['t'])} | {e['text'].replace('|', '/')} |" for e in r.get("timeline", [])]
        out += ["", "## Root cause", "", f"{r.get('root_cause') or '-'} (confidence: {r.get('confidence') or '-'})", ""]
        if r.get("theories"):
            out += ["## Theories considered", ""] + [f"- **{t['status'].replace('_', ' ')}**: {t['claim']} ({t['evidence']})" for t in r["theories"]] + [""]
        if lst("five_whys"): out += ["## Five whys", ""] + [f"{i}. {w}" for i, w in enumerate(lst("five_whys"), 1)] + [""]
        ev_ = [f"- trace [{e['value'][:8]}]({links['trace'].replace('{id}', e['value'])})" if e.get("kind") == "trace" and links.get("trace") else None for e in r.get("evidence", [])]
        ev_ = [x for x in ev_ if x] + [f"- `{x['tool']}({', '.join(f'{k}={v}' for k, v in x['args'].items())})`: {x['result'][:160]}" for x in r.get("trail", [])]
        if ev_: out += ["## Evidence", ""] + ev_ + [""]
        if lst("went_well"): out += ["## What went well", ""] + [f"- {x}" for x in lst("went_well")] + [""]
        acts = lst("prevention") + [f"{x['action']} (proposed fix{', target ' + x['target'] if x.get('target') else ''})" for x in r.get("suggested_fixes", [])]
        if acts: out += ["## Action items", ""] + [f"- [ ] {x}" for x in acts] + [""]
        md = "\n".join(out)
        self._update(n, postmortem=md); self._tl(n, "postmortem", "Postmortem draft written")
        return md

    def _recover(self, inc):
        n = inc["n"]
        f = self.run(f"incident {n} resolved: {'; '.join(inc['texts'])}", inc["svc"] or self._deepest(inc), True, inv=n)
        note = (f or {}).get("summary", "")
        m = re.search(r"Recovered:\s*(yes|no)", note, re.I)
        self._tl(n, "recovery", f"Recovery check: {m.group(1).lower() if m else 'unknown'}")
        self._update(n, state="resolved", recovered=m.group(1).lower() if m else "unknown", recovery_note=note)

    def loop(self):
        while True:
            try: self.stats["checks"] += 1; self.tick(self.b.detect())
            except Exception as e: log.warning("detect failed: %s: %s", type(e).__name__, e)
            rec = getattr(self.b, "rec", None)
            if rec:
                cur = (self.shift.status()["current"] or {}) if self.shift else {}
                try: rec.flush({"scenario": cur.get("id"), "flags": cur.get("flags"), "expected": cur.get("expected"), "profile": self.shift.profile if self.shift else ""})
                except OSError as e: log.warning("record failed: %s", e)
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
        return {"busy": self.busy.locked(), "uptime_s": int(time.time() - self.started), "model": MODELS.model, "preset": MODELS.name, "backend": self.b.name, "open_incidents": sum(i["open"] for i in self.incidents),
                "investigations_last_hour": len(self.starts), "max_per_hour": MAX_PER_HOUR, "reviews_last_hour": len(self.rstarts), **self.stats,
                **({"demo": self.shift.status(presenter=False)} if self.shift else {})}


def make_handler(agent: Agent):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, code, body, ctype="application/json"):
            b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def _stream(self, after):
            """Server-sent events: one `data:` JSON per feed line, `id:` for resume, a comment every 15 s as heartbeat."""
            last = self.headers.get("Last-Event-ID", "")
            if last.isdigit(): after = int(last)
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
            try:
                while True:
                    events = FEED.after(after, wait=15)
                    if events: after = events[-1]["n"]
                    self.wfile.write(("".join(f"id: {e['n']}\ndata: {json.dumps(e)}\n\n" for e in events) or ": ping\n\n").encode()); self.wfile.flush()
            except OSError: pass                                      # client went away
        def do_GET(self):
            if self.path == "/healthz": return self._send(200, {"ok": True})
            path, _, query = self.path.partition("?")
            m = re.search(r"after=(\d+)", query)
            after = int(m.group(1)) if m else 0
            if path == "/api/models": return self._send(200, MODELS.listing())
            if path == "/api/config": return self._send(200, {"env": ENV_NAME, "links": agent.b.links()})
            if path in PAGES:
                name, ctype = PAGES[path]
                with open(os.path.join(STATIC, name), "rb") as fh: return self._send(200, fh.read(), ctype + "; charset=utf-8")
            if path == "/events": return self._send(200, {"events": FEED.after(after), "status": agent.status()})
            if path == "/stream": return self._stream(after)
            if path in ("/demo/grades", "/demo/report"):
                if not agent.shift: return self._send(404, {"error": "demo not configured"})
                recs, hist = agent.records(), agent.shift.status()["history"]
                if path == "/demo/grades": return self._send(200, grade.grade_all(recs, hist))
                return self._send(200, grade.report(recs, hist, MODELS.model), "text/markdown; charset=utf-8")
            if path == "/demo/status": return self._send(200, agent.shift.status()) if agent.shift else self._send(404, {"error": "demo not configured"})
            if path == "/api/investigations": return self._send(200, {"investigations": agent.records(), "status": agent.status()})
            pmg = re.fullmatch(r"/api/investigations/(\d+)/postmortem", path)
            if pmg:
                r = next((r for r in agent.records() if r["id"] == int(pmg.group(1))), None)
                return self._send(200, r["postmortem"], "text/markdown; charset=utf-8") if r and r.get("postmortem") else self._send(404, {"error": "no postmortem yet"})
            one = re.fullmatch(r"/api/investigations/(\d+)", path)
            if one:
                r = next((r for r in agent.records() if r["id"] == int(one.group(1))), None)
                return self._send(200, r) if r else self._send(404, {"error": "not found"})
            self._send(404, {"error": "not found"})
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError: body = {}
            if self.path == "/investigate":
                a = str(body.get("alert") or "manual trigger")[:200]
                threading.Thread(target=agent.run, args=(a,), daemon=True).start(); return self._send(202, {"started": a})
            pm = re.fullmatch(r"/api/investigations/(\d+)/postmortem", self.path)
            if pm:
                md = agent.postmortem(int(pm.group(1)))
                return self._send(200, {"markdown": md}) if md else self._send(404, {"error": "not found"})
            if self.path == "/ask":
                q = str(body.get("question") or "").strip()[:400]
                if not q: return self._send(400, {"error": "question required"})
                log.info("%s", q, extra=ev("question"))
                f = agent.run("ask", question=q)
                return self._send(200, {"answer": f["summary"]} if f else {"answer": "Skipped: the model is busy or the hourly cap is reached.", "skipped": True})
            if self.path == "/api/models":
                try: MODELS.use(str(body.get("name") or ""))
                except KeyError: return self._send(400, {"error": "unknown or unconfigured preset", **MODELS.listing()})
                log.info("model switched to %s (%s)", MODELS.name, MODELS.model); return self._send(200, MODELS.listing())
            if self.path.startswith("/demo/"):
                sh, op = agent.shift, self.path[6:]
                if not sh: return self._send(404, {"error": "demo not configured (set DEMO_FLAGS / mount the flag file)"})
                if op in ("start", "stop", "pause"): return self._send(200, getattr(sh, op)())
                if op == "reset": sh.reset("presenter reset"); return self._send(200, sh.status())
                if op == "trigger":
                    try: return self._send(200, sh.trigger(str(body.get("id") or "")))
                    except KeyError: return self._send(400, {"error": "unknown scenario", "scenarios": sorted(sh.by_id)})
            self._send(404, {"error": "not found"})
    return H


def main():
    name = E("SRE_BACKEND", "tinyolly")
    agent = Agent(BACKENDS[name]())
    log.info("tinyolly-sre up: backend=%s preset=%s model=%s detect=%ss", name, MODELS.name, MODELS.model, DETECT_S)
    threading.Thread(target=MODELS.check, daemon=True).start()
    flags = demo.flag_backend()
    if flags:
        agent.shift = demo.Shift(flags, demo.load_scenarios(), announce=agent.b.mark_change)
        def write_report():
            path = E("DEMO_REPORT_FILE", "/tmp/shift-report.md")
            try:
                with open(path, "w") as fh: fh.write(grade.report(agent.records(), agent.shift.history, MODELS.model))
                log.info("demo: shift report written to %s (GET /demo/report)", path)
            except OSError as e: log.warning("demo: report not written: %s", e)
        agent.shift.on_end = write_report
        if hasattr(agent.b, "fence"): agent.shift.on_fault_end = agent.b.fence
        def bye(*_):
            agent.shift.stop()                                         # never leave the shop broken
            if _: sys.exit(0)
        atexit.register(bye); signal.signal(signal.SIGTERM, bye)
        log.info("demo driver ready: flags=%s, %d scenarios", flags.name, len(agent.shift.by_id))
        if E("DEMO", "0") == "1": agent.shift.start()
    if DETECT_S > 0:
        for fn in (agent.loop, agent.reviews, agent.changes, agent.digest): threading.Thread(target=fn, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), make_handler(agent)).serve_forever()
