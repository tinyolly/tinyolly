---
title: "Docker Deployment"
description: "Start TinyOlly with Docker (core, the OpenTelemetry Demo, your own apps, core-only) and configure OpAMP"
---

# Docker Deployment

<div align="center">
  <a href="../images/full/ui-traces.png"><img src="../images/ui-traces.png" alt="TinyOlly Running on Docker" width="600"></a>
  <p><em>TinyOlly UI showing distributed traces</em></p>
</div>

Run everything from the repo (clone it, or download the current GitHub release archive):
```bash
git clone https://github.com/tinyolly/tinyolly
```

## 1. Deploy TinyOlly Core (Required)

```bash
cd docker
./01-start-core.sh
```

This pulls the images from Docker Hub (`./01-start-core-local.sh` builds them from your checkout) and starts:

- **OTel Collector:** `localhost:4317` (gRPC) and `localhost:4318` (HTTP)
- **OpAMP Server:** `ws://localhost:4320/v1/opamp` (WebSocket), `localhost:4321` (HTTP REST API)
- **TinyOlly UI:** `http://localhost:5005` (empty until you send data), including the **OpenTelemetry Collector + OpAMP Config** tab ([setup](#opamp-configuration-optional))
- **TinyOlly MCP server:** `http://localhost:8765/mcp`, read-only, for AI agents ([set up and connect it](mcp-deploy.md))
- **TinyOlly OTLP Receiver** and its SQLite storage

!!! note
    `01-start-core.sh` starts from a clean slate: it removes the SQLite data volume and the supervisor's cached collector config. To keep data, restart instead:

    ```bash
    docker compose -f docker-compose-tinyolly-core.yml restart
    ```

Stop:
```bash
./02-stop-core.sh
```

## 2. OpenTelemetry Demo (Astronomy Shop)

A 16-service subset of the upstream demo sending to TinyOlly's collector, with failure-injection flags, in about 1.6 GB of VM memory. See [OpenTelemetry Demo](otel-demo.md).

```bash
cd docker-otel-demo
./01-start-otel-demo.sh        # shop at http://localhost:8080
./03-set-flag.sh paymentFailure 50%
./02-stop-otel-demo.sh
```

The [TinyOlly AI SRE Agent](ai-sre.md) watches the shop and investigates faults as they happen: `cd docker && ./05-start-sre.sh --demo`.

## 3. Use TinyOlly with Your Own Apps

Point your app's OpenTelemetry exporter at the collector: from containers `http://otel-collector:4317` (gRPC) or `:4318` (HTTP); from your Mac (Colima forwards the ports) `http://localhost:4317` or `:4318`.

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

## 4. TinyOlly **Core-Only** Deployment: Use Your Own Docker OpenTelemetry Collector

TinyOlly without its collector, for your own collector or direct sends to the receiver:

```bash
cd misc/docker-core-only
./01-start-core.sh
```

It starts the OTLP receiver on `localhost:4343` (gRPC only), the OpAMP server (`ws://localhost:4320/v1/opamp`, `localhost:4321`), the UI (`http://localhost:5005`) and the MCP server (`http://localhost:8765/mcp`, [set up and connect it](mcp-deploy.md)). Point any collector's exporter at `tinyolly-otlp-receiver:4343`, for example:
```yaml
exporters:
  debug:
    verbosity: detailed
  
  otlp:
    endpoint: "tinyolly-otlp-receiver:4343"
    tls:
      insecure: true
    # Batching lives in the exporter's queue; the batch processor is deprecated (removed in collector v0.177.0).
    sending_queue:
      batch:
        enabled: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug, otlp, spanmetrics]
    
    metrics:
      receivers: [otlp,spanmetrics]
      exporters: [debug, otlp]
    
    logs:
      receivers: [otlp]
      exporters: [debug, otlp]
```

Stop:
```bash
./02-stop-core.sh
```

## OpAMP Configuration (Optional)

To manage a collector from the UI's **OpenTelemetry Collector + OpAMP Config** page, add the OpAMP extension:

```yaml
extensions:
  opamp:
    server:
      ws:
        endpoint: ws://localhost:4320/v1/opamp

service:
  extensions: [opamp]
```

A complete example (OTLP receivers, OpAMP, exporter-side batching, spanmetrics) is the default template, `docker/otelcol-configs/config.yaml`.

## Building Images

Deploy scripts pull images from Docker Hub. To build locally or publish, see [Development and testing](development.md#building-and-publishing-images) and [build/README.md](https://github.com/tinyolly/tinyolly/blob/main/build/README.md).
