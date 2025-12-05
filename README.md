<div align="center">
  <img src="docs/images/tinyollytitle.png" alt="TinyOlly" width="500">
  
  **The World's First Desktop Observability Platform**
</div>

---
## Documentation

Docs are here: [https://tinyolly.github.io/tinyolly/](https://tinyolly.github.io/tinyolly/)  

    

## What is TinyOlly?  

Why send telemetry to a cloud observabilty platform while coding? Why not have one on your desktop?  

TinyOlly is <i>the world's first desktop observability platform</i>: a **lightweight OpenTelemetry-native observability platform** for local development.  
Visualize and correlate logs, metrics, and traces without sending data to the cloud.  

**Key Features:**
- Full OpenTelemetry Protocol (OTLP) support with gRPC and HTTP ingestion
- REST API with OpenAPI documentation
- Service catalog, dependency maps, and distributed tracing
- Works with any OTel Collector distro
- Built with Python (FastAPI), Redis, and JavaScript

**Platform Support:** Tested on Docker Desktop and Minikube Kubernetes (Apple Silicon Mac)

<!-- ## Screenshots

<div align="center">
  <table>
    <tr>
      <td align="center" width="50%">
        <img src="docs/images/traces.png" width="400"><br>
        <em>Distributed traces with service correlation</em>
      </td>
      <td align="center" width="50%">
        <img src="docs/images/tracewaterfall.png" width="400"><br>
        <em>Trace waterfall visualization with span timing</em>
      </td>
    </tr>
    <tr>
      <td align="center" width="50%">
        <img src="docs/images/logs.png" width="400"><br>
        <em>Real-time logs with trace/span linking</em>
      </td>
      <td align="center" width="50%">
        <img src="docs/images/metrics.png" width="400"><br>
        <em>Metrics with type-specific visualizations</em>
      </td>
    </tr>
  </table>
</div> -->
---

## Quick Start

All examples are launched from the repo- clone it first:  
```bash
git clone https://github.com/tinyolly/tinyolly
```  

## Docker Deployment

### 1. Deploy TinyOlly Core (Required)

Start the observability backend (OTel Collector, TinyOlly Receiver, Redis, UI):

```bash
cd docker
./01-start-core.sh
```

**Services:**
- **OTLP Receiver**: `localhost:4343` (gRPC)
- **UI**: `http://localhost:5005`
- **Redis**: `localhost:6579`
- **OTel Collector**: `localhost:4317` (gRPC), `localhost:4318` (HTTP)

**Stop:** `./02-stop-core.sh`

---

### 2. Deploy Demo Apps (Optional)

```bash
cd docker-demo
./01-deploy-demo.sh
```

Two Flask microservices with automatic traffic generation. Wait 30 seconds for telemetry to appear.

**Stop:** `./02-cleanup-demo.sh`

---

### 3. OpenTelemetry Demo (~20 Services - Optional)

Clone and configure the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) to route telemetry to TinyOlly. Edit `src/otel-collector/otelcol-config-extras.yml` to add TinyOlly as an exporter, then deploy with built-in observability tools disabled.

---

### 4. Use TinyOlly with Your Own Apps

Point your OpenTelemetry exporter to:
- **gRPC**: `http://otel-collector:4317`
- **HTTP**: `http://otel-collector:4318`

### 5. Core-Only Deployment (Use Your Own OTel Collector)

```bash
cd docker-core-only
docker compose -f docker-compose-tinyolly-core.yml up -d
```

Deploys TinyOlly without the bundled OTel Collector. Point your collector to `tinyolly-otlp-receiver:4343`.

## Kubernetes Deployment

### 1. Deploy TinyOlly Core

```bash
minikube start
./k8s/01-build-images.sh
./k8s/02-deploy-tinyolly.sh
```

**Access UI:**
```bash
minikube tunnel  # Keep running in separate terminal
```
UI available at: `http://localhost:5002`

**Cleanup:** `./k8s/03-cleanup.sh`

---

### 2. Demo Applications (Optional)

```bash
cd k8s-demo
./01-deploy.sh
```

**Cleanup:** `./02-cleanup.sh`

### 3. Core-Only Deployment (Use Your Own OTel Collector)

```bash
./k8s/01-build-images.sh
cd k8s-core-only
./deploy.sh
```

**Cleanup:** `./cleanup.sh`

---

## Features

### UI
- Auto-refresh every 5 seconds (pausable)
- Export JSON with one click
- Service catalog with RED metrics
- Interactive service dependency map
- Distributed trace waterfall with correlated logs
- Metric cardinality protection with visual warnings


### Service Catalog
- RED metrics (Rate, Errors, Duration) with P50/P95 latencies
- Inline metric visualization
- Sortable columns with persistent filters
- Color-coded error rates

### Service Map
- Auto-detected node types (Client, Server, Database, Messaging)
- Interactive graph with zoom/pan
- Call counts between services
- Real-time topology updates

### Cardinality Protection
- Hard limit of 1000 unique metric names (configurable via `MAX_METRIC_CARDINALITY`)
- Visual warnings at 70% and 90%
- Drops metrics exceeding limit with tracking

---

## REST API & OpenAPI

Full REST API with OpenAPI 3.0 documentation:
- **Swagger UI**: `http://localhost:5005/docs`
- **ReDoc**: `http://localhost:5005/redoc`
- **OpenAPI Spec**: `http://localhost:5005/openapi.json`

Generate clients in any language:
```bash
curl http://localhost:5005/openapi.json > openapi.json
openapi-generator-cli generate -i openapi.json -g python -o ./tinyolly-client
```

All responses return OpenTelemetry-native JSON with full trace/span context.

## Technical Details

### Stack
- **Backend**: FastAPI (async), Redis with ZSTD compression + msgpack
- **Frontend**: Vanilla JavaScript, HTML, CSS
- **Ingestion**: OTLP/gRPC and OTLP/HTTP
- **Storage**: 30-minute TTL, sorted sets indexed by timestamp
- **Correlation**: Native trace/span/log linking

### OTLP Support
- Full OpenTelemetry Protocol compliance
- ResourceSpans, ResourceLogs, ResourceMetrics
- Spanmetrics integration for RED metrics
- No vendor lock-in

---

### Admin Endpoints
- `GET /admin/stats` - Redis memory, cardinality, uptime
- `GET/POST/DELETE /admin/alerts` - Alert management
- `GET /health` - Connectivity status

## Licensing

**BSD 3-Clause License** - Free for individual developers, academic use, and small organizations.

**Commercial use** (50+ employees, production deployments, commercial products) requires a license. Contact info in [`LICENSE`](./LICENSE).

---

<div align="center">
  <p>Built for the OpenTelemetry community</p>
  <p>
    <a href="https://github.com/tinyolly/tinyolly">GitHub</a> •
    <a href="https://github.com/tinyolly/tinyolly/issues">Issues</a>
  </p>
</div>