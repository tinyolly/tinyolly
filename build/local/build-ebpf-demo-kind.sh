#!/bin/bash
set -e

# Always use the Colima docker daemon
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

# Build TinyOlly eBPF demo images locally via Colima docker + kind load
# Usage: ./build-ebpf-demo-kind.sh
#
# NOTE: Uses --no-cache for fresh builds

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="$SCRIPT_DIR/../../docker-demo-ebpf"

echo "=========================================="
echo "TinyOlly eBPF Demo - Local kind Build"
echo "=========================================="
echo ""

# Build on the Colima docker daemon, then load into the kind cluster
KIND_CLUSTER="${KIND_CLUSTER:-tinyolly}"
command -v kind >/dev/null || { echo "kind not found (brew install kind)"; exit 1; }
kind get clusters | grep -qx "$KIND_CLUSTER" || { echo "kind cluster '$KIND_CLUSTER' not found: run scripts/kind-up.sh"; exit 1; }

echo ""
echo "Building ebpf-frontend..."
docker build --no-cache -t tinyolly/ebpf-frontend:latest -f "$DEMO_DIR/Dockerfile" "$DEMO_DIR/"

echo ""
echo "Building ebpf-backend..."
docker build --no-cache -t tinyolly/ebpf-backend:latest -f "$DEMO_DIR/Dockerfile.backend" "$DEMO_DIR/"

echo ""
echo "Loading images into kind cluster $KIND_CLUSTER..."
kind load docker-image tinyolly/ebpf-frontend:latest --name "$KIND_CLUSTER"
kind load docker-image tinyolly/ebpf-backend:latest --name "$KIND_CLUSTER"

echo ""
echo "=========================================="
echo "✓ eBPF demo images built in kind"
echo "=========================================="
echo ""
echo "Images:"
echo "  - ebpf-frontend:latest"
echo "  - ebpf-backend:latest"
echo ""
echo "Next: Deploy to Kubernetes"
echo "  cd k8s-demo-ebpf && ./02-deploy.sh"
echo ""
