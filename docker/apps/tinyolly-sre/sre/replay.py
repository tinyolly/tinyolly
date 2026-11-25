"""Replay a recorded shift (SRE_RECORD=<file.jsonl>) through the real detectors and incident logic in seconds.

  python -m sre.replay shift.jsonl                         detection only: incidents, TTD, missed faults, false positives
  python -m sre.replay shift.jsonl --set DETECT_ERROR_PCT_MIN=3 --set DETECT_RECENT_SECONDS=60
  python -m sre.replay shift.jsonl --model                 also run each investigation prompt on the recorded evidence (no tools)

Settings are environment variables read at import, so --set applies them before the agent modules load.
The clock is the recorded poll time; investigations run synchronously, so a replay is deterministic."""
from __future__ import annotations
import argparse, collections, gzip, json, os, threading, types


class ReplayTools:
    """The TinyOlly MCP tools the model uses most, answered from the recorded spans/logs/events at the replay clock."""
    S = {"type": "object", "properties": {}}
    def __init__(self, b, clock, T): self.b, self.clock, self.T = b, clock, T
    def tools(self):
        p = lambda **k: {"type": "object", "properties": {n: {"type": t} for n, t in k.items()}}
        return [{"name": "what_changed", "description": "Change markers (deploys, flag flips) in the last N minutes.", "inputSchema": p(minutes="number")},
                {"name": "list_services", "description": "Services with rate, error rate and p95.", "inputSchema": self.S},
                {"name": "search_spans", "description": "Recent spans of a service; errors_only to keep failures.", "inputSchema": p(service="string", errors_only="boolean", minutes="number")},
                {"name": "query_logs", "description": "Recent logs, by service and severity.", "inputSchema": p(service="string", severity="string", minutes="number")},
                {"name": "get_trace", "description": "All spans of one trace.", "inputSchema": p(trace_id="string")},
                {"name": "get_edge", "description": "Calls from source to target: count, errors, p95.", "inputSchema": p(source="string", target="string", minutes="number")},
                {"name": "compare_windows", "description": "Per-service calls and errors: last N minutes vs the N before.", "inputSchema": p(minutes="number", service="string")}]
    def _rows(self, kind, minutes):
        key = "start_time" if kind == "spans" else "timestamp"; cut = self.clock.now - float(minutes or 10) * 60
        return [x for x in self.b.pool[kind].values() if cut <= self.T._secs(x.get(key)) <= self.clock.now]
    def _slim(self, s): return {k: s.get(k) for k in ("trace_id", "span_id", "service_name", "name", "duration_ms", "status", "start_time")}
    def call(self, name, args):
        err = self.T._is_error
        if name == "what_changed": return json.dumps(self.b.changes(float(args.get("minutes") or 30)))[:4000]
        if name == "list_services": return json.dumps(self.b._safe("/api/service-catalog", []))[:4000]
        if name == "search_spans":
            rows = [s for s in self._rows("spans", args.get("minutes")) if (not args.get("service") or s.get("service_name") == args["service"]) and (not args.get("errors_only") or err(s))]
            return json.dumps([self._slim(s) for s in rows[-30:]])
        if name == "query_logs":
            sev = (args.get("severity") or "").lower()
            rows = [l for l in self._rows("logs", args.get("minutes")) if (not args.get("service") or l.get("service_name") == args["service"]) and (not sev or (l.get("severity") or "").lower() == sev)]
            return json.dumps([{k: l.get(k) for k in ("timestamp", "service_name", "severity", "message", "trace_id")} for l in rows[-30:]])
        if name == "get_trace":
            return json.dumps([self._slim(s) for s in self.b.pool["spans"].values() if s.get("trace_id") == args.get("trace_id")][:60])
        if name in ("get_edge", "compare_windows"):
            m = float(args.get("minutes") or 5); spans = self.b.pool["spans"]
            now = self._rows("spans", m); before = [s for s in self._rows("spans", 2 * m) if s not in now]
            def count(rows):
                c = collections.Counter(); e = collections.Counter()
                for s in rows: c[s.get("service_name")] += 1; e[s.get("service_name")] += err(s)
                return {k: {"calls": c[k], "errors": e[k]} for k in c}
            if name == "get_edge":
                tgt = [s for s in now if s.get("service_name") == args.get("target")]
                return json.dumps({"target": args.get("target"), "calls": len(tgt), "errors": sum(map(err, tgt)), "note": "replay: target-side spans only"})
            a, b_ = count(now), count(before)
            svc = args.get("service")
            return json.dumps({k: {"now": a.get(k), "before": b_.get(k)} for k in sorted(set(a) | set(b_)) if not svc or k == svc})[:4000]
        return f"ERROR: tool {name} is not available in replay"


