#!/usr/bin/env bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
# Start the OpenTelemetry Demo ("Astronomy Shop") sending all telemetry to the running TinyOlly core stack.
#
# Prerequisite: TinyOlly core is up (docker/01-start-core-local.sh, UI on :5005, OTLP on :4317).
# The demo's own collector, Jaeger/Grafana/Prometheus/OpenSearch, Kafka services, flagd-ui and telemetry-docs are NOT started.
# Services send OTLP to host.docker.internal:4317 (TinyOlly's collector).
#
# Options (env): LOADGEN=0       skip the Locust load generator (default: on, 3 users, no headless-browser traffic)
#                LOCUST_USERS=3  simulated users
#                SERVICES="..."  override the service list
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$DIR/.."
source "$ROOT/scripts/lib/preflight.sh"; tinyolly_preflight
VER=$(grep '^OTEL_DEMO_VERSION=' "$ROOT/versions.env" | cut -d= -f2 | awk '{print $1}')
SRC="$DIR/.demo"

if ! docker ps --format '{{.Names}}' | grep -qx otel-collector; then
  echo "ERROR: TinyOlly's otel-collector is not running. Start the core stack first:  (cd docker && ./01-start-core-local.sh)" >&2
  exit 1
fi
if [ ! -d "$SRC/.git" ]; then
  echo "Cloning opentelemetry-demo $VER ..."
  git clone --quiet --depth 1 --branch "$VER" https://github.com/open-telemetry/opentelemetry-demo "$SRC"
fi
CUR=$(git -C "$SRC" describe --tags --exact-match 2>/dev/null || echo unknown)
if [ "$CUR" != "$VER" ]; then
  echo "ERROR: $SRC is at '$CUR' but versions.env wants '$VER'. Remove it and re-run:  rm -rf $SRC" >&2; exit 1
fi

# The demo's .env defaults DEMO_VERSION=latest (images built from main), which does not match this compose file
# (e.g. the newer recommendation image has no 'nc' for the compose healthcheck). Pin the image tag to the git tag.
export DEMO_VERSION="$VER"
export OTEL_COLLECTOR_HOST=host.docker.internal
export LOCUST_USERS="${LOCUST_USERS:-3}"
export LOCUST_BROWSER_TRAFFIC_ENABLED=false
export LOCUST_HEADLESS=true

SERVICES="${SERVICES:-flagd valkey-cart astronomy-db ad cart currency image-provider product-catalog quote email payment shipping checkout recommendation frontend frontend-proxy}"
[ "${LOADGEN:-1}" = "1" ] && SERVICES="$SERVICES load-generator"

cd "$SRC"
# --no-deps: do not pull in the demo's own otel-collector (TinyOlly's collector replaces it)
docker compose -f compose.yaml -p otel-demo up -d --no-deps $SERVICES

echo
echo "-----------------------------------------------------------"
echo "Shop:        http://localhost:8080        (Astronomy Shop)"
echo "TinyOlly UI: http://localhost:5005"
echo "Failure injection: ./03-set-flag.sh paymentFailure 50%   (see docs/otel-demo.md)"
echo "Stop:        ./02-stop-otel-demo.sh"
echo "-----------------------------------------------------------"
