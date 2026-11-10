#!/bin/bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
set +e  # Don't exit on errors

# Trap to prevent terminal exit
trap 'echo "Script interrupted"; exit 0' INT TERM

# Parse arguments
NO_CACHE=""
if [[ "$1" == "--no-cache" ]] || [[ "$1" == "-n" ]]; then
    NO_CACHE="--no-cache"
    echo "Building with --no-cache option"
fi

echo "========================================================"
echo "  TinyOlly - Deploy Demo Apps (LOCAL BUILD)"
echo "========================================================"
echo ""
echo "This builds demo images locally instead of using Docker Hub."
echo "For faster deployment, use ./01-deploy-demo.sh instead."
echo ""

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo "✗ Docker is not installed or not in PATH"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "✗ docker compose is not installed or not in PATH"
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

if ! docker ps 2>/dev/null | grep -q "tinyolly-otlp-receiver"; then
    echo "✗ TinyOlly OTLP Receiver not found"
    echo ""
    echo "Please start TinyOlly core first:"
    echo "  cd ../docker"
    echo "  ./01-start-core.sh"
    echo ""
    exit 1
fi

echo "✓ TinyOlly core is running"
echo ""

# Deploy demo apps
echo "Building and deploying demo applications locally..."
echo ""

# Check if compose file exists
if [ ! -f "docker-compose-demo-local.yml" ]; then
    echo "✗ docker-compose-demo-local.yml not found in current directory"
    echo "Make sure you're running this from the docker-demo/ directory"
    exit 1
fi

docker compose -f docker-compose-demo-local.yml build $NO_CACHE
BUILD_EXIT_CODE=$?

if [ $BUILD_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to build demo apps (exit code: $BUILD_EXIT_CODE)"
    echo "Check the error messages above for details"
    exit 1
fi

docker compose -f docker-compose-demo-local.yml up -d
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "✗ Failed to deploy demo apps (exit code: $EXIT_CODE)"
    echo "Check the error messages above for details"
    exit 1
fi

echo ""
echo "========================================================"
echo "  Demo Apps Deployed!"
echo "========================================================"
echo ""
echo "Demo Frontend:  http://localhost:5001"
echo "TinyOlly UI:    http://localhost:5005"
echo ""
echo "The demo apps will automatically generate traffic."
echo "Watch the TinyOlly UI for traces, logs, and metrics!"
echo ""
echo "To stop demo apps:"
echo "  ./02-cleanup-demo.sh"
echo ""
