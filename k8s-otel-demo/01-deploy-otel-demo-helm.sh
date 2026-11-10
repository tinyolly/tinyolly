#!/bin/bash
set -e

# Add OpenTelemetry Helm repository
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts

helm repo update

# Deploy OpenTelemetry Demo configured for TinyOlly
# Chart 0.42.6 == demo app 3.1.0 (keep in sync with OTEL_DEMO_VERSION in versions.env).
# NOTE: the chart still deploys Kafka/accounting/fraud-detection (checkout waits for Kafka), so this needs a much
# bigger VM (>= 6 GB) than docker-otel-demo/, which runs the 16-service subset in ~1.5 GB. Not tested on kind yet.
helm upgrade --install my-otel-demo open-telemetry/opentelemetry-demo --version 0.42.6 \\
  --set opentelemetry-collector.enabled=false \
  --set jaeger.enabled=false \
  --set grafana.enabled=false \
  --set prometheus.enabled=false \
  --set opensearch.enabled=false \
  --set opentelemetry-collector.config.exporters.otlphttp/tinyolly.endpoint="http://otel-collector.default.svc.cluster.local:4318" \
  --set 'components.load-generator.envOverrides[0].name=LOCUST_BROWSER_TRAFFIC_ENABLED' \
  --set-string 'components.load-generator.envOverrides[0].value=false' \
  --set 'components.load-generator.envOverrides[1].name=LOCUST_USERS' \
  --set-string 'components.load-generator.envOverrides[1].value=3'
