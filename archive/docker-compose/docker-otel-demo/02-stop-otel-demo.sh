#!/usr/bin/env bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
# Stop and remove the OpenTelemetry Demo containers (TinyOlly core keeps running).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -d "$DIR/.demo" ] || { echo "Demo not cloned; nothing to stop."; exit 0; }
VER=$(grep '^OTEL_DEMO_VERSION=' "$DIR/../versions.env" | cut -d= -f2 | awk '{print $1}')
cd "$DIR/.demo"
DEMO_VERSION="$VER" docker compose -f compose.yaml -p otel-demo down --remove-orphans
[ "${1:-}" = "--purge" ] && { cd "$DIR"; rm -rf .demo; echo "Removed local demo clone."; }
true