def history_from(lines):
    """Contiguous runs of the recorded scenario label -> the shift history the grader expects."""
    hist, cur = [], None
    for ln in lines:
        sid = ln.get("scenario")
        if cur and cur["id"] != sid: cur["ended"] = ln["t"]; cur = None
        if sid and not cur:
            cur = {"id": sid, "title": sid, "flags": ln.get("flags") or {}, "expected": ln.get("expected") or {}, "started": ln["t"], "ended": None, "announced": True}
            hist.append(cur)
    if cur: cur["ended"] = lines[-1]["t"]
    return hist


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record"); ap.add_argument("--model", action="store_true"); ap.add_argument("--set", action="append", default=[], metavar="K=V")
    ap.add_argument("--timeline", action="store_true", help="print every change in the set of active signals")
    a = ap.parse_args(argv)
    os.environ.setdefault("MAX_INVESTIGATIONS_PER_HOUR", "999"); os.environ.setdefault("RUNBOOK", "0")
    for kv in a.set: k, _, v = kv.partition("="); os.environ[k] = v
    from . import core, grade
    from .backends import tinyolly as T

    with (gzip.open(a.record, "rt") if a.record.endswith(".gz") else open(a.record)) as fh: lines = [json.loads(l) for l in fh if l.strip()]
    if not lines: raise SystemExit("empty record")
    clock = types.SimpleNamespace(now=lines[0]["t"]); clock.time = lambda: clock.now
    import time as _time                                                   # the detectors' windows use the recorded clock
    T.time = types.SimpleNamespace(**{k: getattr(_time, k) for k in dir(_time) if not k.startswith("_")}); T.time.time = clock.time

    class Sync:                                                            # investigations run inline: deterministic
        def __init__(self, target, args=(), daemon=None): self.f, self.a = target, args
        def start(self): self.f(*self.a)
    core.threading = types.SimpleNamespace(Thread=Sync, Lock=threading.Lock, Condition=threading.Condition)

    class Replay(T.TinyOllyBackend):
        def __init__(self):
            super().__init__(); self.rec = None; self.state, self.pool = {}, {"spans": {}, "logs": {}}
            self.mcp_url = ""                                              # tools would read live data; replay uses recorded evidence only
        def load(self, ln):
            for k, v in ln["r"].items():
                if isinstance(v, dict) and "delta" in v:
                    kind = "spans" if k.startswith("/api/spans") else "logs"; pool = self.pool[kind]
                    for x in v["delta"]: pool[x.get("span_id") if kind == "spans" else x.get("log_id") or f"{x.get('timestamp')}{x.get('service_name')}{x.get('message')}"] = x
                    if len(pool) > 20000:
                        for i in sorted(pool, key=lambda i: T._secs(pool[i].get("start_time") or pool[i].get("timestamp")))[:len(pool) - 20000]: del pool[i]
                    self.state[k] = kind
                else: self.state[k] = v
        def _get(self, path, **params):
            kind = self.state.get(T._key(path, params)) or ("spans" if path == "/api/spans" else "logs" if path == "/api/logs" else None)
            if kind in ("spans", "logs") and kind in self.pool:
                tkey = "start_time" if kind == "spans" else "timestamp"
                rows = sorted(self.pool[kind].values(), key=lambda x: T._secs(x.get(tkey)), reverse=True)
                return [x for x in rows if T._secs(x.get(tkey)) <= clock.now][: int(params.get("limit") or 1000)]
            if T._key(path, params) in self.state: return self.state[T._key(path, params)]
            raise KeyError(path)
        def publish(self, *a_, **k): pass
        def changes(self, minutes=15):
            return [e for e in self._safe("/api/events", [], minutes=15, limit=20) if not str(e.get("kind", "")).startswith("ai-")]
        def topology(self):
            m = self._safe("/api/service-map", {}, limit=1000)
            return {(e.get("source"), e.get("target")) for e in m.get("edges") or [] if not T._ignored(str(e.get("source")))}

    b = Replay(); agent = core.Agent(b); agent.started = lines[0]["t"]
    if a.model: b.local_tools = ReplayTools(b, clock, T)
    if not a.model:
        agent.run = lambda trigger, entity="", recovery=False, **k: {"service": entity, "summary": "(replay: detection only, no model)", "trace": "", "status": "ok",
                                                                   "tool_calls": 0, "tokens_in": 0, "tokens_out": 0, "ms": 0}
    last, prev = None, None
    for ln in lines:
        clock.now = ln["t"]; b.load(ln)
        if prev and prev.get("flags") and prev.get("scenario") != ln.get("scenario") and ln.get("profile") == "quick":
            b.fence(ln["t"])                                                 # the live quick profile cut off detection here too
        prev = ln
        sig = b.detect(); agent.tick(sig, now=ln["t"])
        if a.timeline:
            now_set = sorted(f"{s.kind}:{s.entity}" for s in sig)
            if now_set != last: print(f"+{int(ln['t'] - lines[0]['t']):5d}s [{ln.get('scenario') or '-'}] {', '.join(now_set) or '(no signals)'}"); last = now_set
    hist = history_from(lines)
    recs = agent.records()
    if not a.model:
        for r in recs: r["detection_only"] = True
    print(grade.report(recs, hist, core.MODELS.model if a.model else "replay, detection only"))


if __name__ == "__main__":
    main()
