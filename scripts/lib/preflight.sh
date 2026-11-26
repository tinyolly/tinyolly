#!/usr/bin/env bash
# Shared preflight: source this from 01-*.sh scripts. Fails fast with a fix hint.
# Usage: source "$(dirname "$0")/../scripts/lib/preflight.sh"   (then call tinyolly_preflight)
tinyolly_preflight() {
  local profile="${COLIMA_PROFILE:-tinyolly}"
  command -v docker >/dev/null || { echo "ERROR: docker CLI missing (brew install docker docker-compose)" >&2; return 1; }
  docker compose version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' plugin missing (brew install docker-compose)" >&2; return 1; }
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker daemon unreachable. Run: ./scripts/colima-up.sh (it also repairs a stale docker context after COLIMA_HOME changes)" >&2; return 1
  fi
  local mem_bytes; mem_bytes=$(docker info --format '{{.MemTotal}}')
  if (( mem_bytes < 3500000000 )); then
    echo "WARN: docker VM has <3.5GB RAM; builds may be OOM-killed (COLIMA_MEMORY=...)." >&2
  fi
  echo "preflight OK (context: $(docker context show), arch: $(uname -m), vm mem: $((mem_bytes/1024/1024)) MiB)"
}

# Fail fast if another container in this Docker VM publishes one of TinyOlly core's host ports (the kind cluster
# maps 4317/4318/5005/8765). TinyOlly's own containers (compose project "docker") are fine: they get re-created.
tinyolly_ports_free() {
  local ports="4317 4318 4320 4321 4343 5005 8765 19291" busy
  busy=$(docker ps --format '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Ports}}' 2>/dev/null | awk -F'|' -v ports="$ports" '
    $2 != "docker" { n = split(ports, p, " "); for (i = 1; i <= n; i++) if ($3 ~ (":" p[i] "->")) print "  " $1 " uses port " p[i] }')
  [ -z "$busy" ] && return 0
  echo "ERROR: TinyOlly core's ports are taken:" >&2
  echo "$busy" >&2
  if echo "$busy" | grep -q -- '-control-plane '; then
    echo "That is the kind cluster (docs/kubernetes.md): run one or the other. Remove it with: scripts/teardown.sh --level cluster" >&2
  fi
  return 1
}
