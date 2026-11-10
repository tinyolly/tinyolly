#!/bin/bash

# Safety: only operate on the local kind cluster (see scripts/lib/kubectx.sh)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }
set +e

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
# This script rebuilds the UI image and restarts the K8s pod to pick up changes.


echo "Rebuilding TinyOlly UI (kind)..."
echo "=================================================="

# Build on Colima docker, then load into the kind cluster (only for UI)
# Using --no-cache to ensure latest changes are picked up
echo "Building tinyolly-ui:latest..."
docker build --no-cache -t tinyolly/ui:latest \
  -f ../docker/dockerfiles/Dockerfile.tinyolly-ui \
  --build-arg APP_DIR=tinyolly-ui \
  ../docker/

if [ $? -ne 0 ]; then
    echo "✗ Failed to build UI image"
    exit 1
fi

echo ""
echo "Loading image into kind..."
if ! kind load docker-image tinyolly/ui:latest --name "${KIND_CLUSTER:-tinyolly}"; then
    echo "✗ kind load failed; not restarting the pod"
    exit 1
fi

echo ""
echo "Restarting UI Pod..."
# Deleting the pod forces the Deployment to recreate it with the newly loaded image (imagePullPolicy: IfNotPresent)
kubectl delete pod -l app=tinyolly-ui

echo ""
echo "Waiting for new pod to be ready..."
kubectl wait --for=condition=ready pod -l app=tinyolly-ui --timeout=60s

echo ""
echo "✓ UI Rebuilt and Restarted!"
echo "URL: http://localhost:5005 (kind port mapping)"
