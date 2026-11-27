---
title: "Kubernetes"
description: "Reference for TinyOlly on kind in Colima: commands, ports, size profiles, troubleshooting, manifests"
---

# Kubernetes

TinyOlly runs on kind (Kubernetes) inside a Colima VM. First time? Follow the [Quick Start](quickstart.md).

## Start

```bash
./scripts/colima-up.sh && ./scripts/kind-up.sh
./k8s/02-deploy-tinyolly.sh
```

## Check

```bash
./scripts/status.sh
kubectl get pods
```

## Rebuild from your checkout

```bash
./build/local/build-core-kind.sh                                     # core images
kubectl rollout restart deploy/tinyolly-ui deploy/tinyolly-otlp-receiver
./k8s/05-rebuild+deploy-mcp.sh                                       # MCP server (also after editing docs/)
./k8s/06-rebuild+deploy-sre.sh --build                               # AI SRE Agent
```

## Remove

```bash
./k8s-otel-demo/02-cleanup-otel-demo-helm.sh   # the demo only
./k8s/03-cleanup.sh                            # TinyOlly
kind delete cluster --name tinyolly            # the cluster
colima stop -p tinyolly                        # the VM
```

## Ports

| What | Address |
|---|---|
| UI ([tour](ui-tour.md)) | [http://localhost:5005](http://localhost:5005) |
| OTLP from your Mac | `localhost:4317` (gRPC), `localhost:4318` (HTTP) |
| OTLP from inside the cluster | `otel-collector:4317`, `otel-collector:4318` |
| MCP server ([connect](mcp-deploy.md)) | `http://localhost:8765/mcp` |
| Demo shop and flag panel | `kubectl port-forward svc/frontend-proxy 8080:8080` |
| AI SRE console | `kubectl port-forward deploy/tinyolly-sre 7173:8080` |

## Size profiles

The scripts pick one from your Mac's RAM. To override, put `PROFILE=lean` or `PROFILE=full` before each script.

| | `lean` (under 48 GB) | `full` (48 GB and up) |
|---|---|---|
| Colima VM | 8 CPU, 12 GB | host cores minus 2, 40 GB |
| Demo load | 15 users | 40 users and browser traffic |
| Demo components | no Kafka, AI components, telemetry-docs or demo OpAMP server | all |

To resize an existing VM: `colima stop -p tinyolly`, then `./scripts/colima-up.sh`. `COLIMA_CPU`, `COLIMA_MEMORY` and `COLIMA_DISK` override the numbers.

!!! warning "`full` can drop telemetry"
    Under `full` load some batches are lost (`database is locked` or timeouts in the `tinyolly-otlp-receiver` log). `full` is not yet verified on a 64 GB Mac.

## Troubleshooting

**Nothing in the UI:** wait a minute or two, then check the pods and logs:

```bash
kubectl get pods
kubectl logs deploy/otel-collector --tail 20
kubectl logs deploy/load-generator --tail 20
```

**Port already in use:** the cluster needs 4317, 4318, 5001, 5005, 8765 and 19291 on your Mac.

**VM creation hangs:** the VM disk is in `${COLIMA_HOME:-~/.colima}`; keep it on an APFS disk.

## Manifests

The manifests are in `k8s/` and pull images from Docker Hub. `02-deploy-tinyolly.sh` is the normal way to apply them; by hand:

```bash
kubectl apply -R -f k8s/otelcol-configs/
kubectl apply -f k8s/tinyolly-sqlite-pvc.yaml -f k8s/tinyolly-otlp-receiver.yaml -f k8s/tinyolly-opamp-server.yaml \
  -f k8s/otel-collector.yaml -f k8s/tinyolly-ui.yaml -f k8s/tinyolly-mcp.yaml
```

Do not use `kubectl apply -f k8s/`: it skips the collector ConfigMaps and also deploys the AI SRE Agent. To publish images, see [Development and testing](development.md#building-and-publishing-images).
