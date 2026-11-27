#!/usr/bin/env bash
# Start the Colima VM used by the TinyOlly scripts.
# Colima home: ${COLIMA_HOME:-~/.colima}. Use an APFS location (HFS+ has no sparse files, so VM disk creation hangs).
# Size follows the Mac's profile (scripts/lib/size.sh; PROFILE=lean|full). COLIMA_CPU / COLIMA_MEMORY (GiB) /
# COLIMA_DISK (GiB) override it. A VM that already exists is not resized.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib/size.sh"

VM="${COLIMA_PROFILE:-tinyolly}"
CPU="${COLIMA_CPU:-$VM_CPU}"
MEMORY="${COLIMA_MEMORY:-$VM_MEM}"
DISK="${COLIMA_DISK:-60}"

for bin in colima docker; do
  command -v "$bin" >/dev/null || { echo "ERROR: '$bin' not found. brew install colima docker kubectl kind helm" >&2; exit 1; }
done

echo "Profile $PROFILE (host ${HOST_GB} GB): VM ${CPU} CPU / ${MEMORY} GB."
if (( MEMORY + 8 > HOST_GB )); then
  echo "WARN: VM memory ${MEMORY}G leaves under 8 GB of ${HOST_GB}G for macOS; expect swapping." >&2
fi

if colima status -p "$VM" >/dev/null 2>&1; then
  echo "Colima profile '$VM' already running."
  cur=$(colima list 2>/dev/null | awk -v p="$VM" '$1==p{print $4" CPU / "$5}')
  echo "  current size: $cur (requested ${CPU} CPU / ${MEMORY}GiB; to resize: colima stop -p $VM, then rerun)"
else
  ARGS=(start -p "$VM" --cpu "$CPU" --memory "$MEMORY" --disk "$DISK")
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
SOCK="unix://${COLIMA_HOME:-$HOME/.colima}/$VM/docker.sock"
if [[ "$(docker context inspect "colima-$VM" --format '{{.Endpoints.docker.Host}}' 2>/dev/null)" != "$SOCK" ]]; then
  docker context update "colima-$VM" --docker "host=$SOCK" >/dev/null && echo "Fixed stale docker context colima-$VM -> $SOCK"
fi
docker context use "colima-$VM" >/dev/null
docker info >/dev/null && echo "OK: docker context colima-$VM is up ($(docker info --format '{{.NCPU}} CPU, {{.MemTotal}} bytes'))"
