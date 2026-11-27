---
title: "Kubernetes"
description: "Reference for TinyOlly on kind in Colima: size profiles, ports, manifests, local builds, cleanup, troubleshooting, UI tour"
---

# Kubernetes

TinyOlly runs on kind (Kubernetes) inside a Colima VM. To get started, follow the [Quick Start](quickstart.md).

## Size profiles

Picked from the Mac's RAM; `PROFILE=lean` or `PROFILE=full` overrides it. Pass the override to each script.

| | `lean` (under 48 GB) | `full` (48 GB and up) |
|---|---|---|
| Colima VM | 8 CPU, 12 GB | host cores minus 2, 40 GB |
| Demo load | 15 users, no browser traffic | 40 users with browser traffic |
| Demo components | without Kafka and its consumers, AI components, telemetry-docs, demo OpAMP server | all |

`COLIMA_CPU`, `COLIMA_MEMORY` and `COLIMA_DISK` override the VM size. An existing VM is not resized: `colima stop -p tinyolly`, then run `./scripts/colima-up.sh` again. The VM disk lives in `${COLIMA_HOME:-~/.colima}`; keep it on APFS.

!!! warning "Known limit of `full`"
    At `full` load some telemetry batches are dropped (`database is locked` and timeouts in the `tinyolly-otlp-receiver` log). `full` has not been verified on a 64 GB Mac.

## Ports

| What | Address |
|---|---|
| UI | `http://localhost:5005` |
| OTLP from your Mac | `localhost:4317` (gRPC), `localhost:4318` (HTTP) |
| OTLP from inside the cluster | `otel-collector:4317`, `otel-collector:4318` |
| MCP server | `http://localhost:8765/mcp` ([connect a client](mcp-deploy.md)) |
| Demo shop | `kubectl port-forward svc/frontend-proxy 8080:8080` |
| AI SRE console | `kubectl port-forward deploy/tinyolly-sre 7173:8080` |

The first four are mapped by `scripts/kind-config.yaml`, so they need no port-forward.

## Manifests and images

The manifests are in `k8s/`; images come from Docker Hub. To apply the manifests yourself instead of the deploy script (not `kubectl apply -f k8s/`: that skips the collector ConfigMaps in `k8s/otelcol-configs/` and also deploys the AI SRE Agent):

```bash
kubectl apply -R -f k8s/otelcol-configs/
kubectl apply -f k8s/tinyolly-sqlite-pvc.yaml -f k8s/tinyolly-otlp-receiver.yaml -f k8s/tinyolly-opamp-server.yaml \
  -f k8s/otel-collector.yaml -f k8s/tinyolly-ui.yaml -f k8s/tinyolly-mcp.yaml
```

## Local builds

```bash
./build/local/build-core-kind.sh      # core images, loaded into kind
./k8s/05-rebuild+deploy-mcp.sh        # MCP server (also after editing docs/)
./k8s/06-rebuild+deploy-sre.sh        # AI SRE Agent
kubectl rollout restart deploy/tinyolly-ui deploy/tinyolly-otlp-receiver
```

To publish images, see [Development and testing](development.md#building-and-publishing-images).

## Cleanup

```bash
./k8s-otel-demo/02-cleanup-otel-demo-helm.sh   # the demo only
./k8s/03-cleanup.sh                            # TinyOlly
kind delete cluster --name tinyolly
colima stop -p tinyolly
```

## Troubleshooting

**No traces, logs or metrics:** wait a minute or two, then:

```bash
kubectl get pods
kubectl logs deploy/otel-collector --tail 20
kubectl logs deploy/load-generator --tail 20
```

**Port conflicts:** the cluster uses 4317, 4318, 5001, 5005 and 8765 on your Mac. Stop whatever else listens there.

## UI tour

Open `http://localhost:5005`.

**Traces:** each trace's span waterfall with its correlated logs; click a span for its full JSON.

<div align="center">
  <a href="../images/full/ui-traces.png"><img src="../images/ui-traces.png" alt="TinyOlly Traces View" width="700"></a>
</div>

**Logs:** linked to their trace and span, filterable by severity.

<div align="center">
  <a href="../images/full/ui-logs.png"><img src="../images/ui-logs.png" alt="Logs View" width="700"></a>
</div>

**Metrics:** every metric with charts and cardinality.

<div align="center">
  <a href="../images/full/ui-metrics.png"><img src="../images/ui-metrics.png" alt="Metrics View" width="700"></a>
</div>

**Service Catalog:** rate, errors and duration per service; click a name to jump to its map node, traces, spans, logs or metrics.

<div align="center">
  <a href="../images/full/ui-otel-catalog.png"><img src="../images/ui-otel-catalog.png" alt="Service Catalog" width="700"></a>
</div>

**Service Map:** dependencies with shape for service type and colour for health (legend above the map); click a node for latency.

<div align="center">
  <a href="../images/full/ui-otel-service-map.png"><img src="../images/ui-otel-service-map.png" alt="Service Map" width="700"></a>
</div>

**OpenTelemetry Collector + OpAMP Config:** view a connected collector's config, apply changes with validation and a diff preview, or apply a [collector preset](collector-presets.md) (sampling, PII redaction, transforms, connectors and more). The collector needs the OpAMP extension (see [OpAMP configuration](otel-collector.md#opamp-configuration-optional)).

<div align="center">
  <a href="../images/full/ui-collector.png"><img src="../images/ui-collector.png" alt="OpAMP Config" width="700"></a>
</div>

