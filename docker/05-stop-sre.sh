#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")"
docker compose -f docker-compose-tinyolly-core-local.yml --profile sre rm -sf tinyolly-sre
