#!/usr/bin/env bash
# Validate AND start every collector config/template with the pinned collector-contrib image.
# `validate` only checks schema; OTTL statements / regexes are only parsed when the collector starts,
# so each config is also run for a few seconds and must log "Everything is ready" with no errors.
# Usage: scripts/test-collector-configs.sh [config.yaml ...]   (default: all configs + templates, not examples/)
set -uo pipefail
cd "$(dirname "$0")/.."
VER=$(grep '^OTELCOL_VERSION=' versions.env | cut -d= -f2 | awk '{print $1}')
IMG="ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib:$VER"
if [ $# -gt 0 ]; then FILES=("$@"); else FILES=(docker/otelcol-configs/config.yaml docker/otelcol-configs/templates/*.yaml); fi

fail=0
for f in "${FILES[@]}"; do
  if ! out=$(docker run --rm -v "$PWD/$f":/c.yaml "$IMG" validate --config /c.yaml 2>&1); then
    echo "FAIL validate  $f"; echo "$out" | tail -5 | sed 's/^/    /'; fail=1; continue
  fi
  name="cfgtest-$$"
  docker run -d --name "$name" -v "$PWD/$f":/c.yaml "$IMG" --config /c.yaml >/dev/null
  sleep 6
  logs=$(docker logs "$name" 2>&1)
  docker rm -f "$name" >/dev/null 2>&1
  # exporter/OpAMP connection errors are expected (no backend in this test); config/startup errors are not
  bad=$(echo "$logs" | grep -E '"level":"error"|^Error:|panic|cannot|invalid' | grep -v -E 'tinyolly-otlp-receiver|tinyolly-opamp-server|opamp|dial tcp|lookup|export' | head -3)
  if echo "$logs" | grep -q "Everything is ready" && [ -z "$bad" ]; then
    echo "ok             $f"
  else
    echo "FAIL startup   $f"; echo "${bad:-$(echo "$logs" | tail -3)}" | cut -c1-300 | sed 's/^/    /'; fail=1
  fi
done
exit $fail
