#!/usr/bin/env bash
# Stop the TinyOlly AI SRE Agent (the core stack keeps running). The agent resets all demo flags on exit.
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
cd "$(dirname "${BASH_SOURCE[0]}")"
# Use the compose file the running core was started with, so the core containers are not re-created:
# 01-start-core.sh (Docker Hub images) or 01-start-core-local.sh (built from this checkout).
CORE=docker-compose-tinyolly-core.yml
case "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' tinyolly-ui 2>/dev/null)" in
  *core-local.yml*) CORE=docker-compose-tinyolly-core-local.yml;;
esac
docker compose -f "$CORE" --profile sre rm -sf tinyolly-sre
