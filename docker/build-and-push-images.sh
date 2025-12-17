#!/bin/bash
set -e

# Build and push TinyOlly images to Docker Hub
# Usage: ./build-and-push-images.sh [version]
# Example: ./build-and-push-images.sh v2.0.0

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}
PLATFORMS="linux/amd64,linux/arm64"

echo "=========================================="
echo "TinyOlly Docker Hub Build & Push"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo "Platforms: $PLATFORMS"
echo ""

# Ensure buildx builder exists and is active
echo "Setting up Docker Buildx..."
docker buildx create --name tinyolly-builder --use 2>/dev/null || docker buildx use tinyolly-builder
docker buildx inspect --bootstrap
echo ""

# Build order matters: base image must be built first, then dependent images
echo "Building images in dependency order..."
echo ""

# Image 1: Python base (no dependencies)
echo "----------------------------------------"
echo "Building python-base..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  -f dockerfiles/Dockerfile.tinyolly-python-base \
  -t $DOCKER_HUB_ORG/python-base:latest \
  -t $DOCKER_HUB_ORG/python-base:$VERSION \
  --push .
echo "✓ Pushed $DOCKER_HUB_ORG/python-base:$VERSION"
echo ""

# Image 2: OTLP Receiver (depends on python-base)
echo "----------------------------------------"
echo "Building otlp-receiver..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  -f dockerfiles/Dockerfile.tinyolly-otlp-receiver \
  --build-arg APP_DIR=tinyolly-otlp-receiver \
  -t $DOCKER_HUB_ORG/otlp-receiver:latest \
  -t $DOCKER_HUB_ORG/otlp-receiver:$VERSION \
  --push .
echo "✓ Pushed $DOCKER_HUB_ORG/otlp-receiver:$VERSION"
echo ""

# Image 3: UI (depends on python-base)
echo "----------------------------------------"
echo "Building ui..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  -f dockerfiles/Dockerfile.tinyolly-ui \
  --build-arg APP_DIR=tinyolly-ui \
  -t $DOCKER_HUB_ORG/ui:latest \
  -t $DOCKER_HUB_ORG/ui:$VERSION \
  --push .
echo "✓ Pushed $DOCKER_HUB_ORG/ui:$VERSION"
echo ""

# Image 4: OpAMP Server (independent Go build)
echo "----------------------------------------"
echo "Building opamp-server..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  -f dockerfiles/Dockerfile.tinyolly-opamp-server \
  -t $DOCKER_HUB_ORG/opamp-server:latest \
  -t $DOCKER_HUB_ORG/opamp-server:$VERSION \
  --push .
echo "✓ Pushed $DOCKER_HUB_ORG/opamp-server:$VERSION"
echo ""

# Image 5: OTel Supervisor (independent)
echo "----------------------------------------"
echo "Building otel-supervisor..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORMS \
  -f dockerfiles/Dockerfile.otel-supervisor \
  -t $DOCKER_HUB_ORG/otel-supervisor:latest \
  -t $DOCKER_HUB_ORG/otel-supervisor:$VERSION \
  --push .
echo "✓ Pushed $DOCKER_HUB_ORG/otel-supervisor:$VERSION"
echo ""

echo "=========================================="
echo "✓ All images successfully built and pushed!"
echo "=========================================="
echo ""
echo "Published images:"
echo "  - $DOCKER_HUB_ORG/python-base:$VERSION"
echo "  - $DOCKER_HUB_ORG/otlp-receiver:$VERSION"
echo "  - $DOCKER_HUB_ORG/ui:$VERSION"
echo "  - $DOCKER_HUB_ORG/opamp-server:$VERSION"
echo "  - $DOCKER_HUB_ORG/otel-supervisor:$VERSION"
echo ""
echo "Next steps:"
echo "  1. Verify images: docker pull $DOCKER_HUB_ORG/ui:$VERSION"
echo "  2. Test deployment: cd .. && docker/01-start-core.sh"
echo ""
