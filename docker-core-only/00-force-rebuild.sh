#!/bin/bash
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
echo "Step 2: Removing TinyOlly images..."
docker compose -f docker-compose-tinyolly-core.yml down --rmi all

echo ""
echo "Step 3: Cleaning Docker build cache..."
docker builder prune -f

echo ""
echo "Step 4: Rebuilding from scratch (no cache)..."
docker compose -f docker-compose-tinyolly-core.yml build --no-cache

echo ""
echo "Step 5: Starting services..."
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
echo "TinyOlly UI:    http://localhost:5005"
echo "OTLP Endpoint:  tinyolly-otlp-receiver:4317 (gRPC only, for external collector)"
echo ""

