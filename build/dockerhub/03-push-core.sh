#!/bin/bash
set -e

# Push TinyOlly core images to Docker Hub
# Usage: ./push-core.sh [version]
# Example: ./push-core.sh v2.1.0
#
# NOTE: Run ./build-core.sh first, or use --build flag to build and push

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../docker"

# Always use Docker Desktop daemon for pushing
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH MINIKUBE_ACTIVE_DOCKERD

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}

echo "=========================================="
echo "TinyOlly Core - Push to Docker Hub"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo ""

# Verify key dependencies are present in the images before pushing
echo "Verifying images before push..."
for MODULE in aiosqlite zstandard msgpack; do
  if ! docker run --rm $DOCKER_HUB_ORG/ui:latest python3 -c "import $MODULE" 2>/dev/null; then
    echo "✗ Verification failed: '$MODULE' not found in $DOCKER_HUB_ORG/ui:latest"
    echo "  Run ./02-build-core.sh $VERSION first, then retry."
    exit 1
  fi
  echo "  ✓ $MODULE OK"
done
echo ""

# Push all core images
IMAGES=(
  "python-base"
  "otlp-receiver"
  "ui"
  "opamp-server"
  "otel-supervisor"
)

for IMAGE in "${IMAGES[@]}"; do
  echo "Pushing $DOCKER_HUB_ORG/$IMAGE:$VERSION..."
  docker push $DOCKER_HUB_ORG/$IMAGE:$VERSION
  if [ "$VERSION" != "latest" ]; then
    docker push $DOCKER_HUB_ORG/$IMAGE:latest
  fi
  echo "✓ Pushed $DOCKER_HUB_ORG/$IMAGE:$VERSION"
  echo ""
done

echo "=========================================="
echo "✓ All core images pushed to Docker Hub!"
echo "=========================================="
echo ""
echo "Published images:"
echo "  - $DOCKER_HUB_ORG/python-base:$VERSION"
echo "  - $DOCKER_HUB_ORG/otlp-receiver:$VERSION"
echo "  - $DOCKER_HUB_ORG/ui:$VERSION"
echo "  - $DOCKER_HUB_ORG/opamp-server:$VERSION"
echo "  - $DOCKER_HUB_ORG/otel-supervisor:$VERSION"
echo ""
echo "Verify: docker pull $DOCKER_HUB_ORG/ui:$VERSION"
echo ""
