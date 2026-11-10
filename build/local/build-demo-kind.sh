#!/bin/bash
set -e

# Build TinyOlly demo images locally via Colima docker + kind load
# Usage: ./build-demo-kind.sh
#
# NOTE: Uses --no-cache for fresh builds

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="$SCRIPT_DIR/../../docker-demo"

echo "=========================================="
echo "TinyOlly Demo - Local kind Build"
echo "=========================================="
echo ""

# Build on the Colima docker daemon, then load into the kind cluster
KIND_CLUSTER="${KIND_CLUSTER:-tinyolly}"
command -v kind >/dev/null || { echo "kind not found (brew install kind)"; exit 1; }
kind get clusters | grep -qx "$KIND_CLUSTER" || { echo "kind cluster '$KIND_CLUSTER' not found: run scripts/kind-up.sh"; exit 1; }

echo ""
echo "Building demo-frontend..."
docker build --no-cache -t demo-frontend:latest -f "$DEMO_DIR/Dockerfile" "$DEMO_DIR/"

echo ""
echo "Building demo-backend..."
docker build --no-cache -t demo-backend:latest -f "$DEMO_DIR/Dockerfile.backend" "$DEMO_DIR/"

echo ""
echo "Loading images into kind cluster $KIND_CLUSTER..."
kind load docker-image demo-frontend:latest --name "$KIND_CLUSTER"
kind load docker-image demo-backend:latest --name "$KIND_CLUSTER"

echo ""
echo "=========================================="
echo "✓ Demo images built in kind"
echo "=========================================="
echo ""
echo "Images:"
echo "  - demo-frontend:latest"
echo "  - demo-backend:latest"
echo ""
echo "Next: Deploy to Kubernetes"
echo "  cd k8s-demo && ./02-deploy.sh"
echo ""
