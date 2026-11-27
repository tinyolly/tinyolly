#!/bin/bash
# Rebuild and (re)start the Docker Compose stack next to the kind cluster, on shifted host ports
# (UI 5105, MCP 8865, OTLP 4417/4418; see docker/docker-compose.altports.yml). Uses the second Colima VM ("default").
#   scripts/docker-alt.sh            # rebuild everything and recreate
#   scripts/docker-alt.sh tinyolly-ui tinyolly-mcp   # only these services
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../docker"
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima}"
# The shared tinyolly_common package ships in the python-base image: rebuild it first or backend changes do not reach the apps.
docker build -q -t tinyolly/python-base:latest -f dockerfiles/Dockerfile.tinyolly-python-base .
docker compose -f docker-compose-tinyolly-core-local.yml -f docker-compose.altports.yml up -d --build "$@"
