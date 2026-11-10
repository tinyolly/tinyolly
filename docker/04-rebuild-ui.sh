#!/bin/bash
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
set +e  # Don't exit on errors

echo "========================================================"
echo "  TinyOlly - Rebuild UI Only"
echo "========================================================"
echo ""

# Rebuild and restart only the tinyolly-ui service
# Use local compose file for building (has build context defined)
echo "Rebuilding tinyolly-ui..."
docker compose -f docker-compose-tinyolly-core-local.yml build tinyolly-ui
BUILD_EXIT_CODE=$?

if [ $BUILD_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to build tinyolly-ui (exit code: $BUILD_EXIT_CODE)"
    exit 1
fi

echo ""
echo "Restarting tinyolly-ui..."
docker compose -f docker-compose-tinyolly-core-local.yml up -d --no-deps --force-recreate tinyolly-ui
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to restart tinyolly-ui (exit code: $EXIT_CODE)"
    exit 1
fi

echo ""
echo "✓ TinyOlly UI rebuilt and restarted"
echo ""
echo "TinyOlly UI: http://localhost:5005"
echo ""
