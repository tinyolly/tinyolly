#!/bin/bash
set +e  # Don't exit on errors

echo "Starting TinyOlly Core - LOCAL BUILD MODE"
echo "=================================================="
echo ""
echo "This script builds images locally instead of using Docker Hub."
echo "For production deployments, use ./01-start-core.sh instead."
echo ""
echo "Starting observability stack:"
echo "  - OpenTelemetry Collector (listening on 4317/4318)"
echo "  - TinyOlly OTLP Receiver"
echo "  - SQLite (embedded DB)"
echo "  - TinyOlly Frontend (web UI)"
echo ""

echo "Building images locally..."
echo ""

# Build the shared Python base image first
# This is required because dependencies use "FROM tinyolly/python-base"
echo "Building shared Python base image..."
docker build -t tinyolly/python-base:latest -f dockerfiles/Dockerfile.tinyolly-python-base .
if [ $? -ne 0 ]; then
    echo "✗ Failed to build shared base image"
    exit 1
fi
echo "✓ Base image built"
echo ""

# This prevents stale remote configs from persisting across restarts
echo "Clearing cached collector config..."
docker volume rm tinyolly-otel-supervisor-data 2>/dev/null || true

# Clear SQLite data from previous runs
# This removes stale traces, metrics, and logs for a clean start
echo "Clearing SQLite data volume..."
docker volume rm tinyolly-db-data 2>/dev/null || true

# Use docker-compose with local build config
# --build forces rebuild of all images
# --force-recreate ensures config file changes are picked up
docker-compose -f docker-compose-tinyolly-core-local.yml up -d --build --force-recreate --remove-orphans 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to start core services (exit code: $EXIT_CODE)"
    echo "Check the error messages above for details"
    exit 1
fi

# Reconnect any demo containers that may have been orphaned by network recreation.
# When the core stack restarts, tinyolly-network gets a new ID; running demo
# containers still reference the old (destroyed) network and lose connectivity.
for container in demo-frontend demo-backend; do
  if docker ps -q --filter "name=^${container}$" | grep -q .; then
    docker network connect tinyolly-network $container 2>/dev/null \
      && echo "✓ Reconnected $container to tinyolly-network" || true
  fi
done

echo ""
echo "Services started!"
echo ""
echo "--------------------------------------"
echo "TinyOlly UI:    http://localhost:5005"
echo "--------------------------------------"
echo "OTLP Endpoint:  localhost:4317 (gRPC) or http://localhost:4318 (HTTP)"
echo ""
echo "Next steps:"
echo "  1. Instrument your app to send OTLP to localhost:4317"
echo "  2. Open TinyOlly UI: open http://localhost:5005"
echo "  3. Stop services:    ./02-stop-core.sh"
echo ""
