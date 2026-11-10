#!/usr/bin/env bash
# Stop and remove the OpenTelemetry Demo containers (TinyOlly core keeps running).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -d "$DIR/.demo" ] || { echo "Demo not cloned; nothing to stop."; exit 0; }
VER=$(grep '^OTEL_DEMO_VERSION=' "$DIR/../versions.env" | cut -d= -f2 | awk '{print $1}')
cd "$DIR/.demo"
DEMO_VERSION="$VER" docker compose -f compose.yaml -p otel-demo down --remove-orphans
[ "${1:-}" = "--purge" ] && { cd "$DIR"; rm -rf .demo; echo "Removed local demo clone."; }
true
