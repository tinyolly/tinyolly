#!/usr/bin/env python3
"""End-to-end test of a RUNNING TinyOlly stack, driven only through its public APIs (stdlib only).

  scripts/e2e.py                       # run everything against localhost
  scripts/e2e.py --up                  # start Colima + the local core stack first
  scripts/e2e.py --only baseline,sampling
  scripts/e2e.py --list

How it works: telemetry is sent as OTLP/JSON to the collector (:4318) so it takes the real path
collector -> OTLP receiver (gRPC/protobuf) -> SQLite -> UI API; collector presets are applied through
POST /api/opamp/config?wait=N (which returns once the supervisor reports applied/failed); results are read
back through /api/traces, /api/logs, /api/metrics ... Test hooks used: POST /admin/reset (clean slate) and
`wait` on config apply. Services are named e2e-<run>-* because TinyOlly also ingests its own telemetry.

Exit code 0 = all checks passed.
"""
import argparse
import json
import secrets
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = secrets.token_hex(3)
UI = "http://localhost:5005"
OTLP = "http://localhost:4318"

results = []   # (scenario, name, ok, detail)
current = ["-"]


# ---------------------------------------------------------------------------------------------- helpers
def http(method, url, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    try:
        return code, json.loads(raw) if raw else None
    except ValueError:
        return code, raw.decode(errors="replace")


def ui(path, method="GET", body=None, timeout=60):
    return http(method, UI + path, body, timeout)


def check(name, ok, detail=""):
    results.append((current[0], name, bool(ok), "" if ok else str(detail)[:300]))
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + ("" if ok else f"   -> {str(detail)[:200]}"))
    return bool(ok)


def eventually(fn, timeout=20, interval=0.5):
    """Poll fn() until it returns a truthy value; returns that value or None."""
    end = time.time() + timeout
    while True:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        if time.time() >= end:
            return None
        time.sleep(interval)


def svc(name):
    return f"e2e-{RUN}-{name}"


def res(service, **extra):
    attrs = [{"key": "service.name", "value": {"stringValue": service}}]
    attrs += [{"key": k, "value": {"stringValue": v}} for k, v in extra.items()]
    return {"attributes": attrs}


def attrs(**kv):
    return [{"key": k, "value": ({"intValue": str(v)} if isinstance(v, int) else {"stringValue": str(v)})} for k, v in kv.items()]


