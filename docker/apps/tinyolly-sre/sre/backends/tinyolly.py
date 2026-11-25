"""TinyOlly backend: reads TinyOlly's REST API, tools come from TinyOlly's MCP server,
findings are written back as change-marker events (kind=ai-finding / ai-review) via POST /api/events."""
from __future__ import annotations
import os, time, collections, fnmatch, json
import httpx
from ..backend import Backend, Signal

E = os.getenv
URL = E("TINYOLLY_URL", "http://tinyolly-ui:5002").rstrip("/")
PUBLIC_URL = E("TINYOLLY_PUBLIC_URL", "http://localhost:5005").rstrip("/")   # the TinyOlly UI as the viewer's browser sees it
ERRORS_MIN = int(E("DETECT_ERRORS_MIN", "10"))            # error spans of one service in the window
WINDOW_S = int(E("DETECT_WINDOW_SECONDS", "120"))
IGNORE = [s for s in E("DETECT_IGNORE", "load-generator,tinyolly-*").split(",") if s]   # names or globs
RECENT_S = int(E("DETECT_RECENT_SECONDS", "120"))         # error rate is measured over spans this recent, not the catalog's long average
RECENT_ERRORS_MIN = int(E("DETECT_RECENT_ERRORS_MIN", "3"))  # fewer error spans than this in that window count as 0%
RECENT_MIN_SPANS = int(E("DETECT_RECENT_MIN_SPANS", "10"))   # below this many spans in the window, widen it to 3x (low-traffic services)
LOG_ERRORS_MIN = int(E("DETECT_LOG_ERRORS_MIN", "10"))    # error logs of one service in the window
ERR_PCT_MIN = float(E("DETECT_ERROR_PCT_MIN", "5"))       # service error rate (%) that counts, if also 3x its learned normal
LATENCY_FACTOR = float(E("DETECT_LATENCY_FACTOR", "3"))   # p95 this many times its learned normal (and +100 ms)
TRAFFIC_DROP = float(E("DETECT_TRAFFIC_DROP", "0.2"))     # rate below this fraction of normal (normal >= 0.5/s)
BASELINE_POLLS = int(E("BASELINE_POLLS", "6"))            # polls before a service's learned normal is trusted
CONFIRM_POLLS = int(E("DETECT_CONFIRM_POLLS", "2"))       # consecutive polls a shift must hold before it is a signal
VANISHED_POLLS = int(E("DETECT_VANISHED_POLLS", "3"))
HOLD_MAX_POLLS = int(E("DETECT_HOLD_MAX_POLLS", "20"))
RECENT_STATS = E("DETECT_RECENT_STATS", "0") == "1"           # rate and p95 from recent spans too (not the catalog's long average): faster detect and clear      # a traffic/latency shift held this long becomes the new normal (errors never do)
DB_PCT = float(E("DETECT_DB_PCT", "90"))
DETECTORS = set(E("DETECTORS", "errors,error-rate,op-errors,latency,traffic,vanished,logs,mesh,platform").split(","))
OP_MIN_SPANS = int(E("DETECT_OP_MIN_SPANS", "8"))         # op-errors: one operation (service + span name) failing often while the service as a whole looks fine


def _svc(sp: dict) -> str:
    return sp.get("service_name") or "unknown"


def _is_error(sp: dict) -> bool:
    if (sp.get("status") or {}).get("code") in (2, "STATUS_CODE_ERROR", "ERROR"):
        return True
    if str(sp.get("status_code") or "").isdigit() and int(sp["status_code"]) >= 500:
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


def _ignored(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in IGNORE)


class Learned:
    """Per-service learned normal (EMA of rate, p95, error rate) with confirmation counters."""
    def __init__(self): self.n = 0; self.rate = self.p95 = self.err = 0.0; self.hits = collections.Counter(); self.missing = 0; self.held = 0
    def update(self, c, hold: bool):
        a = 0.2 if self.n < BASELINE_POLLS else 0.05
        keys = ("rate", "p95", "err")
        if hold and self.n >= BASELINE_POLLS:                  # do not learn a problem as normal ...
            self.held += 1
            if self.held < HOLD_MAX_POLLS: return
            # ... unless a traffic/latency level has held for HOLD_MAX_POLLS: it is the new normal (a baseline learned
            # during a boot burst would otherwise keep an incident open forever). Error rate is never re-learned.
            keys = ("rate", "p95"); a = 0.5
        else: self.held = 0
        for k, v in (("rate", c.get("rate")), ("p95", c.get("duration_p95")), ("err", c.get("error_rate"))):
            if k not in keys: continue
            v = float(v or 0); w = 0.4 if k == "err" and v < self.err else a   # errors seen at startup must not stay "normal"
            setattr(self, k, v if self.n == 0 else getattr(self, k) * (1 - w) + v * w)
        self.n += 1


