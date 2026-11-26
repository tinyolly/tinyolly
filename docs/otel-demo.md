---
title: "OpenTelemetry Demo (Astronomy Shop)"
description: "Run the upstream OpenTelemetry Demo against TinyOlly, copyable setup block, feature flags for failure injection"
---

# OpenTelemetry Demo (Astronomy Shop) with TinyOlly

TinyOlly's demo is the upstream [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) ("Astronomy Shop", pinned to `OTEL_DEMO_VERSION` in `versions.env`): a **16-service subset** (frontend, proxy, cart + Valkey, checkout, payment, shipping, currency, quote, email, ad, recommendation, product catalog + Postgres, image provider, flagd) and a light Locust load generator, all sending OTLP to **TinyOlly's collector**. The demo's own collector, Jaeger, Grafana, Prometheus, OpenSearch and Kafka are not started. It uses about 1.6 GB in the Colima VM, so it runs on an 8 GB Mac.

```bash
# 1. One-time prerequisites (macOS)
brew install colima docker docker-compose docker-buildx docker-credential-helper git
mkdir -p ~/.docker && echo '{"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]}' > ~/.docker/config.json   # merge into an existing file if you have one

# 2. Get TinyOlly and start its Colima VM
git clone https://github.com/tinyolly/tinyolly.git && cd tinyolly
./scripts/colima-up.sh                  # VM 'tinyolly' (Docker context: colima-tinyolly); COLIMA_MEMORY=6 ./scripts/colima-up.sh for more headroom

# 3. Start TinyOlly core (UI :5005, OTLP :4317/:4318)
(cd docker && ./01-start-core.sh)       # use ./01-start-core-local.sh to build from this checkout instead

# 4. Start the OpenTelemetry Demo (first run pulls ~16 images)
cd docker-otel-demo
./01-start-otel-demo.sh                 # clones opentelemetry-demo into .demo/ and starts a 16-service subset

# 5. Use it
open http://localhost:8080              # the shop
open http://localhost:5005              # TinyOlly
./03-set-flag.sh                        # list failure-injection flags
./03-set-flag.sh paymentFailure 50%     # inject failures
./03-set-flag.sh --reset                # turn all flags off

# 6. Stop
./02-stop-otel-demo.sh                  # demo only; add --purge to delete the .demo/ clone
```

## What you will see

The services appear on the map within a minute or two:

[![TinyOlly APM Service Map for the OpenTelemetry Demo](images/ui-otel-service-map.png)](images/full/ui-otel-service-map.png)

The catalog shows rate, errors and latency per service:

[![TinyOlly service catalog for the OpenTelemetry Demo](images/ui-otel-catalog.png)](images/full/ui-otel-catalog.png)

No config edits are needed: the script clones the pinned version and points every service at TinyOlly's collector (`host.docker.internal:4317`). Options: `LOADGEN=0` (no load generator), `LOCUST_USERS=3`, `SERVICES="..."` (custom service list).

With the [MCP server](mcp-deploy.md) connected, an assistant can draw the map, find failing orders and explain them: see [Ask an AI about the OpenTelemetry Demo](otel-demo-ai.md).

## Failure injection with feature flags

`./03-set-flag.sh <flag> <variant>` edits flagd's flag file (flagd hot-reloads it); `./03-set-flag.sh --reset` turns everything off. The *Preset* column names a [collector preset](collector-presets.md) that pairs with the flag. With `paymentFailure` at 50%, `checkout` and `payment` turn red within a couple of minutes:

[![Service catalog with checkout and payment at 15% errors after paymentFailure 50%](images/ui-otel-failure-catalog.png)](images/full/ui-otel-failure-catalog.png)

