#!/bin/bash
# Always use the Colima docker daemon (not Docker Desktop / the default colima VM)
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

# Safety: only operate on the local kind cluster (see scripts/lib/kubectx.sh)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }
set +e

# This script rebuilds the demo-frontend image and restarts the K8s pod.

# Ensure we are in the script directory so relative paths work
cd "$(dirname "$0")"

echo "Rebuilding Demo Frontend (kind)..."
echo "=================================================="

# Build image
echo "Building demo-frontend:latest..."
docker build --no-cache -t demo-frontend:latest \
  -f ../docker-demo/Dockerfile \
  ../docker-demo/

if [ $? -ne 0 ]; then
    echo "✗ Failed to build demo-frontend image"
    exit 1
fi

echo ""
echo "Loading image into kind..."
kind load docker-image demo-frontend:latest --name "${KIND_CLUSTER:-tinyolly}"

echo ""
echo "Restarting Demo Frontend Pod..."
kubectl delete pod -l app=demo-frontend

echo ""
echo "Waiting for new pod to be ready..."
kubectl wait --for=condition=ready pod -l app=demo-frontend --timeout=60s

echo ""
echo "✓ Demo Frontend Rebuilt and Restarted!"
