#!/bin/bash
set -e

# Build TinyOlly demo images locally (multi-arch)
# Usage: ./build-demo.sh [version]
# Example: ./build-demo.sh v2.1.0
#
# NOTE: Uses --no-cache for fresh builds. Does NOT push to Docker Hub.
# To push, run: ./03-push-demo.sh [version]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../docker-demo"

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}

# Detect host architecture (--load only supports single platform)
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)       PLATFORM="linux/amd64" ;;
  arm64|aarch64) PLATFORM="linux/arm64" ;;
  *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

echo "=========================================="
echo "TinyOlly Demo - Build (No Push)"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo "Platform: $PLATFORM"
echo "Cache: disabled (fresh build)"
echo ""

# Ensure buildx builder exists
echo "Setting up Docker Buildx..."
docker buildx create --name tinyolly-builder --use 2>/dev/null || docker buildx use tinyolly-builder
docker buildx inspect --bootstrap
echo ""

# Build demo-frontend
echo "----------------------------------------"
echo "Building demo-frontend..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORM \
  --no-cache \
  -f Dockerfile \
  -t $DOCKER_HUB_ORG/demo-frontend:latest \
  -t $DOCKER_HUB_ORG/demo-frontend:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/demo-frontend:$VERSION"
echo ""

# Build demo-backend
echo "----------------------------------------"
echo "Building demo-backend..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORM \
  --no-cache \
  -f Dockerfile.backend \
  -t $DOCKER_HUB_ORG/demo-backend:latest \
  -t $DOCKER_HUB_ORG/demo-backend:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/demo-backend:$VERSION"
echo ""

echo "=========================================="
echo "✓ Demo images built locally!"
echo "=========================================="
echo ""
echo "Built images:"
echo "  - $DOCKER_HUB_ORG/demo-frontend:$VERSION"
echo "  - $DOCKER_HUB_ORG/demo-backend:$VERSION"
echo ""
echo "Next step - push to Docker Hub:"
echo "  ./03-push-demo.sh $VERSION"
echo ""
