#!/bin/bash
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
echo "  TinyOlly - Deploy Demo Apps"
echo "========================================================"
echo ""

# Check if docker is available
if ! command -v docker &> /dev/null; then
    echo "✗ Docker is not installed or not in PATH"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "✗ docker-compose is not installed or not in PATH"
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
echo "Deploying demo applications..."
echo ""

# Check if compose file exists
if [ ! -f "docker-compose-demo.yml" ]; then
    echo "✗ docker-compose-demo.yml not found in current directory"
    echo "Make sure you're running this from the docker-demo/ directory"
    exit 1
fi

docker-compose -f docker-compose-demo.yml up -d
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
echo "Usage:"
echo "  ./01-deploy-demo.sh           # Normal build with cache"
echo "  ./01-deploy-demo.sh --no-cache # Force rebuild without cache"
echo "  ./01-deploy-demo.sh -n         # Short form"
echo ""
echo "To stop demo apps:"
echo "  ./02-cleanup-demo.sh"
echo ""

