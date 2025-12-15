#!/bin/bash
set +e

echo "Rebuilding TinyOlly UI..."
echo "=================================================="

# Rebuild only the tinyolly-ui service
# --no-deps: Don't restart dependent services (Redis, etc.)
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
