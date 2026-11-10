#!/bin/bash
set -e

# Always use the Colima docker daemon
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

# Push TinyOlly AI Agent demo image to Docker Hub
# Usage: ./push-ai-demo.sh [version]
# Example: ./push-ai-demo.sh v2.1.0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VERSION=${1:-"latest"}
DOCKER_HUB_ORG=${DOCKER_HUB_ORG:-"tinyolly"}

echo "=========================================="
echo "TinyOlly AI Demo - Push to Docker Hub"
echo "=========================================="
echo "Organization: $DOCKER_HUB_ORG"
echo "Version: $VERSION"
echo ""

echo "Pushing $DOCKER_HUB_ORG/ai-agent-demo:$VERSION..."
docker push $DOCKER_HUB_ORG/ai-agent-demo:$VERSION
docker push $DOCKER_HUB_ORG/ai-agent-demo:latest
echo "✓ Pushed $DOCKER_HUB_ORG/ai-agent-demo:$VERSION"
echo ""

echo "=========================================="
echo "✓ AI demo image pushed to Docker Hub!"
echo "=========================================="
echo ""
echo "Published image:"
echo "  - $DOCKER_HUB_ORG/ai-agent-demo:$VERSION"
echo ""
