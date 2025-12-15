#!/bin/bash
set +e

# This script rebuilds the UI image and restarts the K8s pod to pick up changes.

# Point to Minikube's Docker daemon
eval $(minikube docker-env)

echo "Rebuilding TinyOlly UI (Minikube)..."
echo "=================================================="

# Build image (same as in 01-build-images.sh but only for UI)
# Using --no-cache to ensure latest changes are picked up
echo "Building tinyolly-ui:latest..."
docker build --no-cache -t tinyolly-ui:latest \
  -f ../docker/dockerfiles/Dockerfile.tinyolly-ui \
  --build-arg APP_DIR=tinyolly-ui \
  ../docker/

if [ $? -ne 0 ]; then
    echo "✗ Failed to build UI image"
    exit 1
fi

echo ""
echo "Restarting UI Pod..."
# Deleting the pod forces the Deployment to recreate it, picking up the new image (imagePullPolicy: Never uses local image)
kubectl delete pod -l app=tinyolly-ui

echo ""
echo "Waiting for new pod to be ready..."
kubectl wait --for=condition=ready pod -l app=tinyolly-ui --timeout=60s

echo ""
echo "✓ UI Rebuilt and Restarted!"
echo "URL: http://localhost:5002 (via minikube tunnel)"
