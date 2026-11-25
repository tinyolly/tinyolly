#!/bin/bash

# Safety: only operate on the local kind cluster (see scripts/lib/kubectx.sh)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../scripts/lib" && pwd)/kubectx.sh" && require_kind_context || { return 1 2>/dev/null || exit 1; }

# Cleanup eBPF Demo from Kubernetes

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}Cleaning up eBPF demo...${NC}"
echo ""

# Delete deployments and services
kubectl delete -f "$SCRIPT_DIR/ebpf-frontend.yaml" 2>/dev/null
kubectl delete -f "$SCRIPT_DIR/ebpf-backend.yaml" 2>/dev/null
kubectl delete -f "$SCRIPT_DIR/ebpf-agent.yaml" 2>/dev/null

echo ""
echo -e "${GREEN}✓ eBPF demo cleaned up${NC}"
echo ""
