#!/bin/bash
set +e

# This script rebuilds the demo-frontend image and restarts the K8s pod.

# Point to Minikube's Docker daemon
eval $(minikube docker-env)

# Ensure we are in the script directory so relative paths work
cd "$(dirname "$0")"

echo "Rebuilding Demo Frontend (Minikube)..."
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
echo "Restarting Demo Frontend Pod..."
kubectl delete pod -l app=demo-frontend

echo ""
echo "Waiting for new pod to be ready..."
kubectl wait --for=condition=ready pod -l app=demo-frontend --timeout=60s

echo ""
echo "✓ Demo Frontend Rebuilt and Restarted!"
