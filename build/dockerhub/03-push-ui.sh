#!/bin/bash
set -e

# Push TinyOlly UI image to Docker Hub
# Usage: ./03-push-ui.sh [version]
# Example: ./03-push-ui.sh v2.1.0
#
# NOTE: Run ./02-build-ui.sh first

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../docker"

# Always use Docker Desktop daemon, never Minikube's
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH MINIKUBE_ACTIVE_DOCKERD

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}

echo "=========================================="
echo "TinyOlly UI - Push to Docker Hub"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo ""

echo "Pushing $DOCKER_HUB_ORG/ui:$VERSION..."
docker push $DOCKER_HUB_ORG/ui:$VERSION
docker push $DOCKER_HUB_ORG/ui:latest
echo "✓ Pushed $DOCKER_HUB_ORG/ui:$VERSION"
echo ""

echo "=========================================="
echo "✓ UI image pushed to Docker Hub!"
echo "=========================================="
echo ""
echo "Published image:"
echo "  - $DOCKER_HUB_ORG/ui:$VERSION"
echo ""
echo "Verify: docker pull $DOCKER_HUB_ORG/ui:$VERSION"
echo ""
