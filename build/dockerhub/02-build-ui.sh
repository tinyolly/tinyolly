#!/bin/bash
set -e

# Build TinyOlly UI image only (multi-arch)
# Usage: ./02-build-ui.sh [version]
# Example: ./02-build-ui.sh v2.1.0
#
# NOTE: Uses --no-cache for fresh builds. Does NOT push to Docker Hub.
# To push, run: ./03-push-ui.sh [version]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../docker"

# Always use Docker Desktop daemon, never Minikube's
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH MINIKUBE_ACTIVE_DOCKERD

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
echo "TinyOlly UI - Build (No Push)"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo "Platform: $PLATFORM"
echo "Cache: disabled (fresh build)"
echo ""

# Ensure buildx builder exists and is active
echo "Setting up Docker Buildx..."
docker buildx create --name tinyolly-builder --use 2>/dev/null || docker buildx use tinyolly-builder
docker buildx inspect --bootstrap
echo ""

echo "----------------------------------------"
echo "Building ui..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORM \
  --no-cache \
  -f dockerfiles/Dockerfile.tinyolly-ui \
  --build-arg APP_DIR=tinyolly-ui \
  -t $DOCKER_HUB_ORG/ui:latest \
  -t $DOCKER_HUB_ORG/ui:$VERSION \
  --load .
echo "✓ Built $DOCKER_HUB_ORG/ui:$VERSION"
echo ""

echo "=========================================="
echo "✓ UI image built locally!"
echo "=========================================="
echo ""
echo "Built image:"
echo "  - $DOCKER_HUB_ORG/ui:$VERSION"
echo ""
echo "Next step - push to Docker Hub:"
echo "  ./03-push-ui.sh $VERSION"
echo ""
