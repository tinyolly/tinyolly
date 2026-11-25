#!/bin/bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
set +e

echo "Rebuilding TinyOlly UI..."
echo "=================================================="

# Rebuild only the tinyolly-ui service
# --no-deps: Don't restart dependent services
# --force-recreate: Ensure container is replaced
# --build: Force image rebuild
docker compose -f docker-compose-tinyolly-core.yml build --no-cache tinyolly-ui
docker compose -f docker-compose-tinyolly-core.yml up -d --no-deps --force-recreate tinyolly-ui

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "✗ Failed to rebuild UI"
    exit 1
fi

echo ""
echo "✓ UI Rebuilt and Restarted!"
echo "URL: http://localhost:5005"
