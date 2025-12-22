# eBPF Zero-Code Tracing Demo

This demo showcases **OpenTelemetry eBPF Instrumentation (OBI)** - automatic trace capture at the kernel level without any code changes to your application.

## What is OBI?

[OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/docs/zero-code/obi/) (formerly Grafana Beyla) uses eBPF to automatically capture HTTP/gRPC traces by inspecting system calls and network traffic at the Linux kernel level.

**Key Benefits:**
- **Zero code changes** - no SDK, no agent, no restarts
- **Language agnostic** - works with Python, Go, Java, Node.js, Rust, C, PHP, and more
- **Protocol-level instrumentation** - captures any HTTP/gRPC traffic

## Quick Start

```bash
# Start TinyOlly core first
cd docker
./01-start-core.sh

# Deploy eBPF demo
cd ../docker-demo-ebpf
./01-deploy-ebpf-demo.sh
```

Access the UI at `http://localhost:5005`

## What's Different from SDK Instrumentation?

### Traces

| Aspect | SDK Instrumentation | eBPF Instrumentation |
|--------|---------------------|----------------------|
| **Span names** | Route names (`GET /hello`, `POST /api/users`) | Generic (`in queue`, `CONNECT`, `HTTP`) |
| **Span attributes** | Rich application context (user IDs, request params) | Network-level only (host, port, method) |
| **Distributed tracing** | Full trace propagation via headers | Limited - eBPF sees connections, not header context |
| **Setup** | Code changes or auto-instrumentation wrapper | Deploy eBPF agent alongside app |

**Example - SDK trace:**
```json
{
  "trace_id": "abc123...",
  "span_name": "GET /process-order",
  "attributes": {
    "http.method": "GET",
    "http.route": "/process-order",
    "http.status_code": 200,
    "order.id": "12345",
    "customer.id": "678"
  }
}
```

**Example - eBPF trace:**
```json
{
  "trace_id": "def456...",
  "span_name": "in queue",
  "attributes": {
    "net.host.name": "ebpf-frontend",
    "net.host.port": 5000
  }
}
```

### Logs

With SDK instrumentation, logs include trace context (`trace_id`, `span_id`) for correlation:

```json
{
  "message": "Processing order 12345",
  "trace_id": "abc123...",
  "span_id": "xyz789..."
}
```

With eBPF instrumentation, **logs have no trace context** because there's no tracing SDK to inject it:

```json
{
  "message": "Processing order 12345",
  "trace_id": "",
  "span_id": ""
}
```

This is expected behavior - eBPF operates at the kernel level and cannot inject context into application logs.

### Metrics

Metrics work the same way in both approaches - they're exported via the OTel SDK regardless of how traces are captured.

## Demo Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    docker-demo-ebpf                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐       ┌──────────────────┐            │
│  │  ebpf-frontend   │──────▶│   ebpf-backend   │            │
│  │                  │       │                  │            │
│  │  OTel SDK:       │       │  NO OTel SDK     │            │
│  │  - Metrics ✓     │       │  - Pure Flask    │            │
│  │  - Logs ✓        │       │                  │            │
│  │  - Traces ✗      │       │                  │            │
│  └──────────────────┘       └──────────────────┘            │
│           │                          │                       │
│           └──────────┬───────────────┘                       │
│                      │                                       │
│                      ▼                                       │
│           ┌──────────────────┐                              │
│           │  otel-ebpf-agent │                              │
│           │                  │                              │
│           │  Captures HTTP   │                              │
│           │  traces via eBPF │                              │
│           │  kernel hooks    │                              │
│           └────────┬─────────┘                              │
│                    │                                        │
└────────────────────┼────────────────────────────────────────┘
                     │
                     ▼
            ┌────────────────┐
            │ otel-collector │
            │                │
            │  Receives:     │
            │  - Traces      │
            │  - Logs        │
            │  - Metrics     │
            └───────┬────────┘
                    │
                    ▼
            ┌────────────────┐
            │    TinyOlly    │
            │                │
            │  http://       │
            │  localhost:5005│
            └────────────────┘
```

## Components

### Frontend (`ebpf-frontend`)
- Flask application with auto-traffic generation
- **Metrics**: Exported via OTel SDK (`OTLPMetricExporter`)
- **Logs**: Exported via OTel SDK (`OTLPLogExporter`)
- **Traces**: None from SDK - captured by eBPF agent

### Backend (`ebpf-backend`)
- Pure Flask application - **no OTel SDK at all**
- Demonstrates that eBPF can trace completely uninstrumented apps
- Logs go to stdout only (not exported to OTel)

### eBPF Agent (`otel-ebpf-agent`)
- Runs with `privileged: true` and `pid: host`
- Monitors port 5000 for HTTP traffic
- Sends traces to OTel Collector

## When to Use eBPF vs SDK

**Use eBPF when:**
- You can't modify application code (legacy apps, third-party binaries)
- You want basic HTTP observability with zero effort
- You're instrumenting many polyglot services quickly

**Use SDK when:**
- You need rich application-level context in traces
- You need log-trace correlation
- You need custom spans for business logic
- You need full distributed tracing with context propagation

**Hybrid approach (this demo):**
- Use eBPF for traces (zero-code)
- Use SDK for metrics and logs (richer data)

## Configuration

The eBPF agent is configured via environment variables in `docker-compose.yml`:

```yaml
otel-ebpf-agent:
  image: docker.io/otel/ebpf-instrument:main
  privileged: true
  pid: host
  environment:
    - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    - OTEL_EBPF_OPEN_PORT=5000
  volumes:
    - /sys/kernel/debug:/sys/kernel/debug:rw
```

Key settings:
- `OTEL_EBPF_OPEN_PORT`: Which port to monitor (5000 = Flask default)
- `privileged: true`: Required for eBPF kernel access
- `pid: host`: Required to see processes in other containers

## Troubleshooting

**No traces appearing?**
- Ensure TinyOlly core is running (`docker ps | grep otel-collector`)
- Check eBPF agent logs: `docker logs otel-ebpf-instrumentation`
- Verify the agent can access `/sys/kernel/debug`

**Traces have wrong service name?**
- OBI discovers service names from process info
- Set `OTEL_EBPF_SERVICE_NAME` for explicit naming

**eBPF agent won't start?**
- Requires Linux kernel 4.4+ with eBPF support
- On macOS, runs inside Docker's Linux VM (should work)
- Check Docker has sufficient privileges

## Learn More

- [OpenTelemetry eBPF Instrumentation Docs](https://opentelemetry.io/docs/zero-code/obi/)
- [OBI GitHub Repository](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation)
- [OBI Docker Setup Guide](https://opentelemetry.io/docs/zero-code/obi/setup/docker/)
