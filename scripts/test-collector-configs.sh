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

# The real image (Dockerfile.otel-supervisor) has a writable /var/lib/otelcol; the plain contrib image does not.
# Mirror that so configs that write there (file exporter, storage extensions) can start. Inside the repo because
# Colima only shares $HOME with containers.
DATA_DIR=$(mktemp -d -p "$PWD" .cfgtest-data.XXXXXX)
chmod 777 "$DATA_DIR"
name="cfgtest-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1; rm -rf "$DATA_DIR"' EXIT INT TERM

fail=0
for f in "${FILES[@]}"; do
  case "$f" in /*) abs="$f" ;; *) abs="$PWD/$f" ;; esac   # accept absolute or repo-relative paths
  if ! out=$(docker run --rm -v "$abs":/c.yaml "$IMG" validate --config /c.yaml 2>&1); then
    echo "FAIL validate  $f"; echo "$out" | tail -5 | sed 's/^/    /'; fail=1; continue
  fi
  docker run -d --name "$name" -v "$abs":/c.yaml -v "$DATA_DIR":/var/lib/otelcol "$IMG" --config /c.yaml >/dev/null
  sleep 6
  logs=$(docker logs "$name" 2>&1)
  docker rm -f "$name" >/dev/null 2>&1
  # Only connection errors to the two backends that do not exist in this test are expected (the OTLP exporter and the
  # OpAMP extension cannot resolve tinyolly-otlp-receiver / tinyolly-opamp-server). Every other error line is a failure,
  # so keep this filter specific: broad words like "export" or "opamp" would hide real config errors.
  bad=$(echo "$logs" | grep -E '"level":"error"|	error	|^Error:|panic|cannot|invalid' | grep -v -E 'tinyolly-otlp-receiver|tinyolly-opamp-server' | head -3)
  if echo "$logs" | grep -q "Everything is ready" && [ -z "$bad" ]; then
    echo "ok             $f"
  else
    echo "FAIL startup   $f"; echo "${bad:-$(echo "$logs" | tail -3)}" | cut -c1-300 | sed 's/^/    /'; fail=1
  fi
done
exit $fail
