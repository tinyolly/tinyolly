---
name: tinyolly-troubleshoot-stack
description: Use when TinyOlly itself seems broken or empty: tinyolly MCP tools say they cannot reach it, the UI shows no data, ports conflict, the collector is not connected, or the user asks how to set up or configure TinyOlly.
---

# Troubleshooting the TinyOlly stack (Colima / kind)

For "how do I set up / configure X" questions, answer from the docs: `search_docs("<topic>")` then `read_doc(name, section)`. Do not guess commands; the docs are verified against the scripts.

## Symptom → check

| Symptom | Check |
|---|---|
| Tool error "Cannot reach TinyOlly at http://localhost:5005" | TinyOlly is down. `colima list`; start with `./scripts/colima-up.sh && ./scripts/kind-up.sh`, then `./k8s/02-deploy-tinyolly.sh`; check `kubectl get pods`. |
| UI loads but no services/traces | Nothing is sending. Confirm the app exports to `localhost:4318` (HTTP) or `4317` (gRPC) and that the collector is up: `kubectl get pods`. Wait ~30 s after starting demos. |
| Data vanished | Retention is 30 minutes by default and `k8s/03-cleanup.sh` removes the data volume. |
| Port already in use (4317/4318/5005) | Stop whatever else listens there; check other Colima VMs too (`colima list`). |
| `kubectl` shows the wrong cluster | TinyOlly's context is `kind-tinyolly`: `kubectl config use-context kind-tinyolly`. |
| Collector config change not applied | Config is in `docker/otelcol-configs/config.yaml`; remote changes via the UI arrive at the next OpAMP check-in (10-30 s). For Kubernetes run `scripts/sync-k8s-configs.sh` first. |

## Verifying with the MCP tools

`list_services` returning rows means ingestion works. `list_metrics(limit=5)` confirms metrics. If only `tinyolly-*` services appear, TinyOlly is receiving its own telemetry but no application is sending.

## Report

State what you checked, what you found, and the exact command to fix it. Run commands only if the user asks; otherwise show them.