| Flag | Try | What to look at | Preset |
|---|---|---|---|
| `paymentFailure` | `50%` / `100%` | **Verified.** `payment` and `checkout` error rates; `ERR` traces; checkout returns 422 `PAYMENT_FAILED` | `sampling` keeps every error trace |
| `emitRawPii` | `on` | **Verified.** raw `user.email`, `demo.payment.card_number`, `demo.payment.card_cvv` on spans | `pii-redaction` masks them, hashes `user.id` |
| `cartFailure` | `25%` … `100%` | cart errors, failing add-to-cart | `sampling` |
| `productCatalogFailure` | `on` | errors for one product | `connectors-metrics` (service graph) |
| `imageSlowLoad`, `intlShippingSlowdown` | `5sec` / `10sec` | slow spans, latency percentiles | `sampling` (keeps >500 ms traces) |
| `adHighCpu`, `adManualGc`, `emailMemoryLeak` | `on` / `10x` | resource metrics of the service | `metrics-shaping` |
| `loadGeneratorFloodHomepage` | `on` | request flood; **watch `docker stats` on an 8 GB machine** | `sampling`, `metrics-shaping` |

Rows not marked *Verified* follow the flag descriptions and are not checked against TinyOlly yet. Flags that need Kafka (`kafkaQueueProblems`), the AI agent (`ai*`) or `flagd-ui` are not in the Docker subset.

## Let an AI SRE agent watch it

The [TinyOlly AI SRE Agent](ai-sre.md) opens an incident when a flag breaks something, investigates with the MCP tools, proposes a fix and checks recovery. `cd docker && ./05-start-sre.sh --demo` also flips these flags on a timer and scores the agent against what it injected. Built with a local Ollama model; OpenAI and Claude are optional.

## Notes

* The script pins `DEMO_VERSION` to the git tag: the demo's `.env` default (`latest`, images from `main`) does not match the checked-out compose file.
* The demo is cloned to `docker-otel-demo/.demo/` (git-ignored); `./02-stop-otel-demo.sh --purge` removes it.

## Kubernetes (kind)

The Helm chart (0.42.6, app 3.1.0) is deployed into the `default` namespace next to TinyOlly; its services send OTLP to `otel-collector`, which is TinyOlly's collector Service. Like the Docker version it is **lean by default**: no Kafka or its consumers, no AI components, no telemetry-docs or demo OpAMP server (17 Deployments), and the load generator limited to 512Mi.

```bash
COLIMA_MEMORY=8 ./scripts/colima-up.sh                    # the kind VM needs about 8 GB next to TinyOlly (stop the VM first to resize it)
./k8s-otel-demo/01-deploy-otel-demo-helm.sh               # FULL=1 for every component (needs 10 GB or more)
kubectl get deploy -l app.kubernetes.io/part-of=opentelemetry-demo
open http://localhost:5005                                # TinyOlly
./k8s-otel-demo/02-cleanup-otel-demo-helm.sh
```

**Failure injection on kind:** flagd reads a copy of the `flagd-config` ConfigMap made at pod start, so edit the ConfigMap and restart flagd (as `scripts/test-otel-demo.py --mode k8s` does). The AI SRE Agent's demo shift uses the flagd-ui API instead, which applies at once.

```bash
kubectl edit configmap flagd-config                       # set a flag's "defaultVariant", for example paymentFailure to "50%"
kubectl delete pod -l app.kubernetes.io/component=flagd   # a rolling restart can stall when the node is nearly out of memory
```

## Test it

`scripts/test-otel-demo.py` checks TinyOlly against a running demo (about 12 minutes): the services in the catalog, map edges, multi-service traces, correlated logs, metrics, the MCP tools, `paymentFailure` injection and recovery, and `emitRawPii` with the `pii-redaction` preset applied and reverted through OpAMP.

```bash
scripts/test-otel-demo.py --mode docker      # flags via docker-otel-demo/03-set-flag.sh
scripts/test-otel-demo.py --mode k8s         # flags via the flagd ConfigMap
scripts/test-otel-demo.py --mode docker --skip-flags --skip-preset   # data checks only, about 2 minutes
```

Set `TINYOLLY_UI` and `MCP_URL` for non-default ports. `scripts/status.sh` shows what is running; `scripts/teardown.sh --level demos` removes the demo from Docker and kind ([details](development.md#tear-everything-down)).
