---
title: "OpenTelemetry Demo (Astronomy Shop)"
description: "Run the upstream OpenTelemetry Demo against TinyOlly, copyable setup block, feature flags for failure injection"
---

# OpenTelemetry Demo (Astronomy Shop) with TinyOlly

TinyOlly's realistic demo is the upstream [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo)
("Astronomy Shop", pinned to `OTEL_DEMO_VERSION` in `versions.env`). We run a **16-service subset** (frontend, proxy,
cart + Valkey, checkout, payment, shipping, currency, quote, email, ad, recommendation, product catalog + Postgres,
image provider, flagd) plus a light Locust load generator. Everything exports OTLP to **TinyOlly's collector**; the demo's
own collector, Jaeger, Grafana, Prometheus, OpenSearch, Kafka and its consumers are not started.

**Footprint:** ~1.1 GB of containers for demo + TinyOlly, ~1.6 GB used inside the Colima VM (4 GB default), so it runs on an 8 GB Mac.

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

**No config edits are needed.** The script clones the demo at the pinned version and points every service at TinyOlly's collector (`host.docker.internal:4317`).

Options: `LOADGEN=0` (no load generator), `LOCUST_USERS=3`, `SERVICES="..."` (custom service list).

## Failure injection with feature flags

The demo reads feature flags from flagd. `./03-set-flag.sh <flag> <variant>` edits the flag file (flagd hot-reloads it);
`./03-set-flag.sh --reset` turns everything off. Flags with a *Preset* column pair with a [collector preset](collector-presets.md).

| Flag | Try | What to look at | Preset |
|---|---|---|---|
| `paymentFailure` | `50%` / `100%` | **Verified.** `payment` and `checkout` error rates in Service Catalog; error traces list with `ERR`; checkout returns 422 `PAYMENT_FAILED` | `sampling` keeps every error trace |
| `emitRawPii` | `on` | **Verified.** raw `user.email`, `demo.payment.card_number`, `demo.payment.card_cvv` on spans | `pii-redaction` masks them (`****`), hashes `user.id` |
| `cartFailure` | `25%` … `100%` | cart errors, failing add-to-cart | `sampling` |
| `productCatalogFailure` | `on` | errors for one product, visible in the trace map | `connectors-metrics` (service graph) |
| `imageSlowLoad`, `intlShippingSlowdown` | `5sec` / `10sec` | slow spans, latency percentiles | `sampling` (keeps >500 ms traces) |
| `adHighCpu`, `adManualGc`, `emailMemoryLeak` | `on` / `10x` | resource metrics on the affected service | `metrics-shaping` |
| `loadGeneratorFloodHomepage` | `on` | request flood. **Do not use on an 8 GB machine without watching `docker stats`** | `sampling`, `metrics-shaping` |

Entries not marked *Verified* are expected behaviour from the flag descriptions and have not been checked against TinyOlly yet.
Flags that depend on Kafka (`kafkaQueueProblems`), the AI agent (`ai*`) or `flagd-ui` are not available in this subset.

## Notes

* **Image tags:** the demo's `.env` defaults `DEMO_VERSION=latest` (images from `main`), which does not match the checked-out
  compose file (the newer `recommendation` image has no `nc`, so its healthcheck fails). The script pins `DEMO_VERSION` to the git tag.
* The demo is cloned to `docker-otel-demo/.demo/` (git-ignored); `./02-stop-otel-demo.sh --purge` removes it.
* **Kubernetes:** `k8s-otel-demo/01-deploy-otel-demo-helm.sh` installs chart 0.42.6 (app 3.1.0). The chart also deploys Kafka and its consumers
  (checkout waits for Kafka), so it needs a VM of 6 GB or more. Not tested on kind yet.