def span(trace, name, parent="", error=False, dur_ms=20, start_ns=None, **attributes):
    start = start_ns or time.time_ns()
    s = {"traceId": trace, "spanId": secrets.token_hex(8), "name": name, "kind": 2,
         "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + int(dur_ms * 1e6)), "attributes": attrs(**attributes)}
    if parent:
        s["parentSpanId"] = parent
    if error:
        s["status"] = {"code": 2, "message": "e2e error"}
    return s


def send_traces(groups):
    """groups: [(service, [spans])] -> POST to the collector."""
    body = {"resourceSpans": [{"resource": res(s), "scopeSpans": [{"spans": sp}]} for s, sp in groups]}
    code, _ = http("POST", OTLP + "/v1/traces", body)
    return code == 200


def send_logs(service, records):
    """records: [(severityText, body, extra) ] ; extra may hold traceId/spanId/attributes/severityNumber."""
    recs = []
    for sev, body, extra in records:
        r = {"timeUnixNano": str(time.time_ns()), "body": {"stringValue": body}}
        if sev:
            r["severityText"] = sev
        r.update(extra or {})
        recs.append(r)
    code, _ = http("POST", OTLP + "/v1/logs", {"resourceLogs": [{"resource": res(service), "scopeLogs": [{"logRecords": recs}]}]})
    return code == 200


def send_metrics(service, metrics):
    code, _ = http("POST", OTLP + "/v1/metrics", {"resourceMetrics": [{"resource": res(service), "scopeMetrics": [{"metrics": metrics}]}]})
    return code == 200


def trace_detail(tid):
    code, body = ui(f"/api/traces/{tid}")
    return body if code == 200 else None


def logs_of(service):
    code, body = ui("/api/logs?limit=5000")
    return [l for l in (body or []) if l.get("service_name") == service] if code == 200 else []


def metric_names():
    code, body = ui("/api/metrics")
    return {m["name"]: m for m in (body or [])} if code == 200 else {}


def reset():
    code, _ = ui("/admin/reset", "POST")
    return code == 200


def collector_ready(timeout=30):
    """Collector accepts OTLP again (it restarts when a config is applied)."""
    def probe():
        return http("POST", OTLP + "/v1/traces", {"resourceSpans": []}, timeout=3)[0] == 200
    return eventually(probe, timeout, 0.5)


def apply_preset(preset, wait=60):
    """Apply a template through the API; returns (ok, detail). ok only if every targeted agent reports applied."""
    code, tpl = ui(f"/api/opamp/templates/{preset}")
    if code != 200:
        return False, f"template {preset}: HTTP {code}"
    code, out = ui(f"/api/opamp/config?wait={wait}", "POST", {"config": tpl["config"]}, timeout=wait + 15)
    if code != 200:
        return False, f"apply: HTTP {code} {out}"
    agents = out.get("agents") or {}
    if not agents:
        return False, f"no connected agents were targeted: {out}"
    bad = {k: v for k, v in agents.items() if not v.get("applied")}
    if bad:
        return False, f"not applied: {bad}"
    if not collector_ready():
        return False, "collector did not come back after apply"
    time.sleep(1.5)     # let pipelines finish starting
    return True, out.get("config_hash", "")


def scenario_setup(title, preset="default"):
    print(f"\n== {title}")
    ok, detail = apply_preset(preset)
    check(f"apply '{preset}' via API and agent reports applied", ok, detail)
    check("reset data via /admin/reset", reset())
    return ok


# ---------------------------------------------------------------------------------------------- scenarios
def s_health():
    code, h = ui("/health")
    check("UI /health", code == 200, (code, h))
    code, st = ui("/api/opamp/status")
    agents = (st or {}).get("agents", {}) if code == 200 else {}
    check("an OpAMP agent (collector) is connected", any(a.get("status") == "connected" for a in agents.values()), st)
    check("collector accepts OTLP/HTTP", collector_ready(10))
    code, stats = ui("/admin/stats")
    check("/admin/stats works", code == 200 and "telemetry" in (stats or {}), stats)


def s_baseline():
    if not scenario_setup("baseline pipeline (default config)"):
        return
    fe, be = svc("frontend"), svc("backend")
    tid, bad = secrets.token_hex(16), secrets.token_hex(16)
    root = span(tid, "GET /cart", **{"http.route": "/cart", "http.method": "GET"})
    child = span(tid, "SELECT carts", parent=root["spanId"], error=True, dur_ms=8)
    ok_trace = span(bad, "GET /ok", dur_ms=5)
    check("send traces", send_traces([(fe, [root, ok_trace]), (be, [child])]))
    check("send correlated log", send_logs(fe, [("ERROR", "cart failed", {"traceId": tid, "spanId": root["spanId"], "severityNumber": 17})]))
    check("send uncorrelated log", send_logs(fe, [("INFO", "hello e2e", {})]))
    bucket = {"timeUnixNano": str(time.time_ns()), "count": "3", "sum": 30.0, "bucketCounts": ["1", "2", "0"], "explicitBounds": [10.0, 100.0],
              "exemplars": [{"timeUnixNano": str(time.time_ns()), "asDouble": 12.0, "traceId": tid, "spanId": root["spanId"]}],
              "attributes": attrs(route="/cart")}
    check("send metrics", send_metrics(fe, [
        {"name": f"e2e.{RUN}.requests", "unit": "1", "sum": {"aggregationTemporality": 2, "isMonotonic": True,
         "dataPoints": [{"timeUnixNano": str(time.time_ns()), "asInt": "5", "attributes": attrs(route="/cart")}]}},
        {"name": f"e2e.{RUN}.latency", "unit": "ms", "histogram": {"aggregationTemporality": 2, "dataPoints": [bucket]}},
        {"name": f"e2e.{RUN}.exp", "unit": "ms", "exponentialHistogram": {"aggregationTemporality": 2, "dataPoints": [
            {"timeUnixNano": str(time.time_ns()), "count": "6", "sum": 40.0, "scale": 1, "zeroCount": "1",
             "positive": {"offset": 2, "bucketCounts": ["1", "2", "0", "2"]}}]}},
        {"name": f"e2e.{RUN}.queue", "unit": "1", "gauge": {"dataPoints": [{"timeUnixNano": str(time.time_ns()), "asDouble": 7.5}]}}]))

    d = eventually(lambda: (lambda x: x if x and len(x["spans"]) == 2 else None)(trace_detail(tid)))
    check("trace arrives with both spans (frontend + backend)", d, "trace missing")
    if d:
        by = {s["name"]: s for s in d["spans"]}
        check("span ids are hex and parent/child linked", by["SELECT carts"]["parentSpanId"] == by["GET /cart"]["spanId"] and len(tid) == 32)
        check("service names preserved per span", {s["serviceName"] for s in d["spans"]} == {fe, be})
        check("error status preserved", by["SELECT carts"]["status"].get("code") in (2, "STATUS_CODE_ERROR"))
    code, traces = ui("/api/traces?limit=5000")
    summ = next((t for t in traces or [] if t["trace_id"] == tid), None)
    check("trace summary: root, span_count, has_error", summ and summ["root_span_name"] == "GET /cart" and summ["span_count"] == 2 and summ["has_error"], summ)

    corr = eventually(lambda: [l for l in ui(f"/api/logs?trace_id={tid}")[1] or [] if l["message"] == "cart failed"])
    check("log correlated to trace by trace_id", corr and corr[0]["span_id"] == root["spanId"] and corr[0]["service_name"] == fe, corr)
    check("uncorrelated log stored", eventually(lambda: [l for l in logs_of(fe) if l["message"] == "hello e2e"]))

    names = eventually(lambda: (lambda n: n if f"e2e.{RUN}.latency" in n else None)(metric_names()))
    check("metrics listed (sum, histogram, gauge)", names and all(f"e2e.{RUN}.{x}" in names for x in ("requests", "latency", "queue")), list(names or {})[:10])
    code, m = ui(f"/api/metrics/e2e.{RUN}.latency")
    series = (m or {}).get("series", []) if code == 200 else []
    ex = [e for s in series for e in s.get("exemplars", [])]
    check("histogram datapoint stored", series and series[0]["datapoints"][0].get("histogram"), series[:1])
    code, me = ui(f"/api/metrics/e2e.{RUN}.exp")
    pts = [dp for sr in (me or {}).get("series", []) for dp in sr["datapoints"]] if code == 200 else []
    check("exponential histogram is stored (converted to buckets), not dropped", pts and pts[0]["histogram"] and pts[0]["histogram"]["count"] == 6, me)
    check("exemplar traceId is hex and links to the stored trace", ex and ex[0]["traceId"] == tid, ex)

    cat = eventually(lambda: (lambda c: c if {fe, be} <= {x["name"] for x in c} else None)(ui("/api/service-catalog")[1] or []))
    check("service catalog lists both services", cat, "missing")
    if cat:
        b = next(x for x in cat if x["name"] == be)
        check("catalog: backend error_rate reflects the error span", b["error_rate"] > 0, b)
    code, smap = ui("/api/service-map")
    edges = (smap or {}).get("edges", [])
    check("service map has frontend -> backend edge", any(e.get("source") == fe and e.get("target") == be for e in edges)
          or any(e.get("data", {}).get("source") == fe for e in edges), edges[:3])

    sm = eventually(lambda: (lambda n: n.get("traces.span.metrics.calls") if n else None)(metric_names()), 40)
    check("collector spanmetrics connector produced RED metrics", sm and fe in sm.get("services", []), sm)

    # direct JSON ingest into the UI (bypasses the collector): hex ids, resource attrs and shape validation
    tid2, sid2 = secrets.token_hex(16), secrets.token_hex(8)
    body = {"resourceSpans": [{"resource": res(svc("direct")), "scopeSpans": [{"spans": [
        {"traceId": tid2, "spanId": sid2, "name": "direct", "startTimeUnixNano": "1", "endTimeUnixNano": "2000000"}]}]}]}
    check("direct OTLP/JSON ingest to UI /v1/traces", http("POST", UI + "/v1/traces", body)[0] == 200)
    d2 = trace_detail(tid2)
    check("direct ingest keeps hex ids + service name", d2 and d2["spans"][0]["spanId"] == sid2 and d2["spans"][0]["serviceName"] == svc("direct"), d2)
    check("wrong payload shape is a 400, not a 500", http("POST", UI + "/v1/traces", {"resourceSpans": "nope"})[0] == 400)

    code, stats = ui("/admin/stats")
    check("admin stats count the data", stats["telemetry"]["spans"] >= 3 and stats["telemetry"]["logs"] >= 2, stats["telemetry"])
    check("reset empties storage", reset() and ui("/admin/stats")[1]["telemetry"]["spans"] == 0)


def s_opamp():
    print("\n== OpAMP apply flow")
    code, out = ui("/api/opamp/config", "POST", {"config": "not: [valid"})
    check("malformed YAML rejected (400)", code == 400, (code, out))
    code, out = ui("/api/opamp/config", "POST", {"config": "42"})
    check("non-mapping config rejected (400)", code == 400, (code, out))
    code, out = ui("/api/opamp/config", "POST", {"config": "a: 1", "instance_id": "does-not-exist"})
    check("unknown config / instance never reaches the collector (4xx)", 400 <= code < 500, (code, out))
    ok, h1 = apply_preset("sampling")
    check("apply 'sampling' and agent reports applied", ok, h1)
    code, st = ui("/api/opamp/status")
    agent = next(iter((st or {}).get("agents", {}).values()), {})
    check("status shows config_status=applied and the matching hash", agent.get("config_status") == "applied" and agent.get("applied_config_hash") == h1, agent.get("config_status"))
    check("effective config now contains tail_sampling", "tail_sampling" in agent.get("effective_config", ""))
    ok, h2 = apply_preset("default")
    check("apply 'default' again; hash differs and is applied", ok and h2 != h1, (ok, h1, h2))
    code, st = ui("/api/opamp/status")
    agent = next(iter((st or {}).get("agents", {}).values()), {})
    check("effective config back to default (no tail_sampling)", "tail_sampling" not in agent.get("effective_config", ""))
    ok, h3 = apply_preset("default")
    check("re-applying the same config is idempotent and applied", ok and h3 == h2, (ok, h2, h3))


def s_sampling():
    if not scenario_setup("preset: sampling", "sampling"):
        return
    s = svc("sampling")
    errs = [secrets.token_hex(16) for _ in range(3)]
    oks = [secrets.token_hex(16) for _ in range(60)]
    send_traces([(s, [span(t, "boom", error=True, dur_ms=5) for t in errs] + [span(t, "fine", dur_ms=5) for t in oks])])
    send_logs(s, [("WARN", f"warn-{i}", {"severityNumber": 13}) for i in range(8)] + [("ERROR", f"err-{i}", {"severityNumber": 17}) for i in range(4)])
    time.sleep(9)      # tail_sampling decision_wait is 5 s
    kept_err = [t for t in errs if trace_detail(t)]
    check("all error traces are kept", len(kept_err) == 3, f"{len(kept_err)}/3")
    kept_ok = [t for t in oks if trace_detail(t)]
    check("healthy traces are sampled down (10% policy)", len(kept_ok) < 40, f"{len(kept_ok)}/60 kept")
    got = {l["message"] for l in logs_of(s)}
    check("WARN/ERROR logs without trace id are always kept", all(f"warn-{i}" in got for i in range(8)) and all(f"err-{i}" in got for i in range(4)), sorted(got))


def s_pii():
    if not scenario_setup("preset: pii-redaction", "pii-redaction"):
        return
    s = svc("pii")
    tid = secrets.token_hex(16)
    secrets_in = {"email": "jane.doe+x@example.com", "visa": "4111 1111 1111 1111", "bearer": "Bearer abcdef0123456789abcdef", "api_key": "SECRETVALUE9"}
    body = f"user {secrets_in['email']} paid with {secrets_in['visa']} via {secrets_in['bearer']} url https://x.io/p?api_key={secrets_in['api_key']}&page=2 ok-marker"
    send_logs(s, [("INFO", body, {"traceId": tid})])
    send_traces([(s, [span(tid, "checkout", **{"user.email": secrets_in["email"], "http.url": f"https://x.io/p?api_key={secrets_in['api_key']}&page=2"})])])
    log = eventually(lambda: next(iter(logs_of(s)), None))
    check("log arrives", log)
    if log:
        for k, v in secrets_in.items():
            probe = v if k != "api_key" else v
            check(f"log: {k} masked", probe not in json.dumps(log), "still visible")
        check("log: non-sensitive text kept", "ok-marker" in log["message"] and "page=2" in log["message"], log["message"])
    d = eventually(lambda: trace_detail(tid))
    check("span attributes: email and api_key masked", d and secrets_in["email"] not in json.dumps(d) and secrets_in["api_key"] not in json.dumps(d), "still visible")


def s_transform():
    if not scenario_setup("preset: transform-ottl", "transform-ottl"):
        return
    health, real, s = svc("probe"), svc("real"), svc("transform")
    t_h, t_r = secrets.token_hex(16), secrets.token_hex(16)
    send_traces([(health, [span(t_h, "GET /healthz", **{"url.path": "/healthz"})]),
                 (real, [span(t_r, "GET /orders", **{"url.path": "/api/orders", "http.route": "/users/123/orders/456"})])])
    send_logs(s, [(None, json.dumps({"level": "debug", "msg": "noisy-e2e"}), {}), (None, json.dumps({"level": "error", "msg": "boom-e2e"}), {}),
                  (None, json.dumps({"user": "bob", "action": "login"}), {})])
    d = eventually(lambda: trace_detail(t_r))
    check("normal trace kept", d)
    check("health-check trace dropped", trace_detail(t_h) is None)
    if d:
        route = next((a["value"].get("stringValue") for a in d["spans"][0]["attributes"] if a["key"] == "http.route"), None)
        check("route normalised to /users/{id}/orders/{id}", route == "/users/{id}/orders/{id}", route)
    recs = eventually(lambda: logs_of(s) if len(logs_of(s)) >= 2 else None, 15) or []
    msgs = " ".join(json.dumps(l) for l in recs)
    check("JSON debug log dropped", "noisy-e2e" not in msgs, msgs[:200])
    check("JSON error log kept", "boom-e2e" in msgs)
    flat = next((l for l in recs if "login" in json.dumps(l)), None)
    check("JSON body flattened to attributes", flat and flat["attributes"].get("user") == "bob", flat)


def s_dedup():
    if not scenario_setup("preset: logs-dedup", "logs-dedup"):
        return
    s = svc("dedup")
    send_logs(s, [("INFO", "spam-e2e", {}) for _ in range(25)] + [("ERROR", "err-e2e", {"severityNumber": 17}) for _ in range(4)])
    errs = eventually(lambda: [l for l in logs_of(s) if l["message"] == "err-e2e"] if len([l for l in logs_of(s) if l["message"] == "err-e2e"]) >= 4 else None, 15)
    check("ERROR logs are never folded (all 4 kept)", errs and len(errs) == 4, len(errs or []))
    spam = eventually(lambda: [l for l in logs_of(s) if l["message"] == "spam-e2e"], 30)   # emitted after the 10 s interval
    check("identical INFO spam is collapsed into far fewer records", spam and len(spam) < 25, len(spam or []))
    if spam:
        check("collapsed record carries dedup_count", any(int(l["attributes"].get("dedup_count", 0)) >= 2 for l in spam), spam[0]["attributes"])


def s_routing():
    if not scenario_setup("preset: connectors-routing", "connectors-routing"):
        return
    s = svc("routing")
    t_err, t_ok = secrets.token_hex(16), secrets.token_hex(16)
    send_traces([(s, [span(t_err, "bad", error=True), span(t_ok, "good")])])
    d_err = eventually(lambda: trace_detail(t_err))
    d_ok = eventually(lambda: trace_detail(t_ok))
    check("both traces reach TinyOlly (traces stay complete)", d_err and d_ok)

    def route(d):
        return next((a["value"].get("stringValue") for a in d["spans"][0]["attributes"] if a["key"] == "collector.route"), None) if d else "?"
    check("error span tagged collector.route=errors", route(d_err) == "errors", route(d_err))
    check("OK span is not tagged", route(d_ok) is None, route(d_ok))


def s_conn_metrics():
    if not scenario_setup("preset: connectors-metrics", "connectors-metrics"):
        return
    s = svc("connm")
    send_traces([(s, [span(secrets.token_hex(16), "bad", error=True) for _ in range(3)] + [span(secrets.token_hex(16), "good") for _ in range(2)])])

    def have(name):
        m = metric_names().get(name)
        return m if m and s in m.get("services", []) else None
    check("signaltometrics: tinyolly.span.duration for the service", eventually(lambda: have("tinyolly.span.duration"), 45))
    check("count: tinyolly.span.error.count for the service", eventually(lambda: have("tinyolly.span.error.count"), 45))
    check("spanmetrics RED metrics for the service", eventually(lambda: have("traces.span.metrics.calls"), 45))


def s_enrichment():
    if not scenario_setup("preset: enrichment", "enrichment"):
        return
    s, tid = svc("enrich"), secrets.token_hex(16)
    send_traces([(s, [span(tid, "op")])])
    d = eventually(lambda: trace_detail(tid))
    r = (d or {}).get("spans", [{}])[0].get("resource", {})
    check("spans carry service.namespace + deployment.environment.name + collector.preset",
          r.get("service.namespace") == "tinyolly-demo" and r.get("deployment.environment.name") == "demo" and r.get("collector.preset") == "enrichment", r)


def s_metrics_shaping():
    if not scenario_setup("preset: metrics-shaping", "metrics-shaping"):
        return
    s = svc("shape")
    now = str(time.time_ns())
    gauge = lambda n: {"name": n, "gauge": {"dataPoints": [{"timeUnixNano": now, "asDouble": 1.0}]}}
    send_metrics(s, [gauge(f"e2e.{RUN}.keep"), gauge("process.runtime.e2e.dropme"), gauge("runtime.e2e.dropme2")])
    keep = eventually(lambda: metric_names().get(f"e2e.{RUN}.keep"), 60, 2)     # `interval` processor flushes every 30 s
    check("regular metric passes through (after the 30s interval)", keep)
    names = metric_names()
    check("runtime.* metrics are filtered out", "process.runtime.e2e.dropme" not in names and "runtime.e2e.dropme2" not in names, [n for n in names if "dropme" in n])


def s_promrw():
    if not scenario_setup("preset: prometheus-remote-write", "prometheus-remote-write"):
        return
    try:
        socket.create_connection(("localhost", 19291), timeout=3).close()
        listening = True
    except OSError:
        listening = False
    check("Prometheus remote-write receiver listens on :19291", listening)
    s, tid = svc("prw"), secrets.token_hex(16)
    send_traces([(s, [span(tid, "still-works")])])
    check("OTLP traces still flow with this preset", eventually(lambda: trace_detail(tid)))


SCENARIOS = {
    "health": s_health, "baseline": s_baseline, "opamp": s_opamp, "sampling": s_sampling, "pii": s_pii,
    "transform": s_transform, "dedup": s_dedup, "routing": s_routing, "connmetrics": s_conn_metrics,
    "enrichment": s_enrichment, "metricsshaping": s_metrics_shaping, "promrw": s_promrw,
}


def main():
    global UI, OTLP
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ui", default=UI)
    ap.add_argument("--otlp", default=OTLP)
    ap.add_argument("--only", help="comma-separated scenarios (see --list)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--up", action="store_true", help="start Colima + the local core stack first (rebuilds images, clears data)")
    ap.add_argument("--keep", action="store_true", help="do not restore the default collector config at the end")
    a = ap.parse_args()
    UI, OTLP = a.ui.rstrip("/"), a.otlp.rstrip("/")
    if a.list:
        print("\n".join(SCENARIOS))
        return 0
    if a.up:
        subprocess.run([str(ROOT / "scripts/colima-up.sh")], check=True)
        subprocess.run(["./01-start-core-local.sh"], cwd=ROOT / "docker", check=True)
    if not eventually(lambda: http("GET", UI + "/health", timeout=3)[0] == 200, 120, 2):
        print(f"UI not reachable at {UI}. Start the stack (docker/01-start-core-local.sh) or pass --up.", file=sys.stderr)
        return 2
    eventually(lambda: any(x.get("status") == "connected" for x in (ui("/api/opamp/status")[1] or {}).get("agents", {}).values()), 60, 2)

    names = a.only.split(",") if a.only else list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print(f"unknown scenario(s): {unknown}; see --list", file=sys.stderr)
        return 2
    started = time.time()
    print(f"e2e run {RUN} against {UI}")
    for n in names:
        current[0] = n
        try:
            SCENARIOS[n]()
        except Exception:
            check("scenario completed without an exception", False, traceback.format_exc().splitlines()[-1])
            traceback.print_exc()
    if not a.keep:
        print("\n== restore default collector config")
        current[0] = "restore"
        ok, d = apply_preset("default")
        check("default config restored", ok, d)

    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed in {time.time() - started:.0f}s")
    for sc, name, _, detail in failed:
        print(f"  FAILED [{sc}] {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
