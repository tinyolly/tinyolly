#!/usr/bin/env python3
"""Full test of TinyOlly against the OpenTelemetry Demo (Astronomy Shop), on Docker or kind.

Assumes TinyOlly and the demo are already running (see docs/otel-demo.md); it asserts what TinyOlly shows
through its REST API and MCP server, injects failures with the demo's feature flags, and puts everything back.

    scripts/test-otel-demo.py --mode docker       # flags via docker-otel-demo/03-set-flag.sh
    scripts/test-otel-demo.py --mode k8s          # flags via the flagd ConfigMap in the kind cluster
    scripts/test-otel-demo.py --mode docker --skip-flags --skip-preset   # data checks only

Env: TINYOLLY_UI (default http://localhost:5005), MCP_URL (default http://localhost:8765/mcp),
DOCKER_CONTEXT (docker mode, passed to 03-set-flag.sh), KUBE_CONTEXT (k8s mode, default kind-tinyolly).
Stdlib only. Exit code 1 if any check fails.
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI = os.environ.get("TINYOLLY_UI", "http://localhost:5005").rstrip("/")
MCP_URL = os.environ.get("MCP_URL", "http://localhost:8765/mcp")
KUBE = os.environ.get("KUBE_CONTEXT", "kind-tinyolly")
CORE = ["frontend", "checkout", "payment", "cart", "product-catalog"]
EXPECTED = CORE + ["shipping", "currency", "quote", "email", "ad", "recommendation", "image-provider", "flagd", "load-generator"]
results = []


def log(*a):
    print(*a, flush=True)


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    log(("PASS " if ok else "FAIL ") + name + (f" :: {detail}" if detail and not ok else ""))
    return bool(ok)


def http(path, method="GET", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(UI + path, data, {"content-type": "application/json"} if data else {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None


def get(path):
    return http(path)[1]


def eventually(fn, timeout=120, every=5):
    end = time.time() + timeout
    while time.time() < end:
        try:
            value = fn()
            if value:
                return value
        except Exception:
            pass
        time.sleep(every)
    return None


# ---------------------------------------------------------------------------------------- MCP (stdlib client)
class MCP:
    def __init__(self, url):
        self.url, self.sid = url, None
        self.sid, _ = self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test-otel-demo", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, body):
        headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
        if self.sid:
            headers["mcp-session-id"] = self.sid
        with urllib.request.urlopen(urllib.request.Request(self.url, json.dumps(body).encode(), headers), timeout=120) as resp:
            data = [ln[5:].strip() for ln in resp.read().decode().splitlines() if ln.startswith("data:")]
            return resp.headers.get("mcp-session-id"), (json.loads(data[0]) if data else None)

    def call(self, name, args=None):
        _, reply = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
        return (reply.get("result") or {}).get("content", [])

    def text(self, name, args=None):
        return "\n".join(c["text"] for c in self.call(name, args) if c["type"] == "text")


# ------------------------------------------------------------------------------------------------- flags
def set_flag(mode, flag, variant):
    """Turn a demo feature flag on (variant) or reset everything (flag None)."""
    if mode == "docker":
        script = os.path.join(ROOT, "docker-otel-demo", "03-set-flag.sh")
        cmd = [script, "--reset"] if flag is None else [script, flag, variant]
        out = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(script))
        return out.returncode == 0, (out.stdout + out.stderr).strip()[-200:]
    # The Helm chart copies this ConfigMap into an emptyDir at pod start and flagd reads the copy, so a patch only
    # takes effect after the flagd pod restarts.
    name = os.environ.get("FLAGD_CONFIGMAP", "flagd-config")
    cm = subprocess.run(["kubectl", "--context", KUBE, "get", "configmap", name, "-o", "json"], capture_output=True, text=True)
    if cm.returncode != 0:
        return False, f"ConfigMap {name} not found: {cm.stderr.strip()[-120:]}"
    item = json.loads(cm.stdout)
    key = next(k for k in item["data"] if k.endswith(".json"))
    flags = json.loads(item["data"][key])
    for fname, spec in flags["flags"].items():
        if flag is None:
            spec["defaultVariant"] = "off"
        elif fname == flag:
            if variant not in spec["variants"]:
                return False, f"{flag} has no variant {variant!r}: {list(spec['variants'])}"
            spec["defaultVariant"] = variant
    patch = json.dumps({"data": {key: json.dumps(flags, indent=2)}})
    out = subprocess.run(["kubectl", "--context", KUBE, "patch", "configmap", name, "--type", "merge", "-p", patch], capture_output=True, text=True)
    if out.returncode != 0:
        return False, out.stderr.strip()[-200:]
    # Delete the pod instead of "rollout restart": a rolling update starts the new pod first, which cannot be
    # scheduled when the node's memory requests are nearly full.
    for cmd in (["delete", "pod", "-l", "app.kubernetes.io/component=flagd", "--wait=true"], ["rollout", "status", "deploy/flagd", "--timeout=120s"]):
        out = subprocess.run(["kubectl", "--context", KUBE, *cmd], capture_output=True, text=True)
        if out.returncode != 0:
            return False, out.stderr.strip()[-200:]
    return True, "flagd restarted with the new flags"


# ------------------------------------------------------------------------------------------------ helpers
def catalog():
    return {s["name"]: s for s in (get("/api/service-catalog") or [])}


def traces(limit=500):
    d = get(f"/api/traces?limit={limit}")
    return d if isinstance(d, list) else (d or {}).get("traces", [])


def attrs(span):
    a = span.get("attributes") or {}
    if isinstance(a, list):
        return {x.get("key"): (x.get("value") or {}).get("stringValue", x.get("value")) for x in a}
    return a


def trace_detail(tid):
    return get(f"/api/traces/{tid}") or {}


def recent_error_traces(since, service=None):
    """Traces started after `since` (epoch s) that contain an error span (optionally touching `service`)."""
    found = []
    for t in traces():
        if t.get("start_time", 0) / 1e9 < since or not t.get("has_error"):
            continue
        if service is None or any(s.get("serviceName") == service for s in trace_detail(t["trace_id"]).get("spans", [])):
            found.append(t)
    return found


# -------------------------------------------------------------------------------------------------- suites
def suite_data(mcp):
    log("\n== data flows from the demo")
    cat = eventually(lambda: (lambda c: c if len([n for n in EXPECTED if n in c]) >= 12 else None)(catalog()), 300, 10) or catalog()
    present = [n for n in EXPECTED if n in cat]
    check("catalog has at least 12 of the 14 demo services", len(present) >= 12, f"{len(present)}: missing {sorted(set(EXPECTED) - set(present))}")
    check("core services present (frontend, checkout, payment, cart, product-catalog)", all(n in cat for n in CORE), [n for n in CORE if n not in cat])
    check("services report span counts and rates", all(cat[n].get("span_count", 0) > 0 for n in present if n in cat), None)

    smap = get("/api/service-map?limit=2000") or {}
    edges = {(e["source"], e["target"]) for e in smap.get("edges", [])}
    check("service map has at least 10 edges", len(edges) >= 10, len(edges))
    check("service map has frontend->checkout and checkout->payment", ("frontend", "checkout") in edges and ("checkout", "payment") in edges, sorted(edges)[:12])

    ts = traces()
    check("traces are stored", len(ts) > 0, len(ts))
    best = max(ts, key=lambda t: t.get("span_count", 0)) if ts else None
    spans = trace_detail(best["trace_id"]).get("spans", []) if best else []
    services = {s.get("serviceName") for s in spans}
    check("a checkout-sized trace spans at least 4 services", len(services) >= 4, sorted(services))

    logs = get("/api/logs?limit=3000") or []
    log_services = {entry.get("service_name") for entry in logs}
    check("logs arrive from at least 3 services", len(log_services) >= 3, sorted(log_services))
    # TinyOlly's own access logs dominate the list and their traces may still be in flight, so sample the demo's logs.
    linked = {}
    for entry in logs:
        if entry.get("trace_id") and not str(entry.get("service_name", "")).startswith("tinyolly"):
            linked.setdefault(entry["trace_id"], entry["service_name"])
    sample = list(linked)[:30]
    stored = sum(1 for t in sample if trace_detail(t).get("spans"))
    check("demo log lines are correlated to stored traces (at least 80% of a sample)", sample and stored >= 0.8 * len(sample), f"{stored}/{len(sample)}")

    # The demo's SDKs export metrics on a 60 s interval, so right after a start only span metrics may exist yet.
    def metric_names():
        names = {m["name"] for m in (get("/api/metrics") or [])}
        return names if len(names) >= 10 else None
    names = eventually(metric_names, timeout=90) or {m["name"] for m in (get("/api/metrics") or [])}
    check("metrics arrive (at least 10 names)", len(names) >= 10, len(names))
    check("span-derived metrics exist (spanmetrics connector)", any("span.metrics" in n or "traces.span" in n for n in names), sorted(names)[:15])
    check("runtime or HTTP metrics from the demo exist", any(n.startswith(("http.", "rpc.", "process.", "runtime.", "jvm.", "app.")) for n in names), sorted(names)[:15])

    log("\n== MCP server")
    listed = mcp.text("list_services")
    check("MCP list_services shows the demo", "checkout" in listed and "frontend" in listed, listed[:200])
    found = mcp.text("search_traces", {"service": "checkout", "limit": 3})
    check("MCP search_traces finds checkout traces", '"trace_id"' in found, found[:200])
    if '"trace_id"' in found:
        tid = json.loads(found)["traces"][0]["trace_id"]
        summary = mcp.text("get_trace", {"trace_id": tid})
        check("MCP get_trace returns a summary", "span" in summary.lower(), summary[:150])
    image = [c for c in mcp.call("chart_service_map", {}) if c["type"] == "image"]
    check("MCP chart_service_map returns a PNG", image and len(base64.b64decode(image[0]["data"])) > 5000, "no image")
    check("MCP search_docs answers about the demo", "demo" in mcp.text("search_docs", {"query": "OpenTelemetry demo feature flags"}).lower(), None)


def suite_flags(mode, mcp):
    log("\n== failure injection: paymentFailure")
    ok, detail = set_flag(mode, None, None)
    check("reset all flags", ok, detail)
    time.sleep(45)
    t0 = time.time()
    base = recent_error_traces(t0 - 60, "payment")
    check("baseline: no payment errors in the last minute", len(base) == 0, len(base))

    ok, detail = set_flag(mode, "paymentFailure", "50%")
    check("set paymentFailure 50%", ok, detail)
    t_on = time.time()
    err = eventually(lambda: recent_error_traces(t_on, "payment"), 240, 10)
    check("error traces touching payment appear within 4 minutes", err, "none")
    cat = catalog()
    check("catalog shows payment or checkout with a non-zero error rate",
          (cat.get("payment", {}).get("error_rate", 0) > 0) or (cat.get("checkout", {}).get("error_rate", 0) > 0),
          {n: cat.get(n, {}).get("error_rate") for n in ("payment", "checkout")})
    posture_text = mcp.text("get_service_map", {"only": "errors"})
    check("MCP get_service_map(only=errors) lists the failing edge", "payment" in posture_text or "checkout" in posture_text, posture_text[:200])

    ok, detail = set_flag(mode, None, None)
    check("reset flags after the failure", ok, detail)
    t_off = time.time()
    time.sleep(90)  # flagd reloads, in-flight requests drain
    after = recent_error_traces(t_off + 60, "payment")
    check("recovery: no new payment errors once the flag is off", len(after) == 0, len(after))


def suite_pii(mode):
    log("\n== PII flag and the pii-redaction preset")
    ok, detail = set_flag(mode, "emitRawPii", "on")
    check("set emitRawPii on", ok, detail)

    def raw_pii(since):
        for t in traces():
            if t.get("start_time", 0) / 1e9 < since:
                continue
            for s in trace_detail(t["trace_id"]).get("spans", []):
                a = attrs(s)
                for key in ("demo.payment.card_number", "user.email", "demo.payment.card_cvv"):
                    if key in a:
                        return key, str(a[key])
        return None

    t_on = time.time()
    first = eventually(lambda: raw_pii(t_on), 240, 10)
    check("raw PII attributes appear on spans", first, "none seen")
    check("the values are raw (not masked)", first and "*" not in first[1], first)

    code, tpl = http("/api/opamp/templates/pii-redaction")
    if code != 200:
        check("pii-redaction template exists", False, code)
        set_flag(mode, None, None)
        return
    code, out = http("/api/opamp/config?wait=90", "POST", {"config": tpl["config"]}, timeout=110)
    applied = code == 200 and out and out.get("agents") and all(a.get("applied") for a in out["agents"].values())
    check("apply the pii-redaction preset through OpAMP", applied, (code, str(out)[:200]))
    t_mask = time.time() + 10
    time.sleep(10)
    masked = eventually(lambda: raw_pii(t_mask), 240, 10)
    check("after the preset, the same attributes are masked", masked and "*" in masked[1], masked)

    ok, detail = set_flag(mode, None, None)
    check("reset flags", ok, detail)
    code, tpl = http("/api/opamp/templates/default")
    code, out = http("/api/opamp/config?wait=90", "POST", {"config": tpl["config"]}, timeout=110)
    check("restore the default collector config", code == 200 and out and all(a.get("applied") for a in (out.get("agents") or {"x": {}}).values()), str(out)[:200])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["docker", "k8s"], required=True)
    ap.add_argument("--skip-flags", action="store_true")
    ap.add_argument("--skip-preset", action="store_true")
    args = ap.parse_args()
    code, health = http("/health")
    if code != 200:
        log(f"TinyOlly is not reachable at {UI} (HTTP {code})")
        return 2
    mcp = MCP(MCP_URL)
    suite_data(mcp)
    if not args.skip_flags:
        suite_flags(args.mode, mcp)
    if not args.skip_preset:
        suite_pii(args.mode)
    failed = [n for n, ok in results if not ok]
    log(f"\nSUMMARY {len(results) - len(failed)}/{len(results)} passed")
    if failed:
        log("FAILED: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
