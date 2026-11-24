"""TinyOlly backend: reads TinyOlly's REST API, tools come from TinyOlly's MCP server,
findings are written back as change-marker events (kind=ai-finding / ai-review) via POST /api/events."""
from __future__ import annotations
import os, time, collections
import httpx
from ..backend import Backend, Signal

E = os.getenv
URL = E("TINYOLLY_URL", "http://tinyolly-ui:5002").rstrip("/")
ERRORS_MIN = int(E("DETECT_ERRORS_MIN", "10"))            # error spans of one service in the window
WINDOW_S = int(E("DETECT_WINDOW_SECONDS", "120"))
IGNORE = {s for s in E("DETECT_IGNORE", "load-generator").split(",") if s}
LOG_ERRORS_MIN = int(E("DETECT_LOG_ERRORS_MIN", "10"))    # error logs of one service in the window
ERR_PCT_MIN = float(E("DETECT_ERROR_PCT_MIN", "5"))       # service error rate (%) that counts, if also 3x its learned normal
LATENCY_FACTOR = float(E("DETECT_LATENCY_FACTOR", "3"))   # p95 this many times its learned normal (and +100 ms)
TRAFFIC_DROP = float(E("DETECT_TRAFFIC_DROP", "0.2"))     # rate below this fraction of normal (normal >= 0.5/s)
BASELINE_POLLS = int(E("BASELINE_POLLS", "6"))            # polls before a service's learned normal is trusted
CONFIRM_POLLS = int(E("DETECT_CONFIRM_POLLS", "2"))       # consecutive polls a shift must hold before it is a signal
VANISHED_POLLS = int(E("DETECT_VANISHED_POLLS", "3"))
DB_PCT = float(E("DETECT_DB_PCT", "90"))
DETECTORS = set(E("DETECTORS", "errors,error-rate,latency,traffic,vanished,logs,mesh,platform").split(","))


def _is_error(sp: dict) -> bool:
    if (sp.get("status") or {}).get("code") in (2, "STATUS_CODE_ERROR", "ERROR"):
        return True
    for a in sp.get("attributes") or []:
        if a.get("key") in ("http.status_code", "http.response.status_code"):
            v = a.get("value", {})
            try:
                return int(v.get("intValue") or v.get("stringValue") or 0) >= 500
            except (TypeError, ValueError):
                return False
    return False


def _secs(ts) -> float:
    """Epoch seconds from s / ms / us / ns."""
    ts = float(ts or 0)
    for div in (1e9, 1e6, 1e3):
        if ts > div * 1e8: return ts / div
    return ts


class Learned:
    """Per-service learned normal (EMA of rate, p95, error rate) with confirmation counters."""
    def __init__(self): self.n = 0; self.rate = self.p95 = self.err = 0.0; self.hits = collections.Counter(); self.missing = 0
    def update(self, c, hold: bool):
        a = 0.2 if self.n < BASELINE_POLLS else 0.05
        if hold and self.n >= BASELINE_POLLS: return          # do not learn a problem as normal
        for k, v in (("rate", c.get("rate")), ("p95", c.get("duration_p95")), ("err", c.get("error_rate"))):
            v = float(v or 0); setattr(self, k, v if self.n == 0 else getattr(self, k) * (1 - a) + v * a)
        self.n += 1


