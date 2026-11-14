---
title: "Istio Ambient Mesh"
description: "See an Istio ambient service mesh in TinyOlly: topology from ztunnel metrics, mTLS posture, denied calls, waypoints"
---

# Istio Ambient Mesh

TinyOlly can show an [Istio ambient](https://istio.io/latest/docs/ambient/) mesh (no sidecars) on the service map. The ambient data plane splits in two:

- **ztunnel** (one per node) gives every pod mTLS and L4 metrics, but emits **no traces**.
- **Waypoint** (optional Envoy per namespace or service) adds L7 features and emits traces, access logs and request metrics.

Because ztunnel produces only metrics, TinyOlly builds map edges from Istio metrics as well as from traces.

!!! tip "Runnable demo"
    The [istio-demo](https://github.com/stevelerner/istio-demo) repo installs Istio ambient on a local kind cluster, deploys Online Boutique, and has scenarios for waypoint, fault injection, retries and authorization policy.

## What you get on the map

| Feature | How it shows |
|---|---|
| Topology without traces | Edges from `istio_tcp_connections_opened_total` and `istio_requests_total` (`source_kind: metrics`) |
| mTLS posture | Green edges are mutual TLS, orange dashed edges are plaintext; the bar above the map shows `mTLS 92.5% · 3 plaintext · 1 denied` |
| Denied calls | Red thick edge. Counted from HTTP 403, gRPC status 7 (PERMISSION_DENIED) and waypoint local replies |
| Mesh roles | Waypoint (cut box) and gateway (pentagon) node shapes |
| Merged vs Layered | `waypoint.boutique` (trace identity) and `waypoint` (metric identity) merge into one node; untick **Merge proxy and app nodes** to see both |

The same data is available from `GET /api/service-map` and `GET /api/mesh-posture` ([API reference](api.md)) and the `get_service_map` / `get_mesh_posture` MCP tools ([MCP](mcp.md)).

## Getting the data in

1. **Metrics:** scrape ztunnel and the waypoint (Prometheus port `15020`) with an OpenTelemetry Collector `prometheus` receiver and forward the `istio_*` metrics to TinyOlly's OTLP receiver. The demo repo has a ready `mesh-metrics.yaml`.
2. **Traces (optional):** register an OpenTelemetry extension provider in Istio and enable it with a `Telemetry` resource on the waypoint; the app's own spans stitch into the same traces if the app exports to TinyOlly too.
3. Name your services consistently: edges from metrics use Istio's `source_canonical_service` / `destination_canonical_service` labels, so set `OTEL_SERVICE_NAME` in the app to the same name to join metric and trace edges.

## Good to know

- **Namespace merge:** a name like `waypoint.boutique` is merged into `waypoint` only when `boutique` appears as a workload namespace in the mesh metrics.
- **Denial detection is heuristic:** a gRPC call denied by an authorization policy returns HTTP 200 with `grpc-status: 7`, and a waypoint local reply shows up with no upstream workload. TinyOlly treats both as denied. Calls that fail upstream with a response flag (for example `UH`) count as errors, not denials.
- **Plaintext edges** are normal for non-mesh traffic such as apps exporting telemetry to TinyOlly.
