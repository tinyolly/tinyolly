#!/bin/bash
set -e

# Build TinyOlly core images locally (multi-arch)
# Usage: ./build-core.sh [version]
# Example: ./build-core.sh v2.1.0
#
# NOTE: Uses --no-cache for fresh builds. Does NOT push to Docker Hub.
# To push, run: ./03-push-core.sh [version]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../docker"

# Always use Docker Desktop daemon, never Minikube's
# (minikube docker-env pollutes the shell and causes images to be built into
#  Minikube instead of the Docker Desktop daemon used by docker push)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH MINIKUBE_ACTIVE_DOCKERD

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}
PLATFORMS="linux/amd64,linux/arm64"

echo "=========================================="
echo "TinyOlly Core - Build (No Push)"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo "Platforms: $PLATFORMS"
echo "Cache: disabled (fresh build)"
echo ""

# Ensure buildx builder exists and is active
echo "Setting up Docker Buildx..."
docker buildx create --name tinyolly-builder --use 2>/dev/null || docker buildx use tinyolly-builder
docker buildx inspect --bootstrap
echo ""

echo "Building images in dependency order..."
echo ""

# Image 1: Python base (no dependencies)
echo "----------------------------------------"
echo "Building python-base..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  --no-cache \
  -f dockerfiles/Dockerfile.tinyolly-python-base \
  -t $DOCKER_HUB_ORG/python-base:latest \
  -t $DOCKER_HUB_ORG/python-base:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/python-base:$VERSION"
echo ""

# Image 2: OTLP Receiver (depends on python-base)
echo "----------------------------------------"
echo "Building otlp-receiver..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  --no-cache \
  -f dockerfiles/Dockerfile.tinyolly-otlp-receiver \
  --build-arg APP_DIR=tinyolly-otlp-receiver \
  -t $DOCKER_HUB_ORG/otlp-receiver:latest \
  -t $DOCKER_HUB_ORG/otlp-receiver:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/otlp-receiver:$VERSION"
echo ""

# Image 3: UI (depends on python-base)
echo "----------------------------------------"
echo "Building ui..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  --no-cache \
  -f dockerfiles/Dockerfile.tinyolly-ui \
  --build-arg APP_DIR=tinyolly-ui \
  -t $DOCKER_HUB_ORG/ui:latest \
  -t $DOCKER_HUB_ORG/ui:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/ui:$VERSION"
echo ""

# Image 4: OpAMP Server (independent Go build)
echo "----------------------------------------"
echo "Building opamp-server..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  --no-cache \
  -f dockerfiles/Dockerfile.tinyolly-opamp-server \
  -t $DOCKER_HUB_ORG/opamp-server:latest \
  -t $DOCKER_HUB_ORG/opamp-server:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/opamp-server:$VERSION"
echo ""

# Image 5: OTel Supervisor (independent)
echo "----------------------------------------"
echo "Building otel-supervisor..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  --no-cache \
  -f dockerfiles/Dockerfile.otel-supervisor \
  -t $DOCKER_HUB_ORG/otel-supervisor:latest \
  -t $DOCKER_HUB_ORG/otel-supervisor:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/otel-supervisor:$VERSION"
echo ""

echo "=========================================="
echo "✓ All core images built locally!"
echo "=========================================="
echo ""
echo "Built images:"
echo "  - $DOCKER_HUB_ORG/python-base:$VERSION"
echo "  - $DOCKER_HUB_ORG/otlp-receiver:$VERSION"
echo "  - $DOCKER_HUB_ORG/ui:$VERSION"
echo "  - $DOCKER_HUB_ORG/opamp-server:$VERSION"
echo "  - $DOCKER_HUB_ORG/otel-supervisor:$VERSION"
echo ""
echo "Next step - push to Docker Hub:"
echo "  ./03-push-core.sh $VERSION"
echo ""
