# TinyOlly v3.0.0

**Release Date:** November 2026

**See your Istio ambient mesh in seconds, and ask your AI about it.** v3.0.0 adds service-mesh visibility to TinyOlly, a smarter MCP server that is now always on, and more accurate service metrics.

**Why 3.0:** TinyOlly now covers the service mesh, MCP becomes a built-in always-on service, and service RED numbers are computed differently (see upgrade notes), so dashboards or alerts built on them may shift.

---

## Highlights

- **A service map from mesh metrics alone** — Ambient ztunnel emits no traces, so most tools show an empty map. TinyOlly now builds edges from Istio metrics and merges them with trace edges: install the mesh and the map fills in.

- **Zero-trust at a glance** — Edges show mTLS (green), plaintext (orange, dashed) and denied calls (red, including L4 connections refused by STRICT mTLS), with a one-line posture summary: "mTLS 92%, 3 plaintext, 0 denied". Node shapes mark waypoints and gateways, and a Merged / Layered toggle switches between app view and proxy view.

- **An MCP server that understands the mesh** — New tools: `get_mesh_posture`, `find_denied`, `find_plaintext`, `get_edge`, `get_trace_mesh`, `get_version_split` and `compare_windows`, plus label filters on `query_metric` and a mesh investigation skill. `chart_service_map` is redrawn with cards, a legend and health colors. Ask "what is denied in the mesh?" and get an answer plus a picture. `get_version_split` includes average latency per version.

- **MCP is always on** — It runs as a pod next to TinyOlly on Kubernetes and as a service in Docker Compose, on `http://localhost:8765/mcp`. One URL for every client: Claude Code directly, Claude Desktop through `mcp-remote`.

- **More accurate service metrics** — Rate, errors and latency now count server-side spans only, so proxy and client spans no longer double-count. Edges report real error counts and request rates.

---

## Upgrade notes

- Service RED numbers can drop for services with proxy or client spans. That is the fix, not a regression.
- The UI pod's memory limit is now 2Gi, so large service maps no longer get it OOM-killed.
- `k8s/04-rebuild+deploy-ui.sh` rebuilds the shared `python-base` image first.
- New API: `GET /api/mesh-posture` and `GET /api/service-map?merge=true|false`. Edges gain `source_kind`, `mtls` and `denied_count`; nodes gain `role`.

## Learn more

- [Istio Ambient Mesh guide](../docs/istio.md)
- [MCP server](../docs/mcp.md)
- Try the end-to-end demo: [istio-ambient-demo](https://github.com/stevelerner/istio-ambient-demo) (Istio ambient + Online Boutique + TinyOlly)
