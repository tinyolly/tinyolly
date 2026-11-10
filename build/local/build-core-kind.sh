#!/bin/bash
set -e

# Always use the Colima docker daemon
unset DOCKER_TLS_VERIFY DOCKER_HOST DOCKER_CERT_PATH
export DOCKER_CONTEXT="${DOCKER_CONTEXT:-colima-${COLIMA_PROFILE:-tinyolly}}"

# Build TinyOlly core images locally via Colima docker + kind load
# Usage: ./build-core-kind.sh
#
# NOTE: Uses --no-cache for fresh builds

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$SCRIPT_DIR/../../docker"

echo "=========================================="
echo "TinyOlly Core - Local kind Build"
echo "=========================================="
echo ""

# Build on the Colima docker daemon, then load into the kind cluster
KIND_CLUSTER="${KIND_CLUSTER:-tinyolly}"
command -v kind >/dev/null || { echo "kind not found (brew install kind)"; exit 1; }
kind get clusters | grep -qx "$KIND_CLUSTER" || { echo "kind cluster '$KIND_CLUSTER' not found: run scripts/kind-up.sh"; exit 1; }

# Build shared Python base image first
echo ""
echo "Building python-base..."
docker build --no-cache -t tinyolly/python-base:latest \
  -f "$DOCKER_DIR/dockerfiles/Dockerfile.tinyolly-python-base" \
  "$DOCKER_DIR/"

echo ""
echo "Building ui..."
docker build --no-cache -t tinyolly/ui:latest \
  -f "$DOCKER_DIR/dockerfiles/Dockerfile.tinyolly-ui" \
  --build-arg APP_DIR=tinyolly-ui \
  "$DOCKER_DIR/"

echo ""
echo "Building otlp-receiver..."
docker build --no-cache -t tinyolly/otlp-receiver:latest \
  -f "$DOCKER_DIR/dockerfiles/Dockerfile.tinyolly-otlp-receiver" \
  --build-arg APP_DIR=tinyolly-otlp-receiver \
  "$DOCKER_DIR/"

echo ""
echo "Building opamp-server..."
docker build --no-cache -t tinyolly/opamp-server:latest \
  -f "$DOCKER_DIR/dockerfiles/Dockerfile.tinyolly-opamp-server" \
  "$DOCKER_DIR/"

echo ""
echo "Building otel-supervisor..."
docker build --no-cache -t tinyolly/otel-supervisor:latest \
  -f "$DOCKER_DIR/dockerfiles/Dockerfile.otel-supervisor" \
  "$DOCKER_DIR/"

echo ""
echo "Loading images into kind cluster $KIND_CLUSTER..."
kind load docker-image tinyolly/python-base:latest --name "$KIND_CLUSTER"
kind load docker-image tinyolly/ui:latest --name "$KIND_CLUSTER"
kind load docker-image tinyolly/otlp-receiver:latest --name "$KIND_CLUSTER"
kind load docker-image tinyolly/opamp-server:latest --name "$KIND_CLUSTER"
kind load docker-image tinyolly/otel-supervisor:latest --name "$KIND_CLUSTER"

echo ""
echo "=========================================="
echo "✓ Core images built in kind"
echo "=========================================="
echo ""
echo "Images:"
echo "  - tinyolly/python-base:latest"
echo "  - tinyolly/ui:latest"
echo "  - tinyolly/otlp-receiver:latest"
echo "  - tinyolly/opamp-server:latest"
echo "  - tinyolly/otel-supervisor:latest"
echo ""
echo "Next: Deploy to Kubernetes"
echo "  cd k8s && ./02-deploy-tinyolly.sh"
echo ""
