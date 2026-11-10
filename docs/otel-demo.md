# OpenTelemetry Demo (Astronomy Shop) with TinyOlly

TinyOlly's realistic demo is the upstream [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo)
("Astronomy Shop", pinned to `OTEL_DEMO_VERSION` in `versions.env`). We run a **16-service subset** (frontend, proxy,
cart + Valkey, checkout, payment, shipping, currency, quote, email, ad, recommendation, product catalog + Postgres,
image provider, flagd) plus a light Locust load generator. Everything exports OTLP to **TinyOlly's collector**; the demo's
own collector, Jaeger, Grafana, Prometheus, OpenSearch, Kafka and its consumers are not started.

**Footprint:** ~1.1 GB of containers for demo + TinyOlly, ~1.6 GB used inside the Colima VM (4 GB default), so it runs on an 8 GB Mac.

```bash
./scripts/colima-up.sh
(cd docker && ./01-start-core-local.sh)         # TinyOlly core first (UI :5005, OTLP :4317)
cd docker-otel-demo
./01-start-otel-demo.sh                          # shop on http://localhost:8080 (first run pulls ~16 images)
./03-set-flag.sh                                 # list failure-injection flags
./02-stop-otel-demo.sh                           # stop the demo (TinyOlly keeps running)
```

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
