#!/bin/bash

# TinyOlly Kubernetes Cleanup Script
# Removes all TinyOlly resources from the Kubernetes cluster

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TinyOlly Kubernetes Cleanup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed${NC}"
    echo "Please install kubectl: https://kubernetes.io/docs/tasks/tools/"
    exit 1
fi

# Check if connected to a cluster
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Not connected to a Kubernetes cluster${NC}"
    echo "Please ensure your cluster is running and kubectl is configured properly"
    exit 1
fi

# Get current context
CONTEXT=$(kubectl config current-context)
echo -e "${YELLOW}Current context: ${CONTEXT}${NC}"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if any TinyOlly resources exist
echo -e "${BLUE}Checking for TinyOlly resources...${NC}"
RESOURCES_EXIST=false

if kubectl get deployment tinyolly-otlp-receiver &> /dev/null || \
   kubectl get deployment tinyolly-ui &> /dev/null || \
   kubectl get deployment tinyolly-opamp-server &> /dev/null || \
   kubectl get deployment otel-collector &> /dev/null || \
   kubectl get service tinyolly-otlp-receiver &> /dev/null || \
   kubectl get service tinyolly-ui &> /dev/null || \
   kubectl get service tinyolly-opamp-server &> /dev/null || \
   kubectl get service otel-collector &> /dev/null || \
    kubectl get pvc tinyolly-db &> /dev/null || \
   kubectl get configmap otel-collector-config &> /dev/null || \
   kubectl get configmap otel-supervisor-config &> /dev/null || \
   kubectl get configmap otelcol-templates &> /dev/null; then
    RESOURCES_EXIST=true
fi

if [ "$RESOURCES_EXIST" = false ]; then
    echo -e "${YELLOW}No TinyOlly resources found in the current namespace${NC}"
    echo ""
    echo -e "${GREEN}Nothing to clean up!${NC}"
    exit 0
fi

# Show resources that will be deleted
echo -e "${YELLOW}The following resources will be deleted:${NC}"
echo ""
kubectl get deployments,services,configmaps,pvc 2>/dev/null | grep -E "(tinyolly|otel-collector|tinyolly-db)" || echo "  (checking resources...)"
echo ""

# Confirm deletion
read -p "$(echo -e ${YELLOW}Do you want to proceed with cleanup? [y/N]:${NC} )" -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}Deleting TinyOlly resources...${NC}"
echo ""

# Method 1: Delete using kubectl delete -f on YAML files only
echo -e "${YELLOW}→ Deleting all resources from k8s manifests...${NC}"
kubectl delete -f "$SCRIPT_DIR/tinyolly-ui.yaml" --ignore-not-found=true 2>/dev/null || true
kubectl delete -f "$SCRIPT_DIR/otel-collector.yaml" --ignore-not-found=true 2>/dev/null || true
kubectl delete -f "$SCRIPT_DIR/tinyolly-opamp-server.yaml" --ignore-not-found=true 2>/dev/null || true
kubectl delete -f "$SCRIPT_DIR/tinyolly-otlp-receiver.yaml" --ignore-not-found=true 2>/dev/null || true
kubectl delete -f "$SCRIPT_DIR/tinyolly-sqlite-pvc.yaml" --ignore-not-found=true 2>/dev/null || true
kubectl delete -f "$SCRIPT_DIR/otel-collector-config.yaml" --ignore-not-found=true 2>/dev/null || true
echo ""

# Method 2: Delete by resource names (fallback to ensure everything is deleted)
echo -e "${YELLOW}→ Ensuring all deployments are deleted...${NC}"
kubectl delete deployment tinyolly-otlp-receiver --ignore-not-found=true 2>/dev/null || true
kubectl delete deployment tinyolly-ui --ignore-not-found=true 2>/dev/null || true
kubectl delete deployment tinyolly-opamp-server --ignore-not-found=true 2>/dev/null || true
kubectl delete deployment otel-collector --ignore-not-found=true 2>/dev/null || true

echo -e "${YELLOW}→ Ensuring all services are deleted...${NC}"
kubectl delete service tinyolly-otlp-receiver --ignore-not-found=true 2>/dev/null || true
kubectl delete service tinyolly-ui --ignore-not-found=true 2>/dev/null || true
kubectl delete service tinyolly-opamp-server --ignore-not-found=true 2>/dev/null || true
kubectl delete service otel-collector --ignore-not-found=true 2>/dev/null || true
kubectl delete pvc tinyolly-db --ignore-not-found=true 2>/dev/null || true

echo -e "${YELLOW}→ Ensuring all configmaps are deleted...${NC}"
kubectl delete configmap otel-collector-config --ignore-not-found=true 2>/dev/null || true
kubectl delete configmap otel-supervisor-config --ignore-not-found=true 2>/dev/null || true
kubectl delete configmap otelcol-templates --ignore-not-found=true 2>/dev/null || true

# Wait for pods to terminate
echo ""
echo -e "${BLUE}Waiting for pods to terminate...${NC}"
kubectl wait --for=delete pod -l app=tinyolly-otlp-receiver --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=tinyolly-ui --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=tinyolly-opamp-server --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l app=otel-collector --timeout=60s 2>/dev/null || true

echo ""
echo -e "${BLUE}Verifying cleanup...${NC}"

# Check if any resources still exist
REMAINING_RESOURCES=false
if kubectl get deployment,service,configmap,pvc 2>/dev/null | grep -qE "(tinyolly|otel-collector|tinyolly-db)"; then
    REMAINING_RESOURCES=true
    echo -e "${YELLOW}Warning: Some resources may still exist:${NC}"
    kubectl get deployment,service,configmap,pvc 2>/dev/null | grep -E "(tinyolly|otel-collector|tinyolly-db)" || true
else
    echo -e "${GREEN}✓ All TinyOlly resources have been deleted${NC}"
fi

# Offer to clean up Docker images if using kind
if command -v kind &> /dev/null && [ "$CONTEXT" = "kind-tinyolly" ]; then
    echo ""
    read -p "$(echo -e ${YELLOW}Do you want to remove TinyOlly Docker images from kind node? [y/N]:${NC} )" -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Removing Docker images from kind node...${NC}"
        docker exec tinyolly-control-plane sh -c 'crictl images | grep tinyolly | awk "{print \$1\":\"\$2}" | xargs -r crictl rmi' || true
        echo -e "${GREEN}✓ Docker images removed${NC}"
    fi
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Cleanup complete!${NC}"
echo -e "${BLUE}========================================${NC}"
