#!/bin/bash
set +e  # Don't exit on errors

# Trap to prevent terminal exit
trap 'echo "Script interrupted"; exit 0' INT TERM

echo "========================================================"
echo "  TinyOlly - Deploy eBPF Zero-Code Demo"
echo "========================================================"
echo ""

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo "✗ Docker is not installed or not in PATH"
    exit 1
fi

# Check if TinyOlly core is running
echo "Checking if TinyOlly core is running..."
if ! docker ps 2>/dev/null | grep -q "otel-collector"; then
    echo "✗ OTel Collector not found"
    echo ""
    echo "Please start TinyOlly core first:"
    echo "  cd ../docker"
    echo "  ./01-start-core.sh"
    echo ""
    exit 1
fi

echo "✓ TinyOlly core is running"
echo ""

# Stop any existing containers
echo "Stopping any existing eBPF demo containers..."
docker-compose down 2>/dev/null

# Force rebuild images (no cache) to ensure clean build
echo "Building demo images (force rebuild)..."
docker-compose build --no-cache
BUILD_EXIT_CODE=$?

if [ $BUILD_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to build demo images (exit code: $BUILD_EXIT_CODE)"
    exit 1
fi

echo "Starting services..."
docker-compose up -d
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to deploy eBPF demo (exit code: $EXIT_CODE)"
    echo "Check the error messages above for details"
    exit 1
fi

echo ""
echo "========================================================"
echo "  eBPF Demo Deployed!"
echo "========================================================"
echo ""
echo "Demo Apps (NO tracing SDK - instrumented via eBPF):"
echo "  Frontend: http://localhost:5001 (metrics via OTel SDK)"
echo "  Backend:  http://localhost:5004 (pure Flask, no SDK)"
echo ""
echo "eBPF Agent: Captures traces automatically at kernel level"
echo ""
echo "TinyOlly UI: http://localhost:5005"
echo ""
echo "To stop: ./02-cleanup.sh"
echo ""
