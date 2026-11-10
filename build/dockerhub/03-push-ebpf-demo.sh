#!/bin/bash
set -e

# Always use the Colima docker daemon
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

# Push TinyOlly eBPF demo images to Docker Hub
# Usage: ./push-ebpf-demo.sh [version]
# Example: ./push-ebpf-demo.sh v2.1.0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}

echo "=========================================="
echo "TinyOlly eBPF Demo - Push to Docker Hub"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo ""

IMAGES=(
  "ebpf-frontend"
  "ebpf-backend"
)

for IMAGE in "${IMAGES[@]}"; do
  echo "Pushing $DOCKER_HUB_ORG/$IMAGE:$VERSION..."
  docker push $DOCKER_HUB_ORG/$IMAGE:$VERSION
  docker push $DOCKER_HUB_ORG/$IMAGE:latest
  echo "✓ Pushed $DOCKER_HUB_ORG/$IMAGE:$VERSION"
  echo ""
done

echo "=========================================="
echo "✓ eBPF demo images pushed to Docker Hub!"
echo "=========================================="
echo ""
echo "Published images:"
echo "  - $DOCKER_HUB_ORG/ebpf-frontend:$VERSION"
echo "  - $DOCKER_HUB_ORG/ebpf-backend:$VERSION"
echo ""
