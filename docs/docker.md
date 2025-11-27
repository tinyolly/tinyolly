# Docker Deployment

All examples are launched from the repo - clone it first:  
```bash
git clone https://github.com/tinyolly/tinyolly
```  

## 1. Deploy TinyOlly Core (Required)

Start the observability backend (OTel Collector, TinyOlly Receiver, Redis, UI):

```bash
cd docker
./01-start-core.sh
```

This starts:
- **OTel Collector**: Listening on `localhost:4317` (gRPC) and `localhost:4318` (HTTP)  
- **TinyOlly UI**: `http://localhost:5005`  
- **TinyOlly OTLP Receiver and its Redis storage**: OTLP observability back end and storage  
- Rebuilds images if code changes are detected  

**Open the UI:** `http://localhost:5005` (empty until you send data)

**Stop core services:**
```bash
./02-stop-core.sh
```

---

## 2. Deploy Demo Apps (Optional)

Deploy two Flask microservices with automatic traffic generation:

```bash
cd docker-demo
./01-deploy-demo.sh
```

Wait 30 seconds. **The demo apps automatically generate traffic** - traces, logs, and metrics will appear in the UI!

**Stop demo apps:**
```bash
./02-cleanup-demo.sh
```

This leaves TinyOlly core running. To stop everything:
```bash
cd docker
./02-stop-core.sh
```

---

## 3. OpenTelemetry Demo (~20 Services - Optional)

**Prerequisites:** Clone the OpenTelemetry Demo first:
```bash
git clone https://github.com/open-telemetry/opentelemetry-demo
cd opentelemetry-demo
```

**Configure:** Edit `src/otel-collector/otelcol-config-extras.yml`:
```yaml
exporters:
  otlphttp/tinyolly:
    endpoint: http://otel-collector:4318

service:
  pipelines:
    traces:
      exporters: [spanmetrics, otlphttp/tinyolly]
```

**Deploy:**
```bash
export OTEL_COLLECTOR_HOST=host.docker.internal
docker compose up \
  --scale otel-collector=0 \
  --scale prometheus=0 \
  --scale grafana=0 \
  --scale jaeger=0 \
  --scale opensearch=0 \
  --force-recreate \
  --remove-orphans \
  --detach
```

**Stop:**
```bash
docker compose down
```

!!! note
    This disables the demo's built-in collector, Jaeger, OpenSearch, Grafana, and Prometheus. All telemetry routes to Otel Collector -> TinyOlly.

---

## 4. Use TinyOlly with Your Own Apps

After deploying TinyOlly core (step 1 above), instrument your application to send telemetry:

**For apps running in Docker containers:**  
Point your OpenTelemetry exporter to:  
- **gRPC**: `http://otel-collector:4317`  
- **HTTP**: `http://otel-collector:4318`  

**For apps running on your host machine (outside Docker):**  
Docker Desktop automatically exposes container ports to `localhost`. Point your OpenTelemetry exporter to:  
- **gRPC**: `http://localhost:4317`  
- **HTTP**: `http://localhost:4318`  

**Example environment variables:**
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

The Otel Collector will forward everything to TinyOlly's OTLP receiver, which process telemetry and stores it in Redis in OTEL format for the backend and UI to access.
