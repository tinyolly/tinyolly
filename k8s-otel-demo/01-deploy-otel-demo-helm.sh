#!/bin/bash

# Safety: only operate on the local kind cluster (see scripts/lib/kubectx.sh)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }
set -e

# Add OpenTelemetry Helm repository
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts

helm repo update

# Deploy OpenTelemetry Demo configured for TinyOlly
# Chart 0.42.6 == demo app 3.1.0 (keep in sync with OTEL_DEMO_VERSION in versions.env).
# The chart's services send OTLP to the host named OTEL_COLLECTOR_NAME (default "otel-collector"), which in the
# default namespace is TinyOlly's own collector Service, so no endpoint override is needed.
#
# Lean by default, like docker-otel-demo/: skip Kafka and its consumers (accounting, fraud-detection; checkout would
# otherwise wait for Kafka), the AI components (agent, chatbot, mcp), telemetry-docs and the demo's own OpAMP server.
# The load generator's 1500Mi limit is also its request, so it is cut to 512Mi (3 Locust users need far less).
# That leaves about 16 services; the VM needs about 8 GB next to TinyOlly (COLIMA_MEMORY=8 ./scripts/colima-up.sh).
# FULL=1 deploys everything (needs 10 GB+).
LEAN_ARGS=()
if [ "${FULL:-0}" != "1" ]; then
  LEAN_ARGS=(
    --set components.kafka.enabled=false
    --set components.accounting.enabled=false
    --set components.fraud-detection.enabled=false
    --set components.agent.enabled=false
    --set components.chatbot.enabled=false
    --set components.mcp.enabled=false
    --set components.telemetry-docs.enabled=false
    --set components.opamp-server.enabled=false
    --set components.checkout.initContainers=null
    --set components.load-generator.resources.limits.memory=512Mi
    # checkout only skips Kafka when KAFKA_ADDR is empty; with it set and no broker it panics on every order
    --set 'components.checkout.envOverrides[0].name=KAFKA_ADDR'
    --set-string 'components.checkout.envOverrides[0].value='
  )
fi

# Helm 4 refuses to overwrite fields edited with kubectl (for example flags changed in the flagd-config ConfigMap);
# re-running this script should reset them, so force it where the flag exists.
FORCE_ARGS=()
helm upgrade --help 2>/dev/null | grep -q -- --force-conflicts && FORCE_ARGS=(--force-conflicts)

helm upgrade --install my-otel-demo open-telemetry/opentelemetry-demo --version 0.42.6 \
  --set opentelemetry-collector.enabled=false \
  --set jaeger.enabled=false \
  --set grafana.enabled=false \
  --set prometheus.enabled=false \
  --set opensearch.enabled=false \
  "${FORCE_ARGS[@]}" "${LEAN_ARGS[@]}" \
  --set 'components.load-generator.envOverrides[0].name=LOCUST_BROWSER_TRAFFIC_ENABLED' \
  --set-string 'components.load-generator.envOverrides[0].value=false' \
  --set 'components.load-generator.envOverrides[1].name=LOCUST_USERS' \
  --set-string 'components.load-generator.envOverrides[1].value=3'
