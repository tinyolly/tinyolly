#!/usr/bin/env python3
"""Post synthetic Istio ambient metrics (OTLP/JSON) for the Online Boutique mesh.

Lets TinyOlly's mesh features (service map, posture, version split, response flags) be exercised on Docker
Compose, which has no Istio. Counters are cumulative and grow with every tick, like real ztunnel/waypoint ones.

  scripts/seed_mesh.py --otlp http://localhost:4418 --scenario flaky --duration 120
Scenarios: baseline, flaky (half the productcatalogservice calls fail, flag UC), fault (2 s delay on half the
currencyservice calls, flag DI), canary (10% to a slow v2), deny (a plaintext outsider refused with flag DENY).
"""
import argparse
import json
import time
import urllib.request

SCENARIOS = ("baseline", "flaky", "fault", "canary", "deny", "multicluster")
# multicluster: these services run in a second cluster, so calls into them cross clusters
REMOTE = {"productcatalogservice", "redis-cart", "currencyservice"}
EDGES = [
    ("loadgenerator", "frontend"), ("frontend", "productcatalogservice"), ("frontend", "currencyservice"),
    ("frontend", "cartservice"), ("frontend", "recommendationservice"), ("frontend", "adservice"),
    ("frontend", "shippingservice"), ("frontend", "checkoutservice"), ("checkoutservice", "productcatalogservice"),
    ("checkoutservice", "cartservice"), ("checkoutservice", "currencyservice"), ("checkoutservice", "paymentservice"),
    ("checkoutservice", "emailservice"), ("checkoutservice", "shippingservice"),
    ("recommendationservice", "productcatalogservice"), ("cartservice", "redis-cart"),
]
BOUNDS = [1, 5, 25, 100, 500, 2500]
PER_TICK = 10


def _attr(key, value):
    return {"key": key, "value": {"stringValue": value}}


def _labels(src, dst, reporter, flags="-", policy="mutual_tls", version=None, clusters=False):
    labels = {"source_canonical_service": src, "destination_canonical_service": dst, "source_workload": src,
              "destination_workload": dst, "source_workload_namespace": "boutique",
              "destination_workload_namespace": "boutique", "connection_security_policy": policy,
              "reporter": reporter, "response_code": "200", "response_flags": flags, "request_protocol": "grpc",
              "source_principal": f"spiffe://cluster.local/ns/boutique/sa/{src}" if policy == "mutual_tls" else "",
              "destination_principal": f"spiffe://cluster.local/ns/boutique/sa/{dst}" if policy == "mutual_tls" else ""}
    if version:
        labels["destination_version"] = version
    if clusters:
        labels["source_cluster"] = "cluster-b" if src in REMOTE else "cluster-a"
        labels["destination_cluster"] = "cluster-b" if dst in REMOTE else "cluster-a"
    if reporter == "source":                       # ztunnel's TCP metrics have no HTTP/gRPC fields
        del labels["response_code"], labels["request_protocol"]
    return [_attr(k, v) for k, v in labels.items()]


def _sum_point(labels, value, now_ns):
    return {"attributes": labels, "timeUnixNano": str(now_ns), "asInt": str(int(value))}


def _hist_point(labels, count, avg_ms, now_ns):
    buckets = [0] * (len(BOUNDS) + 1)
    buckets[next((i for i, b in enumerate(BOUNDS) if avg_ms <= b), len(BOUNDS))] = int(count)
    return {"attributes": labels, "timeUnixNano": str(now_ns), "count": str(int(count)), "sum": float(avg_ms * count),
            "bucketCounts": [str(c) for c in buckets], "explicitBounds": BOUNDS}


