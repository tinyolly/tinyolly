# Technical Details

## Architecture

<div align="center">
  <img src="../images/architecture.png" alt="TinyOlly Architecture" width="700">
</div>

---

## Data Storage

- **Format**: Full OpenTelemetry (OTEL) format for traces, logs, and metrics  
- **SQLite**: All telemetry stored in an embedded SQLite database (compressed with ZSTD + msgpack)  
- **WAL Mode**: Write-Ahead Logging for concurrent reads during writes  
- **Retention**: Records expire after 30 minutes by default (`SQLITE_TTL_SECONDS`), and the database is also capped at 256 MB (`MAX_DB_SIZE_MB`); when full, the oldest records are evicted first  
- **Correlation**: Native trace-metric-log correlation via trace/span IDs  
- **Cardinality Protection**: Prevents metric explosion  
- **Ephemeral by Design**: Designed for local development — data persists across restarts until it expires or storage fills up  

---

## OTLP Compatibility

TinyOlly is **fully OpenTelemetry-native**:  
- **Ingestion**: Accepts OTLP/gRPC (primary) and OTLP/HTTP  
- **Storage**: Stores traces, logs, and metrics in full OTEL format with resources, scopes, and attributes  
- **Correlation**: Native support for trace/span ID correlation across all telemetry types  
- **REST API**: Exposes OTEL-formatted JSON for programmatic access
- **Control Plane**: OpenTelemetry Collector OpAmp for dynamic configuration  

---

## UI Features

- **Trace Waterfall**: Distributed trace visualization with automatic filtering of noisy ASGI sub-spans (http send/receive)  
- **Trace Map**: Per-trace service dependency graph rendered above the waterfall using Cytoscape.js. Detects inferred external clients from orphan parent span IDs (e.g., test clients that propagate trace context but don't export spans)  
- **Deep Linking**: Shareable URLs that open directly to a specific trace detail view (`?tab=traces&traceId=...`), span search (`?tab=spans&spanId=...`), or filtered tab (`?tab=logs&search=...`). "Copy Link" buttons in trace and span detail views generate these URLs  
- **Click-to-Copy IDs**: Trace and span IDs are copyable with a single click throughout the UI  
- **Correlated Logs**: Trace detail view shows correlated logs inline — click any log row to navigate to the Logs tab filtered by trace ID  
- **Cross-Tab Navigation**: Click trace/span IDs in logs to jump to the corresponding trace or span view  
- **Service Catalog**: RED metrics; clicking a service name opens a menu (Service map, Traces, Spans, Logs, Metrics) filtered to that service  
- **Service Map**: Cytoscape.js dependency graph laid out left-to-right (dagre), sized to always fit the window. Shape = service type (server, client, external, database, messaging, isolated), color = health (blue healthy, amber some errors, red >5% errors). Isolated services sit in a grid to the right; an option hides TinyOlly's own services. Selecting a node shows P50/P95/P99 latency and rate with a link back to the catalog  
- **Smart Auto-Refresh**: 5-second polling pauses automatically when a search filter is active, preventing result disruption  
- **Scrollable Lists**: Trace, span, and log lists support scrolling with sticky headers for large datasets

---

## MCP Server

`docker/apps/tinyolly-mcp` is a read-only MCP server over the REST API (traces, spans, logs, metrics, service catalog/map). Every response is size-bounded; large traces are summarized and paged. See the [MCP guide](mcp.md).

---

## Testing

Everything runs locally (no CI): `./scripts/test-all.sh` runs the unit suites (storage library, UI/API, OTLP receiver, MCP server, frontend JS, OpAMP Go server, collector configs, kubectl-context guard). `--stack` adds an end-to-end run against the live stack (88 checks including every collector preset) and `--kind` adds a Kubernetes smoke test on kind. See the [development notes](development.md).
