#!/bin/bash
set -e

# Push the TinyOlly AI SRE Agent image to Docker Hub
# Usage: ./03-push-sre.sh [version]
# Example: ./03-push-sre.sh v2.1.0
#
# NOTE: Run ./02-build-sre.sh first

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../../docker"

# Always use the Colima docker daemon
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}

echo "=========================================="
echo "TinyOlly AI SRE Agent - Push to Docker Hub"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo ""

echo "Pushing $DOCKER_HUB_ORG/sre:$VERSION..."
docker push $DOCKER_HUB_ORG/sre:$VERSION
docker push $DOCKER_HUB_ORG/sre:latest
echo "✓ Pushed $DOCKER_HUB_ORG/sre:$VERSION"
echo ""

echo "=========================================="
echo "✓ AI SRE Agent image pushed to Docker Hub!"
echo "=========================================="
echo ""
echo "Published image:"
echo "  - $DOCKER_HUB_ORG/sre:$VERSION"
echo ""
echo "Verify: docker pull $DOCKER_HUB_ORG/sre:$VERSION"
echo ""
