---
title: "eBPF Zero-Code Tracing Demo"
description: "OpenTelemetry eBPF instrumentation (OBI) demo: what it captures versus SDK tracing, Docker and Kubernetes setup, troubleshooting"
---

# eBPF Zero-Code Tracing Demo

This demo showcases **OpenTelemetry eBPF Instrumentation (OBI)** - automatic trace capture at the kernel level without any code changes to your application.

## What is OBI?

[OpenTelemetry eBPF Instrumentation](https://opentelemetry.io/docs/zero-code/obi/) (formerly Grafana Beyla) uses eBPF to automatically capture HTTP/gRPC traces by inspecting system calls and network traffic at the Linux kernel level.

**Key Benefits:**
- **Zero code changes** - no SDK, no agent, no restarts
- **Language agnostic** - works with Python, Go, Java, Node.js, Rust, C, PHP, and more
- **Protocol-level instrumentation** - captures any HTTP/gRPC traffic

## Quick Start

### Docker

```bash
# Start TinyOlly core first
cd docker
./01-start-core.sh

# Deploy eBPF demo (pulls pre-built images from Docker Hub)
cd ../docker-demo-ebpf
./01-deploy-ebpf-demo.sh
```

Access the UI at `http://localhost:5005`

### Kubernetes

```bash
# Start TinyOlly core first
./scripts/colima-up.sh && ./scripts/kind-up.sh
./k8s/02-deploy-tinyolly.sh

# Deploy eBPF demo (pulls pre-built images from Docker Hub)
cd k8s-demo-ebpf
./02-deploy.sh
```

Access the UI at `http://localhost:5005` (kind port mapping)

### Docker Hub Images

The eBPF demo uses pre-built images from Docker Hub:
- `tinyolly/ebpf-frontend:latest` - Frontend with OTel SDK for metrics/logs
- `tinyolly/ebpf-backend:latest` - Pure Flask backend (no OTel SDK)

For local development, use the build scripts in each demo folder.

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

### Docker

The eBPF agent is configured via environment variables in `docker-compose.yml`:

```yaml
otel-ebpf-agent:
  image: docker.io/otel/ebpf-instrument:v1.0.0
  privileged: true
  pid: host
  environment:
    - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
    - OTEL_EBPF_OPEN_PORT=5000
  volumes:
    - /sys/kernel/debug:/sys/kernel/debug:rw
```

### Kubernetes

In Kubernetes, the eBPF agent runs as a DaemonSet to instrument all pods on each node:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: otel-ebpf-agent
spec:
  template:
    spec:
      hostPID: true
      containers:
      - name: ebpf-agent
        image: docker.io/otel/ebpf-instrument:v1.0.0
        securityContext:
          privileged: true
        env:
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: "http://otel-collector:4317"
        - name: OTEL_EBPF_OPEN_PORT
          value: "5000"
        volumeMounts:
        - name: sys-kernel-debug
          mountPath: /sys/kernel/debug
      volumes:
      - name: sys-kernel-debug
        hostPath:
          path: /sys/kernel/debug
```

### Key Settings

- `OTEL_EBPF_OPEN_PORT`: Which port to monitor (5000 = Flask default)
- `privileged: true`: Required for eBPF kernel access
- `hostPID: true` / `pid: host`: Required to see processes in other containers/pods

## Troubleshooting

**No traces appearing?**
- Ensure TinyOlly core is running (`docker ps | grep otel-collector`)
- Check eBPF agent logs: `docker logs otel-ebpf-instrumentation` (run against the `colima-tinyolly` context: `DOCKER_CONTEXT=colima-tinyolly docker logs ...`)
- Verify the agent can access `/sys/kernel/debug`

**Traces have wrong service name?**
- OBI discovers service names from process info
- Set `OTEL_EBPF_SERVICE_NAME` for explicit naming

**eBPF agent won't start?**
- Requires Linux kernel 4.4+ with eBPF support
- On macOS it runs inside the Colima Linux VM. This demo has not been verified on Colima's default `vz` VM type; if the agent fails to start, check its logs and whether the VM kernel exposes `/sys/kernel/debug`
- The agent runs privileged with the host PID namespace (required for eBPF)

## Learn More

- [OpenTelemetry eBPF Instrumentation Docs](https://opentelemetry.io/docs/zero-code/obi/)
- [OBI GitHub Repository](https://github.com/open-telemetry/opentelemetry-ebpf-instrumentation)
- [OBI Docker Setup Guide](https://opentelemetry.io/docs/zero-code/obi/setup/docker/)