def _request_variants(src, dst, scenario, tick):
    """(response_flags, version, requests, avg_ms) for one edge under a scenario."""
    n = PER_TICK * tick
    if scenario == "flaky" and dst == "productcatalogservice":
        return [("-", None, n // 2, 2.0), ("UC", None, n - n // 2, 2.0)]
    if scenario == "fault" and dst == "currencyservice":
        return [("-", None, n - n // 2, 2.0), ("DI", None, n // 2, 2000.0)]
    if scenario == "canary" and dst == "productcatalogservice":
        v2 = n // 10
        return [("-", "v1", n - v2, 1.0), ("-", "v2", v2, 400.0)]
    return [("-", None, n, 2.0)]


def build_metrics_payload(tick, scenario, now_ns, l7=None):
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose from {', '.join(SCENARIOS)}")
    requests, durations, opened, failed = [], [], [], []
    multi = scenario == "multicluster"
    for src, dst in EDGES:
        if l7 and dst != l7:                      # request-level (waypoint) metrics only for this destination: the rest is L4
            opened.append(_sum_point(_labels(src, dst, "source", clusters=multi), 2 * tick, now_ns))
            continue
        for flags, version, count, avg in _request_variants(src, dst, scenario, tick):
            labels = _labels(src, dst, "waypoint", flags, version=version, clusters=multi)
            requests.append(_sum_point(labels, count, now_ns))
            durations.append(_hist_point(_labels(src, dst, "waypoint", flags, version=version, clusters=multi), count, avg, now_ns))
        opened.append(_sum_point(_labels(src, dst, "source", clusters=multi), 2 * tick, now_ns))
    if scenario == "deny":
        opened.append(_sum_point(_labels("outsider", "frontend", "source", policy="none"), 3 * tick, now_ns))
        failed.append(_sum_point(_labels("outsider", "frontend", "source", "DENY", "none"), 3 * tick, now_ns))

    def total(name, points):
        return {"name": name, "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": points}}

    metrics = [total("istio_requests_total", requests), total("istio_tcp_connections_opened_total", opened),
               total("istio_tcp_connections_failed_total", failed),
               {"name": "istio_request_duration_milliseconds",
                "histogram": {"aggregationTemporality": 2, "dataPoints": durations}}]
    return {"resourceMetrics": [{"resource": {"attributes": [_attr("service.name", "istio-seed")]},
                                 "scopeMetrics": [{"metrics": metrics}]}]}


TRACE_CHAIN = [("shop-ingress-istio", 100), ("frontend", 90), ("waypoint.boutique", 60), ("productcatalogservice", 40)]


def build_trace_payload(trace_id="0123456789abcdef0123456789abcdef", now_ns=None):
    """One trace through gateway -> frontend -> waypoint -> productcatalogservice, each span inside its parent (durations in ms)."""
    now_ns = now_ns or time.time_ns()
    resources, parent = [], ""
    for i, (service, dur_ms) in enumerate(TRACE_CHAIN, start=1):
        start = now_ns + i * 5_000_000
        span = {"traceId": trace_id, "spanId": f"{i:016x}", "name": f"{service} hop", "kind": 2 if i < len(TRACE_CHAIN) else 3,
                "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + dur_ms * 1_000_000)}
        if parent:
            span["parentSpanId"] = parent
        parent = span["spanId"]
        resources.append({"resource": {"attributes": [_attr("service.name", service)]}, "scopeSpans": [{"spans": [span]}]})
    return {"resourceSpans": resources}


def post_trace(otlp_url, payload):
    req = urllib.request.Request(otlp_url.rstrip("/") + "/v1/traces", json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def event_payload(scenario):
    """Change marker recorded when a scenario starts, like the demo's 03-scenario.sh does."""
    return {"title": f"scenario: {scenario}", "source": "seed_mesh", "kind": "scenario", "attributes": {"scenario": scenario}}


def post_event(ui_url, scenario):
    req = urllib.request.Request(ui_url.rstrip("/") + "/api/events", json.dumps(event_payload(scenario)).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def post(url, payload):
    req = urllib.request.Request(url.rstrip("/") + "/v1/metrics", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--otlp", default="http://localhost:4318")
    ap.add_argument("--scenario", default="baseline", choices=SCENARIOS)
    ap.add_argument("--ui", help="TinyOlly UI URL: record a change marker when the scenario starts (e.g. http://localhost:5005)")
    ap.add_argument("--l7", help="only emit request metrics (as a waypoint would) for edges into this service; the others stay L4")
    ap.add_argument("--trace", action="store_true", help="also post one trace through gateway -> frontend -> waypoint -> productcatalogservice")
    ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--duration", type=float, default=120, help="seconds; 0 = forever")
    args = ap.parse_args()
    if args.ui:
        print(f"event {post_event(args.ui, args.scenario)}", flush=True)
    if args.trace:
        print(f"trace {post_trace(args.otlp, build_trace_payload())}", flush=True)
    start, tick = time.time(), 0
    while True:
        tick += 1
        status = post(args.otlp, build_metrics_payload(tick, args.scenario, time.time_ns(), args.l7))
        print(f"tick {tick} {status}", flush=True)
        if args.duration and time.time() - start >= args.duration:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
