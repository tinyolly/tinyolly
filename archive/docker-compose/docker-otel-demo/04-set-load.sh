#!/usr/bin/env bash
# Change the OpenTelemetry Demo's load: recreate only the Locust load generator with N simulated users.
# Usage: ./04-set-load.sh 20      (the TinyOlly AI SRE Agent's quick demo profile uses 20; the demo's default is 3)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
USERS="${1:?usage: $0 <users>}"
[ -d "$DIR/.demo" ] || { echo "Demo not cloned; run ./01-start-otel-demo.sh first." >&2; exit 1; }
export DEMO_VERSION=$(grep '^OTEL_DEMO_VERSION=' "$DIR/../versions.env" | cut -d= -f2 | awk '{print $1}')
export OTEL_COLLECTOR_HOST=host.docker.internal LOCUST_USERS="$USERS" LOCUST_BROWSER_TRAFFIC_ENABLED=false LOCUST_HEADLESS=true
cd "$DIR/.demo"
docker compose -f compose.yaml -p otel-demo up -d --no-deps load-generator
echo "load-generator: $USERS users"
