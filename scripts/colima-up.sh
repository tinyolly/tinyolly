#!/usr/bin/env bash
# Start the Colima VM used by all TinyOlly docker/k8s scripts.
# Colima home: ${COLIMA_HOME:-~/.colima}. Use an APFS location (HFS+ has no sparse files, so VM disk creation hangs).
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
  cur=$(colima list 2>/dev/null | awk -v p="$PROFILE" '$1==p{print $4" CPU / "$5}')
  echo "  current size: $cur (requested ${CPU} CPU / ${MEMORY}GiB; to resize: colima stop -p $PROFILE, then rerun)"
else
  ARGS=(start -p "$PROFILE" --cpu "$CPU" --memory "$MEMORY" --disk "$DISK")
  # Colima only shares $HOME by default; bind mounts from a checkout elsewhere
  # (e.g. an external volume) would silently become empty directories.
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
  case "$ROOT" in
    "$HOME"/*) ;;
    *) ARGS+=(--mount "$HOME:r" --mount "$ROOT:w") ;;
  esac
  if [[ "$(uname -m)" == "arm64" ]]; then
    ARGS+=(--vm-type vz --vz-rosetta)
  fi
  colima "${ARGS[@]}"
fi

# Colima writes the docker context only when it starts a VM. If COLIMA_HOME changed (or the VM was
# started elsewhere), the context keeps a stale socket path; repoint it at this VM's real socket.
SOCK="unix://${COLIMA_HOME:-$HOME/.colima}/$PROFILE/docker.sock"
if [[ "$(docker context inspect "colima-$PROFILE" --format '{{.Endpoints.docker.Host}}' 2>/dev/null)" != "$SOCK" ]]; then
  docker context update "colima-$PROFILE" --docker "host=$SOCK" >/dev/null && echo "Fixed stale docker context colima-$PROFILE -> $SOCK"
fi
docker context use "colima-$PROFILE" >/dev/null
docker info >/dev/null && echo "OK: docker context colima-$PROFILE is up ($(docker info --format '{{.NCPU}} CPU, {{.MemTotal}} bytes'))"
