# Collector presets

TinyOlly ships a baseline collector config plus **presets** you can apply from the *OpenTelemetry Collector + OpAMP Config* tab
(or `POST /api/opamp/config`). Each preset is a complete collector config in
`docker/otelcol-configs/templates/` whose first comment line is the blurb shown in the UI.

**Baseline (every config):** `memory_limiter` → `resourcedetection` (env, system) → `batch`; the debug exporter is `basic` verbosity.

| Preset | Components | What you see |
|---|---|---|
| `sampling` | `tail_sampling` (errors, >500 ms, 10 % of the rest), `probabilistic_sampler` (logs 25 %), `forward` + `spanmetrics` | Trace count drops ~90 %; every error trace is kept. RED metrics are computed *before* sampling, so rates stay accurate. |
| `pii-redaction` | `redaction` on traces, logs **and metrics** (emails, card numbers, bearer tokens, `token=` URL secrets, `*password*`/`*secret*`/`*cvv*`/`*card number*` keys), `attributes` (hash `user.id`, delete auth/cookie headers; traces and logs) | `user.email` → `****`, `?token=…` masked, `user.id` hashed, log bodies masked, `redaction.masked.count` added. Card patterns only match real card formats (grouped digits, or contiguous Visa/MC/Amex/Discover), so epoch timestamps and numeric IDs are left alone. |
| `transform-ottl` | `transform`, `filter`, `resource` | `/users/123` → `/users/{id}`, JSON log bodies flattened to attributes, health checks and debug logs dropped, `deployment.environment.name` added. |
| `enrichment` | `resource`, `groupbyattrs` | `service.namespace`, `deployment.environment.name`, `collector.preset` on everything. |
| `metrics-shaping` | `deltatocumulative`, `filter`, `metricstransform`, `interval` | Delta inputs become cumulative, noisy runtime metrics dropped, labels aggregated, 30 s flush. |
| `logs-dedup` | `transform`, `logdedup` | 60 identical logs → 1 record with `dedup_count: 60`. |
| `connectors-metrics` | `spanmetrics` (exemplars on), `servicegraph`, `count`, `signaltometrics` | Extra derived metrics: service graph, span/log counts, span-duration histogram. |
| `connectors-routing` | `routing`, `failover`, `attributes` | Error spans take their own pipeline (`collector.route=errors`); failover to a backup exporter. |
| `prometheus-remote-write` | `prometheusremotewrite` receiver | Accepts Prometheus remote write on `:19291`. |

`templates/examples/incorrect.yaml` is a deliberately broken config for demoing the UI validator; it is not listed as a preset.

## How configs are applied (important)

The OpAMP supervisor **merges** the remote config into the base `config.yaml` (maps are merged by key, lists replaced).
Pipelines are therefore merged *by name*: a preset that only added `traces/foo` would leave the base `traces` pipeline
running alongside it (so, e.g., sampling would be bypassed). Every preset defines its main pipelines as `traces`, `metrics`
and `logs`, and extra pipelines with suffixes (`traces/sampled`). Keep that convention when writing your own.

Remote config is delivered at the agent's next OpAMP check-in, so a new preset can take ~10-30 s to become active
(watch *effective config* on the Collector tab).

## Stability notes (collector-contrib 0.165.0)

Alpha: `filter`, `redaction` (logs/metrics), `logdedup`, `deltatocumulative`, `count`/`signaltometrics`/`routing`/`failover` connectors,
`probabilistic_sampler` (logs). Beta: `tail_sampling`, `transform`, `memory_limiter`, `resourcedetection`, `groupbyattrs`,
`metricstransform`, `cumulativetodelta`. Stable: `k8sattributes`.

## Not included (yet)

* `k8sattributes` (needs RBAC + a Kubernetes cluster) and `geoip` (needs a MaxMind database) — would be a separate Kubernetes preset.
* `cumulativetodelta` and `metricstarttime` are available in the image but not wired into a preset.
* `filelog` receiver (needs file mounts).

## Testing

```bash
./scripts/test-collector-configs.sh        # validate + start every config with the pinned collector image
./scripts/sync-k8s-configs.sh              # regenerate Kubernetes ConfigMaps after editing configs/presets
```
