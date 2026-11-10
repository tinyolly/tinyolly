#!/bin/bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
set +e  # Don't exit on errors

echo "TinyOlly Force Rebuild (Clean Cache) - No OTel Collector"
echo "=================================================="
echo ""
echo "This will:"
echo "  1. Stop all running containers"
echo "  2. Remove all images"
echo "  3. Clear Docker build cache"
echo "  4. Rebuild everything from scratch"
echo ""
read -p "Are you sure you want to continue? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Step 1: Stopping containers..."
docker compose -f docker-compose-tinyolly-core.yml down

echo ""
echo "Step 2: Clearing SQLite data volume..."
docker volume rm tinyolly-db-data 2>/dev/null || true

echo ""
echo "Step 3: Clearing cached collector config..."
docker volume rm tinyolly-otel-supervisor-data 2>/dev/null || true

echo ""
echo "Step 4: Removing TinyOlly images..."
docker compose -f docker-compose-tinyolly-core.yml down --rmi all

echo ""
echo "Step 5: Cleaning Docker build cache..."
docker builder prune -f

echo ""
echo "Step 6: Rebuilding from scratch (no cache)..."
docker compose -f docker-compose-tinyolly-core.yml build --no-cache

echo ""
echo "Step 7: Starting services..."
docker compose -f docker-compose-tinyolly-core.yml up -d

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to start services (exit code: $EXIT_CODE)"
    echo "Check the error messages above for details"
    exit 1
fi

echo ""
echo "✓ Force rebuild complete!"
echo ""
echo "TinyOlly UI:       http://localhost:5005"
echo "OTLP Endpoint:     localhost:4343 (gRPC only, for external collector)"
echo "OpAMP WebSocket:   ws://localhost:4320/v1/opamp (for external collector config management)"
echo ""

