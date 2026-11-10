#!/bin/bash
set -e

# Always use the Colima docker daemon
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

# Push TinyOlly demo images to Docker Hub
# Usage: ./push-demo.sh [version]
# Example: ./push-demo.sh v2.1.0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}

echo "=========================================="
echo "TinyOlly Demo - Push to Docker Hub"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo ""

IMAGES=(
  "demo-frontend"
  "demo-backend"
)

for IMAGE in "${IMAGES[@]}"; do
  echo "Pushing $DOCKER_HUB_ORG/$IMAGE:$VERSION..."
  docker push $DOCKER_HUB_ORG/$IMAGE:$VERSION
  docker push $DOCKER_HUB_ORG/$IMAGE:latest
  echo "✓ Pushed $DOCKER_HUB_ORG/$IMAGE:$VERSION"
  echo ""
done

echo "=========================================="
echo "✓ Demo images pushed to Docker Hub!"
echo "=========================================="
echo ""
echo "Published images:"
echo "  - $DOCKER_HUB_ORG/demo-frontend:$VERSION"
echo "  - $DOCKER_HUB_ORG/demo-backend:$VERSION"
echo ""
