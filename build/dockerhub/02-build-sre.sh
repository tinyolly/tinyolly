#!/bin/bash
set -e

# Build the TinyOlly AI SRE Agent image (native arch). Self-contained: its build context is docker/apps/tinyolly-sre.
# Usage: ./02-build-sre.sh [version]
# Example: ./02-build-sre.sh v2.1.0
#
# NOTE: Uses --no-cache for fresh builds. Does NOT push to Docker Hub.
# To push, run: ./03-push-sre.sh [version]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../docker"

# Always use the Colima docker daemon
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

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
echo "TinyOlly AI SRE Agent - Build (No Push)"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo "Platform: $PLATFORM"
echo "Cache: disabled (fresh build)"
echo ""

# Ensure buildx builder exists and is active
echo "Setting up Docker Buildx..."
docker buildx use "$DOCKER_CONTEXT"   # built-in builder for the Colima context (a stale Docker Desktop builder broke this)
echo ""

echo "----------------------------------------"
echo "Building sre..."
echo "----------------------------------------"
docker buildx build --platform $PLATFORM \
  --no-cache \
  -f apps/tinyolly-sre/Dockerfile \
  -t $DOCKER_HUB_ORG/sre:latest \
  -t $DOCKER_HUB_ORG/sre:$VERSION \
  --load apps/tinyolly-sre
echo "✓ Built $DOCKER_HUB_ORG/sre:$VERSION"
echo ""

echo "=========================================="
echo "✓ AI SRE Agent image built locally!"
echo "=========================================="
echo ""
echo "Built image:"
echo "  - $DOCKER_HUB_ORG/sre:$VERSION"
echo ""
echo "Next step - push to Docker Hub:"
echo "  ./03-push-sre.sh $VERSION"
echo ""
