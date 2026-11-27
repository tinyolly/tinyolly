---
title: "Send Your Own Telemetry"
description: "Point your own app's OpenTelemetry exporter at TinyOlly."
---

# Send Your Own Telemetry

Point your own app's OpenTelemetry exporter at TinyOlly. This requires step 1, [Quickstart](quickstart.md).

## Do this

From your Mac:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   # HTTP
# or
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # gRPC
```

From inside the cluster:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318   # HTTP
# or
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317   # gRPC
```

From another namespace use `otel-collector.default` instead of `otel-collector`.

Also export a service name so it is easy to find:

```bash
export OTEL_SERVICE_NAME=my-app
```

## What you should see

Open http://localhost:5005, send some requests, and look for `my-app` in Traces and Service Catalog.

Next: [Your Own Collector Config](otel-collector.md)
