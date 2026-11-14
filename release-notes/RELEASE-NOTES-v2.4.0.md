# TinyOlly v2.4.0

**Release Date:** TBD (unreleased draft)

Istio ambient mesh support on the service map, plus a correctness fix to service RED metrics.

---

## Highlights

- **Service map from mesh metrics** — Edges are derived from Istio metrics (`istio_tcp_connections_opened_total`, `istio_requests_total`) and merged with trace edges, so a mesh with only ztunnel (no traces) still has a map. Edges carry `source_kind` (`traces`, `metrics`, `traces+metrics`).
- **mTLS and policy posture** — Edges report `mtls`; new `GET /api/mesh-posture` summarizes mTLS coverage, plaintext edges and denied calls. The map draws mTLS edges green, plaintext orange dashed, denied red, with a posture summary bar.
- **Mesh roles and Merged / Layered view** — Nodes get a `role` (service, waypoint, gateway, ztunnel) with distinct shapes. `name.namespace` proxy identities merge into the app node; `?merge=false` and a UI checkbox show the layered view.
- **MCP** — `get_service_map` returns roles and the mesh edge fields (and now includes call counts, errors and p95) with `service` / `only` / `limit` filters; new tools `get_mesh_posture`, `find_denied`, `find_plaintext`, `get_edge`, `get_trace_mesh` (mesh time, retries, decoded Envoy flags), `get_version_split` and `compare_windows`; `query_metric` gains `labels` and `group_by`; `chart_service_map` draws mTLS, plaintext and denied edges and waypoint/gateway shapes; new `tinyolly-mesh-investigation` skill.
- **MCP server as a pod** — `k8s/tinyolly-mcp.yaml` (+ `Dockerfile.tinyolly-mcp`, `k8s/05-rebuild+deploy-mcp.sh`) runs the MCP server next to the UI over streamable HTTP; kind maps host port 8765 to it. The core Docker Compose files (`docker/`, `docker-core-only/`) gain a `tinyolly-mcp` service on `127.0.0.1:8765` too. Stdio setup is unchanged.
- **Docs** — New [Istio Ambient Mesh](../docs/istio.md) page.

## Behaviour changes

- **Kind-aware RED:** service rate, error rate and latency now count server-side (and consumer) spans, falling back to all spans for services with none, and the rate uses the real time window instead of a fixed divisor. Numbers for services with proxy or client spans will change (typically lower, no double counting).
- **Edge metrics:** service-graph edges now report a real `error_count` and a `req_rate` computed from the traffic window.
- The UI pod's memory limit is raised from 512Mi to 2Gi (large service-map and trace queries could get it OOM-killed).
- `k8s/04-rebuild+deploy-ui.sh` now rebuilds the `python-base` image first, so backend changes reach the UI image.

## API

- `GET /api/service-map?merge=true|false`
- `GET /api/mesh-posture`
- New edge fields: `source_kind`, `mtls`, `denied_count`; new node field: `role`.
