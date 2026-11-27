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
# The Mac's size profile (scripts/lib/size.sh; PROFILE=lean|full) picks the components, their memory limits
# (lean.yaml / full.yaml next to this script) and the load.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/../scripts/lib/size.sh"
echo "Profile $PROFILE: ${LOCUST_USERS:-$LOAD_USERS} users, browser traffic $BROWSER_TRAFFIC."

# Helm 4 refuses to overwrite fields edited with kubectl (for example flags changed in the flagd-config ConfigMap);
# re-running this script should reset them, so force it where the flag exists.
FORCE_ARGS=()
helm upgrade --help 2>/dev/null | grep -q -- --force-conflicts && FORCE_ARGS=(--force-conflicts)
# The chart's own notes list Jaeger, Grafana and other UIs this install does not run; print our own summary instead.
helm upgrade --help 2>/dev/null | grep -q -- --hide-notes && FORCE_ARGS+=(--hide-notes)

helm upgrade --install my-otel-demo open-telemetry/opentelemetry-demo --version 0.42.6 \
  --set opentelemetry-collector.enabled=false \
  --set jaeger.enabled=false \
  --set grafana.enabled=false \
  --set prometheus.enabled=false \
  --set opensearch.enabled=false \
  "${FORCE_ARGS[@]}" -f "$DIR/$PROFILE.yaml" \
  --set 'components.load-generator.envOverrides[0].name=LOCUST_BROWSER_TRAFFIC_ENABLED' \
  --set-string "components.load-generator.envOverrides[0].value=$BROWSER_TRAFFIC" \
  --set 'components.load-generator.envOverrides[1].name=LOCUST_USERS' \
  --set-string "components.load-generator.envOverrides[1].value=${LOCUST_USERS:-$LOAD_USERS}"

echo ""
echo "OpenTelemetry Demo deployed (release my-otel-demo, sending to TinyOlly's otel-collector)."
echo "  Pods:     kubectl get pods -l app.kubernetes.io/part-of=opentelemetry-demo   (first run pulls images for a few minutes)"
echo "  TinyOlly: http://localhost:5005"
echo "  Shop:     kubectl port-forward svc/frontend-proxy 8080:8080, then http://localhost:8080"
echo "  Remove:   k8s-otel-demo/02-cleanup-otel-demo-helm.sh"
