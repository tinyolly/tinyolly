#!/bin/bash
# Rebuild the MCP server image and restart its pod (use after editing docker/apps/tinyolly-mcp or docs/).
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }
set +e

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1   # repo root: the image also bundles docs/*.md

echo "Building tinyolly/mcp:latest..."
docker build -t tinyolly/mcp:latest -f docker/dockerfiles/Dockerfile.tinyolly-mcp . || { echo "✗ Failed to build MCP image"; exit 1; }

echo "Loading image into kind..."
kind load docker-image tinyolly/mcp:latest --name "${KIND_CLUSTER:-tinyolly}" || { echo "✗ kind load failed"; exit 1; }

kubectl apply -f k8s/tinyolly-mcp.yaml
kubectl rollout restart deploy/tinyolly-mcp
kubectl rollout status deploy/tinyolly-mcp --timeout=90s

echo "✓ MCP server running: http://localhost:8765/mcp (restart your MCP client to reconnect)"