class TinyOllyBackend(Backend):
    name = "tinyolly"
    duties = ["shift-note", "instrumentation-gaps", "platform-health", "mesh-posture"]

    def __init__(self):
        self.mcp_url = E("TINYOLLY_MCP_URL", "http://tinyolly-mcp:8765/mcp")
        self.c = httpx.Client(base_url=URL, timeout=20)
        self.learned: dict[str, Learned] = collections.defaultdict(Learned)
        self.mesh0: dict | None = None; self.dropped0: int | None = None

    def _get(self, path, **params):
        r = self.c.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()

    def _safe(self, path, default, **params):
        try: return self._get(path, **params) or default
        except Exception: return default

    def _recent_errors(self, seconds: float) -> list[dict]:
        cut = time.time() - seconds
        return [s for s in self._safe("/api/spans", [], limit=5000) if _secs(s.get("startTimeUnixNano")) >= cut and _is_error(s)]

    # ---- detectors (no model) ----
    def detect(self) -> list[Signal]:
        out: list[Signal] = []
        D = DETECTORS
        if "errors" in D:
            by = collections.Counter(s.get("serviceName") or "unknown" for s in self._recent_errors(WINDOW_S))
            out += [Signal("errors", svc, f"{svc}: {n} failing spans in the last {max(WINDOW_S // 60, 1)} min") for svc, n in by.most_common() if n >= ERRORS_MIN and svc not in IGNORE]
        cat = {c["name"]: c for c in self._safe("/api/service-catalog", [])}
        if cat: out += self._catalog_signals(cat, D)
        if "logs" in D:
            cut = time.time() - WINDOW_S
            by = collections.Counter(l.get("service_name") or "unknown" for l in self._safe("/api/logs", [], limit=1000)
                                     if (l.get("severity") or "").lower() in ("error", "fatal", "critical") and _secs(l.get("timestamp")) >= cut)
            out += [Signal("logs", svc, f"{svc}: {n} error logs in the last {max(WINDOW_S // 60, 1)} min") for svc, n in by.most_common() if n >= LOG_ERRORS_MIN and svc not in IGNORE]
        if "mesh" in D: out += self._mesh_signals()
        if "platform" in D: out += self._platform_signals()
        return out

    def _catalog_signals(self, cat, D):
        out = []
        for name, c in cat.items():
            if name in IGNORE: continue
            L = self.learned[name]; L.missing = 0; ready = L.n >= BASELINE_POLLS
            checks = {
                "error-rate": ready and float(c.get("error_rate") or 0) >= ERR_PCT_MIN and float(c.get("error_rate") or 0) > 3 * max(L.err, 0.5),
                "latency": ready and float(c.get("duration_p95") or 0) > LATENCY_FACTOR * max(L.p95, 1) and float(c.get("duration_p95") or 0) - L.p95 > 100,
                "traffic": ready and L.rate >= 0.5 and float(c.get("rate") or 0) < TRAFFIC_DROP * L.rate,
            }
            texts = {"error-rate": f"{name}: error rate {c.get('error_rate')}% (normal {L.err:.1f}%)",
                     "latency": f"{name}: p95 {c.get('duration_p95')} ms (normal {L.p95:.0f} ms)",
                     "traffic": f"{name}: traffic {c.get('rate')}/s (normal {L.rate:.1f}/s)"}
            for k, hit in checks.items():
                L.hits[k] = L.hits[k] + 1 if hit and k in D else 0
                if L.hits[k] >= CONFIRM_POLLS: out.append(Signal(k, name, texts[k]))
            L.update(c, hold=any(L.hits[k] for k in checks))
        for name, L in self.learned.items():
            if name in cat or name in IGNORE or L.n < BASELINE_POLLS: continue
            L.missing += 1
            if "vanished" in D and L.missing >= VANISHED_POLLS and L.rate >= 0.1:
                out.append(Signal("vanished", name, f"{name}: no longer reporting (normal {L.rate:.1f} req/s)"))
        return out

    def _mesh_signals(self):
        m = self._safe("/api/mesh-posture", None)
        if not m: return []
        denied = {(d.get("source"), d.get("target")) for d in m.get("denied") or []}
        plain = {(d.get("source"), d.get("target")) for d in m.get("plaintext") or []}
        if self.mesh0 is None:
            self.mesh0 = {"denied": denied, "plain": plain}; return []
        out = [Signal("denied", t or "mesh", f"new denied calls {s} -> {t}") for s, t in denied - self.mesh0["denied"]]
        out += [Signal("plaintext", t or "mesh", f"new plaintext edge {s} -> {t}") for s, t in plain - self.mesh0["plain"]]
        return out

    def _platform_signals(self):
        st = self._safe("/admin/stats", None)
        if not st: return []
        out, db, card = [], st.get("db") or {}, st.get("cardinality") or {}
        if db.get("max_size_bytes") and db.get("size_bytes", 0) / db["max_size_bytes"] * 100 >= DB_PCT:
            out.append(Signal("platform", "tinyolly", f"TinyOlly store at {db['size_bytes'] * 100 // db['max_size_bytes']}% of its size cap"))
        d = card.get("dropped") or 0
        if self.dropped0 is None: self.dropped0 = d
        elif d > self.dropped0: out.append(Signal("platform", "tinyolly", f"{d - self.dropped0} metric series dropped (cardinality {card.get('current')}/{card.get('max')})")); self.dropped0 = d
        return out

    # ---- evidence ----
    def changes(self, minutes=15):
        return [e for e in self._safe("/api/events", [], minutes=minutes, limit=20) if not str(e.get("kind", "")).startswith("ai-")]

    def _change_lines(self, minutes=15, n=5):
        return [f"  {time.strftime('%H:%M:%S', time.gmtime(_secs(e.get('timestamp'))))}Z {e.get('title')} ({e.get('source')})" for e in self.changes(minutes)[:n]]

    def evidence(self, trigger, entity="", recovery=False):
        win = 60 if recovery else 600
        parts, top_svc, top_tid = [], entity, ""
        groups = collections.defaultdict(lambda: [0, ""])
        for s in self._recent_errors(win):
            key = (s.get("serviceName") or "?", (s.get("name") or "?")[:80], ((s.get("status") or {}).get("message") or "")[:100])
            groups[key][0] += 1; groups[key][1] = groups[key][1] or s.get("traceId", "")
        ranked = sorted(groups.items(), key=lambda kv: (kv[0][0] != entity, -kv[1][0]))[:5]
        parts.append(f"ERROR SPANS (last {win // 60} min; service | span | status message | count | example trace_id):")
        parts += [f"  {k[0]} | {k[1]} | {k[2] or '-'} | {n} | {tid}" for k, (n, tid) in ranked] or ["  none"]
        if ranked: top_svc, top_tid = ranked[0][0][0], ranked[0][1][1]
        cat = {c["name"]: c for c in self._safe("/api/service-catalog", [])}
        for svc in dict.fromkeys([top_svc, entity]):
            c = cat.get(svc); L = self.learned.get(svc)
            if c: parts.append(f"SERVICE {svc}: rate {c.get('rate')}/s, error rate {c.get('error_rate')}%, p95 {c.get('duration_p95')} ms" +
                               (f" | learned normal: rate {L.rate:.1f}/s, error {L.err:.1f}%, p95 {L.p95:.0f} ms" if L and L.n >= BASELINE_POLLS else ""))
        if not recovery:
            logs = [l for l in self._safe("/api/logs", [], limit=500) if (l.get("severity") or "").lower() in ("error", "fatal", "critical") and (not top_svc or l.get("service_name") == top_svc)][:4]
            parts += ["ERROR LOGS (newest first):"] + [f"  {l.get('service_name')}: {(l.get('message') or '')[:160]} trace_id={l.get('trace_id') or '-'}" for l in logs]
            ch = self._change_lines()
            parts.append("CHANGE MARKERS (15 min):" + ("" if ch else " none")); parts += ch
        return "\n".join(parts), top_svc, top_tid

    def review_evidence(self, duty, ctx=""):
        cat = self._safe("/api/service-catalog", [])
        if duty in ("shift-note", "change-risk", "post-change"):
            rows = sorted(cat, key=lambda c: -(float(c.get("error_rate") or 0)))[:12]
            err = collections.Counter(s.get("serviceName") or "?" for s in self._recent_errors(900))
            parts = ["SERVICES (name | rate/s | error % | p95 ms | learned normal rate/err/p95):"]
            for c in rows:
                L = self.learned.get(c["name"]); n = f"{L.rate:.1f}/{L.err:.1f}/{L.p95:.0f}" if L and L.n >= BASELINE_POLLS else "-"
                parts.append(f"  {c['name']} | {c.get('rate')} | {c.get('error_rate')} | {c.get('duration_p95')} | {n}")
            parts.append("ERROR SPANS BY SERVICE (15 min): " + (", ".join(f"{k}={v}" for k, v in err.most_common(8)) or "none"))
            if duty != "shift-note":                      # who depends on whom, so the note can name blast radius
                edges = (self._safe("/api/service-map", {}, limit=1000) or {}).get("edges") or []
                parts.append("DEPENDENCIES (caller -> callee, calls, errors): " + "; ".join(f"{e.get('source')}->{e.get('target')} {e.get('value', e.get('call_count', '?'))}/{e.get('error_count', 0)}" for e in edges[:25]))
            ch = self._change_lines(30, 8); parts.append("CHANGE MARKERS (30 min):" + ("" if ch else " none")); parts += ch
            return "\n".join(parts)
        if duty == "instrumentation-gaps":
            logs = self._safe("/api/logs", [], limit=2000)
            have, notrace = collections.Counter(l.get("service_name") for l in logs), collections.Counter(l.get("service_name") for l in logs if not l.get("trace_id"))
            parts = ["SERVICE | has spans | log lines | logs without trace_id"]
            parts += [f"  {c['name']} | yes | {have.get(c['name'], 0)} | {notrace.get(c['name'], 0)}" for c in cat]
            parts += [f"  {s} | NO SPANS | {n} | {notrace.get(s, 0)}" for s, n in have.items() if s and s not in {c['name'] for c in cat}]
            return "\n".join(parts)
        if duty == "mesh-posture":
            m = self._safe("/api/mesh-posture", {})
            return "MESH POSTURE: " + (str(m)[:2500] if m else "no mesh telemetry (no Istio metrics seen); nothing to review")
        if duty == "platform-health":
            return "TINYOLLY STATS: " + str(self._safe("/admin/stats", {}))[:2000]
        return ""

    def publish(self, kind, title, attrs):
        try: self.c.post("/api/events", json={"title": title[:200], "source": "tinyolly-sre", "kind": kind, "attributes": {k: v for k, v in attrs.items() if k != "kind"}}).raise_for_status()
        except Exception: pass
