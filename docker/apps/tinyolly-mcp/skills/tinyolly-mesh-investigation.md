---
name: tinyolly-mesh-investigation
description: Use when the user asks about an Istio service mesh in TinyOlly: is traffic encrypted (mTLS), what was denied by policy, why a request is slow or retried in the mesh, waypoint or ztunnel behaviour, canary traffic split, or what changed recently, and the tinyolly MCP tools are available.
---

# TinyOlly mesh investigation: "what is the mesh doing?"

Goal: answer mesh questions (encryption, policy, latency, retries, traffic split) from TinyOlly data in a handful of calls. Ambient mesh facts: **ztunnel** (per node) gives mTLS and L4 metrics but no traces; a **waypoint** (optional proxy) adds L7 spans and metrics.

## Steps

1. **Posture first.** `get_mesh_posture`: mTLS coverage %, plaintext edges, denied edges. If it is all zeros, the mesh metrics are not arriving; use the `tinyolly-troubleshoot-stack` skill.
2. **Show it.** `chart_service_map` (no arguments): edges are green for mTLS, orange dashed for plaintext, red for denied or errors, and waypoints and gateways have their own shapes.
3. **Narrow to the problem edges.** `find_plaintext` and `find_denied` for the lists, or `get_service_map(only="denied")` / `only="plaintext"` / `only="errors"` with `service` to focus on one service. Plaintext edges to telemetry backends (for example tinyolly-otlp-receiver) are normal; plaintext between app services is the real gap.
4. **Explain one edge.** `get_edge(source, target)`: calls, errors, p95, mTLS, denied count, and the RED numbers of both ends.
5. **Slow or retried request.** `search_traces(service=..., min_duration_ms=...)`, then `get_trace_mesh(trace_id)`: mesh time per hop (proxy time minus app time), retry attempts per URL, and decoded Envoy response flags (UH no healthy upstream, UF connection failure, URX retries exhausted). Compare with `get_trace(trace_id, format="waterfall")` for the app side. Needs waypoint tracing; otherwise it says there are no proxy spans.
6. **Canary or version split.** `get_version_split(service)` for traffic share and error rate per version.
7. **What changed?** `compare_windows(minutes=5)` lists services that are new, gone, erroring more or slower than in the previous window. Useful right after a policy, fault or retry change.
8. **Dig into metrics.** `query_metric("istio_requests_total", labels={"response_code": "503"}, group_by="destination_service_name")` ranks destinations by request growth; `list_metrics(search="istio")` shows what is available.

## Report in this shape

- **Posture:** mTLS %, plaintext and denied counts.
- **Finding:** the edge or hop, with numbers (errors, mesh ms, attempts, flags).
- **Evidence:** trace id or metric query.
- **Next:** one concrete action (add a policy, enable the waypoint, fix the retry budget).

## Gotchas

- gRPC denials by an authorization policy come back as HTTP 200 with `grpc-status 7`, so a "healthy" status code can still be a denial; TinyOlly counts these as denied.
- `.namespace` proxy names (for example `waypoint.boutique`) are merged into the app name by default; pass `merge=False` to `get_service_map` to see them separately.
- Edges built only from metrics have no latency; p95 and mesh time need traces through a waypoint.
- Metric counters are cumulative; `delta_sum` and request shares in the tools already use the change over the window.
