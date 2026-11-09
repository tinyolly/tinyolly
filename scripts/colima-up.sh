#!/usr/bin/env bash
# Start the Colima VM used by all TinyOlly docker/k8s scripts.
# Override sizing with COLIMA_CPU / COLIMA_MEMORY (GiB) / COLIMA_DISK (GiB).
set -euo pipefail

PROFILE="${COLIMA_PROFILE:-tinyolly}"
CPU="${COLIMA_CPU:-4}"
MEMORY="${COLIMA_MEMORY:-4}"
DISK="${COLIMA_DISK:-60}"

for bin in colima docker; do
  command -v "$bin" >/dev/null || { echo "ERROR: '$bin' not found. brew install colima docker docker-compose kubectl kind helm" >&2; exit 1; }
done

HOST_MEM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
if (( MEMORY * 2 > HOST_MEM_GB )); then
  echo "WARN: VM memory ${MEMORY}G is over half of host RAM (${HOST_MEM_GB}G); expect swapping." >&2
fi

if colima status -p "$PROFILE" >/dev/null 2>&1; then
  echo "Colima profile '$PROFILE' already running."
else
  ARGS=(start -p "$PROFILE" --cpu "$CPU" --memory "$MEMORY" --disk "$DISK")
  if [[ "$(uname -m)" == "arm64" ]]; then
    ARGS+=(--vm-type vz --vz-rosetta)
  fi
  colima "${ARGS[@]}"
fi

docker context use "colima-$PROFILE" >/dev/null
docker info >/dev/null && echo "OK: docker context colima-$PROFILE is up ($(docker info --format '{{.NCPU}} CPU, {{.MemTotal}} bytes'))"