def _key(path, params):
    return path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)


class Recorder:
    """SRE_RECORD=<file.jsonl>: one line per detect poll with the API responses it used (spans and logs as deltas),
    for replaying detector and prompt changes in seconds (python -m sre.replay)."""
    def __init__(self, path):
        self.path, self.cur, self.seen = path, None, {"spans": set(), "logs": set()}
    def put(self, key, data):
        if self.cur is not None and key not in self.cur: self.cur[key] = data
    def flush(self, meta):
        if self.cur is None: return
        out = {}
        for k, v in self.cur.items():
            kind = "spans" if k.startswith("/api/spans") else "logs" if k.startswith("/api/logs") else None
            if kind and isinstance(v, list):
                ids = [x.get("span_id") if kind == "spans" else x.get("log_id") or f"{x.get('timestamp')}{x.get('service_name')}{x.get('message')}" for x in v]
                out[k] = {"delta": [x for x, i in zip(v, ids) if i not in self.seen[kind]]}; self.seen[kind].update(ids)
            else: out[k] = v
        with open(self.path, "a") as fh: fh.write(json.dumps({"t": time.time(), **meta, "r": out}) + "\n")
        self.cur = None


class TinyOllyBackend(Backend):
    name = "tinyolly"
    duties = ["shift-note", "instrumentation-gaps", "platform-health", "mesh-posture"]

    def __init__(self):
        self.mcp_url = E("TINYOLLY_MCP_URL", "http://tinyolly-mcp:8765/mcp")
        self.c = httpx.Client(base_url=URL, timeout=20)
        self.learned: dict[str, Learned] = collections.defaultdict(Learned)
        self.mesh0: dict | None = None; self.dropped0: int | None = None
        self._topo: tuple[float, set] = (0.0, set())
        self.rec = Recorder(E("SRE_RECORD")) if E("SRE_RECORD") else None
        self.fence_t = 0.0                                     # telemetry before this time is ignored (set when an injected fault ends)
        self.op_err: dict[tuple, float] = {}; self.op_hits: collections.Counter = collections.Counter(); self.op_n: collections.Counter = collections.Counter()

    def fence(self, t: float | None = None):
        """Clean cutoff: forget telemetry before `t`, so the next fault is judged without waiting for the last one to age out."""
        self.fence_t = t or time.time()
        for L in self.learned.values(): L.hits.clear(); L.held = 0
        self.op_hits.clear()

    def links(self):
        u = PUBLIC_URL
        return {"trace": u + "/?tab=traces&traceId={id}", "service": u + "/?tab=catalog", "catalog": u + "/?tab=catalog", "map": u + "/?tab=map",
                "logs": u + "/?tab=logs&search={id}", "spans": u + "/?tab=spans&search={id}", "traces": u + "/?tab=traces&search={id}",
                "metrics": u + "/?tab=metrics&search={id}"}

    def topology(self):
        """(caller, callee) pairs from the service map, cached for 30 s."""
        at, edges = self._topo
        if time.time() - at < 30: return edges
        m = self._safe("/api/service-map", {}, limit=1000)
        edges = {(e.get("source"), e.get("target")) for e in m.get("edges") or [] if not _ignored(str(e.get("source")))} or edges
        self._topo = (time.time(), edges)
        return edges

    def _get(self, path, **params):
        r = self.c.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        d = r.json()
        if self.rec: self.rec.put(_key(path, params), d)
        return d

    def _safe(self, path, default, **params):
        try: return self._get(path, **params) or default
        except Exception: return default

    def _spans(self, seconds: float) -> list[dict]:
        """Spans from the last `seconds` (the API's fields: service_name, trace_id, start_time, name, status)."""
        cut = max(time.time() - seconds, self.fence_t)
        return [s for s in self._safe("/api/spans", [], limit=5000) if _secs(s.get("start_time")) >= cut]

    def _recent_errors(self, seconds: float) -> list[dict]:
        return [s for s in self._spans(seconds) if _is_error(s)]

    def _recent_stats(self) -> dict[str, dict]:
        """Per service over the last RECENT_S: error %, and (for DETECT_RECENT_STATS) rate and p95. A low-traffic service
        (< RECENT_MIN_SPANS spans there) is measured over 3x that, so a partial fault on a service called a few times a
        minute still clears the RECENT_ERRORS_MIN floor. `window_s` is the time really covered (a fence shortens it)."""
        now = time.time(); cut = max(now - RECENT_S, self.fence_t); lcut = max(now - RECENT_S * 3, self.fence_t)
        short, long_ = collections.defaultdict(list), collections.defaultdict(list)
        for s in self._spans(RECENT_S * 3):
            row = (_is_error(s), float(s.get("duration_ms") or 0))
            long_[_svc(s)].append(row)
            if _secs(s.get("start_time")) >= cut: short[_svc(s)].append(row)
        out = {}
        for k, rows_l in long_.items():
            rows, win = (short[k], now - cut) if len(short[k]) >= RECENT_MIN_SPANS else (rows_l, now - lcut)
            bad = sum(e for e, _ in rows); d = sorted(x for _, x in rows)
            out[k] = {"error_rate": round(bad * 100 / len(rows), 2) if rows and bad >= RECENT_ERRORS_MIN else 0.0,
                      "rate": round(len(rows) / win, 3) if win > 0 else 0.0, "duration_p95": d[int(0.95 * (len(d) - 1))] if d else 0.0, "window_s": win}
        return out

    def _recent_error_pct(self) -> dict[str, float]:
        return {k: v["error_rate"] for k, v in self._recent_stats().items()}

    # ---- detectors (no model) ----
    def detect(self) -> list[Signal]:
        if self.rec:                                   # also keep what investigations read, so --model replays see the same evidence
            self.rec.cur = {}; self._safe("/api/events", [], minutes=15, limit=20); self._safe("/api/service-map", {}, limit=1000)
        out: list[Signal] = []
        D = DETECTORS
        if "errors" in D:
            by = collections.Counter(_svc(s) for s in self._recent_errors(WINDOW_S))
            out += [Signal("errors", svc, f"{svc}: {n} failing spans in the last {max(WINDOW_S // 60, 1)} min") for svc, n in by.most_common() if n >= ERRORS_MIN and not _ignored(svc)]
        cat = {c["name"]: c for c in self._safe("/api/service-catalog", [])}
        if cat: out += self._catalog_signals(cat, D, self._recent_stats())
        if "op-errors" in D: out += self._op_signals()
        if "logs" in D:
            cut = max(time.time() - WINDOW_S, self.fence_t)
            by = collections.Counter(l.get("service_name") or "unknown" for l in self._safe("/api/logs", [], limit=1000)
                                     if (l.get("severity") or "").lower() in ("error", "fatal", "critical") and _secs(l.get("timestamp")) >= cut)
            out += [Signal("logs", svc, f"{svc}: {n} error logs in the last {max(WINDOW_S // 60, 1)} min") for svc, n in by.most_common() if n >= LOG_ERRORS_MIN and not _ignored(svc)]
        if "mesh" in D: out += self._mesh_signals()
        if "platform" in D: out += self._platform_signals()
        return out

    def _op_signals(self) -> list[Signal]:
        """Error % per operation (service + span name) over the long recent window, against its own learned normal.
        Catches a failing dependency call (e.g. frontend -> GetAds at 14%) hidden inside a busy service's 0.5% overall."""
        tot, bad = collections.Counter(), collections.Counter()
        for s in self._spans(RECENT_S * 3):
            if _ignored(_svc(s)): continue
            k = (_svc(s), s.get("name") or "?"); tot[k] += 1; bad[k] += _is_error(s)
        out, by_svc = [], {}
        for k, n in tot.items():
            pct = bad[k] * 100 / n if n >= OP_MIN_SPANS and bad[k] >= RECENT_ERRORS_MIN else 0.0
            norm = self.op_err.get(k); ready = self.op_n[k] >= BASELINE_POLLS
            hit = ready and pct >= ERR_PCT_MIN and pct > 3 * min(max(norm or 0, 0.5), ERR_PCT_MIN)
            self.op_hits[k] = self.op_hits[k] + 1 if hit else 0
            if not hit: self.op_err[k] = pct if norm is None else norm * 0.9 + pct * 0.1; self.op_n[k] += 1   # never learn a failure as normal
            if self.op_hits[k] >= CONFIRM_POLLS and (k[0] not in by_svc or pct > by_svc[k[0]][0]): by_svc[k[0]] = (pct, k[1], bad[k], n)
        for svc, (pct, op, b, n) in by_svc.items():
            out.append(Signal("op-errors", svc, f"{svc}: {op} failing {pct:.0f}% ({b} of {n} calls, normal {self.op_err.get((svc, op), 0):.1f}%)"))
        return out

    def _catalog_signals(self, cat, D, recent=None):
        out = []
        for name, c in cat.items():
            if _ignored(name): continue
            L = self.learned[name]; L.missing = 0; ready = L.n >= BASELINE_POLLS
            if recent is not None:
                r = recent.get(name, 0.0)
                r = r if isinstance(r, dict) else {"error_rate": r}            # tests pass plain error %s
                c = {**c, "error_rate": r.get("error_rate", 0.0)}
                if RECENT_STATS and "rate" in r:
                    if r["window_s"] >= RECENT_S / 2: c.update(rate=r["rate"], duration_p95=r["duration_p95"])
                    else: c.update(rate=L.rate, duration_p95=L.p95)        # just after a fence: too little data, stay neutral
                elif RECENT_STATS:                                             # no spans in the window: silent, unless a fence just cleared it
                    c.update(rate=L.rate if time.time() - self.fence_t < RECENT_S / 2 else 0.0, duration_p95=L.p95)
            checks = {
                "error-rate": ready and float(c.get("error_rate") or 0) >= ERR_PCT_MIN and float(c.get("error_rate") or 0) > 3 * min(max(L.err, 0.5), ERR_PCT_MIN),
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
            if name in cat or _ignored(name) or L.n < BASELINE_POLLS: continue
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
            key = (_svc(s), (s.get("name") or "?")[:80], ((s.get("status") or {}).get("message") or "")[:100])
            groups[key][0] += 1; groups[key][1] = groups[key][1] or s.get("trace_id", "")
        ranked = sorted(groups.items(), key=lambda kv: (kv[0][0] != entity, -kv[1][0]))[:5]
        parts.append(f"ERROR SPANS (last {win // 60} min; service | span | status message | count | example trace_id):")
        parts += [f"  {k[0]} | {k[1]} | {k[2] or '-'} | {n} | {tid}" for k, (n, tid) in ranked] or ["  none"]
        if ranked: top_svc, top_tid = ranked[0][0][0], ranked[0][1][1]
        cat = {c["name"]: c for c in self._safe("/api/service-catalog", [])}
        recent = self._recent_error_pct()
        for svc in dict.fromkeys([top_svc, entity]):
            c = cat.get(svc); L = self.learned.get(svc)
            if c: parts.append(f"SERVICE {svc}: rate {c.get('rate')}/s, error rate {recent.get(svc, 0.0)}% (last {RECENT_S} s), p95 {c.get('duration_p95')} ms" +
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
            recent = self._recent_error_pct()
            rows = sorted(({**c, "error_rate": recent.get(c["name"], 0.0)} for c in cat), key=lambda c: -c["error_rate"])[:12]
            err = collections.Counter(_svc(s) for s in self._recent_errors(900))
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

    def mark_change(self, title, attrs):
        try: self.c.post("/api/events", json={"title": title[:200], "source": "flagd", "kind": "flag", "attributes": attrs}).raise_for_status()
        except Exception: pass

    def publish(self, kind, title, attrs):
        try: self.c.post("/api/events", json={"title": title[:200], "source": "tinyolly-sre", "kind": kind, "attributes": {k: v for k, v in attrs.items() if k != "kind"}}).raise_for_status()
        except Exception: pass
