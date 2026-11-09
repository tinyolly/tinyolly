#!/usr/bin/env bash
# Shared preflight: source this from 01-*.sh scripts. Fails fast with a fix hint.
# Usage: source "$(dirname "$0")/../scripts/lib/preflight.sh"   (then call tinyolly_preflight)
tinyolly_preflight() {
  local profile="${COLIMA_PROFILE:-tinyolly}"
  command -v docker >/dev/null || { echo "ERROR: docker CLI missing (brew install docker docker-compose)" >&2; return 1; }
  docker compose version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' plugin missing (brew install docker-compose; see scripts/README.md)" >&2; return 1; }
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker daemon unreachable. Run: ./scripts/colima-up.sh" >&2; return 1
  fi
  local mem_bytes; mem_bytes=$(docker info --format '{{.MemTotal}}')
  if (( mem_bytes < 3500000000 )); then
    echo "WARN: docker VM has <3.5GB RAM; builds may be OOM-killed (COLIMA_MEMORY=...)." >&2
  fi
  echo "preflight OK (context: $(docker context show), arch: $(uname -m), vm mem: $((mem_bytes/1024/1024)) MiB)"
}
